from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pygraphviz as pgv
from pydantic import BaseModel, Field, root_validator

from codebase_analyzer.flowchart.process.generate import (
    Process,
    code_to_process,
    process_lineno,
    process_to_json,
)
from codebase_analyzer.flowchart.process.utils import _output_path
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode
from codebase_analyzer.parser.uri import URI, uri_stem

REPO_ROOT = Path(__file__).parent.parent.parent
CACHE_ROOT = REPO_ROOT / "shared_cache"
LOCAL_ROOT = REPO_ROOT / ".local"


class Branch(BaseModel):
    processes: list[Process]
    start: str
    end: str | None = None
    edge_label: str = Field(default="")


class PendingBranch(BaseModel):
    # (start, end, edge_label): processes
    branches: OrderedDict = Field(default_factory=OrderedDict)

    def add_branch(
        self,
        start: str,
        processes: list[Process],
        end: str | None = None,
        edge_label: str = "",
    ) -> None:
        assert start != end, f"Start and end node should not be the same {start}"
        key = (start, end, edge_label)
        if key in self.branches:
            assert (
                self.branches[key] == []
            ), f"Branch {start, end, edge_label} already exists {self.branches[key]}"
        self.branches[key] = processes

    def update_ends(self, end: str) -> None:
        # Has to iterate again to keep the order
        new_branches = OrderedDict()
        for (start, old_end, edge_label), processes in self.branches.items():
            if old_end is None:
                assert (
                    start != end
                ), f"Start and end node should not be the same {start}"
                print(f"Update end node of branch {start} -> {end} [{edge_label}]")
                new_branches[(start, end, edge_label)] = processes
            else:
                print(f"Skip node of branch {start} -> {old_end} [{edge_label}]")
                new_branches[(start, old_end, edge_label)] = processes
        self.branches = new_branches


def _add_node_by_process(
    graph: pgv.AGraph,
    process: Process,
    pending: Pending,
    branches: list[Branch],
) -> None:
    # NOTE: Setting label=None will show `None` in the graph.
    _add_node(
        graph=graph,
        parent_name=pending.parent_name,
        node_name=process.node_name,
        node_attrs=dict(
            label=process.explanation or process.node_name,
            shape=process.node_shape,
            start_lineno=process.code_lineno[0],
            end_lineno=process.code_lineno[-1] + 1,
        ),
        has_edge=pending.has_edge,
        edge_attrs=dict(
            label=pending.edge_label or "",
        ),
        branches=branches,
    )


def _add_node(
    graph: pgv.AGraph,
    parent_name: str,
    node_name: str,
    branches: PendingBranch,
    has_edge: bool = True,
    node_attrs: dict | None = None,
    edge_attrs: dict | None = None,
) -> None:
    """Add a new node, connect the previous node with the new node and return
    the name of the new node. Also assign the new node as the end node of the
    branches which don't have an end node."""
    node_attrs = node_attrs or {}
    edge_attrs = edge_attrs or {}

    graph.add_node(node_name, **node_attrs)
    if has_edge:
        graph.add_edge(parent_name, node_name, **edge_attrs)

    if branches:
        branches.update_ends(node_name)


class Pending(BaseModel):
    parent_name: str
    node_shape: str = Field(default="box")
    has_edge: bool = Field(default=True)
    edge_label: str = Field(default="")


