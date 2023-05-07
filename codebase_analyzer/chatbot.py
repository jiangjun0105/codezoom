"""Interfaces to the GPT API or ChatGPT webapp"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

import openai
import tiktoken
from colorama import Fore
from loguru import logger
from yaml import safe_load

from codebase_analyzer.logs import SpeakerType


def get_access_token():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["access_token"]


def get_api_key():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["api_key"]


openai.api_key = get_api_key()


class BotModel(str, Enum):
    """Enum for defining which model to use for a chatbot."""

    GPT_3_5_TURBO = "gpt-3.5-turbo"
    GPT_4 = "gpt-4"
    GPT_4_32K = "gpt-4-32k"  # Unavailable


@dataclass
class APIParams:
    """Fixed parameters for the OpenAi API call."""

    model: str = BotModel.GPT_3_5_TURBO
    temperature: float = 0.0
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    n: int = 1
    stream: bool = True
    stop: list[str] | None = None


class Chatbot:
    """
    Chatbot using official ChatGPT API.
    Adjusted based on revChatGPT.V3.Chatbot by acheong08.
    """

    def __init__(
        self,
        *,
        name: str,
        timeout: float = None,
        max_tokens: int = 31000,  # Adjusted dynamically
        truncate_limit: int = 31000,  # Adjusted based on model
        system_prompt: str = "",
        name_color: Fore = "blue",
        msg_color: Fore = "white",
        **api_kwargs,  # Other API params
    ) -> None:
        """Initialize the Chatbot."""
        self.name = name
        self.api_params = APIParams(**api_kwargs)
        self.system_prompt: str = system_prompt
        self.max_tokens = max_tokens
        self.truncate_limit = truncate_limit
        self.timeout: float = timeout
        self.conversation: dict[str, list[dict]] = {
            "default": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
            ],
        }
        self.name_color = name_color
        self.msg_color = msg_color
        self.total_sent_token = 0
        self.total_got_token = 0
        self.logger = self._get_bot_logger(name)
        self.logger.info(f"Initialized {name} with {self.api_params.model}")

        self.adjust_params(self.api_params.model)
        if self.get_token_count("default") > self.max_tokens:
            raise ValueError("System prompt is too long")

    def _get_bot_logger(self, name: str) -> logger:
        return logger.bind(speaker=name)

    def adjust_params(self, model) -> None:
        if model == "gpt-3.5-turbo":
            self.max_tokens = min(self.max_tokens, 4000)
            self.truncate_limit = min(self.truncate_limit, 3500)
            self.sent_price: float = 0.002 / 1000
            self.got_price: float = 0.002 / 1000
        elif model == "gpt-4":
            self.max_tokens = min(self.max_tokens, 7000)
            self.truncate_limit = min(self.truncate_limit, 6500)
            self.sent_price: float = 0.03 / 1000
            self.got_price: float = 0.06 / 1000
        elif model == "gpt-4-32k":
            self.max_tokens = min(self.max_tokens, 31000)
            self.truncate_limit = min(self.truncate_limit, 30500)
            self.sent_price: float = 0.06 / 1000
            self.got_price: float = 0.12 / 1000
        else:
            raise NotImplementedError(f"Unsupported model {model}")

    def speak(self, speak_to: str, stream: Iterator[str]) -> None:
        bot_logger = self.logger.bind(speaker_type=SpeakerType.BOT)
        bot_logger.info(
            f"{self.name.upper()} -> {speak_to.upper()}:\n",
            color=self.name_color,
            end="",
        )
        try:
            for s in stream:
                bot_logger.info(s, color=self.msg_color, end="")
        except RuntimeError:
            bot_logger.info("")
            self.logger.error(
                f"RuntimeError: Bot {self.name} did not respond anything."
            )
        bot_logger.info("\n")

    def add_to_conversation(
        self,
        message: str,
        role: str,
        convo_id: str = "default",
    ) -> None:
        """
        Add a message to the conversation
        """
        self.conversation[convo_id].append({"role": role, "content": message})

    def truncate_conversation(self, convo_id: str = "default") -> None:
        """
        Truncate the conversation
        """
        while True:
            if (
                self.get_token_count(convo_id) > self.truncate_limit
                and len(self.conversation[convo_id]) > 1
            ):
                # Don't remove the first message
                self.conversation[convo_id].pop(1)
            else:
                break

    # https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
    def get_token_count(self, convo_id: str = "default") -> int:
        """
        Get token count
        """
        if self.api_params.model not in set(BotModel):
            raise NotImplementedError(f"Unsupported model {self.api_params.model}")

        tiktoken.model.MODEL_TO_ENCODING["gpt-4"] = "cl100k_base"

        encoding = tiktoken.encoding_for_model(self.api_params.model)

        num_tokens = 0
        for message in self.conversation[convo_id]:
            # every message follows <im_start>{role/name}\n{content}<im_end>\n
            num_tokens += 5
            for key, value in message.items():
                if not value:
                    continue
                # print("debug", key, value)
                num_tokens += len(encoding.encode(value))
                if key == "name":  # if there's a name, the role is omitted
                    num_tokens += 5  # role is always required and always 1 token
        num_tokens += 5  # every reply is primed with <im_start>assistant
        return num_tokens

    def get_max_tokens(self, convo_id: str) -> int:
        """
        Get max tokens
        """
        return self.max_tokens - self.get_token_count(convo_id)

    def log_sent_messages(self) -> None:
        """Log the full list of sent messages"""
        self.logger.info(f"\nSent to {self.name}: ")
        for m in self.conversation["default"]:
            self.logger.info(f"{m['role']}: {m['content']}")

    def ask_stream(
        self,
        prompt: str,
        convo_id: str = "default",
    ) -> Iterator[str]:
        """
        Ask a question
        """
        self.logger.info(f"\nSending to {self.name}: {prompt}")
        # Make conversation if it doesn't exist
        if convo_id not in self.conversation:
            self.reset(convo_id=convo_id, system_prompt=self.system_prompt)
        self.add_to_conversation(prompt, "user", convo_id=convo_id)
        self.truncate_conversation(convo_id=convo_id)

        # Get response
        sent_token = self.get_token_count(convo_id)
        self.total_sent_token += sent_token
        self.logger.critical(
            f"Used/max tokens: {sent_token}/{self.max_tokens}= {self.get_token_count(convo_id)/self.max_tokens:.2%}"
        )
        response = openai.ChatCompletion.create(
            messages=self.conversation[convo_id],
            max_tokens=self.get_max_tokens(convo_id),
            **asdict(self.api_params),
        )

        # Parse response
        full_response = []
        response_role: str | None = None
        for chunk in response:
            choices = chunk["choices"]
            if not choices:
                continue
            delta = choices[0].get("delta")
            if not delta:  # End of stream
                continue
            if "role" in delta:  # Role token
                response_role = delta["role"]
            if "content" in delta:  # Content token
                # To prevent single { or } error
                content = delta["content"].replace("{", "{{").replace("}", "}}")
                full_response.append(content)
                yield content

        full_response = "".join(full_response)
        self.total_got_token += len(full_response)
        self.logger.critical(
            f"Total sent: {self.total_sent_token}, total got: {self.total_got_token}, total cost: {self.current_cost()}$"
        )
        self.logger.info(f"\nReceived from {self.name}: {full_response}")
        self.add_to_conversation(full_response, response_role, convo_id=convo_id)

    def current_cost(self) -> float:
        """Get total cost (dollars) by this bot till now."""
        return (
            self.total_got_token * self.got_price
            + self.total_sent_token * self.sent_price
        )

    def ask(
        self,
        prompt: str,
        asked_by: str,
        convo_id: str = "default",
        **kwargs,
    ) -> str:
        """
        Non-streaming ask
        """
        self.speak(
            speak_to=asked_by,
            stream=self.ask_stream(prompt=prompt, convo_id=convo_id, **kwargs),
        )
        return self.conversation[convo_id][-1]["content"]

    def rollback(self, n: int = 1, convo_id: str = "default") -> None:
        """
        Rollback the conversation
        """
        for _ in range(n):
            self.conversation[convo_id].pop()

    def reset(self, convo_id: str = "default", system_prompt: str = None) -> None:
        """
        Reset the conversation
        """
        self.conversation[convo_id] = [
            {"role": "system", "content": system_prompt or self.system_prompt},
        ]
