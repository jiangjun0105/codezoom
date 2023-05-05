from __future__ import annotations

from ast import literal_eval
from pathlib import Path

import click
import numpy as np
import pandas as pd
from loguru import logger

from codebase_analyzer.embedding import embed_codebase
from codebase_analyzer.interaction import ask_codebase, remind_mission
from codebase_analyzer.parser import extract_code_info, load_raw_code


def load_cached_codebase_info(cache: str) -> pd.DataFrame:
    """Load cached codebase info from the given csv file."""
    codebase_info = pd.read_csv(cache).set_index("Unnamed: 0")
    logger.info(f"Loaded codebase info from {cache}")
    if "embedding" not in codebase_info.columns:
        logger.info("Embeddings not found in cache, embedding codebase...")
        embed_codebase(codebase_info)
    else:
        # TODO: Use format supporting storing the embedding
        codebase_info["embedding"] = codebase_info["embedding"].apply(literal_eval)
    return codebase_info


def codebase_analyzer(repo: str, cache: str = None) -> None:
    """Main loop for interacting wiht the codebase analyzer."""
    raw_codebase = load_raw_code(repo)
    if cache:
        codebase_info = load_cached_codebase_info(cache)
    else:
        codebase_info = extract_code_info(raw_code=raw_codebase)
        codebase_info = embed_codebase(codebase_info)

    while True:
        query = input("\nEnter a query or type 'exit' to quit: ")
        if query.lower() == "exit":
            break
        if query.lower() == "remind":
            remind_mission()
        ask_codebase(
            question=query, codebase_info=codebase_info, raw_codebase=raw_codebase
        )

    codebase_info.to_csv(cache)
    logger.info(f"Saved codebase info to {cache}")


@click.command()
@click.option("--repo", help="Path to the repository to analyze")
@click.option("--cache", help="Path to the cache repo info csv file")
def main(repo: str | Path, cache: str | Path) -> None:
    """GPT Developer - Codebase Analyzer"""
    codebase_analyzer(repo=repo, cache=cache)


if __name__ == "__main__":
    main()
