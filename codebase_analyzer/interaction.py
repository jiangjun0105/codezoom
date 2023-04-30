from __future__ import annotations

import re
from time import sleep

import pandas as pd
import yaml

from codebase_analyzer import prompts
from codebase_analyzer.analyze_tools import execute_function
from codebase_analyzer.chatbot import ask_gptapi, gpt3_bot, gpt4_bot


def parse_response(response: str, code_info: pd.DataFrame, raw_code: str):
    r = re.search(r"^Command: .*", response, re.MULTILINE)
    cmd = r.group(0).split("Command: ")[1]
    return execute_function(function_call=cmd, code_info=code_info, raw_code=raw_code)


def ask_codebase(
    question: str,
    codebase_info: pd.DataFrame,
    raw_codebase: str,
    chatbot=gpt4_bot,
    max_iteration: int = 4,
) -> str:
    code_summary = "\n".join(f"{n}: {c}" for n, c in codebase_info[["name", "summary"]].values)
    instruction = (
        f"Below is a summary of a long python file in format 'function_name: summary'."
        f"\n\n{code_summary}\n\n"
    )
    p = instruction + prompts.question_prompt(question=question)

    while max_iteration > 0:
        max_iteration -= 1
        response = ask_gptapi(prompt=p, chatbot=chatbot)
        if answer := re.search(r"^Answer:.*", response, re.MULTILINE):
            return answer
        try:
            p = "Command return:\n" + parse_response(response, codebase_info, raw_codebase)
            print(p)
        except KeyError:
            print(
                "No command or answer found in response, try to remind it by sending the response format again."
            )
            p = "Reminder: " + prompts.response_format()
