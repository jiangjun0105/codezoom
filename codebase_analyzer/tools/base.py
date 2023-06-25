"""This file contains the tools that can be used by the bot.

IMPORTANT NOTE:
Function docstrings and argument type annotations & descriptions are utilized
as instructions for the LLM models. Therefore, it is crucial to approach them
with seriousness, ensuring docstrings and descriptions are composed in an
instructive tone for the model, and that argument types are specified using
Pydantic's type annotations.
"""

import importlib.util
import inspect
import subprocess
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Callable

import pandas as pd
from loguru import logger
from pydantic import Field

from codebase_analyzer.tools.embedding import search_functions
from codebase_analyzer.tools.token import tokenize


def get_file_summary(
    file_path: Annotated[Path | str, Field(description="Path to the file.")]
) -> str:
    """For getting the summary of the file managed by this bot."""
    # FIXME: this is just a fake function.
    return f"""The file ({file_path}) implements a command-line interface (CLI) for an AI chatbot, specifically OpenAI's ChatGPT. It contains Chatbot and AsyncChatbot classes responsible for managing chat sessions, logging in, sending messages, fetching conversation history, and handling other conversation details. It also includes methods for caching tokens, checking credentials, managing conversations, and handling responses. The main function manages user interaction with the CLI, controlling the conversation flow. Additionally, decorators for logging and several utilities for cache management, chat reset, and conversation rollback are present. It serves as a comprehensive tool for customizable interaction with an AI chatbot."""


def ask_function_bot(
    question: Annotated[
        str, Field(description="Question to ask to the function bot")
    ],
    function_name: Annotated[
        str, Field(description="Which function your question is about.")
    ],
    file_path: Annotated[
        Path, Field(description="Path to the file containing the function.")
    ],
    get_bot_func: Annotated[
        Callable, Field(description="Function to get the function bot.")
    ],
) -> str:
    """For asking a question to a function bot knowing the code of a specific function.
    Consider using this method first before using `get_function_code` when the function code length > 10 lines.
    Also remember include enough information in the question so that the bot can give you a good answer."""

    function_bot = get_bot_func(file_path=file_path, function_name=function_name)
    return function_bot.ask(question)


def get_function_summaries(
    code_info: Annotated[
        pd.DataFrame, Field(description="Extracted codebase info in pd.dataframe.")
    ]
    # file_path: Annotated[Path | str, Field(description="Path to the file.")]
) -> str:
    """For getting the summaries of all functions in this file."""
    # FIXME: this is just a fake function.
    return """This file contains the following functions or methods (Note this is just a brief introduction, please refer to the source code for more details):

__main__: This code checks if the file is being run as a script and then starts the ChatGPT command-line interface, printing some introductory messages and calling the main function with the configuration dictionary.

Chatbot: The Chatbot class is responsible for handling chatbot functionalities such as logging in, sending messages, managing conversations, and getting conversation history. The class also has methods for caching and checking credentials, setting up session tokens and access tokens, writing and reading from cache, sending requests to OpenAI's API, checking message content and responses, retrieving conversation details and their histories, generating and changing conversation titles, deleting and clearing conversations, mapping conversations, resetting chats and rolling back conversations.

AsyncChatbot: The AsyncChatbot class, inheriting the Chatbot class, includes async functionalities for posting messages, asking questions, continuing writing, getting conversations, managing message histories, handling conversation titles, deleting conversations, and clearing all conversations.

configure: This code reads configuration from various places and returns it as a dictionary.

main: This Python code defines the main function for a chatbot program, which handles user input, commands and chatbot responses. It also includes commands such as resetting the chat session, displaying the current configuration, rolling back conversation and changing conversation. A logger is used to log the chat session.

imports: This Python code imports various modules, including httpx, json, typing, and requests. It also defines some utilities and logging functionality.

assignments: The code initializes a logger, sets the base URL, and decorates the 'get_input' function.

logger: The given code defines a decorator function named 'logger'. It takes a boolean parameter 'is_timed' and returns a decorated function. The decorator logs the function name, arguments, and return value when the decorated function is called. If 'is_timed' is True, the decorator also logs the time taken by the decorated function to complete.

"""


def get_function_code(
    function_name: Annotated[
        str, Field(description="Name of the function whose code will be returned.")
    ],
    # file_path: Annotated[Path | str, Field(description="Path to the file containing the function.")],
    code_info: Annotated[
        pd.DataFrame, Field(description="Extracted codebase info in pd.dataframe.")
    ],
) -> str:
    """For getting the code of a specific function. For class methods, use `class_name.method_name` as function_name."""
    result = code_info.loc[
        code_info["name"] == function_name,
        "code",
    ]
    if result.empty:
        return f"Cannot find the function {function_name}."
    return f"{result.values[0]}\n\n"


