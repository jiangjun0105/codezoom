from langchain.chains import LLMChain
from langchain.chat_models import ChatOpenAI
from langchain.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from loguru import logger
from pydantic import BaseModel, root_validator
from tqdm import tqdm

from codebase_analyzer.common.credentials import get_api_key
from codebase_analyzer.tools.context import CodeLengthUnit, get_code_length

SYSTEM_TEMPLATE = (
    "Your task is to analyze the provided code and provide a clear, concise, and accurate summary of its purpose, functionality, and key operations. "
    "Your goal is to help someone who cannot see the code to understand its main function and how it works quickly."
)

# FIXME: the length restriction is not working well for 3.5. Should I use gpt-4?
HUMAN_TEMPLATE = """Summarize the following code using less than {length} tokens:

{code}
"""

# TODO: Rethink the design of the bot
llm: ChatOpenAI = ChatOpenAI(
    temperature=0, openai_api_key=get_api_key(), model="gpt-3.5-turbo-0613"
)


class SummaryBot(BaseModel):
    ratio: float = 15
    min_tokens: int = 20
    max_tokens: int = 100
    chain: LLMChain

    @root_validator(pre=True)
    def init_chain(cls, values):
        system = SystemMessagePromptTemplate.from_template(SYSTEM_TEMPLATE)
        human = HumanMessagePromptTemplate.from_template(HUMAN_TEMPLATE)
        chat_prompt = ChatPromptTemplate.from_messages([system, human])
        values["chain"] = LLMChain(llm=llm, prompt=chat_prompt)
        return values

    def summarize_code(self, code: str) -> str:
        """Summarize the code using LLM model."""
        code_tokens = get_code_length(code, CodeLengthUnit.TOKEN)
        length = min(
            self.max_tokens, max(self.min_tokens, int(code_tokens / self.ratio))
        )
        logger.debug(f"Length of summary should be {length} tokens.")
        response = self.chain.run(length=length, code=code)
        logger.debug(
            f"Actual length is {get_code_length(response, CodeLengthUnit.TOKEN)}"
        )
        return response

    async def asummarize_code(self, code: str) -> str:
        """Summarize the code using LLM model."""
        code_tokens = get_code_length(code, CodeLengthUnit.TOKEN)
        length = min(
            self.max_tokens, max(self.min_tokens, int(code_tokens / self.ratio))
        )
        logger.debug(f"Length of summary should be {length} tokens.")
        response = await self.chain.arun(length=length, code=code)
        logger.debug(
            f"Actual length is {get_code_length(response, CodeLengthUnit.TOKEN)}"
        )
        return response
