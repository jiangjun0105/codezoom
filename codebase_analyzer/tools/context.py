"""Common utilities for building bot and bot tools."""
from __future__ import annotations

from enum import Enum

from codebase_analyzer.tools.token import tokenize


class LengthUnit(str, Enum):
    CHAR = "char"
    LINE = "line"
    TOKEN = "token"


def length_in_token(code: str) -> int:
    """For getting the length of the code in token."""
    return len(tokenize(code))


def get_str_length(code: str, unit: LengthUnit = LengthUnit.TOKEN) -> int:
    """For getting the length of the code."""
    if unit == LengthUnit.CHAR:
        return len(code)
    elif unit == LengthUnit.LINE:
        return len(code.split("\n"))
    elif unit == LengthUnit.TOKEN:
        return len(tokenize(code))
    else:
        raise ValueError(f"Unknown unit {unit}.")
