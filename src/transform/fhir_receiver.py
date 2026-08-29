import pandas as pd
import json
from pathlib import Path
from typing import Any
import random
from datetime import datetime, timedelta

from config_loader import load_contract
from transform.destination import (
    _CODE_DATATYPES,
    _render_dose,
    _render_frequency,
)


def load_fhir_resources(bundle_dir: Path) -> list[dict[str, Any]]:
    """Read all patient FHIR bundles and return their individual resources."""

    resources: list[dict[str, Any]] = []

    for bundle_path in sorted(bundle_dir.glob("*-exchange.json")):
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

        for entry in bundle.get("entry", []):
            resource = entry.get("resource")
            if resource:
                resources.append(resource)

    return resources
def _reference_id(reference: str | None) -> str:
    """Convert a FHIR reference like Patient/A-P0001 into A-P0001."""
    if not reference:
        return ""
    return reference.split("/", 1)[-1]


def extract_condition(resource: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one FHIR Condition into element-level diagnosis rows."""

    patient_id = _reference_id(
        resource.get("subject", {}).get("reference")
    )
    encounter_id = _reference_id(
        resource.get("encounter", {}).get("reference")
    )

    resource_id = resource.get("id", "")
    prefix = f"{encounter_id}-"
    group_id = (
        resource_id[len(prefix):]
        if encounter_id and resource_id.startswith(prefix)
        else resource_id
    )

    coding = resource.get("code", {}).get("coding", [])
    coding0 = coding[0] if coding else {}

    rows: list[dict[str, Any]] = []

    if coding0.get("code") is not None:
        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": group_id,
            "element_group": "diagnosis",
            "element_name": "diagnosis_code",
            "element_value": str(coding0["code"]),
        })

    if coding0.get("display") is not None:
        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": group_id,
            "element_group": "diagnosis",
            "element_name": "diagnosis_display",
            "element_value": str(coding0["display"]),
        })

    if resource.get("onsetDateTime") is not None:
        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": group_id,
            "element_group": "diagnosis",
            "element_name": "diagnosis_onset",
            "element_value": str(resource["onsetDateTime"]),
        })

    return rows

def extract_observation(resource: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one FHIR Observation into element-level assessment rows."""

    patient_id = _reference_id(
        resource.get("subject", {}).get("reference")
    )
    encounter_id = _reference_id(
        resource.get("encounter", {}).get("reference")
    )

    resource_id = resource.get("id", "")
    prefix = f"{encounter_id}-"
    group_id = (
        resource_id[len(prefix):]
        if encounter_id and resource_id.startswith(prefix)
        else resource_id
    )

    coding = resource.get("code", {}).get("coding", [])
    coding0 = coding[0] if coding else {}

    rows: list[dict[str, Any]] = []

    if coding0.get("code") is not None:
        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": group_id,
            "element_group": "assessment",
            "element_name": "assessment_code",
            "element_value": str(coding0["code"]),
        })

    if resource.get("effectiveDateTime") is not None:
        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": group_id,
            "element_group": "assessment",
            "element_name": "assessment_datetime",
            "element_value": str(resource["effectiveDateTime"]),
        })

    value = resource.get("valueQuantity", {}).get("value")
    if value is not None:
        if isinstance(value, float) and value.is_integer():
            value_text = str(int(value))
        else:
            value_text = str(value)

        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": group_id,
            "element_group": "assessment",
            "element_name": "assessment_score",
            "element_value": value_text,
        })

    return rows

