"""Group nodes together based on their semantic meaning."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable, ClassVar

import matplotlib
import matplotlib.pyplot as plt
import networkx as nx
import pygraphviz as pgv
from customized_louvain import best_partition
from loguru import logger
from pydantic import BaseModel, validator
from sklearn.metrics.pairwise import cosine_distances

from codebase_analyzer.flowchart.graph import (
    FlowchartConfig,
    flowchart_node_to_dot_graph,
)
from codebase_analyzer.flowchart.node import BaseFlowchartNode
from codebase_analyzer.tools.embedding import OPENAI_EMBEDDING_DIM, get_embedding


class BaseCsvRow(BaseModel):
    """Base class for CSV rows."""

    uuid: str

    @classmethod
    @property
    def csv_columns(cls) -> list[str]:
        return list(cls.__fields__.keys())

    @classmethod
    def save_dict_to_csv(cls, filename: Path, data: dict[str, BaseCsvRow]) -> None:
        """Save a dictionary of BaseCsvRow to a CSV file."""
        filename.parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cls.csv_columns)
            writer.writeheader()
            for s in data.values():
                writer.writerow(s.dict())
        logger.info(f"Saved {filename}")

    @classmethod
    def load_dict_from_csv(cls, filename: Path) -> dict[str, BaseCsvRow]:
        loaded = dict()
        if not filename.exists():
            logger.warning(f"Input file {filename} does not exist.")
            return loaded

        with open(filename, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                data = cls(**row)
                loaded[data.uuid] = data
        logger.info(f"Loaded {len(loaded)} embeddings.")
        return loaded


class NodeEmbedding(BaseCsvRow):
    text: str
    embedding: list[float]

    @validator("embedding", pre=True)
    def convert_embedding(cls, v: Any) -> list[float]:
        if isinstance(v, str):
            return eval(v)
        return v


class NodeGroup(BaseCsvRow):
    text: str
    group: int


def get_node_embeddings(
    embed_csv: Path,
    node_text: dict[str, str],
    overwrite: bool = False,
) -> None:
    """Either load existing embeddings or generate new embeddings for each node."""

    embeddings = NodeEmbedding.load_dict_from_csv(filename=embed_csv)
    for uuid, text in node_text.items():
        if uuid in embeddings and not overwrite:
            logger.debug(f"Use existing embedding for {uuid}.")
            embedding = embeddings[uuid].embedding
        elif not text:
            logger.debug(f"Empty label for {uuid}. Use zero embedding.")
            embedding = [0.0] * OPENAI_EMBEDDING_DIM
        else:
            embedding = get_embedding(text=text)
            logger.debug(f"Generate embedding for {uuid}.")
        embeddings[uuid] = NodeEmbedding(
            uuid=uuid, text=text or "EMPTY", embedding=embedding
        )
    NodeEmbedding.save_dict_to_csv(filename=embed_csv, data=embeddings)
    return embeddings


def generate_color_mapping(values: set[int], colormap="flag"):
    """
    Generate a dictionary mapping each integer between min_val and max_val
    to a hexadecimal color.

    Args:
    nx_graph (nx.Graph): The input graph.
    colormap (str): The name of the Matplotlib colormap to use.

    Returns:
    dict: A dictionary where keys are integers and values are hexadecimal colors.
    """
    min_val = min(values)
    max_val = max(values)
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


def calculate_edge_weights(
    agraph: pgv.AGraph,
    embeddings: dict[str, NodeEmbedding],
    max_similarity: float = 25,
) -> pgv.AGraph:
    weights = dict()
    for edge in agraph.edges():
        start, end = edge
        start_embed = embeddings[start].embedding
        end_embed = embeddings[end].embedding
        distance = cosine_distances([start_embed], [end_embed])[0][0]
        similarity = min(
            max_similarity, 1 / distance if distance != 0 else max_similarity
        )
        weights[edge] = similarity
    return weights


def detect_node_groups(
    agraph: pgv.AGraph, edge_weights: dict[tuple(str, str), float]
) -> dict[str, int]:
    """
    Detect groups in the graph G using the Louvain method.

    Args:
    - G (nx.Graph): The input graph.

    Returns:
    - dict: A dictionary where keys are node IDs and values are their corresponding group IDs.
    """
    nx_graph = nx.nx_agraph.from_agraph(agraph).to_undirected()
    nx.set_edge_attributes(nx_graph, edge_weights, "weight")
    groups = best_partition(nx_graph, weight="weight")
    return groups


def save_grouping_results(
    agraph: pgv.AGraph,
    node_groups: dict[str, int],
    edge_weights: dict[tuple(str, str), float],
    embeddings: dict[str, NodeEmbedding],
    output_file: Path,
) -> None:
    color_map = generate_color_mapping(node_groups.values())
    for node in agraph.nodes():
        text = embeddings[node.name].text
        group = node_groups[node.name]
        node.attr["label"] = f"uuid: {node.name}\ntext: {text}\ngroup: {group}"
        node.attr["fillcolor"] = color_map[group]
        node.attr["style"] = "filled"
        node.attr["fontcolor"] = get_text_color(color_map[group])

    for edge in agraph.edges():
        start, end = edge
        # The edge is directed, so we need to check both directions
        if (start, end) in edge_weights:
            weight = edge_weights[(start, end)]
        elif (end, start) in edge_weights:
            weight = edge_weights[(end, start)]
        else:
            raise ValueError(f"Edge {start} -> {end} does not exist in nxgraph.")
        edge.attr["label"] = f"{weight:.2f}"

    if output_file:
        agraph.draw(str(output_file.with_suffix(".pdf")), prog="dot")
        logger.info(f"Saved {output_file}")

        group_csv = output_file.with_suffix(".csv")
        group_data = {
            uuid: NodeGroup(uuid=uuid, text=embeddings[uuid].text, group=group)
            for uuid, group in node_groups.items()
        }
        NodeGroup.save_dict_to_csv(filename=group_csv, data=group_data)

    return agraph


if __name__ == "__main__":
    flat_json = Path(__file__).parent / ".local/autogpt/linked/linked_flat.json"
    embed_csv = (
        Path(__file__).parent / ".local/autogpt/abstract/by_labels/0_embed.csv"
    )
    output_file = (
        Path(__file__).parent / ".local/autogpt/abstract/by_labels/0_group.pdf"
    )
    with open(flat_json, "r") as f:
        flat_dict = json.load(f)
    embeddings = get_node_embeddings(
        node_text={uuid: node["label"] for uuid, node in flat_dict["nodes"].items()},
        embed_csv=embed_csv,
    )
    loaded = NodeEmbedding.load_dict_from_csv(filename=embed_csv)
    assert embeddings == loaded
    agraph = flowchart_node_to_dot_graph(
        input=BaseFlowchartNode.from_file(flat_json),
        config=FlowchartConfig(expand_all=True, show_cluster=True),
        save_png=False,
        save_dot=False,
        save_svg=False,
    )
    edge_weights = calculate_edge_weights(agraph=agraph, embeddings=embeddings)
    node_groups = detect_node_groups(agraph=agraph, edge_weights=edge_weights)
    save_grouping_results(
        agraph=agraph,
        edge_weights=edge_weights,
        node_groups=node_groups,
        embeddings=embeddings,
        output_file=output_file,
    )
