# %%
from __future__ import annotations

import copy
import json
from abc import ABC
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, ClassVar, NewType
from uuid import uuid4

import pygraphviz as pgv
from loguru import logger
from pydantic import BaseModel, Field, root_validator, validator

from codebase_analyzer.flowchart.datamodel import (
    ActionPattern,
    ElifPattern,
    ElsePattern,
    ExitPattern,
    IfPattern,
    LoopPattern,
    Process,
)
from codebase_analyzer.parser.uri import URI, uri_stem

REPO_ROOT = Path(__file__).parent.parent.parent
CACHE_ROOT = REPO_ROOT / "shared_cache"
LOCAL_ROOT = REPO_ROOT / ".local"

_CHART_KEY = "chart"


class FlowchartType(Enum):
    IF: str = "IF"
    LOOP: str = "LOOP"
    LINEAR: str = "LINEAR"


NodeURI = NewType("NodeURI", URI)

# HACK: a temporary fix of circular type annotation BaseFlowchartNode
# We probably will fix this by using NodeURI instead of Node Class.
BaseFlowchartNodeType = NewType("BaseFlowchartNodeType", BaseModel)


class Connection(BaseModel):
    node: BaseFlowchartNodeType
    label: str = Field(default="")
    # NOTE: Need `graph` to add edge to the outer level graph to show clusters
    # correctly. Otherwise the from_node in the edges will be added to the
    # subgraph.
    graph: pgv.AGraph = Field(default=None)

    class Config:
        arbitrary_types_allowed = True


def serialize_flowchart_node(node: BaseFlowchartNodeType) -> dict:
    if isinstance(node, BaseModel):
        return node.dict()
    else:
        # Replace with custom logic as necessary
        raise TypeError(f"Cannot serialize node type: {type(node)}")


class Flowchart(BaseModel):
    name: str
    uuid: str
    type: FlowchartType
    start: BaseFlowchartNodeType

    @root_validator(pre=True)
    def set_chart_uuid(cls, values: dict) -> str:
        # uuid initialized from node.uuid
        if values.get("uuid", None):
            return values
        name = values.get("name", "no_name")
        values["uuid"] = f"{name}_{str(uuid4())}"
        return values

    @classmethod
    def from_nodes(
        cls,
        parent: BaseFlowchartNodeType,
        start: BaseFlowchartNodeType,
        type: FlowchartType,
    ) -> Flowchart:
        # NOTE: Must have the same uuid as the parent node
        return cls(
            name=f"chart_{parent.name}", uuid=parent.uuid, type=type, start=start
        )

    def to_flat_dict(self, nodes: dict[str, dict] | None = None) -> dict:
        if nodes is None:
            nodes = dict()
        logger.debug(f"Flatten chart {self.uuid}")
        chart = self.dict(exclude={"start"})
        chart["start"] = self.start.uuid
        chart["type"] = self.type.value  # Otherwise not JSON serializable
        self.start.to_flat_dict(nodes)
        return dict(chart=chart, nodes=nodes)

    @classmethod
    def from_flat_dict_by_chart(
        cls,
        nodes: dict[str, dict],
        chart: dict[str, str],
        done: dict[str, BaseFlowchartNode],
    ) -> Flowchart:
        if not chart:
            return None
        logger.debug(f"Reconstruct chart {chart['uuid']}")
        start = BaseFlowchartNode.from_flat_dict_by_id(
            nodes=nodes,
            node_uuid=chart.pop("start", None),
            done=done,
        )
        return cls(start=start, **chart)

    @classmethod
    def from_flat_dict(cls, data: dict) -> Flowchart:
        data = copy.deepcopy(data)
        nodes = data.get("nodes", dict())
        chart = data.get("chart", dict())
        done: dict[str, BaseFlowchartNode] = dict()
        return cls.from_flat_dict_by_chart(nodes=nodes, chart=chart, done=done)

    @classmethod
    def from_file(cls, json_file: Path, check: bool = True) -> Flowchart:
        data = json.loads(json_file.read_text())
        chart = cls.from_flat_dict(data)
        if check and any(e for e in chart.check().values()):
            raise ValueError(f"Invalid flowchart {chart.name}")
        return chart

    def to_file(self, json_file: Path, indent: int = 4, check: bool = True) -> None:
        if check and any(e for e in self.check().values()):
            raise ValueError(f"Invalid flowchart {self.name}")
        json_file.write_text(json.dumps(self.to_flat_dict(), indent=indent))

    def check(
        self,
        expected_parent: str | None = None,
        checked: dict[str, list[str]] | None = None,
    ) -> dict[str, list[str]]:
        # For now we only require the chart.uuid == parent_node.uuid
        # We might also want to check if chart.name == cluster_{parent_node.name}
        if checked is None:
            checked = defaultdict(list)
        logger.debug(f"Validating flowchart {self.name}")
        if expected_parent and self.uuid != expected_parent:
            error = f"[Chart] {self.uuid=} != {expected_parent=}"
            checked[self.uuid].append(error)
            logger.error(error)
        logger.debug(f"\tChart uuid OK for chart {self.name}")
        self.start.check(expected_parent=self.uuid, checked=checked)
        return checked


