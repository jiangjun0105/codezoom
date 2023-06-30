from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from codebase_analyzer.bots.file.base import FileBot
from codebase_analyzer.managers.function import FunctionBotManager


def interaction_loop(master_bot: Any) -> None:
    """Main loop for interacting wiht the codebase analyzer."""

    while True:
        query = input("\nEnter a query or type 'exit' to quit: ")
        if query.lower() == "exit":
            break
        master_bot.ask(inputs=query)


def main(repo: Path, cache: Path) -> None:
    """Ichigen Coder - A cluster of coding bots
    Codebase Analyzer module
    """

    # FIXME after supporting multiple files
    file_path = Path("src/revChatGPT/V1.py")

    # Singleton managers
    manager = FunctionBotManager()

    # FIXME: For now we use the file bot as master bot
    file_bot = FileBot.from_cache(
        repo_root=repo,
        cache_root=cache,
        file_path=file_path,
        get_bot_func=manager.get_bot,
    )
    interaction_loop(file_bot)
    manager.save_cache()


@click.command()
@click.option("--repo", help="Path to the repository to analyze")
@click.option("--cache", help="Path to the cache repo info csv file")
def cli(repo: str | Path, cache: str | Path) -> None:
    """CLI: wrapper for the main function for easy testing."""
    main(repo=Path(repo), cache=Path(cache))


if __name__ == "__main__":
    cli()
