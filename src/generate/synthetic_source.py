"""Generate the synthetic behavioral-health SOURCE_TRUTH dataset.

WHY CUSTOM GENERATION RATHER THAN SYNTHEA
------------------------------------------
The blueprint's tool stack allows "Synthea and/or controlled custom synthetic
records." V1 uses controlled custom records, deliberately:

1.  A validation experiment requires *exactly known* ground truth. Synthea
    produces realistic longitudinal records, but reconstructing an
    element-level ground-truth ledger from its output is itself an error-prone
    mapping step -- and an error there would silently corrupt the reference
    standard the whole evaluation depends on.
2.  Synthea's behavioral-health depth is thin relative to what this project
    validates (Part 2 sensitivity segmentation, PHQ-9/GAD-7 instruments,
    consent state). Much of it would have to be synthesized anyway.
3.  Controlled generation makes the dataset auditable at 10-patient scale: a
    reviewer can read the source table and verify the expected set by hand.

Synthea remains the right tool for a later realism extension, and
data/raw/synthea/ is reserved for it. That trade-off is recorded in
docs/methodology/methodology_note.md rather than left as an undocumented
divergence from the plan.

OUTPUT SHAPE
------------
SOURCE_TRUTH is written in long (element-level) form: one row per clinical
element instance. Wide clinical tables read more naturally, but the unit of
validation here is the element, and matching a long table to a long table is
what makes element-level traceability (Blueprint Section 7.1) fall out for
free rather than having to be reconstructed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from config_loader import load_consent_rules, load_contract

ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ACTCODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
GTS = "http://terminology.hl7.org/CodeSystem/v3-GTSAbbreviation"


# ---------------------------------------------------------------------------
# Clinical content pools
# ---------------------------------------------------------------------------
# Small, realistic, and fully enumerated. Every code appearing here also
# appears in config/code_equivalence.yaml, so the semantic dimension has a
# documented relationship available for any code the generator can produce.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiagnosisTemplate:
    code: str
    display: str
    instruments: tuple[str, ...]
    medications: tuple[str, ...]


DIAGNOSES: tuple[DiagnosisTemplate, ...] = (
    DiagnosisTemplate("F32.1", "Major depressive disorder, single episode, moderate",
                      ("PHQ9",), ("312940", "310385")),
    DiagnosisTemplate("F33.1", "Major depressive disorder, recurrent, moderate",
                      ("PHQ9",), ("312940", "856706")),
    DiagnosisTemplate("F41.1", "Generalized anxiety disorder",
                      ("GAD7",), ("312940",)),
    DiagnosisTemplate("F43.10", "Post-traumatic stress disorder, unspecified",
                      ("PHQ9", "GAD7"), ("310385",)),
    DiagnosisTemplate("F31.32", "Bipolar disorder, current episode depressed, moderate",
                      ("PHQ9",), ()),
    # --- Part 2 sensitive -----------------------------------------------------
    DiagnosisTemplate("F10.20", "Alcohol dependence, uncomplicated",
                      ("PHQ9",), ("1116442",)),
    DiagnosisTemplate("F11.20", "Opioid dependence, uncomplicated",
                      ("GAD7",), ("1010600",)),
)

INSTRUMENTS: dict[str, dict[str, Any]] = {
    "PHQ9": {"loinc": "44249-1", "display": "PHQ-9 total score", "max": 27},
    "GAD7": {"loinc": "70274-6", "display": "GAD-7 total score", "max": 21},
}

MEDICATIONS: dict[str, dict[str, Any]] = {
    "312940": {"display": "Sertraline 50 MG Oral Tablet", "dose_mg": 50, "frequency": "daily"},
    "310385": {"display": "Fluoxetine 20 MG Oral Capsule", "dose_mg": 20, "frequency": "daily"},
    "856706": {"display": "Venlafaxine 75 MG ER Oral Tablet", "dose_mg": 75, "frequency": "daily"},
    "1010600": {"display": "Buprenorphine 8 MG / Naloxone 2 MG Sublingual Film",
                "dose_mg": 8, "frequency": "daily"},
    "1116442": {"display": "Naltrexone 380 MG Injection",
                "dose_mg": 380, "frequency": "monthly"},
}

STUDY_WINDOW_START = datetime(
    2026, 3, 2, 8, 0, 0,
    tzinfo=timezone.utc,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _element_uid(scenario_id: str, patient_id: str, encounter_id: str,
                 group_id: str, element_name: str) -> str:
    """Stable, human-readable primary key for one element instance.

    Human-readable on purpose: when a validation result says something failed,
    the identifier itself should tell a reviewer which patient, encounter,
    clinical group, and field are involved without a lookup.
    """
    return f"{scenario_id}:{patient_id}:{encounter_id}:{group_id}:{element_name}"


def _pick_consent_states(rng: random.Random, n: int, mix: dict[str, float]) -> list[str]:
    """Assign consent states by quota rather than by independent sampling.

    Independent sampling at n=10 can easily produce zero part2_restricted
    patients, which would leave the entire consent dimension untested in that
    run. Quota assignment guarantees the mix is actually represented -- a
    property the micro-prototype needs and a large Stage B run does not.
    """
    states: list[str] = []
    for state, share in mix.items():
        states.extend([state] * int(round(share * n)))
    while len(states) < n:
        states.append(max(mix, key=mix.get))
    states = states[:n]
    rng.shuffle(states)
    return states


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_source_truth(scenario: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build SOURCE_TRUTH (long) and the PATIENTS table for one scenario.

    Returns
    -------
    (source_truth, patients)
    """
    contract = load_contract()
    consent_rules = load_consent_rules()

    scenario_id = str(scenario["scenario_id"])
    gen = scenario["generation"]
    rng = random.Random(int(gen["random_seed"]))
    source_system = scenario["source_system"]

    n_patients = int(gen["n_patients"])
    enc_lo, enc_hi = gen["encounters_per_patient"]
    obs_lo, obs_hi = gen["assessments_per_encounter"]
    med_lo, med_hi = gen["medications_per_encounter"]
    crisis_p = float(gen["crisis_encounter_probability"])

    consent_states = _pick_consent_states(rng, n_patients, gen["consent_state_mix"])

    patient_rows: list[dict[str, Any]] = []
    element_rows: list[dict[str, Any]] = []

    for patient_index in range(n_patients):
        patient_id = f"{scenario_id}-P{patient_index + 1:04d}"
        consent_state = consent_states[patient_index]
        patient_rows.append({
            "scenario_id": scenario_id,
            "patient_id": patient_id,
            "consent_state": consent_state,
            "source_system": source_system,
        })

        n_encounters = rng.randint(enc_lo, enc_hi)
        encounter_clock = STUDY_WINDOW_START + timedelta(days=rng.randint(0, 40))

        for encounter_index in range(n_encounters):
            encounter_id = f"{patient_id}-E{encounter_index + 1:02d}"
            encounter_clock += timedelta(days=rng.randint(7, 28),
                                         hours=rng.randint(0, 8))
            encounter_class = "EMER" if rng.random() < crisis_p else "AMB"
            encounter_dt = encounter_clock.replace(minute=rng.choice([0, 15, 30, 45]),
                                                   second=0, microsecond=0)

            def add(group_id: str, element_name: str, value: Any,
                    code_system: str | None, sensitivity: str) -> None:
                element_rows.append({
                    "element_uid": _element_uid(scenario_id, patient_id,
                                                encounter_id, group_id, element_name),
                    "scenario_id": scenario_id,
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "group_id": group_id,
                    "element_group": contract.element(element_name).element_group,
                    "element_name": element_name,
                    "element_value": "" if value is None else str(value),
                    "code_system": code_system or "",
                    "sensitivity_class": sensitivity,
                    "encounter_class": encounter_class,
                    "encounter_datetime": encounter_dt.isoformat(),
                    "source_system": source_system,
                })

            # --- Encounter group: always routine (see consent_rules.yaml) ----
            add("ENC", "encounter_class", encounter_class, ACTCODE, "routine")
            add("ENC", "encounter_datetime", encounter_dt.isoformat(), None, "routine")

            # --- Diagnosis ---------------------------------------------------
            diagnosis = rng.choice(DIAGNOSES)
            dx_sensitivity = consent_rules.classify_diagnosis(diagnosis.code)
            onset = (encounter_dt - timedelta(days=rng.randint(30, 900))).date().isoformat()
            add("DX1", "diagnosis_code", diagnosis.code, ICD10, dx_sensitivity)
            add("DX1", "diagnosis_display", diagnosis.display, None, dx_sensitivity)
            add("DX1", "diagnosis_onset", onset, None, dx_sensitivity)

            # --- Assessments -------------------------------------------------
            n_obs = rng.randint(obs_lo, obs_hi)
            available = list(diagnosis.instruments)
            for obs_index in range(min(n_obs, len(available))):
                instrument = available[obs_index]
                spec = INSTRUMENTS[instrument]
                group_id = f"OBS{obs_index + 1}"
                # Scores skew toward the clinically actionable middle/upper
                # bands, where a corrupted value would actually change care.
                score = rng.randint(int(spec["max"] * 0.3), spec["max"])
                obs_dt = encounter_dt + timedelta(minutes=rng.choice([10, 20, 30]))
                add(group_id, "assessment_code", spec["loinc"], LOINC, dx_sensitivity)
                add(group_id, "assessment_score", score, None, dx_sensitivity)
                add(group_id, "assessment_datetime", obs_dt.isoformat(), None, dx_sensitivity)

            # --- Medications -------------------------------------------------
            n_meds = rng.randint(med_lo, med_hi)
            if n_meds and diagnosis.medications:
                rxnorm = rng.choice(list(diagnosis.medications))
                med = MEDICATIONS[rxnorm]
                med_sensitivity = consent_rules.classify_medication(rxnorm)
                # A medication for a Part 2 diagnosis inherits Part 2
                # sensitivity even if the drug itself is not SUD-specific --
                # prescribing an SSRI is routine, but doing so inside an
                # identified Part 2 episode still reveals the episode.
                if dx_sensitivity == "sud_part2":
                    med_sensitivity = "sud_part2"
                add("MED1", "medication_code", rxnorm, RXNORM, med_sensitivity)
                add("MED1", "medication_dose", f"{med['dose_mg']} mg", None, med_sensitivity)
                add("MED1", "medication_frequency", med["frequency"], GTS, med_sensitivity)

    source_truth = pd.DataFrame(element_rows)
    patients = pd.DataFrame(patient_rows)

    # An empty source table means a config error, not a legitimate result.
    if source_truth.empty:
        raise ValueError(
            f"Scenario {scenario_id} generated zero source elements. Check "
            "generation ranges in the scenario config."
        )

    return source_truth, patients
