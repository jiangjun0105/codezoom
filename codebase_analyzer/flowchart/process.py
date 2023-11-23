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

from codebase_analyzer.bots.callbacks import BotStreamingStdOutCallbackHandler
from codebase_analyzer.flowchart.datamodel import (
    ActionPattern,
    ElifPattern,
    ElsePattern,
    ExitPattern,
    IfPattern,
    LoopPattern,
    Process,
)
from codebase_analyzer.flowchart.utils import _output_path
from codebase_analyzer.parser.codeinfo import check_state, update_state
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode
from codebase_analyzer.parser.uri import URI, uri_stem

REPO_ROOT = Path(__file__).parent.parent.parent
CACHE_ROOT = REPO_ROOT / "shared_cache"
LOCAL_ROOT = REPO_ROOT / ".local"

OVERALL_SYSTEM = """
You are an expert in analyzing the process logics of programming languages.
"""
# 1. You need to omit/simplify the unimportant processes or implementation details \
# and extract the major logics,

# TODO: We need a more robust way to ensure GPT follows the rule that subprocesses of if/elif/loop are in child-level.
GENERATE_PROCESS_INSTRUCTIONS = """
First, the target code and the summaries of functions called in the target code are given. Please \
analyze the purpose of the code and extract the main processes. \

Several Notes:
1. The purpose should be brief and general, shouldn't include too much process details.
1. Every process should has an index in format `x.y.z`. Ensure the indexes follow the rules:
    * Continuous: `x`'s next index must be `x+1`, also `x.y`'s next must be `x.y+1`.
    * Hierarchical: `x.y.z`'s children must be `x.y.z.1`, `x.y.z.2`, etc.
1. Put the processes in  branches of if/else or inside loop to a child-level with more indentations, e.g:
    ```python
    if condition:
        true_process
    else:
        false_process
    ```
    should be converted to:
    ```md
    1. **condition**: if condition:
        1.1 **true_process**: true_process
    2. **else**: else:
        2.2 **false_process**: false_process

1. Ensure the hierarchy of the process matches the hierarchy of the code, i.e. the processes under if/else/loop should be sub-processes of the if/else/loop process.
"""

GENERATE_PROCESS_EXAMPLE_INPUT = """
# TARGET FUNCTION CODE

```python
def process_commands(commands):
    if not commands:
        return []

    processed = []
    for c in commands:
        c = convert_format(c)
        if not c.is_valid():
            c = fix_command(c)
        processed.append(c)
    return processed
```

# REFERENCES

Summary of functions/class methods called by the above code:

* convert_format (function): Convert the format of the command `c` to the format required by OpenAI if it's not already that format.
* is_valid (class method): Check if the command `c` is valid based on rules provided by OpenAI.
* fix_command (function): Fix the invalid command `c` using pre-designed rules.
"""

# TODO: User purpose to replace the current function summary.
GENERATE_PROCESS_EXAMPLE_OUTPUT = """
# Purpose
The `process_commands` function ensures the commands are valid and matches the \
format required by OpenAI.

# Process
1. **validate_commands**: if there are no commands provided, return an empty list.
2. **initialize_processed_list**: Initialize an empty list `processed` to store \
the processed commands.
3. **loop_through_commands**: for each command `c` in the given `commands` list:
   3.1. **convert_command_format**: Convert the format of the command `c` to the format required by OpenAI using the `convert_format` function.
   3.2. **check_validity**: If the command `c` is not valid (using the `is_valid` method):
       3.2.1. **fix_invalid_command**: Fix the invalid command `c` using the `fix_command` function.
   3.3. **append_to_processed**: Append the command `c` to the `processed` list.
4. **return_processed**: Return the `processed` list containing the processed commands.
"""

GENERATE_RPOECSS_ACTUAL_INPUT_TEMPLATE = """
# TARGET FUNCTION CODE
```python
{code}
```

# REFERENCES

Summary of functions/class methods called by the above code:

{summaries}
"""

