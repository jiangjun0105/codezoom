from __future__ import annotations

import argparse
import logging

import pandas as pd

from codebase_analyzer.interaction import ask_codebase
from codebase_analyzer.parser import extract_code_info, load_raw_code

logger = logging.getLogger(__name__)


def main(args: argparse.Namespace) -> None:
    """Main loop for interacting wiht the codebase analyzer."""
    raw_codebase = load_raw_code(args.repo)
    if args.cache:
        codebase_info = pd.read_csv(args.cache).set_index("Unnamed: 0")
        print(f"Loaded codebase info from {args.cache}")
        print(codebase_info.columns)
    else:
        # TODO: Change to use parse_codebase + vector store.
        codebase_info = extract_code_info(raw_code=raw_codebase)

    while True:
        query = input("\nEnter a query or type 'exit' to quit: ")
        if query.lower() == "exit":
            break

        ask_codebase(
            question=query, codebase_info=codebase_info, raw_codebase=raw_codebase
        )


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="GPT Developer - Codebase Analyzer")
    parser.add_argument("--repo", help="Path to the repository to analyze")
    parser.add_argument("--cache", help="Path to the cache repo info csv file")
    args = parser.parse_args()

    main(args)
