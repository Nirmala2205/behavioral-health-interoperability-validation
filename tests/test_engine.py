"""End-to-end engine tests.

The consent tests in this file are the ones that would matter most if the
framework were ever pointed at real data. Everything else measures how well the
tool finds problems; these measure whether it invents them out of lawful
privacy behavior.
"""

import pandas as pd
import pytest

from config_loader import load_injection_profile, load_scenario
from inject_failures.injector import inject_failures
from transform.destination import build_wire_copy, clean_received
from transform.expected_exchange import build_expected_exchange, denominator_summary
from generate.synthetic_source import generate_source_truth
from validate.engine import summarize, validate


@pytest.fixture(scope="module")
def scenario():
    return load_scenario("A")


@pytest.fixture(scope="module")
def generated(scenario):
    source_truth, patients = generate_source_truth(scenario)
    expected = build_expected_exchange(source_truth, patients)
    return source_truth, patients, expected


def _run(expected, scenario, profile):
    wire = build_wire_copy(expected, scenario)
    clean = clean_received(wire)
    received, injections = inject_failures(clean, expected, profile, "A")
    results = validate(expected, received, "test-run")
    return results, injections


class TestCleanExchange:
    """With nothing injected, the framework must find nothing."""

    def test_perfect_exchange_produces_zero_failures(self, generated, scenario):
        _, _, expected = generated
        results, _ = _run(expected, scenario,
                          {"mode": "fixed", "random_seed": 1, "fixed_counts": []})
        failures = results[results["status"] == "FAIL"]
        assert len(failures) == 0, (
            "False positives in a clean run:\n"
            + failures[["element_name", "verdict", "detail"]].to_string()
        )

    def test_clean_exchange_is_100_percent_complete_and_faithful(self, generated, scenario):
        _, _, expected = generated
        results, _ = _run(expected, scenario,
                          {"mode": "fixed", "random_seed": 1, "fixed_counts": []})
        summary = summarize(results)
        assert summary["completeness_pct"] == 100.0
        assert summary["fidelity_pct"] == 100.0


class TestConsentHandling:
    """Correct privacy behavior must never be reported as a data-quality defect."""

    def test_restricted_elements_exist_in_the_test_data(self, generated):
        _, _, expected = generated
        excluded = expected[expected["exchange_expectation"] == "excluded_by_consent"]
        assert len(excluded) > 0, (
            "No consent-excluded elements were generated, so the consent "
            "dimension is untested. Check the consent_state_mix quota."
        )

    def test_correct_withholding_is_a_pass_not_a_gap(self, generated, scenario):
        _, _, expected = generated
        results, _ = _run(expected, scenario,
                          {"mode": "fixed", "random_seed": 1, "fixed_counts": []})
        excluded = results[results["exchange_expectation"] == "excluded_by_consent"]
        assert (excluded["status"] == "PASS").all()
        assert (excluded["verdict"] == "authorized_exclusion").all()

    def test_excluded_elements_are_outside_the_denominator(self, generated, scenario):
        _, _, expected = generated
        results, _ = _run(expected, scenario,
                          {"mode": "fixed", "random_seed": 1, "fixed_counts": []})
        summary = summarize(results)
        # The whole point: withheld Part 2 data must not drag completeness down.
        assert summary["total_expected_elements"] + \
               summary["elements_excluded_by_consent"] == \
               summary["total_source_elements"]
        assert summary["completeness_pct"] == 100.0

    def test_fully_restricted_patient_has_a_zero_denominator(self, generated):
        _, _, expected = generated
        denominators = denominator_summary(expected)
        fully_restricted = denominators[
            denominators["consent_state"] == "fully_restricted"
        ]
        if len(fully_restricted):
            # Undefined, not 0% -- an organization must not be scored as having
            # lost everything when it correctly disclosed nothing.
            assert (~fully_restricted["denominator_defined"]).all()

    def test_unauthorized_disclosure_is_detected(self, generated, scenario):
        _, _, expected = generated
        results, _ = _run(expected, scenario, {
            "mode": "fixed", "random_seed": 5,
            "fixed_counts": [{"failure_type": "unauthorized_disclosure",
                              "count": 2,
                              "expected_detection": "unauthorized_disclosure"}],
        })
        found = results[results["verdict"] == "unauthorized_disclosure"]
        assert len(found) == 2, (
            "A validator that iterates only the expected set cannot see leaked "
            "restricted elements. This test exists to catch that design error."
        )


class TestFailureDetection:

    @pytest.mark.parametrize("failure_type,verdict", [
        ("drop_required_element", "missing_element"),
        ("drop_subfield", "subfield_dropped"),
        ("alter_numeric_value", "value_mismatch"),
        ("degrade_code", "semantic_degraded"),
        ("relink_wrong_patient", "patient_linkage"),
        ("relink_wrong_encounter", "encounter_linkage"),
        ("delay_arrival", "timeliness"),
        ("consent_over_restriction", "consent_over_restriction"),
    ])
    def test_each_failure_type_produces_its_verdict(self, generated, scenario,
                                                    failure_type, verdict):
        _, _, expected = generated
        results, injections = _run(expected, scenario, {
            "mode": "fixed", "random_seed": 11,
            "fixed_counts": [{"failure_type": failure_type, "count": 1}],
        })
        assert len(injections) == 1, f"{failure_type} found no eligible target"
        target = injections["target_element_uid"].iloc[0]
        row = results[results["element_uid"] == target].iloc[0]
        assert row["verdict"] == verdict, (
            f"{failure_type} on {row['element_name']} produced "
            f"'{row['verdict']}', expected '{verdict}'. Detail: {row['detail']}"
        )

    def test_timeliness_failure_leaves_content_intact(self, generated, scenario):
        # A late arrival is complete and faithful. If a delay also showed up as
        # a completeness or fidelity failure, the dimensions would not be
        # independent and the same defect would be counted three times.
        _, _, expected = generated
        results, injections = _run(expected, scenario, {
            "mode": "fixed", "random_seed": 11,
            "fixed_counts": [{"failure_type": "delay_arrival", "count": 1}],
        })
        target = injections["target_element_uid"].iloc[0]
        row = results[results["element_uid"] == target].iloc[0]
        assert row["verdict"] == "timeliness"
        assert row["expected_value"] == row["received_value"]
        assert row["secondary_findings"] == ""


class TestTraceability:
    """Blueprint 7.1: every failure preserves full traceability."""

    def test_every_result_row_is_traceable(self, generated, scenario):
        _, _, expected = generated
        profile = load_injection_profile("v1")
        results, _ = _run(expected, scenario, profile)
        required_columns = [
            "run_id", "patient_id", "encounter_id", "element_name",
            "expected_value", "received_value", "verdict", "detail",
        ]
        for column in required_columns:
            assert column in results.columns
        assert results["run_id"].notna().all()

    def test_every_failure_carries_an_explanation(self, generated, scenario):
        _, _, expected = generated
        profile = load_injection_profile("v1")
        results, _ = _run(expected, scenario, profile)
        failures = results[results["status"] == "FAIL"]
        assert (failures["detail"].astype(str).str.len() > 0).all(), (
            "A failure with no explanation cannot be acted on or disputed."
        )


class TestDeterminism:

    def test_identical_inputs_give_identical_outputs(self, scenario):
        profile = load_injection_profile("v1")
        outputs = []
        for _ in range(2):
            source_truth, patients = generate_source_truth(scenario)
            expected = build_expected_exchange(source_truth, patients)
            results, _ = _run(expected, scenario, profile)
            outputs.append(results.to_csv(index=False))
        assert outputs[0] == outputs[1]
