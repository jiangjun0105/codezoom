"""Manages various prompts for the codebase analyzer bots."""

from __future__ import annotations


def init_system_prompt(language="python"):
    return (
        f"""You are an codebase analyzer bot. Human will ask you questions about a {language} codebase."""
        + command_instruction()
        + response_format()
    )


def command_instruction():
    return """If you need more info, available commands are:

1. ask_function("<function_name_before_colon>", "<question>")
    to ask a question about a specific function.
2. search_keyword("<keyword>", "<semantic_filter>")
    to search for a keyword and filter the results by the semantic_filter.

Please only run one command each time, and you can try several time.
"""


def response_format():
    return """If need more info, your reply should look like:

Reasoning: <one_line_reasoning>
Command: <command_shown_above>

When answering, your reply should look like:

Answer: <your_final_answer>
"""


def question_prompt(question: str) -> str:
    return f"Please answer question: {question}"
