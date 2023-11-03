"""Merge the call graph information into the definition tree."""

from pathlib import Path

from loguru import logger

from codebase_analyzer.parser.callgraph import Index, extract_call_info
from codebase_analyzer.parser.codeinfo import generate_summary_embedding
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode, generate_def_tree
from codebase_analyzer.parser.uri import URI


class CacheInvalidError(Exception):
    """The cache is invalid."""

    # TODO: Add checks after loading the cache.
    pass


def _idx_to_node(
    uri2node: dict[URI, CodeNode],
    idx: Index,
    index2uri: dict[Index, URI],
) -> CodeNode:
    """Converts index to CodeNode.

    Corner cases:
        * Code of Namespace doesn't exist
        * Function in function or class method. Be careful there might be multiple layers for wrappers.
    """
    uri = index2uri[idx]
    # FIXME: Handle function in function.
    return uri2node.get(uri, None)


def generate_merge_fasten_graph(
    entry_point: Path,
    output_path: Path,
    uri2node: dict[URI, CodeNode],
    repo_root: Path,
) -> CodeNode:
    """Generates call graph and merges it into the definition tree."""
    if not entry_point.is_relative_to(repo_root):
        raise ValueError(f"{entry_point=} is not inside {repo_root=}.")

    fasten = extract_call_info(
        entry_point=entry_point, repo_root=repo_root, output_path=output_path
    )

    # Merge call graph
    for call in fasten.graph.internalCalls:
        caller_node = _idx_to_node(uri2node, call.caller, fasten.index2uri)
        callee_node = _idx_to_node(uri2node, call.callee, fasten.index2uri)
        if caller_node is None or callee_node is None:
            indexes = [call.caller, call.callee]
            nodes = [caller_node, callee_node]
            uris = [fasten.index2uri[idx] for idx in indexes]
            missing = [i for i, n in enumerate(nodes) if n is None]
            report = [(uris[i], indexes[i]) for i in missing]
            logger.warning(
                f"Cannot registr call in the codeinfo. " f"{report} is missing."
            )
            continue
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


def generate_codeinfo_from_repo(
    repo_root: Path, output_path: Path, entry_point: Path, uri_prefix: str = ""
) -> CodeInfo:
    """Generates the definition tree and merges call graph information.

    Args:
        uri_prefix: useful when testing on a subset of the codebase.
            E.g. "/codebase_analyzer.tests.data"
    """
    codeinfo = generate_def_tree(repo_root=repo_root, uri_prefix=uri_prefix)
    generate_merge_fasten_graph(
        uri2node=codeinfo.nodes,
        output_path=output_path,
        repo_root=repo_root,
        entry_point=entry_point,
    )
    generate_summary_embedding(codeinfo=codeinfo)
    # Can merge more other relations here.
    return codeinfo


# TODO: Organize the following tests into a test file.
# if __name__ == "__main__":
#     repo_root = Path(
#         "/Users/jun/Projects/ichigen-coder/codebase_analyzer/tests/data"
#     )
#     entry_point = Path(
#         "/Users/jun/Projects/ichigen-coder/codebase_analyzer/tests/data/short.py"
#     )
#     output_path = Path(
#         "/Users/jun/Projects/ichigen-coder/codebase_analyzer/tests/data/fasten.json"
#     )
#     uri_prefix = "/codebase_analyzer.tests.data"
#     codeinfo = generate_nodes_from_repo(
#         repo_root=repo_root,
#         output_path=output_path,
#         entry_point=entry_point,
#         uri_prefix=uri_prefix,
#     )
#     codeinfo.to_disk(output_path="./nodes.json")
#     loaded_codeinfo = CodeInfo.from_disk(input_path=Path("./nodes.json"))
#     assert codeinfo == loaded_codeinfo
#     pass
