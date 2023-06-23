from langchain.prompts import PromptTemplate

template = """You are a bot belonging to a group of programming bots. You can see code of a specific function and will be asked questions.
If the questions is about the function, you should answer it. If the question is not about the function, you can either provide helpful
information or say the question is not related to the function. Only answer based on the function code and general programming knowledge.


FUNCTION CODE:
=========
{function_code}
=========
QUESTION: {question}

ANSWER:"""


PROMPT = PromptTemplate(
    template=template, input_variables=["function_code", "question"]
)

DOC_PROMPT = PromptTemplate(
    template="Function code: {page_content}\nFunction length: {function_length}",
    input_variables=["page_content", "function_length"],
)
