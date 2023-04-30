"""Interfaces to the GPT API or ChatGPT webapp"""

from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Union

import openai
from revChatGPT.V1 import Chatbot as ChatGPT
from revChatGPT.V3 import Chatbot as GPTAPI
from yaml import safe_load

from codebase_analyzer.prompts import init_system_prompt

Chatbot = Union[ChatGPT, GPTAPI]


def get_access_token():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["access_token"]


def get_api_key():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["api_key"]


openai.api_key = get_api_key()

chatgpt4_main = ChatGPT(
    config={
        "access_token": get_access_token(),
        "conservation_id": "9033621f-f523-4580-a115-5cdc1b8cd410",
        "model": "gpt-4",
    }
)
chatgpt4_sub = ChatGPT(
    config={
        "access_token": get_access_token(),
        "conservation_id": "03728c4d-bfa1-463e-b3d2-7345cdea0aab",
        "model": "gpt-4",
    }
)
chatgpt3 = ChatGPT(
    config={
        "access_token": get_access_token(),
        "parent_id": "64bc082d-7db8-419c-94c6-ed1766b6177e",
        "conversation_id": "df1f9013-06d0-40b9-970a-6b14e1d410bb",
    }
)


gpt3_bot = GPTAPI(
    api_key=get_api_key(),
    engine="gpt-3.5-turbo",
    temperature=0,
    system_prompt=init_system_prompt(),
)

gpt4_bot = GPTAPI(
    api_key=get_api_key(),
    engine="gpt-4",
    temperature=0,
    # max_tokens=4000,
    system_prompt=init_system_prompt(),
)


def ask_chagpt(prompt: str, chatbot: Chatbot) -> str:
    """Ask a question to the ChatGPT and return the response."""
    print("ChatGPT:\n")
    last_len = 0
    response = chatbot.ask(prompt)

    for data in response:
        message = data["message"]
        print(message[last_len:], end="", flush=True)
        last_len = len(message)
    print()
    return message


def ask_gptapi(prompt: str, chatbot: GPTAPI) -> str:
    """Ask GPT API bot a question and stream the response."""
    full_response = []
    for r in chatbot.ask_stream(prompt):
        print(r, end="", flush=True)
        full_response.append(r)
    print()
    return "".join(full_response)
