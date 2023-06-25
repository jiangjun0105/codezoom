"""This module contains the FunctionBotManager class."""
from pathlib import Path

import pandas as pd
from singleton_decorator import singleton

from codebase_analyzer.bots.function import FunctionBot


@singleton
class FunctionBotManager:
    def __init__(self, codebase_info: dict[str, pd.DataFrame]) -> None:
        self.codebase_info = codebase_info
        self.function_bots: dict[str, FunctionBot] = {}

    def bot_id(self, file_path: Path, function_name: str) -> str:
        """Get a unique bot id for a given function name and file path."""
        return f"{file_path}/{function_name}"

    def get_bot(self, file_path: Path, function_name: str) -> FunctionBot:
        """Get a function bot for a given function name and file path."""
        bot_id = self.bot_id(file_path, function_name)
        if bot_id not in self.function_bots:
            code_info = self.codebase_info[str(file_path.expanduser())]
            function_code = code_info.loc[
                code_info["name"] == function_name, "code"
            ].values[0]
            self.function_bots[bot_id] = FunctionBot.from_str_code(
                file_path=file_path,
                function_name=function_name,
                function_code=function_code,
            )
        return self.function_bots[bot_id]
