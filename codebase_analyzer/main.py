from __future__ import annotations

import re
import argparse
from codebase_analyzer.parser import parse_codebase
from codebase_analyzer.interaction import ask_codebase



def main(args: argparse.Namespace) -> None:
    """Main loop for interacting wiht the codebase analyzer."""

    raw_codebase, codebase_info = parse_codebase(args.repo_path)

    while True:
        query = input("\nEnter a query or type 'exit' to quit: ")
        if query.lower() == "exit":
            break

        ask_codebase(question=query, codebase_info=codebase_info, raw_codebase=raw_codebase)
    
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="GPT Developer - Codebase Analyzer")
    parser.add_argument("repo_path", help="Path to the repository to analyze")
    args = parser.parse_args()

    main(args)
