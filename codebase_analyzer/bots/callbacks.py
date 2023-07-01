import sys
from typing import Any, Dict, List, Optional

from langchain.callbacks import StdOutCallbackHandler
from langchain.input import print_text
from langchain.schema import AgentAction, AgentFinish, LLMResult


class BotStreamingStdOutCallbackHandler(StdOutCallbackHandler):
    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """Print out the prompts."""
        pass

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Do nothing."""
        pass

    def on_llm_new_token(
        self, token: str, color: str = "green", **kwargs: Any
    ) -> None:
        """Run on new LLM token. Only available when streaming is enabled."""
        print_text(token, color=self.color if self.color else color, end="")
        sys.stdout.flush()

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Do nothing."""
        # FIXME: make it more general
        if serialized.get("name") == "ask_function_bot":
            print_text("Function bot:", color="blue", end="")
            sys.stdout.flush()
            return

    def on_tool_end(
        self,
        output: str,
        color: Optional[str] = None,
        observation_prefix: Optional[str] = None,
        llm_prefix: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """If not the final action, print out observation."""
        # FIXME: make it more general
        # Let the asked bot print out the observation
        if kwargs.get("name") == "ask_function_bot":
            sys.stdout.write("\n\n")
            sys.stdout.flush()
            return
        if observation_prefix is not None:
            print_text(f"\n{observation_prefix}")
        output = pad_text(text=output, before="", after="\n\n", strip="\n")
        print_text(output, color=color if color else self.color)

        if llm_prefix is not None:
            print_text(f"\n{llm_prefix}")

    def on_agent_finish(
        self, finish: AgentFinish, color: Optional[str] = None, **kwargs: Any
    ) -> None:
        """Run on agent end."""
        sys.stdout.write("\n")
        sys.stdout.flush()


def pad_text(text: str, before: str = "", after: str = "", strip: str = "\n") -> str:
    """Pad text."""
    return before + text.strip(strip) + after