class BaseFlowchartNode(BaseModel, ABC):
    color: ClassVar[str]
    shape: ClassVar[str]
    name: str
    label: str
    uuid: str
    # This is uuid for both parent chart and the chart's parent node
    parent_uuid: str | None = None
    # NOTE: Any node can have a subchart after merging.
    # but after reorganizing, only IfNode and LoopNode will have subcharts
    subchart: Flowchart = Field(default=None)
    expand: bool = False

    @property
    def node_attrs(self) -> dict[str, str]:
        # Use this method to customize the visualization of the node
        return dict(
            label=self.label,
            shape=self.shape,
            style="filled",
            fontname="Arial",
            fillcolor=self.color,
            parent_uuid=self.parent_uuid,
            type=self.type,
        )

    # TODO: improve node name logic by using increamental index?
    @root_validator(pre=True)
    def set_uuid(cls, values: dict) -> str:
        if values.get("uuid", None):
            return values
        name = values.get("name", "no_name")
        values["uuid"] = f"{name}_{str(uuid4())}"
        return values

    @validator("subchart")
    def validate_subchart(
        cls, subchart: Flowchart, values: dict, **kwargs: dict
    ) -> Flowchart:
        if subchart is None:
            return None

        node_uuid = values["uuid"]
        if subchart.uuid != node_uuid:
            raise ValueError(f"node.uuid={node_uuid}!=subchart.uuid={subchart.uuid}")
        return subchart

    @property
    def type(self) -> str:
        return self.__class__.__name__

    def check_parent_uuid(
        self,
        expected_parent: str | None = None,
        checked: dict[str, list[str]] | None = None,
    ) -> None:
        if expected_parent and self.parent_uuid != expected_parent:
            error = f"[Node] {self.name=} {self.parent_uuid=} != {expected_parent=}"
            checked[self.uuid].append(error)
            logger.error(error)
        logger.debug(f"\tNode parent_uuid OK for node {self.name}")

    def check(
        self,
        expected_parent: str | None = None,
        checked: dict[str, list[str]] | None = None,
    ) -> None:
        if checked is None:
            checked = defaultdict(list)

        if self.uuid in checked:
            return dict()

        logger.info(f"Checking node {self.name} with parent {expected_parent}")
        self.check_parent_uuid(expected_parent=expected_parent, checked=checked)

        if self.subchart:
            self.subchart.check(checked=checked, expected_parent=self.uuid)
        else:
            logger.debug(f"\tNo subchart for node {self.name}")
        return checked

    def to_flat_dict(
        self, exclude: set | None = None, nodes: dict[str, dict] | None = None
    ) -> dict:
        logger.debug(f"Flatten node {self.uuid}")
        if nodes is None:
            nodes = dict()

        if exclude is None:
            exclude = set()

        if self.uuid in nodes:
            assert isinstance(self, LoopNode), f"Duplicate Non-LoopNode {self.uuid=}"
            return dict()

        # FIXME: Are we going to include class variables? e.g. shape, color
        node = self.dict(exclude={"subchart", *exclude})
        node["type"] = self.type
        if self.subchart:
            node["subchart"] = self.subchart.to_flat_dict(nodes)[_CHART_KEY]

        nodes[self.uuid] = node
        return nodes

    @classmethod
    def get_subclass(cls, class_name: str) -> Callable:
        mapping = {
            subcls.__name__: subcls
            for subcls in [
                StartNode,
                ActionNode,
                LoopNode,
                DecisionNode,
                ExitNode,
                EndNode,
            ]
        }
        if not (subclass := mapping.get(class_name, None)):
            raise ValueError(f"Cannot find the node type {class_name}")
        return subclass

    @classmethod
    def _pop_connected_attrs(cls, node_dict: dict[str, str]) -> dict[str, str]:
        return dict()

    @classmethod
    def from_flat_dict_by_id(
        cls,
        nodes: dict[str, dict],
        node_uuid: str,
        done: dict[str, BaseFlowchartNode],
    ) -> BaseFlowchartNode:
        if not node_uuid:
            return None

        if node_uuid in done:
            return done[node_uuid]

        logger.debug(f"Reconstruct node {node_uuid}")
        node_dict = nodes.get(node_uuid, None)
        assert node_dict, f"Node {node_uuid} not found in nodes"
        nodecls: BaseFlowchartNode = cls.get_subclass(node_dict.pop("type", None))

        if subchart := node_dict.pop("subchart", None):
            subchart = Flowchart.from_flat_dict_by_chart(nodes, subchart, done=done)
        # DEBUG: We have to pop out the branches from node_dict, which is done
        # in _pop_connected_attrs. But at the same time we don't want it
        # to be called before node is added to done. We also need to add a class
        # so that it can be linked.
        connected = nodecls._pop_connected_attrs(node_dict)
        node = nodecls(**node_dict, subchart=subchart)
        done[node.uuid] = node
        for attr, to_uuid in connected.items():
            to_node = cls.from_flat_dict_by_id(nodes, to_uuid, done)
            setattr(node, attr, to_node)
        return node


