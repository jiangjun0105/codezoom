"""Base class for bots."""

from abc import ABC, abstractmethod

from pydantic import BaseModel

from codebase_analyzer.bots.file.base import FileBot
from codebase_analyzer.bots.function.base import FunctionBot
from codebase_analyzer.bots.package.base import PackageBot
from codebase_analyzer.parser.deftree import CodeNode, NodeType


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


_BOT_TYPE_MAP = {
    NodeType.PACKAGE: PackageBot,
    NodeType.MODULE: FileBot,
    NodeType.FUNCTION: FunctionBot,
    NodeType.CLASS: FunctionBot,
    NodeType.CLASS_METHOD: FunctionBot,
    NodeType.STATEMENT: FunctionBot,
    NodeType.ENTRYPOINT: FunctionBot,
}


def bot_from_code_node(code_node: CodeNode, **kwargs) -> Bot:
    """Generate a bot from a code node."""
    bot_cls = _BOT_TYPE_MAP[code_node.type]
    return bot_cls.from_code_node(code_node=code_node, **kwargs)
