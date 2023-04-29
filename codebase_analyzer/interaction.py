from __future__ import annotations

# %%
import openai
from pathlib import Path
from yaml import safe_load
from revChatGPT.V1 import Chatbot
from time import sleep
import re
import pandas as pd

from codebase_analyzer.analyze_tools import execute_function
from codebase_analyzer.chatbot import chatgpt4_main


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
        except:
            print(f"HTTPError: Retrying... will retry {retry} times.")
            sleep(1)

    for data in response:
        message = data["message"]
        print(message[last_len:], end="", flush=True)
        last_len = len(message)
    print()
    return message


def parse_response(response: str, code_info: pd.DataFrame, raw_code: str):
    try:
        r = safe_load(response)
        cmd = r["Command"]
        return "Command return: " + execute_function(command=cmd, code_info=code_info, raw_code=raw_code)
    except:
        print("No command or answer found in response, try to remind it by sending the response format again.")
        return """Reminder: 
You are suppose to aswer question: "{question}"

If you need more info, your response should look like:

Reasoning: <one_line_reasoning>
Command: <command_shown_above>

Command could be:
1. ask_function("<function_name>", "<question>") 
    to ask a question about a specific function.
2. search_keyword("<keyword>", "<semantic_filter_in_quotes>")
    to search for a keyword and filter the results by the semantic_filter.

Please only run one command each time, and you can run several times. When answering, please start your response with 'Answer: '."""


# %%
def ask_codebase(question: str, codebase_info: pd.DataFrame, raw_codebase: str, chatbot = chatgpt4_main) -> str:
    instructions = f"""Below is a summary of a long python file in format 'function_name: summary'. Please answer question: "{question}"  

    If you need more info, available commands are:
    1. ask_function("<function_name>", "<question>") 
        to ask a question about a specific function.
    2. search_keyword("<keyword>", "<semantic_filter_in_quotes>")
        to search for a keyword and filter the results by the semantic_filter.

    Your response should look like:
    Reasoning: <one_line_reasoning>
    Command: <command_shown_above>

    Please only run one command each time, and you can try several times before you answer the user's question. When you are ready to answer, plaase start your response with 'Answer: '.
    """
    reminder = f"""
---
Reminder: Don't forget to answer the user's question: "{question}".
Also you can continue run command following the provided formats.
If you forget the provided formats, say '!help!' to get it again.
    """
    p = instructions + "\n".join(f"{n}: {c}" for n, c in codebase_info[["name", "summary"]].values)
    while True:
        response = ask_chatbot(prompt=p, chatbot=chatbot)
        if answer := re.search(r'^Answer: .*', response, re.MULTILINE):
            return answer
        p = parse_response(response, codebase_info, raw_codebase)# + reminder
