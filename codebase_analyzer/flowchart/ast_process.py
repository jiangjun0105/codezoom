# %%
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

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
    EndNode,
    ExitNode,
    Flowchart,
    FlowchartConfig,
    FlowchartType,
    FunctionNode,
    LoopNode,
    StartNode,
    flowchart_node_to_dot_graph,
)
from codebase_analyzer.flowchart.process import ask_gpt

# %%
from codebase_analyzer.tools.context import get_str_length


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


def connect_nodes(nodes: list[BaseFlowchartNode]) -> BaseFlowchartNode | None:
    """Connects a list of nodes and return the start node."""
    if not nodes:
        return None
    start = before = nodes[0]
    for node in nodes[1:]:
        before.next = node
        before = node
    return start


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


class AstChartNodeConverter(BaseModel):
    """Converts AST nodes to Flowchart nodes."""

    code_nodes: dict[URI, CodeNode] = Field(
        ..., description="Code nodes of the whole repo."
    )
    func_nodes: dict[URI, FunctionNode] = Field(default_factory=dict)
    simplify_threshold: int = Field(default=50)
    expand_threshold: int = Field(default=50)

    def call_func_info(self, node: ast.Call, uri: URI) -> str:
        """Gets the semantic information of the inputs and returns of a call node.
        This is also for providing LLM more context information."""
        call_uri = _get_first_party_call(node.func, known_calls=self.get_calls(uri))
        if not call_uri:
            return None

        # TODO: add input and return info to the function nodes. For now we use
        # summary for experimenting purpose.
        # summary = nodes[call_uri].summary
        return call_uri

    def get_calls(self, uri: URI) -> list[URI]:
        """Gets the calls of a function."""
        return self.code_nodes[uri].calls

    def ast_control_to_chart_node(self, node: ast.AST, uri: URI) -> ActionNode:
        """Converts an AST control flow node to a Flowchart node.

        NOTE: kwargs are the same as ast_node_to_chart_node, it's not a good practice but
        here every function's kwargs are the same so we used this way."""
        match type(node):
            # If group
            case ast.If:
                return self.ast_if_to_chart_node(node, uri=uri)
            case ast.IfExp:
                return self.ast_ifexp_to_chart_node(node, uri=uri)
            case ast.Try:
                return self.ast_try_to_chart_node(node, uri=uri)
            # Loop group
            case ast.For:
                return self.ast_try_to_chart_node(node, uri=uri)
            case ast.AsyncFor:
                return self.ast_try_to_chart_node(node, uri=uri)
            case ast.While:
                return self.ast_try_to_chart_node(node, uri=uri)
            # With group
            case ast.With:
                return self.ast_try_to_chart_node(node, uri=uri)
            case ast.AsyncWith:
                return self.ast_try_to_chart_node(node, uri=uri)
            case ast.withitem:
                return self.ast_withitem_to_chart_node(node, uri=uri)
            case _:
                raise ValueError(f"Node {node} is not a control flow node.")

    def _create_warpper_node(
        self,
        name: str,
        label: str,
        start: BaseFlowchartNode,
        type: FlowchartType,  # parent_uuid: str
    ) -> ActionNode:
        """Creates a wrapper node for a subchart. For now we only create ActionNode."""
        wrapper = ActionNode.with_subchart(
            name=name,
            label=label,
            chart_start=start,
            chart_type=type,
        )
        return wrapper

    def ast_if_to_chart_node(self, node: ast.If, uri: URI) -> ActionNode:
        """Converts an AST if node to a Flowchart node."""
        assert isinstance(node, ast.If), f"Node {node} is not an if node."

        logger.info(
            f"Converting if node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )
        test = self.ast_node_to_chart_node(node=node.test, uri=uri)
        if isinstance(test, CallNode):
            if_node = DecisionNode(
                name=f"check_{test.name}",
                label=f"check returns of {test.name} is True",
            )
            # NOTE: We only separate the call node and the if node when calling functions.
            test.next = if_node
        else:
            if_node = DecisionNode(
                name=f"check_{test.name}",
                label=f"check if {test.label} is True",
            )
        if_node.true = self.ast_nodes_to_chart_node(nodes=node.body, uri=uri)
        if_node.false = self.ast_nodes_to_chart_node(nodes=node.orelse, uri=uri)
        return self._create_warpper_node(
            # TODO: better name and label
            name="if",
            label=f"if {ast.unparse(node.test)}",
            start=if_node,
            type=FlowchartType.IF,
            # parent_uuid=kwargs.get("parent_uuid")
        )

    def ast_ifexp_to_chart_node(self, node: ast.IfExp, uri: URI) -> ActionNode:
        """Converts an AST ifexp node to a Flowchart node.

        The main difference between if and ifexp is that ifexp's body and orelse can
        only hold a single node but if's are list of node."""

        assert isinstance(node, ast.IfExp), f"Node {node} is not an ifexp node."
        logger.info(
            f"Converting ifexp node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )

        test = self.ast_node_to_chart_node(node=node.test, uri=uri)
        if isinstance(test, CallNode):
            if_node = DecisionNode(
                name=f"check_{test.name}",
                label=f"check returns of {test.name} is True",
            )
            test.next = if_node
        else:
            if_node = test
        if_node.true = self.ast_node_to_chart_node(node=node.body, uri=uri)
        if_node.false = self.ast_node_to_chart_node(node=node.orelse, uri=uri)
        return self._create_warpper_node(
            # TODO: better name and label
            name="if expr",
            label=f"if {ast.unparse(node.test)}",
            start=test,
            type=FlowchartType.IF,
        )

    def ast_try_to_chart_node(self, node: ast.Try, uri: URI) -> BaseFlowchartNode:
        """Converts an AST try node to a Flowchart node."""
        assert isinstance(node, ast.Try), f"Node {node} is not a try node."
        logger.info(
            f"Converting try node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )

    def ast_for_to_chart_node(self, node: ast.For, uri: URI) -> LoopNode:
        """Converts an AST for node to a Flowchart node."""
        assert isinstance(node, ast.For), f"Node {node} is not a for node."
        logger.info(
            f"Converting for node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )

    def ast_asyncfor_to_chart_node(self, node: ast.AsyncFor, uri: URI) -> LoopNode:
        """Converts an AST asyncfor node to a Flowchart node."""
        assert isinstance(
            node, ast.AsyncFor
        ), f"Node {node} is not an asyncfor node."
        logger.info(
            f"Converting asyncfor node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )

    def ast_while_to_chart_node(self, node: ast.While, uri: URI) -> LoopNode:
        """Converts an AST while node to a Flowchart node."""
        assert isinstance(node, ast.While), f"Node {node} is not a while node."
        logger.info(
            f"Converting while node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )

    def ast_with_to_chart_node(self, node: ast.With, uri: URI) -> BaseFlowchartNode:
        """Converts an AST with node to a Flowchart node."""
        assert isinstance(node, ast.With), f"Node {node} is not a with node."
        logger.info(
            f"Converting with node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )

    def ast_asyncwith_to_chart_node(
        node: ast.AsyncWith, uri: URI
    ) -> BaseFlowchartNode:
        """Converts an AST asyncwith node to a Flowchart node."""
        assert isinstance(
            node, ast.AsyncWith
        ), f"Node {node} is not an asyncwith node."
        logger.info(
            f"Converting asyncwith node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )

    def ast_withitem_to_chart_node(
        node: ast.withitem, uri: URI
    ) -> BaseFlowchartNode:
        """Converts an AST withitem node to a Flowchart node."""
        assert isinstance(node, ast.withitem), f"Node {node} is not a withitem node."
        logger.info(
            f"Converting withitem node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )

    def simplify_node_inplace(
        self, node: ast.AST, chart_nodes: list[BaseFlowchartNode]
    ) -> None:
        """Simplifies the call and control related code in the node."""
        # TODO: We can just replace the call or control with a variable and add a
        # comment showing what the variable does.
        pass

    def simple_code_to_chart_node(
        self,
        *,
        nodes: list[ast.AST],
        uri: URI,
        # parent_uuid: str,
    ) -> ActionNode:
        """Calls GPT to generate a linear flowchart of the input nodes.
        The inputs nodes shouldn't have any control or call logic in it."""
        code = "\n".join(ast.unparse(node) for node in nodes)
        logger.debug(f"Converting simple code:\n{code}")

        return ActionNode(
            name="non_call_non_control",
            label=f"`{code[:30]}`",
            # parent_uuid=parent_uuid,
        )

    def ast_nodes_to_chart_node(
        self,
        *,
        nodes: list[ast.AST],
        uri: URI,
    ) -> ActionNode | None:
        """Converts a list of AST nodes to a Flowchart node."""
        if not nodes:
            return None

        logger.info(f"Converting {len(nodes)} nodes to a Flowchart node.")

        chart_nodes = []
        current = []
        for node in nodes:
            if should_expand(
                node, calls=self.get_calls(uri), threshold=self.expand_threshold
            ):
                if current:
                    chart_nodes.append(
                        self.simple_code_to_chart_node(node=current, uri=uri)
                    )
                    current = []
                chart_nodes.append(self.ast_node_to_chart_node(node=node, uri=uri))
            else:
                # TODO: Cut the group if the length is too long.
                current.append(node)

        if current:
            chart_nodes.append(
                self.simple_code_to_chart_node(nodes=current, uri=uri)
            )

        if len(chart_nodes) == 1:
            return chart_nodes[0]

        # TODO: not just roots
        wrapper = self._create_warpper_node(
            name="root",
            label="root",
            start=connect_nodes(chart_nodes),
            type=FlowchartType.LINEAR,
        )
        return wrapper

    def _ast_node_to_chart_nodes(
        self,
        *,
        node: ast.AST,
        uri: URI,
    ) -> list[BaseFlowchartNode]:
        """Convert a AST node to a list of Flowchart nodes.
        NOTE: The return list might be empty if there is no call or control logic in it."""

        if not isinstance(node, ast.AST):
            raise ValueError(f"Node {node} is not an AST node.")

        if is_first_party_call(node, calls=self.get_calls(uri)):
            return [self.ast_call_to_chart_node(node=node, uri=uri)]
        if is_control_flow(node, threshold=self.expand_threshold):
            return [self.ast_control_to_chart_node(node=node, uri=uri)]

        chart_nodes = []
        # NOTE: Be careful the order must match the execution order of a node.
        # NOTE: If we want to replace the node to simplify the code, we need to use iter_fields.
        for child in ast.iter_child_nodes(node):
            # NOTE: We need node calls for each child node, but the child nodes are
            # just part of the function being processed, so passing the full list of
            # the function calls is enough. We can make this more robust by passing
            # only function calls on these lines or even further, see how pycg works
            # and connect the function calls to the ast nodes directly.
            new_nodes = self._ast_node_to_chart_nodes(node=child, uri=uri)
            chart_nodes.extend(new_nodes)
            if get_str_length(ast.unparse(child)) >= self.simplify_threshold:
                self.simplify_node_inplace(child, chart_nodes=new_nodes)

        return chart_nodes

    def ast_node_to_chart_node(
        self,
        *,
        node: ast.AST,
        uri: URI,
    ) -> ActionNode:
        """Converts an any type AST node to a Flowchart node."""
        logger.info(f"Convert node {type(node)} to a Flowchart node.")
        logger.debug(f"Node code:\n{ast.unparse(node)}")

        chart_nodes = self._ast_node_to_chart_nodes(
            node=node,
            uri=uri,
        )
        if not chart_nodes:
            logger.debug(
                f"node {type(node)} doesn't have any call/control logic in it."
            )
            assert not should_expand(node, calls=self.get_calls(uri))

        if len(chart_nodes) == 1:
            # A single call or control node.
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
        if isinstance(node, ast.Expr):
            # TODO: Actually get the evaluation results of the expression.
            logger.debug(f"Get evaluation of {ast.unparse(node)}")

        return self._create_warpper_node(
            # TODO: generate name and label using GPT
            name=ast.unparse(node),
            label=f"Wrapper for ast node {ast.unparse(node)}",
            start=connect_nodes(chart_nodes),
            type=FlowchartType.LINEAR,
        )

    def ast_call_to_chart_node(
        self,
        *,
        node: ast.Call,
        uri: URI,
    ) -> CallNode | None:
        """Converts an AST call node to a Flowchart node."""
        assert isinstance(node, ast.Call), f"Node {node} is not a call node."
        logger.info(
            f"Converting call node {ast.unparse(node.func)}() to a Flowchart node."
        )

        call_uri = self.call_func_info(node, uri=uri)
        if not call_uri:
            raise ValueError(f"Unknown call {ast.unparse(node.func)}.")

        if call_uri not in self.func_nodes:
            # TODO: Function code will be parsed as a module, so we need to get
            # the body[0]. Maybe we can have a nicer way to do it if we can fuse
            # the code_info generation and this process.
            func_ast = ast.parse(self.code_nodes[call_uri].code).body[0]
            self.ast_funcdef_to_chart(node=func_ast, uri=call_uri)

        func_node = self.func_nodes[call_uri]
        if func_node is None:
            logger.warning(
                f"Call of {call_uri} has circular dependencies, create a dummy one."
            )
            # TODO: Do a simple parse to get the inputs and returns.
            func_node = FunctionNode(
                name=ast.unparse(node.func),
                label=f"Call {ast.unparse(node.func)} with args",
                func_uri=call_uri,
                start=StartNode(name="dummy", inputs=[]),
                body=ActionNode(name="dummy", label="", subchart=None),
                end=EndNode(name="dummy", returns=[]),
            )

        # TODO: Make this look nicer.
        call_uuid = f"{uri}_{uuid4()}"
        call_node = CallNode(
            name=ast.unparse(node.func),
            func_uri=call_uri,
            uuid=call_uuid,
            # TODO: Generate label using GPT following `call xxx with xxx input and
            # output xxx.` Here we might use the simplified code of the node, so
            # need to add that logic to this function.
            label=f"Call {ast.unparse(node.func)} with args",
            # TODO: associate the input annotations with the ast call node's
            # args to generate a summary of the actual input in this call,
            # especially for args whose meaning is unknown. set it to
            # call_node.inputs
            inputs=func_node.inputs,
            returns=func_node.returns,
            subchart=func_node.get_process_chart(uuid=call_uuid),
        )
        assert call_node.subchart.uuid == call_node.uuid

        chart_nodes = []
        # NOTE: We do should_expand check here because we don't want to generate a
        # single node for non-call nor control flow nodes. Also, we do not do the
        # check in the ast_node_to_chart_node function because we want a single type
        # return as a clear interface.
        for arg in node.args:
            if should_expand(arg, calls=self.get_calls(uri)):
                chart_nodes.append(self.ast_node_to_chart_node(node=arg, uri=uri))

        for keyword in node.keywords:
            if should_expand(keyword.value, calls=self.get_calls(uri)):
                chart_nodes.append(
                    self.ast_node_to_chart_node(node=keyword.value, uri=uri)
                )

        if not chart_nodes:
            return call_node

        chart_nodes.append(call_node)
        wrapper = self._create_warpper_node(
            # TODO: generate name and label using GPT
            name=ast.unparse(node.func),
            label=f"generate args and call {ast.unparse(node.func)}",
            start=connect_nodes(chart_nodes),
            type=FlowchartType.LINEAR,
        )
        return wrapper

    def node_name(
        self, node: ast.AST, uri: URI, base_lineno: int = 0, note: str | None = None
    ) -> str:
        """Gets node names in format of `/package.subpkg.module/function:lineno:note`."""
        note = note or node.__class__.__name__
        return f"{uri}:{node.lineno+base_lineno}:{note}"

    def ast_funcdef_to_chart(self, node: ast.FunctionDef, uri: URI) -> FunctionNode:
        """Converts an AST function definition node to a Flowchart."""
        assert isinstance(node, ast.FunctionDef), f"Node {node} is not a function."
        if uri in self.func_nodes:
            logger.debug(f"Function {node.name} is being processed. Loop detected.")
            return None

        logger.info(
            f"Converting function `{ast.unparse(node)[:50]}` to a Flowchart."
        )
        # NOTE: Hold the place to prevent circular dependencies.
        self.func_nodes[uri] = None

        # TODO: Parse inputs and decorations.

        start = StartNode(
            name=self.node_name(node, uri=uri),
            uuid=self.node_name(node, uri=uri),
            label=f"Function {node.name}",
            inputs=[],
        )

        # TODO: Collect ReturnNodes while processing body.
        body = self.ast_nodes_to_chart_node(nodes=node.body, uri=uri)

        # TODO: Summarize all returns and add them to the end node.
        end = EndNode(
            name=self.node_name(node, uri=uri, note="end"),
            uuid=self.node_name(node, uri=uri, note="end"),
            label=f"End of Function {node.name}",
        )

        func_node = FunctionNode.with_subchart(
            name=self.node_name(node, uri=uri, note="FuncDef"),
            uuid=self.node_name(node, uri=uri, note="FuncDef"),
            label=f"Function {node.name}",
            func_uri=uri,
            start=start,
            body=body,
            end=end,
            chart_start=connect_nodes([start, body, end]),
        )
        self.func_nodes[uri] = func_node
        return func_node


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
def test_func():
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
    return 1
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
test_func_uri = "/autogpt.app.main/test_func"
test_code_nodes = {
    test_func_uri: CodeNode(
        uri="/autogpt.app.main/test_func",
        code=test_func_code,
        calls=test_func_calls,
        type="function",
        level=1,
    ),
}

call_test_inputs = dict(
    node=ast.parse(test_func_code).body[0].body,
    uri=test_func_uri,
    # parent_uuid=f"root_{uuid4()}",
)
node_test_inputs = dict(
    node=ast.parse(test_func_code).body[0],
    uri=test_func_uri,
    # parent_uuid=f"root_{uuid4()}",
)
# get = ast_call_to_chart_node(**call_test_inputs, expand_threshold=0)
converter = AstChartNodeConverter(
    code_nodes=nodes,
    simplify_threshold=0,
    expand_threshold=0,
)
get = converter.ast_funcdef_to_chart(
    node=ast.parse(nodes[debug_uri].code).body[0],
    uri=debug_uri,
)
flowchart_node_to_dot_graph(
    get, config=FlowchartConfig(expand_all=True, show_cluster=True)
)
# wrapper = converter._create_warpper_node(
#     name="root",
#     label="root",
#     start=get,
#     type=FlowchartType.LINEAR,
# )
get.subchart.to_file(output_path / "flowchart.json")
pass
# %%
