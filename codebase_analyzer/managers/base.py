"""Base classes for bot managers."""

from abc import ABC, abstractmethod

from loguru import logger
from pydantic import BaseModel

from codebase_analyzer.bots.base import Bot


class BotManagerBase(ABC, BaseModel):
    bots: dict[str, Bot]

    @abstractmethod
    def get_bot(self, *args, **kwargs) -> Bot:
        pass

    @abstractmethod
    def bot_id(self, *args, **kwargs) -> str:
        pass

    def save_cache(self) -> None:
        for bot_id, bot in self.bots.items():
            try:
                logger.info(f"Saving cache for bot {bot_id}.")
                bot.save_cache()
            except Exception as e:
                logger.error(
                    f"Failed to save cache for bot {bot_id} with error {e}."
                )
