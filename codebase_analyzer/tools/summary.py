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

from codebase_analyzer.tools.context import LengthUnit, get_str_length

SYSTEM_TEMPLATE = (
    "Your task is to generate a summary for the given code or descriptions of code/module/package following huamn's instructions."
    "If provided some code, please analyze the code and generate a clear, concise, and accurate summary of its purpose, functionality, and key operations. "
    "If provided some desriptions of a package/module, please generate the summary by keeping the most important functionalities and operations. "
    "Some reference might be provieded to help you understand the code better. Please take them into consideration if provided."
    "Your goal is to help someone who cannot see the original info to understand its main function and how it works quickly."
)

# FIXME: the length restriction is not working well for 3.5. Should I use gpt-4?
HUMAN_TEMPLATE = """Summarize the target code/descriptions using less than {want_tokens} tokens.

{code}
"""

DEBUG_LOG = """
** Input code **
{code}

** Got summary **
{response}

** Token usage **
* Comporession ratio: {ratio}
* Input code: {code_tokens} tokens
* Wanted: {want_tokens} tokens
* Actual used: {got_tokens} tokens
"""


class SummaryBot(BaseModel):
    """A bot that summarizes code."""

    # TODO: Use config to manage this bot's llm_model.
    llm_model: str = "gpt-3.5-turbo"
    ratio: float = 15
    min_tokens: int = 20
    max_tokens: int = 100
    chain: LLMChain

    @root_validator(pre=True)
    def init_chain(cls, values):
        system = SystemMessagePromptTemplate.from_template(SYSTEM_TEMPLATE)
        human = HumanMessagePromptTemplate.from_template(HUMAN_TEMPLATE)
        chat_prompt = ChatPromptTemplate.from_messages([system, human])
        llm_model = values.get("llm_model", "gpt-3.5-turbo")
        llm = ChatOpenAI(temperature=0, model=llm_model)
        values["chain"] = LLMChain(llm=llm, prompt=chat_prompt)
        return values

    def summarize_code(self, code: str) -> str:
        """Summarize the code using LLM model."""
        code_tokens = get_str_length(code, LengthUnit.TOKEN)
        want_tokens = self.get_want_tokens(code_tokens)
        response = self.chain.run(want_tokens=want_tokens, code=code)
        self.report(
            code=code,
            code_tokens=code_tokens,
            response=response,
            want_tokens=want_tokens,
        )
        return response

    async def asummarize_code(self, code: str) -> str:
        """Async summarize the code using LLM model."""
        code_tokens = get_str_length(code, LengthUnit.TOKEN)
        want_tokens = self.get_want_tokens(code_tokens)
        response = await self.chain.arun(want_tokens=want_tokens, code=code)
        self.report(
            code=code,
            code_tokens=code_tokens,
            response=response,
            want_tokens=want_tokens,
        )
        return response

    def get_want_tokens(self, code_tokens: int) -> int:
        """Calculate the number of tokens to use for summarization."""
        # TODO: use a better algorithm
        return min(
            self.max_tokens, max(self.min_tokens, int(code_tokens / self.ratio))
        )

    def report(
        self, code: str, code_tokens: int, want_tokens: int, response: str
    ) -> None:
        got_tokens = get_str_length(response, LengthUnit.TOKEN)
        logger.debug(
            DEBUG_LOG.format(
                code=code,
                response=response,
                ratio=self.ratio,
                code_tokens=code_tokens,
                want_tokens=want_tokens,
                got_tokens=got_tokens,
            )
        )
