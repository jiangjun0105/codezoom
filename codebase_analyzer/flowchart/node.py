"""Definitions of flowchart and its nodes."""
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

from codebase_analyzer.parser.uri import URI, Uri, node_uuid_to_uri, uri_to_path

REPO_ROOT = Path(__file__).parent.parent.parent
CACHE_ROOT = REPO_ROOT / "shared_cache"
LOCAL_ROOT = REPO_ROOT / ".local"

CHART_KEY = "chart"
NODES_KEY = "nodes"
START_KEY = "start"


class FlowchartType(Enum):
    PROCESS: str = "PROCESS"
    FUNCTION_DEF = "FUNCTION_DEF"
    FUNCTION_CALL = "FUNCTION_CALL"
    CLASS = "CLASS"


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

    @root_validator(pre=True)
    def set_parent_uuid(cls, values: dict) -> str:
        parent_uuid = values.get("uuid", None)
        start = values.get("start", None)
        if not parent_uuid or not start:
            return values

        done = set()

        def _set_parent_uuid(node: BaseFlowchartNodeType) -> None:
            if not node or node.uuid in done:
                return
            node.parent_uuid = parent_uuid
            done.add(node.uuid)
            if isinstance(node, BaseOneOutNode):
                _set_parent_uuid(node.next)
            elif isinstance(node, DecisionNode):
                _set_parent_uuid(node.true)
                _set_parent_uuid(node.false)
            elif isinstance(node, LoopNode):
                _set_parent_uuid(node.next)

        _set_parent_uuid(start)
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
        nodes = data.get(NODES_KEY, dict())
        chart = data.get(CHART_KEY, dict())
        done: dict[str, BaseFlowchartNode] = dict()
        return cls.from_flat_dict_by_chart(nodes=nodes, chart=chart, done=done)

    @classmethod
    def from_file(cls, json_file: Path, check: bool = True) -> Flowchart:
        data = json.loads(json_file.read_text())
        if CHART_KEY not in data or NODES_KEY not in data:
            raise ValueError(f"Invalid flowchart json {data}")
        chart = cls.from_flat_dict(data)
        if check and any(e for e in chart.check().values()):
            raise ValueError(f"Invalid flowchart {chart.name}")
        return chart

    def to_file(self, json_file: Path, indent: int = 4, check: bool = True) -> None:
        if check and any(e for e in self.check().values()):
            raise ValueError(f"Invalid flowchart {self.name}")
        json_file.parent.mkdir(parents=True, exist_ok=True)
        json_file.write_text(json.dumps(self.to_flat_dict(), indent=indent))
        logger.info(f"Saved flowchart {self.name} to {json_file}")

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
    chart_type: ClassVar[FlowchartType] = FlowchartType.PROCESS
    code: str | None = None
    name: str
    label: str
    uuid: str
    # This is uuid for both parent chart and the chart's parent node
    parent_uuid: str | None = None
    # NOTE: Any node can have a subchart after merging.
    # but after reorganizing, only IfNode and LoopNode will have subcharts
    subchart: Flowchart = Field(default=None)
    expand: bool = True

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name})"

    @classmethod
    def from_file(cls, json_file: Path, check: bool = True) -> BaseFlowchartNode:
        data = json.loads(json_file.read_text())
        if NODES_KEY not in data or START_KEY not in data:
            raise ValueError(f"Invalid node json {data}")
        node = cls.from_flat_dict_by_id(
            nodes=data.get(NODES_KEY, dict()),
            node_uuid=data.get(START_KEY, None),
            done=dict(),
        )
        if check and any(e for e in node.check().values()):
            raise ValueError(f"Invalid node {node.uuid}")
        return node

    def to_file(self, json_file: Path, indent: int = 4, check: bool = True) -> None:
        if check and any(e for e in self.check().values()):
            raise ValueError(f"Invalid node {self.uuid}")
        json_file.parent.mkdir(parents=True, exist_ok=True)
        data = dict(
            start=self.uuid,
            nodes=self.to_flat_dict(),
        )
        json_file.write_text(json.dumps(data, indent=indent))
        logger.info(f"Saved node {self.uuid} to {json_file}")

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
    ) -> dict:
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
            logger.warning(
                f"Already processed {type(self)} {self.name=} {self.uuid=}"
            )
            return dict()

        # FIXME: Are we going to include class variables? e.g. shape, color
        node = self.dict(exclude={"subchart", *exclude})
        node["type"] = self.type
        if self.subchart:
            node["subchart"] = self.subchart.to_flat_dict(nodes)[CHART_KEY]

        nodes[self.uuid] = node
        return nodes

    @classmethod
    def get_subclass(cls, class_name: str) -> Callable:
        mapping = {
            subcls.__name__: subcls
            for subcls in [
                StartNode,
                CallNode,
                DefineNode,
                ActionNode,
                LoopNode,
                DecisionNode,
                ExitNode,
                EndNode,
                FunctionNode,
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

    @classmethod
    def with_subchart(
        cls,
        chart_start: BaseFlowchartNode,
        chart_type: FlowchartType | None = None,
        **kwargs,
    ) -> BaseFlowchartNode:
        chart_type = chart_type or cls.chart_type
        node = cls(**kwargs)
        node.subchart = Flowchart.from_nodes(
            parent=node, type=chart_type, start=chart_start
        )
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
            return dict()
        if self.next is not None:
            self.next.check(expected_parent=expected_parent, checked=checked)
        return checked

    def to_flat_dict(
        self, nodes: dict[str, dict] | None = None, exclude: dict | None = None
    ) -> dict:
        """Converts the node and sub-nodes to a flat dict.

        Args:
            nodes: dict of nodes already added
            exclude: set of attributes to exclude other than "next"
        """
        # NOTE: Do not do nodes = xxx, only modify it in place!
        # We need receive the converted nodes to check if the next node is
        # Added or not before.
        if nodes is None:
            nodes = dict()

        exclude = {"next"} | (exclude or set())
        updated = super().to_flat_dict(exclude=exclude, nodes=nodes)
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


class FunctionNode(BaseFlowchartNode):
    """Node for a function.

    A function node must have a subchart like:
        start -> body -> end

    where the body usually has a subchart defining the detailed logics.
    """

    shape: ClassVar[str] = "box"
    color: ClassVar[str] = "cornflowerblue"
    chart_type: ClassVar[FlowchartType] = FlowchartType.FUNCTION_DEF
    func_uri: URI

    class Config:
        validate_assignment = True

    @validator("subchart")
    def check_subchart(cls, subchart: Any) -> dict:
        if not subchart:
            return subchart
        if subchart.type != FlowchartType.FUNCTION_DEF:
            raise ValueError(
                f"Function node must have a subchart of type {FlowchartType.FUNCTION_DEF}"
            )
        if (
            subchart.start is None
            or subchart.start.next is None
            or subchart.start.next.next is None
        ):
            raise ValueError(
                f"Function subchart must have [start -> body -> end] structure, but got {subchart}"
            )
        return subchart

    @property
    def start(self) -> BaseFlowchartNode:
        return self.subchart.start

    @property
    def body(self) -> BaseFlowchartNode:
        return self.subchart.start.next

    @property
    def end(self) -> BaseFlowchartNode:
        return self.subchart.start.next.next

    @property
    def inputs(self) -> Any:
        return self.start.inputs

    @property
    def returns(self) -> Any:
        return self.end.returns

    def get_process_chart(self, uuid: str) -> Flowchart:
        if not self.body.subchart:
            logger.debug(
                f"Function {self.name} body has no subchart."
                "Should merge this function with the caller."
            )
            return None
        copied = copy.deepcopy(self.body.subchart)
        copied.uuid = uuid
        return copied

    def to_flat_dict(self, nodes: dict[str, dict] | None = None) -> dict:
        """Converts the node and sub-nodes to a flat dict.
        FunctionNode does not have any successors, because it's last node is EndNode."""
        if nodes is None:
            nodes = dict()
        updated = super().to_flat_dict(
            exclude={"start", "end", "body", "next"}, nodes=nodes
        )
        if not updated:
            logger.debug(f"Node {self.uuid} already added, skip")
            return nodes

        node = nodes.get(self.uuid, None)
        assert node, f"Node {self.uuid} not found in nodes"
        return nodes


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


class CallNode(ActionNode):
    """A node that represents a function call."""

    color: ClassVar[str] = "azure"
    chart_type: ClassVar[FlowchartType] = FlowchartType.FUNCTION_CALL
    func_uri: URI
    inputs: Any = None
    returns: Any = None
    expand: bool = True

    @property
    def node_attrs(self) -> dict[str, str]:
        # Use this method to customize the visualization of the node
        attrs = super().node_attrs
        attrs["func_uri"] = self.func_uri
        return attrs


class DefineNode(ActionNode):
    """A node that defines a normal or nested function.
    The defined function is not its subchart because the function is not executed."""

    color: ClassVar[str] = "bisque"
    func_uri: URI

    @property
    def node_attrs(self) -> dict[str, str]:
        attrs = super().node_attrs
        attrs["func_uri"] = self.func_uri
        return attrs


class ReturnNode(ActionNode):
    """A node that represents a function return."""

    color: ClassVar[str] = "greenyellow"
    returns: Any


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
        if nodes is None:
            nodes = dict()
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
    """Exits the program, e.g. sys.exit()."""

    shape: ClassVar[str] = "oval"
    color: ClassVar[str] = "lavender"


class EndNode(BaseFlowchartNode):
    """The end of the flowchart, e.g. return of a function."""

    shape: ClassVar[str] = "oval"
    color: ClassVar[str] = "brown2"
    name: str = "flowchart_end"
    label: str = "End"
    returns: Any = None


class ContextPair(BaseModel):
    """A pair of context nodes."""

    get_ctx: ActionNode | CallNode
    enter: ActionNode
    exit: ActionNode

    @property
    def start(self) -> ActionNode | CallNode:
        return self.get_ctx if isinstance(self.get_ctx, CallNode) else self.enter


### Below are for testing ###


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


def test_save_load(test_chart: Flowchart):
    test_node = test_chart.start
    test_node.to_file(Path("test_node.json"), indent=4)
    load_node = BaseFlowchartNode.from_file(Path("test_node.json"))
    test_dict = test_node.to_flat_dict()
    load_dict = load_node.to_flat_dict()
    assert test_dict == load_dict, dict_diff(test_dict, load_dict)

    test_dict = test_chart.to_flat_dict()

    test_chart.to_file(Path("test_chart.json"), indent=4)
    load_chart1 = Flowchart.from_flat_dict(test_dict)
    assert test_dict == load_chart1.to_flat_dict()

    load_chart2 = Flowchart.from_file(Path("test_chart.json"))
    load_chart2_dict = load_chart2.to_flat_dict()
    assert test_dict == load_chart2_dict, dict_diff(test_dict, load_chart2_dict)


if __name__ == "__main__":
    output_path = Path(
        "/Users/jun/Projects/ichigen-coder/codebase_analyzer/flowchart/convert_dump/autogpt/app/main/print_assistant_thoughts/flat.json"
    )
    autogpt_chart = Flowchart.from_file(output_path)
    test_save_load(autogpt_chart)
