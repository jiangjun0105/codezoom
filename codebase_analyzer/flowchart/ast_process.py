# %%
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field, root_validator

from codebase_analyzer.flowchart.node import (
    ActionNode,
    BaseFlowchartNode,
    CallNode,
    DecisionNode,
    DefineNode,
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
from codebase_analyzer.flowchart.process import generate_by_chain
from codebase_analyzer.flowchart.prompt import PROCESS_PROMPT_SET, REFINE_TEXT_PROMPT
from codebase_analyzer.flowchart.utils import _output_path
from codebase_analyzer.parser.deftree import CodeInfo, CodeNode
from codebase_analyzer.parser.uri import URI, Uri, uri_to_path
from codebase_analyzer.tools.context import get_str_length

SUMMARIZE_SYSTEM = """Generate one sentence summary for the code.
"""


SIMPLIFIED_TAG = "simplified"


class ContextPair(BaseModel):
    """A pair of context nodes."""

    get_ctx: ActionNode | CallNode
    enter: ActionNode
    exit: ActionNode

    @property
    def start(self) -> ActionNode | CallNode:
        return self.get_ctx if isinstance(self.get_ctx, CallNode) else self.enter


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


def is_docstring(node: ast.AST) -> bool:
    """Check if the given node is a docstring."""
    return isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant))


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
        if not known_call:
            continue
        known_call_func = Uri.from_fasten_uri(known_call).function
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
    """Returns True if the node is a control flow node and longer than threshold."""
    # TODO: get the list based on python version. ast.TryStar is added in 3.11
    # TODO: ast.comprehension might also need to be added.
    if isinstance(
        node,
        (
            ast.If,
            ast.IfExp,
            ast.For,
            ast.AsyncFor,
            # ast.comprehension,
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
    node_uuids: set[str] = Field(default_factory=set)
    # FIXME: for now we use this to save the calls of the nested functions.
    # In long term, we should use namspace dict to handle this.
    nested_func: dict[URI, list[URI]] = Field(default_factory=dict)
    simplify_threshold: int = Field(default=50)
    expand_threshold: int = Field(default=50)

    call_api: bool = Field(default=False)
    dump_dir: Path = Field(default=Path(__file__).parent / "convert_dump")

    def save_to_debug_file(self, text: str) -> None:
        """Saves the input text to a debug file."""
        # TODO: find a better way to do it.
        with open(Path(__file__).parent / "debug.md", "a+") as f:
            f.write(text)

    def call_func_info(self, node: ast.Call, uri: URI) -> str:
        """Gets the semantic information of the inputs and returns of a call node.
        This is also for providing LLM more context information."""
        called_uri = _get_first_party_call(
            node.func, known_calls=self.get_calls(uri)
        )
        if not called_uri:
            return None

        # TODO: add input and return info to the function nodes. For now we use
        # summary for experimenting purpose.
        # summary = nodes[called_uri].summary
        return called_uri

    def get_calls(self, uri: URI) -> list[URI]:
        """Gets the calls of a function."""
        if uri in self.nested_func:
            return self.nested_func[uri]
        return self.code_nodes[uri].calls

    def add_func_node(self, uri: URI, node: BaseFlowchartNode) -> None:
        """Adds a function node to the func_nodes dict."""
        if self.func_nodes.get(uri) is None:
            self.func_nodes[uri] = node
        else:
            raise ValueError(f"Function node {uri} already exists.")

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
            # case ast.TryStar:
            #     return self.ast_try_to_chart_node(node, uri=uri)
            # Loop group
            case ast.For:
                return self.ast_for_to_chart_node(node, uri=uri)
            case ast.AsyncFor:
                return self.ast_asyncfor_to_chart_node(node, uri=uri)
            # TODO: handle comprehension for each type.
            # case ast.comprehension:
            #     return self.ast_comp_to_chart_node(node, uri=uri)
            case ast.While:
                return self.ast_while_to_chart_node(node, uri=uri)
            # With group
            case ast.With:
                return self.ast_with_to_chart_node(node, uri=uri)
            case ast.AsyncWith:
                return self.ast_asyncwith_to_chart_node(node, uri=uri)
            case _:
                raise ValueError(f"Node {node} is not a control flow node.")

    def _create_wrapper_node(
        self,
        name: str,
        label: str,
        start: BaseFlowchartNode,
        type: FlowchartType,  # parent_uuid: str
    ) -> ActionNode:
        """Creates a wrapper node for a subchart. For now we only create ActionNode."""
        # NOTE: Abondoned for now. See if we need it later when using GPT.
        pass

    def _process_if_clause(
        self, test_node: ast.AST, uri: URI
    ) -> tuple[BaseFlowchartNode, DecisionNode]:
        """Processes clause `if xxx`, which generates:

        (test_call_node) -> if_node
        """

        test = self.ast_node_to_chart_node(node=test_node, uri=uri)
        if_node = DecisionNode(
            name=f"check_{test.name}",
            **self.uuid_and_label(
                node=test_node,
                uri=uri,
                suffix="check_value",
                draft=f"Check if condition `{test.label}` is True",
            ),
        )
        if isinstance(test, CallNode) or test.subchart is not None:
            # NOTE: We only separate the call node and the if node when calling functions.
            test.next = if_node
            return test, if_node
        return if_node, if_node

    def _ast_if_to_chart_node(
        self, node: ast.If | ast.IfExp, uri: URI
    ) -> ActionNode:
        logger.info(
            f"Converting if node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )
        chart_start, if_node = self._process_if_clause(test_node=node.test, uri=uri)

        if isinstance(node.body, list):  # ast.If
            if_node.true = self.ast_nodes_to_chart_node(nodes=node.body, uri=uri)
            if_node.false = self.ast_nodes_to_chart_node(nodes=node.orelse, uri=uri)
        else:  # ast.IfExp
            if_node.true = self.ast_node_to_chart_node(node=node.body, uri=uri)
            if_node.false = self.ast_node_to_chart_node(node=node.orelse, uri=uri)

        uuid = self.node_uuid(node=node, uri=uri, suffix="if_wrapper")
        wrapper = ActionNode.with_subchart(
            name="if",
            uuid=uuid,
            # TODO: Template for summarizeing if node.
            label=self.label_from_labels(
                nodes=[if_node, if_node.true, if_node.false]
            ),
            chart_start=chart_start,
        )
        return wrapper

    def ast_if_to_chart_node(self, node: ast.If, uri: URI) -> ActionNode:
        """Converts an AST if node to a Flowchart node."""
        assert isinstance(node, ast.If), f"Node {node} is not an if node."
        return self._ast_if_to_chart_node(node=node, uri=uri)

    def ast_ifexp_to_chart_node(self, node: ast.IfExp, uri: URI) -> ActionNode:
        """Converts an AST ifexp node to a Flowchart node.

        The main difference between if and ifexp is that ifexp's body and orelse can
        only hold a single node but if's are list of node."""

        assert isinstance(node, ast.IfExp), f"Node {node} is not an ifexp node."
        return self._ast_if_to_chart_node(node=node, uri=uri)

    def ast_try_to_chart_node(self, node: ast.Try, uri: URI) -> BaseFlowchartNode:
        """Converts an AST try node to a Flowchart node."""
        assert isinstance(node, ast.Try), f"Node {node} is not a try node."
        logger.info(
            f"Converting try node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )
        trybody = self.ast_nodes_to_chart_node(nodes=node.body, uri=uri)
        orelse = self.ast_nodes_to_chart_node(nodes=node.orelse, uri=uri)
        final = self.ast_nodes_to_chart_node(nodes=node.finalbody, uri=uri)

        excepts = []
        for handler in node.handlers:
            raised = ast.unparse(handler.type) if handler.type else "anhy exception"
            test = DecisionNode(
                name=f"check_{handler.name}",
                **self.uuid_and_label(
                    node=handler,
                    uri=uri,
                    suffix="except",
                    draft=f'check if exception "{raised}" is raised',
                ),
            )
            excepts.append(test)
            test.true = self.ast_nodes_to_chart_node(nodes=handler.body, uri=uri)
            if final:
                test.true.next = final

        assert len(excepts) > 0, "Try node must have at least one except node."
        trybody.next = excepts[0]
        for i in range(len(excepts) - 1):
            excepts[i].false = excepts[i + 1]

        if orelse:
            excepts[-1].false = orelse
            orelse.next = final

        uuid = self.node_uuid(node=node, uri=uri, suffix="try_wrapper")
        wrapper = ActionNode.with_subchart(
            name=f"try_{len(excepts)}_excepts",
            uuid=uuid,
            # TODO: summary template for try node.
            label=self.label_from_labels(
                nodes=[trybody, *excepts, orelse, final],
            ),
            chart_start=trybody,
            chart_type=FlowchartType.PROCESS,
        )
        return wrapper

    def ast_for_to_chart_node(self, node: ast.For, uri: URI) -> LoopNode:
        """Converts an AST for node to a Flowchart node."""
        assert isinstance(node, ast.For), f"Node {node} is not a for node."
        logger.info(
            f"Converting for node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )
        return self._ast_for_to_chart_node(node=node, uri=uri, loop_type="for")

    def _process_for_clause(
        self, node: ast.For, uri: URI, loop_type: str
    ) -> tuple[BaseFlowchartNode, BaseFlowchartNode, DecisionNode]:
        """Processes `for target in iter` clause, which generates:

        (func_call) -> fetch -> if_continue
        """
        assert hasattr(node, "iter"), f"Node {node} doesn't have iter."
        assert hasattr(node, "target"), f"Node {node} doesn't have target."

        target_label = ast.unparse(node.target)
        foriter = self.ast_node_to_chart_node(node=node.iter, uri=uri)
        uuid = self.node_uuid(node=node.target, uri=uri, suffix=f"{loop_type}_fetch")
        if isinstance(foriter, CallNode) or foriter.subchart is not None:
            fetch = ActionNode(
                name=f"{loop_type}_fetch_{target_label}",
                uuid=uuid,
                label=f"Fetch {target_label} from {foriter.label}",
                # label=self.label_from_code(ast.unparse(node), uuid=uuid),
            )
            foriter.next = fetch
        else:
            assert isinstance(foriter, ActionNode)
            assert foriter.subchart is None
            fetch = foriter
            fetch.label = f"Fetch {target_label} from {fetch.label}"

        if_continue = DecisionNode(
            name=f"{loop_type}_check_{target_label}",
            uuid=self.node_uuid(
                node=node.target, uri=uri, suffix=f"{loop_type}_check"
            ),
            label=f"If got unprocessed `{target_label}`",
        )
        fetch.next = if_continue
        return foriter, fetch, if_continue

    def _ast_for_to_chart_node(
        self, node: ast.For, uri: URI, loop_type: str
    ) -> LoopNode:
        target_label = ast.unparse(node.target)
        forbody = self.ast_nodes_to_chart_node(nodes=node.body, uri=uri)
        start, fetch, if_continue = self._process_for_clause(
            node=node, uri=uri, loop_type=loop_type
        )
        if_continue.true = forbody
        forbody.next = fetch

        self._process_loop_orelse(
            node=node,
            uri=uri,
            loop_type=loop_type,
            if_continue=if_continue,
            orelse_label=f"If all `{target_label}` are processed without break",
        )

        wrapper = ActionNode.with_subchart(
            name=f"{loop_type}_loop_{forbody.name}",
            uuid=self.node_uuid(node=node, uri=uri, suffix=f"{loop_type}_wrapper"),
            # TODO: summary template for for node.
            label=self.label_from_labels([fetch, if_continue, forbody]),
            chart_start=start,
            chart_type=FlowchartType.PROCESS,
        )
        return wrapper

    def _process_loop_orelse(
        self,
        node: ast.For | ast.AsyncFor | ast.While,
        uri: URI,
        if_continue: DecisionNode,
        loop_type: str,
        orelse_label: str,
    ) -> ActionNode | None:
        if not node.orelse:
            return None

        if_normal_end = DecisionNode(
            name=f"{loop_type}_check_loop_normal_finish",
            uuid=self.node_uuid(
                node=node.orelse[0], uri=uri, suffix=f"{loop_type}_else_check"
            ),
            label=orelse_label,
        )
        orelse = self.ast_nodes_to_chart_node(nodes=node.orelse, uri=uri)
        if_continue.false = if_normal_end
        if_normal_end.true = orelse
        return orelse

    def ast_asyncfor_to_chart_node(self, node: ast.AsyncFor, uri: URI) -> LoopNode:
        """Converts an AST asyncfor node to a Flowchart node."""
        assert isinstance(
            node, ast.AsyncFor
        ), f"Node {node} is not an asyncfor node."
        logger.info(
            f"Converting asyncfor node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )
        return self._ast_for_to_chart_node(node=node, uri=uri, loop_type="asyncfor")

    def ast_comp_to_chart_node(self, node: ast.AsyncFor, uri: URI) -> LoopNode:
        """Converts an AST asyncfor node to a Flowchart node."""
        assert isinstance(
            node, ast.comprehension
        ), f"Node {node} is not an comprehension node."
        logger.info(
            f"Converting comprehension node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )

        start, fetch, if_continue = self._process_for_clause(
            node=node, uri=uri, loop_type="comp"
        )
        # TODO: add the comprehension logic here.
        # We need to do it for ListComp, SetComp, DictComp, because the elt is
        # not included in the ast.comprehension node.

    def ast_while_to_chart_node(self, node: ast.While, uri: URI) -> LoopNode:
        """Converts an AST while node to a Flowchart node."""
        assert isinstance(node, ast.While), f"Node {node} is not a while node."
        logger.info(
            f"Converting while node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )
        chart_start, if_continue = self._process_if_clause(
            test_node=node.test, uri=uri
        )
        body = self.ast_nodes_to_chart_node(nodes=node.body, uri=uri)
        self._process_loop_orelse(
            node=node,
            uri=uri,
            loop_type="while",
            if_continue=if_continue,
            orelse_label="If the while loop is finished without break",
        )

        if_continue.true = body
        body.next = chart_start
        wrapper = ActionNode.with_subchart(
            name=f"while_loop_{body.name}",
            uuid=self.node_uuid(node=node, uri=uri, suffix="while_wrapper"),
            # TODO: Template for summarizing while node.
            label=self.label_from_labels([if_continue, body]),
            chart_start=chart_start,
            chart_type=FlowchartType.PROCESS,
        )
        return wrapper

    def ast_with_to_chart_node(self, node: ast.With, uri: URI) -> ActionNode:
        """Converts an AST with node to a Flowchart node."""
        assert isinstance(node, ast.With), f"Node {node} is not a with node."
        logger.info(
            f"Converting with node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )
        return self._ast_with_to_chart_node(node=node, uri=uri, type="with")

    def _ast_with_to_chart_node(
        self, node: ast.With, uri: URI, type: str
    ) -> ActionNode:
        contexts = [
            self._process_withitem(node=node, index=index, uri=uri)
            for index in range(len(node.items))
        ]
        assert len(contexts) > 0, "With node must have at least one context."
        body = self.ast_nodes_to_chart_node(nodes=node.body, uri=uri)
        for i, ctx in enumerate(contexts[:-1]):
            assert ctx.get_ctx.next == ctx.enter
            ctx.enter.next = contexts[i + 1].start
            contexts[i + 1].exit.next = ctx.exit
        contexts[-1].enter.next = body
        body.next = contexts[-1].exit

        wrapper = ActionNode.with_subchart(
            name=f"{type}_{len(contexts)}_contexts",
            uuid=self.node_uuid(node=node, uri=uri, suffix=f"{type}_wrapper"),
            # TODO: Template for summarizing with node.
            label=self.label_from_labels([ctx.get_ctx for ctx in contexts]),
            chart_start=contexts[0].start,
            chart_type=FlowchartType.PROCESS,
        )
        return wrapper

    def ast_asyncwith_to_chart_node(
        self, node: ast.AsyncWith, uri: URI
    ) -> ActionNode:
        """Converts an AST asyncwith node to a Flowchart node."""
        assert isinstance(
            node, ast.AsyncWith
        ), f"Node {node} is not an asyncwith node."
        logger.info(
            f"Converting asyncwith node `{ast.unparse(node)[:10]}` to a Flowchart node."
        )
        return self._ast_with_to_chart_node(node=node, uri=uri, type="async_with")

    def _process_withitem(
        self, node: ast.With | ast.AsyncWith, index: int, uri: URI
    ) -> ContextPair:
        """Converts an AST withitem node to a Flowchart node."""
        item = node.items[index]
        assert isinstance(item, ast.withitem), f"Node {item} is not a withitem node."
        logger.info(
            f"Converting withitem node `{ast.unparse(item)[:10]}` to a Flowchart node."
        )
        get_ctx = self.ast_node_to_chart_node(node=item.context_expr, uri=uri)
        if isinstance(get_ctx, CallNode):
            ctx = get_ctx.returns
        elif isinstance(get_ctx, ActionNode):
            # TODO: this means the context is an expression which evaluates as a
            # context manager object. So we need to extract the evaluted value
            # when processing expressions.
            ctx = get_ctx.label

        # TODO: match the context class and get the URI of the enter/exit functions.
        enter_uri = f"{ctx}.__enter__"
        exit_uri = f"{ctx}.__exit__"

        # TODO: create CallNode for enter and exit from the functions.
        # For now, we use ActionNode to represent the enter and exit.
        enter = ActionNode(
            name=f"enter_{get_ctx.name}",
            uuid=self.node_uuid(node=node, uri=uri, suffix=f"enter_{index}"),
            label=f"Call {enter_uri} to enter the context",
            # label=self.label_from_text(f"Call {enter_uri} to enter the context"),
        )
        get_ctx.next = enter
        exit = ActionNode(
            name=f"exit_{get_ctx.name}",
            uuid=self.node_uuid(node=node, uri=uri, suffix=f"exit_{index}"),
            label=f"Call {exit_uri} to exit the context",
            # label=self.label_from_text(f"Call {exit_uri} to exit the context"),
        )
        return ContextPair(get_ctx=get_ctx, enter=enter, exit=exit)

    def should_expand(
        self, node: ast.AST, uri: URI, threshold: int | None = None
    ) -> bool:
        threshold = threshold or self.expand_threshold
        return should_expand(node, calls=self.get_calls(uri), threshold=threshold)

    def should_simplify(self, node: ast.AST) -> bool:
        return get_str_length(ast.unparse(node)) >= self.simplify_threshold

    def simplify_node(self, node: ast.AST, chart_node: BaseFlowchartNode) -> None:
        """Simplifies the call and control related code in the node."""
        # TODO: We can just replace the call or control with a variable and add a
        # comment showing what the variable does.
        if self.should_simplify(node):
            common = dict(
                tag=SIMPLIFIED_TAG,
                id=chart_node.label.replace(" ", "_"),
                lineno=node.lineno,
                col_offset=node.col_offset,
                ctx=ast.Load(),
            )
            if isinstance(node, (ast.Call, ast.FunctionDef)):
                return ast.Name(**common)
            if is_control_flow(node, threshold=0):
                # NOTE: We might want to simplify control flows into a call ast node.
                return ast.Name(**common)
            raise ValueError(
                f"Cannot simplify {node=} which is not a call or control flow."
            )
        else:
            # So that we won't reprocess it.
            node.tag = SIMPLIFIED_TAG
            return node

    def nothing_to_do(self, node: ast.AST) -> bool:
        """Returns True if the node has nothing to convert any more."""
        if isinstance(node, ast.Expr):
            # Single line call is wrapped in an Expr node.
            node = node.value
        return hasattr(node, "tag") and node.tag == SIMPLIFIED_TAG

    def simple_code_to_chart_node(
        self,
        *,
        nodes: list[ast.AST],
        uri: URI,
    ) -> ActionNode:
        """Calls GPT to generate a linear flowchart of the input nodes.
        The inputs nodes shouldn't have any control or call logic in it."""
        code = "\n".join(ast.unparse(node) for node in nodes)
        logger.debug(f"Converting simple code:\n{code}")

        uuid = self.node_uuid(node=nodes[0], uri=uri, suffix="simple")
        action_node = ActionNode(
            name=f"simple_logic_{len(nodes)}_nodes",
            uuid=uuid,
            # label=f"`{code[:30]}`",
            label=self.label_from_code(code, uuid=uuid),
        )
        return action_node

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
        # TODO: Change this into namespace variable.
        for node in nodes:
            if self.should_expand(node, uri=uri):
                if current:
                    chart_nodes.append(
                        self.simple_code_to_chart_node(nodes=current, uri=uri)
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
        wrapper = ActionNode.with_subchart(
            name=f"process_of_{len(nodes)}_nodes",
            uuid=self.node_uuid(node=nodes[0], uri=uri, suffix="nodes_wrapper"),
            # TODO: template for summarizing a list of nodes.
            label=self.label_from_labels(chart_nodes),
            chart_start=connect_nodes(chart_nodes),
        )
        return wrapper

    def _ast_node_to_chart_nodes(
        self,
        *,
        node: ast.AST,
        uri: URI,
    ) -> tuple[list[BaseFlowchartNode], ast.AST]:
        """Convert a AST node to a list of Flowchart nodes.
        NOTE: The return list might be empty if there is no call or control logic in it."""

        if not isinstance(node, ast.AST):
            raise ValueError(f"Node {node} is not an AST node.")

        # TODO: Merge these 3 if statements into one.
        if isinstance(node, ast.FunctionDef):  # Nested function
            # TODO: Pass calls into it.
            nested_uri = f"{uri}.{node.name}"
            self.nested_func[nested_uri] = self.get_calls(uri)
            chart_node = self.ast_funcdef_to_chart_node(node=node, uri=nested_uri)
            simplified = self.simplify_node(node, chart_node=chart_node)
            return [chart_node], simplified

        if is_first_party_call(node, calls=self.get_calls(uri)):
            chart_node = self.ast_call_to_chart_node(node=node, uri=uri)
            simplified = self.simplify_node(node, chart_node=chart_node)
            return [chart_node], simplified

        # NOTE: No need to set threshold because if a control flow node is
        # passed into this function, it must have a first party call in it and
        # we want to expand it no matter how long it is.
        if is_control_flow(node, threshold=0):
            chart_node = self.ast_control_to_chart_node(node=node, uri=uri)
            simplified = self.simplify_node(node, chart_node=chart_node)
            return [chart_node], simplified

        chart_nodes = []
        simplified = copy.deepcopy(node)
        # NOTE: Be careful the order must match the execution order of a node.
        # NOTE: If we want to replace the node to simplify the code, we need to use iter_fields.
        for field, value in ast.iter_fields(simplified):
            # NOTE: We need node calls for each child node, but the child nodes are
            # just part of the function being processed, so passing the full list of
            # the function calls is enough. We can make this more robust by passing
            # only function calls on these lines or even further, see how pycg works
            # and connect the function calls to the ast nodes directly.
            if isinstance(value, list):
                new_asts = []
                for child in value:
                    if not isinstance(child, ast.AST):
                        continue
                    new_charts, new_ast = self._ast_node_to_chart_nodes(
                        node=child, uri=uri
                    )
                    chart_nodes.extend(new_charts)
                    new_asts.append(new_ast)
                setattr(simplified, field, new_asts)
            elif isinstance(value, ast.AST):
                new_charts, new_ast = self._ast_node_to_chart_nodes(
                    node=value, uri=uri
                )
                chart_nodes.extend(new_charts)
                setattr(simplified, field, new_ast)

        return chart_nodes, simplified

    def ast_node_to_chart_node(
        self,
        *,
        node: ast.AST,
        uri: URI,
    ) -> ActionNode:
        """Converts an any type AST node to a Flowchart node."""
        logger.info(f"Convert node {type(node)} to a Flowchart node.")
        logger.debug(f"Node code:\n{ast.unparse(node)}")

        # TODO: this process should also simplified the code of the passed node.
        # Which mean the call and control logic should be simplified in
        # the code. Here, should generate a node showing what the simplified code does.
        # This is the same as the ones in the `ast_call_to_chart_node` function.
        chart_nodes, new_ast = self._ast_node_to_chart_nodes(
            node=node,
            uri=uri,
        )
        if not chart_nodes:
            logger.debug(
                f"node {type(node)} doesn't have any call/control logic in it."
            )
            assert not self.should_expand(node, uri=uri)

        if self.nothing_to_do(new_ast):
            # All logic converted for single call or control nodes.
            return chart_nodes[0]

        uuid = self.node_uuid(node=node, uri=uri, suffix="glue")
        glue = ActionNode(
            name="glue",
            uuid=uuid,
            label=self.label_from_code(ast.unparse(new_ast), uuid=uuid),
        )
        if isinstance(node, ast.Expr):
            # TODO: Actually get the evaluation results of the expression.
            logger.debug(f"Get evaluation of {ast.unparse(node)}")

        # NOTE: If there is only one glue node, no need to create a wrapper.
        if not chart_nodes:
            return glue

        chart_nodes.append(glue)
        action_node = ActionNode.with_subchart(
            # TODO: generate name and label using GPT
            name=ast.unparse(node),
            uuid=self.node_uuid(node=node, uri=uri, suffix="wrapper"),
            # TODO: template for summarizing a list of nodes.
            label=self.label_from_labels(chart_nodes),
            chart_start=connect_nodes(chart_nodes),
        )
        return action_node

    @property
    def skipped_value(self) -> str:
        """Returns a string to represent a function node is skipped due to
        cannot be found in the code_nodes."""
        return "skipped"

    def ast_call_to_chart_node(
        self,
        *,
        node: ast.Call,
        uri: URI,
    ) -> CallNode | ActionNode | None:
        """Converts an AST call node to a Flowchart node."""
        assert isinstance(node, ast.Call), f"Node {node} is not a call node."

        # FIXME: We need a better way to check if pycg extract the call correctly.
        # Idealy following python's LEGB rule.
        if uri not in self.code_nodes and uri not in self.nested_func:
            logger.warning(f"Call of {uri} is not in the code nodes. Skip it.")
            self.add_func_node(uri, node=self.skipped_value)
            return None

        logger.info(
            f"Converting call node {ast.unparse(node.func)}() to a Flowchart node."
        )

        called_uri = self.call_func_info(node, uri=uri)
        if not called_uri:
            # NOTE: Theoriticaly this should not happen because we have checked the
            # first party call in the should_expand function.
            raise ValueError(f"Not a first party call {ast.unparse(node.func)}.")

        if called_uri not in self.code_nodes:
            # NOTE: This should not happen because we have checked the first party
            # call in the should_expand function.
            raise ValueError(f"Called URI {called_uri} is not in the code nodes.")

        chart_nodes = []
        # NOTE: We do should_expand check here because we don't want to generate a
        # single node for non-call nor control flow nodes. Also, we do not do the
        # check in the ast_node_to_chart_node function because we want a single type
        # return as a clear interface.
        for arg in node.args:
            if self.should_expand(arg, uri=uri):
                chart_nodes.append(self.ast_node_to_chart_node(node=arg, uri=uri))

        for keyword in node.keywords:
            if self.should_expand(node=keyword.value, uri=uri):
                chart_nodes.append(
                    self.ast_node_to_chart_node(node=keyword.value, uri=uri)
                )

        call_node = self.chart_funcdef_to_chart_call(
            node=node, uri=uri, called_uri=called_uri
        )
        if not chart_nodes:
            return call_node

        # NOTE: Put the argument nodes before the call node.
        chart_nodes.append(call_node)

        wrapper = ActionNode.with_subchart(
            # TODO: generate name and label using GPT
            name=ast.unparse(node.func),
            uuid=self.node_uuid(node=node, uri=uri, suffix="call_wrapper"),
            # TODO: Template for summarizing call nodes
            label=self.label_from_labels(chart_nodes),
            chart_start=connect_nodes(chart_nodes),
        )
        return wrapper

    def chart_funcdef_to_chart_call(
        self, node: ast.Call, uri: URI, called_uri: URI
    ) -> CallNode:
        """Creates a CallNode for a ast.Call node using a functiondef node as the template."""
        # TODO: Function code will be parsed as a module, so we need to get
        # the body[0]. Maybe we can have a nicer way to do it if we can fuse
        # the code_info generation and this process.
        func_ast = ast.parse(self.code_nodes[called_uri].code).body[0]
        if called_uri not in self.func_nodes:
            self.ast_funcdef_to_chart_node(node=func_ast, uri=called_uri)

        func_node = self.func_nodes[called_uri]
        call_uuid = self.node_uuid(node=node, uri=uri, suffix="call")

        if func_node is None:
            logger.warning(
                f"Call of {called_uri} is in a circle of recursive calls. "
                "Extract the inputs and returns without creating a chart node."
            )
            # TODO: Think of a better way to handle circular calls. It's the
            # best to be able to keep the reference to the actual node generated later.
            func_inputs = func_ast.args
            func_returns = func_ast.returns
            # func_process = None
        else:
            func_inputs = func_node.inputs
            func_returns = func_node.returns
            # func_process = func_node.get_process_chart(uuid=call_uuid)

        # NOTE: When the called function is complex (has a subchart), create
        # a call node wrapping the subchart.
        call_node = CallNode(
            name=ast.unparse(node.func),
            func_uri=called_uri,
            uuid=call_uuid,
            # TODO: Generate label using GPT following `call xxx with xxx input and
            # output xxx.` Here we might use the simplified code of the node, so
            # need to add that logic to this function.
            # label=f"Call {ast.unparse(node.func)} with args",
            label=self.label_from_code(ast.unparse(node), uuid=call_uuid),
            # TODO: associate the input annotations with the ast call node's
            # args to generate a summary of the actual input in this call,
            # especially for args whose meaning is unknown. set it to
            # call_node.inputs
            inputs=func_inputs,
            returns=func_returns,
            # subchart=func_process,
        )
        assert (call_node.subchart is None) or (
            call_node.subchart.uuid == call_node.uuid
        )
        return call_node

    def node_uuid(
        self, node: ast.AST, uri: URI, suffix: str, base_lineno: int = 0
    ) -> str:
        """Gets node names in format of
        `/package.subpkg.module/function:lineno:col_offset:suffix`."""
        note = f"{node.__class__.__name__}:{suffix}"
        node_uuid = f"{uri}:{node.lineno+base_lineno}:{node.col_offset}:{note}"
        if node_uuid in self.node_uuids:
            raise ValueError(f"Node {node_uuid} already exists.")
        self.node_uuids.add(node_uuid)
        return node_uuid

    def label_from_text(self, text: str, uuid: str) -> str:
        self.save_to_debug_file(
            f"""
# Text
`{uuid}`
{text}
"""
        )
        if self.call_api:
            uri = Uri.from_node_uuid(uuid)
            refined_key = "refined"
            response = generate_by_chain(
                messages=[REFINE_TEXT_PROMPT],
                inputs=dict(text=text),
                output_key=refined_key,
                output_path=self.prompt_dump_path(uri=uri, uuid=uuid),
                call_api=True,
                model="gpt-4-1106-preview",
            )
            return response[refined_key]

        return text

    def label_from_code(self, code: str, uuid: str) -> str:
        """ "Generates labels for nodes."""
        # TODO: If just a variable, return its meaning in the namespace.
        uri = Uri.from_node_uuid(uuid)
        if self.call_api:
            inputs = dict(
                summaries="",
                code=code,
                function_name=uri.function,
                file_name=uri.path,
                # function_summary = self.code_nodes[uri].summary if uri in self.code_nodes else "None",
                # summaries = "* _save_split: Split the given string by space and return the result.",
            )
            output_key = "process"
            outputs = generate_by_chain(
                messages=PROCESS_PROMPT_SET,
                inputs=inputs,
                output_key=output_key,
                output_path=self.prompt_dump_path(uri=uri, uuid=uuid),
                call_api=True,
                model="gpt-4-1106-preview",
            )
            return outputs[output_key]
        return f"{code[:50]}"

    def label_from_labels(self, nodes: list[BaseFlowchartNode]) -> str:
        """Summarizes the labels of a list of nodes."""
        labels = [node.label for node in nodes if node]
        self.save_to_debug_file(
            f"""# Summary of labels
Summarize labels:
{' *'.join(labels)}
"""
        )
        if self.call_api:
            pass
            # TODO: Call GPT and return response
        return f"Summary of {len(nodes)} nodes"

    def uuid_and_label(
        self,
        node: ast.AST,
        uri: URI,
        suffix: str,
        draft: str | None,
    ) -> dict[str, str]:
        """Gets the uuid and label of a node."""
        uuid = self.node_uuid(node=node, uri=uri, suffix=suffix)
        label = self.label_from_text(text=draft, uuid=uuid)
        return dict(uuid=uuid, label=label)

    def prompt_dump_path(self, uri: Uri, uuid: str) -> Path:
        file = "_".join(uuid.split(":")[1:])
        return self.dump_dir / uri.dump_dir / "prompts" / f"{file}.md"

    def ast_funcdef_to_chart_node(
        self, node: ast.FunctionDef, uri: URI
    ) -> DefineNode:
        """Converts an AST function definition node to a Flowchart.
        The defined FunctionNode will be registered in the func_nodes dict.
        A node representing the function definition behavior will be returned.
        """
        assert isinstance(node, ast.FunctionDef), f"Node {node} is not a function."
        if uri in self.func_nodes:
            logger.debug(f"Function {node.name} is being processed. Loop detected.")
            return None

        logger.info(
            f"Converting function `{ast.unparse(node)[:50]}` to a Flowchart."
        )
        # NOTE: Hold the place to prevent circular dependencies.
        self.add_func_node(uri, node=None)

        # TODO: Parse inputs and decorations.

        start = StartNode(
            name=f"{node.name}_Start",
            # TODO: Add input info to the label.
            inputs=[],
            uuid=self.node_uuid(node=node, uri=uri, suffix="start"),
            label=f"Start of function {node.name}",
        )

        # TODO: Collect ReturnNodes while processing body.
        if is_docstring(node.body[0]):
            docstr = ast.unparse(node.body[0])
            body_nodes = node.body[1:]
        else:
            body_nodes = node.body
        body = self.ast_nodes_to_chart_node(nodes=body_nodes, uri=uri)

        # TODO: Summarize all returns and add them to the end node.
        end = EndNode(
            name=f"{node.name}_end",
            uuid=self.node_uuid(node, uri=uri, suffix="end"),
            # TODO: add return info to the label.
            label=f"End of Function {node.name}",
        )

        func_node = FunctionNode.with_subchart(
            # TODO: Make these suffixs constants.
            name=f"{node.name}_FunctionDef",
            func_uri=uri,
            chart_start=connect_nodes([start, body, end]),
            **self.uuid_and_label(
                node=node,
                uri=uri,
                suffix="funcdef_wrapper",
                draft=f'Definition of function `{node.name}` which does "{body.label}"',
            ),
        )
        self.add_func_node(uri, node=func_node)

        define_node = DefineNode(
            name=f"{node.name}_Define",
            uuid=self.node_uuid(node, uri=uri, suffix="define"),
            label=f"Define function {node.name}",
            func_uri=uri,
        )
        return define_node


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

dummy_func_code = """
def {func_name}():
    return 1
"""

test_func_code = """
def test_func(messages):
    \"\"\"This is a docstring.\"\"\"  # test docstring
    if check_func():
        root_func(
            1,
            func_1(
                func_1_1(),
                True if messages else False,
                e=3,
            ),  # test function call arg
            a=2,
            c=func_2(
                4,
                g=1 if func_2_1() else 0,
            ),  # test function call kwarg
        )
    else:
        if messages:
            # DEBUG: Didn't see the for loop and if here.
            # print([m for m in messages if len(m) > 0])
            # DEBUG: Didn't see the glue node here.
            print(func_1())
    try:
        print("try")
    except ValueError:
        print("value error")
    except Exception:
        print("exception")
    else:
        print("else")
    finally:
        print("finally")

    # Testing for loop
    async for x in func_2():
        for i in range(10):
            print(i, x)
    else:
        print("for else")

    # Test while loop
    x = 10
    while x > 0:
        print(x)
        x -= 1
    else:
        print("while else")

    # Test while loop 2
    while func_1():
        print("while true")
        break

    # Test with
    with func_1() as x, func_2() as y:
        print(x, y)

    with cm as x:
        print(x)
    return 1

"""
test_func_calls = [
    "/autogpt.app.main/test_func",
    "/autogpt.app.main/check_func",
    "/autogpt.app.main/root_func",
    "/autogpt.app.main/func_1",
    "/autogpt.app.main/func_2",
    "/autogpt.app.main/func_1_1",
    "/autogpt.app.main/func_2_1",
    "",
]
test_func_uri = "/autogpt.app.main/test_func"
test_code_nodes = dict()

# NOTE: Need to generate dummy function definitions for the functions called.
for called_uri in test_func_calls:
    func_name = called_uri.split("/")[-1]
    test_code_nodes[called_uri] = CodeNode(
        uri=called_uri,
        code=dummy_func_code.format(func_name=func_name),
        calls=[],
        type="function",
        level=1,
    )
test_code_nodes[test_func_uri] = CodeNode(
    uri=test_func_uri,
    code=test_func_code,
    calls=test_func_calls,
    type="function",
    level=1,
)

for expand_threhold in [0, 100]:
    test_converter = AstChartNodeConverter(
        code_nodes=test_code_nodes,
        simplify_threshold=0,
        expand_threshold=expand_threhold,
    )
    test_chart = test_converter.ast_funcdef_to_chart_node(
        node=ast.parse(test_func_code).body[0],
        uri=test_func_uri,
    )
    flowchart_node_to_dot_graph(
        test_converter.func_nodes[test_func_uri],
        config=FlowchartConfig(expand_all=True, show_cluster=True),
        output_path=Path(__file__).parent / f"test_output_{expand_threhold}",
    )
    test_output_path = Path(__file__).parent / "test_output"
    func_node = test_converter.func_nodes[test_chart.func_uri]
    func_node.subchart.to_file(test_output_path / "funcdef_flowchart.json")

#### Real code ####
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
target_uri = update_uri
code = nodes[target_uri].code
ast_tree = ast.parse(code)
converter = AstChartNodeConverter(
    code_nodes=nodes,
    simplify_threshold=10,
    expand_threshold=50,
    call_api=True,
)
get = converter.ast_funcdef_to_chart_node(
    node=ast.parse(nodes[target_uri].code).body[0],
    uri=target_uri,
)

# %%
from codebase_analyzer.flowchart.node import flowchart_to_element_json


def save_function_separate(converter):
    for func_uri, func_node in converter.func_nodes.items():
        uri = Uri.from_fasten_uri(func_uri)
        flat_json = uri.dump_dir / "flat.json"
        element_json = uri.dump_dir / "element.json"

        flowchart_node_to_dot_graph(
            func_node,
            config=FlowchartConfig(expand_all=False, show_cluster=True),
            output_path=converter.dump_dir,
        )
        func_node.subchart.to_file(converter.dump_dir / flat_json)
        read = Flowchart.from_file(json_file=converter.dump_dir / flat_json)
        assert read.to_flat_dict() == func_node.subchart.to_flat_dict()
        flowchart_to_element_json(
            flowchart=func_node.subchart,
            output_path=converter.dump_dir / element_json,
        )


save_function_separate(converter=converter)
