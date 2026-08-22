"""Evaluation: does the detector actually work?

Blueprint Section 15 is blunt about why this module exists: "The dashboard
shows 500 errors" is not proof that the detector is correct. A framework that
reports findings has demonstrated that it produces output. A framework scored
against a known reference standard has demonstrated that its output is right.

This is Study 3 logic in miniature -- the injection ledger is the reference
standard, and the detector is scored against it without being told what it
contains.

TWO LEVELS OF SCORING
---------------------
Detection and classification are scored separately, because collapsing them
hides a real and common weakness:

    detection      Was the element flagged at all?
    classification Was it flagged with the CORRECT failure class?

A framework that catches every injected failure but calls half of them by the
wrong name has perfect detection sensitivity and mediocre classification
accuracy. Reporting only the first number would overstate what the tool can do,
since the recommended response to a linkage failure and a semantic degradation
are not the same. Classification accuracy is the stricter and more honest
headline, so it is reported first.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Injections whose intended effect is that the element does not arrive at all.
# Used to independently recompute the expected completeness figure.
_REMOVAL_FAILURES = {
    "drop_required_element",
    "drop_subfield",
    "consent_over_restriction",
}


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 2) if denominator else None


def _ensure_ledger_columns(injections: pd.DataFrame) -> pd.DataFrame:
    """Guarantee the ledger has its columns even when it has no rows.

    A zero-injection run is a first-class case, not an edge case -- it is the
    project's primary false-positive check. Reaching for a missing column here
    would crash exactly the diagnostic that is supposed to prove the framework
    invents nothing.
    """
    required = ["target_element_uid", "expected_detection", "failure_type"]
    if injections.empty:
        return pd.DataFrame(columns=required)
    missing = [column for column in required if column not in injections.columns]
    if missing:
        raise ValueError(f"Injection ledger is missing columns: {missing}")
    return injections


def evaluate(results: pd.DataFrame, injections: pd.DataFrame) -> dict[str, Any]:
    """Score VALIDATION_RESULTS against the FAILURE_INJECTIONS ledger."""
    injections = _ensure_ledger_columns(injections)
    true_failures = injections[injections["expected_detection"] != "none"]
    negative_controls = injections[injections["expected_detection"] == "none"]

    injected_class_by_uid: dict[str, str] = dict(
        zip(true_failures["target_element_uid"], true_failures["expected_detection"])
    )
    control_uids = set(negative_controls["target_element_uid"])

    flagged = results[results["status"] == "FAIL"]
    flagged_verdict_by_uid: dict[str, str] = dict(
        zip(flagged["element_uid"], flagged["verdict"])
    )

    # ------------------------------------------------------------------
    # Detection level -- flagged at all?
    # ------------------------------------------------------------------
    detection_tp = sum(1 for uid in injected_class_by_uid if uid in flagged_verdict_by_uid)
    detection_fn = len(injected_class_by_uid) - detection_tp
    detection_fp = sum(1 for uid in flagged_verdict_by_uid if uid not in injected_class_by_uid)
    detection_tn = len(results) - len(injected_class_by_uid) - detection_fp

    # ------------------------------------------------------------------
    # Classification level -- flagged with the right class?
    # ------------------------------------------------------------------
    classification_tp = sum(
        1 for uid, expected_class in injected_class_by_uid.items()
        if flagged_verdict_by_uid.get(uid) == expected_class
    )
    misclassified = detection_tp - classification_tp

    # ------------------------------------------------------------------
    # Negative controls -- correct behavior that must not be flagged
    # ------------------------------------------------------------------
    controls_flagged = sorted(uid for uid in control_uids if uid in flagged_verdict_by_uid)

    # ------------------------------------------------------------------
    # Per-failure-type breakdown
    # ------------------------------------------------------------------
    by_type: list[dict[str, Any]] = []
    for expected_class, group in true_failures.groupby("expected_detection"):
        uids = list(group["target_element_uid"])
        correct = sum(1 for uid in uids if flagged_verdict_by_uid.get(uid) == expected_class)
        wrong_class = sum(
            1 for uid in uids
            if uid in flagged_verdict_by_uid
            and flagged_verdict_by_uid[uid] != expected_class
        )
        missed = len(uids) - correct - wrong_class
        by_type.append({
            "expected_detection": expected_class,
            "injected": len(uids),
            "detected_correct_class": correct,
            "detected_wrong_class": wrong_class,
            "missed": missed,
            "classification_sensitivity_pct": _safe_ratio(correct, len(uids)),
            "misclassified_as": "; ".join(sorted({
                f"{flagged_verdict_by_uid[uid]}" for uid in uids
                if uid in flagged_verdict_by_uid
                and flagged_verdict_by_uid[uid] != expected_class
            })) or "",
        })

    # ------------------------------------------------------------------
    # False-positive detail -- what did the framework invent, and where?
    # ------------------------------------------------------------------
    false_positive_uids = [uid for uid in flagged_verdict_by_uid
                           if uid not in injected_class_by_uid]
    fp_breakdown = (
        flagged[flagged["element_uid"].isin(false_positive_uids)]
        .groupby("verdict").size().to_dict()
        if false_positive_uids else {}
    )

    summary = {
        "injected_failures": len(injected_class_by_uid),
        "negative_controls": len(control_uids),
        "flagged_elements": len(flagged_verdict_by_uid),

        "classification_true_positives": classification_tp,
        "detection_true_positives": detection_tp,
        "detected_but_misclassified": misclassified,
        "false_negatives": detection_fn,
        "false_positives": detection_fp,
        "true_negatives": detection_tn,

        "classification_sensitivity_pct": _safe_ratio(classification_tp,
                                                      len(injected_class_by_uid)),
        "detection_sensitivity_pct": _safe_ratio(detection_tp,
                                                 len(injected_class_by_uid)),
        "precision_pct": _safe_ratio(detection_tp, detection_tp + detection_fp),
        "specificity_pct": _safe_ratio(detection_tn, detection_tn + detection_fp),
        "false_positive_rate_pct": _safe_ratio(detection_fp, detection_fp + detection_tn),

        "negative_controls_incorrectly_flagged": len(controls_flagged),
        "negative_control_failures": controls_flagged,
        "false_positive_verdicts": fp_breakdown,
    }

    return {"summary": summary, "by_failure_type": pd.DataFrame(by_type)}


def completeness_accuracy(results: pd.DataFrame, injections: pd.DataFrame,
                          reported_completeness: float | None) -> dict[str, Any]:
    """Independently recompute completeness from ground truth and compare.

    Blueprint Section 15 asks whether "the framework calculates the known
    completeness level correctly." The check is worth doing separately from
    failure detection: the engine could classify every individual failure
    perfectly and still produce a wrong headline percentage if its denominator
    logic were subtly off -- for example by including consent-excluded elements,
    which is exactly the mistake this project is built to avoid.

    Recomputing from the ledger, using arithmetic that shares no code with the
    engine, is what turns "the number looks plausible" into "the number is
    verified."
    """
    injections = _ensure_ledger_columns(injections)
    total_expected = int((results["exchange_expectation"] == "expected").sum())

    removals = injections[injections["failure_type"].isin(_REMOVAL_FAILURES)]
    # Only removals that hit an authorized element reduce the received count;
    # a removal targeting an already-excluded element would not.
    expected_uids = set(results.loc[results["exchange_expectation"] == "expected",
                                    "element_uid"])
    effective_removals = sum(1 for uid in removals["target_element_uid"]
                             if uid in expected_uids)

    ground_truth_received = total_expected - effective_removals
    ground_truth_pct = _safe_ratio(ground_truth_received, total_expected)

    agrees = (
        reported_completeness is not None
        and ground_truth_pct is not None
        and abs(reported_completeness - ground_truth_pct) < 0.01
    )

    return {
        "total_expected_elements": total_expected,
        "ground_truth_received": ground_truth_received,
        "ground_truth_completeness_pct": ground_truth_pct,
        "framework_reported_completeness_pct": reported_completeness,
        "agrees": bool(agrees),
    }
