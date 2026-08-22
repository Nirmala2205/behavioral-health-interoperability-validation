"""Evaluation-layer tests.

The evaluation layer is what licenses every performance claim the project
makes, so its arithmetic is tested against hand-constructed cases where the
right answer is obvious by inspection. A bug here would not produce a visibly
broken run -- it would produce a plausible, wrong number.
"""

import pandas as pd

from metrics.evaluate import completeness_accuracy, evaluate


def _results(rows):
    """Minimal VALIDATION_RESULTS frame with only the columns evaluate() reads."""
    return pd.DataFrame([{
        "element_uid": uid,
        "status": status,
        "verdict": verdict,
        "exchange_expectation": expectation,
        "delivery_status": "delivered",
        "received_value": "x",
    } for uid, status, verdict, expectation in rows])


#: Columns the real ledger always carries, even when empty. Declaring them
#: here keeps the fixture faithful to src/inject_failures/injector.py's
#: _Ledger.frame(), which never returns a column-less frame.
_LEDGER_COLUMNS = ["target_element_uid", "expected_detection", "failure_type"]


def _injections(rows):
    return pd.DataFrame([{
        "target_element_uid": uid,
        "expected_detection": expected,
        "failure_type": failure_type,
    } for uid, expected, failure_type in rows], columns=_LEDGER_COLUMNS)


class TestConfusionMatrix:

    def test_perfect_detection(self):
        results = _results([
            ("e1", "FAIL", "missing_element", "expected"),
            ("e2", "PASS", "exact_match", "expected"),
        ])
        injections = _injections([("e1", "missing_element", "drop_required_element")])
        summary = evaluate(results, injections)["summary"]

        assert summary["classification_true_positives"] == 1
        assert summary["false_negatives"] == 0
        assert summary["false_positives"] == 0
        assert summary["classification_sensitivity_pct"] == 100.0
        assert summary["precision_pct"] == 100.0

    def test_missed_failure_is_a_false_negative(self):
        results = _results([("e1", "PASS", "exact_match", "expected")])
        injections = _injections([("e1", "missing_element", "drop_required_element")])
        summary = evaluate(results, injections)["summary"]

        assert summary["false_negatives"] == 1
        assert summary["classification_sensitivity_pct"] == 0.0

    def test_invented_failure_is_a_false_positive(self):
        results = _results([("e1", "FAIL", "value_mismatch", "expected")])
        injections = _injections([])
        summary = evaluate(results, injections)["summary"]

        assert summary["false_positives"] == 1
        assert summary["precision_pct"] == 0.0
        assert summary["false_positive_verdicts"] == {"value_mismatch": 1}

    def test_detected_but_misclassified_is_scored_separately(self):
        # The framework caught it, but called it the wrong thing. Detection
        # sensitivity is 100%; classification sensitivity is 0%. Reporting only
        # the first number would overstate what the tool can tell a user.
        results = _results([("e1", "FAIL", "value_mismatch", "expected")])
        injections = _injections([("e1", "semantic_degraded", "degrade_code_uncurated")])
        summary = evaluate(results, injections)["summary"]

        assert summary["detection_sensitivity_pct"] == 100.0
        assert summary["classification_sensitivity_pct"] == 0.0
        assert summary["detected_but_misclassified"] == 1
        assert summary["false_positives"] == 0   # not invented, just misnamed

    def test_negative_control_flagged_is_reported(self):
        results = _results([("e1", "FAIL", "missing_element", "excluded_by_consent")])
        injections = _injections([("e1", "none", "correct_consent_exclusion")])
        summary = evaluate(results, injections)["summary"]

        assert summary["negative_controls_incorrectly_flagged"] == 1
        assert "e1" in summary["negative_control_failures"]


class TestPerFailureTypeBreakdown:

    def test_breakdown_separates_correct_wrong_and_missed(self):
        results = _results([
            ("e1", "FAIL", "semantic_degraded", "expected"),
            ("e2", "FAIL", "value_mismatch", "expected"),
            ("e3", "PASS", "exact_match", "expected"),
        ])
        injections = _injections([
            ("e1", "semantic_degraded", "degrade_code"),
            ("e2", "semantic_degraded", "degrade_code_uncurated"),
            ("e3", "semantic_degraded", "degrade_code"),
        ])
        breakdown = evaluate(results, injections)["by_failure_type"]
        row = breakdown[breakdown["expected_detection"] == "semantic_degraded"].iloc[0]

        assert row["injected"] == 3
        assert row["detected_correct_class"] == 1
        assert row["detected_wrong_class"] == 1
        assert row["missed"] == 1
        assert row["misclassified_as"] == "value_mismatch"


class TestCompletenessAccuracy:
    """Recompute completeness from the ledger and confirm the engine agrees."""

    def test_agreement_when_the_engine_is_right(self):
        results = _results([
            ("e1", "FAIL", "missing_element", "expected"),
            ("e2", "PASS", "exact_match", "expected"),
            ("e3", "PASS", "exact_match", "expected"),
            ("e4", "PASS", "exact_match", "expected"),
        ])
        injections = _injections([("e1", "missing_element", "drop_required_element")])
        check = completeness_accuracy(results, injections, reported_completeness=75.0)

        assert check["ground_truth_completeness_pct"] == 75.0
        assert check["agrees"] is True

    def test_disagreement_is_caught(self):
        results = _results([
            ("e1", "FAIL", "missing_element", "expected"),
            ("e2", "PASS", "exact_match", "expected"),
        ])
        injections = _injections([("e1", "missing_element", "drop_required_element")])
        # Engine claims 100% when ground truth is 50%.
        check = completeness_accuracy(results, injections, reported_completeness=100.0)

        assert check["ground_truth_completeness_pct"] == 50.0
        assert check["agrees"] is False

    def test_consent_excluded_elements_stay_out_of_the_denominator(self):
        results = _results([
            ("e1", "PASS", "exact_match", "expected"),
            ("e2", "PASS", "authorized_exclusion", "excluded_by_consent"),
            ("e3", "PASS", "authorized_exclusion", "excluded_by_consent"),
        ])
        check = completeness_accuracy(results, _injections([]), reported_completeness=100.0)

        assert check["total_expected_elements"] == 1
        assert check["ground_truth_completeness_pct"] == 100.0