class BaseOneOutNode(BaseFlowchartNode):
    """Nodes that only have one out-edge."""

    next: BaseFlowchartNode | None = None

    def out_edge(self, graph: pgv.AGraph | None = None) -> Connection | None:
        # NOTE: Do not check next because it might haven't been assigned yet.
        return Connection(node=self, label="", graph=graph)

    def out_edges(self, graph: pgv.AGraph | None = None) -> list[Connection]:
        return [self.out_edge(graph)]

    def check(
        self,
        expected_parent: str | None = None,
        checked: dict[str, list[str]] | None = None,
    ) -> None:
        if not super().check(expected_parent=expected_parent, checked=checked):
            return checked
        if self.next is not None:
            self.next.check(expected_parent=expected_parent, checked=checked)
        return checked

    def to_flat_dict(self, nodes: dict[str, dict] | None = None) -> dict:
        # NOTE: Do not do nodes = xxx, only modify it in place!
        # We need receive the converted nodes to check if the next node is
        # Added or not before.
        if nodes is None:
            nodes = dict()
        updated = super().to_flat_dict(exclude={"next"}, nodes=nodes)
        if not updated:
            logger.debug(f"Node {self.uuid} already added, skip")
            return nodes

        node = nodes.get(self.uuid, None)
        assert node, f"Node {self.uuid} not found in nodes"
        if self.next:
            node["next"] = self.next.uuid
            nextnodes = self.next.to_flat_dict(nodes)
            nodes.update(nextnodes)
        return nodes

    @classmethod
    def _pop_connected_attrs(cls, node_dict: dict[str, str]) -> dict[str, str]:
        if next_uuid := node_dict.pop("next", None):
            return dict(next=next_uuid)
        return dict()


class StartNode(BaseOneOutNode):
    """The start of the flowchart."""

    shape: ClassVar[str] = "oval"
    color: ClassVar[str] = "palegreen"
    name: str = "flowchart_start"
    label: str = "Start"
    inputs: Any = None


class ActionNode(BaseOneOutNode):
    color: ClassVar[str] = "skyblue"
    shape: ClassVar[str] = "box"


