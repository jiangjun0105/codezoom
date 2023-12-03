# %%
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger

from codebase_analyzer.flowchart.utils import _output_path
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode
from codebase_analyzer.parser.uri import URI, uri_full_func_name, uri_stem

REPO_ROOT = Path(__file__).parent.parent.parent
CACHE_ROOT = REPO_ROOT / "shared_cache"
LOCAL_ROOT = REPO_ROOT / ".local"

code_info = CodeInfo.from_disk(input_path=CACHE_ROOT / "Auto-GPT/codeinfo.json")
nodes = code_info.nodes
output_dir = (LOCAL_ROOT / "flowcharts").absolute()

debug_uri = "/autogpt.logs.logger/Logger.debug"
main_uri = "/autogpt.app.main/run_auto_gpt"
update_uri = "/autogpt.app.main/update_user"
loop_uri = "/autogpt.app.main/run_interaction_loop"
# %%
target_uri = main_uri
output_path = _output_path(target_uri, output_dir=output_dir)
print(output_path)

code = nodes[target_uri].code
ast_tree = ast.parse(code)


def is_same_node(node1, node2):  # noqa C901
    # Compare the types of both nodes
    if type(node1) != type(node2):
        return False

    # If they are the same type, we can compare the relevant fields
    if isinstance(node1, ast.AST):
        # Compare non-node fields for equality
        for field in node1._fields:
            if isinstance(getattr(node1, field), ast.AST):
                # If the field is an AST node, compare recursively
                if not is_same_node(getattr(node1, field), getattr(node2, field)):
                    return False
            elif isinstance(getattr(node1, field), list):
                # If the field is a list of nodes, compare each item
                list1 = getattr(node1, field)
                list2 = getattr(node2, field)
                if len(list1) != len(list2):
                    return False
                for item1, item2 in zip(list1, list2):
                    if not is_same_node(item1, item2):
                        return False
            else:
                # Compare field values directly
                if getattr(node1, field) != getattr(node2, field):
                    return False
        return True
    else:
        # If it's not an AST node, just compare values
        return node1 == node2


from typing import ClassVar

from codebase_analyzer.flowchart.node import (
    ActionNode,
    BaseFlowchartNode,
    CallNode,
    DecisionNode,
    Flowchart,
    FlowchartConfig,
    FlowchartType,
    LoopNode,
    flowchart_node_to_dot_graph,
)
from codebase_analyzer.flowchart.process import ask_gpt

# %%
from codebase_analyzer.tools.context import get_str_length

# RETHINK HOW SHOULD DEFINE CALLNODE
# class CallNode(BaseFlowchartNode):
#     """A node that represents a function call."""

#     color: ClassVar[str] = "azure"
#     func_uri: URI
#     # TODO: add inputs and return info


# class CallActionNode(CallNode, ActionNode):
#     """An action node which is a function call."""

#     pass


# class CallDecisionNode(CallNode, DecisionNode):
#     """An if node which is a function call."""

#     pass


def _is_same_method_call(known_call: str, test_call: str) -> bool:
    """FIXME: This is a hacky way to compare method calls. We need a more robust
    way, otherwise there will be millions of corner cases."""
    known_parts = known_call.split(".")
    test_parts = test_call.split(".")
    if known_parts[-1] == "__init__":
        # E.g. Agent.__init__ and Agent)
        return ".".join(known_parts[:-1]) == test_call
    # TODO: handle other __xxx__ methods
    return known_parts[1:] == test_parts[1:]


def _get_first_party_call(
    func_node: ast.Name | ast.Attribute, known_calls: list[URI]
) -> URI | None:
    """Returns True if the call is a first party call.
    TODO: Parse imports and construct the key-value pairs of the namespace.

    Known issues:
    * run_auto_gpt calls plugin.can_handle_retport but its not in the call graph, because no proper type annotation for config.plugins.
    * Class methods calls like Agent.__init__ and Logger.set_level are not same.
    * Workspace.init_workspace are the same with code.
    * scan_plugins, get_memory is not in the call graph.
    """
    # TODO: Find a way to map the function name to the URI.
    # TODO: Add non-expanding call check logic here.
    # return ast.unparse(child.func) in nodes[target_uri].calls
    assert isinstance(
        func_node, (ast.Name, ast.Attribute)
    ), f"Encounterred {type(func_node)} node."

    call_func = ast.unparse(func_node)
    for known_call in known_calls:
        known_call_func = uri_full_func_name(known_call)
        if known_call_func == call_func:
            return known_call
        if isinstance(func_node, ast.Attribute) and _is_same_method_call(
            known_call_func, call_func
        ):
            return known_call
    print("Unknown call:", ast.unparse(func_node))
    return None


