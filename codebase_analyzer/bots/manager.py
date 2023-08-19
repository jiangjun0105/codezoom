"""This module contains the BotManager class."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from loguru import logger
from pydantic import BaseModel, Field
from singleton_decorator import singleton

from codebase_analyzer.bots.executor import Bot
from codebase_analyzer.bots.function.base import FunctionBot
from codebase_analyzer.bots.module.base import ModuleBot
from codebase_analyzer.bots.package.base import PackageBot
from codebase_analyzer.parser.callgraph import URI
from codebase_analyzer.parser.codeinfo import _join_summaries
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode, NodeType
from codebase_analyzer.parser.merge import (
    CacheInvalidError,
    generate_codeinfo_from_repo,
)
from codebase_analyzer.tools.base import ask_bot, get_code, semantic_search
from codebase_analyzer.tools.embedding import search_by_embedding

_SUMMARY_SHEET = """You contains the following functions/modules/packages:

URI (type): Summary
-------------------
{children_summaries}

You called the following functions:

URI (type): Summary
-------------------
{calls_summaries}
"""

_SEMANTIC_SERACH = """URI, code_length (tokens)
=============
{results}

"""

BOT_TYPE_MAP = {
    NodeType.PACKAGE: PackageBot,
    NodeType.MODULE: ModuleBot,
    NodeType.FUNCTION: FunctionBot,
    NodeType.CLASS: FunctionBot,
    NodeType.CLASS_METHOD: FunctionBot,
    NodeType.STATEMENT: FunctionBot,
    NodeType.ENTRYPOINT: FunctionBot,
}


class BotConfig(BaseModel):
    llm_model: str = Field(
        default="gpt-3.5-turbo", description="Which openai model to use."
    )
    # TODO: Add tools to the config.


# TODO: Make this configurable through a yaml file.
class BotManagerConfig(BaseModel):
    function: BotConfig = Field(default_factory=BotConfig)
    module: BotConfig = Field(default_factory=BotConfig)
    package: BotConfig = Field(default_factory=BotConfig)

    def by_class(self, bot_cls: Callable) -> BotConfig:
        if bot_cls == FunctionBot:
            return self.function
        if bot_cls == ModuleBot:
            return self.module
        if bot_cls == PackageBot:
            return self.package
        raise ValueError(f"Unknown bot class {bot_cls=}")


def _codeinfo_path(cache_root: Path) -> Path:
    """Gets the path to the codeinfo.json file."""
    return cache_root / "codeinfo.json"


def _fasten_path(cache_root: Path, entry_point: Path) -> Path:
    """Gets the path to the fasten.json file."""
    return cache_root / f"{entry_point.stem}_fasten.json"


# @singleton
class BotManager(BaseModel):
    bots: dict[URI, Bot] = Field(default_factory=dict)
    nodes: dict[str, CodeNode]
    root_uri: URI
    node_count: int
    config: BotManagerConfig = Field(default_factory=BotManagerConfig)

    @classmethod
    def from_repo(
        cls,
        repo_root: Path,
        cache_root: Path,
        entry_point: Path,
        uri_prefix: str = "",
    ) -> BotManager:
        """Create a BotManager from a repo root path."""
        try:
            code_info = CodeInfo.from_disk(input_path=_codeinfo_path(cache_root))
        except FileNotFoundError or CacheInvalidError:
            logger.info(
                f"Cannot find valid cache for {repo_root}. Generating from scratch."
            )
            code_info = generate_codeinfo_from_repo(
                repo_root=repo_root,
                output_path=_fasten_path(cache_root, entry_point),
                entry_point=entry_point,
                uri_prefix=uri_prefix,
            )
            logger.info(f"Saving codeinfo to {cache_root}/codeinfo.json.")
            code_info.to_disk(output_path=cache_root / "codeinfo.json")

        return cls(
            nodes=code_info.nodes,
            root_uri=code_info.metadata.root,
            node_count=code_info.metadata.count,
        )

    def get_bot_by_uri(self, uri: URI) -> Bot:
        if uri not in self.nodes:
            # TODO: Later if allowing loading parts of the codebase, we need to
            # change this to warning.
            raise ValueError(f"Cannot find {uri} in the self.nodes.")

        if uri not in self.bots:
            self.bots[uri] = self.bot_from_code_node(uri=uri)
        return self.bots[uri]

    @property
    def root_bot(self) -> Bot:
        """Get the root bot."""
        return self.get_bot_by_uri(uri=self.root_uri)

    def bot_from_code_node(self, uri: URI) -> Bot:
        """Generate a bot from a code node."""
        code_node = self.nodes[uri]
        bot_cls = BOT_TYPE_MAP[code_node.type]
        # TODO: Rethink if we should distinguish different types of nodes.
        # TODO: Rethink if we should include called_by and parent.
        children_summaries = _join_summaries(
            uris=code_node.children, uri2node=self.nodes
        )
        calls_summaries = _join_summaries(uris=code_node.calls, uri2node=self.nodes)

        return bot_cls(
            llm_model=self.config.by_class(bot_cls).llm_model,
            code_node=code_node,
            summary_sheet=_SUMMARY_SHEET.format(
                children_summaries=children_summaries,
                calls_summaries=calls_summaries,
            ),
            ask_manager=self.process_ask,
        )

    def ask_bot(self, ask_to: URI, inputs: str) -> Bot:
        return self.get_bot_by_uri(uri=ask_to).ask(inputs=inputs)

    def get_code_by_uri(self, uri: URI) -> str:
        return self.nodes[uri].code

    def _connected_nodes(self, uri: URI) -> list[CodeNode]:
        """Get all connected nodes of a given node."""
        # TODO: Rethink if give called by and supperclasses.
        node = self.nodes[uri]
        connected = set(node.children + node.calls)
        return [self.nodes[uri] for uri in connected]

    def semantic_search(self, ask_by: URI, query: str, n: int = 5) -> str:
        connected: list[CodeNode] = self._connected_nodes(uri=ask_by)
        uris = np.array([n.uri for n in connected])
        embeddings = np.array([n.embedding for n in connected])
        indexes = search_by_embedding(embeddings=embeddings, query=query, n=n)
        got_nodes: list[CodeNode] = [self.nodes[u] for u in uris[indexes]]

        return _SEMANTIC_SERACH.format(
            results="\n".join(f"{n.uri}, {n.code_length}" for n in got_nodes)
        )

    def process_ask(self, ask_type: str, ask_by: URI, **kwargs) -> str:
        """Process ask from a bot/tool. Having this function is mainly to solve
        the circular import problem. If calling corresponding function in tools
        directly, the imports are like:

            Tools -> BotManager -> Bot -> Tools.
        """
        # TODO: Log this ask event
        if ask_type == ask_bot.__name__:
            return self.ask_bot(**kwargs)
        if ask_type == get_code.__name__:
            return self.get_code_by_uri(**kwargs)
        if ask_type == semantic_search.__name__:
            return self.semantic_search(ask_by=ask_by, **kwargs)
        raise ValueError(f"Unknown ask type {ask_type=}.")


# TODO: Organize the following tests into a test file.
# m = BotManager.from_repo(
#     repo_root=Path("codebase_analyzer/tests/data/").resolve(),
#     cache_root=Path("codebase_analyzer/tests/data/").resolve(),
#     entry_point=Path("codebase_analyzer/tests/data/short.py").resolve(),
#     uri_prefix="/codebase_analyzer.tests.data",
#     )
# b1 = m.get_bot_by_uri(uri="/codebase_analyzer.tests.data.short/")
# m.process_ask(ask_type="ask_bot", ask_by=b1.uri, ask_to="/codebase_analyzer.tests.data.short/Foo", inputs="Hi!")
# m.process_ask(ask_type="semantic_search", ask_by=b1.uri, query="Greetings related")
# m.process_ask(ask_type="get_code", ask_by=b1.uri, uri="/codebase_analyzer.tests.data.short/")
# pass
