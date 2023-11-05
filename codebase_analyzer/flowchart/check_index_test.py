"""Test cases for the check_indexes function"""

from codebase_analyzer.flowchart.check_index import check_indexes

# Define test cases JSON structures
test_cases = [
    # Missing Index
    {
        "name": "missing_index_process",
        "explanation": "This process is missing an index.",
        "subprocesses": [],
    },
    # Non-Numeric Index
    {
        "name": "non_numeric_index_process",
        "index": "1.a",
        "explanation": "This process has a non-numeric index.",
        "subprocesses": [],
    },
    # Non-Continuous Index at Root Level
    {
        "name": "non_continuous_root_process",
        "index": "3",
        "explanation": "This root-level process has a non-continuous index.",
        "subprocesses": [],
    },
    # Non-Continuous Index at Subprocess Level
    {
        "name": "parent_process",
        "index": "1",
        "explanation": "This process has a non-continuous child index.",
        "subprocesses": [
            {
                "name": "non_continuous_subprocess",
                "index": "1.3",
                "explanation": "This subprocess has a non-continuous index.",
                "subprocesses": [],
            }
        ],
    },
    # Incorrect Hierarchical Index
    {
        "name": "incorrect_hierarchy_process",
        "index": "1.2.1",
        "explanation": "This process has an incorrect hierarchical index.",
        "subprocesses": [],
    },
    # Correct Structure
    {
        "name": "correct_structure_process",
        "index": "1",
        "explanation": "This process has a correct structure.",
        "subprocesses": [
            {
                "name": "correct_child_process",
                "index": "1.1",
                "explanation": "This child process has a correct index.",
                "subprocesses": [
                    {
                        "name": "correct_subchild_process",
                        "index": "1.1.1",
                        "explanation": "This subchild process has a correct index.",
                        "subprocesses": [],
                    }
                ],
            }
        ],
    },
]

# Function to run test cases
def run_test_cases(test_cases):
    test_results = {}
    for i, test_case in enumerate(test_cases, 1):
        # Check the indexes of each test case
        if "index" in test_case:
            errors = check_indexes([test_case])
        else:
            errors = check_indexes([test_case], parent_index="")
        test_results[f"Test Case {i}"] = errors or "No errors detected."
    return test_results


# Run the test cases
test_results = run_test_cases(test_cases)

# Output the results
for test_case, result in test_results.items():
    print(f"{test_case}: {result}")
