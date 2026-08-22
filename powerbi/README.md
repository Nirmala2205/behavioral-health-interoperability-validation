# Power BI Build Specification

Power BI is the **presentation layer, not the validation engine.** It consumes
tables produced by Python and SQL and displays them. It does not recompute
completeness, fidelity, or any verdict.

This matters enough to state as a rule: reimplementing a rule in DAX creates a
second definition of the same fact, and the two diverge silently the first time
the Python side changes. Blueprint Section 19 makes "Power BI accurately
reflects the validation outputs rather than recreating hidden logic in DAX" a
condition of project success.

The `.pbix` is built by hand in Power BI Desktop; this file specifies exactly
what to build so the result is reproducible rather than improvised.

---

## 1. Data sources

Connect to CSV. All paths relative to the repository root.

| Table | Path | Grain |
|---|---|---|
| `ValidationResults` | `data/processed/scenario_*/validation_results.csv` | one row per expected element |
| `FailureInjections` | `data/received/scenario_*/failure_injections.csv` | one row per deliberate modification |
| `RunSummary` | `outputs/scenario_*/validation_run_summary.csv` | one row per run |
| `CompletenessByElement` | `outputs/scenario_*/completeness_by_element.csv` | one row per element name |
| `FidelityByElement` | `outputs/scenario_*/fidelity_by_element.csv` | one row per element name |
| `EvaluationByFailureType` | `outputs/scenario_*/evaluation_by_failure_type.csv` | one row per failure class |
| `DenominatorByPatient` | `data/expected/scenario_*/denominator_by_patient.csv` | one row per patient |

Use a folder query combining both `scenario_A` and `scenario_B` so the scenario
slicer works across the whole report.

---

## 2. Model

`ValidationResults` is the fact table. Everything else is either a rollup
(display directly) or a dimension.

```
        Dim_Element                    Dim_Verdict
             │                              │
             │  element_name                │  verdict
             ▼                              ▼
        ┌──────────────────────────────────────┐
        │        ValidationResults             │◄── FailureInjections
        │        (fact, one row per element)   │    (1:1 on element_uid,
        └──────────────────────────────────────┘     LEFT — most elements
             ▲                    ▲                  have no injection)
             │  patient_id        │  run_id + scenario_id
        Dim_Patient           Dim_Run
```

**Relationships**

| From | To | Cardinality | Direction |
|---|---|---|---|
| `ValidationResults[element_uid]` | `FailureInjections[target_element_uid]` | 1:1 | single, LEFT |
| `ValidationResults[patient_id]` | `Dim_Patient[patient_id]` | many:1 | single |
| `ValidationResults[verdict]` | `Dim_Verdict[verdict]` | many:1 | single |
| `ValidationResults[element_name]` | `Dim_Element[element_name]` | many:1 | single |

Build `Dim_Verdict` as a small manual table carrying `verdict`, `dimension`,
`is_failure`, and a `sort_order` — so failure categories appear in severity
order rather than alphabetically, and so a verdict can be relabeled for display
without touching the fact table.

---

## 3. Measures

Every measure guards its denominator with `DIVIDE`, which returns blank rather
than erroring on zero. That is deliberate: a patient who authorized nothing has
an undefined completeness, not 0%.

```dax
Expected Elements =
CALCULATE(
    COUNTROWS( ValidationResults ),
    ValidationResults[exchange_expectation] = "expected"
)

Elements Received =
CALCULATE(
    COUNTROWS( ValidationResults ),
    ValidationResults[exchange_expectation] = "expected",
    ValidationResults[delivery_status]      = "delivered",
    ValidationResults[received_value]      <> ""
)

Completeness % = DIVIDE( [Elements Received], [Expected Elements] )

Comparable Elements = [Elements Received]

Values Preserved =
CALCULATE(
    [Comparable Elements],
    NOT ValidationResults[verdict] IN { "value_mismatch", "semantic_degraded" }
)

Fidelity % = DIVIDE( [Values Preserved], [Comparable Elements] )

Consent Excluded =
CALCULATE(
    COUNTROWS( ValidationResults ),
    ValidationResults[exchange_expectation] = "excluded_by_consent"
)

Correct Authorized Exclusions =
CALCULATE( COUNTROWS( ValidationResults ),
           ValidationResults[verdict] = "authorized_exclusion" )

Unauthorized Disclosures =
CALCULATE( COUNTROWS( ValidationResults ),
           ValidationResults[verdict] = "unauthorized_disclosure" )

Total Failures =
CALCULATE( COUNTROWS( ValidationResults ), ValidationResults[status] = "FAIL" )
```

