"""Loop manager for human-bot interactions."""

from __future__ import annotations

from loguru import logger
from pydantic import BaseModel, Field

from codebase_analyzer.bots.executor import Bot
from codebase_analyzer.parser.callgraph import URI


class LoopManager(BaseModel):
    active_bot: Bot = Field(None, description="The bot talking to the user.")
    bot_stack: list[Bot] = Field(
        default_factory=list,
        description="The stack of bots that the user has talked to.",
    )
    pending: dict[URI, str] = Field(
        default_factory=dict,
        description="The pending questions for each bot. The key is the bot's uri.",
    )

    def interaction_loop(self, bot: Bot | None = None) -> None:
        """Main loop for interacting wiht the codebase analyzer."""
        if bot is not None:
            self.switch_bot(switch_to=bot)

        while True:
            query = input("\nEnter a query or type 'exit' to quit: ")
            if query.lower() == "exit":
                break
            if query.lower() == "/who":
                print(self.active_bot.uri)
                continue
            if query.lower() == "/repo_bot":
                self.switch_bot(switch_to=self.bot_stack[0])
                continue
            self.active_bot.ask(inputs=query)
            # The above call might cause some pending questions if switching bots
            if question := self.pending[self.active_bot.uri]:
                logger.info(f"Found Pending {question=}")
                self.active_bot.ask(inputs=question)

    def switch_bot(self, switch_to: Bot) -> None:
        self.active_bot = switch_to
        self.bot_stack.append(switch_to)
