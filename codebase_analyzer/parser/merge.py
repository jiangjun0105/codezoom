"""Merge the call graph information into the definition tree."""

import json
from pathlib import Path

from loguru import logger

from codebase_analyzer.parser.callgraph import URI, Index, extract_call_info
from codebase_analyzer.parser.codeinfo import generate_summary_embedding
from codebase_analyzer.parser.deftree import CodeNode, generate_def_tree

METADATA_KEY = "metadata"
NODE_KEY = "nodes"


def _idx_to_node(
    uri2node: dict[URI, CodeNode],
    idx: Index,
    index2uri: dict[Index, URI],
) -> CodeNode:
    """Converts index to CodeNode."""
    uri = index2uri[idx]
    return uri2node[uri]


def generate_merge_fasten_graph(
    entry_point: Path,
    output_path: Path,
    uri2node: dict[URI, CodeNode],
    repo_root: Path,
) -> CodeNode:
    """Generates call graph and merges it into the definition tree."""
    if not entry_point.is_relative_to(repo_root):
        raise ValueError(f"{entry_point=} is not inside {repo_root=}.")

    fasten = extract_call_info(entry_point=entry_point, output_path=output_path)

    # Merge call graph
    for call in fasten.graph.internalCalls:
        caller_node = _idx_to_node(uri2node, call.caller, fasten.index2uri)
        callee_node = _idx_to_node(uri2node, call.callee, fasten.index2uri)
        caller_node.calls.append(callee_node.uri)
        callee_node.called_by.append(caller_node.uri)

    # Merge inheritance
    for subclass, superclass in fasten.inheritance:
        if superclass.startswith("//"):
            logger.info(f"Skipping external {superclass=} for now.")
            continue

        sub_node = uri2node[subclass]
        super_node = uri2node[superclass]
        sub_node.superclasses.append(super_node.uri)
        super_node.subclasses.append(sub_node.uri)
    return


def generate_and_merge_all(
    repo_root: Path, output_path: Path, entry_point: Path, uri_prefix: str = ""
) -> CodeNode:
    """Generates the definition tree and merges call graph information."""
    root_node, uri2node = generate_def_tree(
        repo_root=repo_root, uri_prefix=uri_prefix
    )
    generate_merge_fasten_graph(
        uri2node=uri2node,
        output_path=output_path,
        repo_root=repo_root,
        entry_point=entry_point,
    )
    generate_summary_embedding(root=root_node, uri2node=uri2node)
    # Can merge more other relations here.
    return root_node, uri2node


def save_nodes_to_disk(
    root_node: CodeNode, uri2node: dict[URI, CodeNode], output_path: Path
) -> None:
    """Saves the nodes into disk."""
    cache = {
        NODE_KEY: uri2node,
        METADATA_KEY: dict(
            root=root_node.uri,
            count=len(uri2node),
        ),
    }
    # TODO: save summaries and embeddings separately to a vector store.
    with open(output_path, "w") as f:
        json.dump(cache, f, default=lambda n: n.dict())


def load_nodes_from_dick(input_path: Path) -> dict[URI, CodeNode]:
    with open(input_path, "r") as f:
        cache = json.load(f)
    uri2node = {uri: CodeNode(**d) for uri, d in cache[NODE_KEY].items()}
    return uri2node


if __name__ == "__main__":
    # repo_root = Path(
    #     "/Users/jun/Projects/ichigen-coder/codebase_analyzer/tests/data"
    # )
    # entry_point = Path(
    #     "/Users/jun/Projects/ichigen-coder/codebase_analyzer/tests/data/short.py"
    # )
    # output_path = Path(
    #     "/Users/jun/Projects/ichigen-coder/codebase_analyzer/tests/data/fasten.json"
    # )
    # uri_prefix = "/codebase_analyzer.tests.data"
    # root_node, uri2node = generate_and_merge_all(
    #     repo_root=repo_root,
    #     output_path=output_path,
    #     entry_point=entry_point,
    #     uri_prefix=uri_prefix,
    # )
    # save_nodes_to_disk(root_node=root_node, uri2node=uri2node, output_path="./nodes.json")
    # load_nodes_from_dick(input_path=Path("./nodes.json"))
    pass
