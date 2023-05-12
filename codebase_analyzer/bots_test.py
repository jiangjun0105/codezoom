from __future__ import annotations

from unittest import mock

import pandas as pd

from codebase_analyzer.bots import CodebaseBot, MasterBot
from codebase_analyzer.logs import SpeakerType, human_logger
from codebase_analyzer.test_data import sample_embedding, sample_gpt_returns
from codebase_analyzer.test_utils import TestChat, generate_gpt_responses


@mock.patch(
    "codebase_analyzer.chatbot.openai.ChatCompletion.create",
)
@mock.patch(
    "codebase_analyzer.embedding.get_embedding", return_value=sample_embedding
)
def test_codebase_bot(
    mock_embedding: mock.MagicMock,
    mock_api: mock.MagicMock,
) -> None:
    """End-to-end test of the codebase analyzer."""
    human = "human"
    bot = "bot"
    chat = TestChat(actors=[human, bot])
    chat.send(human, "What is this codebase about?")
    chat.send(bot, "Answer: This codebase is about a chatbot.")
    # chat.send(human, "Can you summarize the main function of the code?")
    # chat.send(bot, 'Command: ask_function("main", "summary")')
    # chat.send(bot, "main function is the entry point of the program.")
    # chat.send(bot, "Answer: main function is the entry point of the program.")
    chat.send(human, "Can you show me the code of main()?")
    chat.send(bot, "Command: get_relevant_functions('main', 'code')")
    chat.send(
        bot,
        """Answer:
def main():
    print("Hello World!")
    d = {"a": 1, "b": 2}
    return d
""",
    )

    mock_api.side_effect = [generate_gpt_responses(r) for r in chat.get(bot)]
    codebase_bot = CodebaseBot(
        repo="~/ChatGPT/src/revChatGPT/V1.py",
        cache=".cache/code_info.csv",
    )
    for q in chat.get(human):
        human_logger.info(f"HUMAN: {q}", speaker=SpeakerType.HUMAN)
        codebase_bot.ask(prompt=q, asked_by="human")


@mock.patch(
    "codebase_analyzer.chatbot.openai.ChatCompletion.create",
    side_effect=[generate_gpt_responses("Answer: OK") for _ in range(2)],
)
def test_codebase_bot_no_memory(mock_api: mock.MagicMock):
    """Tests if the codebase bot will be reset every time."""

    codebase_bot = CodebaseBot(
        repo="~/ChatGPT/src/revChatGPT/V1.py",
        cache=".cache/code_info.csv",
    )
    token1 = codebase_bot.bot.get_token_count()
    codebase_bot.ask(prompt="What is this codebase about?", asked_by="tester")
    token2 = codebase_bot.bot.get_token_count()
    codebase_bot.ask(prompt="Can you show me the main function?", asked_by="tester")
    token3 = codebase_bot.bot.get_token_count()
    assert token1 == token2 == token3


if __name__ == "__main__":
    test_codebase_bot()
