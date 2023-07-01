"""Base class for bots."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class Bot(ABC, BaseModel):
    @abstractmethod
    def ask(self, *args, **kwargs) -> str:
        pass

    def save_cache(self) -> None:
        # NOTE: Not all bots need to save cache
        pass
