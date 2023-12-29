from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from loguru import logger

from codebase_analyzer.flowchart.process.schema import Process


def add_lineno_to_process(
    processes: list[Process], index_to_lineno, code: list[str] = None
):
    for process in processes:
        index = process.index

        if index and index in index_to_lineno:
            linenos = index_to_lineno[index]
            process.code_lineno = linenos

        if code and process.code_lineno:
            my_code = []
            for lineno in process.code_lineno:
                if lineno >= len(code):
                    logger.warning(
                        f"Line number {lineno} is out of range of the code {len(code)}."
                    )
                my_code.append(code[lineno])
            process.code = "\n".join(my_code)

        add_lineno_to_process(process.subprocesses, index_to_lineno, code=code)


def add_code_lineno(process: Process, csv_file: str, code: str) -> None:

    code = code.split("\n")
    df = pd.read_csv(csv_file)
    df = df.rename(columns=lambda x: x.strip())
    df["process_index"] = df["process_index"].str.strip().str.strip('"')

    index_to_lineno = (
        df.groupby("process_index")["code_lineno"].apply(list).to_dict()
    )

    add_lineno_to_process(process.subprocesses, index_to_lineno, code=code)
    return process
