from __future__ import annotations

from unittest import mock

from click.testing import CliRunner

from codebase_analyzer.main import codebase_analyzer, main
from codebase_analyzer.test_data import sample_embedding
from codebase_analyzer.test_utils import TestChat, generate_gpt_responses

human = "test_human"
bot = "test_bot"


@mock.patch(
    "codebase_analyzer.chatbot.openai.ChatCompletion.create",
)
@mock.patch("builtins.input")
@mock.patch(
    "codebase_analyzer.embedding.get_embedding", return_value=sample_embedding
)
def test_codebase_analyzer(
    mock_input: mock.MagicMock,
    mock_api: mock.MagicMock,
    mock_embedding: mock.MagicMock,
) -> None:
    """End-to-end test of the codebase analyzer."""
    chat = TestChat(actors=[human, bot])
    chat.send(human, "What is this codebase about?")
    chat.send(bot, "Answer: This codebase is about a chatbot.")
    chat.send(human, "Can you summarize the main function of the code?")
    chat.send(bot, 'Command: ask_function("main", "summary")')
    chat.send(bot, "main function is the entry point of the program.")
    chat.send(bot, "Answer: main function is the entry point of the program.")
    chat.send(human, "Can you show me the code of main()?")
    chat.send(
        bot,
        """Answer:
def main():
    print("Hello World!")
    d = {"a": 1, "b": 2}
    return d
""",
    )
    chat.send(human, "exit")

    mock_input.side_effect = chat.get(human)
    mock_api.side_effect = [generate_gpt_responses(r) for r in chat.get(bot)]
    codebase_analyzer(
        repo="~/ChatGPT/src/revChatGPT/V1.py",
        cache=".cache/code_info.csv",
    )


@mock.patch(
    "codebase_analyzer.chatbot.openai.ChatCompletion.create",
)
@mock.patch("builtins.input")
@mock.patch(
    "codebase_analyzer.embedding.get_embedding", return_value=sample_embedding
)
def test_codebase_analyzer_simple(
    mock_input: mock.MagicMock,
    mock_api: mock.MagicMock,
    mock_embedding: mock.MagicMock,
) -> None:
    """End-to-end test of the codebase analyzer."""
    human = "human"
    bot = "bot"
    chat = TestChat(actors=[human, bot])
    chat.send(human, "Hello")
    chat.send(bot, "Hello, how can I help you today?")
    chat.send(human, "What is 7x6?")
    chat.send(bot, "Answer: The answer is 42.")
    chat.send(human, "exit")

    mock_input.side_effect = chat.get(human)
    mock_api.side_effect = [generate_gpt_responses(r) for r in chat.get(bot)]
    codebase_analyzer(
        repo="~/ChatGPT/src/revChatGPT/V1.py",
        cache=".cache/code_info.csv",
    )


@mock.patch("codebase_analyzer.main.codebase_analyzer")
def test_main_cli(mock_analyzer: mock.MagicMock) -> None:
    """Test main function."""
    # Given
    mock_analyzer.return_value = None
    want_repo = "~/ChatGPT/src/revChatGPT/V1.py"
    want_cache = ".cache/code_info.csv"

    # When
    runner = CliRunner()
    runner.invoke(main, ["--repo", want_repo, "--cache", want_cache])

    # Then
    mock_analyzer.assert_called_once_with(repo=want_repo, cache=want_cache)


if __name__ == "__main__":
    """Workaround for pytest cannot give original log format."""
    test_codebase_analyzer()
