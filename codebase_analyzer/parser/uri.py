from __future__ import annotations

import re
from pathlib import Path
from typing import NewType

URI = NewType("URI", str)

# TODO: Make a URI class that can parse the URI and provide useful methods


def uri_stem(uri: URI) -> str:
    parts = re.split(r"[/.]", str(uri))
    return parts[-1]
