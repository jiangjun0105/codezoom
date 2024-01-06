# %%
"""Extacts the abstract logics from the groupping results."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import networkx as nx
import pygraphviz as pgv
from loguru import logger

from codebase_analyzer.flowchart.graph import (
    FlowchartConfig,
    flowchart_node_to_dot_graph,
)
from codebase_analyzer.flowchart.group import (
    NodeEmbedding,
    NodeGroup,
    calculate_edge_weights,
    detect_node_groups,
    get_node_embeddings,
    save_grouping_results,
)
from codebase_analyzer.flowchart.node import BaseFlowchartNode
from codebase_analyzer.flowchart.process.generate import ask_gpt

ABSTRACT_TEMPLATE = """You are good at analyzing program's high-level logic. Below are the summaries of the program's logic, please summarize the overall purpose of all given processes in one sentence:

{summaries}
"""


def load_node_groups(csv_path: Path) -> list[dict]:
    groups = dict()
    with open(csv_path, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            group = row["group"]
            if group not in groups:
                groups[group] = []
            groups[group].append(row)
    return groups


def remove_prefix(sentence: str) -> str:
    import re

    pattern = r"The overall purpose of .+? is to (.+)"

    # Extract the part after "The overall purpose of xxx is to"
    match = re.search(pattern, sentence)
    extracted_part = match.group(1) if match else sentence
    return extracted_part


def extract_node_texts(
    groups: dict[str, NodeGroup], abstract_csv: Path, abstract: bool = False
) -> list[list]:
    group2nodes = dict()
    for _, data in groups.items():
        group = data.group
        if group not in group2nodes:
            group2nodes[group] = []
        group2nodes[group].append(data)

    rows = []
    for group, nodes in group2nodes.items():
        if len(nodes) < 2:
            rows.append([group, nodes[0].text, None])
            continue

        texts = [node.text for node in nodes]
        if not abstract:
            text = "\n".join(texts)
            rows.append([group, text, None])
            continue

        summaries = "\n".join([f"* {text}" for text in texts])
        formatted = ABSTRACT_TEMPLATE.format(summaries=summaries)
        text = ask_gpt(
            prompt=formatted,
            model="gpt-4-1106-preview",
            call_api=True,
        )
        text = remove_prefix(text)
        rows.append(
            [
                group,
                text,
                summaries,
            ]
        )
        print(f"Input prompot:\n{formatted}")
        print(f"Abstract logic:\n{text}")

    with open(abstract_csv, "w") as f:
        writer = csv.writer(f)
        writer.writerow(["group", "text", "summaries"])
        for row in rows:
            writer.writerow(row)
    return {str(row[0]): row[1] for row in rows}


def abstract_agraph_and_flat_json(
    agraph: pgv.AGraph, group_csv: Path, abstract_csv: Path, flat_json: Path
) -> pgv.AGraph:
    id2group = NodeGroup.load_dict_from_csv(group_csv)
    nodes = dict()

    abs_graph = pgv.AGraph(directed=True)
    with open(abstract_csv, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            abs_graph.add_node(
                row["group"], label=row["text"], shape="box", style="filled"
            )
            nodes[row["group"]] = dict(
                uuid=str(row["group"]),
                label=row["text"],
            )

    for start, end in agraph.edges():
        start_group = id2group[start].group
        end_group = id2group[end].group
        if start_group != end_group:
            logger.info(
                f"Edge {start} -> {end} is between different groups: {start_group} -> {end_group}"
            )
            abs_graph.add_edge(start_group, end_group)

    flat_json.write_text(json.dumps(dict(nodes=nodes), indent=4))
    return abs_graph


def _group_path(output_dir: Path, index: int) -> Path:
    return output_dir / f"{index}_group.csv"


def _abstract_path(output_dir: Path, index: int) -> Path:
    return output_dir / f"{index}_abstract.csv"


def _flat_path(output_dir: Path, index: int) -> Path:
    return output_dir / f"{index}_flat.json"


def group_and_abstract_once(
    *,
    node_text: dict[str, str],
    output_dir: Path,
    index: int,
    agraph: pgv.AGraph,
    overwrite: bool = False,
) -> None:
    embed_csv = output_dir / f"{index}_embed.csv"
    abstract_csv = _abstract_path(output_dir, index)
    group_csv = _group_path(output_dir, index)

    # Generate embeddings for target attributes
    embeddings = get_node_embeddings(
        node_text=node_text, embed_csv=embed_csv, overwrite=overwrite
    )

    # Groupping
    edge_weights = calculate_edge_weights(agraph=agraph, embeddings=embeddings)
    node_groups = detect_node_groups(agraph=agraph, edge_weights=edge_weights)
    save_grouping_results(
        agraph=agraph,
        edge_weights=edge_weights,
        embeddings=embeddings,
        node_groups=node_groups,
        output_file=group_csv,
    )

    # Extract abstract logic
    node_text = extract_node_texts(
        groups=NodeGroup.load_dict_from_csv(group_csv),
        abstract_csv=abstract_csv,
    )
    return node_text


def group_and_abstract(
    flat_json: Path,
    output_dir: Path,
    times: int,
    attribute: str,
    overwrite: bool = False,
) -> None:
    agraph = flowchart_node_to_dot_graph(
        input=BaseFlowchartNode.from_file(flat_json),
        config=FlowchartConfig(expand_all=True, show_cluster=True),
        save_png=False,
        save_dot=False,
        save_svg=False,
    )
    with open(flat_json, "r") as f:
        flat_json = json.load(f)
        node_text = {
            uuid: node[attribute] for uuid, node in flat_json["nodes"].items()
        }
    for index in range(times):
        node_text = group_and_abstract_once(
            node_text=node_text,
            output_dir=output_dir,
            index=index,
            agraph=agraph,
            overwrite=overwrite,
        )
        flat_json = _flat_path(output_dir, index)
        agraph = abstract_agraph_and_flat_json(
            agraph=agraph,
            group_csv=_group_path(output_dir, index),
            abstract_csv=_abstract_path(output_dir, index),
            flat_json=flat_json,
        )


if __name__ == "__main__":
    flat_json = Path(__file__).parent / ".local/autogpt/linked/linked_flat.json"
    output_dir = Path(__file__).parent / ".local/autogpt/abstract/by_code"
    group_and_abstract(
        flat_json=flat_json,
        attribute="code",
        output_dir=output_dir,
        times=3,
        overwrite=False,
    )


# %%
# ask_gpt(
#     prompt="""
# You are good at analyzing program's high-level logic. Below are the summaries of the program's logic, please summarize the overall purpose of all given processes in one sentence:

# * Return the list of trimmed messages.
# * Trim the agent's history and add it to the prompt, making sure the total token count stays within the limit after reserving some tokens.

# NOTE: Omit "The overall purpose of all given processes is to" in your the start of your output.
# """,
#     model="gpt-4-1106-preview",
#     call_api=False,
# )
