
import re
import openai

def search_data_structure(query, data_structure):
    query = query.lower()
    results = []

    for file_info in data_structure:
        for module in file_info["modules"]:
            for function in module["functions"]:
                if query in function["name"].lower():
                    results.append((function["name"], file_info["file"], function["docstring"]))
            
            for class_info in module["classes"]:
                if query in class_info["name"].lower():
                    results.append((class_info["name"], file_info["file"], class_info["docstring"]))

                for function in class_info["functions"]:
                    if query in function["name"].lower():
                        results.append((function["name"], file_info["file"], function["docstring"]))

    return results



# Set up your OpenAI API key
openai.api_key = "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"


def generate_codebase_description(codebase_info):
    # Flatten the codebase_info structure
    functions = []
    for file, file_info in codebase_info.items():
        for func_name, func_info in file_info.items():
            functions.append((func_name, file, func_info["docstring"]))

    # Generate a prompt that includes the list of functions
    function_list = "\n".join([f"{name}: {docstring}" for name, _, docstring in functions])
    prompt = f"Given the following list of functions in a codebase, summarize what the codebase does:\n{function_list}"

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a codebase summarizer."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=50,
    )

    return response.choices[0].message['content'].strip()


def generate_gpt_response(prompt):

    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": f"{prompt}"}
        ]
    )

    return completion.choices[0].message

def process_query(query, codebase_info):
    gpt_response = generate_gpt_response(query)
    print(f"gpt_response: {gpt_response}")

    if "summarize" in query.lower():
        search_results = search_data_structure(gpt_response, codebase_info)
    else:
        search_results = []

    if search_results:
        print(f"Found {len(search_results)} results:")
        for name, file, docstring in search_results:
            print(f"\n{name}\nFile: {file}\nDocstring: {docstring}")
    else:
        print("No results found.")
