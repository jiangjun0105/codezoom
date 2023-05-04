"""Logging module for Auto-GPT."""
from __future__ import annotations

import logging
import sys
from enum import Enum
from pathlib import Path

import loguru
from autogpt.config import Config
from colorama import Fore, Style

CFG = Config()
# TODO: Make this configurable.
LOG_FILE_PATH = Path("~/gpt-developer/.cache/chatbot.log").expanduser()

BOT_SPEAK = 25
logging.addLevelName(BOT_SPEAK, "BOT_SPEAK")


class LogOutput(str, Enum):
    """Enum for defining where a log message should be outputted."""

    MAIN = "main"
    FILE = "file"
    ALL = "all"


class SpeakerType(str, Enum):
    HUMAN = "human"
    BOT = "bot"
    SYSTEM = "system"


def print_with_color(color: str, text: str, **kwargs) -> None:
    """Prints text with color."""
    print(f"{color}{text}{Style.RESET_ALL}", **kwargs)


def bot_typer(message: loguru.Message) -> None:
    """Loguru sink that allows to print stream messages from bots."""
    color = message.record["extra"].get("color", Fore.WHITE)
    print_with_color(color=color, text=message, end="", flush=True)


def log_filter(desired: SpeakerType) -> bool:
    """Loguru filter that allows to print stream messages from bots."""

    def filter(record: loguru.Record) -> bool:
        """Loguru filter that allows to print stream messages from bots."""
        return record["extra"].get("speaker_type", SpeakerType.SYSTEM) == desired

    return filter


def bot_fomatter(record: loguru.Record) -> str:
    """Formatter allowing custom line terminator for bot messages.
    NOTE: It cannot handle variables which shouldn't exist in bot response.
    """
    end = record["extra"].get("end", "\n")
    message = record["message"]
    return f"{message}{end}"


loguru.logger.remove()
loguru.logger.add(sys.stderr, level="DEBUG", filter=log_filter(SpeakerType.SYSTEM))
loguru.logger.add(bot_typer, filter=log_filter(SpeakerType.BOT), format=bot_fomatter)