def _dot_from_process(
    processes: list[Process],
    graph: pgv.AGraph,
    start: str,
    end: str,
    edge_label: str = "",
) -> None:
    """Add all processes to the graph betwen start and end nodes."""
    if not processes:
        graph.add_edge(start, end, label=edge_label)
        return graph

    else_origin = None
    branches = PendingBranch()
    pending = Pending(parent_name=start, edge_label=edge_label)

    # First add all nodes in the current branch, and save sub branches for later.
    # By the end, main branch should be single line processes.
    for p in processes:
        if p.pattern is None:  # Normal process
            _add_node_by_process(graph, p, pending=pending, branches=branches)
            pending = Pending(parent_name=p.node_name)
        elif p.pattern in ["if", "if-elif"]:
            _add_node_by_process(graph, p, pending=pending, branches=branches)
            pending = Pending(parent_name=p.node_name, has_edge=False)
            # True branch
            branches.add_branch(
                processes=p.subprocesses, start=p.node_name, edge_label="yes"
            )
            # False branch
            if p.pattern == "if":
                branches.add_branch(processes=[], start=p.node_name, edge_label="no")
            else_origin = p
        elif p.pattern == "elif":
            # start node should be a "if" or "elif" node.
            assert graph.get_node(pending.parent_name).attr["shape"] == "diamond"
            elif_process = p.copy(update={"pattern": "if-elif"})
            # Flase branch from previous to this node
            branches.add_branch(
                start=pending.parent_name, processes=[elif_process], edge_label="no"
            )
            # False branch of this node at next level
            # branches.add_branch(start=elif_process.node_name, processes=[], edge_label="no")
            # TODO: Check if there is a elif/else after elif, now assume yes
            else_origin = elif_process
        elif p.pattern == "else":
            # else won't add a node in main branch, so no need to update start.
            assert graph.get_node(pending.parent_name).attr["shape"] == "diamond"
            assert else_origin is not None
            branches.add_branch(
                start=else_origin.node_name,
                processes=p.subprocesses,
                edge_label="no",
            )
        elif p.pattern == "loop":
            # Add loop setup node.
            _add_node_by_process(graph, p, pending=pending, branches=branches)

            # Add a diamond loop termination checking node after the setup node.
            check_node = f"{p.node_name}_loop_check"
            _add_node(
                graph,
                parent_name=p.node_name,
                node_name=check_node,
                has_edge=False,
                node_attrs=dict(label="Is loop done?", shape="diamond"),
                branches=branches,
            )
            graph.add_edge(check_node, p.node_name, label="no")
            branches.add_branch(
                processes=p.subprocesses, start=p.node_name, end=check_node
            )
            pending = Pending(parent_name=check_node, edge_label="yes")
        else:
            raise ValueError(f"Unknown pattern {p.pattern}")
    # If the end node is the end node, add all branches to the graph.
    branches.update_ends(end)

    for keys, branch_processes in branches.branches.items():
        branch_start, branch_end, branch_edge_label = keys
        assert branch_end is not None
        _dot_from_process(
            processes=branch_processes,
            graph=graph,
            start=branch_start,
            end=branch_end,
            edge_label=branch_edge_label,
        )
    if pending.has_edge:
        graph.add_edge(pending.parent_name, end, label=pending.edge_label)
    return


def get_dot_from_process(process: Process) -> str:
    # Create a new graph
    graph = pgv.AGraph(directed=True)
    graph.node_attr["shape"] = "box"
    # A.node_attr['style'] = 'filled'
    # A.node_attr['fillcolor'] = 'yellow'
    start = "start"
    end = "end"
    graph.add_node(start, shape="oval")
    graph.add_node(end, shape="oval")
    # graph.add_edge(start, end)
    _dot_from_process(process.subprocesses, graph, start, end)
    return graph


def generate_function_flowchart(
    target_uri: URI,
    nodes: dict[CodeNode],
    output_dir: Path | None = None,
    call_api: bool = False,
) -> str:
    output_path = _output_path(target_uri, output_dir=output_dir)
    code_to_process(
        target_uri=target_uri,
        nodes=nodes,
        call_api=call_api,
        output_path=output_path,
    )
    process_to_json(output_path=output_path, call_api=call_api)
    process_lineno(target_uri=target_uri, output_path=output_path, call_api=call_api)
    process = Process.from_files(
        process_json_file=output_path / "process.json",
        lineno_csv_file=output_path / "lineno.csv",
    )
    graph = get_dot_from_process(process)
    graph.draw(output_path / "flowchart.png", prog="dot")
    graph.write(output_path / "flowchart.dot")


if __name__ == "__main__":
    run_interaction_loop = "/autogpt.app.main/run_interaction_loop"
    # generate_function_flowchart(target_uri=run_interaction_loop, nodes=nodes, output_dir=output_dir, call_api=True)
    # exit()
    # graph = get_dot_from_process(process)
    # graph.draw(output_path / "flowchart.png", prog="dot")
    # graph.write(output_path / "flowchart.dot")
