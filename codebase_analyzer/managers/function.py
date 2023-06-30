"""This module contains the FunctionBotManager class."""
from pathlib import Path

import pandas as pd
from singleton_decorator import singleton

from codebase_analyzer.bots.function import FunctionBot


@singleton
class FunctionBotManager:
    def __init__(self) -> None:
        self.function_bots: dict[str, FunctionBot] = {}

    def bot_id(self, file_path: Path, function_name: str) -> str:
        """Get a unique bot id for a given function name and file path."""
        return f"{file_path}/{function_name}"

    def get_bot(
        self, file_path: Path, function_name: str, code_info: pd.DataFrame
    ) -> FunctionBot:
        """Get a function bot for a given function name and file path."""

        # NOTE: Currently using absolute path to the file to include repo path
        bot_id = self.bot_id(file_path, function_name)
        if bot_id not in self.function_bots:
            # NOTE: Use the code info to get the function code but might change to reading file
            function_code = code_info.loc[
                code_info["name"] == function_name, "code"
            ].values[0]
            self.function_bots[bot_id] = FunctionBot.from_str_code(
                file_path=file_path,
                function_name=function_name,
                function_code=function_code,
            )
        return self.function_bots[bot_id]
