"""Generates call graph from a given source code repository."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import NewType

from loguru import logger
from pydantic import BaseModel, Field, root_validator, validator

from codebase_analyzer.parser.uri import URI

Index = NewType("Index", str)


class InvalidNamespaceError(Exception):
    """The namespace is invalid as it doesn't have line numbers."""

    pass


class Metadata(BaseModel):
    # Some namespaces don't have line numbers.
    first: int | None = Field(..., description="First line number.")
    last: int | None = Field(..., description="Last line number.")
    superClasses: list[URI] | None = None


class Namespace(BaseModel):
    namespace: URI
    metadata: Metadata | None

    @validator("metadata", pre=True)
    def check_metadata(cls, value: dict) -> dict:
        # External modules's metadata is an empty {}.
        return None if not value else value


class Module(BaseModel):
    sourceFile: Path
    namespaces: dict[Index, Namespace]

    # @validator("namespaces", pre=True)
    # def filter_namespaces(cls, value: dict) -> dict:
    #     filtered = dict()
    #     for index, namespace in value.items():
    #         if namespace.metadata.get("first", "empty") is None:
    #             continue
    #         filtered[index] = namespace


class Modules(BaseModel):
    internal: dict[URI, Module]
    external: dict[URI, Module]


class Call(BaseModel):
    caller: Index
    callee: Index
    extra: dict

    @classmethod
    def from_list(cls, v: list) -> Call:
        if isinstance(v, list) and len(v) == 3:
            return Call(caller=v[0], callee=v[1], extra=v[2])
        else:
            raise ValueError("Must be a list of length 3.")


class Graph(BaseModel):
    internalCalls: list[Call]
    externalCalls: list[Call]

    @root_validator(pre=True)
    def check_call(cls, values: dict):
        internal = values.get("internalCalls", [])
        external = values.get("externalCalls", [])
        values["internalCalls"] = [Call.from_list(v) for v in internal]
        values["externalCalls"] = [Call.from_list(v) for v in external]
        return values


class FastenGraph(BaseModel):
    modules: Modules
    graph: Graph
    index2uri: dict[Index, URI] = Field(default_factory=dict)
    inheritance: list[tuple[URI, URI]] = Field(default_factory=list)

    class Config:
        extra = "allow"


def extract_fasten_graph(
    entry_point: Path, repo_root: Path, output_path: Path
) -> dict:
    """Extracts call graph in FastenGraph format for a given entry point.
    NOTE:
        * Can only extract for a single entry point.
        * Sometimes, namespace for function doesn't have ()."""

    # TODO: Handle multiple entry points.
    try:
        subprocess.run(
            [
                "pycg",
                "--fasten",
                "--output",
                str(output_path),
                "--package",
                str(repo_root),
                str(entry_point),
            ],
            check=True,
        )
    except Exception as e:
        logger.error(
            f"Error extracting call graph for {entry_point=} {output_path=}"
            "Please ensure that pycg is installed."
        )
        raise e

    with open(output_path, "r") as f:
        return FastenGraph(**json.load(f))


def namespace_to_uri(namespace: str, file: Path | None = None) -> URI:
    """Converts FASTEN python namespace to CodeNode URI. This is to handle some
    corner cases where the namespace doesn't match the URI nameing rules.

    Corner cases:
        * Some function namespace doesn't have () at the end.
        * __init__ is omitted but is needed to be consistent with CodeNode URI.
        * Some namespaces don't have lineno and don't exist in code.
    """
    if file and file.name == "__init__.py":
        left, right = namespace.rsplit("/", 1)
        namespace = f"{left}.__init__/{right}"
    return namespace.rstrip("()")


def extract_extra_info(graph: FastenGraph) -> FastenGraph:
    """Parses the call graph in FastenGraph format."""
    # For now we only care about the internal modules' calls and inheritance.
    for _, module in graph.modules.internal.items():
        for index, namespace in module.namespaces.items():
            if namespace.metadata.first is None:
                graph.index2uri[index] = None
            else:
                uri = namespace_to_uri(namespace.namespace, file=module.sourceFile)
                graph.index2uri[index] = uri
                if not namespace.metadata.superClasses:
                    continue
                for superclass in namespace.metadata.superClasses:
                    # FIXME: We assume superclass is not defined in __init__.py
                    graph.inheritance.append((uri, namespace_to_uri(superclass)))
    return graph


def extract_call_info(
    entry_point: Path, output_path: Path, repo_root: Path
) -> FastenGraph:
    """Extracts call graph for a given entry point."""
    graph = extract_fasten_graph(
        entry_point=entry_point, output_path=output_path, repo_root=repo_root
    )
    graph = extract_extra_info(graph=graph)
    return graph


# TODO: Organize the following tests into a test file.
# p = "/Users/jun/Projects/ichigen-coder/codebase_analyzer/main.py"
# extract_call_info(p, "/Users/jun/Projects/ichigen-coder/codebase_analyzer/main.json")
# pass
