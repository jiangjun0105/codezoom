from __future__ import annotations

import ast
from ast import literal_eval
from dataclasses import dataclass
from pathlib import Path
from time import sleep

import pandas as pd

from codebase_analyzer.parser.codeinfo import extract_code_info


def traverse_directory(directory_path: str | Path) -> list[str]:
    """Traverse the directory and return a list of python files."""
    directory_path = Path(directory_path).expanduser()
    python_files = []

    for p in directory_path.glob("**/*"):
        if not p.is_dir() and p.endswith(".py"):
            python_files.append(p.absolute().as_posix())

    return python_files


# NOTE: Unused because we perfer to parse the codebase on demand.
def parse_codebase(codebase_path: str | Path) -> tuple[dict[str, str], pd.DataFrame]:
    """Parse the codebase and return a list of codebase info."""
    python_files = traverse_directory(codebase_path)
    raw_codebase = {}
    codebase_info = []

    for file in python_files:
        try:
            raw_code, code_info = extract_code_info(Path(file))
            raw_codebase[file] = raw_code
            codebase_info.extend(code_info)
        except Exception as e:
            print(f"Error parsing {file}: {e}")

    return raw_codebase, pd.DataFrame(codebase_info)
