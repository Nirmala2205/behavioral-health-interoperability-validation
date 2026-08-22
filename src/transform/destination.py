"""Render the exchange (wire) copy and assemble the simulated RECEIVED dataset.

Two distinct things happen here, and keeping them separate is the point:

1.  RENDERING (build_wire_copy) -- how the sending system writes values on the
    wire. Grams instead of milligrams, "QD" instead of "daily", lower-case
    codes. These are surface differences, NOT data-quality failures. If the
    validator reports any of them, it is producing a false positive.

2.  DELIVERY (build_received) -- taking the wire copy, applying whatever
    failures the injector decided to introduce, and producing what the
    receiving system actually ends up holding.

Conflating the two is a real and common modeling error: it makes rendering
differences look like corruption, which inflates apparent failure rates and
makes the framework useless across heterogeneous senders -- the exact
heterogeneity the research question is about.

A NOTE ON CORRELATION IDENTIFIERS
---------------------------------
Received rows carry `exchange_element_id`, a wire identifier that survives
transmission, and the validator matches expected to received on it. This models
FHIR's persistent `Resource.id` / `Identifier`, which does survive exchange in
practice.

It is still an assumption, and a load-bearing one: an exchange path that does
NOT preserve stable identifiers would require probabilistic record matching
instead, and matching error would then confound every downstream metric.
That limitation is stated in docs/methodology/methodology_note.md rather than
buried here, because a reviewer will ask about it.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from config_loader import load_equivalence

_CODE_DATATYPES = {"code"}


def _render_dose(value: str, target_unit: str) -> str:
    """Re-express a canonical 'N mg' dose in the scenario's preferred unit."""
    equivalence = load_equivalence()
    try:
        magnitude_text, unit = value.split()
        magnitude = float(magnitude_text)
    except (ValueError, AttributeError):
        return value  # unparseable input is passed through untouched

    milligrams = equivalence.to_mg(magnitude, unit)
    if milligrams is None:
        return value

    if target_unit == "g":
        grams = milligrams / 1000.0
        return f"{grams:g} g"
    if target_unit == "mcg":
        return f"{milligrams * 1000:g} mcg"
    return f"{milligrams:g} mg"


def _render_frequency(value: str, style: str) -> str:
    """Emit frequency either as free text or as an HL7 GTS abbreviation."""
    if style != "gts_abbreviation":
        return value
    canonical = load_equivalence().canonical_frequency(value)
    return canonical if canonical else value


def build_wire_copy(expected: pd.DataFrame, scenario: dict[str, Any]) -> pd.DataFrame:
    """Produce the exchange representation of every source element.

    All elements are rendered, including consent-excluded ones. Excluded rows
    are carried with authorized_to_send=False so the injector can, if
    configured to, deliberately leak one -- which is how the unauthorized
    disclosure scenario becomes testable.
    """
    from config_loader import load_contract

    contract = load_contract()
    rendering = scenario["rendering"]
    transmission = scenario["transmission"]
    rng = random.Random(int(scenario["generation"]["random_seed"]) + 1)

    code_case = rendering.get("code_case", "upper")
    dose_unit = rendering.get("dose_unit", "mg")
    frequency_style = rendering.get("frequency_style", "free_text")
    base_latency = int(transmission["base_latency_minutes"])
    jitter = int(transmission["latency_jitter_minutes"])

    rows: list[dict[str, Any]] = []
    for record in expected.to_dict("records"):
        element = contract.element(record["element_name"])
        value = record["element_value"]

        if element.datatype in _CODE_DATATYPES and record["element_name"] != "medication_frequency":
            value = value.lower() if code_case == "lower" else value.upper()
        elif record["element_name"] == "medication_dose":
            value = _render_dose(value, dose_unit)
        elif record["element_name"] == "medication_frequency":
            value = _render_frequency(value, frequency_style)

        encounter_dt = datetime.fromisoformat(record["encounter_datetime"])
        sent = encounter_dt + timedelta(minutes=rng.randint(1, 30))
        received = sent + timedelta(minutes=base_latency + rng.randint(0, jitter))

        rows.append({
            "exchange_element_id": record["element_uid"],
            "scenario_id": record["scenario_id"],
            "patient_id": record["patient_id"],
            "encounter_id": record["encounter_id"],
            "group_id": record["group_id"],
            "element_group": record["element_group"],
            "element_name": record["element_name"],
            "element_value": value,
            "code_system": record["code_system"],
            "sensitivity_class": record["sensitivity_class"],
            "encounter_class": record["encounter_class"],
            "authorized_to_send": bool(record["authorized"]),
            "sent_timestamp": sent.isoformat(),
            "received_timestamp": received.isoformat(),
            "destination_system": scenario["destination_system"],
        })

    return pd.DataFrame(rows)


def clean_received(wire: pd.DataFrame) -> pd.DataFrame:
    """The destination state under perfect exchange, before any injection.

    Every element produces a destination row, but in one of two states:

        delivered        authorized element, value present
        withheld_notice  consent-excluded element; the receiver is told
                         something was withheld but not what it was

    Emitting an explicit notice for withheld content -- rather than simply
    omitting the row -- is what lets the framework later distinguish correct
    privacy behavior from silent loss. See the module docstring in
    src/inject_failures/injector.py for why that distinction is load-bearing.

    This is the baseline a run with zero injections must validate as 100%
    complete and 100% faithful, with every consent exclusion recorded as an
    authorized exclusion rather than a gap. Running the pipeline with an empty
    injection profile is therefore the cheapest possible regression test for
    false positives, and tests/test_engine.py does exactly that.
    """
    destination = wire.copy()
    destination["delivery_status"] = [
        "delivered" if authorized else "withheld_notice"
        for authorized in destination["authorized_to_send"]
    ]
    # A withholding notice discloses that something was withheld, never the
    # value itself -- carrying the value here would defeat the restriction and
    # would also let the validator "detect" content it should not be able to see.
    destination.loc[destination["delivery_status"] == "withheld_notice",
                    "element_value"] = ""
    return destination.drop(columns=["authorized_to_send"]).reset_index(drop=True)
