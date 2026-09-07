# V1 Validation Contract and Data Dictionary

**Contract version:** 1.0.0
**FHIR version:** R4 (4.0.1)
**Status:** V1 frozen for the micro-prototype and scaled benchmark

This is the human-readable half of the Validation Contract. The machine-readable
half is [`config/v1_elements.yaml`](../../config/v1_elements.yaml), and the two
must agree — `tests/test_contract_sync.py` fails the build if an element is
declared in one and not the other.

The contract exists because of a specific hazard. A data-quality percentage is
only meaningful if its denominator and its comparison rules are stated in
advance. Decide them after seeing the results and you can produce almost any
number you like, honestly and without noticing. Writing them down first — before
a line of validation code was written, per Blueprint Next Action #3 — is what
makes the eventual numbers a measurement rather than an opinion.

---

## 1. The three-dataset comparison

The framework never compares source directly to destination. It compares across
three datasets, and the middle one is what makes the result correct:

```
SOURCE_TRUTH  ──►  EXPECTED_EXCHANGE  ──►  RECEIVED_DATA  ──►  VALIDATION_RESULTS
what the           what consent           what the             what survived,
sender has         authorized to move     receiver has         and what didn't
```

**Why the middle step is not optional.** In behavioral health, lawfully withheld
information and lost information look identical at the destination — both are
simply absent. A framework that compares source to destination directly reports
every correctly withheld 42 CFR Part 2 element as missing data. The consequence
is not a small accuracy penalty: the more carefully an organization honors SUD
restrictions, the worse its measured data quality appears. The tool would
actively punish compliance.

---

## 2. Element registry

Eleven elements across four clinical groups. Every one has a declared datatype,
normalization rule, comparison rule, and tolerance. Nothing in the engine is
allowed to hard-code any of these.

### 2.1 Encounter

| Element | Type | Code system | FHIR path | Required | Normalization | Comparison | Tolerance |
|---|---|---|---|---|---|---|---|
| `encounter_class` | code | v3-ActCode | `Encounter.class.code` | Yes | `upper_trim` | `exact` | — |
| `encounter_datetime` | datetime | — | `Encounter.period.start` | Yes | `iso_datetime` | `exact_datetime` | 0 sec |

`encounter_class` (AMB vs EMER) selects the timeliness threshold, so a corrupted
value has consequences beyond itself.

### 2.2 Diagnosis

| Element | Type | Code system | FHIR path | Required | Normalization | Comparison | Tolerance |
|---|---|---|---|---|---|---|---|
| `diagnosis_code` | code | ICD-10-CM | `Condition.code.coding.code` | Yes | `upper_trim` | `code_equivalence` | — |
| `diagnosis_display` | text | — | `Condition.code.coding.display` | No | `text_normalized` | `text_equivalence` | case/punct/ws |
| `diagnosis_onset` | date | — | `Condition.onsetDateTime` | No | `iso_date` | `exact_date` | 0 days |

`diagnosis_display` is deliberately **not required**. Display text is advisory;
the code carries the meaning. Marking it required would fill the completeness
failure count with findings no clinician would act on.

### 2.3 Assessment

| Element | Type | Code system | FHIR path | Required | Normalization | Comparison | Tolerance |
|---|---|---|---|---|---|---|---|
| `assessment_code` | code | LOINC | `Observation.code.coding.code` | Yes | `upper_trim` | `exact` | — |
| `assessment_score` | numeric | — | `Observation.valueQuantity.value` | Yes | `numeric` | `numeric_exact` | **0** |
| `assessment_datetime` | datetime | — | `Observation.effectiveDateTime` | No | `iso_datetime` | `exact_datetime` | 0 sec |

LOINC 44249-1 = PHQ-9 total score; 70274-6 = GAD-7 total score.

**Why `assessment_score` tolerance is exactly zero.** PHQ-9 severity bands are
five points wide (0–4 minimal, 5–9 mild, 10–14 moderate, 15–19 moderately
severe, 20–27 severe). Any nonzero tolerance admits the possibility of a value
crossing a band boundary and changing a treatment decision while the framework
reports a match. Zero requires no clinical defense; any other number does.

### 2.4 Medication

| Element | Type | Code system | FHIR path | Required | Normalization | Comparison | Tolerance |
|---|---|---|---|---|---|---|---|
| `medication_code` | code | RxNorm | `MedicationRequest.medicationCodeableConcept.coding.code` | Yes | `upper_trim` | `code_equivalence` | — |
| `medication_dose` | quantity | UCUM | `MedicationRequest.dosageInstruction.doseAndRate.doseQuantity` | No | `dose_quantity` | `quantity_equivalence` | unit-normalized exact |
| `medication_frequency` | code | v3-GTSAbbreviation | `MedicationRequest.dosageInstruction.timing.code.coding.code` | No | `frequency_code` | `exact` | — |

