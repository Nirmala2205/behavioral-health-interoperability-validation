"""Controlled failure injection directly into generated FHIR bundles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def inject_fhir_numeric_value(
    bundle_dir: Path,
    expected: pd.DataFrame,
    scenario_id: str,
    delta: float = 10,
) -> pd.DataFrame:
    """Alter one authorized assessment score inside a FHIR Observation.

    The resource identity and linkage are preserved. Only the numeric score
    carried in Observation.valueQuantity.value is changed.

    Returns a one-row ground-truth ledger describing the injected failure.
    """

    eligible = expected[
        (expected["authorized"])
        & (expected["element_name"] == "assessment_score")
    ]

    if eligible.empty:
        raise ValueError(
            "No authorized assessment_score is available for FHIR injection."
        )

    target = eligible.iloc[0]

    patient_id = str(target["patient_id"])
    encounter_id = str(target["encounter_id"])
    group_id = str(target["group_id"])

    bundle_path = bundle_dir / f"{patient_id}-exchange.json"

    if not bundle_path.exists():
        raise FileNotFoundError(
            f"FHIR bundle not found: {bundle_path}"
        )

    bundle: dict[str, Any] = json.loads(
        bundle_path.read_text(encoding="utf-8")
    )

    target_resource_id = f"{encounter_id}-{group_id}"

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        if (
            resource.get("resourceType") == "Observation"
            and resource.get("id") == target_resource_id
        ):
            value_quantity = resource.get("valueQuantity", {})
            original_value = value_quantity.get("value")

            if original_value is None:
                raise ValueError(
                    "Target Observation has no numeric valueQuantity.value."
                )

            injected_value = float(original_value) + delta

            if injected_value.is_integer():
                injected_value = int(injected_value)

            value_quantity["value"] = injected_value

            bundle_path.write_text(
                json.dumps(bundle, indent=2),
                encoding="utf-8",
            )

            return pd.DataFrame([{
                "injection_id": f"{scenario_id}-FHIR-INJ0001",
                "scenario_id": scenario_id,
                "failure_stage": "fhir",
                "failure_type": "alter_numeric_value",
                "expected_detection": "value_mismatch",
                "target_element_uid": target["element_uid"],
                "target_patient_id": patient_id,
                "target_encounter_id": encounter_id,
                "element_name": target["element_name"],
                "element_group": target["element_group"],
                "original_value": str(original_value),
                "injected_value": str(injected_value),
                "detail": (
                    "Assessment score altered directly in "
                    "FHIR Observation.valueQuantity.value."
                ),
            }])

    raise ValueError(
        f"Target Observation {target_resource_id} was not found "
        f"in {bundle_path.name}."
    )
