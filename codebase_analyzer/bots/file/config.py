from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.chat_models import ChatOpenAI

from codebase_analyzer.common.credentials import get_api_key

LLM = ChatOpenAI(
    temperature=0,
    model="gpt-3.5-turbo-0613",
    # model="gpt-4-0613",
    
    streaming=True,
    client=None,  # TODO: How to fix pydantic error?
)
