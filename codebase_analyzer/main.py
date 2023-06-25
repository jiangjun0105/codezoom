from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from codebase_analyzer.bots.file.base import FileBot
from codebase_analyzer.managers.function import FunctionBotManager
from codebase_analyzer.parser.parser import load_cached_codebase_info


def interaction_loop(master_bot: Any) -> None:
    """Main loop for interacting wiht the codebase analyzer."""

    while True:
        query = input("\nEnter a query or type 'exit' to quit: ")
        if query.lower() == "exit":
            break
        master_bot.ask(inputs=query)


def main(repo_path: Path, cache_path: Path) -> None:
    """Ichigen Coder - A cluster of coding bots
    Codebase Analyzer module
    """

    # FIXME after supporting multiple files
    file_path = (repo_path / "V1.py").expanduser()
    code_info = load_cached_codebase_info(cache_path=cache_path)
    codebase_info = {
        str(file_path): code_info,
    }

    # Singleton managers
    manager = FunctionBotManager(codebase_info=codebase_info)

    # FIXME: For now we use the file bot as master bot
    file_bot = FileBot(
        file_path=file_path,
        cache_path=cache_path,
        code_info=code_info,
        get_bot_func=manager.get_bot,
    )
    interaction_loop(file_bot)


@click.command()
@click.option("--repo", help="Path to the repository to analyze")
@click.option("--cache", help="Path to the cache repo info csv file")
def cli(repo: str | Path, cache: str | Path) -> None:
    """CLI: wrapper for the main function for easy testing."""
    main(repo_path=Path(repo), cache_path=Path(cache))


if __name__ == "__main__":
    cli()
