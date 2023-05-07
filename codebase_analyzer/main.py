from __future__ import annotations

from functools import partial
from pathlib import Path

import click
import pandas as pd

from codebase_analyzer import prompts
from codebase_analyzer.bots import CodebaseBot, CodingBot, MasterBot
from codebase_analyzer.chatbot import BotModel, Chatbot
from codebase_analyzer.logs import SpeakerType, human_logger


def register_bots(repo: str, cache: str | Path = None) -> tuple[str, pd.DataFrame]:
    """Anything needs to be done before the interaction loop."""
    codebase_bot = CodebaseBot(repo=repo, cache=cache)
    coding_bot = CodingBot()
    bots = {
        "codebase_bot": codebase_bot,
        "coding_bot": coding_bot,
    }
    bot_map = {
        "codebase_bot.ask": partial(codebase_bot.ask, asked_by="master_bot"),
        "coding_bot.ask": partial(coding_bot.ask, asked_by="master_bot"),
    }
    return bots, MasterBot(bot_map=bot_map)


def before_exiting(bots: dict[str, Chatbot]) -> None:
    """Anything needs to be done before the interaction loop."""
    bots["codebase_bot"].save_cache()


def interaction_loop(master_bot: MasterBot) -> None:
    """Main loop for interacting wiht the codebase analyzer."""

    while True:
        query = input("\nEnter a query or type 'exit' to quit: ")
        if query.lower() == "exit":
            break
        human_logger.info(
            f"HUMAN -> MASTER_BOT: {query}\n", speaker=SpeakerType.HUMAN
        )
        master_bot.ask(prompt=query, asked_by="human")


def main(repo: str | Path, cache: str | Path) -> None:
    """GPT Developer - Codebase Analyzer"""
    bots, master_bot = register_bots(repo=repo, cache=cache)
    interaction_loop(master_bot)
    before_exiting(bots=bots)


@click.command()
@click.option("--repo", help="Path to the repository to analyze")
@click.option("--cache", help="Path to the cache repo info csv file")
def cli(repo: str | Path, cache: str | Path) -> None:
    """CLI: wrapper for the main function for easy testing."""
    main(repo=repo, cache=cache)


if __name__ == "__main__":
    cli()
