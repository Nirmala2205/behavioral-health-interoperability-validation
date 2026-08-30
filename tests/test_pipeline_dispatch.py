import ast
from pathlib import Path


def test_patient_linkage_cli_dispatches_to_fhir_injector():
    pipeline_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "run_pipeline.py"
    )
    tree = ast.parse(
        pipeline_path.read_text(encoding="utf-8")
    )

    matching_branches = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue

        test = node.test

        if not (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "patient-linkage"
        ):
            continue

        called_functions = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
        }
        matching_branches.append(called_functions)

    assert any(
        "inject_fhir_wrong_patient_linkage" in calls
        for calls in matching_branches
    )