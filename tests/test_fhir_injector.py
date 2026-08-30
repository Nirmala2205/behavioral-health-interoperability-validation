import json


import pandas as pd
import pytest

from inject_failures.fhir_injector import (
    inject_fhir_element_loss,
    inject_fhir_numeric_value,
    inject_fhir_semantic_code_degradation,
    inject_fhir_wrong_patient_linkage,
)
from config_loader import load_scenario
from generate.synthetic_source import generate_source_truth
from transform.destination import clean_received
from transform.expected_exchange import build_expected_exchange
from transform.fhir_builder import build_bundles
from transform.fhir_receiver import build_wire_from_fhir
from validate.engine import validate


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

def test_fhir_numeric_failure_is_detected_end_to_end(tmp_path):
    scenario = load_scenario("A")

    source_truth, patients = generate_source_truth(scenario)
    expected = build_expected_exchange(
        source_truth,
        patients,
    )

    build_bundles(
        expected,
        patients,
        tmp_path,
    )

    ledger = inject_fhir_numeric_value(
        tmp_path,
        expected,
        "A",
    )

    wire = build_wire_from_fhir(
        expected,
        scenario,
        tmp_path,
    )

    received = clean_received(wire)

    results = validate(
        expected,
        received,
        "A-fhir-integration-test",
    )

    target_uid = ledger.iloc[0]["target_element_uid"]

    target = results[
        results["element_uid"] == target_uid
    ]

    assert len(target) == 1

    row = target.iloc[0]

    assert row["status"] == "FAIL"
    assert row["verdict"] == "value_mismatch"
    assert row["dimension"] == "fidelity"
    assert row["expected_value"] != row["received_value"] 


def test_inject_fhir_semantic_code_degradation_changes_condition(tmp_path):
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "P1-E01-DX1",
                    "code": {
                        "coding": [{
                            "system": "http://hl7.org/fhir/sid/icd-10-cm",
                            "code": "F41.1",
                            "display": "Generalized anxiety disorder",
                        }]
                    },
                    "subject": {
                        "reference": "Patient/P1",
                    },
                    "encounter": {
                        "reference": "Encounter/P1-E01",
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
            "element_uid": "A:P1:P1-E01:DX1:diagnosis_code",
            "scenario_id": "A",
            "patient_id": "P1",
            "encounter_id": "P1-E01",
            "group_id": "DX1",
            "element_group": "diagnosis",
            "element_name": "diagnosis_code",
            "element_value": "F41.1",
            "code_system": "http://hl7.org/fhir/sid/icd-10-cm",
            "authorized": True,
        }
    ])

    ledger = inject_fhir_semantic_code_degradation(
        tmp_path,
        expected,
        "A",
    )

    mutated_bundle = json.loads(
        bundle_path.read_text(encoding="utf-8")
    )

    condition = mutated_bundle["entry"][0]["resource"]
    mutated_code = condition["code"]["coding"][0]["code"]

    assert mutated_code == "F41.9"

    assert len(ledger) == 1
    assert ledger.iloc[0]["failure_stage"] == "fhir"
    assert ledger.iloc[0]["failure_type"] == "degrade_code"
    assert ledger.iloc[0]["expected_detection"] == "semantic_degraded"
    assert ledger.iloc[0]["original_value"] == "F41.1"
    assert ledger.iloc[0]["injected_value"] == "F41.9"   

def test_fhir_semantic_failure_is_detected_end_to_end(tmp_path):
    scenario = load_scenario("A")

    source_truth, patients = generate_source_truth(scenario)
    expected = build_expected_exchange(
        source_truth,
        patients,
    )

    build_bundles(
        expected,
        patients,
        tmp_path,
    )

    ledger = inject_fhir_semantic_code_degradation(
        tmp_path,
        expected,
        "A",
    )

    wire = build_wire_from_fhir(
        expected,
        scenario,
        tmp_path,
    )

    received = clean_received(wire)

    results = validate(
        expected,
        received,
        "A-fhir-semantic-integration-test",
    )

    target_uid = ledger.iloc[0]["target_element_uid"]

    target = results[
        results["element_uid"] == target_uid
    ]

    assert len(target) == 1

    row = target.iloc[0]

    assert row["status"] == "FAIL"
    assert row["verdict"] == "semantic_degraded"
    assert row["dimension"] == "semantic"
    assert row["expected_value"] != row["received_value"]     

def test_inject_fhir_element_loss_removes_effective_datetime(tmp_path):
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "P1-E01-OBS1",
                    "subject": {
                        "reference": "Patient/P1",
                    },
                    "encounter": {
                        "reference": "Encounter/P1-E01",
                    },
                    "effectiveDateTime": "2026-01-15T10:30:00Z",
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

    expected = pd.DataFrame([{
        "element_uid": "A:P1:P1-E01:OBS1:assessment_datetime",
        "scenario_id": "A",
        "patient_id": "P1",
        "encounter_id": "P1-E01",
        "group_id": "OBS1",
        "element_group": "assessment",
        "element_name": "assessment_datetime",
        "element_value": "2026-01-15T10:30:00Z",
        "authorized": True,
    }])

    ledger = inject_fhir_element_loss(
        tmp_path,
        expected,
        "A",
    )

    mutated_bundle = json.loads(
        bundle_path.read_text(encoding="utf-8")
    )

    observation = mutated_bundle["entry"][0]["resource"]

    assert "effectiveDateTime" not in observation

    assert len(ledger) == 1
    assert ledger.iloc[0]["failure_stage"] == "fhir"
    assert ledger.iloc[0]["failure_type"] == "drop_subfield"
    assert ledger.iloc[0]["expected_detection"] == "subfield_dropped"
    assert ledger.iloc[0]["target_element_uid"] == (
        "A:P1:P1-E01:OBS1:assessment_datetime"
    )
    assert ledger.iloc[0]["original_value"] == "2026-01-15T10:30:00Z"
    assert pd.isna(ledger.iloc[0]["injected_value"])


