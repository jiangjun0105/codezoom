# %%
from __future__ import annotations

import abc
import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from loguru import logger

from codebase_analyzer import prompts, tools
from codebase_analyzer.chatbot import BotModel, Chatbot
from codebase_analyzer.commands import ask_function, execute_function, parse_response
from codebase_analyzer.embedding import embed_codebase
from codebase_analyzer.logs import SpeakerType
from codebase_analyzer.parser import (
    extract_code_info,
    load_cached_codebase_info,
    load_raw_code,
)
from codebase_analyzer.tools import Tool, ToolSet


# %%
def generate_bot_hash(bot_type: Callable, **kwargs):
    kwargs["bot_type"] = bot_type.__name__
    sorted_kwargs = dict(sorted(kwargs.items()))
    kwargs_bytes = json.dumps(sorted_kwargs).encode()
    return hashlib.sha256(kwargs_bytes).hexdigest()


# %%
class BaseBot(abc.ABC):
    def __init__(
        self, name: str, model: BotModel, system_prompt: str, **kwargs
    ) -> None:
        self.bot = Chatbot(
            name=name,
            model=model,
            system_prompt=system_prompt,
            **kwargs,
        )

    @property
    def profile(self) -> BotProfile:
        return BotProfile(bot_type=self.__class__, **self.__dict__)

    def reset(self) -> None:
        pass

    def ask(self, prompt: str, **kwargs: Any) -> str:
        return self.bot.ask(prompt=prompt, asked_by=self.name, **kwargs)


# %%
class BotSet(set):
    def __init__(self, *bots: BotProfile) -> None:
        super().__init__(bots)

    @property
    def instructions(self) -> str:
        return "\n".join([f"{b.name}: {b.instruction}" for b in self])


# %%
class ReActBot(BaseBot):
    def __init__(self, name, model, system_prompt, **kwargs) -> None:
        super().__init__(
            name=name, model=model, system_prompt=system_prompt, **kwargs
        )
        self.max_iteration = 10
        self.tool_set = ToolSet()
        self.sub_bots = BotSet()

    def ask(self, prompt: str, reset: bool = True, **kwargs: Any) -> str:
        """Main loop for interaction between AI bots on codebase questions."""
        p = prompts.question_prompt(question=prompt)

        iteration = self.max_iteration
        while iteration > 0:
            iteration -= 1
            response = self.bot.ask(prompt=p, **kwargs)
            if re.search(r"^Answer:.*", response, re.MULTILINE):
                break
            try:
                cmds = parse_response(response=response)
                tool_res = execute_function(
                    function_call=cmds["Tool"], function_map=self.tool_set
                )
                bot_res = BOT_MANAGER.route(cmds["Bot"], asked_by=self.name)
                p = f"Tool: {tool_res}\nBot: {bot_res}\n"
            except AttributeError:
                self.bot.logger.error(
                    f"No command or answer found in response {response}."
                )
                break
        if reset:
            self.bot.reset()
        return response


# %%
class CacheManager:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_name = "index.csv"
        self.index = self.load_index()

    def load_index(self) -> pd.DataFrame:
        index_path = self.cache_dir / self.index_name
        if index_path.exists():
            return pd.read_csv(index_path).set_index("Unnamed: 0")
        else:
            return pd.DataFrame()

    def _get_cache(self, hash: str) -> str | None:
        if hash in self.index:
            return self.cache_dir / self.index.loc[hash, "file_name"]
        else:
            return None

    def get_cache(self, **kwargs) -> str | None:
        hash = generate_bot_hash(**kwargs)
        return self._get_cache(hash)

    def save_cache(self, hash: str, content: str, extension: str = "txt") -> None:
        if hash in self.index:
            logger.warning(f"Cache for {hash} already exists.")
            return
        file_name = Path(hash).with_suffix(extension)
        with open(self.cache_dir / file_name, "w") as f:
            f.write(content)
        update_time = pd.Timestamp.now()
        self.index.loc[hash] = [file_name, update_time]

    def save_index(self) -> None:
        self.index.to_csv(self.cache_dir / self.index_name)


