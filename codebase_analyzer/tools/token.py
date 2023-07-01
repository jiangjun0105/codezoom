"""Tokenization tools."""

import tiktoken

# cl100k_base is used for gpt-4, gpt-3.5-turbo, text-embedding-ada-002
# https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
OPEN_AI_ENCODING = "cli100k_base"


def tokenize(text: str, model_name: str = "gpt-3.5-turbo") -> list[int]:
    """Tokenize the given text."""
    encoding = tiktoken.encoding_for_model(model_name=model_name)
    return encoding.encode(text)