class LoopNode(BaseOneOutNode):
    """Node for fetching next element for the next iteration of a loop."""

    shape: ClassVar[str] = "box"
    color: ClassVar[str] = "cornflowerblue"


class DecisionNode(BaseFlowchartNode):
    """Node for checking if a condition is true or not."""

    shape: ClassVar[str] = "diamond"
    color: ClassVar[str] = "orange"

    true: BaseFlowchartNode | None = None
    false: BaseFlowchartNode | None = None

    def true_out_edges(self, graph: pgv.AGraph | None = None) -> list[Connection]:
        return [Connection(node=self, label="Yes", graph=graph)]

    def false_out_edges(self, graph: pgv.AGraph | None = None) -> list[Connection]:
        return [Connection(node=self, label="No", graph=graph)]

    def out_edges(self, graph: pgv.AGraph | None = None) -> list[Connection]:
        return self.true_out_edges(graph) + self.false_out_edges(graph)

    def check(
        self,
        expected_parent: str | None = None,
        checked: dict[str, list[str]] | None = None,
    ) -> None:
        if not super().check(expected_parent=expected_parent, checked=checked):
            return checked
        if self.true is not None:
            self.true.check(expected_parent=expected_parent, checked=checked)
        if self.false is not None:
            self.false.check(expected_parent=expected_parent, checked=checked)

    def to_flat_dict(self, nodes: dict[str, dict] | None = None) -> dict:
        updated = super().to_flat_dict(exclude={"true", "false"}, nodes=nodes)
        if not updated:
            logger.debug(f"Node {self.uuid} already added, skip")
            return nodes

        node = nodes.get(self.uuid, None)
        assert node, f"Node {self.uuid} not found in nodes"
        for key, branch in [("true", self.true), ("false", self.false)]:
            if branch:
                node[key] = branch.uuid
                branodes = branch.to_flat_dict(nodes)
                nodes.update(branodes)
        return nodes

    @classmethod
    def _pop_connected_attrs(cls, node_dict: dict[str, str]) -> dict[str, str]:
        connected = dict()
        for attr in ["true", "false"]:
            if next_uuid := node_dict.pop(attr, None):
                connected[attr] = next_uuid
        return dict(connected)


class ExitNode(BaseFlowchartNode):
    """Exits from the middle of the flowchart."""

    shape: ClassVar[str] = "oval"
    color: ClassVar[str] = "lavender"
    returns: Any = None


class EndNode(BaseFlowchartNode):
    """The end of the flowchart."""

    shape: ClassVar[str] = "oval"
    color: ClassVar[str] = "brown2"
    name: str = "flowchart_end"
    label: str = "End"
    returns: Any = None


def _log_conversion(process: Process, parent: BaseFlowchartNode) -> None:
    chart_type = (
        f"{parent.subchart.type} (expand={parent.expand})"
        if parent.subchart
        else None
    )
    logger.info(
        f"Converted [{process.index}] {process.name=} to an {parent.type} with {chart_type} subchart."
    )


def process_to_action_node(
    process: Process, parent_node: BaseFlowchartNode
) -> ActionNode:
    assert isinstance(process.pattern, ActionPattern)
    parent_uuid = parent_node.uuid if parent_node else None
    node = ActionNode(
        name=process.name, label=process.pattern.body, parent_uuid=parent_uuid
    )
    _log_conversion(process, node)
    return node


def process_to_exit_node(
    process: Process, parent_node: BaseFlowchartNode
) -> ExitNode:
    assert isinstance(process.pattern, ExitPattern)
    parent_uuid = parent_node.uuid if parent_node else None
    node = ExitNode(
        name=process.name, label=process.pattern.body, parent_uuid=parent_uuid
    )
    _log_conversion(process, node)
    return node


