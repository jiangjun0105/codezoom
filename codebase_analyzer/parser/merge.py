"""Merge the call graph information into the definition tree."""

from pathlib import Path

from loguru import logger

from codebase_analyzer.parser.callgraph import URI, Index, extract_call_info
from codebase_analyzer.parser.deftree import CodeNode, generate_def_tree


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

    fasten_graph = extract_call_info(
        entry_point=entry_point, output_path=output_path
    )

    # Merge call graph
    for call in fasten_graph.graph.internalCalls:
        caller_node = _idx_to_node(uri2node, call.caller, fasten_graph.index2uri)
        callee_node = _idx_to_node(uri2node, call.callee, fasten_graph.index2uri)
        caller_node.calls.append(callee_node)
        callee_node.called_by.append(caller_node)

    # Merge inheritance
    for subclass, superclass in fasten_graph.inheritance:
        if superclass.startswith("//"):
            logger.info(f"Skipping external {superclass=} for now.")
            continue

        subclass_node = uri2node[subclass]
        superclass_node = uri2node[superclass]
        subclass_node.superclasses.append(superclass_node)
        superclass_node.subclasses.append(subclass_node)
    return


def generate_and_merge_all(
    repo_root: Path, output_path: Path, entry_point: Path
) -> CodeNode:
    """Generates the definition tree and merges call graph information."""
    root_node, uri2node = generate_def_tree(repo_root=repo_root)
    generate_merge_fasten_graph(
        uri2node=uri2node,
        output_path=output_path,
        repo_root=repo_root,
        entry_point=entry_point,
    )
    # Can merge more other relations here.
    return root_node


if __name__ == "__main__":
    repo_root = Path("/Users/jun.jiang/ichigen-coder")
    entry_point = Path(
        "/Users/jun.jiang/ichigen-coder/codebase_analyzer/parser/merge.py"
    )
    output_path = Path(
        "/Users/jun.jiang/ichigen-coder/codebase_analyzer/parser/merge.json"
    )
    generate_and_merge_all(
        repo_root=repo_root, output_path=output_path, entry_point=entry_point
    )
