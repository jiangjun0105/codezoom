import os
from codebase_analyzer.file_parser import parse_codebase
from codebase_analyzer.query_processor import process_query, generate_codebase_description


def main(repo_path, codebase_description):
    codebase_info = parse_codebase(repo_path)

    while True:
        query = input("\nEnter a query or type 'exit' to quit: ")
        if query.lower() == "exit":
            break

        process_query(query, codebase_info, codebase_description)
    
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GPT Developer - Codebase Analyzer")
    parser.add_argument("repo_path", help="Path to the repository to analyze")
    args = parser.parse_args()

    codebase_info = parse_codebase(args.repo_path)
    codebase_description = generate_codebase_description(codebase_info)
    main(args.repo_path, codebase_description)
