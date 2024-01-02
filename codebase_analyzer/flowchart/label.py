# %%
from __future__ import annotations

import ast
import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from langchain.callbacks import get_openai_callback
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
from codebase_analyzer.flowchart.process.generate import ask_gpt, generate_by_chain

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


SUMMARIZE_LABELS_TEMPLATE = """The following is a description of some process \
using mix of human language and python syntax. Please help to summarize its \
major processes into one sentence using less than 30 words \

{labels}

NOTE: No need to say "The process ..." at the beginning, say the content directly.
"""


CODE_INSTRUCT = """The following is a description of some process using \
mix of human language and python syntax. Please help to summarize its major \
processes into one sentence using less than 30 words.
"""

GENERAL_FORMAT_INSTRUCT = """
NOTE: No need to say 'The process ...' at the beginning, say the content directly.
"""

FORMAT_HOLDER = """
The summarized sentence should follow format `{format}`
"""

CODE_HOLDER = """
```python
{code}
```
"""
SUMMARY_HOLDER = """

{summaries}
"""

CALL_FORMAT = "Call the <xxx function> by providing <xxx inputs> to get/do <xxxx>."
ASSIGN_FORMAT = "Assign <xxx> to <yyyy>."
IF_FORMAT = "If <xxx> do <xxx> (else <xxx>)."

from codebase_analyzer.flowchart.node import (
    ActionNode,
    BaseFlowchartNode,
    ContextPair,
    DecisionNode,
)
from codebase_analyzer.parser.uri import Uri


