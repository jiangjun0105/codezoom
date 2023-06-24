"""Base classes for function bot."""
from pathlib import Path
from typing import Any

from langchain.chains.base import Chain
from langchain.chains.qa_with_sources import load_qa_with_sources_chain
from langchain.docstore.document import Document
from langchain.llms import OpenAI
from langchain.schema import BaseOutputParser
from loguru import logger
from pydantic import BaseModel, root_validator, validator

from codebase_analyzer.bots.base import Bot
from codebase_analyzer.bots.callbacks import BotStreamingStdOutCallbackHandler
from codebase_analyzer.bots.function.prompts import DOC_PROMPT, PROMPT
from codebase_analyzer.common.credentials import get_api_key
from codebase_analyzer.tools.base import load_single_function

function_llm = OpenAI(
    temperature=0,
    openai_api_key=get_api_key(),
    streaming=True,
    callbacks=[BotStreamingStdOutCallbackHandler(color="blue")],
)

FUNCTION_CHAIN = load_qa_with_sources_chain(
    llm=function_llm,
    chain_type="stuff",
    prompt=PROMPT,
    document_prompt=DOC_PROMPT,
    document_variable_name="function_code",
)


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

    TODO: think if we need inherit from BaseSingleActionAgent or just pydantic BaseModel.
    """

    # TODO: Should I use Field default_factory or just assign the value directly?
    # For now maybe just assign the value directly but if later the bot has memory, we need rethink.
    chain: Chain = FUNCTION_CHAIN
    file_path: Path | None = None
    function_name: str | None = None
    function_code: list[Document] | None = None

    @root_validator(pre=True)
    def load_function_code(cls, values: dict) -> dict:
        """Set function code based on file_path and function_name."""
        file_path = values.get("file_path")
        function_name = values.get("function_name")
        function_code = values.get("function_code")

        if function_code is not None:
            if None not in [file_path, function_name]:
                logger.warning(
                    f"Function code is provided. The contents from {file_path}/{function_name} will be ignored."
                )
            return values

        if file_path is None or function_name is None:
            raise ValueError(
                "Either function_code or both file_path and function_name must be provided."
            )

        # TODO: Rethink if we should support two init ways: 1) function_code, 2) file_path & function_name.
        values["function_code"] = load_single_function(
            file_path=file_path, function_name=function_name
        )
        return values

    @validator("function_code", pre=True)
    def set_function_code(cls, function_code: str) -> list[Document]:
        return [
            Document(
                page_content=function_code,
                metadata={"function_length": len(function_code)},
            )
        ]

    def return_function_code(self) -> str:
        if self.function_code is not None:
            return self.function_code[0].page_content
        else:
            raise ValueError("Function code is not provided.")

    def ask(self, question: str) -> Any:
        response = self.chain(
            {"input_documents": self.function_code, "question": question},
            return_only_outputs=True,
        )["output_text"]
        # TODO: Fix a better way to generate trailing newlines.
        return f"Function bot: {response}"


# function_bot = FunctionBot(function_code=func_str)
# print(function_bot.ask("What does this function do?"))