---

## 3. Normalization rules

Normalization strips representation so comparison can see content. The rule
followed throughout: **normalize only differences documented in `config/` as
representational, and flag anything unparseable rather than guessing.**

| Rule | Strips | Keeps | Unparseable input |
|---|---|---|---|
| `upper_trim` | case, surrounding whitespace | everything else | passes through |
| `text_normalized` | case, punctuation, whitespace runs | word content and order | passes through |
| `iso_datetime` / `iso_date` | format variation | the instant | flagged `ok=False` |
| `numeric` | string formatting (`18` vs `18.0`) | magnitude | flagged `ok=False` |
| `dose_quantity` | unit rendering (`0.05 g` → `50 mg`) | magnitude in mg | flagged `ok=False` |
| `frequency_code` | surface form (`daily`, `QD`, `q.d.` → `QD`) | dosing schedule | flagged `ok=False`, value preserved verbatim |

Two failure modes are being balanced. Under-normalizing produces false positives
on every heterogeneous sender. Over-normalizing produces false negatives, which
are far worse in a tool built to find what other tools miss — so an
unnormalizable value is always flagged, never coerced to a default.

`text_normalized` deliberately does **not** resolve synonyms. Deciding that
"MDD" means "Major depressive disorder" is a terminology judgment, and
terminology judgments belong in the reviewable equivalence map, not hidden
inside a string function.

---

## 4. Comparison outcomes

Every comparator returns one of **three** values, not two:

| Outcome | Meaning | Verdict |
|---|---|---|
| `match` | received value carries the expected content | PASS |
| `degraded` | received value is a documented broader concept — meaning partially survived | `semantic_degraded` |
| `mismatch` | received value does not carry the expected content | `value_mismatch` |

The three-way outcome is the reason the semantic dimension exists. To a binary
comparator, `F32.1 → F32.9` (severity specifier lost) and `F32.1 → I10`
(hypertension) are both "mismatch". They are not the same finding, and a
receiving organization would respond to them very differently.

Equivalence relationships are curated in
[`config/code_equivalence.yaml`](../../config/code_equivalence.yaml). See §8 for
the measured cost of that curation being incomplete.

---

## 5. Consent model and the denominator

| Consent state | Authorizes | Meaning |
|---|---|---|
| `authorized_all` | `routine`, `sud_part2` | full disclosure authorized |
| `part2_restricted` | `routine` | SUD records withheld |
| `fully_restricted` | *(none)* | nothing authorized to move |

Sensitivity attaches to a **clinical group**, not a field. If a diagnosis is
Part 2, its code, display, and onset all are — withholding the code while
exchanging the display "Alcohol dependence, uncomplicated" would disclose
exactly what the restriction protects. The encounter group is always routine:
*that* a visit occurred is exchanged, *what happened in it* may be restricted.

**Denominator rules:**

- Completeness denominator = elements with `exchange_expectation = 'expected'`. Consent-excluded elements are never in it.
- A correctly withheld element is a **PASS** (`authorized_exclusion`), not a gap.
- A `fully_restricted` patient has a denominator of **zero**, and completeness for that patient is reported as **undefined (n/a)** — never 0%. Reporting 0% would score an organization as having lost everything when it correctly disclosed nothing.

---

## 6. Destination delivery states

The destination distinguishes three conditions, which is what makes the consent
dimension measurable:

| `delivery_status` | Receiver's situation |
|---|---|
| `delivered` | element arrived, with a value |
| `withheld_notice` | element did not arrive; receiver was told something was withheld |
| *(no row)* | element did not arrive; receiver has no idea anything is missing |

This models Data Segmentation for Privacy (DS4P) practice. Combined with the
patient's consent state it separates three situations that are otherwise
identical from the destination's point of view:

| Consent authorized it? | Destination state | Verdict |
|---|---|---|
| No | `withheld_notice` | **PASS** — `authorized_exclusion` |
| Yes | `withheld_notice` | FAIL — `consent_over_restriction` (faulty rule) |
| Yes | no row | FAIL — `missing_element` (silent technical loss) |

The last two matter operationally: one is a consent-configuration problem, the
other is an IT problem.

*Simplification:* real DS4P notices are usually document- or section-level, not
element-level. Without any such signal, the second and third rows would be
genuinely indistinguishable and both would have to be reported as
`missing_element`.

---

## 7. Verdict vocabulary and precedence

