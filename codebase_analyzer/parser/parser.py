from __future__ import annotations

import ast
from ast import literal_eval
from dataclasses import dataclass
from pathlib import Path
from time import sleep

import pandas as pd
from langchain.chat_models import ChatOpenAI
from loguru import logger
from tqdm import tqdm

from codebase_analyzer.common.credentials import get_api_key
from codebase_analyzer.parser.ast_visitor import CodeExtractor
from codebase_analyzer.tools.embedding import embed_codebase


@dataclass
class RawCode:
    file: Path
    code: str


summary_bot = ChatOpenAI(
    temperature=0,
    model="gpt-3.5-turbo-0613",
    openai_api_key=get_api_key(),
    # streaming=True,
    # callbacks=[FinalStreamingStdOutCallbackHandler()],
    client=None,  # TODO: How to fix pydantic error?
)


def extract_code_units(
    code: str, threshold: int = 50
) -> tuple[dict[str, str], str, str]:
    """Extract code in unit of function or class from the given code."""
    tree = ast.parse(code)
    extractor = CodeExtractor(threshold)
    extractor.visit(tree)
    return extractor.code_units, extractor.imports, extractor.assignments


def summarize_code(
    code: str,
    # chatbot: Chatbot,
    ratio: float = 15,
    min_len=20,
    max_len=100,
) -> str:
    """Summarize the code using GPT chatbot."""
    length = min(max_len, max(min_len, int(len(code) / ratio)))
    prompt = (
        f"Summarize the following code using less than {length} chars:\n\n{code}"
    )
    return prompt


def load_raw_code(file: Path) -> str:
    with open(Path(file).expanduser(), "r", encoding="utf-8") as source_file:
        return source_file.read()


def load_cached_codebase_info(
    path: str | Path, auto_embedding: bool = False
) -> pd.DataFrame:
    """Load cached codebase info from the given csv file."""
    codebase_info = pd.read_csv(path).set_index("Unnamed: 0")
    logger.info(f"Loaded codebase info from {path}")
    if "embedding" not in codebase_info.columns and auto_embedding:
        logger.info("Embeddings not found in cache, embedding codebase...")
        embed_codebase(codebase_info)
    else:
        # TODO: Use format supporting storing the embedding
        codebase_info["embedding"] = codebase_info["embedding"].apply(literal_eval)
    return codebase_info


def extract_code_info(file_path: Path) -> tuple[RawCode, list[dict]]:
    """Extract code units, imports, and assignments from the given file."""
    # TODO: Improve this function and rethink about RawCode class
    file_path = Path(file_path).expanduser()
    raw_code = RawCode(file=file_path, code=load_raw_code(file_path))
    code_info = []
    code_units, imports, assignments = extract_code_units(raw_code.code)

    print(f"Length of code units: {len(code_units)}\n")
    for name, code in tqdm(code_units.items()):
        print(f"Code Unit {name}:\n")
        code_info.append(
            dict(
                # file=file_path,
                name=name,
                code=code,
                summary=summarize_code(code, summary_bot),
            ),
        )
        sleep(1)  # avoid rate limit

    print("Imports:\n")
    code_info.append(
        dict(
            # file=file,
            name="import statements",
            code=imports,
            summary=summarize_code(imports, summary_bot),
        )
    )
    print("Assignments:\n")
    code_info.append(
        dict(
            # file=file,
            name="file level assignments",
            code=assignments,
            summary=summarize_code(assignments, summary_bot),
        )
    )
    summary = "\n".join(i["summary"] for i in code_info)
    print(
        f"Original Code length: {len(raw_code.code)}\n"
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
            raw_code, code_info = extract_code_info(Path(file))
            raw_codebase[file] = raw_code
            codebase_info.extend(code_info)
        except Exception as e:
            print(f"Error parsing {file}: {e}")

    return raw_codebase, pd.DataFrame(codebase_info)
