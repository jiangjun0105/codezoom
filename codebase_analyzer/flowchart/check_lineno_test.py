import json
from pathlib import Path

from codebase_analyzer.flowchart.check_lineno import (
    check_process_linenos_data,
    compare_indices,
)

# Test cases for the compare_indices function
test_cases = [
    ("1", "2", False),
    ("2", "1", True),
    ("2.1", "2.1.1", False),
    ("2.1.1", "2.1", True),
    ("2.2", "2.10", False),
    ("2.10", "2.2", True),
    ("3", "3.0", False),
    ("3.0", "3", False),
    ("3.1.2", "3.1.10", False),
    ("3.1.10", "3.1.2", True),
    ("3.1.2.0", "3.1.2", False),
]

# Execute the test cases
test_results = {}
for i, (index1, index2, expected) in enumerate(test_cases, 1):
    result = compare_indices(index1, index2)
    assert (
        result == expected
    ), f"Test Case {i, index1, index2}failed. Expected: {expected}, Got: {result}"
    print(f"Test Case {i} passed {index1} > {index2, expected}.")


# Test Case 1: Parent Process index no less than child process index
test_case_1 = {
    "name": "root",
    "subprocesses": [
        {"name": "process1", "index": "1", "code_lineno": [1, 2, 3]},
        {"name": "process2", "index": "2", "code_lineno": [4, 5, 6]},
        {
            "name": "process3",
            "index": "3",
            "subprocesses": [
                {"name": "process3.1", "index": "3.1", "code_lineno": [7, 8]},
            ],
            "code_lineno": [7, 8],
        },
    ],
}

# Test Case 2: Non-increasing Sequence
test_case_2 = {
    "name": "root",
    "subprocesses": [{"name": "process1", "index": "1", "code_lineno": [1, 3, 2]}],
}

# Test Case 3: Large Gaps
test_case_3 = {
    "name": "root",
    "subprocesses": [{"name": "process1", "index": "1", "code_lineno": [1, 2, 5]}],
}

# Test Case 4: Incorrect Index Order
test_case_4 = {
    "name": "root",
    "subprocesses": [
        {"name": "process1", "index": "1", "code_lineno": [1, 3]},
        {"name": "process2", "index": "2", "code_lineno": [2, 4]},
    ],
}

# Test Case 5: Missing Line Numbers
test_case_5 = {
    "name": "root",
    "subprocesses": [{"name": "process1", "index": "1", "code_lineno": []}],
}


test_case_6 = {
    "name": "root",
    "subprocesses": [
        {"name": "process1", "index": "1", "code_lineno": [1, 2, 3]},
        {"name": "process2", "index": "2", "code_lineno": [4, 5, 6]},
        {
            "name": "process3",
            "index": "3",
            "subprocesses": [
                {"name": "process3.1", "index": "3.1", "code_lineno": [8, 9]},
            ],
            "code_lineno": [7],
        },
    ],
}

# Define the test cases
test_cases = [
    (test_case_1, 1, 0),
    (test_case_2, 1, 0),
    (test_case_3, 0, 1),
    (test_case_4, 1, 0),
    (test_case_5, 0, 1),
    (test_case_6, 0, 0),
]

# Function to run test cases and check for errors and warnings
def run_test_cases(test_cases):
    test_results = {}
    for i, test_case in enumerate(test_cases, 1):
        input_dict, expected_errors, expected_warnings = test_case
        errors, warnings = check_process_linenos_data(input_dict)
        test_results[f"Test Case {i}"] = {"Errors": errors, "Warnings": warnings}
        assert (
            len(errors) == expected_errors
        ), f"Test Case {i} failed. Expected: {expected_errors} errors, Got: {len(errors)} errors"
        assert (
            len(warnings) == expected_warnings
        ), f"Test Case {i} failed. Expected: {expected_warnings} warnings, Got: {len(warnings)} warnings"
    return test_results


# Execute the test cases and print results
test_results = run_test_cases(test_cases)


for r in test_results:
    print(f"Test Case {r}:")
    print(f"Errors: {test_results[r]['Errors']}")
    print(f"Warnings: {test_results[r]['Warnings']}")
    print("\n")
