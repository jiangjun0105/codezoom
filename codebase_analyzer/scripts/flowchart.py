# %%
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar

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

from codebase_analyzer.parser.codeinfo import check_state, update_state
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode
from codebase_analyzer.parser.uri import URI, uri_stem

REPO_ROOT = Path(__file__).parent.parent.parent
CACHE_ROOT = REPO_ROOT / "shared_cache"
LOCAL_ROOT = REPO_ROOT / ".local"

OVERALL_SYSTEM = """You are an expert in analyzing programming languages and \
creating activity flowcharts from code. Now, you are going to help analyze the \
main logic of a target function and create a flowchart using dot language. \
Please do it STEP BY STEP and follow the system or user instructions at each \
step.
"""

GENERATE_PROCESS_INSTRUCTIONS = """First, the code of the target function and \
the summaries of the functions being called will be given. For this step, please \
analyze the purpose of the target function and extract the main processes. \

Several Notes:
1. The purpose should be brief and general, shouldn't include too much process details.
1. Every process should has an index in format `x.y.z`. Ensure the indexes follow the rules:
    * Continuous: `x`'s next index must be `x+1`, also `x.y`'s next must be `x.y+1`.
    * Hierarchical: `x.y.z`'s children must be `x.y.z.1`, `x.y.z.2`, etc.
1. You need to omit/simplify the unimportant processes or implementation details \
and extract the major logics, but please show the decision points like `if` and \
`switch` as well as loops like `for`, `while` in your output processes.
1. Put the processes in if branches or inside loop to a child-level of the if or loop decision point. \
   Show the type of the parent process after the process name, e.g. `if`, `else`, `elif`, `loop`. E.g.:
    ```md
    1. **loop_through_commands** (loop): for each command `c` in the given `commands` list:
        1.1 **convert_command_format**: Convert the format of the command `c`.
    ```
1. If a process has sub-processes, you must show it's type. Also, it a process has type, it must have child-level processes.
1. For this step, only need to output purposes and processes, no need for the flowchart.
"""

GENERATE_PROCESS_EXAMPLE_INPUT = """# TARGET FUNCTION CODE

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

Summary of functions called by the above code:

| URI | type (where method is class method) | Summary |
|-----|------|---------|
| convert_format | function | Convert the format of the command `c` to the format required by OpenAI if it's not already that format. |
| is_valid | method | Check if the command `c` is valid based on rules provided by OpenAI. |
| fix_command | function | Fix the invalid command `c` using pre-designed rules. |
"""

GENERATE_PROCESS_EXAMPLE_OUTPUT = """# Purpose
The `process_commands` function ensures the commands are valid and matches the \
format required by OpenAI.

# Process
1. **validate_commands**: if there are no commands provided, return an empty list.
2. **initialize_processed_list**: Initialize an empty list `processed` to store \
the processed commands.
3. **loop_through_commands** (loop): for each command `c` in the given `commands` list:
   3.1. **convert_command_format**: Convert the format of the command `c` to the format required by OpenAI using the `convert_format` function.
   3.2. **check_validity** (if): If the command `c` is not valid (using the `is_valid` method):
       3.2.1. **fix_invalid_command**: Fix the invalid command `c` using the `fix_command` function.
   3.3. **append_to_processed**: Append the command `c` to the `processed` list.
4. **return_processed**: Return the `processed` list containing the processed commands.
"""

GENERATE_RPOECSS_ACTUAL_INPUT_TEMPLATE = """# TARGET FUNCTION CODE
```python
{code}
```

# REFERENCES

Summary of functions called by the above code:

{summaries}
"""

# TODO: Add example if performance is bad.
GENERATE_FLOWCHART_GIVEN_PROCESSES = """Well done! Then please create a \
flowchart for the program using dot language based on the extracted processed \
above. The extracted steps in the flowchart should have similar granularity.

Be sure extract all decision points, e.g. `if` or `switch`, and show their \
branches conditions with label on the edge.  Also, for all kinds of loops, \
convert loop body into normal processes and loop end conditions into decision \
points.

For the flowchart, you can use the following shapes:
 * oval: start and end (Do not include actual processes in these shapes)
 * rectangle: normal process
 * diamond: decision points
"""


TABLE_PREFIX = """
| URI | type | Summary |
|-----|------|---------|
"""

TABLE_TEMPLATE = """| {uri} | {type} | {summary} |"""

