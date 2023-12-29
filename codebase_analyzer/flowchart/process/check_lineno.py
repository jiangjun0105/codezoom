from __future__ import annotations

from codebase_analyzer.flowchart.process.schema import Process


def is_index_larger(index1: str, index2: str) -> bool:
    """Returns if index1 is larger than index2"""
    parts1 = list(map(int, index1.split(".")))
    parts2 = list(map(int, index2.split(".")))
    length_difference = len(parts1) - len(parts2)
    if length_difference > 0:
        parts2.extend([0] * length_difference)
    elif length_difference < 0:
        parts1.extend([0] * -length_difference)
    return parts1 > parts2


def get_min_max_lineno(lineno_list: list[int]) -> tuple[float, float]:
    """Helper function to extract the smallest and largest line number from a list"""
    if not lineno_list:
        return float("inf"), float("-inf")
    return min(lineno_list), max(lineno_list)


def _is_not_incremental(linenos: list[int]) -> bool:
    return any(linenos[i] <= linenos[i - 1] for i in range(1, len(linenos)))


def _is_gap_large(linenos: list[int], threshold: int) -> bool:
    return any(
        linenos[i] - linenos[i - 1] > threshold for i in range(1, len(linenos))
    )


def check_process_linenos_data(
    root_process: Process,
    max_lineno_gap: int = 2,
) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []

    def _check_process_linenos(
        processes: list[Process],
        prev_max: float = float("-inf"),
        prev_index: str = "",
    ):
        nonlocal errors, warnings
        for process in processes:
            linenos = process.code_lineno
            index = process.index

            if not linenos:
                warnings.append(f"Warning: Missing lineno '{index} {process.name}'")
                continue

            if _is_not_incremental(linenos):
                errors.append(
                    f"Error: Non incremental lineno '{index} {process.name}'."
                )

            if _is_gap_large(linenos, max_lineno_gap):
                warnings.append(f"Warning: Gap too large '{index} {process.name}'")

            current_min, current_max = get_min_max_lineno(linenos)
            if prev_index and is_index_larger(prev_index, index):
                errors.append(
                    f"Error: Non incremental index {prev_index} -> {index} {process.name}."
                )

            if current_min <= prev_max:
                errors.append(
                    f"Error: Overlap lineno with previous {prev_index} -> {index} {process.name}'"
                )

            _check_process_linenos(
                process.subprocesses,
                prev_max=max(current_max, prev_max),
                prev_index=index,
            )

    _check_process_linenos(root_process.subprocesses)

    return errors, warnings


def check_process_linenos(
    process: Process, max_lineno_gap: int = 2
) -> tuple[list[str], list[str]]:
    """Function to check the line numbers for each process in a JSON file"""
    return check_process_linenos_data(process, max_lineno_gap)
