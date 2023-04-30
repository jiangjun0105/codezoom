from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from time import sleep

import pandas as pd
from revChatGPT.V1 import Chatbot
from tqdm import tqdm

from codebase_analyzer.ast_visitor import CodeExtractor
from codebase_analyzer.interaction import ask_gptapi, gpt3_bot


@dataclass
class RawCode:
    file: Path
    code: str


def extract_code_units(code: str, threshold: int = 50) -> tuple[dict[str, str], list[str], list[str]]:
    """Extract code in unit of function or class from the given code."""
    tree = ast.parse(code)
    extractor = CodeExtractor(threshold)
    extractor.visit(tree)
    return extractor.code_units, extractor.imports, extractor.assignments


def summarize_code(code: str, chatbot: Chatbot, ratio: float = 15, min_len=20, max_len=100) -> str:
    """Summarize the code using GPT chatbot."""
    length = min(max_len, max(min_len, int(len(code) / ratio)))
    prompt = (
        f"Please summarize the main purpose and functionality of the given Python code using up to {length} characters. "
        f"Be concise! No need to explain python syntax or common practice."
        f"\n\nCode:\n{code}"
    )
    return ask_gptapi(prompt, chatbot)


def load_raw_code(file: Path) -> str:
    with open(Path(file).expanduser(), "r", encoding="utf-8") as source_file:
        return source_file.read()


def extract_code_info(raw_code: RawCode) -> tuple[str, list[dict]]:
    """Extract code units, imports, and assignments from the given file."""

    file = raw_code.file
    code_info = []
    code_units, imports, assignments = extract_code_units(raw_code.code)

    print(f"Length of code units: {len(code_units)}\n")
    for name, code in tqdm(code_units.items()):
        print(f"Code Unit {name}:\n")
        code_info.append(dict(file=file, name=name, code=code, summary=summarize_code(code, gpt3_bot)))
        sleep(1)  # avoid rate limit

    print("Imports:\n")
    code_info.append(
        dict(
            file=file,
            name="imports",
            code=imports,
            summary=summarize_code(imports, gpt3_bot),
        )
    )
    print("Assignments:\n")
    code_info.append(
        dict(
            file=file,
            name="assignments",
            code=assignments,
            summary=summarize_code(assignments, gpt3_bot),
        )
    )
    summary = "\n".join(i["summary"] for i in code_info)
    print(
        f"Original Code length: {len(raw_code)}\n"
        f"Extracted block num: {len(code_info)}\n"
        f"Extracted Code length: {len(summary)}\n"
    )
    return raw_code, code_info


def traverse_directory(directory_path: str | Path) -> list[str]:
    """Traverse the directory and return a list of python files."""
    directory_path = Path(directory_path).expanduser()
    python_files = []

    for p in directory_path.glob("**/*"):
        if not p.is_dir() and p.endswith(".py"):
            python_files.append(p.absolute().as_posix())

    return python_files


def parse_codebase(codebase_path: str | Path) -> tuple[dict[str, str], pd.DataFrame]:
    """Parse the codebase and return a list of codebase info."""
    python_files = traverse_directory(codebase_path)
    raw_codebase = {}
    codebase_info = []

    for file in python_files:
        try:
            raw_code, code_info = extract_code_info(file)
            raw_codebase[file] = raw_code
            codebase_info.extend(code_info)
        except Exception as e:
            print(f"Error parsing {file}: {e}")

    return raw_codebase, pd.DataFrame(codebase_info)
