import json


import pandas as pd
import pytest

from inject_failures.fhir_injector import inject_fhir_numeric_value


def test_inject_fhir_numeric_value_changes_observation(tmp_path):
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "P1-E01-OBS1",
                    "subject": {"reference": "Patient/P1"},
                    "encounter": {"reference": "Encounter/P1-E01"},
                    "valueQuantity": {
                        "value": 9,
                        "system": "http://unitsofmeasure.org",
                        "code": "{score}",
                    },
                }
            }
        ],
    }

    bundle_path = tmp_path / "P1-exchange.json"
    bundle_path.write_text(
        json.dumps(bundle),
        encoding="utf-8",
    )

    expected = pd.DataFrame([
        {
            "element_uid": "A:P1:P1-E01:OBS1:assessment_score",
            "scenario_id": "A",
            "patient_id": "P1",
            "encounter_id": "P1-E01",
            "group_id": "OBS1",
            "element_group": "assessment",
            "element_name": "assessment_score",
            "element_value": "9",
            "authorized": True,
        }
    ])

    ledger = inject_fhir_numeric_value(
        tmp_path,
        expected,
        "A",
    )

    mutated_bundle = json.loads(
        bundle_path.read_text(encoding="utf-8")
    )

    observation = mutated_bundle["entry"][0]["resource"]

    assert observation["valueQuantity"]["value"] == 19

    assert len(ledger) == 1
    assert ledger.iloc[0]["failure_stage"] == "fhir"
    assert ledger.iloc[0]["failure_type"] == "alter_numeric_value"
    assert ledger.iloc[0]["expected_detection"] == "value_mismatch"
    assert ledger.iloc[0]["target_element_uid"] == (
        "A:P1:P1-E01:OBS1:assessment_score"
    )
    assert ledger.iloc[0]["original_value"] == "9"
    assert ledger.iloc[0]["injected_value"] == "19"
    import pytest


def test_inject_fhir_numeric_value_requires_authorized_score(tmp_path):
    expected = pd.DataFrame([
        {
            "element_uid": "A:P1:P1-E01:OBS1:assessment_score",
            "scenario_id": "A",
            "patient_id": "P1",
            "encounter_id": "P1-E01",
            "group_id": "OBS1",
            "element_group": "assessment",
            "element_name": "assessment_score",
            "element_value": "9",
            "authorized": False,
        }
    ])

    with pytest.raises(
        ValueError,
        match="No authorized assessment_score is available for FHIR injection",
    ):
        inject_fhir_numeric_value(
            tmp_path,
            expected,
            "A",
        )    
