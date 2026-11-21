# %%
import numpy as np
import pandas as pd
from langchain.embeddings import OpenAIEmbeddings

OPENAI_EMBEDDING_DIM = 1536


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


def search_by_embedding(embeddings: np.array, query: str, n: int = 1) -> list[int]:
    """Returns the indices of n of the most similar embeddings to the query."""
    # TODO: Use vector store to support it.
    query_emb = np.array(get_embedding(text=query))
    # TODO: Use more numpy vector operations.
    # embeddings_norm = np.linalg.norm(embeddings, axis=1)
    # query_emb_norm = np.linalg.norm(query_emb)
    # similarities = embeddings.dot(query) / (embeddings_norm * query_emb_norm)
    similarities = np.array(
        [cosine_similarity(query_emb, emb) for emb in embeddings]
    )
    return similarities.argsort()[::-1][:n]


# %%