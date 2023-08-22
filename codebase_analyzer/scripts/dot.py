import json
import subprocess
from pathlib import Path

import click
from loguru import logger


def generate_dot(
    graph_dict: dict[str, dict],
    show_node: list[str] = None,
    show_edge: list[str] = None,
) -> str:
    if not show_node:
        show_node = "all"
    if not show_edge:
        show_edge = "all"

    dot_lines = ["digraph G {", "    rankdir=LR;"]
    for node, value in graph_dict.items():
        if not (show_node == "all" or value["type"] in show_node):
            logger.debug(
                f"Skipping {node} because {value['type']} is not in {show_node}"
            )
            continue

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
                    logger.debug(
                        f"Skipping {target} because {graph_dict[target]['type']} is not in {show_node}"
                    )
                    continue
                dot_lines.append(
                    f'    "{node}" -> "{target}" [color={color}, label="{label}"];'
                )

    dot_lines.append("}")
    return "\n".join(dot_lines)


@click.command()
@click.option("--input-path", "-i", type=Path, required=True)
@click.option("--output-path", "-o", type=Path, required=True)
@click.option("--show-node", "-n", type=str, multiple=True, default=None)
@click.option("--show-edge", "-e", type=str, multiple=True, default=None)
def main(
    input_path: Path, output_path: Path, show_node: list[str], show_edge: list[str]
) -> None:
    logger.info(f"{show_edge=}, {show_node=}", type(show_edge), type(show_node))
    input_path = Path(input_path).expanduser()
    if not input_path.exists():
        raise ValueError(f"{input_path=} does not exist.")

    logger.info(f"Reading from {input_path}")
    with open(input_path, "r") as f:
        info = json.load(f)

    dot = generate_dot(info["nodes"], show_edge=show_edge, show_node=show_node)
    logger.info(dot)

    dot_file = output_path.with_suffix(".dot")
    svg_file = output_path.with_suffix(".svg")

    logger.info(f"Writing dot to {dot_file}")
    with open(dot_file, "w") as f:
        f.writelines(dot)

    logger.info(f"Writing svg to {svg_file}")
    subprocess.run(["dot", "-Tsvg", dot_file, "-o", svg_file])


if __name__ == "__main__":
    main()
