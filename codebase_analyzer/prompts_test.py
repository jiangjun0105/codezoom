from __future__ import annotations

from unittest import mock

import numpy as np
import pandas as pd

from codebase_analyzer.prompts import question_prompt
from codebase_analyzer.test_data import sample_embedding


# skip this test
@mock.patch("codebase_analyzer.prompts.find_relevant_code_info")
def _test_question_prompt(mock_info: mock.MagicMock):
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
    mock_info.return_value = codebase_info
    p = question_prompt(question=question, codebase_info=codebase_info)
    assert p is not None
    assert isinstance(p, str)
    assert (
        """
test1: test1
test2: test2
test3: test3"""
        in p
    )