ASSOCIATE_FLOWCHART_AND_CODE = """Next please associate the nodes in \
the generated dot flowchart with the line numbers of code. The code is shown \
again with line numbers on the left. Your output should look like:

node_name|start_lineno|end_lineno
---------|------------|----------
start | 0 | 1
name1 | 1 | 2
name2 | 2 | 5
end   | - | -

NOTE: The start and end line numbers should follow python list index so that \
code_split_by_newline[start_lineno: end_lineno] should return the code of the \
node.

PLEASE THINK IT STEP BT STEP, you can:
1. Analyze the correspondance between the flowchart node and the code.
2. Find the start and end line number of the node in the code.

# Line Number of Target Function Code

{code_lineno}
"""


def uri_to_path(uri: URI) -> str:
    # TODO: Think about cases having functions, for now this is OK because
    # AgentExecutorBot will only be used for Module and Packages
    uri = uri.lstrip("/")
    return uri.replace(".", "/")


def _output_path(uri: str, output_dir: Path) -> Path:
    if output_dir is None:
        return None

    output_path = output_dir / uri_to_path(uri)
    output_path.mkdir(exist_ok=True, parents=True)
    return output_path


def summaries_prompt(summaries: list[tuple[str, str, str]]) -> str:
    contents = "\n".join(
        [
            TABLE_TEMPLATE.format(uri=uri, type=type, summary=summary)
            for uri, type, summary in summaries
        ]
    )
    if contents:
        return TABLE_PREFIX + contents
    else:
        return "No function is called, so no summary."


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


SHOW_PROCESS = """The purposes and processes of the target function are analyzed as:

{process_output}
"""

