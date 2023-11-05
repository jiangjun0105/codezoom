# %%
from typing import List

from pydantic import ValidationError

from codebase_analyzer.flowchart.datamodel import (
    ActionPattern,
    ElifPattern,
    ElsePattern,
    ExitPattern,
    IfPattern,
    LoopPattern,
    Pattern,
    Process,
)

# Define the allowed successors for each pattern type
allowed_successors = {
    ActionPattern.get_name(): (ActionPattern, IfPattern, LoopPattern, ExitPattern),
    IfPattern.get_name(): (
        ActionPattern,
        IfPattern,
        ElifPattern,
        ElsePattern,
        LoopPattern,
        ExitPattern,
    ),
    ElifPattern.get_name(): (ElifPattern, ElsePattern),
    ElsePattern.get_name(): (ActionPattern, IfPattern, LoopPattern, ExitPattern),
    LoopPattern.get_name(): (ActionPattern, IfPattern, LoopPattern, ExitPattern),
    ExitPattern.get_name(): (),
}


def print_report(warnings: List[str], errors: List[str]) -> None:
    if errors:
        print("Validation errors found:")
        for error in errors:
            print(f"[Error] {error}")
    else:
        print("No errors found.")

    if warnings:
        print("Validation warnings found:")
        for warning in warnings:
            print(f"[Warning] {warning}")
    else:
        print("No warnings found.")


def check_process_pattern(process: Process) -> List[str]:
    errors = []
    warnings = []

    # Helper function to check subprocesses
    def check_subprocesses(subprocesses):
        if (
            subprocesses
            and subprocesses[0].pattern
            and isinstance(subprocesses[0].pattern, (ElifPattern, ElsePattern))
        ):
            errors.append(
                f"A subprocess list cannot start with {subprocesses[0].pattern.name}."
            )

        for i, sub in enumerate(subprocesses):
            # Check if subprocesses are required and exist
            if (
                sub.pattern
                and isinstance(
                    sub.pattern, (IfPattern, ElifPattern, ElsePattern, LoopPattern)
                )
                and not sub.subprocesses
            ):
                warnings.append(
                    f"Process `{sub.index}. {sub.name}` with {sub.pattern.name} should have subprocesses."
                )

            # Check if the subprocess's pattern type is allowed
            if i < len(subprocesses) - 1:
                next_sub = subprocesses[i + 1]
                if next_sub.pattern:
                    if isinstance(
                        next_sub.pattern.name, allowed_successors[sub.pattern.name]
                    ):
                        errors.append(
                            f"Process `{sub.index}. {sub.name}` with {sub.pattern.name} cannot be followed by a {next_sub.pattern.name} process."
                        )

            # Recurse into subprocesses
            if sub.subprocesses:
                check_subprocesses(sub.subprocesses)

    check_subprocesses([process])
    print_report(warnings, errors)
    return warnings, errors


if __name__ == "__main__":
    try:
        process = Process(
            name="root",
            index="0",
            explanation="",
            subprocesses=[
                Process(
                    name="root",
                    index="0",
                    explanation="",
                    subprocesses=[],
                    pattern=IfPattern(decision="a", true="b", false="c"),
                ),
                Process(
                    name="root",
                    index="0",
                    explanation="",
                    pattern=ElifPattern(decision="a", true="b"),
                ),
                Process(
                    name="root",
                    index="0",
                    explanation="",
                    pattern=LoopPattern(setup="a", decision="b", body="c"),
                ),
                Process(
                    name="root",
                    index="0",
                    explanation="",
                    pattern=ActionPattern(body="a"),
                ),
            ],
            pattern=ActionPattern(body="a"),
        )
        warnings, errors = check_process_pattern(process)
    except ValidationError as e:
        print(f"Validation Error: {e}")

# %%
