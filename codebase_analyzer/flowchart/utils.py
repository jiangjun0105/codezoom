from pathlib import Path

from codebase_analyzer.parser.uri import URI


def extract_dot_blocks(md_text):
    # Split the markdown text into lines
    lines = md_text.split("\n")

    # Initialize lists to store DOT blocks and the current block being processed
    dot_blocks = []
    current_block = []
    inside_dot_block = False

    # Iterate through each line
    for line in lines:
        if line.strip() == "```dot":
            inside_dot_block = True
            continue
        if line.strip() == "```" and inside_dot_block:
            inside_dot_block = False
            dot_blocks.append("\n".join(current_block))
            current_block = []
            continue
        if inside_dot_block:
            current_block.append(line)

    return "\n".join(dot_blocks)


def uri_to_path(uri: URI) -> str:
    # TODO: Think about cases having functions, for now this is OK because
    # AgentExecutorBot will only be used for Module and Packages
    uri = uri.lstrip("/")
    return uri.replace(".", "/")


def _output_path(uri: str, output_dir: Path) -> Path:
    if output_dir is None:
        return None

    output_path = output_dir / uri_to_path(uri)
    output_path.mkdir(exist_ok=True, parents=True)
    return output_path
