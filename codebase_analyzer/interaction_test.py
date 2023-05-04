from __future__ import annotations

from unittest import mock

import pandas as pd

from codebase_analyzer.interaction import ask_codebase
from codebase_analyzer.parser import load_raw_code
from codebase_analyzer.test_utils import openai_returns, test_inputs


@mock.patch(
    "codebase_analyzer.chatbot.openai.ChatCompletion.create",
    return_value=openai_returns,
)
@mock.patch("builtins.input", side_effect=test_inputs)
def test_ask_codebase(mock_input: mock.MagicMock, openai_mock: mock.MagicMock):
    raw_codebase = load_raw_code("~/ChatGPT/src/revChatGPT/V1.py")
    codebase_info = pd.read_csv(".cache/code_info.csv").set_index("Unnamed: 0")
    ask_codebase(
        question="test query", codebase_info=codebase_info, raw_codebase=raw_codebase
    )
