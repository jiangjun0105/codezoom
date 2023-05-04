from __future__ import annotations

import re

import pandas as pd
from loguru import logger

from codebase_analyzer import prompts
from codebase_analyzer.chatbot import Chatbot, main_bot
from codebase_analyzer.commands import execute_function


def parse_response(response: str, code_info: pd.DataFrame, raw_code: str):
    r = re.search(r"^Command: .*", response, re.MULTILINE)
    cmd = r.group(0).split("Command: ")[1]
    return execute_function(
        function_call=cmd, code_info=code_info, raw_code=raw_code
    )


def ask_codebase(
    question: str,
    codebase_info: pd.DataFrame,
    raw_codebase: str,
    chatbot=main_bot,
    max_iteration: int = 4,
) -> str:
    """Main loop for interaction between AI bots on codebase questions."""
    code_summary = "\n".join(
        f"{n}: {c}" for n, c in codebase_info[["name", "summary"]].values
    )
    # TODO: Not send summary everytime.
    instruction = (
        f"Below is a summary of python code in format 'function_name: summary':"
        f"\n\n{code_summary}\n\n"
    )
    p = instruction + prompts.question_prompt(question=question)

    while max_iteration > 0:
        max_iteration -= 1
        response = chatbot.ask(prompt=p)
        # response = ask_chatbot(prompt=p, chatbot=chatbot)
        if answer := re.search(r"^Answer:.*", response, re.MULTILINE):
            return answer
        try:
            p = "Command return:\n" + parse_response(
                response, codebase_info, raw_codebase
            )
        except AttributeError:
            logger.error(
                "No command or answer found in response, try to remind it by sending the response format again."
            )
            return response


def remind_mission(chatbot: Chatbot = main_bot) -> None:
    """Remind the chatbot of its response format."""
    p = "Reminder: \n" + prompts.response_format()
    chatbot.ask(prompt=p, chatbot=chatbot)
