"""Base classes for function bot."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain.chains.base import Chain
from langchain.chains.qa_with_sources import load_qa_with_sources_chain
from langchain.docstore.document import Document
from langchain.llms import OpenAIChat
from langchain.schema import BaseOutputParser
from loguru import logger
from pydantic import BaseModel, Field, root_validator, validator

from codebase_analyzer.bots.callbacks import BotStreamingStdOutCallbackHandler
from codebase_analyzer.bots.executor import Bot
from codebase_analyzer.bots.function.prompts import DOC_PROMPT, PROMPT
from codebase_analyzer.parser.deftree import CodeNode
from codebase_analyzer.tools.base import load_single_function


class FunctionOutputParser(BaseOutputParser):
    def parse(self, text: str) -> Any:
        # For now, we don't requrie function agent to return any structured response
        return text

    def get_format_instructions(self) -> str:
        return "Please return your response directily."


class FunctionBot(Bot):
    """Function bot that can answer questions about a function.

    NOTE: It's based on the StuffDocumentsChain for now because we haven't give it any tools and just expect
    one round of interaction, ie. one question and one answer. This will be changed in the future.
    """

    # For now maybe just assign the value directly but if later the bot has memory, we need rethink.
    llm_model: str = Field(..., description="gpt-3.5-turbo-0613 or gpt-4-0613")
    code_node: CodeNode = Field(...)
    chain: Chain

    @root_validator(pre=True)
    def init_chain(cls, values: dict) -> dict:
        llm_model = values.get("llm_model")
        function_llm = OpenAIChat(
            model=llm_model,
            temperature=0,
            streaming=True,
            callbacks=[BotStreamingStdOutCallbackHandler(color="blue")],
        )
        values["chain"] = load_qa_with_sources_chain(
            llm=function_llm,
            chain_type="stuff",
            prompt=PROMPT,
            document_prompt=DOC_PROMPT,
            document_variable_name="function_code",
        )
        return values

    @property
    def function_code_document(self) -> list[Document]:
        return [
            Document(
                page_content=self.code_node.code,
                metadata={"function_length": self.code_node.code_length},
            )
        ]

    def ask(self, inputs: str) -> Any:
        response = self.chain(
            {"input_documents": self.function_code_document, "question": inputs},
            return_only_outputs=True,
        )["output_text"]
        return f"Function bot: {response}"


# function_bot = FunctionBot(function_code=func_str)
# print(function_bot.ask("What does this function do?"))