def test_fhir_element_loss_is_detected_end_to_end(tmp_path):
    scenario = load_scenario("A")

    source_truth, patients = generate_source_truth(scenario)
    expected = build_expected_exchange(
        source_truth,
        patients,
    )

    build_bundles(
        expected,
        patients,
        tmp_path,
    )

    ledger = inject_fhir_element_loss(
        tmp_path,
        expected,
        "A",
    )

    wire = build_wire_from_fhir(
        expected,
        scenario,
        tmp_path,
        allow_missing_authorized=True,
    )

    received = clean_received(wire)

    results = validate(
        expected,
        received,
        "A-fhir-element-loss-integration-test",
    )

    target_uid = ledger.iloc[0]["target_element_uid"]

    target = results[
        results["element_uid"] == target_uid
    ]

    assert len(target) == 1

    row = target.iloc[0]

    assert row["status"] == "FAIL"
    assert row["verdict"] == "subfield_dropped"
    assert row["dimension"] == "fidelity"
    assert row["received_value"] == ""

def test_inject_fhir_wrong_patient_linkage_changes_condition_subject(
    tmp_path,
):
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "P1-E01-DX1",
                    "code": {
                        "coding": [{
                            "system": "http://hl7.org/fhir/sid/icd-10-cm",
                            "code": "F41.1",
                            "display": "Generalized anxiety disorder",
                        }]
                    },
                    "subject": {
                        "reference": "Patient/P1",
                    },
                    "encounter": {
                        "reference": "Encounter/P1-E01",
                    },
                    "onsetDateTime": "2026-01-15",
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
            "element_uid": "A:P1:P1-E01:DX1:diagnosis_code",
            "scenario_id": "A",
            "patient_id": "P1",
            "encounter_id": "P1-E01",
            "group_id": "DX1",
            "element_group": "diagnosis",
            "element_name": "diagnosis_code",
            "element_value": "F41.1",
            "authorized": True,
        },
        {
            "element_uid": "A:P1:P1-E01:DX1:diagnosis_display",
            "scenario_id": "A",
            "patient_id": "P1",
            "encounter_id": "P1-E01",
            "group_id": "DX1",
            "element_group": "diagnosis",
            "element_name": "diagnosis_display",
            "element_value": "Generalized anxiety disorder",
            "authorized": True,
        },
        {
            "element_uid": "A:P1:P1-E01:DX1:diagnosis_onset",
            "scenario_id": "A",
            "patient_id": "P1",
            "encounter_id": "P1-E01",
            "group_id": "DX1",
            "element_group": "diagnosis",
            "element_name": "diagnosis_onset",
            "element_value": "2026-01-15",
            "authorized": True,
        },
        {
            "element_uid": "A:P2:P2-E01:ENC:encounter_class",
            "scenario_id": "A",
            "patient_id": "P2",
            "encounter_id": "P2-E01",
            "group_id": "ENC",
            "element_group": "encounter",
            "element_name": "encounter_class",
            "element_value": "AMB",
            "authorized": True,
        },
    ])

    ledger = inject_fhir_wrong_patient_linkage(
        tmp_path,
        expected,
        "A",
    )

    mutated_bundle = json.loads(
        bundle_path.read_text(encoding="utf-8")
    )

    condition = mutated_bundle["entry"][0]["resource"]

    assert condition["subject"]["reference"] == "Patient/P2"
    assert condition["encounter"]["reference"] == "Encounter/P1-E01"
    assert condition["code"]["coding"][0]["code"] == "F41.1"

    assert len(ledger) == 3
    assert set(ledger["failure_stage"]) == {"fhir"}
    assert set(ledger["failure_type"]) == {
        "relink_wrong_patient"
    }
    assert set(ledger["expected_detection"]) == {
        "patient_linkage"
    }
    assert set(ledger["original_value"]) == {"P1"}
    assert set(ledger["injected_value"]) == {"P2"}
    assert set(ledger["target_element_uid"]) == {
        "A:P1:P1-E01:DX1:diagnosis_code",
        "A:P1:P1-E01:DX1:diagnosis_display",
        "A:P1:P1-E01:DX1:diagnosis_onset",
    }

def test_fhir_wrong_patient_linkage_is_detected_end_to_end(
    tmp_path,
):
    scenario = load_scenario("A")

    source_truth, patients = generate_source_truth(scenario)
    expected = build_expected_exchange(
        source_truth,
        patients,
    )

    build_bundles(
        expected,
        patients,
        tmp_path,
    )

    ledger = inject_fhir_wrong_patient_linkage(
        tmp_path,
        expected,
        "A",
    )

    wire = build_wire_from_fhir(
        expected,
        scenario,
        tmp_path,
        allow_patient_linkage_corruption=True,
    )

    received = clean_received(wire)

    results = validate(
        expected,
        received,
        "A-fhir-patient-linkage-integration-test",
    )

    targets = results[
        results["element_uid"].isin(
            ledger["target_element_uid"]
        )
    ]

    assert len(targets) == len(ledger)
    assert set(targets["status"]) == {"FAIL"}
    assert set(targets["verdict"]) == {"patient_linkage"}
    assert set(targets["dimension"]) == {"linkage"}

    injected_patient_id = ledger.iloc[0]["injected_value"]

    assert set(targets["received_patient_id"]) == {
        injected_patient_id
    }
    assert set(targets["patient_id"]) != {
        injected_patient_id
    }