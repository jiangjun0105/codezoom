"""This module contains the FunctionBotManager class."""
from pathlib import Path

import pandas as pd
from loguru import logger
from pydantic import Field
from singleton_decorator import singleton

from codebase_analyzer.bots.function import FunctionBot
from codebase_analyzer.managers.base import BotManagerBase


@singleton
class FunctionBotManager(BotManagerBase):
    bots: dict[str, FunctionBot] = Field(default_factory=dict)

    def bot_id(self, file_path: Path, function_name: str) -> str:
        """Get a unique bot id for a given function name and file path."""
        return f"{file_path}/{function_name}"

    def get_bot(
        self, file_path: Path, function_name: str, code_info: pd.DataFrame
    ) -> FunctionBot:
        """Get a function bot for a given function name and file path."""
        # TODO: Rethink if file_path/function_name is a good way to identify a function bot
        # Maybe we need to include index and level of the function?
        bot_id = self.bot_id(file_path, function_name)
        if bot_id not in self.bots:
            candidate = code_info.loc[code_info["name"] == function_name, "code"]
            if len(candidate) == 0:
                logger.error(f"Cannot find function {function_name} in {file_path}.")
                return None

            if len(candidate) > 1:
                logger.warning(
                    f"Found {len(candidate)} functions with the same name {function_name} in {file_path} "
                    "It's possbile but rare. Will use code of both functions but please check if the cache is corrupted."
                )

            # TODO: Rethink how to concatenate the code of multiple functions
            function_code = "\n".join(candidate.values)
            self.bots[bot_id] = FunctionBot.from_str_code(
                file_path=file_path,
                function_name=function_name,
                function_code=function_code,
            )
        return self.bots[bot_id]