def process_to_node_with_loop_chart(
    process: Process, parent_node: BaseFlowchartNode
) -> ActionNode:
    assert isinstance(process.pattern, LoopPattern)

    # Body node
    body = ActionNode(name=f"{process.name}_body", label=process.pattern.body)

    # Setup node
    setup = LoopNode(
        name=f"{process.name}_setup", label=process.pattern.setup, next=body
    )
    if process.subprocesses:
        body.subchart = processes_to_linear_chart(process, parent_node=body)
        # TODO: How to handle the last node is ExitNode?
        body.expand = True

    # Decision node
    decision = DecisionNode(
        name=f"{process.name}_decision", label=process.pattern.decision
    )
    body.next = decision
    decision.false = setup

    # Parent node of the chart
    parent_uuid = parent_node.uuid if parent_node else None
    node = ActionNode(
        parent_uuid=parent_uuid,
        name=process.name,
        label=process.explanation,
        expand=len(process.subprocesses) > 0,
    )

    # Chart including setup, body, and decision nodes
    node.subchart = Flowchart.from_nodes(
        parent=node, type=FlowchartType.LOOP, start=setup
    )

    _log_conversion(process, node)
    return node


def _still_has_elif(processes: list[Process]) -> bool:
    # NOTE: The list is reversed
    return len(processes) >= 1 and isinstance(processes[-1].pattern, ElifPattern)


def _only_has_else(processes: list[Process]) -> bool:
    # NOTE: The list is reversed
    return len(processes) == 1 and isinstance(processes[0].pattern, ElsePattern)


def _create_node_with_if_chart(
    processes: list[Process], parent_node: BaseFlowchartNode
) -> ActionNode:
    # Could be if or elif pattern
    if_process = processes.pop()
    parent_uuid = parent_node.uuid if parent_node else None

    if_node = ActionNode(
        name=if_process.name,
        # TODO: improve the if_node.label to a summary of if_process + all
        # sub/elif/else processes.
        label=if_process.explanation,
        parent_uuid=parent_uuid,
        # Expand if there are subprocesses or if-elif-else groups
        expand=len(if_process.subprocesses) > 0 or len(processes) > 0,
    )

    # Create the subchart of if_node
    true = ActionNode(
        name=f"{if_process.name}_true",
        label=if_process.pattern.true,
        parent_uuid=if_node.uuid,
    )
    if if_process.subprocesses:
        true.subchart = processes_to_linear_chart(
            parent_process=if_process, parent_node=true
        )
        true.expand = True

    decision = DecisionNode(
        name=f"{if_process.name}_decision",
        label=if_process.pattern.decision,
        true=true,
        parent_uuid=if_node.uuid,
    )

    if _still_has_elif(processes):
        decision.false = _create_node_with_if_chart(processes, parent_node=if_node)
    elif _only_has_else(processes):
        label = processes[-1].pattern.body
        decision.false = ActionNode(
            name=f"{if_process.name}_false",
            label=label,
            parent_uuid=if_node.uuid,
        )
    elif if_process.pattern.false:
        decision.false = ActionNode(
            name=f"{if_process.name}_false",
            label=if_process.pattern.false,
            parent_uuid=if_node.uuid,
        )
    else:
        logger.debug("The if process doesn't have a false branch.")

    if_node.subchart = Flowchart.from_nodes(
        parent=if_node, type=FlowchartType.IF, start=decision
    )
    _log_conversion(if_process, if_node)
    return if_node


def processes_to_node_with_if_chart(
    processes: list[Process], parent_node: BaseFlowchartNode
) -> ActionNode:
    """create an ActionNode with a subchart for the if-elif(-else) group."""
    assert isinstance(processes[0].pattern, IfPattern)

    if_process = processes[0]
    if len(processes) > 1:
        # TODO: Make this warning in production
        assert if_process.pattern.false is None

    return _create_node_with_if_chart(list(reversed(processes)), parent_node)


def _is_if_group(processes: list[Process]) -> bool:
    # Multiple processes mean we have an if-elif(-else) group
    # For now we only have if-elif-else groups
    # Later we might have linear groups as well
    assert len(processes) > 1
    if not isinstance(processes[0].pattern, IfPattern):
        raise ValueError("The first process must be an IfPattern")
    if not isinstance(processes[-1].pattern, (ElifPattern, ElsePattern)):
        raise ValueError("The last process must be an ElifPattern or ElsePattern")
    if any(not isinstance(p.pattern, ElifPattern) for p in processes[1:-1]):
        raise ValueError("The middle processes must be ElifPattern")
    return True


