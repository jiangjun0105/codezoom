from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import click

from codebase_analyzer.bots.file.base import FileBot
from codebase_analyzer.managers.function import FunctionBotManager


def calculate_path_hash(path: Path | str) -> str:
    """Calculate the hash256 of the given path."""

    # Resolve the absolute path and check if it exists
    path = Path(path).resolve()
    return hashlib.sha256(str(path).encode()).hexdigest()


def get_cache_root(repo_root: Path) -> Path:
    """Gets the cache root path for the given repo path."""
    # TODO: Make the cache root configurable
    return Path(__file__).parent.parent / ".cache" / calculate_path_hash(repo_root)


def interaction_loop(master_bot: Any) -> None:
    """Main loop for interacting wiht the codebase analyzer."""

    while True:
        query = input("\nEnter a query or type 'exit' to quit: ")
        if query.lower() == "exit":
            break
        master_bot.ask(inputs=query)


def main(repo: Path, cache: Path | None = None) -> None:
    """Ichigen Coder - A cluster of coding bots
    Codebase Analyzer module
    """
    cache = cache or get_cache_root(repo)

    # FIXME after supporting multiple files
    file_path = Path("src/revChatGPT/V1.py")

    # Singleton managers
    manager = FunctionBotManager()

    # FIXME: For now we use the file bot as master bot
    file_bot = FileBot.from_cache(
        repo_root=repo,
        cache_root=cache,
        file_relative_path=file_path,
        get_bot_func=manager.get_bot,
    )
    interaction_loop(file_bot)
    file_bot.save_cache()
    manager.save_cache()


@click.command()
@click.option(
    "--repo", type=Path, required=True, help="Path to the repository to analyze"
)
@click.option("--cache", type=Path, help="Path to the cache repo info csv file")
def cli(repo: Path, cache: Path) -> None:
    """CLI: wrapper for the main function for easy testing."""
    main(repo=repo, cache=cache)


if __name__ == "__main__":
    cli()
