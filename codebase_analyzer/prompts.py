"""Manages various prompts for the codebase analyzer bots."""

from __future__ import annotations

import pandas as pd

from codebase_analyzer.embedding import find_relevant_code_info


def main_bot_system(language="python"):
    return (
        f"You are an codebase analyzer bot. Human will ask you questions about a {language} codebase. "
        f"The codebase is too large to read, so the 3 most relevent functions and their summaries will be given to you.\n"
        + command_instruction()
        + response_format()
    )


def command_instruction():
    return """If you need more info, available commands are:

1. ask_function("<function_name_before_colon>", "<question>")
    to ask a question about a specific function.
    E.g. ask_function("main", "What does this function do?")
2. search_keyword("<keyword>", "<one_sentence_semantic_filter>")
    to search for a keyword and filter the results by the semantic_filter.
    E.g. search_keyword("URL", "only return the ones in module level")

Please only run one command each time, and you can try several time.
"""


def response_format():
    return """If need more info, your reply should look like:

Reasoning: <one_line_reasoning>
Command: <command_shown_above>

When answering, your reply should look like:

Answer: <your_final_answer>
"""


def question_prompt(question: str, codebase_info: pd.DataFrame) -> str:
    code_info = find_relevant_code_info(question, codebase_info)
    give_info = "\n".join(
        f"{n}: {s}" for n, s in code_info[["name", "summary"]].values
    )
    p = (
        f"The user asked: `{question}` "
        f"Below is the relevant functions and their summaries in the form of `function_name: summary`\n\n"
        + give_info
    )
    return p


def search_bot_system() -> str:
    return (
        "You are a helper bot for a codebase analyzer bot. "
        "You will be given code search results of a keyword, and you help filter the results with a given smentic filter."
    )


def function_bot_system() -> str:
    return (
        "You are a helper bot for a codebase analyzer bot. "
        "You wil answer questions about a specific function."
    )


def summary_bot_system(language: str = "Python") -> str:
    return (
        "You are a helper bot for a codebase analyzer bot. "
        f"You help summarize the main purpose and functionality of given {language} code using less than given length limitation."
        f"Be concise! No need to explain python syntax or common practice."
    )