def call_func_info(node: ast.Call, node_calls: list[URI]) -> str:
    """Gets the semantic information of the inputs and returns of a call node.
    This is also for providing LLM more context information."""
    call_uri = _get_first_party_call(node.func, known_calls=node_calls)
    if not call_uri:
        return None

    # TODO: add input and return info to the function nodes. For now we use
    # summary for experimenting purpose.
    # summary = nodes[call_uri].summary
    return call_uri


def is_first_party_call(node: ast.Call, calls: list[URI]) -> bool:
    """Returns True if the node is a first party call."""
    if not isinstance(node, (ast.Call)):
        return False
    if _get_first_party_call(node.func, known_calls=calls):
        return True
    return False


def is_control_flow(node: ast.AST, threshold: int = 50) -> bool:
    """Returns True if the node is a control flow node."""
    # TODO: get the list based on python version. ast.TryStar is added in 3.11
    # TODO: ast.comprehension might also need to be added.
    if isinstance(
        node,
        (
            ast.If,
            ast.IfExp,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.With,
            ast.AsyncWith,
            ast.Try,
            ast.withitem,
        ),
    ):
        # TODO: Try different thresholds and uints.
        if get_str_length(ast.unparse(node)) >= threshold:
            return True
    return False


def should_expand(node: ast.AST, calls: list, threshold: int = 50) -> bool:
    """Returns True if the node itself or its children is a first party call or
    a control flow node whose code length in token is larger than the input
    threshold."""
    if hasattr(node, "name"):
        node_symbol = node.name
    elif isinstance(node, ast.Call):
        node_symbol = ast.unparse(node.func)
    else:
        node_symbol = type(node)

    # NOTE: ast.walk includes all children and the node itself.
    # FIXME: This walk is actually expensive when the node is large. For now
    # it's OK because we process code function by function so won't be too large.
    for child in ast.walk(node):
        if is_first_party_call(child, calls=calls):
            logger.debug(
                f"Expand {node_symbol} as found first party call: {ast.unparse(child.func)}"
            )
            return True
        if is_control_flow(child, threshold=threshold):
            logger.debug(
                f"Expand {node_symbol} as found control flow: {ast.unparse(child)}"
            )
            return True
    return False


def connect_nodes(nodes: list[BaseFlowchartNode]) -> BaseFlowchartNode | None:
    """Connects a list of nodes and return the start node."""
    if not nodes:
        return None
    start = before = nodes[0]
    for node in nodes[1:]:
        before.next = node
        before = node
    return start


def ast_control_to_chart_node(node: ast.AST, **kwargs: Any) -> ActionNode:
    """Converts an AST control flow node to a Flowchart node.

    NOTE: kwargs are the same as ast_node_to_chart_node, it's not a good practice but
    here every function's kwargs are the same so we used this way."""
    match type(node):
        # If group
        case ast.If:
            return ast_if_to_chart_node(node, **kwargs)
        case ast.IfExp:
            return ast_ifexp_to_chart_node(node, **kwargs)
        case ast.Try:
            return ast_try_to_chart_node(node, **kwargs)
        # Loop group
        case ast.For:
            return ast_try_to_chart_node(node, **kwargs)
        case ast.AsyncFor:
            return ast_try_to_chart_node(node, **kwargs)
        case ast.While:
            return ast_try_to_chart_node(node, **kwargs)
        # With group
        case ast.With:
            return ast_try_to_chart_node(node, **kwargs)
        case ast.AsyncWith:
            return ast_try_to_chart_node(node, **kwargs)
        case ast.withitem:
            return ast_withitem_to_chart_node(node, **kwargs)
        case _:
            raise ValueError(f"Node {node} is not a control flow node.")


def _create_warpper_node(
    name: str,
    label: str,
    start: BaseFlowchartNode,
    type: FlowchartType,  # parent_uuid: str
) -> ActionNode:
    """Creates a wrapper node for a subchart. For now we only create ActionNode."""
    wrapper = ActionNode(
        name=name,
        # uuid=start.parent_uuid,
        # parent_uuid=parent_uuid,
        label=label,
    )
    wrapper.subchart = Flowchart.from_nodes(
        parent=wrapper,
        start=start,
        type=type,
    )
    return wrapper