class NodeLabelerMixin(BaseModel):
    """Generates labels for nodes."""

    call_api: bool = False
    dump: bool = True
    dump_dir: Path = Field(default=Path(__file__).parent / "convert_dump")
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0

    @root_validator(pre=False)
    def clear_dump_files(cls, values: dict) -> dict:
        dump = values.get("dump")
        if not dump:
            return values
        csv_file = values.get("dump_dir") / "labels.csv"
        if csv_file.exists():
            csv_file.unlink()

        csv_file.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_file, "a+", newline="") as f:
            csv_writer = csv.writer(f)
            csv_writer.writerow(
                [
                    "uuid",
                    "code",
                    "text",
                    "labels",
                    "response",
                    "prompt",
                ]
            )
        return values

    @property
    def dump_csv(self) -> Path:
        return self.dump_dir / "labels.csv"

    def save_to_md(self, uuid: str, prompt: str, response: str) -> Path:
        uri = Uri.from_node_uuid(uuid=uuid)
        file = "_".join(uuid.split(":")[1:])
        dump_path = self.dump_dir / uri.dump_dir / "prompts" / f"{file}.md"
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        text = f"""`uuid = {uuid}`
# Prompt
{prompt}
# Response
{response}
"""
        dump_path.write_text(text)

    def save_to_csv(
        self,
        *,
        uuid: str,
        response: str,
        prompt: str,
        code: str = "",
        text: str = "",
        labels: str = "",
    ) -> None:
        with open(self.dump_csv, "a+", newline="") as f:
            csv_writer = csv.writer(f)
            csv_writer.writerow(
                [
                    uuid,
                    code,
                    text,
                    labels,
                    response,
                    prompt,
                ]
            )

    def call_llm(
        self,
        template: str,
        inputs: dict[str, str],
        uuid: str,
        model: str = "gpt-4-1106-preview",
    ) -> str:
        prompt = template.format(**inputs)
        input_str = "\n".join([f"{k}:\n{v}" for k, v in inputs.items()])
        if not self.call_api:
            response = input_str
        else:
            llm = ChatOpenAI(
                model=model,
                temperature=0,
                verbose=True,
                streaming=True,
                callbacks=[BotStreamingStdOutCallbackHandler()],
            )
            try:
                with get_openai_callback() as cb:
                    response = llm.invoke(prompt).content
                    self.prompt_tokens += cb.prompt_tokens
                    self.completion_tokens += cb.completion_tokens
                    self.total_cost += cb.total_cost
            except Exception as e:
                logger.error(e)
                response = f"Error when calling {model=}"

        if self.dump:
            self.save_to_md(uuid=uuid, prompt=prompt, response=response)
            self.save_to_csv(uuid=uuid, **inputs, response=response, prompt=prompt)

        return response

    def code_prompt_template(self, format: str | None = None) -> str:
        prompt = CODE_INSTRUCT
        if format:
            prompt += FORMAT_HOLDER.format(format=format)
        else:
            prompt += GENERAL_FORMAT_INSTRUCT
        prompt += CODE_HOLDER
        return prompt

    def label_from_text(self, text: str, uuid: str) -> str:
        return self.call_llm(
            uuid=uuid,
            template=REFINE_TEXT_TEMPLATE,
            inputs=dict(text=text),
        )

    def label_from_code(self, code: str, uuid: str) -> str:
        """ "Generates labels for nodes."""
        # TODO: If just a variable, return its meaning in the namespace.
        return self.call_llm(
            uuid=uuid,
            template=self.code_prompt_template(),
            inputs=dict(code=code),
        )

    def label_from_labels(self, labels: str, uuid: str) -> str:
        """Summarizes the labels of a list of nodes."""
        return self.call_llm(
            template=SUMMARIZE_LABELS_TEMPLATE,
            inputs=dict(labels=labels),
            uuid=uuid,
        )

    def label_from_linear_labels(
        self, nodes: list[BaseFlowchartNode], uuid: str
    ) -> str:
        """Summarizes the labels of a list of nodes."""
        return self.label_from_labels(
            labels="\n".join([node.label for node in nodes if node]),
            uuid=uuid,
        )

    def label_from_if_labels(
        self,
        start: BaseFlowchartNode,
        test: DecisionNode,
        true: ActionNode,
        false: ActionNode,
        uuid: str,
    ) -> str:
        """Summarizes the labels of a if node."""
        prepare = ""
        if start.label != test.label:
            prepare = start.label
        return self.label_from_labels(
            labels=prepare
            + f"\nif results of `{test.label}` is True:\n\t{true.label}\n"
            + (f"else:\n\t{false.label}" if false else ""),
            uuid=uuid,
        )

    def label_from_for_labels(
        self, foriter: ActionNode, body: ActionNode, orelse: ActionNode, uuid: str
    ) -> str:
        """Summarizes the labels of a for node."""
        return self.label_from_labels(
            labels=f"{foriter.label}:\n\t{body.label}\n"
            + (f"else:\n\t{orelse.label}" if orelse else ""),
            uuid=uuid,
        )

    def label_from_try_labels(
        self,
        body: ActionNode,
        excepts: list[DecisionNode],
        orelse: ActionNode,
        final: ActionNode,
        uuid: str,
    ) -> str:
        """Summarizes the labels of a try node."""
        except_labels = "\nOtherwise ".join(
            [f"{exc.label}:\n\t{exc.true.label}" for exc in excepts]
        )
        return self.label_from_labels(
            labels=f"try:\n\t{body.label}\n{except_labels}"
            + (f"\nelse:\n\t{orelse.label}" if orelse else "")
            + (f"\nfinally:\n\t{final.label}" if final else ""),
            uuid=uuid,
        )

    def label_from_with_labels(
        self, contexts: list[ContextPair], body: ActionNode, uuid: str
    ) -> str:
        """Summarizes the labels of a with node."""
        get_ctxs = [ctx.get_ctx.label for ctx in contexts]
        enters = [ctx.enter.label for ctx in contexts]
        exits = [ctx.exit.label for ctx in reversed(contexts)]
        return self.label_from_labels(
            labels="\n".join(get_ctxs + enters + [body.label] + exits),
            uuid=uuid,
        )

    def label_from_while_labels(
        self,
        start: BaseFlowchartNode,
        test: DecisionNode,
        body: ActionNode,
        orelse: ActionNode,
        uuid: str,
    ) -> str:
        """Summarizes the labels of a while node."""
        label = ""
        if start.label != test.label:
            label = start.label
        return self.label_from_labels(
            labels=label
            + f"while {test.label}:\n\t{body.label}\n"
            + (f"else:\n\t{orelse.label}" if orelse else ""),
            uuid=uuid,
        )

    def ast_format(self, ast_node: ast.AST) -> str | None:
        if isinstance(ast_node, ast.Call):
            return CALL_FORMAT
        elif isinstance(ast_node, ast.Assign):
            return ASSIGN_FORMAT
        elif isinstance(ast_node, ast.If):
            return IF_FORMAT
        else:
            return None

    def label_from_ast(self, ast_node: ast.AST, uuid: str) -> str:
        """Summarizes the code of a call node."""
        format = self.ast_format(ast_node=ast_node)
        code = ast.unparse(ast_node)

        return self.call_llm(
            uuid=uuid,
            template=self.code_prompt_template(format),
            inputs=dict(code=code),
        )


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
        messages=REFINE_TEXT_TEMPLATE,
        inputs=dict(text=text),
        output_key=output_key,
        output_path=output_path,
        call_api=True,
        model="gpt-4-1106-preview",
        # model="gpt-4",
        # model="gpt-3.5-turbo",
    )
# %%
