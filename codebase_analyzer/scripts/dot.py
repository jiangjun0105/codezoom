import json
import subprocess
from pathlib import Path

import click
import pygraphviz as pgv
from loguru import logger


def extract_subtree(graph: pgv.AGraph, root_node: str) -> pgv.AGraph:
    """
    Extracts the subtree rooted at 'root_node' from the given 'graph'.
    Returns a new AGraph object representing the subtree.
    """
    subtree = pgv.AGraph(
        directed=True, strict=False, rankdir="LR"
    )  # Set strict=False to allow multiple edges between nodes

    # Use BFS to traverse and collect nodes and edges
    queue = [root_node]
    visited = set()
    added_edges = set()  # Keep track of added edges to avoid duplicates

    while queue:
        node = queue.pop(0)
        if node not in visited:
            logger.debug(f"Visiting node {node}")
            visited.add(node)

            # Fetching all edges between the current node and neighbor
            for edge in graph.edges_iter([node]):
                if edge[0] != node:
                    # It fetches both inbound and outbound edges, so we need to filter out the inbound edges
                    continue
                neighbor = edge[1]
                logger.debug(f"Fetching edges between {node} and {neighbor}")
                edge_key = (
                    edge[0],
                    edge[1],
                    edge.attr.get("color", None),
                )  # Including color attribute to distinguish edges

                if edge_key not in added_edges:
                    attributes = edge.attr
                    logger.debug(f"Adding edge {edge_key}")
                    subtree.add_edge(edge[0], edge[1], **attributes)
                    added_edges.add(edge_key)

                # logger.debug(f"Visited: {visited}")
                # logger.debug(f"Queue: {queue}")
                if neighbor not in visited:
                    logger.debug(f"Adding node {neighbor}")
                    queue.append(neighbor)

    return subtree


def generate_agraph(
    graph_dict: dict[str, dict],
    show_node: list[str] = None,
    show_edge: list[str] = None,
    show_uncalled: bool = False,
) -> pgv.AGraph:
    if not show_node:
        show_node = "all"
    if not show_edge:
        show_edge = "all"

    G = pgv.AGraph(directed=True, rankdir="LR")

    for node, value in graph_dict.items():
        if not (show_node == "all" or value["type"] in show_node):
            continue

        # Ensure the node is added even if it has no outgoing edges
        if show_uncalled:
            G.add_node(node)

        for edge_type, color, label in zip(
            ["children", "calls", "superclasses"],
            ["red", "blue", "green"],
            ["child", "call", "superclass"],
        ):
            if not (show_edge == "all" or edge_type in show_edge):
                continue

            for target in value[edge_type]:
                if not (
                    show_node == "all" or graph_dict[target]["type"] in show_node
                ):
                    continue
                # logger.debug(f"Adding edge {node} -> {target}")
                G.add_edge(node, target, color=color, label=label)

    return G


@click.command()
@click.option("--input-path", "-i", type=Path, required=True)
@click.option("--output-path", "-o", type=Path, required=True)
@click.option("--root-node", "-r", type=str, default=None)
@click.option("--show-uncalled", type=bool, default=False)
@click.option("--show-node", "-n", type=str, multiple=True, default=None)
@click.option("--show-edge", "-e", type=str, multiple=True, default=None)
def main(
    input_path: Path,
    output_path: Path,
    show_node: list[str],
    show_edge: list[str],
    root_node: str | None = None,
    show_uncalled: bool = False,
) -> None:
    logger.info(f"{show_edge=}, {show_node=}", type(show_edge), type(show_node))
    input_path = Path(input_path).expanduser()
    if not input_path.exists():
        raise ValueError(f"{input_path=} does not exist.")

    logger.info(f"Reading from {input_path}")
    with open(input_path, "r") as f:
        info = json.load(f)

    logger.info("Generating graph")
    agraph = generate_agraph(
        info["nodes"],
        show_edge=show_edge,
        show_node=show_node,
        show_uncalled=show_uncalled,
    )

    if root_node and root_node not in info["nodes"]:
        raise ValueError(f"{root_node=} is not a valid node.")

    if root_node and root_node != info["metadata"]["root"]:
        logger.info(f"Extracting subtree rooted at {root_node}")
        agraph = extract_subtree(agraph, root_node)

    agraph.layout(prog="dot")

    dot_file = output_path.with_suffix(".dot")
    svg_file = output_path.with_suffix(".svg")

    logger.info(f"Writing dot to {dot_file}")
    agraph.write(dot_file)
    logger.info(f"Writing svg to {svg_file}")
    agraph.draw(svg_file, format="svg")


if __name__ == "__main__":
    main()
