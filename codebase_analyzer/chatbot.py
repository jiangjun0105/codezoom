"""Interfaces to the GPT API or ChatGPT webapp"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from time import sleep
from typing import Union

import openai
import tiktoken
from colorama import Fore, Style
from loguru import logger
from yaml import safe_load

from codebase_analyzer import prompts
from codebase_analyzer.logs import LogOutput, SpeakerType


def get_access_token():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["access_token"]


def get_api_key():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["api_key"]


openai.api_key = get_api_key()


class Chatbot:
    """
    Chatbot using official ChatGPT API.
    Adjusted based on revChatGPT.V3.Chatbot by acheong08.
    """

    def __init__(
        self,
        name: str,
        engine: str = "gpt-3.5-turbo",
        timeout: float = None,
        max_tokens: int = None,
        temperature: float = 0,
        top_p: float = 1.0,
        presence_penalty: float = 0.0,
        frequency_penalty: float = 0.0,
        reply_count: int = 1,
        truncate_limit: int = None,
        system_prompt: str = "",
        outputs=None,
        name_color: Fore = "blue",
        msg_color: Fore = "white",
    ) -> None:
        """Initialize the Chatbot."""
        self.name = name
        self.engine: str = engine
        self.system_prompt: str = system_prompt
        self.max_tokens: int = max_tokens or (
            31000 if engine == "gpt-4-32k" else 7000 if engine == "gpt-4" else 4000
        )
        self.truncate_limit: int = truncate_limit or (
            30500 if engine == "gpt-4-32k" else 6500 if engine == "gpt-4" else 3500
        )
        self.temperature: float = temperature
        self.top_p: float = top_p
        self.presence_penalty: float = presence_penalty
        self.frequency_penalty: float = frequency_penalty
        self.reply_count: int = reply_count
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
        self.outputs = outputs or [LogOutput.MAIN, LogOutput.FILE]
        self.logger = self._get_bot_logger(name)
        self.logger.info(f"Initialized {name} with {engine}")

        if self.get_token_count("default") > self.max_tokens:
            raise ValueError("System prompt is too long")

    def _get_bot_logger(self, name: str) -> logger:
        return logger.bind(speaker=name)

    def speak(self, stream: Iterator[str]) -> None:
        bot_logger = self.logger.bind(speaker_type=SpeakerType.BOT)
        bot_logger.info(f"{self.name}: ", color=self.name_color, end="")
        try:
            for s in stream:
                bot_logger.info(s, color=self.msg_color, end="")
        except RuntimeError:
            bot_logger.info("")
            self.logger.error(
                f"RuntimeError: Bot {self.name} did not respond anything."
            )
        bot_logger.info("")

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
        if self.engine not in [
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-0301",
            "gpt-4",
            "gpt-4-0314",
            "gpt-4-32k",
            "gpt-4-32k-0314",
        ]:
            raise NotImplementedError(f"Unsupported engine {self.engine}")

        tiktoken.model.MODEL_TO_ENCODING["gpt-4"] = "cl100k_base"

        encoding = tiktoken.encoding_for_model(self.engine)

        num_tokens = 0
        for message in self.conversation[convo_id]:
            # every message follows <im_start>{role/name}\n{content}<im_end>\n
            num_tokens += 5
            for key, value in message.items():
                if not value:
                    continue
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
        role: str = "user",
        convo_id: str = "default",
        **kwargs,
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
        response = openai.ChatCompletion.create(
            model=self.engine,
            messages=self.conversation[convo_id],
            stream=True,
            temperature=kwargs.get("temperature", self.temperature),
            top_p=kwargs.get("top_p", self.top_p),
            presence_penalty=kwargs.get("presence_penalty", self.presence_penalty),
            frequency_penalty=kwargs.get(
                "frequency_penalty", self.frequency_penalty
            ),
            n=kwargs.get("n", self.reply_count),
            user=role,
            max_tokens=self.get_max_tokens(convo_id),
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
        self.logger.info(f"\nReceived from {self.name}: {full_response}")
        self.add_to_conversation(full_response, response_role, convo_id=convo_id)

    def ask(
        self,
        prompt: str,
        role: str = "user",
        convo_id: str = "default",
        **kwargs,
    ) -> str:
        """
        Non-streaming ask
        """
        self.speak(
            self.ask_stream(prompt=prompt, role=role, convo_id=convo_id, **kwargs)
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


search_bot = Chatbot(
    name="search_bot",
    name_color="yellow",
    engine="gpt-3.5-turbo",
    system_prompt=prompts.search_bot_system(),
)

function_bot = Chatbot(
    name="function_bot",
    name_color="yellow",
    engine="gpt-3.5-turbo",
    system_prompt=prompts.function_bot_system(),
)

summary_bot = Chatbot(
    name="summary_bot",
    name_color="yellow",
    engine="gpt-3.5-turbo",
    system_prompt=prompts.summary_bot_system(),
)

main_bot = Chatbot(
    name="main_bot",
    engine="gpt-4",
    system_prompt=prompts.main_bot_system(),
)