def processes_to_node(
    processes: list[Process], parent_node: BaseFlowchartNode
) -> BaseFlowchartNode:

    if len(processes) == 1:
        process = processes[0]
        if isinstance(process.pattern, ActionPattern):
            return process_to_action_node(process, parent_node)
        elif isinstance(process.pattern, ExitPattern):
            return process_to_exit_node(process, parent_node)
        elif isinstance(process.pattern, LoopPattern):
            return process_to_node_with_loop_chart(process, parent_node)
        elif isinstance(process.pattern, IfPattern):
            # For If without elif or else, we will also treat it with the group
            # handler for consistency
            return processes_to_node_with_if_chart(processes, parent_node)
    elif _is_if_group(processes):
        # Single If as a group for consistency
        return processes_to_node_with_if_chart(processes, parent_node)


def _is_last_if_or_elif(current: list[list[Process]]) -> bool:
    return current and isinstance(current[-1].pattern, (IfPattern, ElifPattern))


def _is_elif_or_else(process: Process) -> bool:
    return isinstance(process.pattern, (ElifPattern, ElsePattern))


def processes_to_linear_chart(
    parent_process: Process, parent_node: BaseFlowchartNode
) -> Flowchart:
    processes = parent_process.subprocesses
    if not processes:
        return None
    groups: list[list[Process]] = []  # list of lists to keep track of process groups
    current: list[Process] = []  # Current group being built

    for process in processes:
        if isinstance(process.pattern, IfPattern):
            # Start a new group with the current if process
            current = [process]
            groups.append(current)
        elif _is_elif_or_else(process) and _is_last_if_or_elif(current):
            current.append(process)
        else:
            current = [process]
            groups.append(current)

    nodes = []
    previous = None
    for group in groups:
        node = processes_to_node(group, parent_node=parent_node)
        assert isinstance(
            node, (ExitNode, ActionNode)
        ), f"{node.name=} {type(node)=} Cannot be a parent node."
        nodes.append(node)
        if previous is not None:
            previous.next = node
        previous = node

    assert len(nodes) > 0, "The subprocesses must have at least one node."
    subchart = Flowchart.from_nodes(
        parent=parent_node,
        type=FlowchartType.LINEAR,
        start=nodes[0],
    )
    _log_conversion(parent_process, parent_node)
    return subchart


def root_process_to_flowchart(process: Process) -> Flowchart:
    assert process.subprocesses, "The root process must have subprocesses."
    root_uuid = f"root_{process.name}_{uuid4()}"
    end = ExitNode(name="flowchart_end", label="End", parent_uuid=root_uuid)
    body = ActionNode(
        name=process.name,
        label=process.explanation,
        expand=True,
        next=end,
        parent_uuid=root_uuid,
    )
    body.subchart = processes_to_linear_chart(
        parent_process=process, parent_node=body
    )
    start = StartNode(name="flowchart_start", next=body, parent_uuid=root_uuid)

    root_chart = Flowchart(
        name=f"root_{process.name}",
        type=FlowchartType.LINEAR,
        start=start,
        uuid=root_uuid,
    )
    return root_chart


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
                    f"{graph.get_edge(node_edge).attr['label']}. "
                    f"Will overwrite with label {edge.label}."
                )
                graph.add_edge(node_edge, label=edge.label)
            else:
                continue
            logger.debug(
                f"Adding edge\n\t{from_node=}\n\t{to_node=}\n\t{edge.label=}\n\t{graph.name=}"
            )


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
        assert isinstance(node, ActionNode)
        out_edges = flowchart_to_graph(
            node.subchart, graph, in_edges=in_edges, config=config
        )
        if node.next:
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
    elif isinstance(node, (ExitNode, EndNode)):
        logger.info(f"Encounter an ExitNode {node.name} at this branch.")
        out_edges = []

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
    if save_png:
        graph.draw(output_path / f"{input.name}{suffix}.png", prog="dot")
    if save_dot:
        graph.write(output_path / f"{input.name}{suffix}.dot")
    return graph


