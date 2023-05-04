openai_returns = [
    {
        "choices": [
            {"delta": {"role": "assistant"}, "finish_reason": "null", "index": 0}
        ],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    },
    {
        "choices": [
            {"delta": {"content": "How "}, "finish_reason": "null", "index": 0}
        ],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    },
    {
        "choices": [
            {"delta": {"content": "are "}, "finish_reason": "null", "index": 0}
        ],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    },
    {
        "choices": [
            {"delta": {"content": "you?"}, "finish_reason": "null", "index": 0}
        ],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    },
    {
        "choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    },
]

test_inputs = ["remind", "test query", "exit"]


def _start_response(role: str = "assistant") -> dict:
    return {
        "choices": [{"delta": {"role": role}, "finish_reason": "null", "index": 0}],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    }


def _middle_response(content: str) -> dict:
    return {
        "choices": [
            {"delta": {"content": content}, "finish_reason": "null", "index": 0}
        ],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    }


def _end_response() -> dict:
    return {
        "choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
        "created": 1677825464,
        "id": "chatcmpl-6ptKyqKOGXZT6iQnqiXAH8adNLUzD",
        "model": "gpt-3.5-turbo-0301",
        "object": "chat.completion.chunk",
    }


def generate_gpt_responses(content: str) -> list[dict]:
    yield _start_response()
    for c in content.split(" "):
        # Split using whitespace
        yield _middle_response(c + " ")
    yield _end_response()


class TestChat:
    def __init__(self, actors: list[str]):
        for a in actors:
            setattr(self, a, [])

    def send(self, actor: str, message: str):
        getattr(self, actor).append(message)

    def get(self, actor: str) -> list[str]:
        return getattr(self, actor)
