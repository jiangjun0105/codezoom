# %%
from pathlib import Path
from time import sleep

import openai
from revChatGPT.V1 import Chatbot
from yaml import safe_load


def get_access_token():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["access_token"]


def get_api_key():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["api_key"]


openai.api_key = get_api_key()

chatgpt4_main = Chatbot(
    config={
        "access_token": get_access_token(),
        "conservation_id": "9033621f-f523-4580-a115-5cdc1b8cd410",
        "model": "gpt-4",
    }
)
chatgpt4_sub = Chatbot(
    config={
        "access_token": get_access_token(),
        "conservation_id": "03728c4d-bfa1-463e-b3d2-7345cdea0aab",
        "model": "gpt-4",
    }
)
chatgpt3 = Chatbot(
    config={
        "access_token": get_access_token(),
        "parent_id": "64bc082d-7db8-419c-94c6-ed1766b6177e",
        "conversation_id": "df1f9013-06d0-40b9-970a-6b14e1d410bb",
    }
)


def ask_chatbot(prompt: str, chatbot: Chatbot) -> str:
    """Ask a question to the chatbot and return the response."""
    # print(f"User: {prompt}")
    print("Chatbot:\n")
    last_len = 0
    retry = 5

    while retry > 0:
        retry -= 1
        try:
            response = chatbot.ask(prompt)
        except Exception as e:
            print(f"Exception: {e}")
            print(f"HTTPError: Retrying... will retry {retry} times.")
            sleep(1)

    for data in response:
        message = data["message"]
        print(message[last_len:], end="", flush=True)
        last_len = len(message)
    print()
    return message
