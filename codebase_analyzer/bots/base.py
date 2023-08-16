"""Base class for bots."""

from abc import ABC, abstractmethod
from typing import Callable

from pydantic import BaseModel

from codebase_analyzer.parser.deftree import CodeNode


class Bot(ABC, BaseModel):
    @abstractmethod
    def ask(self, *args, **kwargs) -> str:
        pass

    @classmethod
    @abstractmethod
    def from_code_node(cls, code_node: CodeNode) -> None:
        pass

    def save_cache(self) -> None:
        # NOTE: Not all bots need to save cache
        pass
