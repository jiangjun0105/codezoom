from __future__ import annotations

from unittest import mock

import pytest

from codebase_analyzer.chatbot import Chatbot
from codebase_analyzer.test_data import openai_returns


@mock.patch("codebase_analyzer.chatbot.openai.ChatCompletion.create")
def test_ask_chatbot(
    mock_openai: mock.MagicMock, caplog: pytest.CaptureFixture
) -> None:
    """Test ask_chatbot function."""
    # Given
    mock_openai.return_value = openai_returns
    chatbot = Chatbot(name="test_bot")

    # When
    with caplog.at_level("BOT_SPEAK", logger="test_bot"):
        chatbot.ask(prompt="Hi!")

    # Then
    assert "How are you!" in caplog.text