# %%
class BotManager:
    @dataclass
    class BotInfo:
        type: str
        bot: BaseBot
        created_at: pd.Timestamp
        last_active_at: pd.Timestamp
        sent_num: int
        got_num: int

    def __init__(self) -> None:
        self.bots = dict()

    def register_bot(self, bot_type: Callable, **kwargs) -> None:
        hash = generate_bot_hash(bot_type=bot_type, **kwargs)
        if hash in self.bots:
            logger.warning(f"Bot {hash} already exists.")
            return hash
        bot_info = self.new_bot_info(bot_type=bot_type, **kwargs)
        self.bots[hash] = bot_info
        logger.info(f"Registered {bot_info.type} hash: {hash}")
        logger.debug(f"Registered bot info: {bot_info}, kwargs: {kwargs}")
        return hash

    def new_bot_info(self, bot_type: Callable, **kwargs) -> BotInfo:
        bot = bot_type(**kwargs)
        return self.BotInfo(
            type=bot_type.__name__,
            bot=bot,
            created_at=pd.Timestamp.now(),
            last_active_at=pd.Timestamp.now(),
            ingress_num=0,
            engress_num=0,
        )

    def delete_bot(self, hash: str) -> None:
        if hash not in self.bots:
            logger.warning(f"Bot {hash} not found.")
            return
        logger.info(f"Deleted bot {hash}")
        logger.debug(f"Deleted bot info: {self.bots[hash]}")
        del self.bots[hash]

    def get_bot_by_kwargs(self, **kwargs: Any) -> BaseBot:
        hash = generate_bot_hash(**kwargs)
        return self.get_bot_by_hash(hash)

    def get_bot_by_hash(self, hash: str) -> BaseBot:
        if hash not in self.bots:
            raise KeyError(f"Bot {hash} not found.")
        return self.bots[hash]

    def route(self, prompt: str, from_bot: BotProfile, to_bot: BotProfile) -> str:
        from_bot = self.get_bot_by_hash(from_bot.hash)
        to_bot = self.get_bot_by_hash(to_bot.hash)
        from_bot.sent_num += 1
        to_bot.got_num += 1
        try:
            mgs = to_bot.ask(prompt=prompt)
        except Exception as e:
            logger.error(f"Error when routing from {from_bot} to {to_bot}")
            raise e
        from_bot.last_active_at = pd.Timestamp.now()
        to_bot.last_active_at = pd.Timestamp.now()
        return mgs


class BotProfile:
    """Defines a certain bot that can be used by other bots."""

    def __init__(self, bot_type: BaseBot, **bot_kwargs: Any) -> None:
        self.type = bot_type
        self.kwargs = bot_kwargs
        self.hash = generate_bot_hash(bot_type=bot_type, **bot_kwargs)


BOT_MANAGER = BotManager()

# %%
class CodebaseBot(ReActBot):
    def __init__(self, repo_path: str, cache_path: str, **kwargs) -> None:
        self.profile = BotProfile(
            bot_type=CodebaseBot, repo_path=repo_path, cache_path=cache_path
        )
        self.cache_path = Path(cache_path).expanduser()
        self.repo_path = Path(repo_path).expanduser()
        # self.raw_codebase = load_raw_code(self.repo_path)
        # self.codebase_info = self.load_codebase_info(self.cache_path)

        self.tool_set = ToolSet(
            tools.get_directory_tree.update(root_path=self.repo_path),
            tools.get_file_content.update(root_path=self.repo_path),
            # tools.get_relevant_functions.update(codebase_info=self.codebase_info),
        )
        self.sub_bots = BotSet(
            BotProfile(bot_type=FileBot, repo_path=self.repo_path),
        )

        super().__init__(
            name="codebase_bot",
            model=BotModel.GPT_4,
            system_prompt=self.system_prompt(self.tool_set, self.sub_bots),
            **kwargs,
        )

    def system_prompt(self, tool_set: ToolSet, sub_bots: BotSet, language="python"):
        return (
            f"You are an codebase analyzer bot. Human will ask you questions about a {language} codebase. "
            f"The codebase is too large to read, but you can use commands to get necessary info.\n"
            + prompts.tool_instruction(tool_set.instructions)
            + prompts.sub_bot_instruction(sub_bots.instructions)
            + prompts.response_format()
        )

    def load_codebase_info(self, cache: str) -> tuple[str, pd.DataFrame]:
        if cache:
            codebase_info = load_cached_codebase_info(cache)
        else:
            codebase_info = extract_code_info(raw_code=self.raw_codebase)
            codebase_info = embed_codebase(codebase_info)
        return codebase_info

    def save_cache(self) -> None:
        """Save the codebase info to cache."""
        # self.codebase_info.to_csv(self.cache_path)
        logger.info(f"Saved codebase info to {self.cache_path}")


