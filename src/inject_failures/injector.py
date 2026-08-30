"""Controlled failure injection and the ground-truth ledger.

Blueprint Section 13: "Controlled error injection is what turns the project
from a dashboard into an evaluable prototype." Without a ledger of what was
deliberately broken, a dashboard reporting "500 errors" is unfalsifiable --
there is no way to know whether those are the real errors, or 500 different
ones, or 400 real plus 100 imagined.

MODELING WITHHELD DATA: THE `delivery_status` FIELD
---------------------------------------------------
The destination state distinguishes three conditions, not two:

    delivered        the element arrived, with a value
    withheld_notice  the element did not arrive, and the receiver was told
                     that something was withheld
    (absent)         no row at all -- the receiver has no idea anything is
                     missing

That middle state is what makes two otherwise-identical situations separable:

    * a Part 2 element correctly withheld under a valid restriction
      -> withheld_notice on an element consent did NOT authorize -> PASS
    * an authorized element wrongly withheld by a faulty rule
      -> withheld_notice on an element consent DID authorize
      -> consent_over_restriction

and both are separable from silent technical loss, which leaves no row at all.

This mirrors Data Segmentation for Privacy (DS4P) practice, where a receiving
system is notified that content has been redacted without being told what it
was. It is a simplification -- real notices are usually document- or
section-level rather than element-level -- and the methodology note says so.
Without some such signal, "wrongly withheld" and "technically lost" are
genuinely indistinguishable from the destination, and the framework would have
to report both as missing_element. That would be an honest answer too, but a
less useful one, and the difference matters operationally: one is an IT
problem, the other is a consent-configuration problem.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from config_loader import load_contract, load_equivalence

# Codes used for the "unrelated concept" injection. Chosen from a different
# ICD-10 chapter so no accidental hierarchical relationship exists with any
# behavioral-health code in the generator's pool.
UNRELATED_ICD10 = ["E11.9", "I10", "J45.909", "M54.5"]

# ---------------------------------------------------------------------------
# What the detector SHOULD emit for each injected failure type.
# ---------------------------------------------------------------------------
# The injection vocabulary and the verdict vocabulary are deliberately
# different: an injection describes an action taken on the data
# ("drop_required_element"), a verdict describes what the detector concluded
# ("missing_element"). Keeping them distinct prevents the reference standard
# from being defined in the detector's own terms, which would make the
# evaluation partly circular.
#
# The fixed-count profile states expected_detection explicitly for each entry.
# This table supplies the same mapping for probabilistic mode, where the
# profile is just a rate per failure type. Without it, probabilistic runs would
# score every detection as a misclassification -- reporting 0% classification
# sensitivity on a detector that was working perfectly.
# ---------------------------------------------------------------------------
FAILURE_TYPE_TO_DETECTION = {
    "drop_required_element": "missing_element",
    "drop_subfield": "subfield_dropped",
    "alter_numeric_value": "value_mismatch",
    "degrade_code": "semantic_degraded",
    "replace_code_incorrect": "value_mismatch",
    "relink_wrong_patient": "patient_linkage",
    "relink_wrong_encounter": "encounter_linkage",
    "delay_arrival": "timeliness",
    "unauthorized_disclosure": "unauthorized_disclosure",
    "consent_over_restriction": "consent_over_restriction",
    "correct_consent_exclusion": "none",
    "degrade_code_uncurated": "semantic_degraded",
}

# Genuine ICD-10-CM category-level ancestors that are deliberately ABSENT from
# config/code_equivalence.yaml. Used by the adversarial profile to measure what
# happens when the curated map does not cover a real degradation -- see
# config/injection_profile_blindspots.yaml.
UNCURATED_ANCESTORS = {
    "F32.1": "F32", "F33.1": "F33", "F41.1": "F41",
    "F43.10": "F43", "F10.20": "F10", "F11.20": "F11", "F31.32": "F31",
}


class _Ledger:
    """Accumulates the ground-truth record of every deliberate modification."""

    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        self.rows: list[dict[str, Any]] = []
        self.claimed: set[str] = set()

    def claim(self, element_uid: str) -> bool:
        """Reserve an element so no two injections target the same one.

        Overlapping injections would make the reference standard ambiguous:
        if an element is both value-corrupted and delayed, there is no single
        correct verdict to score the detector against.
        """
        if element_uid in self.claimed:
            return False
        self.claimed.add(element_uid)
        return True

    def record(self, failure_type: str, expected_detection: str,
               row: dict[str, Any], detail: str,
               original_value: Any = "", injected_value: Any = "") -> None:
        self.rows.append({
            "injection_id": f"{self.scenario_id}-INJ{len(self.rows) + 1:04d}",
            "scenario_id": self.scenario_id,
            "failure_type": failure_type,
            "expected_detection": expected_detection,
            "target_element_uid": row["exchange_element_id"],
            "target_patient_id": row["patient_id"],
            "target_encounter_id": row["encounter_id"],
            "element_name": row["element_name"],
            "element_group": row["element_group"],
            "original_value": str(original_value),
            "injected_value": str(injected_value),
            "detail": detail,
        })

    def frame(self) -> pd.DataFrame:
        columns = ["injection_id", "scenario_id", "failure_type",
                   "expected_detection", "target_element_uid",
                   "target_patient_id", "target_encounter_id", "element_name",
                   "element_group", "original_value", "injected_value", "detail"]
        if not self.rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(self.rows)[columns]


def _eligible(received: dict[str, dict[str, Any]], ledger: _Ledger,
              predicate) -> list[str]:
    return [
        uid for uid, row in received.items()
        if uid not in ledger.claimed and predicate(row)
    ]


def _band_crossing_score(current: int) -> int:
    """Shift a score across a severity band boundary.

    PHQ-9 bands are 5 points wide (0-4 minimal, 5-9 mild, 10-14 moderate,
    15-19 moderately severe, 20-27 severe); GAD-7 uses the same widths. Moving
    a score by 10 guarantees it lands at least two bands away, so the injected
    error is one that would change a clinical interpretation -- not a cosmetic
    perturbation the detector could plausibly be excused for missing.
    """
    return max(0, current - 10) if current >= 10 else current + 10


def inject_failures(clean: pd.DataFrame, expected: pd.DataFrame,
                    profile: dict[str, Any],
                    scenario_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the configured failures to a clean destination state.

    Parameters
    ----------
    clean : destination state under perfect exchange (from destination.clean_received)
    expected : EXPECTED_EXCHANGE, used to know each element's authorization
    profile : parsed config/injection_profile_*.yaml
    scenario_id : identifies this run's rows in the ledger

    Returns
    -------
    (received, injections) -- the corrupted destination state and the ledger.
    """
    contract = load_contract()
    equivalence = load_equivalence()
    rng = random.Random(int(profile["random_seed"]))
    ledger = _Ledger(scenario_id)

    received: dict[str, dict[str, Any]] = {
        row["exchange_element_id"]: dict(row) for row in clean.to_dict("records")
    }

    expected_by_uid = {row["element_uid"]: row for row in expected.to_dict("records")}
    all_patients = sorted({row["patient_id"] for row in received.values()})
    encounters_by_patient: dict[str, list[str]] = {}
    for row in received.values():
        encounters_by_patient.setdefault(row["patient_id"], [])
        if row["encounter_id"] not in encounters_by_patient[row["patient_id"]]:
            encounters_by_patient[row["patient_id"]].append(row["encounter_id"])

    mode = profile.get("mode", "fixed")
    if mode == "fixed":
        plan = [(entry["failure_type"], int(entry["count"]), entry)
                for entry in profile.get("fixed_counts", [])]
    else:
        rates = profile.get("probabilistic_rates", {})
        total_elements = len(received)
        plan = [
            (failure_type, max(0, int(round(rate * total_elements))), {})
            for failure_type, rate in rates.items()
        ]

    for failure_type, count, entry in plan:
        targets = entry.get("targets") or {}
        perturbation = entry.get("perturbation") or {}
        expected_detection = entry.get(
            "expected_detection",
            FAILURE_TYPE_TO_DETECTION.get(failure_type, failure_type),
        )

        # ------------------------------------------------------------------
        # Completeness: silent removal, no notice to the receiver
        # ------------------------------------------------------------------
        if failure_type == "drop_required_element":
            pool = _eligible(received, ledger, lambda r: (
                r["delivery_status"] == "delivered"
                and contract.element(r["element_name"]).required
            ))
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received.pop(uid)
                ledger.record(failure_type, expected_detection, row,
                              "Required element removed from destination with no "
                              "withholding notice (silent technical loss).",
                              original_value=row["element_value"])

        elif failure_type == "drop_subfield":
            allowed = set(targets.get("element_names") or [])
            pool = _eligible(received, ledger, lambda r: (
                r["delivery_status"] == "delivered"
                and not contract.element(r["element_name"]).required
                and (not allowed or r["element_name"] in allowed)
            ))
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received.pop(uid)
                ledger.record(failure_type, expected_detection, row,
                              "Non-required subfield dropped; parent clinical "
                              "group still delivered.",
                              original_value=row["element_value"])

        # ------------------------------------------------------------------
        # Fidelity: value corruption
        # ------------------------------------------------------------------
        elif failure_type == "alter_numeric_value":
            allowed = set(targets.get("element_names") or ["assessment_score"])
            pool = _eligible(received, ledger, lambda r: (
                r["delivery_status"] == "delivered" and r["element_name"] in allowed
            ))
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received[uid]
                original = row["element_value"]
                try:
                    current = int(float(original))
                except (TypeError, ValueError):
                    continue
                new_value = (_band_crossing_score(current)
                             if perturbation.get("mode") == "band_crossing"
                             else current + 7)
                row["element_value"] = str(new_value)
                ledger.record(failure_type, expected_detection, row,
                              "Numeric assessment score altered across a "
                              "severity band boundary.",
                              original_value=original, injected_value=new_value)

        # ------------------------------------------------------------------
        # Semantic: code degradation vs. outright wrong code
        # ------------------------------------------------------------------
        elif failure_type == "degrade_code":
            allowed = set(targets.get("element_names") or [])
            pool = _eligible(received, ledger, lambda r: (
                r["delivery_status"] == "delivered"
                and (not allowed or r["element_name"] in allowed)
                and bool(equivalence.broader_codes(r["code_system"],
                                                   r["element_value"]))
            ))
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received[uid]
                original = row["element_value"]
                broader = equivalence.broader_codes(row["code_system"], original)
                new_value = rng.choice(broader)
                row["element_value"] = new_value
                ledger.record(failure_type, expected_detection, row,
                              "Code replaced with a documented less-specific mapping; "
                              "structurally valid but less specific.",
                              original_value=original, injected_value=new_value)

        elif failure_type == "degrade_code_uncurated":
            # ADVERSARIAL: a real clinical degradation the curated equivalence
            # map does not know about. F32.1 -> F32 loses the episode/severity
            # specifier and is unambiguously a broadening, but because that
            # relationship is not in config/code_equivalence.yaml the engine
            # has no basis to call it degraded and will report value_mismatch.
            #
            # The framework still catches it -- detection sensitivity is
            # unaffected -- but it names it wrongly. That gap is a real
            # limitation of hand-curated terminology, and measuring it is more
            # useful than asserting in a README that curation "may be
            # incomplete."
            pool = _eligible(received, ledger, lambda r: (
                r["delivery_status"] == "delivered"
                and r["element_name"] == "diagnosis_code"
                and r["element_value"].upper() in UNCURATED_ANCESTORS
            ))
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received[uid]
                original = row["element_value"]
                new_value = UNCURATED_ANCESTORS[original.upper()]
                row["element_value"] = new_value
                ledger.record(failure_type, expected_detection, row,
                              "ADVERSARIAL: broader ancestor that is absent from "
                              "the curated equivalence map.",
                              original_value=original, injected_value=new_value)

        elif failure_type == "replace_code_incorrect":
            allowed = set(targets.get("element_names") or ["diagnosis_code"])
            pool = _eligible(received, ledger, lambda r: (
                r["delivery_status"] == "delivered" and r["element_name"] in allowed
            ))
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received[uid]
                original = row["element_value"]
                new_value = rng.choice(UNRELATED_ICD10)
                row["element_value"] = new_value
                ledger.record(failure_type, expected_detection, row,
                              "Code replaced with an unrelated concept from a "
                              "different ICD-10 chapter.",
                              original_value=original, injected_value=new_value)

        # ------------------------------------------------------------------
        # Linkage
        # ------------------------------------------------------------------
        elif failure_type == "relink_wrong_patient":
            pool = _eligible(received, ledger,
                             lambda r: r["delivery_status"] == "delivered")
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received[uid]
                others = [p for p in all_patients if p != row["patient_id"]]
                if not others:
                    continue
                original = row["patient_id"]
                row["patient_id"] = rng.choice(others)
                ledger.record(failure_type, expected_detection, row,
                              "Element delivered under a different patient's "
                              "identifier; value intact, person wrong.",
                              original_value=original,
                              injected_value=row["patient_id"])

        elif failure_type == "relink_wrong_encounter":
            pool = _eligible(received, ledger, lambda r: (
                r["delivery_status"] == "delivered"
                and len(encounters_by_patient.get(r["patient_id"], [])) > 1
            ))
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received[uid]
                others = [e for e in encounters_by_patient[row["patient_id"]]
                          if e != row["encounter_id"]]
                if not others:
                    continue
                original = row["encounter_id"]
                row["encounter_id"] = rng.choice(others)
                ledger.record(failure_type, expected_detection, row,
                              "Element attached to the wrong encounter for the "
                              "correct patient; contextually wrong.",
                              original_value=original,
                              injected_value=row["encounter_id"])

        # ------------------------------------------------------------------
        # Timeliness
        # ------------------------------------------------------------------
        elif failure_type == "delay_arrival":
            # -----------------------------------------------------------------
            # AN INJECTION IS ONLY A TRUE FAILURE IF IT ACTUALLY CREATES ONE.
            #
            # A fixed delay does not do that. The timeliness threshold depends
            # on encounter class: 60 minutes for EMER, 1440 for AMB. Adding a
            # flat 240 minutes breaches the crisis window comfortably and does
            # not come close to breaching the routine one -- so a flat delay
            # applied to an ambulatory encounter produces a ledger entry
            # claiming a timeliness failure where no failure exists.
            #
            # That is a defect in the reference standard, not the detector.
            # Measured on a 500-patient probabilistic run, it reported 114
            # false negatives and 32% timeliness sensitivity for a detector
            # that was behaving correctly on every single one of them.
            #
            # The fix is for the injector to check its own post-condition: take
            # whichever is larger, the configured delay or the delay actually
            # required to cross this element's threshold.
            #
            # This does mean the injector reads the same threshold table the
            # engine reads. That is shared experimental specification, not
            # circularity -- the threshold defines what "late" means for the
            # experiment, and both the thing being simulated and the thing
            # detecting it are entitled to know the definition. The engine
            # still derives its verdict independently from observed timestamps.
            # -----------------------------------------------------------------
            preferred = targets.get("prefer_encounter_class")
            extra = int(perturbation.get("extra_minutes", 240))

            def _delay_pool(require_preferred: bool) -> list[str]:
                return _eligible(received, ledger, lambda r: (
                    r["delivery_status"] == "delivered"
                    and (not require_preferred or r["encounter_class"] == preferred)
                ))

            pool = _delay_pool(bool(preferred))
            if len(pool) < count:
                # Fall back to any encounter class rather than silently
                # injecting fewer failures than configured. A quietly short
                # injection run would make the denominator of the evaluation
                # wrong without anything in the output saying so.
                pool = list(dict.fromkeys(pool + _delay_pool(False)))
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received[uid]
                original = row["received_timestamp"]

                threshold = contract.threshold_minutes(row.get("encounter_class"))
                sent = datetime.fromisoformat(str(row["sent_timestamp"]))
                current_latency = (
                    datetime.fromisoformat(original) - sent
                ).total_seconds() / 60.0
                # +1 minute so the result is strictly past the threshold rather
                # than exactly on it, where a >= vs > choice would decide the
                # verdict.
                required = threshold - current_latency + 1
                applied = int(max(extra, required))

                delayed = datetime.fromisoformat(original) + timedelta(minutes=applied)
                row["received_timestamp"] = delayed.isoformat()
                ledger.record(
                    failure_type, expected_detection, row,
                    f"Arrival delayed by {applied} additional minutes "
                    f"(threshold for {row.get('encounter_class')} encounters is "
                    f"{threshold} min); content fully intact.",
                    original_value=original, injected_value=delayed.isoformat(),
                )

        # ------------------------------------------------------------------
        # Consent
        # ------------------------------------------------------------------
        elif failure_type == "unauthorized_disclosure":
            # Targets elements that are NOT in the expected set. A validator
            # that iterates only the expected set cannot see these at all.
            pool = _eligible(received, ledger,
                             lambda r: r["delivery_status"] == "withheld_notice")
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received[uid]
                source_row = expected_by_uid.get(uid)
                if source_row is None:
                    continue
                row["delivery_status"] = "delivered"
                row["element_value"] = str(source_row["element_value"])
                ledger.record(failure_type, expected_detection, row,
                              "Restricted element disclosed to the destination "
                              "despite consent requiring it be withheld.",
                              original_value="(withheld)",
                              injected_value=row["element_value"])

        elif failure_type == "consent_over_restriction":
            pool = _eligible(received, ledger,
                             lambda r: r["delivery_status"] == "delivered")
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                row = received[uid]
                original = row["element_value"]
                row["delivery_status"] = "withheld_notice"
                row["element_value"] = ""
                ledger.record(failure_type, expected_detection, row,
                              "Authorized element withheld by a faulty "
                              "restriction rule; receiver notified of a "
                              "withholding that should not have occurred.",
                              original_value=original)

        # ------------------------------------------------------------------
        # Negative controls -- correct behavior that must NOT be flagged
        # ------------------------------------------------------------------
        elif failure_type == "correct_consent_exclusion":
            pool = _eligible(received, ledger,
                             lambda r: r["delivery_status"] == "withheld_notice")
            for uid in rng.sample(pool, min(count, len(pool))):
                if not ledger.claim(uid):
                    continue
                ledger.record(failure_type, "none", received[uid],
                              "NEGATIVE CONTROL: restricted element correctly "
                              "withheld. Any finding on this element is a false "
                              "positive.")

        else:
            raise ValueError(
                f"Injection profile requests unknown failure_type "
                f"'{failure_type}'. Add an implementation or remove it from "
                "the profile -- silently skipping it would overstate the "
                "detector's measured sensitivity."
            )

    received_frame = pd.DataFrame(list(received.values()))
    return received_frame.reset_index(drop=True), ledger.frame()