def ast_if_to_chart_node(node: ast.If, **kwargs: Any) -> ActionNode:
    """Converts an AST if node to a Flowchart node."""
    assert isinstance(node, ast.If), f"Node {node} is not an if node."

    logger.info(
        f"Converting if node `{ast.unparse(node)[:10]}` to a Flowchart node."
    )
    test = ast_node_to_chart_node(node=node.test, **kwargs)
    if isinstance(test, CallNode):
        if_node = DecisionNode(
            name=f"check_{test.name}",
            label=f"check returns of {test.name} is True",
            #    parent_uuid=kwargs.get("parent_uuid")
        )
        test.next = if_node
    else:
        if_node = test
    if_node.true = ast_nodes_to_chart_node(nodes=node.body, **kwargs)
    if_node.false = ast_nodes_to_chart_node(nodes=node.orelse, **kwargs)
    return _create_warpper_node(
        # TODO: better name and label
        name="if",
        label=f"if {ast.unparse(node.test)}",
        start=test,
        type=FlowchartType.IF,
        # parent_uuid=kwargs.get("parent_uuid")
    )


def ast_ifexp_to_chart_node(node: ast.IfExp, **kwargs: Any) -> ActionNode:
    """Converts an AST ifexp node to a Flowchart node.

    The main difference between if and ifexp is that ifexp's body and orelse can
    only hold a single node but if's are list of node."""

    assert isinstance(node, ast.IfExp), f"Node {node} is not an ifexp node."
    logger.info(
        f"Converting ifexp node `{ast.unparse(node)[:10]}` to a Flowchart node."
    )

    test = ast_node_to_chart_node(node=node.test, **kwargs)
    if isinstance(test, CallNode):
        if_node = DecisionNode(
            name=f"check_{test.name}",
            label=f"check returns of {test.name} is True",
        )
        test.next = if_node
    else:
        if_node = test
    if_node.true = ast_node_to_chart_node(node=node.body, **kwargs)
    if_node.false = ast_node_to_chart_node(node=node.orelse, **kwargs)
    return _create_warpper_node(
        # TODO: better name and label
        name="if expr",
        label=f"if {ast.unparse(node.test)}",
        start=test,
        type=FlowchartType.IF,
    )


def ast_try_to_chart_node(node: ast.Try, **kwargs: Any) -> BaseFlowchartNode:
    """Converts an AST try node to a Flowchart node."""
    assert isinstance(node, ast.Try), f"Node {node} is not a try node."
    logger.info(
        f"Converting try node `{ast.unparse(node)[:10]}` to a Flowchart node."
    )


def ast_for_to_chart_node(node: ast.For, **kwargs: Any) -> LoopNode:
    """Converts an AST for node to a Flowchart node."""
    assert isinstance(node, ast.For), f"Node {node} is not a for node."
    logger.info(
        f"Converting for node `{ast.unparse(node)[:10]}` to a Flowchart node."
    )


def ast_asyncfor_to_chart_node(node: ast.AsyncFor, **kwargs: Any) -> LoopNode:
    """Converts an AST asyncfor node to a Flowchart node."""
    assert isinstance(node, ast.AsyncFor), f"Node {node} is not an asyncfor node."
    logger.info(
        f"Converting asyncfor node `{ast.unparse(node)[:10]}` to a Flowchart node."
    )


def ast_while_to_chart_node(node: ast.While, **kwargs: Any) -> LoopNode:
    """Converts an AST while node to a Flowchart node."""
    assert isinstance(node, ast.While), f"Node {node} is not a while node."
    logger.info(
        f"Converting while node `{ast.unparse(node)[:10]}` to a Flowchart node."
    )


def ast_with_to_chart_node(node: ast.With, **kwargs: Any) -> BaseFlowchartNode:
    """Converts an AST with node to a Flowchart node."""
    assert isinstance(node, ast.With), f"Node {node} is not a with node."
    logger.info(
        f"Converting with node `{ast.unparse(node)[:10]}` to a Flowchart node."
    )


def ast_asyncwith_to_chart_node(
    node: ast.AsyncWith, **kwargs: Any
) -> BaseFlowchartNode:
    """Converts an AST asyncwith node to a Flowchart node."""
    assert isinstance(node, ast.AsyncWith), f"Node {node} is not an asyncwith node."
    logger.info(
        f"Converting asyncwith node `{ast.unparse(node)[:10]}` to a Flowchart node."
    )


def ast_withitem_to_chart_node(
    node: ast.withitem, **kwargs: Any
) -> BaseFlowchartNode:
    """Converts an AST withitem node to a Flowchart node."""
    assert isinstance(node, ast.withitem), f"Node {node} is not a withitem node."
    logger.info(
        f"Converting withitem node `{ast.unparse(node)[:10]}` to a Flowchart node."
    )