if __name__ == "__main__":
    # Creating test cases for the conversion functions
    dummy_parent_node = ActionNode(
        name="DummyParentNode",
        label="DummyParentNode",
        expand=True,
        uuid="DummyParentNode_uuid",
    )
    test_action_process = Process(
        name="ActionProcess",
        explanation="This is an action process",
        pattern=ActionPattern(body="Action Body"),
    )
    test_action_process2 = Process(
        name="ActionProcess2",
        explanation="This is an action process2",
        pattern=ActionPattern(body="Action Body2"),
    )
    converted_action_node = process_to_action_node(
        test_action_process, parent_node=dummy_parent_node
    )
    flowchart_node_to_dot_graph(converted_action_node)
    logger.info("======")

    test_exit_process = Process(
        name="ExitProcess",
        explanation="This is an exit process",
        pattern=ExitPattern(body="Exit Body"),
    )
    converted_exit_node = process_to_exit_node(
        test_exit_process, parent_node=dummy_parent_node
    )
    flowchart_node_to_dot_graph(converted_exit_node)
    logger.info("======")

    test_if_process_no_else = Process(
        name="IfProcess_no_else",
        explanation="This is an if process no else",
        pattern=IfPattern(decision="If Decision", true="If True", false=None),
    )
    converted_if_node_no_else = processes_to_node_with_if_chart(
        [test_if_process_no_else],
        parent_node=dummy_parent_node,
    )
    flowchart_node_to_dot_graph(converted_if_node_no_else)
    logger.info("======")

    test_if_process_no_sub = Process(
        name="IfProcess_no_sub",
        explanation="This is an if process no sub",
        pattern=IfPattern(decision="If Decision", true="If True", false="If False"),
    )
    converted_if_node_no_sub = processes_to_node_with_if_chart(
        [test_if_process_no_sub],
        parent_node=dummy_parent_node,
    )
    flowchart_node_to_dot_graph(converted_if_node_no_sub)
    logger.info("======")

    test_if_process = Process(
        name="IfProcess",
        explanation="This is an if process",
        pattern=IfPattern(decision="If Decision", true="If True", false="If False"),
        subprocesses=[
            test_action_process,
            test_action_process2,
        ],
    )
    converted_if_node = processes_to_node_with_if_chart(
        [test_if_process], parent_node=dummy_parent_node
    )
    flowchart_node_to_dot_graph(converted_if_node)
    logger.info("======")

    test_if_elif_else_processes = [
        Process(
            name="IfProcess_with_elif_else",
            explanation="This is the main if process",
            pattern=IfPattern(decision="If Decision", true="If True"),
        ),
        Process(
            name="ElifProcess1",
            explanation="This is an elif process1",
            pattern=ElifPattern(decision="Elif Decision1", true="Elif Body"),
        ),
        Process(
            name="ElifProcess2",
            explanation="This is an elif process2",
            pattern=ElifPattern(decision="Elif Decision2", true="Elif Body"),
        ),
        Process(
            name="ElseProcess",
            explanation="This is an else process",
            pattern=ElsePattern(body="Else Body"),
        ),
    ]
    converted_if_elif_else_node = processes_to_node_with_if_chart(
        test_if_elif_else_processes,
        parent_node=dummy_parent_node,
    )
    flowchart_node_to_dot_graph(converted_if_elif_else_node)
    logger.info("======")

    test_loop_process = Process(
        name="LoopProcess",
        explanation="This is a loop process",
        pattern=LoopPattern(
            setup="Loop Setup", body="Loop Body", decision="Loop Decision"
        ),
        subprocesses=[
            test_action_process,
            test_action_process2,
        ],
    )
    converted_loop_node = process_to_node_with_loop_chart(
        test_loop_process, parent_node=dummy_parent_node
    )
    flowchart_node_to_dot_graph(converted_loop_node)
    logger.info("======")

    all_test_processes = [
        test_if_process_no_sub,
        test_action_process,
        test_if_process_no_else,
        *test_if_elif_else_processes,
        test_loop_process,
    ]

    parent_process = Process(
        name="ParentProcess",
        explanation="This is a parent process",
        subprocesses=all_test_processes,
    )
    converted_flowchart = root_process_to_flowchart(parent_process)
    flowchart_node_to_dot_graph(converted_flowchart)
    logger.info("======")

    pass


