"""This module contains the BotManager class."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from pydantic import BaseModel, Field
from singleton_decorator import singleton

from codebase_analyzer.bots.base import Bot
from codebase_analyzer.bots.function.base import FunctionBot
from codebase_analyzer.bots.module.base import ModuleBot
from codebase_analyzer.bots.package.base import PackageBot
from codebase_analyzer.parser.callgraph import URI
from codebase_analyzer.parser.codeinfo import _join_summaries
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode, NodeType
from codebase_analyzer.parser.merge import (
    CacheInvalidError,
    generate_nodes_from_repo,
)
from codebase_analyzer.tools.base import ask_bot, get_code, semantic_search
from codebase_analyzer.tools.embedding import search_by_embedding

_SUMMARY_SHEET = """You contains the following functions/modules/packages:

{children_summaries}

You call the following functions:

{calls_summaries}
"""

_SEMANTIC_SERACH = """name, code_length (tokens)
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


@singleton
class BotManager:
    bots: dict[URI, Bot] = Field(default_factory=dict)
    nodes: dict[str, CodeNode] = Field(default_factory=dict)
    root_uri: URI
    node_count: int

    @staticmethod
    def from_repo(
        cls,
        repo_root: Path,
        cache_root: Path,
    ) -> BotManager:
        """Create a BotManager from a repo root path."""
        try:
            nodes = CodeInfo.from_disk(cache_root=cache_root)
        except FileNotFoundError or CacheInvalidError:
            logger.info(
                f"Cannot find valid cache for {repo_root}. Generating from scratch."
            )
            nodes = generate_nodes_from_repo(
                repo_root=repo_root,
                output_path=cache_root,
                entry_point=repo_root,
                uri_prefix="",
            )
            nodes.to_disk(nodes=nodes, cache_root=cache_root)

        return cls(
            nodes=nodes.uri2node,
            root_uri=nodes.metadata.root,
            node_count=nodes.metadata.count,
        )

    def get_bot_by_uri(self, uri: URI) -> Bot:
        if uri not in self.nodes:
            # TODO: Later if allowing loading parts of the codebase, we need to
            # change this to warning.
            raise ValueError(f"Cannot find {uri} in the cache.")

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
        """Process ask from a bot/tool."""
        # TODO: Log this ask event
        if ask_type == ask_bot.__name__:
            return self.ask_bot(**kwargs)
        if ask_type == get_code.__name__:
            return self.get_code_by_uri(**kwargs)
        if ask_type == semantic_search.__name__:
            return self.semantic_search(ask_by=ask_by, **kwargs)
        raise ValueError(f"Unknown ask type {ask_type=}.")
