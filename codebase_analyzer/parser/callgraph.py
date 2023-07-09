"""Generates call graph from a given source code repository."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


# Can only extract for a single entry point.
# Sometimes, namespace for function doesn't have ().
def extract_fasten_graph(entry_point: Path, output_path: str) -> dict:
    """Extracts call graph in FASTEN format for a given entry point."""
    subprocess.call(f"pycg --fasten -o {output_path} {entry_point}", shell=True)
    with open(output_path, "r") as f:
        fasten_graph = json.load(f)
    return fasten_graph


def parse_fasten_graph(fasten_graph: dict) -> dict:
    """Parses the call graph in FASTEN format."""
    # For now we only care about the internal modules.
    modules = [
        Module.from_fasten(k, v) for k, v in fasten_graph["modules"]["internal"]
    ]
    calls = fasten_graph["graph"]["internalCalls"]
    # TODO: Parse the call graph.
    # TODO: Make bidirectional call graph.
    ...

    call_graph: dict[Namespace, list[Namespace]] = {
        # The whole call graph, including source file
    }

    # Module including the namespaces in it.
    modules: Module
    return call_graph


def add_ast(call_graph, modules):
    for module in modules:
        # generate AST
        def_tree: CodeNode
        # Find correspondance between CodeNodes and Namespaces by name
        # "/codebase_analyzer.main/calculate_path_hash()",


# schema.py
from pydantic import BaseModel, Field


class Metadata(BaseModel):
    first: int = Field(..., description="First line number.")
    last: int = Field(..., description="Last line number.")


class Namespace(BaseModel):
    name: str = Field(..., description="Namespace name.")
    metadata: Metadata = Field(..., description="Namespace metadata.")
    module: Module = Field(..., description="Which module is in.")


class Module(BaseModel):
    """Module model."""

    name: str = Field(..., description="Module name.")
    source_file: str = Field(..., description="Source file path.")
    namespaces: list[Namespace] = Field(..., description="Module namespaces.")

    @classmethod
    def from_fasten(cls, name: str, value: dict) -> Module:
        namespaces = {i: Namespace.parse_raw(v) for i, v in value["namespaces"]}

        return cls(
            name=name,
            source_file=value["sourceFile"],
            namespaces=namespaces,
        )
