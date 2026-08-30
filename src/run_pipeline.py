"""End-to-end pipeline runner.

    source truth -> expected exchange -> FHIR -> wire -> injected failures
                 -> received -> validation -> SQL rollups -> evaluation

Usage
-----
    python src/run_pipeline.py                       # Scenarios A and B, micro
    python src/run_pipeline.py --scenarios A         # one scenario
    python src/run_pipeline.py --clean               # no failures (FP check)
    python src/run_pipeline.py --patients 500 \
        --profile v1 --mode probabilistic            # Stage B scaled benchmark

Every run is deterministic. Given the same configs and flags it produces
byte-identical outputs, which is what makes "reproducibility" a checkable
property rather than a claim -- `--verify-reproducible` runs the whole pipeline
twice and compares hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# src/ on the path so modules can import each other by their blueprint names
# (generate.*, transform.*, validate.*, metrics.*) without a packaging step.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb
import pandas as pd

import paths
from config_loader import (load_contract, load_injection_profile, load_scenario)
from generate.synthetic_source import generate_source_truth
from inject_failures.fhir_injector import (
    inject_fhir_element_loss,
    inject_fhir_numeric_value,
    inject_fhir_semantic_code_degradation,
)
from inject_failures.injector import inject_failures
from metrics.evaluate import completeness_accuracy, evaluate
from transform.destination import clean_received
from transform.fhir_receiver import build_wire_from_fhir
from transform.expected_exchange import build_expected_exchange, denominator_summary
from transform.fhir_builder import build_bundles
from validate.engine import summarize, validate


def _hash_frame(frame: pd.DataFrame) -> str:
    return hashlib.sha256(
        frame.to_csv(index=False).encode("utf-8")
    ).hexdigest()[:16]


def _run_sql(results: pd.DataFrame, sql_name: str) -> pd.DataFrame:
    """Execute one of the sql/*.sql rollups against the results table.

    Running the SQL for real, rather than shipping it as documentation, means
    a syntax error or a drifted column name fails the pipeline instead of
    waiting to be discovered by whoever opens the repo next.
    """
    query = (paths.SQL / sql_name).read_text(encoding="utf-8")
    connection = duckdb.connect(":memory:")
    connection.register("validation_results", results)
    frame = connection.execute(query).fetch_df()
    connection.close()
    return frame


def assert_baseline_latency_within_thresholds(scenario: dict[str, Any]) -> None:
    """Guard the exhaustiveness of the injection ledger.

    The evaluation layer treats the ledger as a complete record of every true
    failure in the run. If a scenario's ordinary transmission latency could
    exceed a timeliness threshold on its own, the run would contain real
    timeliness failures that were never injected, and every one of them would
    be scored as a false positive -- penalizing the framework for being right.

    This assertion exists because that is not hypothetical: it happened during
    development, on Scenario B, and produced four phantom false positives in a
    zero-injection run. Catching it in config rather than in an unexplained
    metric is worth the six lines.
    """
    contract = load_contract()
    transmission = scenario["transmission"]
    worst_case = (int(transmission["base_latency_minutes"])
                  + int(transmission["latency_jitter_minutes"]))
    tightest = min([contract.timeliness_default_minutes,
                    *contract.timeliness_by_class.values()])

    if worst_case >= tightest:
        raise ValueError(
            f"Scenario {scenario['scenario_id']} has a worst-case baseline "
            f"latency of {worst_case} minutes, which meets or exceeds the "
            f"tightest timeliness threshold ({tightest} minutes). Baseline "
            "latency must stay below every threshold, or the injection ledger "
            "stops being an exhaustive reference standard and true timeliness "
            "failures get scored as false positives. See the comment in "
            "config/scenario_B.yaml."
        )


def run_scenario(scenario_id: str, args: argparse.Namespace) -> dict[str, Any]:
    scenario = load_scenario(scenario_id)
    assert_baseline_latency_within_thresholds(scenario)
    if args.patients:
        scenario["generation"]["n_patients"] = args.patients

    profile = load_injection_profile(args.profile)
    if args.mode:
        profile["mode"] = args.mode
    if args.clean:
        # A run with zero injections must produce zero findings. Any finding
        # here is a false positive with nowhere to hide, which makes this the
        # single most informative diagnostic the pipeline can run.
        profile = {**profile, "mode": "fixed", "fixed_counts": []}

    run_id = (f"{scenario_id}-{'clean' if args.clean else profile['profile_id']}"
              f"-n{scenario['generation']['n_patients']}")

    # --- 1. Source truth ---------------------------------------------------
    source_truth, patients = generate_source_truth(scenario)

    # --- 2. Expected exchange (the denominator) ----------------------------
    expected = build_expected_exchange(source_truth, patients)
    denominators = denominator_summary(expected)

    # --- 3. FHIR representation --------------------------------------------
    bundle_dir = paths.scenario_dir(paths.FHIR_EXCHANGE, scenario_id)
    bundles = build_bundles(expected, patients, bundle_dir)

    fhir_injections = pd.DataFrame()

    if args.fhir_failure == "numeric":
        fhir_injections = inject_fhir_numeric_value(
            bundle_dir,
            expected,
            scenario_id,
        )
    elif args.fhir_failure == "semantic":
        fhir_injections = inject_fhir_semantic_code_degradation(
            bundle_dir,
            expected,
            scenario_id,
        )
    elif args.fhir_failure == "element-loss":
        fhir_injections = inject_fhir_element_loss(
            bundle_dir,
            expected,
            scenario_id,
        )

    # --- 4. Wire copy and clean destination state --------------------------
    wire = build_wire_from_fhir(
        expected,
        scenario,
        bundle_dir,
        allow_missing_authorized=(
            args.fhir_failure == "element-loss"
        ),
    )
    clean = clean_received(wire)

    # --- 5. Controlled failure injection -----------------------------------
    received, destination_injections = inject_failures(
    clean,
    expected,
    profile,
    scenario_id,
    )

    destination_injections = destination_injections.copy()
    destination_injections["failure_stage"] = "destination"

    injections = pd.concat(
    [
        fhir_injections,
        destination_injections,
    ],
    ignore_index=True,
    sort=False,
    )

    # --- 6. Validation ------------------------------------------------------
    results = validate(expected, received, run_id)
    run_summary = summarize(results)

    # --- 7. SQL rollups -----------------------------------------------------
    completeness_by_element = _run_sql(results, "completeness.sql")
    fidelity_by_element = _run_sql(results, "fidelity.sql")
    sql_summary = _run_sql(results, "validation_summary.sql")

    # --- 8. Evaluation against the injection ledger ------------------------
    evaluation = evaluate(results, injections)
    accuracy = completeness_accuracy(results, injections,
                                     run_summary["completeness_pct"])

    # --- 9. Persist ---------------------------------------------------------
    def write(frame: pd.DataFrame, base: Path, name: str) -> None:
        frame.to_csv(paths.scenario_dir(base, scenario_id) / name, index=False)

    write(source_truth, paths.DATA_SOURCE, "source_truth.csv")
    write(patients, paths.DATA_SOURCE, "patients.csv")
    write(expected, paths.DATA_EXPECTED, "expected_exchange.csv")
    write(denominators, paths.DATA_EXPECTED, "denominator_by_patient.csv")
    write(wire, paths.DATA_EXCHANGED, "wire_copy.csv")
    write(received, paths.DATA_RECEIVED, "received_data.csv")
    write(injections, paths.DATA_RECEIVED, "failure_injections.csv")
    write(results, paths.DATA_PROCESSED, "validation_results.csv")
    write(completeness_by_element, paths.OUTPUTS, "completeness_by_element.csv")
    write(fidelity_by_element, paths.OUTPUTS, "fidelity_by_element.csv")
    write(sql_summary, paths.OUTPUTS, "validation_run_summary.csv")
    write(evaluation["by_failure_type"], paths.OUTPUTS,
          "evaluation_by_failure_type.csv")

    report = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_name": scenario["scenario_name"],
        "contract_version": load_contract().contract_version,
        "patients": int(len(patients)),
        "fhir_bundles_written": len(bundles),
        "validation": run_summary,
        "evaluation": evaluation["summary"],
        "completeness_accuracy_check": accuracy,
        "output_hashes": {
            "validation_results": _hash_frame(results),
            "failure_injections": _hash_frame(injections),
        },
    }
    (paths.scenario_dir(paths.OUTPUTS, scenario_id) / "run_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def _fmt(value: Any, width: int = 8) -> str:
    """Format a metric that is legitimately undefined as 'n/a', not 0.

    A rate whose denominator is zero has no value. Printing 0 there would be a
    quiet lie -- a clean run has no failures to detect, so its sensitivity is
    undefined, not zero percent.
    """
    if value is None:
        return "n/a".rjust(width)
    return f"{value:>{width}}"


def _print_report(report: dict[str, Any]) -> None:
    validation = report["validation"]
    evaluation = report["evaluation"]
    accuracy = report["completeness_accuracy_check"]

    print(f"\n{'=' * 78}")
    print(f"  {report['run_id']}  --  {report['scenario_name']}")
    print(f"{'=' * 78}")

    print("\n  VALIDATION")
    print(f"    source elements generated      {validation['total_source_elements']:>8}")
    print(f"    expected (authorized)          {validation['total_expected_elements']:>8}")
    print(f"    excluded by consent            {validation['elements_excluded_by_consent']:>8}"
          f"   <- not in the denominator")
    print(f"    received                       {validation['expected_elements_received']:>8}")
    print(f"    completeness                   {_fmt(validation['completeness_pct'])}%")
    print(f"    fidelity                       {_fmt(validation['fidelity_pct'])}%")
    print(f"    total failures flagged         {validation['total_failures']:>8}")

    print("\n  DETECTION PERFORMANCE  (scored against the injection ledger)")
    print(f"    failures injected              {evaluation['injected_failures']:>8}")
    print(f"    correctly classified (TP)      {evaluation['classification_true_positives']:>8}")
    print(f"    detected, wrong class          {evaluation['detected_but_misclassified']:>8}")
    print(f"    missed (FN)                    {evaluation['false_negatives']:>8}")
    print(f"    false positives (FP)           {evaluation['false_positives']:>8}")
    print(f"    true negatives (TN)            {evaluation['true_negatives']:>8}")
    print(f"    classification sensitivity     {_fmt(evaluation['classification_sensitivity_pct'])}%")
    print(f"    detection sensitivity          {_fmt(evaluation['detection_sensitivity_pct'])}%")
    print(f"    precision                      {_fmt(evaluation['precision_pct'])}%")
    print(f"    specificity                    {_fmt(evaluation['specificity_pct'])}%")
    print(f"    negative controls wrongly hit  {evaluation['negative_controls_incorrectly_flagged']:>8}")

    print("\n  COMPLETENESS ACCURACY  (recomputed independently from ground truth)")
    print(f"    ground truth                   {_fmt(accuracy['ground_truth_completeness_pct'])}%")
    print(f"    framework reported             {_fmt(accuracy['framework_reported_completeness_pct'])}%")
    print(f"    agrees                         {str(accuracy['agrees']):>8}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", nargs="+", default=["A", "B"])
    parser.add_argument("--profile", default="v1")
    parser.add_argument("--mode", choices=["fixed", "probabilistic"], default=None)
    parser.add_argument("--patients", type=int, default=None)
    parser.add_argument("--clean", action="store_true",
                        help="Run with zero injected failures (false-positive check).")
    parser.add_argument(
        "--fhir-failure",
        nargs="?",
        const="numeric",
        choices=["numeric", "semantic", "element-loss"],
        default=None,
        help=(
            "Inject one controlled failure directly into generated FHIR. "
            "Using the flag without a value defaults to numeric."
        ),
    )
    parser.add_argument("--verify-reproducible", action="store_true",
                        help="Run twice and confirm identical output hashes.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    paths.ensure_dirs()

    reports = [run_scenario(scenario_id, args) for scenario_id in args.scenarios]
    if not args.quiet:
        for report in reports:
            _print_report(report)

    exit_code = 0

    if args.verify_reproducible:
        second = [run_scenario(scenario_id, args) for scenario_id in args.scenarios]
        identical = all(
            first["output_hashes"] == repeat["output_hashes"]
            for first, repeat in zip(reports, second)
        )
        print(f"\n  REPRODUCIBILITY: identical outputs across two runs = {identical}")
        if not identical:
            exit_code = 1

    # Cross-scenario comparison is the Stage C generalization evidence: if
    # precision holds when the wire rendering changes, the normalization layer
    # is doing real work rather than being tuned to one schema.
    if len(reports) > 1 and not args.quiet:
        print(f"\n{'=' * 78}")
        print("  CROSS-SCENARIO GENERALIZATION")
        print(f"{'=' * 78}")
        print(f"    {'scenario':<12}{'class.sens':>12}{'precision':>12}"
              f"{'specificity':>13}{'false pos':>11}")
        for report in reports:
            evaluation = report["evaluation"]
            print(f"    {report['scenario_id']:<12}"
                  f"{_fmt(evaluation['classification_sensitivity_pct'], 11)}%"
                  f"{_fmt(evaluation['precision_pct'], 11)}%"
                  f"{_fmt(evaluation['specificity_pct'], 12)}%"
                  f"{evaluation['false_positives']:>11}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
