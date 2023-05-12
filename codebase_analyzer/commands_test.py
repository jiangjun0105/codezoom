from __future__ import annotations

import pytest

from codebase_analyzer.commands import parse_function_call


@pytest.mark.parametrize(
    "given,expected",
    [
        ("test()", ("test", [], {})),
        ("test('a')", ("test", ["a"], {})),
        ("test('a', 'b')", ("test", ["a", "b"], {})),
        ("test('a', 'b', c=1)", ("test", ["a", "b"], {"c": 1})),
    ],
)
def test_parse_function_call(given, expected):
    assert parse_function_call(given) == expected
