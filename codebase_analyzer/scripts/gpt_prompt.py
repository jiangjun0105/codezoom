from pathlib import Path

from langchain.chat_models import ChatOpenAI

from codebase_analyzer.parser.deftree import CodeInfo, CodeNode

REPO_ROOT = Path(__file__).parent.parent.parent.parent
CACHE_ROOT = REPO_ROOT / "shared_cache"


PROCESS_FLOW_TEMPLATE = """Given the following target function and the summaries of the functions being called, extract the main processes flow of the target function in the following format:
1. <operation xx described semantically>
2. <operation yy described semantically>
3. if <semantic_condition>, do <operation kk described semantically>
...

I'd like to create a flow chat for the program to show the main logic of this program. Your task is to consider what the major processes will happen if the target function is executed and extract them as a flow. The major processes don't have to be in the target function but also could be inside functions being called. You need to omit/simplify the unimportant processes or implementation details and extract the major logic steps.  About how to measure which processes are important, you can think which you are going to show if creating a process flow chart for this program.

====
TARGET FUNCTION
====
{code}

====
REFERENCES
====
Summary of functions called by the above code:

{summaries}
"""

TABLE_PREFIX = """
| URI (type) | Summary |
|------------|---------|
"""

TABLE_TEMPLATE = """| {uri} ({type}) | {summary} |"""

MAIN_FLOW_TEMPLATE = """The code of a target function is given, in which you can see it calls other functions. The main processes of other function is also given under a block named after the function name.

e.g. of input:

-----------
Target Function Code
-----------
aaa
bbb
if condition:
     yyy(args)
else:
    ccc

-----------
yyy
-----------
1. do zzz
2. do kkk
3. do uuu

I'd like to create a flow chat for the program to show the main logic of this program. Your task is to consider what the major processes will happen if the target function is executed and extract them as a flow. The major processes don't have to be in the target function but also could be inside functions being called. You need to omit/simplify the unimportant processes or implementation details and extract the major logic steps.  About how to measure which processes are important, you can think which you are going to show if creating a process flow chart for this program.
The output format should be similar to the ones of called functions.

Continue of the above example, the possible output is:

-----------
output flow
-----------
1. do aaa and bbb (merge them as they are less important and describe using human language)
2. if condition:
    - do zzz and kkk (merge them as they are less important)
   - do uuu
3. else, do ccc

-----------
Target Function Code
-----------
{code}

======
Process flows of called functions
======

{processes}
"""

FLOW_TEMPLATE = """
-----------
{name}
-----------
{process}
"""

SEP = "**********"


def summaries_prompt(summaries: list[tuple[str, str, str]]) -> str:
    contents = "\n".join(
        [
            TABLE_TEMPLATE.format(uri=uri, type=type, summary=summary)
            for uri, type, summary in summaries
        ]
    )
    if contents:
        return TABLE_PREFIX + contents
    else:
        return "No function is called, so no summary."


def generate_flow_prompt(target_uri: str, nodes: dict[str, CodeNode]) -> str:
    data = []
    target_node = nodes[target_uri]
    for call_uri in target_node.calls:
        data.append((call_uri, nodes[call_uri].type, nodes[call_uri].summary))
    return PROCESS_FLOW_TEMPLATE.format(
        code=target_node.code, summaries=summaries_prompt(data)
    )


def ask_gpt(prompt: str, model="gpt-4") -> str:
    llm = ChatOpenAI(model=model, temperature=0)
    return llm.invoke(prompt).content


def generate_main_flow_prompt(target_uri, nodes, flows):
    target_node = nodes[target_uri]
    processes = []
    for i, call_uri, response in flows:
        name = call_uri.split("/")[-1]
        processes.append(FLOW_TEMPLATE.format(name=name, process=response))
    return MAIN_FLOW_TEMPLATE.format(
        code=target_node.code, processes="\n".join(processes)
    )


def generate_process_flows(target_uri: str, nodes: dict[str, CodeNode]) -> str:
    main_node = nodes[target_uri]
    folder = Path("instructions")
    folder.mkdir(exist_ok=True)
    flows = []
    for i, call_uri in enumerate(main_node.calls):
        print(f"Generating flow for {call_uri}")
        name = call_uri.split("/")[-1]

        with open(f"instructions/{name}.txt", "w") as f:
            prompt = generate_flow_prompt(call_uri, nodes)
            print(prompt, file=f)
            print(f"\n{SEP}\n", file=f)
            response = ask_gpt(prompt)
            flows.append([i, call_uri, response])
            print(response, file=f)

    print(f"Generating main flow for main function {target_uri}")
    main_prompt = generate_main_flow_prompt(target_uri, nodes, flows)
    with open("instructions/main.txt", "w") as f:
        print(main_prompt, file=f)
        print(f"\n{SEP}\n", file=f)
        response = ask_gpt(main_prompt)
        print(response, file=f)


code_info = CodeInfo.from_disk(input_path=CACHE_ROOT / "Auto-GPT/codeinfo.json")
nodes = code_info.nodes
main_uri = "/autogpt.app.main/run_auto_gpt"

# generate_process_flows(main_uri, nodes)
