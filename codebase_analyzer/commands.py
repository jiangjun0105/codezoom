import ast
import re
from functools import partial
from typing import Any, Callable

import pandas as pd
from loguru import logger

from codebase_analyzer import prompts
from codebase_analyzer.chatbot import Chatbot
from codebase_analyzer.embedding import search_functions

search_bot = Chatbot(
    name="search_bot",
    name_color="yellow",
    model="gpt-3.5-turbo",
    system_prompt=prompts.search_bot_system(),
)

function_bot = Chatbot(
    name="function_bot",
    name_color="yellow",
    model="gpt-3.5-turbo",
    system_prompt=prompts.function_bot_system(),
)


def ask_function(name: str, question: str, code_info: pd.DataFrame) -> str:
    """Ask a question about a specific function."""
    print(f"Getting function code for {name}...")
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
    return function_bot.ask(prompt=p, asked_by="codebase_bot")


def search_keyword(keyword: str, semantic_filer: str, raw_code: str) -> list[str]:
    """Search for a keyword in the codebase and filter using semantic_filer."""
    print(f"Searching for keyword '{keyword}'...")
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
    return search_bot.ask(prompt=p, asked_by="codebase_bot")


# - ask_function("<function_name>", "<question>")
#     to ask a question about a specific function.
#     E.g. ask_function("main", "What does this function do?")
# Please only run one command each time, and you can try several time.
# """


def get_relevant_functions(
    query: str,
    want: str = "summary",
    n: int = 1,
    codebase_info: pd.DataFrame | None = None,
) -> pd.DataFrame:
    print("Searching for relevant functions...")
    if codebase_info is None:
        logger.error("Codebase info is not provided.")
        return "Codebase info is not provided."
    res = search_functions(codebase_info, query, n=n)
    if want in res.columns:
        got = "\n".join(res[want])
        return f"Below is the {want} related to query:\n" + got
    else:
        logger.error(f"Cannot find {want} in the codebase info.")
        return f"Cannot find {want} in the codebase info."
    # for name, code in res.loc[["name", "code"]]:


def parse_function_call(function_call: str) -> tuple[str, list[str], dict[str, str]]:
    """Parse a function call string into a function name, a list of arguments, and a dictionary of keyword arguments."""
    # Parse the function call into an AST
    tree = ast.parse(function_call)

    # Check if the parsed code is a single function call
    if not isinstance(tree.body[0], ast.Expr) or not isinstance(
        tree.body[0].value, ast.Call
    ):
        raise ValueError(f"Invalid function string: {function_call}")

    # Extract the function name, positional arguments, and keyword arguments
    call_node = tree.body[0].value
    function_name = ast.unparse(call_node.func)
    # NOTE: Can only handle literals (e.g., numbers, strings, lists, dictionaries, etc.)
    args = [ast.literal_eval(ast.unparse(arg)) for arg in call_node.args]
    kwargs = {
        kwarg.arg: ast.literal_eval(ast.unparse(kwarg.value))
        for kwarg in call_node.keywords
    }

    return function_name, args, kwargs


def execute_function(function_map: dict[str, Callable], function_call: str) -> str:
    """Execute the function in Chatbot response string."""

    function_name, args, kwargs = parse_function_call(function_call)
    function = function_map.get(function_name)

    if function is None:
        raise ValueError(f"Unknown function: {function_name}")

    return function(*args, **kwargs)


def parse_response(response: str, function_map: dict[str, callable]) -> str:
    r = re.search(r"^Command: .*", response, re.MULTILINE)
    if r is None:
        logger.info("No command found in response.")
        return
    cmd = r.group(0).split("Command: ")[1]
    return execute_function(
        function_map=function_map,
        function_call=cmd,
    )