def extract_encounter(resource: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one FHIR Encounter into element-level encounter rows."""

    patient_id = _reference_id(
        resource.get("subject", {}).get("reference")
    )
    encounter_id = resource.get("id", "")

    rows: list[dict[str, Any]] = []

    encounter_class = resource.get("class", {}).get("code")
    if encounter_class is not None:
        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": "ENC",
            "element_group": "encounter",
            "element_name": "encounter_class",
            "element_value": str(encounter_class),
        })

    encounter_datetime = resource.get("period", {}).get("start")
    if encounter_datetime is not None:
        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": "ENC",
            "element_group": "encounter",
            "element_name": "encounter_datetime",
            "element_value": str(encounter_datetime),
        })

    return rows


def extract_medication_request(resource: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one FHIR MedicationRequest into element-level medication rows."""

    patient_id = _reference_id(
        resource.get("subject", {}).get("reference")
    )
    encounter_id = _reference_id(
        resource.get("encounter", {}).get("reference")
    )

    resource_id = resource.get("id", "")
    prefix = f"{encounter_id}-"
    group_id = (
        resource_id[len(prefix):]
        if encounter_id and resource_id.startswith(prefix)
        else resource_id
    )

    rows: list[dict[str, Any]] = []

    medication_coding = (
        resource.get("medicationCodeableConcept", {})
        .get("coding", [])
    )
    medication0 = medication_coding[0] if medication_coding else {}

    if medication0.get("code") is not None:
        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": group_id,
            "element_group": "medication",
            "element_name": "medication_code",
            "element_value": str(medication0["code"]),
        })

    dosage_list = resource.get("dosageInstruction", [])
    dosage = dosage_list[0] if dosage_list else {}

    dose_and_rate = dosage.get("doseAndRate", [])
    dose_quantity = (
        dose_and_rate[0].get("doseQuantity", {})
        if dose_and_rate
        else {}
    )

    dose_value = dose_quantity.get("value")
    dose_unit = dose_quantity.get("unit")

    if dose_value is not None:
        dose_text = str(dose_value)
        if dose_unit:
            dose_text = f"{dose_text} {dose_unit}"

        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": group_id,
            "element_group": "medication",
            "element_name": "medication_dose",
            "element_value": dose_text,
        })

    timing_code = dosage.get("timing", {}).get("code", {})
    frequency_text = timing_code.get("text")

    frequency_coding = timing_code.get("coding", [])
    frequency0 = frequency_coding[0] if frequency_coding else {}

    frequency_value = (
        frequency_text
        if frequency_text not in (None, "")
        else frequency0.get("code")
    )

    if frequency_value is not None:
        rows.append({
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "group_id": group_id,
            "element_group": "medication",
            "element_name": "medication_frequency",
            "element_value": str(frequency_value),
        })

    return rows
def parse_fhir_bundles(bundle_dir: Path) -> pd.DataFrame:
    """Reconstruct element-level clinical data from FHIR exchange bundles.

    Only clinical content actually present in the FHIR bundles is returned.
    Patient and Consent resources are intentionally not converted into
    validation elements.
    """

    resources = load_fhir_resources(bundle_dir)
    rows: list[dict[str, Any]] = []

    for resource in resources:
        resource_type = resource.get("resourceType")

        if resource_type == "Encounter":
            rows.extend(extract_encounter(resource))

        elif resource_type == "Condition":
            rows.extend(extract_condition(resource))

        elif resource_type == "Observation":
            rows.extend(extract_observation(resource))

        elif resource_type == "MedicationRequest":
            rows.extend(extract_medication_request(resource))

    return pd.DataFrame(rows)