class FileBot(ReActBot):
    name = "file_bot"
    instruction = """
- file_bot.ask(file_path="<file_path_relative_to_repo_root>", prompt="<context_and_question_or_request>")
    to ask a question about a specific file in the codebase.
    E.g. file_bot.ask(path="src/codebase_analyzer/bots.py", prompt="What is the codebase bot?")
"""

    def __init__(self, file_path: str | Path, repo_path: Path) -> None:
        self.repo_path = Path(repo_path).expanduser()
        self.file_path = Path(file_path)
        self.full_path = self.repo_path / self.file_path
        self.file_content = load_raw_code(self.full_path)
        # self.code_info = self.get_code_info(self.full_path)
        self.file_summary = None
        super().__init__(
            name=f"file_bot_{self.file_path}",
            model=BotModel.GPT_3_5_TURBO,
            system_prompt=self.system_prompt(),
        )
        self.tool_set = ToolSet(
            tools.get_relevant_functions.update(codebase_info=self.file_summary),
        )
        # self.sub_bots =

    def system_prompt(self) -> str:
        return (
            f"You are an AI bot managing the file {self.file_path} which belongs to codebase {self.repo_path}. "
            f"You will be asked questions about the codebase which might be related or unrelated to the file. "
            f"Please answer or provide relevant info based on your knowledge about the file as well as general programming knowledge. "
            f"If the question is unrelated to the file, please directly say it."
            + prompts.response_format()
        )


class FunctionBot(ReActBot):
    def __init__(self, file_path: str | Path, function_name: str, code: str) -> None:
        self.file_name = Path(file_path).expanduser()
        self.function_name = function_name
        self.code = code
        super().__init__(
            name=f"function_bot_{self.function_name}",
            model=BotModel.GPT_3_5_TURBO,
            system_prompt=self.system_prompt(),
        )

    def system_prompt(self) -> str:
        return (
            f"You are an AI bot managing the function {self.function_name} in file {self.file_name} belonging to a codebase. "
            f"You will be asked questions about the codebase which might be related or unrelated to the function. "
            f"Please answer or provide relevant info based on your knowledge about the function as well as general programming knowledge. "
            f"If the question is unrelated to the function, please directly say it."
        )


class CodingBot:
    def __init__(self) -> None:
        self.bot = Chatbot(
            name="coding_bot",
            model=BotModel.GPT_3_5_TURBO,
            system_prompt=prompts.coding_bot_system(),
        )

    def ask(self, prompt: str, **kwargs) -> str:
        return f"Being asked to {prompt}"


class MasterBot:
    def __init__(self, bot_map) -> None:
        self.bot = Chatbot(
            name="master_bot",
            model=BotModel.GPT_4,
            system_prompt=prompts.master_bot_system(),
        )
        self.bot_map = bot_map

    def ask(self, prompt: str, **kwargs) -> str:
        # NOTE: Only allow one round interaction for now.
        r = self.bot.ask(prompt=prompt, **kwargs)
        answer = parse_response(response=r, function_map=self.bot_map)
        if answer:
            # TODO: Test if I can just return answer
            self.bot.add_to_conversation(answer, "system")
        return answer


# %%
