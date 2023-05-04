from __future__ import annotations

from unittest import mock

from click.testing import CliRunner

from codebase_analyzer.main import codebase_analyzer, main
from codebase_analyzer.test_utils import generate_gpt_responses, test_inputs


@mock.patch(
    "codebase_analyzer.chatbot.openai.ChatCompletion.create",
)
@mock.patch("builtins.input", side_effect=test_inputs)
def test_codebase_analyzer(
    mock_input: mock.MagicMock, mock_api: mock.MagicMock
) -> None:
    """End-to-end test of the codebase analyzer."""
    responses = [
        "Hello, how can I help you today?",
        "Answer: The answer is 42.",
    ]
    mock_api.side_effect = [generate_gpt_responses(r) for r in responses]
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
