from __future__ import annotations

from pathlib import Path

import click
import pandas as pd

from codebase_analyzer.interaction import ask_codebase, remind_mission
from codebase_analyzer.logs import Logger
from codebase_analyzer.parser import extract_code_info, load_raw_code

logger = Logger(__name__)


@click.command()
@click.option("--repo", help="Path to the repository to analyze")
@click.option("--cache", help="Path to the cache repo info csv file")
def main(repo: str | Path, cache: str | Path) -> None:
    """GPT Developer - Codebase Analyzer"""
    """Main loop for interacting wiht the codebase analyzer."""
    raw_codebase = load_raw_code(repo)
    if cache:
        codebase_info = pd.read_csv(cache).set_index("Unnamed: 0")
        logger.info(f"Loaded codebase info from {cache}")
    else:
        # TODO: Change to use parse_codebase + vector store.
        codebase_info = extract_code_info(raw_code=raw_codebase)

    while True:
        query = input("\nEnter a query or type 'exit' to quit: ")
        if query.lower() == "exit":
            break
        if query.lower() == "remind":
            remind_mission()
        ask_codebase(
            question=query, codebase_info=codebase_info, raw_codebase=raw_codebase
        )


if __name__ == "__main__":
    main()