def simplify_node_inplace(
    node: ast.AST, chart_nodes: list[BaseFlowchartNode]
) -> None:
    """Simplifies the call and control related code in the node."""
    # TODO: We can just replace the call or control with a variable and add a
    # comment showing what the variable does.
    pass


def simple_code_to_chart_node(
    *,
    nodes: list[ast.AST],
    node_calls: list[URI],
    # parent_uuid: str,
) -> ActionNode:
    """Calls GPT to generate a linear flowchart of the input nodes.
    The inputs nodes shouldn't have any control or call logic in it."""
    code = ast.unparse(ast.Module(body=nodes))
    return ActionNode(
        name="non_call_non_control",
        label=f"`{code[:10]}`",
        # parent_uuid=parent_uuid,
    )


def ast_nodes_to_chart_node(
    *,
    nodes: list[ast.AST],
    node_calls: list[URI],
    simplify_threshold: int = 50,
    expand_threshold: int = 50,
) -> ActionNode | None:
    """Converts a list of AST nodes to a Flowchart node."""
    if not nodes:
        return None

    logger.info(f"Converting {len(nodes)} nodes to a Flowchart node.")
    kwargs = dict(
        node_calls=node_calls,
        simplify_threshold=simplify_threshold,
        expand_threshold=expand_threshold,
    )

    chart_nodes = []
    current = []
    for node in nodes:
        if should_expand(node, calls=node_calls):
            if current:
                chart_nodes.append(simple_code_to_chart_node(node=current, **kwargs))
                current = []
            chart_nodes.append(ast_node_to_chart_node(node=node, **kwargs))
        else:
            # TODO: Cut the group if the length is too long.
            current.append(node)

    if current:
        chart_nodes.append(simple_code_to_chart_node(node=current, **kwargs))

    return _create_warpper_node(
        name="root",
        label="root",
        start=connect_nodes(chart_nodes),
        type=FlowchartType.LINEAR,
    )


def _ast_node_to_chart_nodes(
    *,
    node: ast.AST,
    node_calls: list[URI],
    simplify_threshold: int = 50,
    expand_threshold: int = 50,
) -> list[BaseFlowchartNode]:
    """Convert a AST node to a list of Flowchart nodes.
    NOTE: The return list might be empty if there is no call or control logic in it."""

    if not isinstance(node, ast.AST):
        raise ValueError(f"Node {node} is not an AST node.")

    kwargs = dict(
        node_calls=node_calls,
        simplify_threshold=simplify_threshold,
        expand_threshold=expand_threshold,
    )
    if is_first_party_call(node, calls=node_calls):
        return [ast_call_to_chart_node(node=node, **kwargs)]
    if is_control_flow(node, threshold=expand_threshold):
        return [ast_control_to_chart_node(node=node, **kwargs)]

    chart_nodes = []
    # NOTE: Be careful the order must match the execution order of a node.
    # NOTE: If we want to replace the node to simplify the code, we need to use iter_fields.
    for child in ast.iter_child_nodes(node):
        # NOTE: We need node calls for each child node, but the child nodes are
        # just part of the function being processed, so passing the full list of
        # the function calls is enough. We can make this more robust by passing
        # only function calls on these lines or even further, see how pycg works
        # and connect the function calls to the ast nodes directly.
        new_nodes = _ast_node_to_chart_nodes(node=child, **kwargs)
        chart_nodes.extend(new_nodes)
        if get_str_length(ast.unparse(child)) >= simplify_threshold:
            simplify_node_inplace(child, chart_nodes=new_nodes)

    return chart_nodes


def ast_node_to_chart_node(
    *,
    node: ast.AST,
    node_calls: list[URI],
    simplify_threshold: int = 50,
    expand_threshold: int = 50,
) -> ActionNode:
    """Converts an any type AST node to a Flowchart node."""
    chart_nodes = _ast_node_to_chart_nodes(
        node=node,
        node_calls=node_calls,
        simplify_threshold=simplify_threshold,
        expand_threshold=expand_threshold,
    )
    if not chart_nodes:
        logger.debug(f"node {type(node)} doesn't have any call/control logic in it.")
        assert not should_expand(node, calls=node_calls)

    if len(chart_nodes) == 1:
        return chart_nodes[0]

    # TODO: the above process should also simplified the code of the passed node.
    # Which mean the call and control logic should be simplified in
    # the code. Here, should generate a node showing what the simplified code does.
    # This is the same as the ones in the `ast_call_to_chart_node` function.
    chart_nodes.append(
        ActionNode(
            name="glue",
            label=f"non-call and non-control in `{ast.unparse(node)[:10]}`",
        )
    )
    return _create_warpper_node(
        # TODO: generate name and label using GPT
        name=ast.unparse(node),
        label=f"Wrapper for ast node {ast.unparse(node)}",
        start=connect_nodes(chart_nodes),
        type=FlowchartType.LINEAR,
    )


