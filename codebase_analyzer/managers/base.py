"""This module contains the BotManager class."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger
from pydantic import Field
from singleton_decorator import singleton

from codebase_analyzer.bots.base import Bot, bot_from_code_node
from codebase_analyzer.parser.callgraph import URI
from codebase_analyzer.parser.deftree import CodeNode
from codebase_analyzer.parser.merge import (
    CacheInvalidError,
    generate_nodes_from_repo,
    load_nodes_from_disk,
    save_nodes_to_disk,
)


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
            nodes = load_nodes_from_disk(cache_root=cache_root)
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
            save_nodes_to_disk(nodes=nodes, cache_root=cache_root)

        return cls(
            nodes=nodes.uri2node,
            root_uri=nodes.metadata.root_uri,
            node_count=nodes.metadata.node_count,
        )

    def _to_uri(self, file_path: Path, function_name: str) -> str:
        """Get URI for a given function name and file path."""
        return f"{file_path}/{function_name}"

    def get_bot(
        self,
        file_path: Path,
        function_name: str,
    ) -> Bot:
        """Get a function bot for a given function name and file path."""
        uri = self._to_uri(file_path, function_name)
        return self.get_bot_by_uri(uri)

    def get_bot_by_uri(self, uri: URI) -> Bot:
        if uri not in self.nodes:
            # TODO: Later if allowing loading parts of the codebase, we need to
            # change this to warning.
            raise ValueError(f"Cannot find {uri} in the cache.")

        if uri not in self.bots:
            self.bots[uri] = bot_from_code_node(
                code_node=self.nodes[uri],
                get_bot_func=self.get_bot,
            )
        return self.bots[uri]

    @property
    def root_bot(self) -> Bot:
        """Get the root bot."""
        return self.get_bot_by_uri(uri=self.root_uri)
