"""Generates call graph from a given source code repository."""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import NewType

from loguru import logger
from pydantic import BaseModel, Field, root_validator

Index = NewType("Index", str)
URI = NewType("URI", str)


class Metadata(BaseModel):
    # @singleton decorator confused pgcg so the line numbers are null.
    first: int | None = Field(..., description="First line number.")
    last: int | None = Field(..., description="Last line number.")


class Namespace(BaseModel):
    namespace: URI
    # Exteranl modules's metadata is an empty {}.
    metadata: Metadata | dict


class Module(BaseModel):
    sourceFile: Path
    namespaces: dict[Index, Namespace]


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

    class Config:
        extra = "allow"


def extract_fasten_graph(entry_point: Path, output_path: Path) -> dict:
    """Extracts call graph in FastenGraph format for a given entry point.
    NOTE:
        * Can only extract for a single entry point.
        * Sometimes, namespace for function doesn't have ()."""

    # TODO: Handle multiple entry points.
    try:
        subprocess.call(f"pycg --fasten -o {output_path} {entry_point}", shell=True)
    except Exception as e:
        logger.error(
            f"Error extracting call graph for {entry_point=} {output_path=}"
            "Please ensure that pycg is installed."
        )
        raise e
    with open(output_path, "r") as f:
        fasten_graph = json.load(f)
    return FastenGraph(**fasten_graph)


def parse_fasten_graph(fasten_graph: FastenGraph) -> dict:
    """Parses the call graph in FastenGraph format."""
    caller2callees: dict[Index, list[Index]] = defaultdict(list)
    index2URI: dict[Index, URI] = dict()

    # For now we only care about the internal modules and calls.
    for _uri, module in fasten_graph.modules.internal.items():
        for index, namespace in module.namespaces.items():
            index2URI[index] = namespace.namespace  # URI of namespace

    for call in fasten_graph.graph.internalCalls:
        caller2callees[call.caller].append(call.callee)

    return caller2callees, index2URI


p = "/Users/jun.jiang/ichigen-coder/fasten.json"
with open(p, "r") as f:
    fasten_graph = json.load(f)
fasten_graph = FastenGraph(**fasten_graph)
parse_fasten_graph(fasten_graph)