def ast_call_to_chart_node(
    *,
    node: ast.Call,
    node_calls: list[URI],
    simplify_threshold: int = 50,
    expand_threshold: int = 50,
) -> CallNode | None:
    """Converts an AST call node to a Flowchart node."""
    assert isinstance(node, ast.Call), f"Node {node} is not a call node."
    logger.info(
        f"Converting call node {ast.unparse(node.func)}() to a Flowchart node."
    )

    # node_calls = nodes[target_uri].calls
    call_uri = call_func_info(node, node_calls)

    call_node = CallNode(
        name=ast.unparse(node.func),
        func_uri=call_uri,
        # TODO: Generate label using GPT following `call xxx with xxx input and
        # output xxx.` Here we might use the simplified code of the node, so
        # need to add that logic to this function.
        label=f"Call {ast.unparse(node.func)} with args",
    )

    kwargs = dict(
        node_calls=node_calls,
        # parent_uuid=call_node.uuid,
        simplify_threshold=simplify_threshold,
        expand_threshold=expand_threshold,
    )

    chart_nodes = []
    # NOTE: We do should_expand check here because we don't want to generate a
    # single node for non-call nor control flow nodes. Also, we do not do the
    # check in the ast_node_to_chart_node function because we want a single type
    # return as a clear interface.
    for arg in node.args:
        if should_expand(arg, calls=node_calls):
            chart_nodes.append(ast_node_to_chart_node(node=arg, **kwargs))

    for keyword in node.keywords:
        if should_expand(keyword.value, calls=node_calls):
            chart_nodes.append(ast_node_to_chart_node(node=keyword.value, **kwargs))

    if not chart_nodes:
        return call_node

    chart_nodes.append(call_node)
    wrapper = _create_warpper_node(
        # TODO: generate name and label using GPT
        name=ast.unparse(node.func),
        label=f"generate args and call {ast.unparse(node.func)}",
        start=connect_nodes(chart_nodes),
        type=FlowchartType.LINEAR,
    )
    return wrapper


real_func_code = """
logger.typewriter_log(
    "NEXT ACTION: ",
    Fore.CYAN,
    f"COMMAND = {Fore.CYAN}{remove_ansi_escape(command_name)}{Style.RESET_ALL}  "
    f"ARGUMENTS = {Fore.CYAN}{command_args}{Style.RESET_ALL}",
)
"""
real_func_calls = [
    "/autogpt.logs.logger/Logger.typewriter_log",
    "/autogpt.app.main/remove_ansi_escape",
    "",
]

test_func_code = """
if test_func():
    root_func(
        1,
        func_1(
            func_1_1(),
            e=3,
        ),  # test function call arg
        a=2,
        c=func_2(
            4,
            g=1 if func_2_1() else 0,
        ),  # test function call kwarg
    )
"""
test_func_calls = [
    "/autogpt.app.main/test_func",
    "/autogpt.app.main/root_func",
    "/autogpt.app.main/func_1",
    "/autogpt.app.main/func_2",
    "/autogpt.app.main/func_1_1",
    "/autogpt.app.main/func_2_1",
    "",
]

call_test_inputs = dict(
    node=ast.parse(test_func_code).body[0].body,
    node_calls=test_func_calls,
    # parent_uuid=f"root_{uuid4()}",
)
node_test_inputs = dict(
    node=ast.parse(test_func_code).body[0],
    node_calls=test_func_calls,
    # parent_uuid=f"root_{uuid4()}",
)
# get = ast_call_to_chart_node(**call_test_inputs, expand_threshold=0)
get = ast_node_to_chart_node(**node_test_inputs, expand_threshold=0)
flowchart_node_to_dot_graph(
    get, config=FlowchartConfig(expand_all=True, show_cluster=True)
)
wrapper = _create_warpper_node(
    name="root",
    label="root",
    start=get,
    type=FlowchartType.LINEAR,
)
wrapper.subchart.to_file(output_path / "flowchart.json")
pass
# %%
