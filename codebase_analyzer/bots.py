from __future__ import annotations

import re
from enum import Enum
from functools import partial
from pathlib import Path

import pandas as pd
from loguru import logger

from codebase_analyzer import prompts, tools
from codebase_analyzer.chatbot import BotModel, Chatbot
from codebase_analyzer.commands import ask_function, parse_response, search_keyword
from codebase_analyzer.embedding import embed_codebase
from codebase_analyzer.logs import SpeakerType
from codebase_analyzer.parser import (
    extract_code_info,
    load_cached_codebase_info,
    load_raw_code,
)
from codebase_analyzer.tools import Tool, ToolSet


class CodebaseBot:
    def __init__(self, repo: str, cache: str, **kwargs) -> None:
        self.cache_path = Path(cache).expanduser()
        self.raw_codebase = load_raw_code(repo)
        self.codebase_info = self.load_codebase_info(cache)
        self.max_iteration = 6

        self.tool_set = ToolSet(
            tools.get_relevant_functions.update(codebase_info=self.codebase_info),
        )

        self.bot = Chatbot(
            name="codebase_bot",
            model=BotModel.GPT_4,
            system_prompt=self.system_prompt(self.tool_set),
            **kwargs,
        )

    def system_prompt(self, tool_set: ToolSet, language="python"):
        return (
            f"You are an codebase analyzer bot. Human will ask you questions about a {language} codebase. "
            f"The codebase is too large to read, but you can use commands to get necessary info.\n"
            + prompts.command_instruction(tool_set.prompts)
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
        self.codebase_info.to_csv(self.cache_path)
        logger.info(f"Saved codebase info to {self.cache_path}")

    def ask(self, prompt: str, **kwargs) -> str:
        """Main loop for interaction between AI bots on codebase questions."""
        p = prompts.question_prompt(question=prompt)

        max_iteration = self.max_iteration
        while max_iteration > 0:
            max_iteration -= 1
            response = self.bot.ask(prompt=p, **kwargs)
            if re.search(r"^Answer:.*", response, re.MULTILINE):
                break
            try:
                p = "Command return:\n" + parse_response(
                    response=response, function_map=self.tool_set
                )
            except AttributeError:
                self.bot.logger.error(
                    "No command or answer found in response, try to remind it by sending the response format again."
                )
                break
        self.bot.reset()
        return response


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