**Evaluation measures** — these are what make the report evidence rather than
decoration.

```dax
Injected Failures =
CALCULATE( COUNTROWS( FailureInjections ),
           FailureInjections[expected_detection] <> "none" )

Classification TP =
CALCULATE(
    COUNTROWS( ValidationResults ),
    ValidationResults[status] = "FAIL",
    FILTER( ValidationResults,
            RELATED( FailureInjections[expected_detection] )
            = ValidationResults[verdict] )
)

Detected (any class) =
CALCULATE( COUNTROWS( ValidationResults ),
           ValidationResults[status] = "FAIL",
           NOT ISBLANK( RELATED( FailureInjections[injection_id] ) ) )

False Negatives = [Injected Failures] - [Detected (any class)]

False Positives =
CALCULATE( COUNTROWS( ValidationResults ),
           ValidationResults[status] = "FAIL",
           ISBLANK( RELATED( FailureInjections[injection_id] ) ) )

Classification Sensitivity % = DIVIDE( [Classification TP], [Injected Failures] )
Detection Sensitivity %      = DIVIDE( [Detected (any class)], [Injected Failures] )
Precision %                  = DIVIDE( [Detected (any class)],
                                       [Detected (any class)] + [False Positives] )
```

Format all `%` measures as percentage, 2 decimals.

---

## 4. Pages

### Page 1 — Validation Overview
KPI row: Expected Elements · Elements Received · Completeness % · Fidelity % ·
Total Failures · Consent Excluded.

Put **Consent Excluded next to Completeness**, not buried. A reader must be able
to see at a glance that excluded elements are outside the denominator — that is
the project's central claim and the number that makes it visible.

Slicers: `scenario_id`, `run_id`, `consent_state`.

### Page 2 — Completeness
Bar chart, `Completeness %` by `element_name`, ascending, with a reference line
at 100%. Table below: `CompletenessByElement`. Drill-through to Page 6 on any
element.

### Page 3 — Fidelity
Stacked bar by `element_name`: values preserved / value mismatches / semantic
degradations. Keep the two failure types visually distinct — the difference
between "lost specificity" and "wrong value" is the point.

### Page 4 — Failure Patterns
Failure counts by `dimension` (completeness, fidelity, semantic, linkage,
timeliness, consent), with a second visual by `verdict` inside the selected
dimension. Sort by `Dim_Verdict[sort_order]`.

### Page 5 — Consent Correctness
Three cards: Correct Authorized Exclusions · Unauthorized Disclosures ·
Consent Over-Restrictions. Matrix of `consent_state` × `sensitivity_class`
showing element counts by outcome.

Report correct behavior alongside failures. A run with 27 authorized exclusions
and 0 unauthorized disclosures is evidence the consent layer worked, and that is
a finding — not an absence of one.

### Page 6 — Patient / Encounter Drill-Down
Table filtered to one patient: `element_name`, `expected_value`,
`received_value`, `status`, `verdict`, `detail`. Conditional formatting on
`status`. This page answers "show me exactly what happened to this patient."

### Page 7 — Framework Evaluation
The most important page for a reviewer.

Cards: Injected Failures · Classification TP · False Negatives · False Positives
· Classification Sensitivity % · Detection Sensitivity % · Precision %.
Table: `EvaluationByFailureType`, with `misclassified_as` visible.

Show classification and detection sensitivity **side by side**. Where they
differ, the framework caught the failure but named it wrongly, and hiding that
behind a single number would overstate what the tool can tell a user.

### Page 8 — Methodology and Limitations
Text page. Denominator definitions, the consent-exclusion rule, the
synthetic-data warning, the correlation-identifier assumption, and the measured
terminology blind spot. Link to the data dictionary and methodology note.

Not optional. Every number in this report is meaningless without its
denominator, and a dashboard that shows rates without definitions invites
exactly the misreading the project exists to argue against.

---

## 5. Rules for whoever builds this

1. **No business logic in DAX.** If a measure needs a rule the Python engine does not already produce, add it to the engine and regenerate — do not reimplement it here.
2. **Never display a rate without its denominator on the same page.**
3. **Blank means undefined, not zero.** Do not replace blanks with 0 in visuals; a zero denominator is a real state that means "not applicable."
4. **Label the synthetic-data warning on every page footer.** Screenshots get separated from their context, and a chart showing "96% completeness" with no provenance will eventually be read as a real-world finding.
