import re
from functools import partial

import pandas as pd

from codebase_analyzer.chatbot import chatgpt3, chatgpt4_sub
from codebase_analyzer.interaction import ask_chatbot


def _ask_function(name: str, question: str, code_info: pd.DataFrame) -> str:
    """Ask a question about a specific function."""
    # print(f"Getting function code for {name}...\n")
    code = code_info.loc[code_info["name"] == name, "code"].values[0]
    p = (
        f"Below is the code for function {name}:\n{code}\n\n"
        f"User has question: {question}\n"
        f"Please answer the user's question or return relavent code concisely.\n"
    )
    return ask_chatbot(prompt=p, chatbot=chatgpt4_sub)


def _search_keyword(keyword: str, semantic_filer: str, raw_code: str) -> list[str]:
    """Search for a keyword in the codebase and filter using semantic_filer."""
    print(f"Searching for keyword '{keyword}'...\n")
    result = [f"{i}: {line}" for i, line in enumerate(raw_code.split("\n"), 1) if keyword in line]
    if len(result) == 0:
        return "No result found for keyword '{keyword}'\n"
    p = (
        f"Below are the lines that contain keyword '{keyword}':\n"
        f"{''.join(result)}\n\n"
        f"User only wants: {semantic_filer}\n"
        f"Please filter the search result and only return relavent code.\n"
    )
    return ask_chatbot(prompt=p, chatbot=chatgpt3)


def parse_function_call(function_call: str) -> tuple(str, list[str]):
    """Parse a function call string into a function name and a list of arguments."""
    function_pattern = re.compile(r"(\w+)\((.*)\)")
    match = function_pattern.match(function_call)

    if not match:
        raise ValueError(f"Invalid function string: {function_call}")

    function_name = match.group(1)
    args_string = match.group(2)

    arg_pattern = re.compile(r"\"([^\"]*)\"|\'([^\']*)\'")
    arg_list = [match.group(1) or match.group(2) for match in arg_pattern.finditer(args_string)]

    return function_name, arg_list


def execute_function(function_call: str, code_info, raw_code) -> str:
    """Execute the function in Chatbot response string."""
    ask_function = partial(_ask_function, code_info=code_info)
    search_keyword = partial(_search_keyword, raw_code=raw_code)

    function_map = {
        "ask_function": ask_function,
        "search_keyword": search_keyword,
    }

    function_name, args = parse_function_call(function_call)
    function = function_map.get(function_name)

    if function is None:
        raise ValueError(f"Unknown function: {function_name}")

    return function(*args)
