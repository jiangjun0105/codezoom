from __future__ import annotations

from unittest import mock

from click.testing import CliRunner

from codebase_analyzer.main import main
from codebase_analyzer.test_data import openai_returns, test_inputs


@mock.patch(
    "codebase_analyzer.chatbot.openai.ChatCompletion.create",
    return_value=openai_returns,
)
@mock.patch("builtins.input", side_effect=test_inputs)
def test_main(mock_input: mock.MagicMock, openai_mock: mock.MagicMock) -> None:
    """End-to-end test of the codebase analyzer."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--repo",
            "~/ChatGPT/src/revChatGPT/V1.py",
            "--cache",
            ".cache/code_info.csv",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"Command failed with exit code {result.exit_code}"


if __name__ == "__main__":
    """Workaround for pytest cannot give original log format."""
    test_main()
