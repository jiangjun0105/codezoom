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


def main(repo_root: Path, file_path: Path, cache_root: Path | None = None) -> None:
    """Ichigen Coder - A cluster of coding bots
    Codebase Analyzer module
    """
    cache_root = cache_root or get_cache_root(repo_root)

    # FIXME after supporting multiple files
    file_relative_path = file_path
    if not file_path.is_absolute():
        file_relative_path = file_path.relative_to(repo_root)

    # Singleton managers
    manager = FunctionBotManager()

    # FIXME: For now we use the file bot as master bot
    file_bot = FileBot.from_cache(
        repo_root=repo_root,
        cache_root=cache_root,
        file_relative_path=file_relative_path,
        get_bot_func=manager.get_bot,
    )
    interaction_loop(file_bot)
    file_bot.save_cache()
    manager.save_cache()


@click.command()
@click.option(
    "--repo-root",
    "-r",
    type=Path,
    required=True,
    help="Path to the root of the repository to analyze.",
)
@click.option(
    "--file-path",
    "-f",
    type=Path,
    required=True,
    help="Relative or absoluate path to the file in the repository to analyze. "
    "Will become Optional after supporting multiple files.",
)
@click.option(
    "--cache-root",
    "-c",
    type=Path,
    help="Path to the root cache repo. Will cacluate based on sha256 of repo root if not assigned",
)
def cli(repo_root: Path, file_path: Path, cache_root: Path) -> None:
    """CLI: wrapper for the main function for easy testing."""
    main(repo_root=repo_root, cache_root=cache_root, file_path=file_path)


if __name__ == "__main__":
    cli()
