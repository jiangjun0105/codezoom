# %%
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from langchain.chains import LLMChain
from langchain.chat_models import ChatOpenAI
from langchain.prompts import (
    AIMessagePromptTemplate,
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain.schema import AIMessage, BaseMessage, HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel, Field, root_validator

from codebase_analyzer.flowchart.process import ask_gpt, generate_by_chain

OVERALL_SYSTEM = """
# Instructions
You are an expert in analyzing the process logics of programming languages. You
will help to convert a large program into a flowchart. The large program is
already divided into small snippets based on its abstract syntax tree structure,
and each snippet should be converted into a node in the flowchart.

Given a single snippet, your job is to analyze and summarize the processing
logic of the given code. In some cases, additional information is provided to help you
understand the code, including the summary of functions called in the code, and
the summary of variables used in the code.

NOTE: Your summary will be used as the label of the node in the flowchart, so it
should be brief so that it can be displayed in the flowchart. Also, don not use
any IT jargons as the readers may not understand programming at all.
"""

PROCESS_EXAMPLE_INPUT1 = """
# Example Input
Code from the function `plan` in file `gpt_coder/task.py`.

```python
actions = some_function()
```

* `some_function`: Calculate what actions needed to be done when given a task.
"""

PROCESS_EXAMPLE_OUTPUT1 = (
    """Save the actions needed to be done to the variable `actions`."""
)


PROCESS_EXAMPLE_INPUT2 = """
# Example Input
Code from the function `agent_action` in file `gpt_coder/agent.py`.

```python
    processed = []
    for c in commands:
        c = convert_format(c)
        processed.append(c)
```

* `convert_format` (function): Convert the format of the command `c` to the format required by OpenAI if it's not already that format.
"""

PROCESS_EXAMPLE_OUTPUT2 = (
    "Convert the format of all commands to the format required by OpenAI."
)


RPOECSS_ACTUAL_INPUT_TEMPLATE = """
# Actual Input
Code from the function `{function_name}` in file `{file_name}`.

```python
{code}
```

{summaries}
"""


PROCESS_PROMPT_SET = [
    SystemMessage(
        additional_kwargs=dict(name="overall_instructions"),
        content=OVERALL_SYSTEM,
    ),
    HumanMessage(
        additional_kwargs=dict(name="example_input1"),
        content=PROCESS_EXAMPLE_INPUT1,
    ),
    AIMessage(
        additional_kwargs=dict(name="example_output1"),
        content=PROCESS_EXAMPLE_OUTPUT1,
    ),
    HumanMessage(
        additional_kwargs=dict(name="example_input2"),
        content=PROCESS_EXAMPLE_INPUT2,
    ),
    AIMessage(
        additional_kwargs=dict(name="example_output2"),
        content=PROCESS_EXAMPLE_OUTPUT2,
    ),
    HumanMessagePromptTemplate.from_template(
        additional_kwargs=dict(name="actual_input"),
        template=RPOECSS_ACTUAL_INPUT_TEMPLATE,
    ),
]

REFINE_TEXT_TEMPLATE = """The following is an assembled sentence by a program, \
please refine it to make it natural and concise but still keep the original \
meaning:

{text}
"""
REFINE_TEXT_PROMPT = [
    SystemMessagePromptTemplate.from_template(
        template=REFINE_TEXT_TEMPLATE,
    )
]

SUMMARIZE_LABELS_TEMPLATE = """The following is a description of some process \
using  mix of human language and python syntax. Please help to summarize its \
major processes into one sentence using less than 30 words \

{labels}

NOTE: No need to say "The process ..." at the beginning, say the content directly.
"""

SUMMARIZE_LABELS_PROMPT = [
    SystemMessagePromptTemplate.from_template(
        template=SUMMARIZE_LABELS_TEMPLATE,
    )
]

if __name__ == "__main__":
    output_key = "process"
    code = """
assistant_thought = some_function()
if assistant_thought:
       logger.speak(assistant_thought)
    """
    inputs = dict(
        # summaries = "None",
        code=code,
        function_name="ConfigBuilder.build_config_from_env",
        file_name="auto_gpt/config/config.py",
        # function_summary = 'This code defines a class method `build_config_from_env` that builds a configuration object based on environment variables.',
        summaries="""
* `some_function`: Remove formatting codes from the assistant's text.
* `logger.speak`: print the inputs in green color in terminal
""",
    )
    text = """Check if the condition "'the text-to-speech provider is ElevenLabs." is True """
    output_path = Path(__file__).parent / "process_debug"
    generate_by_chain(
        # messages=PROCESS_PROMPT_SET,
        # inputs=inputs,
        messages=REFINE_TEXT_PROMPT,
        inputs=dict(text=text),
        output_key=output_key,
        output_path=output_path,
        call_api=True,
        model="gpt-4-1106-preview",
        # model="gpt-4",
        # model="gpt-3.5-turbo",
    )
# %%
