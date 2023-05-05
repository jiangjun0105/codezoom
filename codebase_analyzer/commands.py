import re
from functools import partial

import pandas as pd

from codebase_analyzer.chatbot import function_bot, search_bot
from codebase_analyzer.embedding import search_functions


def _ask_function(name: str, question: str, code_info: pd.DataFrame) -> str:
    """Ask a question about a specific function."""
    print(f"Getting function code for {name}...\n")
    try:
        code = code_info.loc[code_info["name"] == name, "code"].values[0]
    except IndexError:
        return (
            "Cannot find the function in the codebase. Maybe wrong function name.\n"
        )
    p = (
        f"Code for function {name}:\n{code}\n\n"
        f"Question: {question}\n"
        f"Please answer the question or return relavent code concisely.\n"
    )
    return function_bot.ask(prompt=p)


def _search_keyword(keyword: str, semantic_filer: str, raw_code: str) -> list[str]:
    """Search for a keyword in the codebase and filter using semantic_filer."""
    print(f"Searching for keyword '{keyword}'...\n")
    result = [
        f"{i}: {line}"
        for i, line in enumerate(raw_code.split("\n"), 1)
        if keyword in line
    ]
    if len(result) == 0:
        return f"No result found for keyword '{keyword}'\n"
    if not semantic_filer:
        return "\n".join(result)
    p = (
        f"Code search result of keyword '{keyword}':\n" + "\n".join(result) + "\n"
        f"The given semantic filter is: {semantic_filer}\n"
        f"Please help find the relavent code or provide other helpful info.\n"
    )
    return search_bot.ask(prompt=p)


def _get_relevant_functions(
    query: str, column: str, n: int, codebase_info: pd.DataFrame
) -> pd.DataFrame:
    if column not in ["code", "summary"]:
        return f"Unknown column: {column}, use 'code' or 'summary' instead."
    print("Searching for relevant functions...")
    res = search_functions(codebase_info, query, n=n)
    got = "\n".join(f"{n}: {s}" for n, s in res[["name", column]].values)
    return (
        f"Below is the {n} relevant functions and their summaries in the form of `function_name: summary`\n\n"
        + got
    )


def parse_function_call(function_call: str) -> tuple[str, list[str]]:
    """Parse a function call string into a function name and a list of arguments."""
    function_pattern = re.compile(r"(\w+)\((.*)\)")
    match = function_pattern.match(function_call)

    if not match:
        raise ValueError(f"Invalid function string: {function_call}")

    function_name = match.group(1)
    args_string = match.group(2)

    arg_pattern = re.compile(r"\"([^\"]*)\"|\'([^\']*)\'")
    arg_list = [
        match.group(1) or match.group(2)
        for match in arg_pattern.finditer(args_string)
    ]

    return function_name, arg_list


def execute_function(function_call: str, code_info, raw_code) -> str:
    """Execute the function in Chatbot response string."""
    ask_function = partial(_ask_function, code_info=code_info)
    search_keyword = partial(_search_keyword, raw_code=raw_code, semantic_filer="")
    get_relevant_functions = partial(
        _get_relevant_functions, n=1, codebase_info=code_info, column="code"
    )

    function_map = {
        "ask_function": ask_function,
        "search_keyword": search_keyword,
        "get_relevant_functions": get_relevant_functions,
    }

    function_name, args = parse_function_call(function_call)
    function = function_map.get(function_name)

    if function is None:
        raise ValueError(f"Unknown function: {function_name}")

    return function(*args)
