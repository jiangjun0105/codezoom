"""Base classes for bot managers."""

from abc import ABC, abstractmethod

from codebase_analyzer.bots.base import Bot


class BotMager(ABC):
    @abstractmethod
    def get_bot(self, *args, **kwargs) -> Bot:
        pass

    @abstractmethod
    def bot_id(self, *args, **kwargs) -> str:
        pass
