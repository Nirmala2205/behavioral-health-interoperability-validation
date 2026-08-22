"""Derive EXPECTED_EXCHANGE -- the validation denominator.

This is the most consequential module in the project, and the shortest.

Blueprint Section 11 states the critical design rule: the comparison is not
SOURCE vs DESTINATION, it is

    SOURCE TRUTH -> EXPECTED/AUTHORIZED EXCHANGE -> RECEIVED -> VALIDATION

Everything hinges on getting the middle step right. In behavioral health,
lawfully withheld information and lost information are indistinguishable at the
destination -- both are simply absent. The only thing that separates them is
knowing, independently, what was authorized to move in the first place. That
knowledge is what this module encodes.

A framework without this step does not merely lose a little accuracy on
Part 2 data. It systematically reports correct privacy behavior as data loss,
and the more carefully an organization protects SUD records, the worse its
measured "data quality" appears. That inversion would make the tool actively
harmful to the organizations it is meant to help.
"""

from __future__ import annotations

import pandas as pd

from config_loader import load_consent_rules


def build_expected_exchange(source_truth: pd.DataFrame,
                            patients: pd.DataFrame) -> pd.DataFrame:
    """Annotate every source element with its exchange expectation.

    Adds three columns:

      consent_state          the patient's authorization state
      authorized             whether consent permits this element to move
      exchange_expectation   'expected'            -> counts in the denominator
                             'excluded_by_consent' -> must NOT arrive; its
                                                      absence is a PASS and its
                                                      presence is a consent
                                                      failure

    Every source element appears in the output exactly once. Excluded elements
    are retained rather than filtered away, because the framework must still
    check that they did not arrive -- a validator that iterates only the
    expected set is structurally incapable of detecting an unauthorized
    disclosure. (config/injection_profile_v1.yaml injects exactly that case as
    a deliberate trap for this design mistake.)
    """
    consent_rules = load_consent_rules()

    consent_by_patient = dict(
        zip(patients["patient_id"], patients["consent_state"])
    )

    missing = set(source_truth["patient_id"]) - set(consent_by_patient)
    if missing:
        raise ValueError(
            "Source elements reference patients with no consent state: "
            f"{sorted(missing)[:5]}. Every patient must have a declared "
            "consent state; defaulting to 'authorized' would silently inflate "
            "the denominator."
        )

    expected = source_truth.copy()
    expected["consent_state"] = expected["patient_id"].map(consent_by_patient)
    expected["authorized"] = [
        consent_rules.authorizes(state, sensitivity)
        for state, sensitivity in zip(expected["consent_state"],
                                      expected["sensitivity_class"])
    ]
    expected["exchange_expectation"] = [
        "expected" if authorized else "excluded_by_consent"
        for authorized in expected["authorized"]
    ]

    return expected


def denominator_summary(expected: pd.DataFrame) -> pd.DataFrame:
    """Per-patient denominator, including the zero-denominator case.

    A patient whose consent authorizes nothing has an expected-element count of
    zero. Completeness for that patient is undefined, not 0% -- reporting 0%
    would mean the framework penalizes an organization for correctly honoring a
    full restriction. This table makes the distinction explicit so the metric
    layer and the dashboard cannot accidentally average a meaningless zero into
    an overall rate.
    """
    grouped = (
        expected
        .groupby(["scenario_id", "patient_id", "consent_state"], as_index=False)
        .agg(
            total_source_elements=("element_uid", "count"),
            expected_elements=("authorized", "sum"),
        )
    )
    grouped["expected_elements"] = grouped["expected_elements"].astype(int)
    grouped["excluded_by_consent"] = (
        grouped["total_source_elements"] - grouped["expected_elements"]
    )
    grouped["denominator_defined"] = grouped["expected_elements"] > 0
    return grouped
