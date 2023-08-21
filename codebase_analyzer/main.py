from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import click
from loguru import logger

from codebase_analyzer.bots.manager import BotManager


def calculate_path_hash(path: Path | str) -> str:
    """Calculate the hash256 of the given path."""

    # Resolve the absolute path and check if it exists
    path = Path(path).expanduser().resolve()
    logger.debug(f"For cache hash: {path=}")
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


def _path(path: Path | str, check_exist: bool = False, create: bool = False) -> Path:
    p = Path(path).expanduser().resolve()
    if check_exist and not p.exists():
        raise ValueError(f"{p=} does not exist.")
    if create and not p.exists():
        p.mkdir(parents=True)
    logger.info(f"{str(p)=}")
    return p


def main(
    repo_root: Path, entry_point: Path, cache_root: Path | None = None, **kwargs: Any
) -> None:
    """Ichigen Coder - A cluster of coding bots
    Codebase Analyzer module
    """
    cache_root = cache_root or get_cache_root(repo_root)
    cache_root = _path(cache_root, create=True)
    repo_root = _path(repo_root, check_exist=True)
    entry_point = _path(entry_point, check_exist=True)

    # Singleton manager
    manager = BotManager.from_repo(
        repo_root=repo_root,
        cache_root=cache_root,
        entry_point=entry_point,
        **kwargs,
    )

    # TODO: We may want a separate master bot to have more flexibility
    # TODO: Currently if the root_bot only have one child, the performance is bad.
    interaction_loop(master_bot=manager.root_bot)


@click.command()
@click.option(
    "--repo-root",
    "-r",
    type=Path,
    required=True,
    help="Path to the root of the repository to analyze.",
)
@click.option(
    "--entry-point",
    "-e",
    type=Path,
    required=True,
    # TODO: Detect the entry_point automatically
    help="Relative or absoluate path to the entry_point file in the repository. ",
)
@click.option(
    "--cache-root",
    "-c",
    type=Path,
    help="Path to the root cache repo. Will cacluate based on sha256 of repo root if not assigned",
)
def cli(repo_root: Path, entry_point: Path, cache_root: Path) -> None:
    """CLI: wrapper for the main function for easy testing."""
    main(repo_root=repo_root, cache_root=cache_root, entry_point=entry_point)


if __name__ == "__main__":
    # cli()

    ## TODO: Make the following a test
    repo_root = Path("/Users/jun/Projects/Auto-GPT/").resolve()
    entry_point = Path("/Users/jun/Projects/Auto-GPT/autogpt/app/cli.py").resolve()
    # cache_root = Path("/Users/jun/Projects/ichigen-coder/shared_cache/Auto-GPT").resolve()
    main(
        repo_root=repo_root,
        entry_point=entry_point,
        # cache_root=cache_root,
    )
