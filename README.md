# Behavioral Health Interoperability Validation Framework

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

Behavioral health is where this matters most and is studied least. 68% of
behavioral-health facilities use an EHR, but only 19% participate in a health
information exchange, and 67% do not know whether an HIE is even available to
them.¹ The 2009 HITECH Act's $25B+ in adoption incentives excluded behavioral
health facilities, so the sector never built the exchange infrastructure or the
institutional expertise that physical health spent fifteen years accumulating.
On top of that, substance-use-disorder records carry an additional consent
layer under 42 CFR Part 2 — whose Final Rule compliance deadline passed in
February 2026 — which means **correctly withheld data and lost data look
identical at the destination.** A validation method that cannot tell those
apart is not merely imprecise; it penalizes organizations for protecting
patients.

---

## What this does

```
SOURCE_TRUTH  ──►  EXPECTED_EXCHANGE  ──►  FHIR R4  ──►  RECEIVED_DATA  ──►  VALIDATION
what the           what consent           wire            what the             what survived
sender has         authorized             format          receiver has         and what didn't
                        │                                      ▲
                        └──────── controlled failure injection ┘
                                  (with a ground-truth ledger)
```

Six validation dimensions, each answering a distinct question:

| Dimension | Question | Example failure |
|---|---|---|
| **Completeness** | Did every expected element arrive? | PHQ-9 expected, absent |
| **Fidelity** | Did values survive intact? | PHQ-9 18 → 8 |
| **Semantic preservation** | Did clinical meaning survive? | `F32.1` → `F32.9` (severity lost) |
| **Record linkage** | Right patient, right encounter? | assessment on the wrong visit |
| **Timeliness** | Did it arrive in the clinically useful window? | crisis data 4 hours late |
| **Consent correctness** | Were restrictions honored — in both directions? | Part 2 element disclosed, or wrongly withheld |

**The central design decision** is that the comparison is *not* source vs.
destination. It is source → **expected/authorized** → received. Consent-excluded
elements are removed from the denominator before anything is counted, so
lawfully withheld Part 2 data never registers as data loss.

---

## Results

Every number below is produced by `python src/run_pipeline.py` and written to
`outputs/`.

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

### Scaled benchmark — 500 synthetic patients, probabilistic injection

8,421 elements · 1,557 injected failures · **1,557 correctly classified · 0 false negatives · 0 false positives** · runtime under 4 seconds.

### Generalization across scenarios

Scenario B is the same clinical content rendered differently on the wire: doses
in grams instead of milligrams, HL7 GTS abbreviations (`QD`) instead of free
text (`daily`), lower-case codes, a slower exchange path. None of those are
data-quality failures, and a framework tuned to one schema would report them as
findings.

| Scenario | Classification sensitivity | Precision | Specificity | False positives |
|---|---|---|---|---|
| A | 100% | 100% | 100% | 0 |
| B | 100% | 100% | 100% | 0 |

Both scenarios also run clean (zero injections → **zero findings**), which is
the sharpest false-positive test available: any finding in a clean run has
nowhere to hide.

### Reproducibility

`--verify-reproducible` runs the entire pipeline twice and compares SHA-256
hashes of every output. **Identical.**

---

## What the perfect scores do and do not mean

100% sensitivity on synthetic, self-injected failures is a **necessary
condition, not an achievement.** It demonstrates the comparison rules are
internally consistent, the reference standard is sound, and the consent
denominator behaves correctly. It says nothing about performance against
real-world failures whose modes were never anticipated — and the failures that
matter most in practice are precisely the unanticipated ones.

Anyone reporting these numbers as evidence the method "works" on real exchange
data would be overclaiming. They are evidence the method is *ready to be tested*
on real data.

To keep that honest, the repository includes an **adversarial profile** that
injects a failure the framework is known to handle badly:

```bash
python src/run_pipeline.py --scenarios A --profile blindspots
```

A diagnosis code degrades to its ICD-10-CM category ancestor (`F32.1 → F32`) —
a genuine loss of specificity that is deliberately absent from the curated
equivalence map.

| | Detection sensitivity | Classification sensitivity |
|---|---|---|
| Curated degradations | 100% | 100% |
| **Uncurated degradations** | **100%** | **0%** — reported as `value_mismatch` |
| Combined | 100% | **50%** |

The honest characterization: **a curated-terminology approach does not miss
things, it mislabels the things outside its curation.** The implication — that a
dissertation-scale version must derive equivalence from the ICD-10-CM hierarchy
and RxNorm graph rather than a YAML file — follows from a measurement rather
than an opinion.

---

## Two bugs worth reading about

Both were found by the pipeline's own diagnostics, and both were defects in the
**measurement**, not the detector. They are documented in the code because how a
framework fails is more informative than that it eventually passed.

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

The general lesson, which applies to any evaluation of this kind: **an injected
failure is only ground truth if it actually produces the failure condition.**

---

## Running it

```bash
git clone <this-repo> && cd behavioral-health-interoperability-validation
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python src/run_pipeline.py                    # both scenarios, micro-prototype
python -m pytest tests/ -q                    # 94 tests
```

| Command | What it does |
|---|---|
| `--scenarios A` | one scenario only |
| `--clean` | zero injections — the false-positive check |
| `--patients 500 --mode probabilistic` | Stage B scaled benchmark |
| `--profile blindspots` | adversarial run against known limitations |
| `--verify-reproducible` | run twice, compare output hashes |

Outputs land in `outputs/` (metrics, Power BI inputs), `data/processed/`
(element-level results), and `fhir/exchange/` (FHIR R4 bundles).

---

## How it is built

| Layer | Tool | Role |
|---|---|---|
| Synthetic generation | Python (deterministic, seeded) | non-PHI source patients — see note below |
| Source / destination modeling | pandas, CSV | element-level long-form tables |
| Exchange representation | FHIR R4 JSON | Patient, Encounter, Condition, Observation, MedicationRequest, Consent |
| Failure injection | Python | 12 failure types + a ground-truth ledger |
| Validation engine | Python | normalization, comparison, classification |
| Aggregation | DuckDB / SQL | completeness, fidelity, run summary |
| Evaluation | Python | TP/FP/FN/TN, sensitivity, precision, specificity |
| Testing | pytest | 94 tests |
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
tests/      94 tests, including contract/documentation sync
docs/       data dictionary, methodology, architecture, walkthrough
fhir/       generated FHIR R4 bundles
outputs/    metrics and Power BI input tables
powerbi/    data model and DAX specification
```

Start with
[`docs/data_dictionary/v1_validation_contract.md`](docs/data_dictionary/v1_validation_contract.md)
— it defines every element, rule, and denominator before any code runs.
[`docs/walkthrough.md`](docs/walkthrough.md) traces a single element end to end.

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

¹ ONC/ASTP, *Electronic Health Record Adoption and Exchange Capabilities Among
Substance Use and Mental Health Treatment Facilities*, 2024.

**Standards referenced:** HL7 FHIR R4 (4.0.1) · US Behavioral Health Profiles IG
v0.1.0 · USCDI+ Behavioral Health · LOINC · ICD-10-CM · RxNorm · UCUM ·
42 CFR Part 2 (Final Rule, compliance February 16, 2026)
