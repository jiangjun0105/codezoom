from __future__ import annotations

import ast
from ast import literal_eval
from dataclasses import dataclass
from pathlib import Path
from time import sleep

import pandas as pd
from loguru import logger
from tqdm import tqdm

from codebase_analyzer import prompts
from codebase_analyzer.ast_visitor import CodeExtractor
from codebase_analyzer.chatbot import Chatbot
from codebase_analyzer.embedding import embed_codebase


@dataclass
class RawCode:
    file: Path
    code: str


summary_bot = Chatbot(
    name="summary_bot",
    name_color="yellow",
    model="gpt-3.5-turbo",
    system_prompt=prompts.summary_bot_system(),
)


def extract_code_units(
    code: str, threshold: int = 50
) -> tuple[dict[str, str], list[str], list[str]]:
    """Extract code in unit of function or class from the given code."""
    tree = ast.parse(code)
    extractor = CodeExtractor(threshold)
    extractor.visit(tree)
    return extractor.code_units, extractor.imports, extractor.assignments


def summarize_code(
    code: str,
    chatbot: Chatbot,
    ratio: float = 15,
    min_len=20,
    max_len=100,
) -> str:
    """Summarize the code using GPT chatbot."""
    length = min(max_len, max(min_len, int(len(code) / ratio)))
    prompt = (
        f"Summarize the following code using less than {length} chars:\n\n{code}"
    )
    return chatbot.ask(prompt, chatbot)


def load_raw_code(file: Path) -> str:
    with open(Path(file).expanduser(), "r", encoding="utf-8") as source_file:
        return source_file.read()


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


def extract_code_info(raw_code: RawCode) -> tuple[str, list[dict]]:
    """Extract code units, imports, and assignments from the given file."""

    file = raw_code.file
    code_info = []
    code_units, imports, assignments = extract_code_units(raw_code.code)

    print(f"Length of code units: {len(code_units)}\n")
    for name, code in tqdm(code_units.items()):
        print(f"Code Unit {name}:\n")
        code_info.append(
            dict(
                file=file,
                name=name,
                code=code,
                summary=summarize_code(code, summary_bot),
            ),
        )
        sleep(1)  # avoid rate limit

    print("Imports:\n")
    code_info.append(
        dict(
            file=file,
            name="imports",
            code=imports,
            summary=summarize_code(imports, summary_bot),
        )
    )
    print("Assignments:\n")
    code_info.append(
        dict(
            file=file,
            name="assignments",
            code=assignments,
            summary=summarize_code(assignments, summary_bot),
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
