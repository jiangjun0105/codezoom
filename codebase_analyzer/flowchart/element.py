"""Converts a flowchart to a JSON file that can be used by cytoscape.js."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pygraphviz as pgv
from loguru import logger

from codebase_analyzer.flowchart.graph import (
    FlowchartConfig,
    flowchart_node_to_dot_graph,
)
from codebase_analyzer.flowchart.node import NODES_KEY, BaseFlowchartNode, Flowchart


# %%
def pgv_edge_element(edge) -> dict:
    return dict(
        group="edges",
        data=dict(
            id=str(uuid4()),
            source=edge[0],
            target=edge[1],
            label=edge.attr["label"],
        ),
    )


def _dict_node_element(node: dict) -> dict:
    return dict(
        group="nodes",
        data=dict(
            id=node["uuid"],
            label=node["label"],
            parent=node["parent_uuid"],
        ),
        classes=node["type"],
    )


def pgv_node_element(node: pgv.Node) -> dict:
    element = dict(
        group="nodes",
        data=dict(
            id=node.name,
            label=node.attr["label"],
            parent=node.attr["parent_uuid"],
        ),
        classes=node.attr["type"],
    )
    if node.attr["type"] == "CallNode":
        element["data"]["func_uri"] = node.attr["func_uri"]
    return element


def flat_node_element(node: dict) -> dict:
    element = dict(
        group="nodes",
        data=dict(
            id=node["uuid"],
            label=node["label"],
            parent=node["parent_uuid"],
        ),
        classes=node["type"],
    )
    if node["type"] == "CallNode":
        element["data"]["func_uri"] = node["func_uri"]
    return element


def flowchart_to_element_json(
    flowchart: Flowchart | BaseFlowchartNode, output_path: Path | None = None
) -> dict:
    elements = []
    agraph = flowchart_node_to_dot_graph(
        flowchart,
        save_png=False,
        save_dot=False,
        save_svg=False,
        config=FlowchartConfig(expand_all=True),
    )
    flat_dict = flowchart.to_flat_dict()
    nodes = flat_dict[NODES_KEY] if isinstance(flowchart, Flowchart) else flat_dict
    for node in nodes.values():
        elements.append(flat_node_element(node))
        logger.info(f"add parent for node {node['uuid']}")

    for edge in agraph.edges():
        elements.append(pgv_edge_element(edge))

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(dict(flowchart=elements), indent=4))


if __name__ == "__main__":
    output_path = (
        Path(__file__).parent
        / "convert_dump/autogpt/app/main/print_assistant_thoughts/flat.json"
    )
    autogpt_chart = Flowchart.from_file(output_path)
    flowchart_to_element_json(
        autogpt_chart, Path("/Users/jun/Projects/display-flowchart/db.json")
    )