class CodeLengthUnit(str, Enum):
    CHAR = "char"
    LINE = "line"
    TOKEN = "token"


def get_code_length(code: str, unit: CodeLengthUnit) -> int:
    """For getting the length of the code."""
    if unit == CodeLengthUnit.CHAR:
        return len(code)
    elif unit == CodeLengthUnit.LINE:
        return len(code.split("\n"))
    elif unit == CodeLengthUnit.TOKEN:
        return len(tokenize(code))
    else:
        raise ValueError(f"Unknown unit {unit}.")


def get_related_functions(
    query: Annotated[
        str,
        Field(
            description="Functions having semantic similarity to this query will be returned, so please include enough semantic information in your query."
        ),
    ],
    want: str = "name",
    n: Annotated[
        int, Field(description="Number of function names to be returned.", default=5)
    ] = 5,
    code_info: pd.DataFrame | None = None,
    length_unit: CodeLengthUnit = CodeLengthUnit.TOKEN,
) -> str:
    """For getting the name of related functions based on the semantic similarity of the function code and your input query.
    Semantic similarity is the vector distance of embeddings, so please include enough semantic information in your query.
    E.g. get_relevant_functions("Completions API test", "code")  # returns function code most relevant to "Completions API test"
    """

    # logger.info("Searching for relevant functions...")
    if code_info is None:
        logger.error("Codebase info is not provided.")
        return "Codebase info is not provided."

    res = search_functions(code_info, query, n=n)

    if want not in res.columns:
        logger.error(f"Cannot find {want} in the codebase info.")
        return f"Cannot find {want} in the codebase info."

    got_list = [f"name, code length ({length_unit})", "============="]
    for w, c in zip(res[want], res["code"]):
        # TODO: The best way of getting code length is to calculate length once when parsing codebase info,
        # store it in the cache and then retrieve it here. For that we need refactor the cache structure.
        got_list.append(f"{w}, {get_code_length(c, length_unit)}")
    return "\n".join(got_list) + "\n\n"


def get_directory_tree(
    path: Annotated[
        str | Path,
        Field(
            description="Path to the directory whose tree will be returned. './' is the root directory."
        ),
    ],
    level: Annotated[
        int,
        Field(description="Level of the directory tree to be returned.", default=1),
    ],
    # TODO: How to provide default value for root_path? Maybe using kwargs of the tools?
    root_path: Path | None = None,
) -> str:
    """To get the directory tree of the given codebase.
    Recommend to set level to 1 or 2 to prevent the output exceed your context window.
    E.g. directory_tree(path="./", level=2)
    """
    if not root_path:
        # TOOD: for now this shouldn't happen but later may change to let bot
        # ask user to provide codebase root directory
        raise ValueError("root_path is not provided.")

    path = Path(path).expanduser()
    # logger.info(f"Getting directory tree of {path}...")
    if not path.exists():
        return f"Path {path} doesn't exist."
    if not path.is_dir():
        return f"Path {path} is not a directory."
    if level < 1:
        return "Level should be greater than 0."
    try:
        # Catch output of tree command and return it
        return subprocess.check_output(
            ["tree", "-L", str(level), str(path)], cwd=root_path
        ).decode()
    except subprocess.CalledProcessError as e:
        return f"Error when running tree command: {e}"


def get_file_content(
    path: Annotated[
        str | Path,
        Field(
            description="Path to the file whose content will be returned. './' is the root directory."
        ),
    ],
    # TODO: How to provide default value for root_path?
    root_path: Path | str | None = None,
) -> str:
    """To get the content of the given file."""

    if not root_path:
        # TOOD: for now this shouldn't happen but later may change to let bot
        # ask user to provide codebase root directory
        raise ValueError("root_path is not provided.")

    path = (Path(root_path) / Path(path)).expanduser()
    # logger.info(f"Getting content of {path}...")
    if not path.exists():
        return f"Path {path} doesn't exist."
    if not path.is_file():
        return f"Path {path} is not a file."
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error when reading file: {e}"


def load_single_function(file_path: Path, function_name: str):
    """Load code of a specific function given the function location."""
    file_path = Path(file_path).expanduser()
    if not file_path.exists():
        raise ValueError(f"File {file_path} does not exist.")

    spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
    if spec is None:
        raise ValueError(f"Cannot load file {file_path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, function_name)
    function_code = inspect.getsource(function)
    return function_code


# FIXME: This function is not used yet and won't work, but we will need a search tool.
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
    return p
    # return search_bot.ask(prompt=p, asked_by="codebase_bot")