| Verdict | Dimension | Trigger |
|---|---|---|
| `unauthorized_disclosure` | consent | restricted element present at destination |
| `consent_over_restriction` | consent | authorized element withheld |
| `missing_element` | completeness | required expected element absent or valueless |
| `subfield_dropped` | fidelity | non-required element absent; parent group present |
| `patient_linkage` | linkage | delivered under the wrong patient |
| `encounter_linkage` | linkage | delivered under the wrong encounter |
| `value_mismatch` | fidelity | value differs, no documented relationship |
| `semantic_degraded` | semantic | value is a documented broader concept |
| `timeliness` | timeliness | latency exceeds the encounter-class threshold |
| `authorized_exclusion` | consent | **PASS** — correctly withheld |
| `exact_match` | — | **PASS** — arrived and matched |

An element can fail more than one way. The results table carries one **primary
verdict** so counts do not double, plus a `secondary_findings` column so nothing
is discarded. Precedence, highest first:

```
consent  >  completeness  >  linkage  >  value/semantic  >  timeliness
```

This ordering is a judgment. It is stated explicitly because it changes what the
headline numbers mean, and a reader who disagrees can re-derive every count from
`secondary_findings` without rerunning anything.

**Timeliness thresholds:** EMER 60 minutes, AMB 1440 minutes (24h). These are
illustrative experimental parameters, **not** published clinical standards.

---

## 8. Known limitation: curated terminology

`code_equivalence` depends on a hand-curated map. When a real degradation falls
outside that curation, the framework still detects it but names it wrongly.

This was measured rather than assumed. `config/injection_profile_blindspots.yaml`
injects five degradations covered by the map and five that are not (ICD-10-CM
category-level ancestors like `F32.1 → F32`, which are genuine broadenings):

| | Detection sensitivity | Classification sensitivity |
|---|---|---|
| Curated degradations | 100% | 100% |
| Uncurated degradations | 100% | **0%** — reported as `value_mismatch` |
| Combined run | 100% | **50%** |

The honest characterization of a curated-terminology approach: **it does not
miss things, it mislabels the things outside its curation.** A production or
dissertation-scale version would derive equivalence from the ICD-10-CM hierarchy
and the RxNorm relationship graph (UMLS, RxNav) rather than a YAML file. That
conclusion follows from a measurement, not from an opinion.

---

## 9. Dataset schemas

### SOURCE_TRUTH — `data/source/scenario_*/source_truth.csv`
One row per clinical element instance (long form).

| Column | Meaning |
|---|---|
| `element_uid` | `scenario:patient:encounter:group:element` — human-readable primary key |
| `patient_id`, `encounter_id`, `group_id` | traceability keys |
| `element_group`, `element_name` | what kind of element this is |
| `element_value` | canonical source value |
| `code_system` | terminology URI, blank for uncoded values |
| `sensitivity_class` | `routine` or `sud_part2` |
| `encounter_class`, `encounter_datetime` | clinical context |
| `source_system` | simulated origin |

### EXPECTED_EXCHANGE — `data/expected/scenario_*/expected_exchange.csv`
SOURCE_TRUTH plus `consent_state`, `authorized`, `exchange_expectation`.

### RECEIVED_DATA — `data/received/scenario_*/received_data.csv`
Adds `exchange_element_id`, `delivery_status`, `sent_timestamp`,
`received_timestamp`, `destination_system`.

### FAILURE_INJECTIONS — `data/received/scenario_*/failure_injections.csv`
The reference standard: `injection_id`, `failure_type`, `expected_detection`,
`target_element_uid`, `original_value`, `injected_value`, `detail`.

### VALIDATION_RESULTS — `data/processed/scenario_*/validation_results.csv`
One row per expected-exchange element, with `status`, `verdict`, `dimension`,
`secondary_findings`, `detail`, `latency_minutes`, `threshold_minutes`, and full
expected/received traceability.

---

## 10. Correlation-identifier assumption

Received rows carry `exchange_element_id`, and the validator matches expected to
received on it. This models FHIR's persistent `Resource.id` / `Identifier`,
which does survive exchange in practice.

It remains a **load-bearing assumption**. An exchange path that does not
preserve stable identifiers would require probabilistic record matching, and
matching error would then confound every metric downstream. Stated here because
a reviewer will ask.

---

## 11. Metric definitions

```
completeness = expected elements received / total expected elements × 100
```
"Received" = a `delivered` record carrying a non-empty value. A withholding
notice is not receipt. Consent-excluded elements are in neither term.

```
fidelity = comparable elements matching / comparable elements × 100
```
"Comparable" = received with a value, so a comparison could actually be
performed. An element that never arrived cannot be unfaithful — it is
incomplete, and counting it twice would make the two dimensions
non-independent. `semantic_degraded` counts as not matching, and is also
reported separately under the semantic dimension.

---

## 12. V1 scope exclusions

Free-text clinical notes; document attachments; production vendor connectors;
real PHI; automated remediation; any claim about real-world prevalence.

---

## Change log

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-08-16 | Initial contract. 11 elements, 4 groups, 7 validation dimensions, 3 consent states, 10 primary failure types plus 1 negative control. |
