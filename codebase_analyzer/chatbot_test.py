from __future__ import annotations

from unittest import mock

import pytest

from codebase_analyzer.chatbot import Chatbot
from codebase_analyzer.test_data import sample_gpt_returns


@mock.patch("codebase_analyzer.chatbot.openai.ChatCompletion.create")
def test_ask_chatbot(
    mock_openai: mock.MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Test ask_chatbot function."""
    # Given
    mock_openai.return_value = sample_gpt_returns
    want_msg = ["How ", "are ", "you?"]

    # When
    with caplog.at_level(level="DEBUG"):
        chatbot = Chatbot(name="test_bot")
        chatbot.ask(prompt="Hi!", asked_by="TESTER")

    # Then
    for r, t in zip(caplog.records, want_msg):
        assert r.message == t
