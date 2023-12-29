"""Generate dot graph from a flowchart."""
from __future__ import annotations

from pathlib import Path

import pygraphviz as pgv
from loguru import logger
from pydantic import BaseModel, Field, validator

from codebase_analyzer.flowchart.node import (
    ActionNode,
    BaseFlowchartNode,
    Connection,
    DecisionNode,
    EndNode,
    ExitNode,
    Flowchart,
    FunctionNode,
    LoopNode,
    StartNode,
)
from codebase_analyzer.parser.uri import URI, Uri, node_uuid_to_uri


class FlowchartConfig(BaseModel):
    show_cluster: bool = False
    expand_all: bool = False
    fold_all: bool = False  # Has higher priority than expand_all
    expand_list: list[str] = Field(default_factory=list)

    @validator("expand_all")
    def expand_all_logging(cls, v: bool) -> bool:
        if v:
            logger.info("Expand all nodes regardless other settings.")
        return v


def _is_expand(node: BaseFlowchartNode, config: FlowchartConfig) -> bool:
    if config.fold_all:
        return False
    if node.subchart is None:
        # TODO: Mabye we can add further expand logic here
        return False
    if config.expand_all:
        return True
    if node.uuid in config.expand_list:
        node.expand = True
    return node.expand


def _add_in_edges(
    to_node_graph: pgv.AGraph, to_node: str, in_edges: list[Connection]
) -> None:
    if in_edges:
        assert isinstance(in_edges, list)
        for edge in in_edges:
            if edge is None:
                continue
            assert isinstance(edge, Connection)
            from_node = edge.node.uuid
            node_edge = (from_node, to_node)
            graph = edge.graph
            # NOTE: We use this way to avoid duplicate edges when there is a
            # loop. It's only loop [decision.false] -> [loop setup], so no the
            # edge.node and to_node are in the same graph.
            # We need to be careful if there are connection causing loops between
            # nodes in different graphs.
            assert not to_node_graph.has_edge(node_edge)
            if not graph.has_edge(node_edge):
                graph.add_edge(node_edge, label=edge.label)
            elif graph.get_edge(*node_edge).attr["label"] != edge.label:
                logger.warning(
                    f"Edge {node_edge} already exists with label "
                    f"{graph.get_edge(*node_edge).attr['label']}. "
                    f"Will overwrite with label {edge.label}."
                )
                graph.add_edge(node_edge, label=edge.label)
            else:
                continue
            logger.debug(
                f"Adding edge\n\t{from_node=}\n\t{to_node=}\n\t{edge.label=}\n\t{graph.name=}"
            )


def node_to_graph(
    node: BaseFlowchartNode,
    graph: pgv.AGraph,
    config: FlowchartConfig,
    in_edges: list[Connection] | None = None,
) -> None:
    assert graph is not None

    if node is None:
        return in_edges

    if graph.has_node(node.uuid):
        # LoopDecision.false branch points to an existing LoopSetup node.
        _add_in_edges(graph, node.uuid, in_edges)
        return []

    if _is_expand(node, config):
        # For now all nodes with subcharts are ActionNodes
        # TODO: We need to support DecisionNode to have subcharts and be
        # expanded because it can have function calls.
        if not isinstance(node, (ActionNode, FunctionNode)):
            logger.warning(
                f"Node {node.name=} {type(node)} is not an ActionNode but has a subchart."
            )
        out_edges = flowchart_to_graph(
            node.subchart, graph, in_edges=in_edges, config=config
        )
        if isinstance(node, ActionNode) and node.next:
            out_edges = node_to_graph(
                node.next, graph, in_edges=out_edges, config=config
            )
        return out_edges

    graph.add_node(node.uuid, **node.node_attrs)
    logger.debug(f"Adding node\n\t{node.uuid=}\n\t{node.label=}\n\t{graph.name=}.")
    _add_in_edges(graph, node.uuid, in_edges)

    if isinstance(node, DecisionNode):
        true_out = node_to_graph(
            node.true, graph, in_edges=node.true_out_edges(graph), config=config
        )
        false_out = node_to_graph(
            node.false, graph, in_edges=node.false_out_edges(graph), config=config
        )
        out_edges = true_out + false_out
    elif isinstance(node, (ActionNode, StartNode)):
        out_edges = node_to_graph(
            node.next, graph, in_edges=node.out_edges(graph), config=config
        )
    elif isinstance(node, LoopNode):
        out_edges = node_to_graph(
            node.next, graph, in_edges=node.out_edges(graph), config=config
        )
    elif isinstance(node, (ExitNode, EndNode, FunctionNode)):
        logger.info(f"Encounter an ExitNode {node.name} at this branch.")
        out_edges = []
    else:
        raise ValueError(f"Cannot visualize {type(node)}")

    return out_edges


def flowchart_to_graph(
    flowchart: Flowchart,
    graph: pgv.AGraph,
    config: FlowchartConfig,
    in_edges: list[Connection] | None = None,
) -> pgv.AGraph:
    subgraph_name = (
        f"cluster_{flowchart.uuid}" if config.show_cluster else flowchart.uuid
    )
    with graph.subgraph(
        name=subgraph_name, label=flowchart.name, labeljust="l"
    ) as subgraph:
        out_edges = node_to_graph(
            flowchart.start, graph=subgraph, config=config, in_edges=in_edges
        )
    for e in out_edges:
        e.graph = graph
    return out_edges


def flowchart_node_to_dot_graph(
    input: Flowchart | BaseFlowchartNode,
    config: FlowchartConfig | None = None,
    save_png: bool = True,
    save_dot: bool = True,
    save_svg: bool = True,
    output_path: Path | None = None,
    suffix: str = "",
) -> pgv.AGraph:
    if config is None:
        config = FlowchartConfig(
            show_cluster=False, expand_all=False, fold_all=False, expand_list=[]
        )
    graph = pgv.AGraph(name=input.name, strict=False, directed=True, rankdir="TB")
    if isinstance(input, Flowchart):
        flowchart_to_graph(input, graph=graph, config=config)
    elif isinstance(input, BaseFlowchartNode):
        node_to_graph(input, graph=graph, config=config)
    else:
        raise ValueError(f"Cannot visualize {type(input)}")

    if output_path is None:
        output_path = Path(__file__).parent / "dot_graphs"
        output_path.mkdir(parents=True, exist_ok=True)

    input_uri = node_uuid_to_uri(input.uuid)
    uri = Uri.from_fasten_uri(input_uri)
    file_name = output_path / uri.dump_dir / f"chart{suffix}"
    file_name.parent.mkdir(parents=True, exist_ok=True)
    if save_png:
        graph.draw(file_name.with_suffix(".png"), prog="dot")
        logger.info(f"Saved {file_name.with_suffix('.png')}")
    if save_svg:
        graph.draw(file_name.with_suffix(".svg"), prog="dot")
        logger.info(f"Saved {file_name.with_suffix('.svg')}")
    if save_dot:
        graph.write(file_name.with_suffix(".dot"))
        logger.info(f"Saved {file_name.with_suffix('.dot')}")
    return graph
