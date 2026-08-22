"""The validation engine: expected vs. received, element by element.

This module implements Blueprint Section 7.1's V1 validation logic:

    * every element marked expected must either be received or have a
      documented, valid exclusion reason
    * when an expected element is received, its normalized value must match the
      reference value according to the element-specific comparison rule
    * the validator must distinguish missing, altered, intentionally excluded,
      and not-applicable states
    * every failure must preserve traceability to patient, encounter, element,
      expected value, received value, and test run

VERDICT PRECEDENCE
------------------
An element can fail in more than one way at once -- delivered to the wrong
encounter AND late, for instance. The results table carries one primary verdict
per element so it can be counted without double-counting, plus a
`secondary_findings` column so nothing is thrown away.

Precedence runs from "the receiver has the wrong thing" down to "the receiver
has the right thing, inconveniently":

    consent  >  completeness  >  linkage  >  value/semantic  >  timeliness

The ordering is a judgment, and it is stated here rather than left implicit in
the order of a chain of if-statements, because it changes what the headline
numbers mean. A reader who disagrees with it can re-derive every count from
`secondary_findings` without rerunning anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from config_loader import load_contract
from validate import rules
from validate.normalize import normalize

# Highest severity first.
VERDICT_PRECEDENCE = [
    "unauthorized_disclosure",
    "consent_over_restriction",
    "missing_element",
    "subfield_dropped",
    "patient_linkage",
    "encounter_linkage",
    "value_mismatch",
    "semantic_degraded",
    "timeliness",
]

_PRECEDENCE_RANK = {verdict: rank for rank, verdict in enumerate(VERDICT_PRECEDENCE)}


def _latency_minutes(sent: Any, received: Any) -> float | None:
    try:
        delta = datetime.fromisoformat(str(received)) - datetime.fromisoformat(str(sent))
    except (TypeError, ValueError):
        return None
    return delta.total_seconds() / 60.0


def validate(expected: pd.DataFrame, received: pd.DataFrame,
             run_id: str) -> pd.DataFrame:
    """Produce element-level VALIDATION_RESULTS.

    One row per element in EXPECTED_EXCHANGE -- including consent-excluded
    elements, which must be checked for absence rather than skipped.
    """
    contract = load_contract()
    received_by_uid = {
        row["exchange_element_id"]: row for row in received.to_dict("records")
    }

    results: list[dict[str, Any]] = []
    matched_uids: set[str] = set()

    for source in expected.to_dict("records"):
        uid = source["element_uid"]
        element = contract.element(source["element_name"])
        destination = received_by_uid.get(uid)
        if destination is not None:
            matched_uids.add(uid)

        delivery_status = destination["delivery_status"] if destination else "absent"
        received_value = destination["element_value"] if destination else ""
        received_patient = destination["patient_id"] if destination else ""
        received_encounter = destination["encounter_id"] if destination else ""

        findings: list[tuple[str, str, str]] = []   # (verdict, dimension, detail)
        latency = None
        threshold = contract.threshold_minutes(source.get("encounter_class"))

        # ------------------------------------------------------------------
        # Branch 1: consent did NOT authorize this element to move.
        # Absence is the correct outcome; presence is a disclosure failure.
        # ------------------------------------------------------------------
        if source["exchange_expectation"] == "excluded_by_consent":
            if delivery_status == "delivered" and str(received_value) != "":
                findings.append((
                    "unauthorized_disclosure", "consent",
                    f"Element carries sensitivity class "
                    f"'{source['sensitivity_class']}', which consent state "
                    f"'{source['consent_state']}' does not authorize, but it was "
                    "present at the destination."
                ))
            # Otherwise: correctly withheld. Recorded as a PASS below, and
            # deliberately NOT counted in the completeness denominator.

        # ------------------------------------------------------------------
        # Branch 2: consent authorized it. Now check it actually arrived intact.
        # ------------------------------------------------------------------
        else:
            if destination is None:
                findings.append((
                    "missing_element" if element.required else "subfield_dropped",
                    "completeness" if element.required else "fidelity",
                    "Expected element has no corresponding record at the "
                    "destination and no withholding notice was issued."
                ))
            elif delivery_status == "withheld_notice":
                findings.append((
                    "consent_over_restriction", "consent",
                    f"Element was withheld, but consent state "
                    f"'{source['consent_state']}' authorizes sensitivity class "
                    f"'{source['sensitivity_class']}'. The restriction rule "
                    "over-applied."
                ))
            else:
                # --- Linkage ------------------------------------------------
                if received_patient != source["patient_id"]:
                    findings.append((
                        "patient_linkage", "linkage",
                        f"Delivered under patient {received_patient}, expected "
                        f"{source['patient_id']}."
                    ))
                elif received_encounter != source["encounter_id"]:
                    findings.append((
                        "encounter_linkage", "linkage",
                        f"Delivered under encounter {received_encounter}, "
                        f"expected {source['encounter_id']}."
                    ))

                # --- Value ---------------------------------------------------
                if str(received_value).strip() == "":
                    findings.append((
                        "missing_element" if element.required else "subfield_dropped",
                        "completeness" if element.required else "fidelity",
                        "Element record present at the destination but carries "
                        "no value."
                    ))
                else:
                    expected_norm = normalize(element.normalization,
                                              source["element_value"])
                    received_norm = normalize(element.normalization, received_value)
                    comparison = rules.compare(element, expected_norm, received_norm)
                    if comparison.outcome == rules.DEGRADED:
                        findings.append(("semantic_degraded", "semantic",
                                         comparison.detail))
                    elif comparison.outcome == rules.MISMATCH:
                        findings.append(("value_mismatch", "fidelity",
                                         comparison.detail))

                # --- Timeliness ----------------------------------------------
                latency = _latency_minutes(destination.get("sent_timestamp"),
                                           destination.get("received_timestamp"))
                if latency is not None and latency > threshold:
                    findings.append((
                        "timeliness", "timeliness",
                        f"Arrived {latency:.0f} minutes after transmission; "
                        f"threshold for {source.get('encounter_class')} "
                        f"encounters is {threshold} minutes."
                    ))

        # ------------------------------------------------------------------
        # Reduce findings to one primary verdict plus the rest
        # ------------------------------------------------------------------
        if findings:
            findings.sort(key=lambda f: _PRECEDENCE_RANK[f[0]])
            primary_verdict, dimension, detail = findings[0]
            status = "FAIL"
            secondary = "; ".join(verdict for verdict, _, _ in findings[1:])
        else:
            status = "PASS"
            if source["exchange_expectation"] == "excluded_by_consent":
                primary_verdict, dimension = "authorized_exclusion", "consent"
                detail = ("Correctly withheld: consent does not authorize "
                          "sensitivity class "
                          f"'{source['sensitivity_class']}'. Excluded from the "
                          "completeness denominator.")
            else:
                primary_verdict, dimension = "exact_match", "none"
                detail = ""
            secondary = ""

        results.append({
            "run_id": run_id,
            "scenario_id": source["scenario_id"],
            "element_uid": uid,
            "patient_id": source["patient_id"],
            "encounter_id": source["encounter_id"],
            "encounter_class": source.get("encounter_class", ""),
            "element_group": source["element_group"],
            "element_name": source["element_name"],
            "group_id": source["group_id"],
            "sensitivity_class": source["sensitivity_class"],
            "consent_state": source["consent_state"],
            "exchange_expectation": source["exchange_expectation"],
            "required": bool(element.required),
            "expected_value": source["element_value"],
            "received_value": received_value,
            "received_patient_id": received_patient,
            "received_encounter_id": received_encounter,
            "delivery_status": delivery_status,
            "status": status,
            "verdict": primary_verdict,
            "dimension": dimension,
            "secondary_findings": secondary,
            "detail": detail,
            "latency_minutes": round(latency, 2) if latency is not None else None,
            "threshold_minutes": threshold,
        })

    # ----------------------------------------------------------------------
    # Orphan check
    # ----------------------------------------------------------------------
    # Destination records with no counterpart in the expected set. In this
    # simulation they should never occur, since every wire record derives from
    # a source element. Checking anyway is cheap, and an assumption that is
    # verified in code is worth more than one asserted in a comment.
    orphans = set(received_by_uid) - matched_uids
    if orphans:
        raise ValueError(
            f"{len(orphans)} destination records have no expected counterpart, "
            f"e.g. {sorted(orphans)[:3]}. This indicates a pipeline defect, not "
            "a data-quality finding."
        )

    return pd.DataFrame(results)


def summarize(results: pd.DataFrame) -> dict[str, Any]:
    """Run-level completeness and fidelity, per Blueprint Section 12.1.

    Definitions are spelled out because a data-quality percentage without its
    denominator stated is not a reproducible measurement:

    completeness = expected elements received / total expected elements
        "received" means a delivered destination record carrying a non-empty
        value. A withholding notice does not count as received.
        Consent-excluded elements are NOT in either term.

    fidelity = received comparable elements matching / received comparable
        "comparable" means received with a value, so the comparison could
        actually be performed. An element that never arrived cannot be
        unfaithful -- it is incomplete, and counting it as a fidelity failure
        too would double-penalize the same defect.
        Semantically degraded values count as NOT matching, and are also
        reported separately under the semantic dimension.
    """
    expected_only = results[results["exchange_expectation"] == "expected"]
    total_expected = len(expected_only)

    received_mask = (
        (expected_only["delivery_status"] == "delivered")
        & (expected_only["received_value"].astype(str).str.strip() != "")
    )
    received_count = int(received_mask.sum())

    comparable = expected_only[received_mask]
    fidelity_failures = comparable["verdict"].isin(["value_mismatch", "semantic_degraded"])
    matched = int(len(comparable) - fidelity_failures.sum())

    excluded = results[results["exchange_expectation"] == "excluded_by_consent"]

    return {
        "run_id": results["run_id"].iloc[0] if len(results) else "",
        "scenario_id": results["scenario_id"].iloc[0] if len(results) else "",
        "total_source_elements": len(results),
        "total_expected_elements": total_expected,
        "expected_elements_received": received_count,
        # A zero denominator means every patient in the run was fully
        # restricted. Reporting 0% there would be wrong; None is honest.
        "completeness_pct": round(100.0 * received_count / total_expected, 2)
                            if total_expected else None,
        "comparable_elements": int(len(comparable)),
        "comparable_elements_matched": matched,
        "fidelity_pct": round(100.0 * matched / len(comparable), 2)
                        if len(comparable) else None,
        "elements_excluded_by_consent": int(len(excluded)),
        "correct_authorized_exclusions": int((excluded["verdict"] == "authorized_exclusion").sum()),
        "unauthorized_disclosures": int((results["verdict"] == "unauthorized_disclosure").sum()),
        "total_failures": int((results["status"] == "FAIL").sum()),
    }
