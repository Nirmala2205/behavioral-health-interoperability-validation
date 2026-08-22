# Architecture

## Pipeline

```
                    config/  (Validation Contract, consent rules,
                              equivalence map, scenarios, injection profiles)
                       │
                       ▼  read once, by config_loader.py
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                      │
  │  1  generate/synthetic_source.py                                     │
  │     └─► SOURCE_TRUTH        what the sending EHR holds (long form)   │
  │                       │                                              │
  │  2  transform/expected_exchange.py                                   │
  │     └─► EXPECTED_EXCHANGE   + consent_state, authorized,             │
  │                       │       exchange_expectation   ◄── DENOMINATOR │
  │                       ├──────────────────────┐                       │
  │  3  transform/fhir_builder.py                │                       │
  │     └─► FHIR R4 bundles (authorized only)    │                       │
  │                                              │                       │
  │  4  transform/destination.py                 ▼                       │
  │     build_wire_copy   ─► scenario rendering (units, case, timing)    │
  │     clean_received    ─► delivered | withheld_notice                 │
  │                       │                                              │
  │  5  inject_failures/injector.py                                      │
  │     └─► RECEIVED_DATA  +  FAILURE_INJECTIONS  ◄── REFERENCE STANDARD │
  │                       │                              │               │
  │  6  validate/engine.py                               │               │
  │     normalize ─► compare ─► classify ─► precedence   │               │
  │     └─► VALIDATION_RESULTS  (one row per element)    │               │
  │                       │                              │               │
  │  7  sql/*.sql via DuckDB                             │               │
  │     └─► completeness / fidelity / run summary        │               │
  │                       │                              │               │
  │  8  metrics/evaluate.py  ◄───────────────────────────┘               │
  │     └─► TP / FP / FN / TN, sensitivity, precision, specificity       │
  │                       │                                              │
  └───────────────────────┼──────────────────────────────────────────────┘
                          ▼
                    outputs/  ─►  Power BI (display only, no logic)
```

## Design rules

**1. Configuration is not code.**
No element name, comparison rule, tolerance, code relationship, or threshold
appears in the engine. All of it lives in `config/`. This is what makes a second
source configuration (Scenario B) a config change rather than a code change, and
it is a stated success condition in the project blueprint.

**2. One source of truth per fact.**
The Python engine decides element-level verdicts. SQL aggregates them. Power BI
displays the aggregates. Nothing recomputes anything upstream of it. A DAX
measure reimplementing a completeness rule would create two definitions that
silently diverge.

**3. The reference standard is separate from the detector.**
The injection ledger records what was broken, in its own vocabulary
(`drop_required_element`), distinct from the detector's verdict vocabulary
(`missing_element`). Sharing the vocabulary would make the evaluation partly
circular.

**4. Fail loudly on anything undeclared.**
An unknown normalizer, comparator, element, or consent state raises. A silently
skipped rule produces a clean-looking run containing a false negative — the
worst outcome for a tool built to find silent failures.

**5. Determinism everywhere.**
Every random source is seeded from config. `--verify-reproducible` runs the
pipeline twice and compares output hashes.

## Module map

| Module | Responsibility | Key decision it owns |
|---|---|---|
| `config_loader.py` | parse and validate config | refuses undeclared elements |
| `generate/synthetic_source.py` | build SOURCE_TRUTH | sensitivity class per clinical group |
| `transform/expected_exchange.py` | build the denominator | authorized vs. excluded |
| `transform/fhir_builder.py` | FHIR R4 representation | authorized content only |
| `transform/destination.py` | wire rendering, clean delivery | rendering ≠ corruption |
| `inject_failures/injector.py` | controlled failures + ledger | injections verify their own post-conditions |
| `validate/normalize.py` | strip representation | flag unparseable, never coerce |
| `validate/rules.py` | compare content | three-valued outcome |
| `validate/engine.py` | classify and prioritize | verdict precedence |
| `metrics/evaluate.py` | score the detector | detection vs. classification, separately |

## Data flow contract

| Dataset | Grain | Rows (Scenario A, n=10) |
|---|---|---|
| SOURCE_TRUTH | one clinical element instance | 184 |
| EXPECTED_EXCHANGE | same, + authorization | 184 |
| RECEIVED_DATA | one destination record | ~184 minus silent drops |
| FAILURE_INJECTIONS | one deliberate modification | 21 (18 failures + 3 negative controls) |
| VALIDATION_RESULTS | one verdict per expected element | 184 |