PROCESS_PATTERN = """but please show the decision points like `if` and \
`switch` as well as loops like `for`, `while` in your output processes.
1. Put the processes in if branches or inside loop to a child-level of the if or loop decision point. \
   Show the type of the parent process after the process name, e.g. `if`, `else`, `elif`, `loop`. E.g.:
    ```md
    1. **loop_through_commands** (loop): for each command `c` in the given `commands` list:
        1.1 **convert_command_format**: Convert the format of the command `c`.
    ```
1. If a process has sub-processes, you must show it's type. Also, it a process has type, it must have child-level processes.

"""


def summaries_prompt(summaries: list[tuple[str, str, str]]) -> str:
    contents = []
    for uri, type, summary in summaries:
        u = uri_stem(uri)
        t = "class method" if type == "method" else type
        s = summary.strip().replace("\n", " ")
        contents.append(f"* **`{u}` ({t})**: {s}")

    if contents:
        return "\n".join(contents)
    else:
        return "No function/class method is called, so no summary."


def generate_process_inputs(
    target_node: CodeNode, nodes: dict[str, CodeNode]
) -> str:
    data = []
    for call_uri in target_node.calls:
        data.append((call_uri, nodes[call_uri].type, nodes[call_uri].summary))
    return dict(
        # NOTE: Adding line number here negatively influence the performance.
        code=target_node.code,
        summaries=summaries_prompt(data),
    )


@dataclass
class ProcessFlowMessages:
    overall_instruction = SystemMessage(
        additional_kwargs=dict(name="overall_instructions"),
        content=OVERALL_SYSTEM,
    )
    process_generate_instruction = SystemMessage(
        additional_kwargs=dict(name="generate_processes_instructions"),
        content=GENERATE_PROCESS_INSTRUCTIONS,
    )
    process_generate_example_intput = HumanMessage(
        additional_kwargs=dict(name="generate_processes_example_input"),
        content=GENERATE_PROCESS_EXAMPLE_INPUT,
    )
    process_generate_example_output = AIMessage(
        additional_kwargs=dict(name="generate_processes_example_output"),
        content=GENERATE_PROCESS_EXAMPLE_OUTPUT,
    )
    code_and_summaries = HumanMessagePromptTemplate.from_template(
        additional_kwargs=dict(name="generate_processes_actual_input"),
        template=GENERATE_RPOECSS_ACTUAL_INPUT_TEMPLATE,
    )

    @property
    def process_messages(self) -> list[BaseMessage]:
        return [
            self.overall_instruction,
            self.process_generate_instruction,
            self.process_generate_example_intput,
            self.process_generate_example_output,
            self.code_and_summaries,
        ]


MESSAGE_SET = ProcessFlowMessages()


def add_lineno_to_code(code: str) -> str:
    return "\n".join([f"{i}: {l}" for i, l in enumerate(code.split("\n"))])


def generate_by_chain(
    messages: list[BaseMessage],
    inputs: dict,
    output_key: str,
    output_path: Path | None = None,
    call_api: bool = False,
) -> dict:
    prompt = ChatPromptTemplate.from_messages(
        messages=messages,
    )
    chain = LLMChain(
        llm=ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0,
            streaming=True,
            verbose=True,
            callbacks=[BotStreamingStdOutCallbackHandler()],
        ),
        prompt=prompt,
        output_key=output_key,
        verbose=True,
    )

    formated_prompt = prompt.format(**inputs)

    if output_path is not None:
        output_path.with_suffix(".input.md").write_text(formated_prompt)

    if call_api:
        outputs = chain(inputs=inputs)
    else:
        outputs = inputs.copy()
        outputs[chain.output_key] = "Fake response of gpt-3.5-turbo"

    if output_path is not None:
        output_path.write_text(outputs[chain.output_key])
    return outputs


def code_to_process(
    target_uri: URI,
    nodes: dict[URI, CodeNode],
    output_path: Path | None = None,
    call_api: bool = False,
) -> dict[str, str]:
    outputs = generate_by_chain(
        messages=MESSAGE_SET.process_messages,
        inputs=generate_process_inputs(target_node=nodes[target_uri], nodes=nodes),
        call_api=call_api,
        output_key="process_output",
        output_path=output_path / "process.md",
    )
    return outputs


# %%
import re


