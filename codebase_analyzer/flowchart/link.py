"""Links all nodes in a repo based on the function calls."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from loguru import logger

from codebase_analyzer.flowchart.element import flowchart_to_element_json
from codebase_analyzer.flowchart.graph import (
    FlowchartConfig,
    flowchart_node_to_dot_graph,
)
from codebase_analyzer.flowchart.node import (
    ELEMENT_JSON,
    FLAT_JSON,
    BaseFlowchartNode,
    BaseOneOutNode,
    CallNode,
    DecisionNode,
    EndNode,
    ExitNode,
    Flowchart,
    FunctionNode,
)
from codebase_analyzer.parser.uri import URI, Uri


def get_utility_functions(func_nodes: dict[Uri, FunctionNode]) -> set[URI]:
    counter = Counter()
    utility = set()

    for node in func_nodes.values():
        flat_dict = node.to_flat_dict()
        for info in flat_dict.values():
            if info["type"] == CallNode.__name__:
                counter[info["func_uri"]] += 1

    for call, count in counter.items():
        if count > 1:
            logger.info(f"{call} is called {count} times.")
            utility.add(call)
    return utility


def load_function_nodes(load_dir: Path) -> dict[URI, FunctionNode]:
    func_nodes = dict()
    for func_path in load_dir.glob(f"**/{FLAT_JSON}"):
        logger.info(f"Loading function chart from {func_path}.")
        func_node = BaseFlowchartNode.from_file(json_file=func_path)
        uri = Uri.from_node_uuid(func_node.uuid)
        func_nodes[uri] = func_node
    return func_nodes


def link_called_functions(
    func_nodes: dict[Uri, FunctionNode],
    utility: set[Uri],
    node: BaseFlowchartNode,
    done: set[Uri],
) -> Flowchart:
    """Links all the CallNodes with the FunctionNodes."""
    if node is None or node.uuid in done:
        return

    done.add(node.uuid)
    if isinstance(node, CallNode):
        if node.func_uri in utility:
            logger.info(f"Skip linking utility function {node.func_uri}.")
        elif node.func_uri not in func_nodes:
            logger.warning(f"Function {node.func_uri} is not in the func_nodes.")
        else:
            func_node = func_nodes[node.func_uri]
            node.subchart = func_node.get_process_chart(uuid=node.uuid)

    if node.subchart is not None:
        link_called_functions(
            func_nodes=func_nodes,
            utility=utility,
            node=node.subchart.start,
            done=done,
        )

    if isinstance(node, BaseOneOutNode):
        link_called_functions(
            func_nodes=func_nodes, utility=utility, node=node.next, done=done
        )
    elif isinstance(node, DecisionNode):
        link_called_functions(func_nodes, utility, node.true, done=done)
        link_called_functions(func_nodes, utility, node.false, done=done)
    elif isinstance(node, (ExitNode, EndNode)):
        pass
    else:
        raise ValueError(f"Unupported node type {node}.")


def link_charts_from_entrypoint(
    dump_dir: Path,
    entry_uri: URI,
) -> Flowchart:
    """Links all the CallNodes with the FunctionNodes."""
    done = set()
    func_nodes = load_function_nodes(dump_dir)
    utility = get_utility_functions(func_nodes)
    entry_node = func_nodes[entry_uri].start
    link_called_functions(
        func_nodes=func_nodes, utility=utility, node=entry_node, done=done
    )
    return entry_node


def link_all_chart_nodes(
    target_uri: str,
    dump_dir: Path,
    save_flat: bool = False,
    save_element: bool = False,
    save_dot: bool = False,
) -> Flowchart:
    full_chart = link_charts_from_entrypoint(
        dump_dir=dump_dir,
        entry_uri=Uri.from_fasten_uri(target_uri),
    )
    if save_flat:
        full_chart.to_file(dump_dir.parent / f"linked_{FLAT_JSON}")

    if save_element:
        flowchart_to_element_json(
            flowchart=full_chart,
            output_path=dump_dir.parent / f"linked_{ELEMENT_JSON}.json",
        )
    if save_dot:
        flowchart_node_to_dot_graph(
            full_chart,
            config=FlowchartConfig(expand_all=False, show_cluster=False),
            output_path=dump_dir.parent / "linked_chart",
            save_png=False,
            save_svg=True,
            suffix="_linked",
        )
    return full_chart
