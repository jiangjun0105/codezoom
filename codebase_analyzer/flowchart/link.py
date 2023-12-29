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
    ActionNode,
    BaseFlowchartNode,
    BaseOneOutNode,
    CallNode,
    ContextPair,
    DecisionNode,
    DefineNode,
    EndNode,
    ExitNode,
    Flowchart,
    FlowchartType,
    FunctionNode,
    LoopNode,
    StartNode,
)
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode
from codebase_analyzer.parser.uri import URI, Uri


def get_utility_functions(nodes: dict[str, CodeNode]) -> set[URI]:
    counter = Counter()
    utility = set()

    for node in nodes.values():
        for call in node.calls:
            counter[call] += 1

    for call, count in counter.items():
        if count > 1:
            logger.info(f"{call} is called {count} times.")
            utility.add(call)
    return utility


FLAT_JSON = "flat.json"


def load_function_nodes(load_dir: Path) -> dict[URI, Flowchart]:
    func_nodes = dict()
    for func_path in load_dir.glob(f"**/{FLAT_JSON}"):
        logger.info(f"Loading function chart from {func_path}.")
        chart = BaseFlowchartNode.from_file(json_file=func_path)
        uri = Uri.from_node_uuid(chart.uuid)
        func_nodes[uri] = chart
    return func_nodes


def link_called_functions(
    func_nodes: dict[URI, Flowchart],
    utility: set[URI],
    node: BaseFlowchartNode,
    done: set[URI],
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
    nodes: dict[str, CodeNode],
    entry_uri: URI,
) -> Flowchart:
    """Links all the CallNodes with the FunctionNodes."""
    done = set()
    func_nodes = load_function_nodes(dump_dir)
    utility = get_utility_functions(nodes)
    entry_node = func_nodes[entry_uri].start
    link_called_functions(
        func_nodes=func_nodes, utility=utility, node=entry_node, done=done
    )
    return entry_node


def link_nodes_and_save_jsons(
    nodes: dict[str, CodeNode],
    target_uri: str,
    dump_dir: Path,
    linked_flat_json: Path,
    linked_element_json: Path,
):
    link_charts_from_entrypoint(
        dump_dir=dump_dir,
        nodes=nodes,
        entry_uri=Uri.from_fasten_uri(target_uri),
    ).to_file(linked_flat_json)

    read = BaseFlowchartNode.from_file(json_file=linked_flat_json)
    flowchart_to_element_json(
        flowchart=read,
        output_path=linked_element_json,
    )
    flowchart_node_to_dot_graph(
        read,
        config=FlowchartConfig(expand_all=False, show_cluster=True),
        output_path=dump_dir,
        save_png=False,
        save_svg=True,
        suffix="_linked",
    )