def dict_diff(d1, d2, path=""):
    """Recursively compares two dictionaries.
    Args:
        d1 (dict): First dictionary.
        d2 (dict): Second dictionary.
        path (str): The current path to the value being compared.
    """
    for key in d1:
        if key not in d2:
            print(f"{path + str(key)}: Key removed from second dict")
        else:
            if isinstance(d1[key], dict) and isinstance(d2[key], dict):
                path += key + "."
                dict_diff(d1[key], d2[key], path)
                path = path[: -len(key) - 1]  # Reset path to previous state
            elif d1[key] != d2[key]:
                print(f"{path + str(key)}: {d1[key]} -> {d2[key]}")

    for key in d2:
        if key not in d1:
            print(f"{path + str(key)}: Key added in second dict")


def test_save_load(test_node):
    test_dict = test_node.to_flat_dict()
    Path("test_dict.json").write_text(json.dumps(test_dict, indent=4))
    test_node.to_file(Path("test.json"), indent=4)
    load_node = Flowchart.from_flat_dict(test_dict)
    load_dict = load_node.to_flat_dict()
    load_node.to_file(Path("load.json"), indent=4)
    print("******")
    print("Save and load test results:")
    try:
        assert test_dict == load_dict
    except AssertionError:
        print("test_dict != load_dict")
        dict_diff(test_dict, load_dict)
    finally:
        print("test_dict == load_dict")
    try:
        assert test_node == load_node
    except AssertionError:
        print("test_node != load_node")
    except RecursionError:
        print("Loop in the charts, cannot compare.")
    finally:
        print("test_node == load_node")
    print("******")


# %%

# %%
def _edge_element(edge) -> dict:
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


def _node_element(node) -> dict:
    return dict(
        group="nodes",
        data=dict(
            id=node.name,
            label=node.attr["label"],
            parent=node.attr["parent_uuid"],
        ),
        classes=node.attr["type"],
    )


def flowchart_to_element_json(
    flowchart: Flowchart, output_path: Path | None = None
) -> dict:
    # if True:
    elements = []
    agraph = flowchart_node_to_dot_graph(
        flowchart,
        save_png=False,
        save_dot=False,
        config=FlowchartConfig(expand_all=True),
    )
    flat_dict = flowchart.to_flat_dict()
    for node in agraph.nodes():
        elements.append(_node_element(node))
        parent = flat_dict["nodes"].get(node.attr["parent_uuid"], None)
        if not parent:
            print(f"no parent for node {node.name}")
            continue
        elements.append(_dict_node_element(parent))
        print(f"add parent for node {node.name}")

    for edge in agraph.edges():
        elements.append(_edge_element(edge))

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(dict(flowchart=elements), indent=4))
    # return elements


if __name__ == "__main__":
    output_path = Path(
        "/Users/jun/Projects/ichigen-coder/.local/flowcharts/autogpt/app/main/run_auto_gpt"
    )
    # autogpt_process = Process.from_file(output_path / "process_saved.json")
    # autogpt_chart = root_process_to_flowchart(autogpt_process)
    # test_path = Path(__file__).parent / "dot_graphs"
    # converted_flowchart.to_file(test_path / "flowchart_test.json", indent=4)
    autogpt_chart = Flowchart.from_file(output_path / "flowchart_saved.json")
    # flowchart = Flowchart.from_file(test_path / "flowchart_test.json")

    flowchart_to_element_json(
        autogpt_chart, Path("/Users/jun/Projects/display-flowchart/db.json")
    )
    # autogpt_chart.to_file(Path(__file__).parent / "flowchart_changed.json", indent=4)
    # assert loaded == autogpt_chart
    # test_save_load(autogpt_chart)
    # %%
    # %%timeit
    # f = Flowchart.from_file(output_path / "flowchart_saved.json")
    # g = flowchart_node_to_dot_graph(f, config=FlowchartConfig(expand_all=True), save_dot=True, save_png=False)
