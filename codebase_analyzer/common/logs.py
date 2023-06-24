from __future__ import annotations

import logging
import sys
from enum import Enum
from pathlib import Path

import loguru
from autogpt.config import Config

CFG = Config()
# TODO: Make this configurable.
LOG_FILE_PATH = Path("~/gpt-developer/.cache/chatbot.log").expanduser()


class LogOutput(str, Enum):
    """Enum for defining where a log message should be outputted."""

    MAIN = "main"
    FILE = "file"
    ALL = "all"


class SpeakerType(str, Enum):
    HUMAN = "human"
    BOT = "bot"
    SYSTEM = "system"


def log_filter(desired: SpeakerType | set[SpeakerType]) -> bool:
    """Loguru filter that allows to print stream messages from bots."""
    if isinstance(desired, SpeakerType):
        desired = {desired}

    def filter(record: loguru.Record) -> bool:
        """Loguru filter that allows to print stream messages from bots."""
        return record["extra"].get("speaker_type", SpeakerType.SYSTEM) in desired

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
    sys.stderr,
    filter=log_filter({SpeakerType.BOT, SpeakerType.HUMAN}),
    format=bot_fomatter,
)
# loguru.logger.add(
#     sys.stderr,
#     filter=log_filter(SpeakerType.SYSTEM),
#     level="ERROR",
# )
# loguru.logger.add(LOG_FILE_PATH, filter=log_filter(SpeakerType.BOT), format=bot_fomatter)

human_logger = loguru.logger.bind(speaker_type=SpeakerType.HUMAN, color="green")
