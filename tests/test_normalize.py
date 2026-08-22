"""Normalization tests.

These are the tests that matter most for false-positive control. Every case
below is a difference in *representation* that must NOT be reported as a
difference in *content* -- or, in the negative cases, an unparseable input that
must NOT be silently coerced into something comparable.
"""

import pytest

from validate.normalize import normalize


class TestDoseQuantity:
    """Doses must compare on magnitude, not on how the unit was written."""

    def test_grams_and_milligrams_are_the_same_dose(self):
        # This is exactly the Scenario A vs Scenario B difference. If this
        # fails, every medication in Scenario B becomes a phantom finding.
        assert normalize("dose_quantity", "50 mg").value == \
               normalize("dose_quantity", "0.05 g").value

    def test_micrograms_convert(self):
        assert normalize("dose_quantity", "500 mcg").value == 0.5

    def test_different_doses_stay_different(self):
        assert normalize("dose_quantity", "50 mg").value != \
               normalize("dose_quantity", "100 mg").value

    def test_float_error_does_not_leak(self):
        # 0.05 g -> 50.000000000000007 mg without rounding, which would read
        # as a value change on an exact comparison.
        assert normalize("dose_quantity", "0.05 g").value == 50.0

    def test_unknown_unit_is_flagged_not_guessed(self):
        result = normalize("dose_quantity", "50 furlongs")
        assert result.ok is False
        assert "unknown dose unit" in result.note

    def test_unparseable_is_flagged_not_guessed(self):
        # A normalizer that returned 0.0 here would turn corruption into a
        # comparable value and could produce a spurious PASS.
        assert normalize("dose_quantity", "as directed").ok is False


class TestFrequency:
    """Dosing frequency has many surface forms and one meaning."""

    @pytest.mark.parametrize("raw", ["daily", "Once Daily", "QD", "q.d.",
                                     "every day", "1x daily"])
    def test_daily_synonyms_all_canonicalize(self, raw):
        assert normalize("frequency_code", raw).value == "QD"

    def test_already_canonical_passes_through(self):
        # Scenario B emits GTS abbreviations directly; they must not be mangled.
        assert normalize("frequency_code", "BID").value == "BID"

    def test_distinct_frequencies_stay_distinct(self):
        assert normalize("frequency_code", "daily").value != \
               normalize("frequency_code", "twice daily").value

    def test_unmapped_frequency_is_flagged(self):
        result = normalize("frequency_code", "every third Tuesday")
        assert result.ok is False
        assert "not in synonym map" in result.note


class TestCodesAndText:

    def test_code_case_is_irrelevant(self):
        assert normalize("upper_trim", "f32.1").value == \
               normalize("upper_trim", "F32.1").value

    def test_display_text_ignores_case_punctuation_whitespace(self):
        assert normalize("text_normalized",
                         "Major Depressive Disorder, moderate").value == \
               normalize("text_normalized",
                         "major  depressive disorder moderate").value

    def test_display_text_does_not_resolve_synonyms(self):
        # Deciding "MDD" == "Major depressive disorder" is a terminology
        # judgment. It belongs in the reviewable equivalence map, not hidden
        # inside a string normalizer.
        assert normalize("text_normalized", "MDD").value != \
               normalize("text_normalized", "Major depressive disorder").value


class TestTemporal:

    def test_datetime_parses(self):
        assert normalize("iso_datetime", "2026-08-16T09:30:00").ok

    def test_bad_datetime_is_flagged(self):
        assert normalize("iso_datetime", "16/08/2026").ok is False

    def test_date_accepts_a_datetime_string(self):
        assert normalize("iso_date", "2026-08-16T09:30:00").value == \
               normalize("iso_date", "2026-08-16").value


class TestNumeric:

    def test_numeric_string_forms_agree(self):
        assert normalize("numeric", "18").value == normalize("numeric", "18.0").value

    def test_non_numeric_is_flagged(self):
        assert normalize("numeric", "eighteen").ok is False


def test_unknown_normalizer_raises_loudly():
    # A typo in the contract must fail the run, not quietly disable a rule --
    # a disabled rule produces a clean-looking result containing a false
    # negative, which is the worst outcome for this project.
    with pytest.raises(KeyError):
        normalize("no_such_normalizer", "x")
