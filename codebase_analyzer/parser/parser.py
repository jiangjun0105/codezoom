from __future__ import annotations

import ast
from ast import literal_eval
from dataclasses import dataclass
from pathlib import Path
from time import sleep

import pandas as pd
from loguru import logger
from tqdm import tqdm

from codebase_analyzer.parser.ast_visitor import CodeBlockLevel, CodeExtractor


def load_cached_code_info(path: Path) -> pd.DataFrame:
    """Load cached codebase info from the given csv file."""
    code_info = pd.read_csv(path).set_index("Unnamed: 0")
    logger.info(f"Loaded codebase info from {path}")

    # TODO: Use format supporting storing the embeddings instead of CSV
    # TODO: Create single source of true for names of the columns
    code_info["embedding"] = code_info["embedding"].apply(literal_eval)
    return code_info


def extract_code_info(file_path: Path) -> pd.DataFrame:
    """Extract code units, imports, and assignments from the given file."""
    file_path = Path(file_path).expanduser()
    raw_code = file_path.read_text(encoding="utf-8")
    return CodeExtractor.blocks_from_code(code=raw_code)


def _log_summary(code_info: list[dict], raw_code: str):
    """Log the summary of the code info."""
    summary = "\n".join(i["summary"] for i in code_info)

    logger.info(
        f"Original Code length: {len(raw_code)}\n"
        f"Extracted block num: {len(code_info)}\n"
        f"Extracted Code length: {len(summary)}\n"
    )


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


def generate_file_summary(code_info):
    """Generate the summary of the file."""
    return "\n".join(
        i["summary"] for i in code_info if i["level"] == CodeBlockLevel.FILE
    )


def generate_functions_summary(code_info):
    """Generate the summary of the functions."""
    return "\n".join(
        i["summary"] for i in code_info if i["level"] == CodeBlockLevel.DIRECT_CHILD
    )
