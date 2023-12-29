from __future__ import annotations

import re
from pathlib import Path
from typing import NewType

from pydantic import BaseModel

URI = NewType("URI", str)

# TODO: Make a URI class that can parse the URI and provide useful methods


def uri_stem(uri: URI) -> str:
    parts = re.split(r"[/.]", str(uri))
    return parts[-1]


class Uri(BaseModel):
    modules: list[str]
    functions: list[str] | None = None  # Could be Class and methods

    @classmethod
    def from_fasten_uri(cls, uri: str) -> URI:
        """E.g. /auto_gpt.config.config/Config.from_dict"""
        parts = re.split(r"[/]", uri)
        assert 2 <= len(parts) <= 3, "URI must have 3 or 2 parts separated by `/`"
        modules = parts[1].split(".")
        functions = None
        if len(parts) == 3:
            functions = parts[2].split(".")
        return cls(modules=modules, functions=functions)

    @classmethod
    def from_node_uuid(cls, uuid: str) -> URI:
        fasten_uri = uuid.split(":")[0]
        return cls.from_fasten_uri(fasten_uri)

    def __str__(self) -> str:
        string = f"/{'.'.join(self.modules)}"
        if self.functions:
            string += f"/{'.'.join(self.functions)}"
        return string

    def __hash__(self) -> int:
        return self.__str__().__hash__()

    def __eq__(self, other: URI | Uri) -> bool:
        return str(self) == str(other)

    @property
    def file(self) -> Path:
        return Path(f"{self.modules[-1]}")

    @property
    def pyfile(self) -> Path:
        return self.file.with_suffix(".py")

    @property
    def dir(self) -> Path:
        return Path("/".join(self.modules[:-1]))

    @property
    def path(self) -> Path:
        return self.dir / self.file

    @property
    def pypath(self) -> Path:
        return self.dir / self.pyfile

    @property
    def function(self) -> str:
        return ".".join(self.functions) if self.functions else ""

    @property
    def dump_dir(self) -> Path:
        return self.path / self.function.replace(".", "/")


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
