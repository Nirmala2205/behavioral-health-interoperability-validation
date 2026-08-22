"""Comparison-rule tests.

The central assertion in this file is that the comparator is three-valued.
A binary match/mismatch comparator would collapse "lost clinical specificity"
into "wrong value", and the semantic dimension -- one of the six the project
claims to measure -- would not exist.
"""

import pytest

from config_loader import load_contract
from validate import rules
from validate.normalize import normalize

CONTRACT = load_contract()
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"


def _compare(element_name: str, expected_raw, received_raw):
    element = CONTRACT.element(element_name)
    return rules.compare(
        element,
        normalize(element.normalization, expected_raw),
        normalize(element.normalization, received_raw),
    )


class TestCodeEquivalence:
    """The degraded-vs-wrong distinction, which is the point of the project."""

    def test_identical_code_matches(self):
        assert _compare("diagnosis_code", "F32.1", "F32.1").outcome == rules.MATCH

    def test_case_difference_still_matches(self):
        assert _compare("diagnosis_code", "F32.1", "f32.1").outcome == rules.MATCH

    def test_documented_broader_ancestor_is_degraded_not_mismatch(self):
        # F32.9 is "MDD, single episode, unspecified" -- the same condition
        # with the severity specifier lost. Meaning partially survived.
        result = _compare("diagnosis_code", "F32.1", "F32.9")
        assert result.outcome == rules.DEGRADED
        assert "broader" in result.detail

    def test_unrelated_code_is_a_mismatch_not_a_degradation(self):
        # I10 is essential hypertension. Nothing about it preserves the
        # meaning of a depression diagnosis.
        assert _compare("diagnosis_code", "F32.1", "I10").outcome == rules.MISMATCH

    def test_rxnorm_ingredient_collapse_is_degraded(self):
        # 312940 = sertraline 50 MG oral tablet; 36437 = sertraline (ingredient).
        # Strength and dose form lost, drug retained.
        assert _compare("medication_code", "312940", "36437").outcome == rules.DEGRADED

    def test_uncurated_ancestor_falls_back_to_mismatch(self):
        # F32 IS a genuine ancestor of F32.1, but it is deliberately absent
        # from config/code_equivalence.yaml. The engine has no documented basis
        # to call it a degradation, so it reports a mismatch.
        #
        # This test asserts a KNOWN LIMITATION rather than desired behavior.
        # config/injection_profile_blindspots.yaml quantifies its impact
        # (100% detection, 50% classification sensitivity). It is pinned here
        # so the limitation cannot change silently.
        assert _compare("diagnosis_code", "F32.1", "F32").outcome == rules.MISMATCH


class TestNumericTolerance:

    def test_equal_scores_match(self):
        assert _compare("assessment_score", "18", "18").outcome == rules.MATCH

    def test_zero_tolerance_means_one_point_fails(self):
        # PHQ-9 severity bands are 5 points wide, so even small drift can move
        # a patient across a treatment-relevant boundary.
        assert _compare("assessment_score", "18", "17").outcome == rules.MISMATCH

    def test_band_crossing_error_fails(self):
        # The blueprint's worked example: 18 (moderately severe) -> 8 (mild).
        assert _compare("assessment_score", "18", "8").outcome == rules.MISMATCH

    def test_tolerance_comes_from_the_contract_not_the_code(self):
        assert CONTRACT.element("assessment_score").tolerance == 0


class TestQuantityEquivalence:

    def test_unit_conversion_does_not_read_as_a_change(self):
        assert _compare("medication_dose", "50 mg", "0.05 g").outcome == rules.MATCH

    def test_genuinely_different_dose_fails(self):
        assert _compare("medication_dose", "50 mg", "100 mg").outcome == rules.MISMATCH


class TestFrequencyAndText:

    def test_free_text_and_abbreviation_agree(self):
        assert _compare("medication_frequency", "daily", "QD").outcome == rules.MATCH

    def test_different_frequency_fails(self):
        assert _compare("medication_frequency", "daily", "BID").outcome == rules.MISMATCH

    def test_display_text_formatting_is_ignored(self):
        assert _compare("diagnosis_display",
                        "Generalized anxiety disorder",
                        "generalized  anxiety disorder").outcome == rules.MATCH


def test_unknown_comparator_raises_loudly():
    from config_loader import ElementDef
    bogus = ElementDef(
        element_name="x", element_group="g", datatype="code", code_system=None,
        fhir_path="", normalization="upper_trim", comparison="no_such_rule",
        required=True,
    )
    with pytest.raises(KeyError):
        rules.compare(bogus, normalize("upper_trim", "a"), normalize("upper_trim", "a"))
