"""Generate benchmark estimates with 95% Wilson confidence intervals."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from metrics.confidence import wilson_interval


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "outputs" / "benchmarks"

BENCHMARKS = {
    "primary_v1_probabilistic_n500": (
        BENCHMARK_ROOT / "v1_probabilistic_n500"
    ),
    "held_out_blindspots_n500": (
        BENCHMARK_ROOT / "blindspots_n500"
    ),
}


def interval_row(
    benchmark: str,
    scope: str,
    scenario: str,
    metric: str,
    successes: int,
    total: int,
) -> dict[str, Any]:
    lower, upper = wilson_interval(successes, total)

    return {
        "benchmark": benchmark,
        "scope": scope,
        "scenario": scenario,
        "metric": metric,
        "successes": successes,
        "total": total,
        "estimate_pct": round(100 * successes / total, 2),
        "ci95_lower_pct": round(100 * lower, 2),
        "ci95_upper_pct": round(100 * upper, 2),
    }


def metric_counts(
    evaluation: dict[str, Any],
) -> dict[str, tuple[int, int]]:
    classification_tp = int(
        evaluation["classification_true_positives"]
    )
    detection_tp = int(
        evaluation["detection_true_positives"]
    )
    injected = int(evaluation["injected_failures"])
    false_positives = int(evaluation["false_positives"])
    true_negatives = int(evaluation["true_negatives"])

    return {
        "classification_sensitivity": (
            classification_tp,
            injected,
        ),
        "detection_sensitivity": (
            detection_tp,
            injected,
        ),
        "precision": (
            detection_tp,
            detection_tp + false_positives,
        ),
        "specificity": (
            true_negatives,
            true_negatives + false_positives,
        ),
    }


def load_run_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for benchmark, benchmark_dir in BENCHMARKS.items():
        combined_counts: dict[str, list[int]] = defaultdict(
            lambda: [0, 0]
        )
        class_counts: dict[str, list[int]] = defaultdict(
            lambda: [0, 0]
        )

        for scenario in ("A", "B"):
            scenario_dir = benchmark_dir / f"scenario_{scenario}"
            report = load_run_report(
                scenario_dir / "run_report.json"
            )

            counts = metric_counts(report["evaluation"])

            for metric, (successes, total) in counts.items():
                rows.append(
                    interval_row(
                        benchmark,
                        "scenario",
                        scenario,
                        metric,
                        successes,
                        total,
                    )
                )
                combined_counts[metric][0] += successes
                combined_counts[metric][1] += total

            evaluation_path = (
                scenario_dir
                / "evaluation_by_failure_type.csv"
            )

            with evaluation_path.open(
                encoding="utf-8",
                newline="",
            ) as handle:
                for record in csv.DictReader(handle):
                    failure_class = record[
                        "expected_detection"
                    ]
                    class_counts[failure_class][0] += int(
                        record["detected_correct_class"]
                    )
                    class_counts[failure_class][1] += int(
                        record["injected"]
                    )

        for metric, (successes, total) in combined_counts.items():
            rows.append(
                interval_row(
                    benchmark,
                    "combined",
                    "A+B",
                    metric,
                    successes,
                    total,
                )
            )

        for failure_class, (
            successes,
            total,
        ) in sorted(class_counts.items()):
            rows.append(
                interval_row(
                    benchmark,
                    "combined_by_failure_type",
                    "A+B",
                    (
                        "classification_sensitivity:"
                        f"{failure_class}"
                    ),
                    successes,
                    total,
                )
            )

    return rows


def main() -> None:
    rows = build_rows()

    csv_path = (
        BENCHMARK_ROOT / "statistical_summary.csv"
    )
    json_path = (
        BENCHMARK_ROOT / "statistical_summary.json"
    )

    fieldnames = [
        "benchmark",
        "scope",
        "scenario",
        "metric",
        "successes",
        "total",
        "estimate_pct",
        "ci95_lower_pct",
        "ci95_upper_pct",
    ]

    with csv_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )

    print(f"Wrote {len(rows)} statistical rows.")
    print(csv_path)
    print(json_path)


if __name__ == "__main__":
    main()