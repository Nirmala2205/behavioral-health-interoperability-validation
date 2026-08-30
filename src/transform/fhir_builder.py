"""Build the FHIR R4 representation of the authorized exchange content.

WHERE THIS SITS, AND WHY IT IS NOT THE VALIDATION
--------------------------------------------------
Blueprint Section 9 is explicit that FHIR conformance validation and this
project's end-to-end validation are different things, and warns against
confusing them. The distinction is the project's central scientific claim, so
it is worth stating precisely:

    A FHIR resource can be 100% structurally and profile-valid while carrying
    a clinically wrong or incomplete representation.

An Observation with valueQuantity 8 where the patient scored 18 is perfectly
conformant FHIR. A Condition coded F32.9 where the source said F32.1 is
perfectly conformant FHIR. A validator that checks structure will pass both.
That gap -- between "well-formed" and "faithful" -- is what this framework
measures, and it is why conformance checking is a complementary layer here
rather than the answer.

Generated resources are aligned to the element choices in USCDI+ Behavioral
Health and the US Behavioral Health Profiles IG (v0.1.0, FHIR R4). They are not
claimed to be profile-conformant: asserting conformance requires running the
official HL7 validator against the published StructureDefinitions, which is a
separate step documented in docs/methodology/methodology_note.md. Claiming
conformance without running the validator would be exactly the kind of
unverified assertion the project is meant to argue against.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _full_url(resource_type: str, resource_id: str) -> str:
    """Return a deterministic synthetic absolute URL for a FHIR resource."""
    return f"https://example.org/fhir/{resource_type}/{resource_id}"


FHIR_VERSION = "4.0.1"

_LOINC = "http://loinc.org"
_ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
_RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
_ACTCODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"


def _group_values(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {row["element_name"]: row["element_value"] for row in rows}


def _patient_resource(patient_id: str, consent_state: str) -> dict[str, Any]:
    return {
        "resourceType": "Patient",
        "id": patient_id,
        "meta": {"tag": [{
            "system": "urn:bhiv:synthetic",
            "code": "SYNTHETIC",
            "display": "Synthetic record. Not a real person. No PHI.",
        }]},
        "identifier": [{
            "system": "urn:bhiv:patient",
            "value": patient_id,
        }],
        "active": True,
    }


def _consent_resource(patient_id: str, consent_state: str,
                      authorized_classes: list[str]) -> dict[str, Any]:
    """A Consent resource recording what this patient authorized to move.

    Included so the expected-exchange denominator travels with the bundle
    rather than living only in the project's own tables. A receiving system
    that gets the Consent alongside the clinical content can, in principle,
    perform the same authorized-vs-missing distinction the framework performs.
    """
    return {
        "resourceType": "Consent",
        "id": f"{patient_id}-consent",
        "status": "active",
        "scope": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/consentscope",
            "code": "patient-privacy",
        }]},
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "IDSCL",
            "display": "information disclosure",
        }]}],
        "patient": {"reference": f"Patient/{patient_id}"},
        "policyRule": {"text": (
            "Simplified synthetic consent model. Authorizes sensitivity "
            f"classes: {', '.join(authorized_classes) or '(none)'}. "
            "Not a compliance artifact."
        )},
        "provision": {
            "type": "permit",
            "securityLabel": [
                {"system": "urn:bhiv:sensitivity", "code": sensitivity}
                for sensitivity in authorized_classes
            ],
        },
    }


def _encounter_resource(patient_id: str, encounter_id: str,
                        values: dict[str, str]) -> dict[str, Any]:
    return {
        "resourceType": "Encounter",
        "id": encounter_id,
        "status": "finished",
        "class": {
            "system": _ACTCODE,
            "code": values.get("encounter_class", "AMB"),
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": values.get("encounter_datetime")},
    }


def _condition_resource(patient_id: str, encounter_id: str, group_id: str,
                        values: dict[str, str]) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "Condition",
        "id": f"{encounter_id}-{group_id}",
        "clinicalStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": "active",
        }]},
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
            "code": "encounter-diagnosis",
        }]}],
        "code": {"coding": [{
            "system": _ICD10,
            "code": values.get("diagnosis_code"),
            "display": values.get("diagnosis_display"),
        }]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
    }
    if values.get("diagnosis_onset"):
        resource["onsetDateTime"] = values["diagnosis_onset"]
    return resource


def _observation_resource(patient_id: str, encounter_id: str, group_id: str,
                          values: dict[str, str]) -> dict[str, Any]:
    score = values.get("assessment_score")
    return {
        "resourceType": "Observation",
        "id": f"{encounter_id}-{group_id}",
        "status": "final",
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
            "code": "survey",
        }]}],
        "code": {"coding": [{
            "system": _LOINC,
            "code": values.get("assessment_code"),
        }]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "effectiveDateTime": values.get("assessment_datetime"),
        "valueQuantity": {
            "value": float(score) if score not in (None, "") else None,
            "system": "http://unitsofmeasure.org",
            "code": "{score}",
        },
    }


def _medication_request_resource(patient_id: str, encounter_id: str, group_id: str,
                                 values: dict[str, str]) -> dict[str, Any]:
    from config_loader import load_equivalence

    dose_text = values.get("medication_dose", "")
    dose_quantity: dict[str, Any] | None = None
    if dose_text:
        parts = dose_text.split()
        if len(parts) == 2:
            dose_quantity = {
                "value": float(parts[0]),
                "unit": parts[1],
                "system": "http://unitsofmeasure.org",
                "code": parts[1],
            }

    dosage: dict[str, Any] = {"text": " ".join(
        filter(None, [dose_text, values.get("medication_frequency", "")])
    ).strip()}
    if dose_quantity:
        dosage["doseAndRate"] = [{"doseQuantity": dose_quantity}]

    if values.get("medication_frequency"):
        frequency_text = values["medication_frequency"]
        canonical_frequency = load_equivalence().canonical_frequency(
            frequency_text
        )

        timing_code: dict[str, Any] = {
            "text": frequency_text,
        }

        if canonical_frequency:
            timing_code["coding"] = [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-GTSAbbreviation",
                "code": canonical_frequency,
            }]

        dosage["timing"] = {
            "code": timing_code,
        }
    return {
        "resourceType": "MedicationRequest",
        "id": f"{encounter_id}-{group_id}",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {"coding": [{
            "system": _RXNORM,
            "code": values.get("medication_code"),
        }]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "dosageInstruction": [dosage],
    }


_BUILDERS = {
    "encounter": _encounter_resource,
    "diagnosis": _condition_resource,
    "assessment": _observation_resource,
    "medication": _medication_request_resource,
}


def build_bundles(expected: pd.DataFrame, patients: pd.DataFrame,
                  output_dir: Path) -> list[Path]:
    """Write one FHIR R4 collection Bundle per patient.

    Only authorized content is included. The bundle is the wire representation
    of what consent permitted to move -- placing restricted content in it and
    filtering later would model a design that leaks by default.
    """
    from config_loader import load_consent_rules

    consent_rules = load_consent_rules()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Each call creates one complete corpus. Remove bundle files left by a
    # previous run so changed patient counts or consent states cannot leak
    # stale clinical resources into the new exchange.
    for stale_bundle in output_dir.glob("*-exchange.json"):
        stale_bundle.unlink()

    written: list[Path] = []

    authorized = expected[expected["authorized"]]
    consent_by_patient = dict(
        zip(patients["patient_id"], patients["consent_state"])
    )

    for patient_id, patient_rows in authorized.groupby("patient_id"):
        consent_state = consent_by_patient[patient_id]

        patient_resource = _patient_resource(
            patient_id,
            consent_state,
        )

        consent_resource = _consent_resource(
            patient_id,
            consent_state,
            consent_rules.states.get(consent_state, []),
        )

        entries: list[dict[str, Any]] = [
            {
                "fullUrl": _full_url(
                    patient_resource["resourceType"],
                    patient_resource["id"],
                ),
                "resource": patient_resource,
            },
            {
                "fullUrl": _full_url(
                    consent_resource["resourceType"],
                    consent_resource["id"],
                ),
                "resource": consent_resource,
            },
        ]

        for (encounter_id, group_id), group_rows in patient_rows.groupby(
                ["encounter_id", "group_id"], sort=True):
            element_group = group_rows["element_group"].iloc[0]
            builder = _BUILDERS.get(element_group)

            if builder is None:
                continue

            values = _group_values(group_rows.to_dict("records"))

            if element_group == "encounter":
                resource = builder(
                    patient_id,
                    encounter_id,
                    values,
                )
            else:
                resource = builder(
                    patient_id,
                    encounter_id,
                    group_id,
                    values,
                )

            entries.append({
                "fullUrl": _full_url(
                    resource["resourceType"],
                    resource["id"],
                ),
                "resource": resource,
            })

        bundle = {
            "resourceType": "Bundle",
            "id": f"{patient_id}-exchange",
            "meta": {
                "tag": [{
                    "system": "urn:bhiv:synthetic",
                    "code": "SYNTHETIC",
                    "display": "Synthetic data. Not real patient information.",
                }],
                "profile": [],
            },
            "type": "collection",
            "entry": entries,
        }

        path = output_dir / f"{patient_id}-exchange.json"
        path.write_text(
            json.dumps(bundle, indent=2),
            encoding="utf-8",
        )
        written.append(path)

    return written
