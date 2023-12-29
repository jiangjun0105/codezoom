"""Converts Process to Flowchart."""
from __future__ import annotations

from uuid import uuid4

from loguru import logger

from codebase_analyzer.flowchart.node import (
    ActionNode,
    BaseFlowchartNode,
    DecisionNode,
    ExitNode,
    Flowchart,
    FlowchartType,
    LoopNode,
    StartNode,
    flowchart_node_to_dot_graph,
)
from codebase_analyzer.flowchart.process.schema import (
    ActionPattern,
    ElifPattern,
    ElsePattern,
    ExitPattern,
    IfPattern,
    LoopPattern,
    Process,
)


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

    # Parent node of the chart
    parent_uuid = parent_node.uuid if parent_node else None
    node = ActionNode(
        parent_uuid=parent_uuid,
        name=process.name,
        label=process.explanation,
        expand=len(process.subprocesses) > 0,
    )

    # Body node
    body = ActionNode(
        name=f"{process.name}_body",
        label=process.pattern.body,
        parent_uuid=node.uuid,
    )

    # Setup node
    setup = LoopNode(
        name=f"{process.name}_setup",
        label=process.pattern.setup,
        next=body,
        parent_uuid=node.uuid,
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

    # Chart including setup, body, and decision nodes
    node.subchart = Flowchart.from_nodes(
        parent=node, type=FlowchartType.PROCESS, start=setup
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
        type=FlowchartType.PROCESS,
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
        type=FlowchartType.PROCESS,
        start=start,
        uuid=root_uuid,
    )
    return root_chart


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
