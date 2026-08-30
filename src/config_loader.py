"""Load and validate the YAML configuration that defines the Validation Contract.

The contract is data, not code. This module is the single place it enters the
program, and it fails loudly on anything malformed rather than letting a typo
in a YAML key silently disable a validation rule -- a disabled rule produces a
clean-looking run with a false negative in it, which is the worst possible
failure mode for a tool whose entire purpose is detecting silent failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

import paths


# ---------------------------------------------------------------------------
# Raw YAML access
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required config file is missing: {path}")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file did not parse to a mapping: {path}")
    return loaded


# ---------------------------------------------------------------------------
# Element definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ElementDef:
    """One validatable element, exactly as declared in config/v1_elements.yaml."""

    element_name: str
    element_group: str
    datatype: str
    code_system: str | None
    fhir_path: str
    normalization: str
    comparison: str
    required: bool
    tolerance: Any = None
    notes: str = ""


@dataclass(frozen=True)
class Contract:
    """The full parsed Validation Contract."""

    contract_version: str
    fhir_version: str
    elements: dict[str, ElementDef]
    element_order: list[str]
    groups: dict[str, list[str]]
    timeliness_default_minutes: int
    timeliness_by_class: dict[str, int]
    failure_classes: dict[str, dict[str, str]]
    pass_classes: dict[str, dict[str, str]]

    def element(self, name: str) -> ElementDef:
        try:
            return self.elements[name]
        except KeyError as exc:
            raise KeyError(
                f"Element '{name}' is not declared in the Validation Contract. "
                "Every element the engine touches must be declared in "
                "config/v1_elements.yaml -- undeclared elements are refused "
                "rather than validated with default rules."
            ) from exc

    def threshold_minutes(self, encounter_class: str | None) -> int:
        if encounter_class and encounter_class in self.timeliness_by_class:
            return self.timeliness_by_class[encounter_class]
        return self.timeliness_default_minutes


@lru_cache(maxsize=1)
def load_contract() -> Contract:
    raw = _load_yaml(paths.CONFIG / "v1_elements.yaml")

    elements: dict[str, ElementDef] = {}
    order: list[str] = []
    groups: dict[str, list[str]] = {}

    for entry in raw.get("elements", []):
        element = ElementDef(
            element_name=entry["element_name"],
            element_group=entry["element_group"],
            datatype=entry["datatype"],
            code_system=entry.get("code_system"),
            fhir_path=entry["fhir_path"],
            normalization=entry["normalization"],
            comparison=entry["comparison"],
            required=bool(entry["required"]),
            tolerance=entry.get("tolerance"),
            notes=(entry.get("notes") or "").strip(),
        )
        if element.element_name in elements:
            raise ValueError(
                f"Duplicate element declaration: {element.element_name}"
            )
        elements[element.element_name] = element
        order.append(element.element_name)
        groups.setdefault(element.element_group, []).append(element.element_name)

    if not elements:
        raise ValueError("Validation Contract declares zero elements.")

    timeliness = raw.get("timeliness", {})

    return Contract(
        contract_version=str(raw["contract_version"]),
        fhir_version=str(raw["fhir_version"]),
        elements=elements,
        element_order=order,
        groups=groups,
        timeliness_default_minutes=int(timeliness.get("default_threshold_minutes", 1440)),
        timeliness_by_class={
            str(k): int(v) for k, v in (timeliness.get("by_encounter_class") or {}).items()
        },
        failure_classes=raw.get("failure_classes", {}),
        pass_classes=raw.get("pass_classes", {}),
    )


# ---------------------------------------------------------------------------
# Consent rules
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConsentRules:
    states: dict[str, list[str]]
    sud_diagnosis_prefixes: tuple[str, ...]
    sud_medication_codes: frozenset[str]
    encounter_group_always_routine: bool

    def authorizes(self, consent_state: str, sensitivity_class: str) -> bool:
        """Is this sensitivity class authorized to move under this consent state?

        This single predicate is what separates an authorized exclusion (PASS)
        from missing data (FAIL). Getting it wrong in either direction produces
        a wrong answer of a different kind: too permissive and the framework
        under-reports data loss; too strict and it reports lawful privacy
        behavior as a defect.
        """
        if consent_state not in self.states:
            raise KeyError(
                f"Unknown consent state '{consent_state}'. Declared states: "
                f"{sorted(self.states)}"
            )
        return sensitivity_class in self.states[consent_state]

    def classify_diagnosis(self, code: str) -> str:
        normalized = (code or "").upper().replace(".", "")
        for prefix in self.sud_diagnosis_prefixes:
            if normalized.startswith(prefix.upper().replace(".", "")):
                return "sud_part2"
        return "routine"

    def classify_medication(self, rxnorm_code: str) -> str:
        if str(rxnorm_code) in self.sud_medication_codes:
            return "sud_part2"
        return "routine"


@lru_cache(maxsize=1)
def load_consent_rules() -> ConsentRules:
    raw = _load_yaml(paths.CONFIG / "consent_rules.yaml")

    states = {
        name: list(body.get("authorizes_sensitivity_classes") or [])
        for name, body in (raw.get("consent_states") or {}).items()
    }
    assignment = raw.get("sensitivity_assignment") or {}
    dx = (assignment.get("diagnosis_code_prefixes") or {}).get("sud_part2") or []
    meds = (assignment.get("medication_rxnorm_codes") or {}).get("sud_part2") or []
    propagation = raw.get("propagation") or {}

    return ConsentRules(
        states=states,
        sud_diagnosis_prefixes=tuple(str(p) for p in dx),
        sud_medication_codes=frozenset(str(m) for m in meds),
        encounter_group_always_routine=bool(
            propagation.get("encounter_group_always_routine", True)
        ),
    )


# ---------------------------------------------------------------------------
# Code equivalence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EquivalenceMap:
    systems: dict[str, dict[str, dict[str, Any]]]
    unit_to_mg: dict[str, float]
    frequency_synonyms: dict[str, str] = field(default_factory=dict)

    def relationship(self, system: str | None, expected: str, received: str) -> str:
        """Classify the relationship between an expected and a received code.

        Returns one of: 'exact', 'equivalent', 'degraded', 'unrelated'.
        """
        exp = (expected or "").strip().upper()
        rec = (received or "").strip().upper()
        if exp == rec:
            return "exact"

        entries = self.systems.get(system or "", {})
        # Case-insensitive lookup of the expected code's entry.
        entry = None
        for code, body in entries.items():
            if str(code).strip().upper() == exp:
                entry = body
                break
        if entry is None:
            return "unrelated"

        equivalent = {str(c).strip().upper() for c in (entry.get("equivalent") or [])}
        broader = {str(c).strip().upper() for c in (entry.get("broader") or [])}

        if rec in equivalent:
            return "equivalent"
        if rec in broader:
            return "degraded"
        return "unrelated"

    def broader_codes(self, system: str | None, expected: str) -> list[str]:
        """Documented less-specific mappings used by the failure injector."""
        exp = (expected or "").strip().upper()
        for code, body in self.systems.get(system or "", {}).items():
            if str(code).strip().upper() == exp:
                return [str(c) for c in (body.get("broader") or [])]
        return []

    def to_mg(self, value: float, unit: str) -> float | None:
        factor = self.unit_to_mg.get((unit or "").strip().lower())
        if factor is None:
            return None
        return value * factor

    def canonical_frequency(self, text: str) -> str | None:
        return self.frequency_synonyms.get((text or "").strip().lower())


@lru_cache(maxsize=1)
def load_equivalence() -> EquivalenceMap:
    raw = _load_yaml(paths.CONFIG / "code_equivalence.yaml")

    synonyms: dict[str, str] = {}
    for canonical, variants in (raw.get("frequency_synonyms") or {}).items():
        # The canonical form maps to itself so already-canonical input passes
        # through unchanged -- Scenario B emits GTS abbreviations directly.
        synonyms[str(canonical).strip().lower()] = str(canonical)
        for variant in variants or []:
            synonyms[str(variant).strip().lower()] = str(canonical)

    return EquivalenceMap(
        systems=raw.get("systems") or {},
        unit_to_mg={
            str(k).lower(): float(v)
            for k, v in (raw.get("unit_conversion_to_mg") or {}).items()
        },
        frequency_synonyms=synonyms,
    )


# ---------------------------------------------------------------------------
# Scenarios and injection profiles
# ---------------------------------------------------------------------------

def load_scenario(scenario_id: str) -> dict[str, Any]:
    return _load_yaml(paths.CONFIG / f"scenario_{scenario_id}.yaml")


def load_injection_profile(profile: str = "v1") -> dict[str, Any]:
    return _load_yaml(paths.CONFIG / f"injection_profile_{profile}.yaml")
