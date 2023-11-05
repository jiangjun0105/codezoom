from __future__ import annotations


def format_expected_index(parent_index: str | None, next_index: int) -> str:
    return f"{parent_index}.{next_index}" if parent_index else str(next_index)


def is_index_numeric(index: str) -> bool:
    return all(part.isdigit() for part in index.split("."))


def is_index_continuous(
    index_parts: list[int], expected_next_index: int, parent_index_parts: list[int]
) -> bool:
    return (
        index_parts[:-1] == parent_index_parts
        and index_parts[-1] == expected_next_index
    )


def is_root_process(index_parts: list[int]) -> bool:
    return len(index_parts) == 1


def check_one_index(processes, parent_index=None):
    errors = []
    expected_next_index = 1  # Start counting at 1 for each level

    for process in processes:
        index = process.get("index")
        if not index:
            errors.append(f"Process '{process['name']}' is missing an index.")
            continue

        if not is_index_numeric(index):
            errors.append(
                f"Process '{process['name']}' has a non-numeric index: '{index}'."
            )
            continue

        index_parts = list(map(int, index.split(".")))

        # Hierarchical correctness
        if parent_index:
            parent_index_parts = list(map(int, parent_index.split(".")))
            # Check if this index is a direct child
            if index_parts[:-1] != parent_index_parts:
                errors.append(
                    f"Process '{process['name']}' has an incorrect hierarchical index: '{index}'. Expected parent index: '{parent_index}'."
                )
            elif index_parts[-1] != expected_next_index:
                expected_index = format_expected_index(
                    parent_index, expected_next_index
                )
                errors.append(
                    f"Process '{process['name']}' has a non-continuous index: '{index}'. Expected: '{expected_index}'"
                )
        # Continuity for root level processes
        elif (
            not is_root_process(index_parts) or index_parts[0] != expected_next_index
        ):
            expected_index = str(expected_next_index)
            errors.append(
                f"Process '{process['name']}' has a non-continuous index: '{index}'. Expected: '{expected_index}'"
            )

        expected_next_index = index_parts[-1] + 1

        # Recursively check subprocesses
        subprocess_errors = check_one_index(process["subprocesses"], index)
        errors.extend(subprocess_errors)

    return errors


def check_process_indexes(processes: dict) -> list[str]:
    errors = check_one_index(processes["subprocesses"])
    if not errors:
        print("No errors detected in the indexes of the processes.")

    for i, result in enumerate(errors):
        print(f"[{i}] {result}")
    return errors
