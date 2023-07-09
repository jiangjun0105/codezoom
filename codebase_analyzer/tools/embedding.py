import numpy as np
import openai
import pandas as pd
from langchain.embeddings import OpenAIEmbeddings


def get_embedding(text: str, model: str = "text-embedding-ada-002") -> list[float]:
    """Get the embedding of the given text using OpenAI Embedding API."""
    # TODO: If the embedding is too slow, think about async.
    embeddings = OpenAIEmbeddings(model=model)
    return embeddings.embed_query(text=text)


def embed_codebase(codebase_info: pd.DataFrame) -> pd.DataFrame:
    """Embed the codebase info using OpenAI Embedding API."""
    codebase_info["embedding"] = codebase_info["code"].apply(get_embedding)
    return codebase_info


def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def search_functions(df, code_query, n=1):
    embedding = get_embedding(code_query, model="text-embedding-ada-002")
    df["similarities"] = df.embedding.apply(
        lambda x: cosine_similarity(x, embedding)
    )
    return df.sort_values("similarities", ascending=False).head(n)
