"""Comparison rules: decide whether a received value preserved the expected one.

Each rule answers a three-way question rather than a two-way one:

    match      the received value carries the expected content
    degraded   the received value carries a documented, less specific version
               of the expected content -- meaning partially survived
    mismatch   the received value does not carry the expected content

The three-way outcome is deliberate. A binary match/mismatch comparison cannot
express the single most interesting finding in this problem space: a
structurally valid, apparently fine record that has quietly lost clinical
specificity. "F32.1 became F32.9" and "F32.1 became I10" are both mismatches to
a binary comparator, but the first is a mapping-depth problem and the second is
a wrong-record problem, and a receiving organization would act on them very
differently.
"""

from __future__ import annotations

from dataclasses import dataclass

from config_loader import ElementDef, load_equivalence
from validate.normalize import Normalized

MATCH = "match"
DEGRADED = "degraded"
MISMATCH = "mismatch"


@dataclass(frozen=True)
class Comparison:
    outcome: str
    detail: str = ""


def exact(expected: Normalized, received: Normalized, element: ElementDef) -> Comparison:
    if not received.ok:
        return Comparison(MISMATCH, received.note)
    if expected.value == received.value:
        return Comparison(MATCH)
    return Comparison(MISMATCH, f"expected {expected.value!r}, received {received.value!r}")


def text_equivalence(expected: Normalized, received: Normalized,
                     element: ElementDef) -> Comparison:
    return exact(expected, received, element)


def exact_datetime(expected: Normalized, received: Normalized,
                   element: ElementDef) -> Comparison:
    if not received.ok:
        return Comparison(MISMATCH, received.note)
    if expected.value == received.value:
        return Comparison(MATCH)
    return Comparison(MISMATCH,
                      f"expected {expected.value}, received {received.value}")


def exact_date(expected: Normalized, received: Normalized,
               element: ElementDef) -> Comparison:
    return exact_datetime(expected, received, element)


def numeric_exact(expected: Normalized, received: Normalized,
                  element: ElementDef) -> Comparison:
    """Numeric comparison against the element's declared tolerance.

    Tolerance is read from the contract rather than assumed. assessment_score
    declares 0 and documents why (PHQ-9 severity bands are 5 points wide, so
    any drift can cross a band boundary and change a clinical reading).
    """
    if not received.ok or received.value is None:
        return Comparison(MISMATCH, received.note or "received value is not numeric")

    tolerance = element.tolerance if isinstance(element.tolerance, (int, float)) else 0
    difference = abs(float(expected.value) - float(received.value))
    if difference <= float(tolerance):
        return Comparison(MATCH)
    return Comparison(
        MISMATCH,
        f"expected {expected.value:g}, received {received.value:g} "
        f"(difference {difference:g} exceeds tolerance {tolerance})"
    )


def quantity_equivalence(expected: Normalized, received: Normalized,
                         element: ElementDef) -> Comparison:
    """Dose comparison after unit normalization to milligrams."""
    if not received.ok or received.value is None:
        return Comparison(MISMATCH, received.note or "received dose is unparseable")
    if abs(float(expected.value) - float(received.value)) < 1e-6:
        return Comparison(MATCH)
    return Comparison(
        MISMATCH,
        f"expected {expected.value:g} mg, received {received.value:g} mg"
    )


def code_equivalence(expected: Normalized, received: Normalized,
                     element: ElementDef) -> Comparison:
    """Terminology comparison against the documented equivalence map."""
    if not received.ok:
        return Comparison(MISMATCH, received.note)

    relationship = load_equivalence().relationship(
        element.code_system, str(expected.value), str(received.value)
    )
    if relationship in ("exact", "equivalent"):
        return Comparison(MATCH, "" if relationship == "exact"
                          else "documented equivalent code")
    if relationship == "degraded":
        return Comparison(
            DEGRADED,
            f"{received.value} is a documented broader concept than "
            f"{expected.value}; clinical specificity lost"
        )
    return Comparison(
        MISMATCH,
        f"expected {expected.value}, received {received.value} "
        "(no documented relationship)"
    )


COMPARATORS = {
    "exact": exact,
    "text_equivalence": text_equivalence,
    "exact_datetime": exact_datetime,
    "exact_date": exact_date,
    "numeric_exact": numeric_exact,
    "quantity_equivalence": quantity_equivalence,
    "code_equivalence": code_equivalence,
}


def compare(element: ElementDef, expected: Normalized,
            received: Normalized) -> Comparison:
    try:
        comparator = COMPARATORS[element.comparison]
    except KeyError as exc:
        raise KeyError(
            f"Validation Contract names comparator '{element.comparison}' for "
            f"element '{element.element_name}', which is not implemented. "
            f"Available: {sorted(COMPARATORS)}"
        ) from exc
    return comparator(expected, received, element)
