"""Logging module for Auto-GPT."""
from __future__ import annotations

import logging
from enum import Enum
from logging import LogRecord
from pathlib import Path

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


class ColorFormatter(logging.Formatter):
    """A formatter that adds color to log messages."""

    def format(self, record: LogRecord) -> str:
        log_msg = super().format(record)
        return f"{record.color}{log_msg}{Style.RESET_ALL}"


class ConsoleHandler(logging.StreamHandler):
    """Custom console handler that allows to use a custom terminator."""

    def emit(self, record: LogRecord) -> None:
        """Copied from logging.StreamHandler.emit() and modified the terminator."""
        if hasattr(record, "terminator"):
            terminator = record.terminator
        else:
            terminator = self.terminator

        try:
            msg = self.format(record)
            stream = self.stream
            stream.write(msg)
            stream.write(terminator)
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


class RoutingHandler(logging.Handler):
    """A handler that routes messages to other handlers."""

    def __init__(self, log_file: str = LOG_FILE_PATH) -> None:
        super().__init__()

        # Set up console handler
        console_handler = ConsoleHandler()
        console_formatter = ColorFormatter()
        console_handler.setFormatter(console_formatter)

        # Set up file handler
        file_handler = logging.FileHandler(log_file)

        self.console_handler = console_handler
        self.file_handler = file_handler

    def emit(self, record: LogRecord) -> None:
        """Emit a log message to either the console or the file handler or both."""
        if hasattr(record, "output") and record.output == LogOutput.FILE:
            self.file_handler.emit(record)
        elif hasattr(record, "output") and record.output == LogOutput.MAIN:
            self.console_handler.emit(record)
        elif not hasattr(record, "output") or record.output == LogOutput.ALL:
            self.console_handler.emit(record)
            self.file_handler.emit(record)
        else:
            raise ValueError(f"Invalid output type: {record.output}")


class Logger:
    def __init__(
        self, name: str = __file__, level: logging._Level = logging.INFO, **kwargs
    ):
        self.logger = logging.getLogger(name=name)
        self.logger.setLevel(level=level)

        routing_handler = RoutingHandler(**kwargs)
        self.logger.addHandler(routing_handler)

    def log(self, level: int, message: str, **kwargs) -> None:
        self.logger.log(level, message, extra=kwargs)

    def info(
        self,
        message: str,
        output: LogOutput = LogOutput.ALL,
        color: Fore = Fore.GREEN,
        **kwargs,
    ) -> None:
        extra = {"color": color, "output": output}
        self.logger.info(message, extra=extra, **kwargs)

    def warn(
        self,
        message: str,
        output: LogOutput = LogOutput.ALL,
        color: Fore = Fore.YELLOW,
        **kwargs,
    ) -> None:
        extra = {"color": color, "output": output}
        self.logger.warn(message, extra=extra, **kwargs)

    def error(
        self,
        message: str,
        output: LogOutput = LogOutput.ALL,
        color: Fore = Fore.RED,
        **kwargs,
    ) -> None:
        extra = {"color": color, "output": output}
        self.logger.error(message, extra=extra, **kwargs)


class BotLogger(Logger):
    """Logger allowing straming messages from bots."""

    def bot_speak(
        self,
        message: str,
        output: LogOutput = LogOutput.ALL,
        color: Fore = Fore.BLUE,
        **kwargs,
    ) -> None:
        if self.logger.isEnabledFor(BOT_SPEAK):
            # TODO: Add text to speach here.
            kwargs.update({"color": color, "output": output, "terminator": ""})
            self.log(level=BOT_SPEAK, message=message, **kwargs)