def ask_gpt(
    prompt: str, model: str = "gpt-3.5-turbo", call_api: bool = False
) -> str:
    print(prompt)
    llm = ChatOpenAI(
        model=model,
        temperature=0,
        verbose=True,
        streaming=True,
        callbacks=[BotStreamingStdOutCallbackHandler()],
    )
    if call_api:
        return llm.invoke(prompt).content
    return f"Fake response of {model=}"


def extract_purpose_process_from_file(file_path: Path) -> str:
    # TODO: Add format check here.
    if not file_path.exists():
        raise ValueError(f"{file_path=} does not exist.")
    file_path = Path(file_path).absolute()
    with open(file_path, "r") as f:
        parts = f.read().split("# Process")
        purpose = parts[0].strip().split("# Purpose")[1].strip()
        process = parts[1].strip()
        logger.debug(purpose)
        logger.debug(process)
        return purpose, process


def parse_process_markdown(text) -> Process:
    """Parses the extracted process from markdown to a JSON format."""

    # Given:
    # ```md
    #   1.2 **Process 1**: This is the first process.
    # ```
    # Output:
    # index = 1.2, name = "Process 1", explanation = "This is the first process."

    pattern = re.compile(r"(\d+(?:\.\d+)*)\. \*\*(.+?)\*\*(?: \((.+?)\))?: (.+)")
    # TODO: add function name and explanation here.
    root = Process(
        name="root",
        explanation="This is the root of the processes.",
        index="",
        subprocesses=[],
    )
    process_map: dict[str, Process] = {root.index: root}

    for line in text.split("\n"):
        match = pattern.match(line.strip())
        if match:
            index, name, proc_pattern, explanation = match.groups()
            # TODO: Remove proc_pattern
            logger.info(f"Found process {index=}, {name=}, {proc_pattern=}")
            process = Process(
                name=name,
                index=index,
                explanation=explanation,
                subprocesses=[],
            )
            if proc_pattern:
                process.pattern = proc_pattern

            # Split the index and find the parent index
            index_parts = index.split(".")
            parent_index = ".".join(index_parts[:-1])
            parent = process_map.get(parent_index)
            if parent is not None:
                parent.subprocesses.append(process)

            process_map[index] = process
        else:
            # TODO: This should also be feed back to GPT as error report.
            logger.error(f"Line {line} doesn't match the pattern.")
            # TODO: Remove in production
            raise ValueError(f"Line {line} doesn't match the pattern.")

    return root


# TODO: CONSTANTS for file names
def process_to_json(output_path: Path) -> Process:
    ## STEP1: Convert the process from MD to JSON
    process_file = output_path / "process.md"
    purpose, processes = extract_purpose_process_from_file(process_file)
    process_obj = parse_process_markdown(processes)
    process_obj.name = output_path.name
    process_obj.explanation = purpose
    print(f"Converted process markdown in {process_file} to process object.")
    return process_obj


# %%
# This works not bad for run_auto_gpt.
CODE_PROCESS_PAIR = """Please associate the code of the target function with \
the extracted processes of the same function. The code is shown \
again with line numbers on the left. You should assign a process index to each line of code. \
If no corresponding process, assign `-` to the line.

# Example code of the Target Function
```python
0: def process_commands(commands):
1:     if not commands:
2:         return []
3:
4:     processed = []
5:     for c in commands:
6:         c = convert_format(c)
7:         if not c.is_valid():
8:             c = fix_command(c)
9:         processed.append(c)
10:     return processed
```

# Example processes of the Target Function
1. **validate_commands**: if there are no commands provided, return an empty list.
2. **initialize_processed_list**: Initialize an empty list `processed` to store \
the processed commands.
3. **loop_through_commands**: for each command `c` in the given `commands` list:
   3.1. **convert_command_format**: Convert the format of the command `c` to the format required by OpenAI using the `convert_format` function.
   3.2. **check_validity**: If the command `c` is not valid (using the `is_valid` method):
       3.2.1. **fix_invalid_command**: Fix the invalid command `c` using the `fix_command` function.
   3.3. **append_to_processed**: Append the command `c` to the `processed` list.
4. **return_processed**: Return the `processed` list containing the processed commands.


# Example output

code_lineno, process_index
0, -
1, 1
2, 1
3, -
4, 2
5, 3
6, 3.1
7, 3.2
8, 3.2.1
9, 3.3
10, 4

# Actual Target Function Code with Line Number

```python
{code_lineno}
```

# Actual Process of the Target Function

{process_output}

# Your output
"""


