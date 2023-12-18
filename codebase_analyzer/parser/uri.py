from __future__ import annotations

import re
from pathlib import Path
from typing import NewType

URI = NewType("URI", str)

# TODO: Make a URI class that can parse the URI and provide useful methods


def uri_stem(uri: URI) -> str:
    parts = re.split(r"[/.]", str(uri))
    return parts[-1]


def uri_full_func_name(uri: URI) -> str:
    parts = re.split(r"[/]", str(uri))
    return parts[-1]


def uri_to_path(uri: URI) -> Path:
    """Converts a URI to a Path object."""
    parts = re.split(r"[/]", str(uri))[1:]  # Remove the first empty string
    assert 1 <= len(parts) <= 2, "URI must have 1 or 2 parts separated by `/`"
    names = parts[0].split(".")
    file = Path("/".join(names))
    if len(parts) == 2:
        file = file / parts[1].replace(".", "/")
    return file


def node_uuid_to_uri(uuid: str) -> URI:
    """Finds the URI of the function in which a flowchart node is in."""
    return uuid.split(":")[0]