def build_wire_from_fhir(
    expected: pd.DataFrame,
    scenario: dict[str, Any],
    bundle_dir: Path,
) -> pd.DataFrame:
    """Build the exchange wire representation from the generated FHIR bundles.

    Authorized clinical values are read from FHIR rather than copied directly
    from EXPECTED_EXCHANGE.

    Consent-excluded elements are retained only as internal placeholders so
    clean_received() can create withholding notices and the synthetic failure
    injector can test unauthorized disclosure.
    """

    # ------------------------------------------------------------------
    # 1. Read the clinical payload back from the actual FHIR JSON files.
    # ------------------------------------------------------------------
    parsed = parse_fhir_bundles(bundle_dir)

    key_columns = [
        "patient_id",
        "encounter_id",
        "group_id",
        "element_group",
        "element_name",
    ]

    # ------------------------------------------------------------------
    # 2. Make sure every authorized expected element exists exactly once
    #    in the reconstructed FHIR payload.
    # ------------------------------------------------------------------
    authorized_expected = expected[expected["authorized"]].copy()

    if parsed.duplicated(key_columns).any():
        raise ValueError(
            "FHIR reconstruction produced duplicate clinical element keys."
        )

    if authorized_expected.duplicated(key_columns).any():
        raise ValueError(
            "EXPECTED_EXCHANGE contains duplicate authorized element keys."
        )

    expected_keys = {
        tuple(row[column] for column in key_columns)
        for row in authorized_expected.to_dict("records")
    }

    parsed_keys = {
        tuple(row[column] for column in key_columns)
        for row in parsed.to_dict("records")
    }

    missing_from_fhir = expected_keys - parsed_keys
    unexpected_in_fhir = parsed_keys - expected_keys

    if missing_from_fhir:
        raise ValueError(
            f"FHIR reconstruction is missing {len(missing_from_fhir)} "
            "authorized expected elements."
        )

    if unexpected_in_fhir:
        raise ValueError(
            f"FHIR reconstruction contains {len(unexpected_in_fhir)} "
            "unexpected clinical elements."
        )

    # Lookup containing the value that ACTUALLY came back from FHIR.
    parsed_value_by_key = {
        tuple(row[column] for column in key_columns): row["element_value"]
        for row in parsed.to_dict("records")
    }

    # ------------------------------------------------------------------
    # 3. Load the same rendering/transmission rules used by the original
    #    destination simulation.
    # ------------------------------------------------------------------
    contract = load_contract()

    rendering = scenario["rendering"]
    transmission = scenario["transmission"]

    rng = random.Random(
        int(scenario["generation"]["random_seed"]) + 1
    )

    code_case = rendering.get("code_case", "upper")
    dose_unit = rendering.get("dose_unit", "mg")
    frequency_style = rendering.get("frequency_style", "free_text")

    base_latency = int(transmission["base_latency_minutes"])
    jitter = int(transmission["latency_jitter_minutes"])

    rows: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # 4. Walk through EXPECTED_EXCHANGE in its original order.
    #
    #    IMPORTANT:
    #    Authorized value   -> comes from FHIR
    #    Unauthorized value -> retained only as synthetic experiment
    #                          metadata until clean_received() blanks it.
    # ------------------------------------------------------------------
    for record in expected.to_dict("records"):

        key = tuple(record[column] for column in key_columns)

        if bool(record["authorized"]):
            value = parsed_value_by_key[key]
        else:
            value = record["element_value"]

        # Preserve Scenario A/B destination representation differences.
        element = contract.element(record["element_name"])

        if (
            element.datatype in _CODE_DATATYPES
            and record["element_name"] != "medication_frequency"
        ):
            value = str(value)
            value = (
                value.lower()
                if code_case == "lower"
                else value.upper()
            )

        elif record["element_name"] == "medication_dose":
            value = _render_dose(str(value), dose_unit)

        elif record["element_name"] == "medication_frequency":
            value = _render_frequency(
                str(value),
                frequency_style,
            )

        else:
            value = str(value)

        # Preserve the existing deterministic transmission simulation.
        encounter_dt = datetime.fromisoformat(
            record["encounter_datetime"]
        )

        sent = encounter_dt + timedelta(
            minutes=rng.randint(1, 30)
        )

        received = sent + timedelta(
            minutes=base_latency + rng.randint(0, jitter)
        )

        rows.append({
            "exchange_element_id": record["element_uid"],
            "scenario_id": record["scenario_id"],
            "patient_id": record["patient_id"],
            "encounter_id": record["encounter_id"],
            "group_id": record["group_id"],
            "element_group": record["element_group"],
            "element_name": record["element_name"],

            # For authorized records this value came from FHIR.
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