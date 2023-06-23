"""Base class for bots."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class Bot(ABC, BaseModel):
    @abstractmethod
    def ask(self, *args, **kwargs) -> str:
        pass
