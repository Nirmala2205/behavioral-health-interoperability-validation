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


def inject_fhir_semantic_code_degradation(
    bundle_dir: Path,
    expected: pd.DataFrame,
    scenario_id: str,
) -> pd.DataFrame:
    """Replace one diagnosis code with a documented less-specific code in FHIR."""

    from config_loader import load_equivalence

    equivalence = load_equivalence()

    eligible = expected[
        (expected["authorized"])
        & (expected["element_name"] == "diagnosis_code")
    ]

    for _, target in eligible.iterrows():
        original_value = str(target["element_value"])
        code_system = str(target["code_system"])

        broader_codes = equivalence.broader_codes(
            code_system,
            original_value,
        )

        if not broader_codes:
            continue

        injected_value = broader_codes[0]

        patient_id = str(target["patient_id"])
        encounter_id = str(target["encounter_id"])
        group_id = str(target["group_id"])

        bundle_path = bundle_dir / f"{patient_id}-exchange.json"

        if not bundle_path.exists():
            continue

        bundle: dict[str, Any] = json.loads(
            bundle_path.read_text(encoding="utf-8")
        )

        target_resource_id = f"{encounter_id}-{group_id}"

        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})

            if (
                resource.get("resourceType") == "Condition"
                and resource.get("id") == target_resource_id
            ):
                coding = resource.get("code", {}).get("coding", [])

                if not coding:
                    continue

                coding[0]["code"] = injected_value

                bundle_path.write_text(
                    json.dumps(bundle, indent=2),
                    encoding="utf-8",
                )

                return pd.DataFrame([{
                    "injection_id": f"{scenario_id}-FHIR-INJ0002",
                    "scenario_id": scenario_id,
                    "failure_stage": "fhir",
                    "failure_type": "degrade_code",
                    "expected_detection": "semantic_degraded",
                    "target_element_uid": target["element_uid"],
                    "target_patient_id": patient_id,
                    "target_encounter_id": encounter_id,
                    "element_name": target["element_name"],
                    "element_group": target["element_group"],
                    "original_value": original_value,
                    "injected_value": injected_value,
                    "detail": (
                        "Diagnosis code replaced directly in FHIR Condition "
                        "with a documented less-specific mapping."
                    ),
                }])

    raise ValueError(
        "No authorized diagnosis_code with a documented less-specific mapping "
        "is available for FHIR semantic injection."
    )

def inject_fhir_element_loss(
    bundle_dir: Path,
    expected: pd.DataFrame,
    scenario_id: str,
) -> pd.DataFrame:
    """Remove one optional assessment datetime directly from FHIR."""

    eligible = expected[
        (expected["authorized"])
        & (expected["element_name"] == "assessment_datetime")
    ]

    if eligible.empty:
        raise ValueError(
            "No authorized assessment_datetime is available "
            "for FHIR element-loss injection."
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
            original_value = resource.get("effectiveDateTime")

            if original_value is None:
                raise ValueError(
                    "Target Observation has no effectiveDateTime."
                )

            del resource["effectiveDateTime"]

            bundle_path.write_text(
                json.dumps(bundle, indent=2),
                encoding="utf-8",
            )

            return pd.DataFrame([{
                "injection_id": f"{scenario_id}-FHIR-INJ0003",
                "scenario_id": scenario_id,
                "failure_stage": "fhir",
                "failure_type": "drop_subfield",
                "expected_detection": "subfield_dropped",
                "target_element_uid": target["element_uid"],
                "target_patient_id": patient_id,
                "target_encounter_id": encounter_id,
                "element_name": target["element_name"],
                "element_group": target["element_group"],
                "original_value": str(original_value),
                "injected_value": None,
                "detail": (
                    "Optional assessment datetime removed directly from "
                    "FHIR Observation.effectiveDateTime."
                ),
            }])

    raise ValueError(
        f"Target Observation {target_resource_id} was not found "
        f"in {bundle_path.name}."
    )

def inject_fhir_wrong_patient_linkage(
    bundle_dir: Path,
    expected: pd.DataFrame,
    scenario_id: str,
) -> pd.DataFrame:
    """Attach one Condition resource to the wrong patient in FHIR."""

    eligible = expected[
        (expected["authorized"])
        & (expected["element_group"] == "diagnosis")
    ]

    if eligible.empty:
        raise ValueError(
            "No authorized diagnosis group is available "
            "for FHIR patient-linkage injection."
        )

    target = eligible.iloc[0]

    patient_id = str(target["patient_id"])
    encounter_id = str(target["encounter_id"])
    group_id = str(target["group_id"])

    other_patients = sorted({
        str(value)
        for value in expected["patient_id"].dropna().unique()
        if str(value) != patient_id
    })

    if not other_patients:
        raise ValueError(
            "FHIR patient-linkage injection requires at least two patients."
        )

    injected_patient_id = other_patients[0]
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
            resource.get("resourceType") == "Condition"
            and resource.get("id") == target_resource_id
        ):
            subject = resource.get("subject", {})
            original_reference = subject.get("reference")

            if original_reference != f"Patient/{patient_id}":
                raise ValueError(
                    "Target Condition does not reference the expected patient."
                )

            subject["reference"] = f"Patient/{injected_patient_id}"

            bundle_path.write_text(
                json.dumps(bundle, indent=2),
                encoding="utf-8",
            )

            affected = expected[
                (expected["authorized"])
                & (expected["patient_id"].astype(str) == patient_id)
                & (expected["encounter_id"].astype(str) == encounter_id)
                & (expected["group_id"].astype(str) == group_id)
                & (expected["element_group"] == "diagnosis")
            ]

            ledger_rows = []

            for index, (_, row) in enumerate(
                affected.iterrows(),
                start=4,
            ):
                ledger_rows.append({
                    "injection_id": (
                        f"{scenario_id}-FHIR-INJ{index:04d}"
                    ),
                    "scenario_id": scenario_id,
                    "failure_stage": "fhir",
                    "failure_type": "relink_wrong_patient",
                    "expected_detection": "patient_linkage",
                    "target_element_uid": row["element_uid"],
                    "target_patient_id": patient_id,
                    "target_encounter_id": encounter_id,
                    "element_name": row["element_name"],
                    "element_group": row["element_group"],
                    "original_value": patient_id,
                    "injected_value": injected_patient_id,
                    "detail": (
                        "FHIR Condition subject.reference changed to "
                        "a different patient while resource identity, "
                        "encounter, and clinical values were preserved."
                    ),
                })

            return pd.DataFrame(ledger_rows)

    raise ValueError(
        f"Target Condition {target_resource_id} was not found "
        f"in {bundle_path.name}."
    )