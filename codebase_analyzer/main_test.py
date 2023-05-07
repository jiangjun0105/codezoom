from __future__ import annotations

from unittest import mock

from click.testing import CliRunner

from codebase_analyzer.bots import CodebaseBot, MasterBot
from codebase_analyzer.main import cli, main
from codebase_analyzer.test_data import sample_embedding
from codebase_analyzer.test_utils import TestChat, generate_gpt_responses

human = "human_input"
master_bot = "api_return"
codebase_bot = "api_return"
function_bot = "api_return"


@mock.patch(
    "codebase_analyzer.chatbot.openai.ChatCompletion.create",
)
@mock.patch("builtins.input")
@mock.patch(
    "codebase_analyzer.embedding.get_embedding", return_value=sample_embedding
)
def test_e2e(
    mock_embedding: mock.MagicMock,
    mock_input: mock.MagicMock,
    mock_api: mock.MagicMock,
) -> None:
    """End-to-end test of the codebase analyzer."""
    chat = TestChat(actors={human, master_bot, codebase_bot})
    chat.send(human, "What is this codebase about?")
    chat.send(
        master_bot,
        "I need to ask the codebase bot.\nCommand: codebase_bot.ask('What is this codebase about?')",
    )
    chat.send(codebase_bot, "Answer: This codebase is about a chatbot.")
    chat.send(human, "Can you summarize the main function of the code?")
    chat.send(
        master_bot,
        "I need to ask the codebase bot.\nCommand: codebase_bot.ask('Can you summarize the main function?')",
    )
    chat.send(codebase_bot, 'Command: ask_function("main", "summary")')
    chat.send(function_bot, "main function is the entry point of the program.")
    chat.send(
        codebase_bot, "Answer: main function is the entry point of the program."
    )
    chat.send(human, "exit")

    mock_input.side_effect = chat.get(human)
    mock_api.side_effect = [
        generate_gpt_responses(r) for r in chat.get("api_return")
    ]
    main(
        repo="~/ChatGPT/src/revChatGPT/V1.py",
        cache=".cache/code_info.csv",
    )


@mock.patch("codebase_analyzer.main.main")
def test_cli(mock_analyzer: mock.MagicMock) -> None:
    """Test the CLI."""
    # Given
    mock_analyzer.return_value = None
    want_repo = "~/ChatGPT/src/revChatGPT/V1.py"
    want_cache = ".cache/code_info.csv"

    # When
    runner = CliRunner()
    runner.invoke(cli, ["--repo", want_repo, "--cache", want_cache])

    # Then
    mock_analyzer.assert_called_once_with(repo=want_repo, cache=want_cache)


if __name__ == "__main__":
    """Workaround for pytest cannot give original log format."""
    test_e2e()
