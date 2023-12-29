from __future__ import annotations

from codebase_analyzer.flowchart.process.schema import ROOT_PROCESS_INDEX, Process


def format_expected_index(parent_index: str | None, next_index: int) -> str:
    if parent_index is None:
        return ROOT_PROCESS_INDEX
    if parent_index == ROOT_PROCESS_INDEX:
        return str(next_index)
    return f"{parent_index}.{next_index}"


def is_index_numeric(index: str) -> bool:
    return all(part.isdigit() for part in index.split("."))


def is_index_continuous(
    index_parts: list[int], expected_index: int, parent_index_parts: list[int]
) -> bool:
    return (
        index_parts[:-1] == parent_index_parts and index_parts[-1] == expected_index
    )


def is_root_process(index_parts: list[int]) -> bool:
    return len(index_parts) == 1 and index_parts[0] == ROOT_PROCESS_INDEX


def check_process(
    process: Process, expected_index: int, parent_index: str
) -> list[str]:
    errors = []

    index = process.index
    if not index:
        errors.append(f"Process '{process.name}' is missing an index.")
        return errors

    if not is_index_numeric(index):
        errors.append(
            f"Process '{process.name}' has a non-numeric index: '{index}'."
        )
        return errors

    index_parts = list(map(int, index.split(".")))

    # Both root and non-root processes
    if index_parts[-1] != expected_index:
        expected_index = format_expected_index(parent_index, expected_index)
        errors.append(
            f"Process '{process.name}' has a non-continuous index: '{index}'. Expected: '{expected_index}'"
        )

    # Only for non-root processes
    if parent_index and parent_index != ROOT_PROCESS_INDEX:
        parent_index_parts = list(map(int, parent_index.split(".")))
        if index_parts[:-1] != parent_index_parts:
            errors.append(
                f"Process '{process.name}' has an incorrect hierarchical index: '{index}'. Expected parent index: '{parent_index}'."
            )

    # Recursively check subprocesses
    for i, sub in enumerate(process.subprocesses, 1):
        sub_errors = check_process(sub, expected_index=i, parent_index=process.index)
        errors.extend(sub_errors)

    return errors


def check_process_indexes(process: Process) -> list[str]:
    errors = check_process(
        process, expected_index=int(ROOT_PROCESS_INDEX), parent_index=None
    )

    for i, result in enumerate(errors):
        print(f"[{i}] {result}")

    if not errors:
        print("No errors detected in the indexes of the processes.")
    return errors
