from __future__ import annotations

from unittest import mock

import numpy as np
import pandas as pd

from codebase_analyzer.embedding import search_functions
from codebase_analyzer.test_data import sample_embedding


def test_find_relevant_code_info():
    # Given
    length = len(sample_embedding)
    codebase_info = pd.DataFrame(
        {
            "name": ["test1", "test2", "test3"],
            "summary": ["test1", "test2", "test3"],
            "code": ["test1", "test2", "test3"],
            "embedding": [np.zeros(length), sample_embedding, np.ones(length)],
        }
    )
    question = "test question"

    # When
    with mock.patch(
        "codebase_analyzer.embedding.get_embedding", return_value=sample_embedding
    ):
        res = search_functions(code_query=question, df=codebase_info)

    # Then
    assert len(res) == 1
    assert res.loc[1, "name"] == "test2"
