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


def log_filter(desired: SpeakerType) -> bool:
    """Loguru filter that allows to print stream messages from bots."""

    def filter(record: loguru.Record) -> bool:
        """Loguru filter that allows to print stream messages from bots."""
        return record["extra"].get("speaker_type", SpeakerType.SYSTEM) == desired

    return filter


def bot_fomatter(record: loguru.Record) -> str:
    """Formatter allowing custom line terminator and color."""
    color = record["extra"].get("color", "white")
    end = record["extra"].get("end", "\n")
    return f"<{color}>{{message}}</>{end}{{exception}}"


loguru.logger.remove()
# TODO: Make level configurable.
# loguru.logger.add(sys.stderr, level="DEBUG", filter=log_filter(SpeakerType.SYSTEM))
loguru.logger.add(
    LOG_FILE_PATH, level="DEBUG", filter=log_filter(SpeakerType.SYSTEM)
)
loguru.logger.add(
    sys.stdout, filter=log_filter(SpeakerType.BOT), format=bot_fomatter
)
# loguru.logger.add(LOG_FILE_PATH, filter=log_filter(SpeakerType.BOT), format=bot_fomatter)
