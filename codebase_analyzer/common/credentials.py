from pathlib import Path

import openai
from yaml import safe_load


def get_access_token():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["access_token"]


def get_api_key():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["api_key"]


openai.api_key = get_api_key()
