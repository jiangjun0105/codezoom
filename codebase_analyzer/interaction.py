from __future__ import annotations

import re
from time import sleep

import pandas as pd
from revChatGPT.V1 import Chatbot
from yaml import safe_load

from codebase_analyzer.analyze_tools import execute_function
from codebase_analyzer.chatbot import chatgpt4_main

MAIN_PROMPT = """
Please answer question: "{question}"

If you need more info, available commands are:
1. ask_function("<function_name>", "<question>")
    to ask a question about a specific function.
2. search_keyword("<keyword>", "<semantic_filter_in_quotes>")
    to search for a keyword and filter the results by the semantic_filter.

Your response should look like:
Reasoning: <one_line_reasoning>
Command: <command_shown_above>

Please only run one command each time, and you can try several time. 
When answering, plaase start your response with 'Answer: '.
"""


def ask_chatbot(prompt: str, chatbot: Chatbot) -> str:
    """Ask a question to the chatbot and return the response."""
    print(f"User: {prompt}")
    print("Chatbot:\n")
    last_len = 0
    retry = 5

    while retry > 0:
        retry -= 1
        try:
            response = chatbot.ask(prompt)
        except Exception as e:
            print(f"Exception: {e}")
            print(f"HTTPError: Retrying... will retry {retry} times.")
            sleep(1)

    for data in response:
        message = data["message"]
        print(message[last_len:], end="", flush=True)
        last_len = len(message)
    print()
    return message


def parse_response(response: str, code_info: pd.DataFrame, raw_code: str):
    r = safe_load(response)
    cmd = r["Command"]
    return execute_function(command=cmd, code_info=code_info, raw_code=raw_code)


# %%
def ask_codebase(
    question: str,
    codebase_info: pd.DataFrame,
    raw_codebase: str,
    chatbot=chatgpt4_main,
    max_iteration: int = 4,
) -> str:
    code_summary = "\n".join(f"{n}: {c}" for n, c in codebase_info[["name", "summary"]].values)
    instruction = f"""Below is a summary of a long python file in format 'function_name: summary'.\n\n{code_summary}\n\n"""
    p = instruction + MAIN_PROMPT.format(question=question)

    while max_iteration > 0:
        max_iteration -= 1
        response = ask_chatbot(prompt=p, chatbot=chatbot)
        if answer := re.search(r"^Answer: .*", response, re.MULTILINE):
            return answer
        try:
            p = "Command return: " + parse_response(response, codebase_info, raw_codebase)
        except KeyError:
            print(
                "No command or answer found in response, try to remind it by sending the response format again."
            )
            p = "Reminder: " + MAIN_PROMPT.format(question=question)


# %%