def process_lineno(
    nodes: dict[URI, CodeNode],
    target_uri: str,
    output_path: Path | None = None,
    call_api: bool = False,
) -> str:
    ## STEP2: Find the process index of each line of code
    process_file = output_path / "process.md"
    target_code = nodes[target_uri].code
    _, process = extract_purpose_process_from_file(process_file)
    prompt = CODE_PROCESS_PAIR.format(
        code_lineno=add_lineno_to_code(target_code),
        process_output=process,
    )
    Path(output_path / "lineno.input.md").write_text(prompt)
    lineno_response = ask_gpt(
        prompt=prompt,
        call_api=call_api,
    )
    if call_api:
        Path(output_path / "lineno.csv").write_text(lineno_response)
        print(f"Saved lineno to {output_path / 'lineno.csv'}")


def show_process_lineno(code: str, output_path: Path | None = None) -> None:
    lineno_file = output_path / "lineno.csv"
    df = pd.read_csv(lineno_file)
    df = df.rename(columns=lambda x: x.strip())
    df["process_index"] = df["process_index"].str.strip().str.strip('"')


# _check_save_load(process)
# %%
from langchain.chains.openai_functions.base import create_openai_fn_chain

# %%
from codebase_analyzer.flowchart.add_lineno import add_code_lineno
from codebase_analyzer.flowchart.check_lineno import check_process_linenos

# %%


# def _check_save_load(process, output_path: Path) -> None:
#     process.to_file(output_path / "process_check.json")
#     new_process = Process.from_file(
#         json_file=output_path / "process_check.json",
#     )
#     assert process == new_process


PROCESS_PATTERN_SYSTEM = """You are an expert in analyzing programming languages and \
creating activity flowcharts from code. A long program are divided into multiple
parts, each of which has a process description and the corresponding code snippet.
Now, we are going to analyze a single part and and conert it to a/several node(s) in a UML activity flowchart of the whole program.

Your task is to analyze the type of the **outmost** logic, extract required information, and return them using the provided function. \
Remember, MUST return using the function, and if there are elements of more than one type, just focus on the outmost \
one. For example, if there is a loop inside an if statement, just focus on the \
if statement.
"""

UNUSED = """
Your task is to do the following step by step:
1. First analyze the **primary** type of the process. Available types are: \
`normal`, `loop`, `if`, `elif`, `else`. Each of them has a corresponding \
function and you can refer the docstring for more definition.

2. After deciding the type, check the instructions and examples in corresponding \
function's docstring and extract those required informaton from the process \
description and the code.

3. Return the extracted information using the provided functions.
"""

PROCESS_PATTERN_INPUT = """
# Process name and description
{process}

# Code Snippet
```python
def {function_name}(...): # Arguments omitted
    # other code ommited, target code starts from here

{code}

    # other code ommited, target code ends here
```
"""


LOOP_EXAMPLE_INPUT = """
# Example process:
convert_command_format: get commands and convert their formats.

# Example code:
```python
commands = get_commands()
for c in commands:
    c = convert_format(c)
```
"""
LOOP_EXAMPLE_CALL = dict(
    name=LoopPattern.get_name(),
    arguments=LoopPattern(
        setup="Take a command from the gotten commands",
        body="Convert the format of the command",
        decision="Check if there are more commands",
    ).json(),
)


IF_EXAMPLE_INPUT = """
Example input process:
print_debug: print various debug info if encountered an error when do_something.

Example input code:
```python
try:
    do_something()
except Exception as e:
    print("error encountered")
    print(debug_info)
    print(e)
```
"""
IF_EXAMPLE_CALL = dict(
    name=IfPattern.get_name(),
    arguments=IfPattern(
        decision="If error encountered when do_something",
        true="print various debug info",
    ).json(),
)


messages = [
    SystemMessage(content=PROCESS_PATTERN_SYSTEM),
    HumanMessage(content=LOOP_EXAMPLE_INPUT),
    AIMessage(content="", additional_kwargs=dict(function_call=LOOP_EXAMPLE_CALL)),
    HumanMessagePromptTemplate.from_template(
        template=PROCESS_PATTERN_INPUT,
    ),
]

