from __future__ import annotations

from pathlib import Path


def uri_to_path(uri: str) -> str:
    # TODO: Think about cases having functions, for now this is OK because
    # AgentExecutorBot will only be used for Module and Packages
    return uri.replace(".", "/")
