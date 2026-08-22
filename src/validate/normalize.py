"""Normalization: strip away representation so comparison can see content.

Normalization is where most of a data-quality framework's false positives are
either created or prevented. Two systems can hold the identical clinical fact
and render it as "50 mg" and "0.05 g", or "daily" and "QD", or "F32.1" and
"f32.1". A comparison performed on raw strings reports three failures where
there are none.

The opposite error is just as damaging and much harder to notice: normalizing
so aggressively that genuinely different values collapse to equal. A
normalizer that silently coerced unparseable input to a default would turn
real corruption into a clean PASS -- a false negative in a tool whose entire
purpose is finding what other tools miss.

The rule followed here: normalize only differences that are documented in
config/ as representational, and return an explicit failure marker for
anything unparseable rather than guessing.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from config_loader import load_equivalence


@dataclass(frozen=True)
class Normalized:
    """Result of normalizing one raw value.

    ok=False means the value could not be interpreted under its declared
    datatype. That is itself a finding, not something to paper over: the
    engine treats an unnormalizable received value as a mismatch and records
    the reason.
    """

    value: Any
    ok: bool = True
    note: str = ""

    @property
    def missing(self) -> bool:
        return self.value is None or self.value == ""


_PUNCTUATION = str.maketrans("", "", string.punctuation)
_WHITESPACE = re.compile(r"\s+")


def upper_trim(raw: Any) -> Normalized:
    """Codes: case and surrounding whitespace carry no meaning."""
    if raw is None:
        return Normalized(None, note="null input")
    return Normalized(str(raw).strip().upper())


def text_normalized(raw: Any) -> Normalized:
    """Display text: case, punctuation, and whitespace runs carry no meaning.

    Deliberately does NOT attempt synonym resolution. "Major depressive
    disorder, moderate" and "Moderate MDD" are left as different strings,
    because deciding they are the same is a terminology judgment, and
    terminology judgments belong in the documented equivalence map where they
    can be reviewed -- not hidden inside a string normalizer.
    """
    if raw is None:
        return Normalized(None, note="null input")
    text = str(raw).strip().lower().translate(_PUNCTUATION)
    return Normalized(_WHITESPACE.sub(" ", text).strip())


def iso_datetime(raw: Any) -> Normalized:
    if raw is None or str(raw).strip() == "":
        return Normalized(None, note="empty datetime")
    try:
        return Normalized(datetime.fromisoformat(str(raw).strip()))
    except ValueError:
        return Normalized(None, ok=False, note=f"unparseable datetime: {raw!r}")


def iso_date(raw: Any) -> Normalized:
    if raw is None or str(raw).strip() == "":
        return Normalized(None, note="empty date")
    text = str(raw).strip()
    try:
        return Normalized(date.fromisoformat(text))
    except ValueError:
        pass
    try:
        return Normalized(datetime.fromisoformat(text).date())
    except ValueError:
        return Normalized(None, ok=False, note=f"unparseable date: {raw!r}")


def numeric(raw: Any) -> Normalized:
    if raw is None or str(raw).strip() == "":
        return Normalized(None, note="empty numeric")
    try:
        return Normalized(float(str(raw).strip()))
    except ValueError:
        return Normalized(None, ok=False, note=f"unparseable numeric: {raw!r}")


def dose_quantity(raw: Any) -> Normalized:
    """Parse 'value unit' and convert to milligrams.

    Milligrams is the canonical internal unit. Converting both sides before
    comparison is what allows Scenario A (mg) and Scenario B (g) to be
    validated by identical rules -- the generalization property Blueprint
    Stage C asks for.
    """
    if raw is None or str(raw).strip() == "":
        return Normalized(None, note="empty dose")

    text = str(raw).strip()
    match = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*([A-Za-z]+)\s*$", text)
    if not match:
        return Normalized(None, ok=False, note=f"unparseable dose: {raw!r}")

    magnitude = float(match.group(1))
    unit = match.group(2)
    milligrams = load_equivalence().to_mg(magnitude, unit)
    if milligrams is None:
        return Normalized(None, ok=False, note=f"unknown dose unit: {unit!r}")

    # Round to 6 decimals so float representation error in unit conversion
    # (0.05 g -> 50.000000000000007 mg) never reads as a value change.
    return Normalized(round(milligrams, 6))


def frequency_code(raw: Any) -> Normalized:
    """Map a dosing frequency onto a canonical HL7 GTS abbreviation."""
    if raw is None or str(raw).strip() == "":
        return Normalized(None, note="empty frequency")
    canonical = load_equivalence().canonical_frequency(str(raw))
    if canonical is None:
        # Preserved verbatim and flagged, never coerced. An unmapped frequency
        # is a gap in config/code_equivalence.yaml that a maintainer should
        # see, not a value to quietly invent a canonical form for.
        return Normalized(str(raw).strip().upper(), ok=False,
                          note=f"frequency not in synonym map: {raw!r}")
    return Normalized(canonical)


# Dispatch table -- the contract names one of these by string.
NORMALIZERS = {
    "upper_trim": upper_trim,
    "text_normalized": text_normalized,
    "iso_datetime": iso_datetime,
    "iso_date": iso_date,
    "numeric": numeric,
    "dose_quantity": dose_quantity,
    "frequency_code": frequency_code,
}


def normalize(normalizer_name: str, raw: Any) -> Normalized:
    try:
        normalizer = NORMALIZERS[normalizer_name]
    except KeyError as exc:
        raise KeyError(
            f"Validation Contract names normalizer '{normalizer_name}', which "
            f"is not implemented. Available: {sorted(NORMALIZERS)}"
        ) from exc
    return normalizer(raw)
