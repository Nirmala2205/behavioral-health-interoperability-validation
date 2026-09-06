# Behavioral Health Interoperability Validation Framework

[![Tests](https://github.com/Nirmala2205/behavioral-health-interoperability-validation/actions/workflows/tests.yml/badge.svg)](https://github.com/Nirmala2205/behavioral-health-interoperability-validation/actions/workflows/tests.yml)

A reproducible proof-of-concept that detects and quantifies **silent
data-quality failures** during behavioral-health information exchange — the
kind that leave a record looking technically fine while its clinical content
has quietly changed, gone missing, or become attached to the wrong person.

**Synthetic data only. No real patient information is used anywhere in this
repository.**

---

## The problem

A successful technical exchange does not prove the receiving system got a
complete and faithful representation of what was supposed to move.

FHIR conformance validation answers *"is this resource well-formed?"* — and a
resource can be perfectly well-formed while carrying the wrong content. An
`Observation` with `valueQuantity: 8` where the patient scored 18 is valid
FHIR. A `Condition` coded `F32.9` where the source said `F32.1` is valid FHIR.
A structural validator passes both.

This project asks the different question: **of the behavioral-health
information that was expected and authorized to move, what arrived, what
changed, what did not arrive, and how confidently can we detect the
difference?**

Behavioral-health exchange raises an additional validation problem: information may be absent because it was lost, altered, or intentionally excluded from an authorized exchange. In this synthetic proof of concept, the expected exchange is therefore defined as the subset of source information both expected and authorized to move.

The authorization model used here is synthetic and simplified. It is motivated by privacy-sensitive behavioral-health exchange, including constraints such as 42 CFR Part 2, but it is not an implementation of those regulations.

---

## What this does

```text
SOURCE_TRUTH
    |
    v
EXPECTED_AUTHORIZED_EXCHANGE
    |
    v
FHIR R4  ->  RECEIVED_DATA  ->  VALIDATION_RESULTS
                 ^
                 |
       controlled failure injection
       (ground-truth ledger kept separate)
```

Seven validation dimensions, each answering a distinct question:

| Dimension | Question | Example failure |
|---|---|---|
| **Completeness** | Did every expected element arrive? | expected assessment element absent |
| **Fidelity** | Did values survive intact? | numeric score altered |
| **Semantic preservation** | Did clinical meaning survive? | diagnosis code replaced with a less-specific code |
| **Authorization correctness** | Was only authorized information exchanged, without wrongly withholding authorized information? | restricted element disclosed, or authorized element withheld |
| **Patient linkage** | Was the information linked to the correct patient? | record assigned to the wrong patient |
| **Encounter linkage** | Was the information linked to the correct encounter? | assessment assigned to the wrong visit |
| **Timeliness** | Did it arrive within the expected exchange window? | data arrived outside the configured threshold |

**The central design decision** is that the comparison is not simply source vs. destination. It is source -> **expected/authorized exchange** -> received. Elements excluded by the synthetic authorization rules are removed from the expected denominator before completeness is evaluated, allowing authorized withholding to be distinguished from simulated data loss within the benchmark.

---

## Results

The pipeline produces the validation and evaluation results. Archived benchmark
reports live under `outputs/benchmarks/`, and
`python src/generate_statistical_report.py` reproducibly derives the reported
Wilson confidence intervals from those artifacts.

### Micro-prototype — 10 synthetic patients, two scenarios

| | Scenario A | Scenario B |
|---|---|---|
| Source elements | 184 | 162 |
| Expected (authorized) | 157 | 154 |
| Excluded by consent | 27 | 8 |
| Completeness | 96.18% | 96.10% |
| Fidelity | 96.69% | 96.62% |
| **Failures injected** | **18** | **18** |
| Correctly classified | 18 | 18 |
| Missed (FN) | 0 | 0 |
| False positives | 0 | 0 |
| Classification sensitivity | 100% | 100% |
| Precision | 100% | 100% |
| Negative controls wrongly flagged | 0 | 0 |

Completeness was independently recomputed from the injection ledger using
arithmetic that shares no code with the engine: **96.18% vs 96.18%, agrees.**

### Scaled benchmark — 500 synthetic patients per scenario

The archived probabilistic benchmark evaluates 1,000 synthetic patient-scenario
runs across two differently rendered exchange paths.

| | Scenario A | Scenario B | Combined |
|---|---:|---:|---:|
| Evaluated elements | 8,421 | 8,347 | 16,768 |
| Injected failures | 1,557 | 1,543 | 3,100 |
| Correctly classified | 1,557 | 1,543 | 3,100 |
| False negatives | 0 | 0 | 0 |
| False positives | 0 | 0 | 0 |
| True negatives | 6,864 | 6,804 | 13,668 |
| Classification sensitivity | 100% | 100% | 100% |
| Precision | 100% | 100% | 100% |
| Specificity | 100% | 100% | 100% |

The combined classification estimate is **3,100/3,100 (100%; 95% Wilson CI
99.88%–100%)**. Combined specificity is **13,668/13,668 (100%; 95% Wilson CI
99.97%–100%)**. These intervals quantify uncertainty from finite synthetic
samples; they do not establish performance on real-world exchange data.

Reproducible benchmark artifacts and statistical summaries are preserved under
`outputs/benchmarks/`.

### Robustness across synthetic scenarios

Scenario B contains the same kinds of synthetic clinical information but represents several values differently on the exchange path, including dose units, schedule notation, code casing, and timing. These representation differences were intentionally treated as non-failures so the benchmark could test whether the framework distinguished equivalent representations from injected data-quality defects.

| Scenario | Correctly classified | Classification sensitivity (95% CI) | Precision (95% CI) | Specificity (95% CI) |
|---|---:|---:|---:|---:|
| A | 1,557/1,557 | 100% (99.75%–100%) | 100% (99.75%–100%) | 100% (99.94%–100%) |
| B | 1,543/1,543 | 100% (99.75%–100%) | 100% (99.75%–100%) | 100% (99.94%–100%) |

Both scenarios also completed clean runs with zero injected failures and zero findings, providing a direct false-positive check within the synthetic benchmark.

### Reproducibility

`--verify-reproducible` runs the pipeline twice and compares SHA-256 hashes of the generated outputs. The tested runs produced identical output hashes. Each FHIR build first clears generated bundles from the prior run, preventing a changed patient count from leaving stale resources in the corpus. The archived primary and held-out benchmark reports can also be converted back into the same 34-row CSV and JSON statistical summaries with `python src/generate_statistical_report.py`.

---

## What the perfect scores do and do not mean

The 100% primary-benchmark results show that, for the predefined synthetic failure modes and reference data used here, the detector and evaluation logic behaved consistently with the injected ground truth. They also show that the authorization-aware denominator operated as intended within the tested scenarios.

These results do not establish performance on unanticipated failure modes, independently annotated data, or real-world exchange data. The framework should therefore be interpreted as a synthetic proof of concept and a candidate for further independent and real-data evaluation under appropriate governance.

To probe a known limitation, the repository includes a held-out terminology profile:

```bash
python src/run_pipeline.py --profile blindspots --patients 500
```

The profile constructs diagnosis-code degradations using an ICD-10-CM category-ancestor relationship (`F32.1 → F32`) that is deliberately withheld from the curated equivalence map.

| | Detection sensitivity (95% CI) | Classification sensitivity (95% CI) |
|---|---:|---:|
| Curated degradations | 10/10, 100% (72.25%–100%) | 10/10, 100% (72.25%–100%) |
| **Uncurated degradations** | **10/10, 100% (72.25%–100%)** | **0/10, 0% (0%–27.75%)** — reported as `value_mismatch` |
| Combined | 20/20, 100% (83.89%–100%) | **10/20, 50% (29.93%–70.07%)** |

In this held-out benchmark, all 20 tested terminology degradations were detected, but the 10 cases outside the curated equivalence map were misclassified as `value_mismatch`. This result identifies a limitation of the hand-curated mapping approach and motivates future evaluation of hierarchy- or terminology-graph-based semantic equivalence.
---

## Four bugs worth reading about

The first three surfaced through evaluation and reproducibility checks; the
fourth was found during final code-and-documentation review. They are documented
because how an evaluation framework fails is more informative than the fact that
it eventually passed.

**1. Phantom false positives from baseline latency.**
Scenario B's original transmission config (25 min base + up to 40 min jitter)
could exceed the 60-minute crisis threshold on its own. A zero-injection run
reported four false positives — and the framework was right every time; those
arrivals genuinely were late. The bug was that the injection ledger, which the
evaluation treats as an exhaustive list of true failures, did not know about
them. Fixed by bounding baseline latency below every threshold, and by an
assertion in `run_pipeline.py` so a future config edit cannot reintroduce it.

**2. An injector that did not verify its own perturbation.**
`delay_arrival` added a flat 240 minutes. That comfortably breaches the
60-minute crisis window and comes nowhere near the 24-hour routine one — so on
ambulatory encounters it created a ledger entry claiming a timeliness failure
where none existed. The 500-patient run reported 114 false negatives and 32%
timeliness sensitivity for a detector behaving correctly on every one of them.
Fixed by making the injector compute the delay actually required to cross each
element's threshold.

**3. Stale FHIR bundles surviving between runs.**
A scaled run followed by a smaller run left hundreds of old generated bundles in
the live exchange directory. Because each run is intended to create one complete
corpus, files from a previous patient count could contaminate corpus validation
and reproducibility evidence. Fixed by clearing only generated
`*-exchange.json` files before rebuilding the corpus, with a regression test
covering the cleanup behavior.

**4. A CLI option accepted but never dispatched.**
The pipeline advertised `--fhir-failure patient-linkage`, and the injector and
receiver both had end-to-end component tests, but a duplicated `element-loss`
branch meant the patient-linkage injector was never called by `run_scenario()`.
A clean CLI run could therefore complete with no injected linkage failure.
Fixed by wiring the option to `inject_fhir_wrong_patient_linkage` and adding a
pipeline-dispatch regression test. The corrected path injects three related
diagnosis elements at the FHIR layer and classifies all three as
`patient_linkage`.

The broader lesson: **an injected failure is ground truth only if it actually
produces the failure condition, enters the evaluated path, and is isolated from
state left by earlier runs.** Detector performance is uninterpretable unless the
evaluation machinery proves all three.

---

## Running it

```bash
git clone <this-repo> && cd behavioral-health-interoperability-validation
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python src/run_pipeline.py                    # both scenarios, micro-prototype
python -m pytest tests/ -q                    # 116 tests
python src/generate_statistical_report.py    # rebuild benchmark CIs
```

| Command | What it does |
|---|---|
| `--scenarios A` | run one scenario only |
| `--clean` | run with zero destination-stage injections for a false-positive check |
| `--patients 500 --mode probabilistic` | run the scaled probabilistic benchmark |
| `--profile blindspots` | run the adversarial terminology evaluation |
| `--fhir-failure <mode>` | inject one FHIR-layer failure; modes: `numeric`, `semantic`, `element-loss`, `patient-linkage` |
| `--verify-reproducible` | run twice and compare output hashes |

The four FHIR-stage modes reuse the same clinical failure classes as the
destination-stage injector, allowing the framework to test whether corruption
introduced on the wire survives parsing and is still classified correctly.

Outputs land in `outputs/` (metrics, Power BI inputs), `data/processed/`
(element-level results), and `fhir/exchange/` (FHIR R4 bundles).

---

## How it is built

| Layer | Tool | Role |
|---|---|---|
| Synthetic generation | Python (deterministic, seeded) | non-PHI source patients — see note below |
| Source / destination modeling | pandas, CSV | element-level long-form tables |
| Exchange representation | FHIR R4 JSON | Patient, Encounter, Condition, Observation, MedicationRequest, Consent |
| Failure injection | Python | 10 primary failure types, one negative control, one held-out adversarial variant, and a ground-truth ledger |
| Validation engine | Python | normalization, comparison, classification |
| Aggregation | DuckDB / SQL | completeness, fidelity, run summary |
| Evaluation | Python | TP/FP/FN/TN, sensitivity, precision, specificity |
| Testing | pytest | 116 tests |
| Visualization | Power BI | 8-page dashboard over the output tables |

**Why not Synthea.** The blueprint allowed "Synthea and/or controlled custom
synthetic records," and V1 uses controlled generation deliberately: a validation
experiment needs *exactly known* ground truth, and reconstructing an
element-level truth ledger from Synthea output is itself an error-prone mapping
step whose mistakes would silently corrupt the reference standard. Synthea's
behavioral-health depth is also thin relative to what this validates (Part 2
segmentation, PHQ-9/GAD-7, consent state). `data/raw/synthea/` is reserved for a
later realism extension. Full reasoning in
[`docs/methodology/methodology_note.md`](docs/methodology/methodology_note.md).

Nothing in the engine hard-codes an element name, comparison rule, or tolerance
— all of it lives in `config/`, which is what makes a second source
configuration a config change rather than a code change.

---

## Repository layout

```
config/     Validation Contract, consent rules, code equivalence,
            exchange scenarios, injection profiles
src/        generate/ transform/ inject_failures/ validate/ metrics/
sql/        completeness, fidelity, run summary (executed by the pipeline)
tests/      116 tests, including contract/documentation sync
docs/       data dictionary, methodology, architecture, walkthrough
fhir/       generated FHIR R4 bundles
outputs/    metrics and Power BI input tables
powerbi/    data model and DAX specification
```

Start with
[`docs/data_dictionary/v1_validation_contract.md`](docs/data_dictionary/v1_validation_contract.md)
— it defines every element, rule, and denominator before any code runs.
[`docs/walkthrough.md`](docs/walkthrough.md) traces a single element end to end.
[`docs/manuscript/results_and_discussion.md`](docs/manuscript/results_and_discussion.md)
provides a manuscript-ready account of the results, interpretation, validity
threats, and future work.

---

## Limitations

This is a research prototype. It does not:

- operate inside a live HIE, or connect to any production EHR;
- claim any commercial EHR or HIE is currently losing data;
- estimate real-world failure rates — injection rates are experimental parameters chosen to exercise the detector, and synthetic prevalence means nothing;
- replace FHIR conformance validation, which answers a different and complementary question;
- model real consent workflows, which are jurisdiction-, organization-, and workflow-specific;
- automatically repair anything. Detection, classification, and measurement only.

Additional stated assumptions: persistent correlation identifiers survive
exchange (modeling FHIR `Resource.id`); DS4P withholding notices are
element-level rather than document-level; terminology equivalence is
hand-curated. Each is discussed with its consequences in the methodology note.

---

## Context

Built as an independent research prototype supporting PhD applications in
biomedical/health informatics, in a research direction concerning behavioral
health interoperability and the detection of completeness, fidelity, and
semantic-preservation failures as clinical information moves across
heterogeneous EHR and HIE environments.

It is a bounded methodological contribution — a way to *detect and measure* one
class of problem — not a solution to behavioral-health interoperability. The
federal BHIT Initiative, a nine-state pilot launched in February 2026 with
$20M+ in funding, calls itself a pilot testing two standards. That is the right
scale to calibrate against.

---

**Standards referenced:** HL7 FHIR R4 (4.0.1) · US Behavioral Health Profiles IG
v0.1.0 · USCDI+ Behavioral Health · LOINC · ICD-10-CM · RxNorm · UCUM ·
42 CFR Part 2 (Final Rule, compliance February 16, 2026)