chain = create_openai_fn_chain(
    functions=[
        LoopPattern,
        IfPattern,
        ElifPattern,
        ElsePattern,
        ActionPattern,
        ExitPattern,
    ],
    llm=ChatOpenAI(
        model="gpt-3.5-turbo",
        temperature=0,
        verbose=True,
        streaming=True,
        callbacks=[BotStreamingStdOutCallbackHandler()],
    ),
    prompt=ChatPromptTemplate.from_messages(messages),
    verbose=True,
)


def _process_pattern(
    function_name: str,
    process: Process,
    output_path: Path | None = None,
    call_api: bool = False,
) -> str:
    if call_api:
        pattern = chain.run(
            function_name=function_name,
            process=f"{process.name}: {process.explanation}",
            code=process.code or "# No code for this process.",
        )
        process.pattern = pattern

    print(f"{process.name=}, {process.pattern=}")

    if output_path is not None:
        prompt = chain.prompt.format(
            function_name=function_name,
            process=f"{process.name}: {process.explanation}",
            code=process.code,
        )
        output_file = output_path / f"{process.node_name}.md"
        output_file.write_text(
            f"""
{prompt}

# Result
{str(process.pattern)}
"""
        )

    for sub_p in process.subprocesses:
        _process_pattern(
            function_name=function_name,
            process=sub_p,
            output_path=output_path,
            call_api=call_api,
        )


def process_pattern(
    process: Process,
    output_path: Path | None = None,
    call_api: bool = False,
) -> None:

    output_path = output_path / "patterns/"
    output_path.mkdir(parents=True, exist_ok=True)

    for p in process.subprocesses:
        _process_pattern(
            function_name=process.name,
            process=p,
            output_path=output_path,
            call_api=call_api,
        )
        # break


# %%
from codebase_analyzer.flowchart.check_pattern import check_process_pattern

if __name__ == "__main__":
    code_info = CodeInfo.from_disk(input_path=CACHE_ROOT / "Auto-GPT/codeinfo.json")
    nodes = code_info.nodes
    output_dir = (LOCAL_ROOT / "flowcharts").absolute()

    debug_uri = "/autogpt.logs.logger/Logger.debug"
    main_uri = "/autogpt.app.main/run_auto_gpt"
    update_uri = "/autogpt.app.main/update_user"
    loop_uri = "/autogpt.app.main/run_interaction_loop"

    target_uri = loop_uri
    # %%
    output_path = _output_path(target_uri, output_dir=output_dir)
    print(output_path)

    #### TODO: To file, make it return object.
    # code_to_process(
    #     target_uri=target_uri,
    #     nodes=nodes,
    #     call_api=True,
    #     output_path=output_path,
    # )

    # %%
    ### NO API CALL
    process = process_to_json(output_path=output_path)
    from codebase_analyzer.flowchart.check_index import check_process_indexes

    ### TODO: Fix the root index
    process.to_file(output_path / "process.json")
    process_lineno(
        nodes=nodes,
        target_uri=target_uri,
        output_path=output_path,
        call_api=True,
    )

    add_code_lineno(
        process=process,
        csv_file=output_path / "lineno.csv",
        code=nodes[target_uri].code,
    )

    check_process_linenos(process=process)

    ### %%
    process_pattern(
        process=process,
        output_path=output_path,
        call_api=True,
    )

    check_process_pattern(process)
    process.to_file(output_path / "process.json")

    # %%
    # import codebase_analyzer.flowchart.node
    # import importlib
    # importlib.reload(codebase_analyzer.flowchart.node)
    from codebase_analyzer.flowchart.node import (
        FlowchartConfig,
        flowchart_node_to_dot_graph,
        flowchart_to_element_json,
        root_process_to_flowchart,
    )

    process = Process.from_file(output_path / "process.json")
    flowchart = root_process_to_flowchart(process)
    flowchart_node_to_dot_graph(
        flowchart, config=FlowchartConfig(expand_all=True, show_cluster=True)
    )
    # db_path = Path("/Users/jun/Projects/display-flowchart/db.json")
    # flowchart_to_element_json(flowchart=flowchart, output_path=db_path)
    # %%
