"""Group nodes together based on their semantic meaning."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable, ClassVar
from uuid import uuid4

import networkx as nx
import numpy as np
import pygraphviz as pgv
from customized_louvain import best_partition
from loguru import logger
from pydantic import BaseModel, Field, root_validator
from sklearn.metrics.pairwise import cosine_distances

from codebase_analyzer.flowchart.element import flowchart_to_element_json
from codebase_analyzer.flowchart.graph import (
    FlowchartConfig,
    flowchart_node_to_dot_graph,
)
from codebase_analyzer.flowchart.label import NodeLabelerMixin
from codebase_analyzer.flowchart.link import link_all_chart_nodes
from codebase_analyzer.flowchart.node import (
    ELEMENT_JSON,
    FLAT_JSON,
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
from codebase_analyzer.tools.context import get_str_length
from codebase_analyzer.tools.embedding import OPENAI_EMBEDDING_DIM, get_embedding


class NodeSemantics(BaseModel):
    uuid: str
    label: str
    code: str | None = None
    embedding: list[float]
    csv_columns: ClassVar[list[str]] = ["uuid", "label", "code", "embedding"]

    @classmethod
    def from_csv(cls, row: list[str]) -> NodeSemantics:
        return cls(uuid=row[0], label=row[1], code=row[2], embedding=eval(row[3]))

    def to_csv(self) -> list[str]:
        return [self.uuid, self.label, self.code, self.embedding]


def generate_label_embeddings(
    flat_json: Path, embed_csv: Path, overwrite: bool = False
) -> None:
    with open(flat_json, "r") as f:
        flat_dict = json.load(f)

    semantics = load_embeddings(embed_csv=embed_csv)
    for uuid, node in flat_dict["nodes"].items():
        label = node["label"]
        code = node["code"]
        if uuid in semantics and not overwrite:
            logger.debug(f"Use existing embedding for {uuid}.")
            embedding = semantics[uuid].embedding
        elif not label:
            logger.debug(f"Empty label for {uuid}. Use zero embedding.")
            embedding = [0.0] * OPENAI_EMBEDDING_DIM
        else:
            embedding = get_embedding(label)
        logger.debug(f"Generating embedding for {uuid}.")
        semantics[uuid] = NodeSemantics(
            uuid=uuid, code=code, label=label, embedding=embedding
        )

    with open(embed_csv, "w") as f:
        writer = csv.writer(f)
        writer.writerow(NodeSemantics.csv_columns)
        for s in semantics.values():
            writer.writerow(s.to_csv())


def load_embeddings(embed_csv: Path) -> dict[str, NodeSemantics]:
    loaded = dict()
    with open(embed_csv, "r") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            data = NodeSemantics.from_csv(row)
            loaded[data.uuid] = data
    logger.info(f"Loaded {len(loaded)} embeddings.")
    return loaded


import matplotlib
import matplotlib.pyplot as plt


def generate_color_mapping(nx_graph: nx.MultiDiGraph, colormap="flag"):
    """
    Generate a dictionary mapping each integer between min_val and max_val
    to a hexadecimal color.

    Args:
    nx_graph (nx.Graph): The input graph.
    colormap (str): The name of the Matplotlib colormap to use.

    Returns:
    dict: A dictionary where keys are integers and values are hexadecimal colors.
    """
    communities = set(nx.get_node_attributes(nx_graph, "community").values())
    min_val = min(communities)
    max_val = max(communities)
    cmap = plt.get_cmap(colormap)

    # Create the color mapping dictionary
    color_mapping = dict()
    for val in range(min_val, max_val + 1):
        start_point = 0  # Starting point in the colormap (0 to 1)
        end_point = 1  # Ending point in the colormap (0 to 1)

        normalized_val = start_point + ((val - min_val) / (max_val - min_val)) * (
            end_point - start_point
        )

        # Get the color from the colormap and convert to hex
        rgb_color = cmap(normalized_val)[:3]  # Get RGB values
        hex_color = matplotlib.colors.rgb2hex(rgb_color)  # Convert RGB to hex

        # Add to the dictionary
        color_mapping[val] = hex_color

    return color_mapping


def get_text_color(hex_color: str):
    # Convert hex color to RGB
    r, g, b = matplotlib.colors.hex2color(hex_color)
    # Calculate luminance
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    # If background color is dark, return white, otherwise black
    return "#FFFFFF" if luminance < 0.5 else "#000000"


def create_nxgraph_with_weights(
    agraph: pgv.AGraph,
    semantics: dict[str, NodeSemantics],
    max_similarity: float = 25,
) -> pgv.AGraph:
    nx_graph = nx.nx_agraph.from_agraph(agraph).to_undirected()
    weights = dict()
    for start, end in nx_graph.edges():
        start_embed = semantics[start].embedding
        end_embed = semantics[end].embedding
        distance = cosine_distances([start_embed], [end_embed])[0][0]
        similarity = min(
            max_similarity, 1 / distance if distance != 0 else max_similarity
        )
        weights[(start, end)] = similarity
    nx.set_edge_attributes(nx_graph, weights, "weight")
    return nx_graph


def save_partition_results(
    agraph: pgv.AGraph,
    semantics: dict[str, NodeSemantics],
    nx_graph: nx.MultiGraph,
    output_file: Path,
) -> None:
    color_map = generate_color_mapping(nx_graph)
    for node in agraph.nodes():
        code = semantics[node.name].code
        label = semantics[node.name].label
        community = nx_graph.nodes[node.name]["community"]
        node.attr[
            "label"
        ] = f"uuid: {node.name}\nlabel: {label}\ncode: {code}\ncommunity: {community}"
        node.attr["fillcolor"] = color_map[community]
        node.attr["fontcolor"] = get_text_color(color_map[community])

    weights = nx.get_edge_attributes(nx_graph, "weight")
    for edge in agraph.edges():
        s, e = edge
        # The edge is directed, so we need to check both directions
        if (s, e) in weights:
            weight = weights[(s, e)]
        elif (e, s) in weights:
            weight = weights[(e, s)]
        else:
            raise ValueError(f"Edge {s} -> {e} does not exist in nxgraph.")
        edge.attr["label"] = f"{weight:.2f}"

    if output_file:
        agraph.draw(str(output_file.with_suffix(".pdf")), prog="dot")
        logger.info(f"Saved {output_file}")

        labels = nx.get_node_attributes(nx_graph, "label")
        communities = nx.get_node_attributes(nx_graph, "community")
        with open(output_file.with_suffix(".csv"), "w") as f:
            writer = csv.writer(f)
            writer.writerow(["node_id", "label", "code", "community"])
            for node in agraph.nodes():
                writer.writerow(
                    [
                        node.name,
                        labels[node.name],
                        semantics[node.name].code,
                        communities[node.name],
                    ]
                )
        logger.info(f"Saved {output_file.with_suffix('.csv')}")

    return agraph


def detect_communities(nx_graph: nx.MultiGraph) -> nx.MultiGraph:
    """
    Detect communities in the graph G using the Louvain method.

    Args:
    - G (nx.Graph): The input graph.

    Returns:
    - dict: A dictionary where keys are node IDs and values are their corresponding community IDs.
    """
    partition = best_partition(nx_graph, weight="weight")
    nx.set_node_attributes(nx_graph, partition, "community")
    return nx_graph


if __name__ == "__main__":
    flat_json = Path(__file__).parent / ".local/convert_dump/linked_flat.json"
    embed_csv = Path(__file__).parent / ".local/convert_dump/embedding.csv"
    svg_file = Path(__file__).parent / ".local/convert_dump/linked_group.pdf"
    generate_label_embeddings(
        flat_json=flat_json,
        embed_csv=embed_csv,
    )
    loaded = load_embeddings(embed_csv=embed_csv)
    agraph = flowchart_node_to_dot_graph(
        input=BaseFlowchartNode.from_file(flat_json),
        config=FlowchartConfig(expand_all=True, show_cluster=True),
        save_png=True,
        save_dot=False,
        save_svg=False,
    )
    nx_graph = create_nxgraph_with_weights(agraph=agraph, semantics=loaded)
    nx_graph = detect_communities(nx_graph=nx_graph)
    save_partition_results(
        agraph=agraph, nx_graph=nx_graph, semantics=loaded, output_file=svg_file
    )
