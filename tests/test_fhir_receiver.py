import json

from transform.fhir_receiver import (
    extract_encounter,
    extract_condition,
    extract_observation,
    extract_medication_request,
    parse_fhir_bundles,
)


def test_extract_encounter():
    resource = {
        "resourceType": "Encounter",
        "id": "P1-E01",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
        },
        "subject": {"reference": "Patient/P1"},
        "period": {"start": "2026-03-02T08:00:00+00:00"},
    }

    rows = extract_encounter(resource)

    values = {
        row["element_name"]: row["element_value"]
        for row in rows
    }

    assert values["encounter_class"] == "AMB"
    assert values["encounter_datetime"] == "2026-03-02T08:00:00+00:00"


def test_extract_condition():
    resource = {
        "resourceType": "Condition",
        "id": "P1-E01-DX1",
        "code": {
            "coding": [{
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "code": "F32.1",
                "display": "Major depressive disorder, single episode, moderate",
            }]
        },
        "subject": {"reference": "Patient/P1"},
        "encounter": {"reference": "Encounter/P1-E01"},
        "onsetDateTime": "2026-01-15",
    }

    rows = extract_condition(resource)

    values = {
        row["element_name"]: row["element_value"]
        for row in rows
    }

    assert values["diagnosis_code"] == "F32.1"
    assert values["diagnosis_display"] == (
        "Major depressive disorder, single episode, moderate"
    )
    assert values["diagnosis_onset"] == "2026-01-15"


def test_extract_observation():
    resource = {
        "resourceType": "Observation",
        "id": "P1-E01-OBS1",
        "status": "final",
        "code": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "44249-1",
            }]
        },
        "subject": {"reference": "Patient/P1"},
        "encounter": {"reference": "Encounter/P1-E01"},
        "effectiveDateTime": "2026-03-02T08:10:00+00:00",
        "valueQuantity": {
            "value": 12,
            "system": "http://unitsofmeasure.org",
            "code": "{score}",
        },
    }

    rows = extract_observation(resource)

    values = {
        row["element_name"]: row["element_value"]
        for row in rows
    }

    assert values["assessment_code"] == "44249-1"
    assert values["assessment_score"] == "12"
    assert values["assessment_datetime"] == "2026-03-02T08:10:00+00:00"


def test_extract_medication_request_prefers_frequency_text():
    resource = {
        "resourceType": "MedicationRequest",
        "id": "P1-E01-MED1",
        "medicationCodeableConcept": {
            "coding": [{
                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                "code": "312940",
                "display": "Sertraline 50 MG Oral Tablet",
            }]
        },
        "subject": {"reference": "Patient/P1"},
        "encounter": {"reference": "Encounter/P1-E01"},
        "dosageInstruction": [{
            "doseAndRate": [{
                "doseQuantity": {
                    "value": 50,
                    "unit": "mg",
                    "system": "http://unitsofmeasure.org",
                    "code": "mg",
                }
            }],
            "timing": {
                "code": {
                    "text": "daily",
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v3-GTSAbbreviation",
                        "code": "QD",
                    }],
                }
            },
        }],
    }

    rows = extract_medication_request(resource)

    values = {
        row["element_name"]: row["element_value"]
        for row in rows
    }

    assert values["medication_code"] == "312940"
    assert values["medication_dose"] == "50 mg"
    assert values["medication_frequency"] == "daily"


def test_extract_medication_request_falls_back_to_frequency_code():
    resource = {
        "resourceType": "MedicationRequest",
        "id": "P1-E01-MED1",
        "medicationCodeableConcept": {
            "coding": [{
                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                "code": "312940",
            }]
        },
        "subject": {"reference": "Patient/P1"},
        "encounter": {"reference": "Encounter/P1-E01"},
        "dosageInstruction": [{
            "timing": {
                "code": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v3-GTSAbbreviation",
                        "code": "QD",
                    }]
                }
            },
        }],
    }

    rows = extract_medication_request(resource)

    values = {
        row["element_name"]: row["element_value"]
        for row in rows
    }

    assert values["medication_frequency"] == "QD"
    import json

from transform.fhir_receiver import parse_fhir_bundles


def test_parse_fhir_bundles(tmp_path):
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "fullUrl": "https://example.org/fhir/Patient/P1",
                "resource": {
                    "resourceType": "Patient",
                    "id": "P1",
                },
            },
            {
                "fullUrl": "https://example.org/fhir/Encounter/P1-E01",
                "resource": {
                    "resourceType": "Encounter",
                    "id": "P1-E01",
                    "status": "finished",
                    "class": {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                        "code": "AMB",
                    },
                    "subject": {
                        "reference": "Patient/P1",
                    },
                    "period": {
                        "start": "2026-03-02T08:00:00+00:00",
                    },
                },
            },
            {
                "fullUrl": "https://example.org/fhir/Condition/P1-E01-DX1",
                "resource": {
                    "resourceType": "Condition",
                    "id": "P1-E01-DX1",
                    "code": {
                        "coding": [{
                            "system": "http://hl7.org/fhir/sid/icd-10-cm",
                            "code": "F32.1",
                            "display": (
                                "Major depressive disorder, "
                                "single episode, moderate"
                            ),
                        }]
                    },
                    "subject": {
                        "reference": "Patient/P1",
                    },
                    "encounter": {
                        "reference": "Encounter/P1-E01",
                    },
                    "onsetDateTime": "2026-01-15",
                },
            },
        ],
    }

    bundle_path = tmp_path / "P1-exchange.json"
    bundle_path.write_text(
        json.dumps(bundle),
        encoding="utf-8",
    )

    parsed = parse_fhir_bundles(tmp_path)

    values = {
        row["element_name"]: row["element_value"]
        for row in parsed.to_dict("records")
    }

    assert values["encounter_class"] == "AMB"
    assert values["encounter_datetime"] == "2026-03-02T08:00:00+00:00"
    assert values["diagnosis_code"] == "F32.1"
    assert values["diagnosis_onset"] == "2026-01-15"
    