SHOW_FLOWCHART = """The flowchart of the given function generated based on the processes is:

{flowchart_output}
"""


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
    show_process = HumanMessagePromptTemplate.from_template(
        additional_kwargs=dict(name="generate_processes_actual_output"),
        template=SHOW_PROCESS,
    )
    flowchart_generate_instruction = SystemMessage(
        additional_kwargs=dict(name="second_step_instructions"),
        content=GENERATE_FLOWCHART_GIVEN_PROCESSES,
    )
    show_flowchart = HumanMessagePromptTemplate.from_template(
        additional_kwargs=dict(name="generate_flowchart_actual_output"),
        template=SHOW_FLOWCHART,
    )
    code_lineno_instruction = HumanMessagePromptTemplate.from_template(
        additional_kwargs=dict(name="associate_code_lineno_instruction"),
        template=ASSOCIATE_FLOWCHART_AND_CODE,
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

    @property
    def flowchart_messages(self) -> list[BaseMessage]:
        # TODO: Optimize the token and rethink if we need the first step
        # instructions and inputs.
        return [
            self.overall_instruction,
            # self.process_generate_instruction, # Recover this if bad performance
            self.code_and_summaries,
            self.show_process,
            self.flowchart_generate_instruction,
        ]

    @property
    def code_lineno_messages(self) -> list[BaseMessage]:
        # TODO: Optimize the token and rethink if we need the first step
        # instructions and inputs.
        return [
            self.overall_instruction,
            self.code_and_summaries,
            self.show_process,
            self.show_flowchart,
            self.code_lineno_instruction,
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
        llm=ChatOpenAI(model="gpt-4", temperature=0),
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
        outputs[chain.output_key] = "Fake response of gpt-4"

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


def generate_chart_from_process(
    process_outputs: dict[str, str],
    output_path: Path | None = None,
    call_api: bool = False,
) -> str:
    outputs = generate_by_chain(
        messages=MESSAGE_SET.flowchart_messages,
        # TODO: Single source of truth for the output_key
        output_key="flowchart_output",
        inputs=process_outputs,
        call_api=call_api,
        output_path=output_path / "flowchart.md",
    )
    return outputs


def generate_node_code_lineno(
    target_uri: URI,
    inputs: dict[str, str],
    output_path: Path | None = None,
    call_api: bool = False,
) -> str:
    inputs["code_lineno"] = add_lineno_to_code(inputs["code"])
    outputs = generate_by_chain(
        messages=MESSAGE_SET.code_lineno_messages,
        # TODO: Single source of truth for the output_key
        output_key="lineno_output",
        inputs=inputs,
        call_api=call_api,
        output_path=output_path / "lineno.md",
    )
    return outputs


def extract_dot_blocks(md_text):
    # Split the markdown text into lines
    lines = md_text.split("\n")

    # Initialize lists to store DOT blocks and the current block being processed
    dot_blocks = []
    current_block = []
    inside_dot_block = False

    # Iterate through each line
    for line in lines:
        if line.strip() == "```dot":
            inside_dot_block = True
            continue
        if line.strip() == "```" and inside_dot_block:
            inside_dot_block = False
            dot_blocks.append("\n".join(current_block))
            current_block = []
            continue
        if inside_dot_block:
            current_block.append(line)

    return "\n".join(dot_blocks)


def ask_gpt(prompt: str, model: str = "gpt-4", call_api: bool = False) -> str:
    print(prompt)
    llm = ChatOpenAI(model=model, temperature=0, verbose=True)
    if call_api:
        return llm.invoke(prompt).content
    return f"Fake response of {model=}"


def extract_process_from_file(file_path: Path) -> str:
    file_path = Path(file_path).absolute()
    with open(file_path, "r") as f:
        return f.read().split("# Process")[1].strip()


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
1, "1"
2, "1"
3, "-"
4, "2"
5, "3"
6, "3.1"
7, "3.2"
8, "3.2.1"
9, "3.3"
10, "4"

# Actual Target Function Code with Line Number

{code_lineno}

# Actual Process of the Target Function

{process_output}

# Your output
"""


import re


def parse_markdown_v5(text):
    pattern = re.compile(r"(\d+(?:\.\d+)*)\. \*\*(.+?)\*\*(?: \((.+?)\))?: (.+)")
    root = {
        "name": "root",
        "explanation": "This is the root of the processes.",
        "subprocesses": [],
    }
    process_map = {"": root}

    for line in text.split("\n"):
        match = pattern.match(line.strip())
        if match:
            index, name, proc_pattern, explanation = match.groups()
            process = {
                "name": name,
                "index": index,
                "explanation": explanation,
                "subprocesses": [],
            }
            if proc_pattern:
                process["pattern"] = proc_pattern

            # Split the index and find the parent index
            index_parts = index.split(".")
            parent_index = ".".join(index_parts[:-1])
            parent = process_map.get(parent_index)
            if parent is not None:
                parent["subprocesses"].append(process)

            process_map[index] = process

    return root


def process_to_json(output_path: Path | None = None, call_api: bool = False) -> str:
    process_file = output_path / "process.md"
    main_process = extract_process_from_file(process_file)
    print(main_process)

    ## STEP1: Convert the process from MD to JSON
    # json_response = ask_gpt(
    #     prompt=PROCESS_TO_JSON.format(
    #         process_output=main_process,
    #     ),
    #     call_api=call_api,
    # )
    json_dict = parse_markdown_v5(main_process)
    json_str = json.dumps(json_dict, indent=4)
    output_file = output_path / "process.json"
    with open(output_file, "w") as f:
        f.write(json_str)
    print(f"Saved process to {output_file}")


def process_lineno(
    target_uri: str, output_path: Path | None = None, call_api: bool = False
) -> str:
    ## STEP2: Find the process index of each line of code
    process_file = output_path / "process.md"
    target_code = nodes[target_uri].code
    main_process = extract_process_from_file(process_file)
    lineno_response = ask_gpt(
        prompt=CODE_PROCESS_PAIR.format(
            code_lineno=add_lineno_to_code(target_code),
            process_output=main_process,
        ),
        call_api=call_api,
    )
    with open(output_path / "lineno.csv", "w") as f:
        f.write(lineno_response)


class Process(BaseModel):
    index2lineno: ClassVar[defaultdict]
    name: str
    index: str
    explanation: str
    subprocesses: list[Process] = Field(default_factory=list)
    code_lineno: list[int] = Field(default_factory=list)
    code: str | None = None
    pattern: str | None = None

    @classmethod
    def from_files(cls, process_json_file: Path, lineno_csv_file: Path) -> Process:
        with open(process_json_file, "r") as f:
            process_json = json.load(f)

        df = pd.read_csv(lineno_csv_file)
        # TODO: Make this more robust or solve the problem when saving the csv.
        df = df.rename(columns=lambda x: x.strip())
        df["process_index"] = df["process_index"].str.strip().str.strip('"')

        index2lineno = defaultdict(list)
        for lineno, index in zip(df["code_lineno"], df["process_index"]):
            if index == "-":
                continue
            if index2lineno[index] and lineno - index2lineno[index][-1] != 1:
                logger.warning(
                    f"Line number {lineno} is not continuous with {index2lineno[index][-1]}"
                )
            index2lineno[index].append(lineno)

        cls.index2lineno = index2lineno
        print(
            f"assign {len(index2lineno)} process indexes to {len(df)} lines of code"
        )
        return cls.parse_obj(process_json)

    @root_validator(pre=True)
    def get_code(cls, values):
        if values["name"] == "root":
            values["index"] = "root"
            return values
        values["code_lineno"] = cls.index2lineno[values["index"]]
        return values

    @property
    def node_name(self):
        return f"{self.index}_{self.name}"

    @property
    def node_shape(self):
        return "diamond" if self.pattern in ["if", "elif"] else "box"


from collections import OrderedDict

# STEP5: Convert the process to dot based on if/loop pattern
import networkx as nx
import pygraphviz as pgv


class Branch(BaseModel):
    processes: list[Process]
    start: str
    end: str | None = None
    edge_label: str = Field(default="")


class PendingBranch(BaseModel):
    # (start, end, edge_label): processes
    branches: OrderedDict = Field(default_factory=OrderedDict)

    def add_branch(
        self,
        start: str,
        processes: list[Process],
        end: str | None = None,
        edge_label: str = "",
    ) -> None:
        assert start != end, f"Start and end node should not be the same {start}"
        key = (start, end, edge_label)
        if key in self.branches:
            assert (
                self.branches[key] == []
            ), f"Branch {start, end, edge_label} already exists {self.branches[key]}"
        self.branches[key] = processes

    def update_ends(self, end: str) -> None:
        # Has to iterate again to keep the order
        new_branches = OrderedDict()
        for (start, old_end, edge_label), processes in self.branches.items():
            if old_end is None:
                assert (
                    start != end
                ), f"Start and end node should not be the same {start}"
                print(f"Update end node of branch {start} -> {end} [{edge_label}]")
                new_branches[(start, end, edge_label)] = processes
            else:
                print(f"Skip node of branch {start} -> {old_end} [{edge_label}]")
                new_branches[(start, old_end, edge_label)] = processes
        self.branches = new_branches


def _add_node_by_process(
    graph: pgv.AGraph,
    process: Process,
    pending: Pending,
    branches: list[Branch],
) -> None:
    # NOTE: Setting label=None will show `None` in the graph.
    _add_node(
        graph=graph,
        parent_name=pending.parent_name,
        node_name=process.node_name,
        node_attrs=dict(
            label=process.explanation or process.node_name,
            shape=process.node_shape,
            start_lineno=process.code_lineno[0],
            end_lineno=process.code_lineno[-1] + 1,
        ),
        has_edge=pending.has_edge,
        edge_attrs=dict(
            label=pending.edge_label or "",
        ),
        branches=branches,
    )


def _add_node(
    graph: pgv.AGraph,
    parent_name: str,
    node_name: str,
    branches: PendingBranch,
    has_edge: bool = True,
    node_attrs: dict | None = None,
    edge_attrs: dict | None = None,
) -> None:
    """Add a new node, connect the previous node with the new node and return
    the name of the new node. Also assign the new node as the end node of the
    branches which don't have an end node."""
    node_attrs = node_attrs or {}
    edge_attrs = edge_attrs or {}

    graph.add_node(node_name, **node_attrs)
    if has_edge:
        graph.add_edge(parent_name, node_name, **edge_attrs)

    if branches:
        branches.update_ends(node_name)


class Pending(BaseModel):
    parent_name: str
    node_shape: str = Field(default="box")
    has_edge: bool = Field(default=True)
    edge_label: str = Field(default="")


def _dot_from_process(
    processes: list[Process],
    graph: pgv.AGraph,
    start: str,
    end: str,
    edge_label: str = "",
) -> None:
    """Add all processes to the graph betwen start and end nodes."""
    if not processes:
        graph.add_edge(start, end, label=edge_label)
        return graph

    else_origin = None
    branches = PendingBranch()
    pending = Pending(parent_name=start, edge_label=edge_label)

    # First add all nodes in the current branch, and save sub branches for later.
    # By the end, main branch should be single line processes.
    for p in processes:
        if p.pattern is None:  # Normal process
            _add_node_by_process(graph, p, pending=pending, branches=branches)
            pending = Pending(parent_name=p.node_name)
        elif p.pattern in ["if", "if-elif"]:
            _add_node_by_process(graph, p, pending=pending, branches=branches)
            pending = Pending(parent_name=p.node_name, has_edge=False)
            # True branch
            branches.add_branch(
                processes=p.subprocesses, start=p.node_name, edge_label="yes"
            )
            # False branch
            if p.pattern == "if":
                branches.add_branch(processes=[], start=p.node_name, edge_label="no")
            else_origin = p
        elif p.pattern == "elif":
            # start node should be a "if" or "elif" node.
            assert graph.get_node(pending.parent_name).attr["shape"] == "diamond"
            elif_process = p.copy(update={"pattern": "if-elif"})
            # Flase branch from previous to this node
            branches.add_branch(
                start=pending.parent_name, processes=[elif_process], edge_label="no"
            )
            # False branch of this node at next level
            # branches.add_branch(start=elif_process.node_name, processes=[], edge_label="no")
            # TODO: Check if there is a elif/else after elif, now assume yes
            else_origin = elif_process
        elif p.pattern == "else":
            # else won't add a node in main branch, so no need to update start.
            assert graph.get_node(pending.parent_name).attr["shape"] == "diamond"
            assert else_origin is not None
            branches.add_branch(
                start=else_origin.node_name,
                processes=p.subprocesses,
                edge_label="no",
            )
        elif p.pattern == "loop":
            # Add loop setup node.
            _add_node_by_process(graph, p, pending=pending, branches=branches)

            # Add a diamond loop termination checking node after the setup node.
            check_node = f"{p.node_name}_loop_check"
            _add_node(
                graph,
                parent_name=p.node_name,
                node_name=check_node,
                has_edge=False,
                node_attrs=dict(label="Is loop done?", shape="diamond"),
                branches=branches,
            )
            graph.add_edge(check_node, p.node_name, label="no")
            branches.add_branch(
                processes=p.subprocesses, start=p.node_name, end=check_node
            )
            pending = Pending(parent_name=check_node, edge_label="yes")
        else:
            raise ValueError(f"Unknown pattern {p.pattern}")
    # If the end node is the end node, add all branches to the graph.
    branches.update_ends(end)

    for keys, branch_processes in branches.branches.items():
        branch_start, branch_end, branch_edge_label = keys
        assert branch_end is not None
        _dot_from_process(
            processes=branch_processes,
            graph=graph,
            start=branch_start,
            end=branch_end,
            edge_label=branch_edge_label,
        )
    if pending.has_edge:
        graph.add_edge(pending.parent_name, end, label=pending.edge_label)
    return


def get_dot_from_process(process: Process) -> str:
    # Create a new graph
    graph = pgv.AGraph(directed=True)
    graph.node_attr["shape"] = "box"
    # A.node_attr['style'] = 'filled'
    # A.node_attr['fillcolor'] = 'yellow'
    start = "start"
    end = "end"
    graph.add_node(start, shape="oval")
    graph.add_node(end, shape="oval")
    # graph.add_edge(start, end)
    _dot_from_process(process.subprocesses, graph, start, end)
    return graph


code_info = CodeInfo.from_disk(input_path=CACHE_ROOT / "Auto-GPT/codeinfo.json")
nodes = code_info.nodes
debug_uri = "/autogpt.logs.logger/Logger.debug"
main_uri = "/autogpt.app.main/run_auto_gpt"
target_uri = "/autogpt.app.main/update_user"
output_dir = (LOCAL_ROOT / "experiments/gpt_flowchart/fully-automated").absolute()


def generate_function_flowchart(
    target_uri: URI,
    nodes: dict[CodeNode],
    output_dir: Path | None = None,
    call_api: bool = False,
) -> str:
    output_path = _output_path(target_uri, output_dir=output_dir)
    code_to_process(
        target_uri=target_uri,
        nodes=nodes,
        call_api=call_api,
        output_path=output_path,
    )
    process_to_json(output_path=output_path, call_api=call_api)
    process_lineno(target_uri=target_uri, output_path=output_path, call_api=call_api)
    process = Process.from_files(
        process_json_file=output_path / "process.json",
        lineno_csv_file=output_path / "lineno.csv",
    )
    graph = get_dot_from_process(process)
    graph.draw(output_path / "flowchart.png", prog="dot")
    graph.write(output_path / "flowchart.dot")


run_interaction_loop = "/autogpt.app.main/run_interaction_loop"
# generate_function_flowchart(target_uri=run_interaction_loop, nodes=nodes, output_dir=output_dir, call_api=True)
# exit()

output_path = _output_path(target_uri, output_dir=output_dir)
process = Process.from_files(
    process_json_file=output_path / "process.json",
    lineno_csv_file=output_path / "lineno.csv",
)
graph = get_dot_from_process(process)
graph.draw(output_path / "flowchart.png", prog="dot")
graph.write(output_path / "flowchart.dot")

# %%
