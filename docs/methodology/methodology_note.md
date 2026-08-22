# Methodology Note

Design decisions, their justifications, and the limitations they create.
Written so a reviewer can evaluate the reasoning rather than take the results on
trust — and so that anything later found to be wrong can be traced to a stated
choice rather than an accident.

---

## 1. Why synthetic data, and why not Synthea

**Decision.** V1 uses a deterministic custom generator rather than Synthea.

**Reasoning.** The project blueprint permitted "Synthea and/or controlled custom
synthetic records." Three considerations decided it:

1. **Ground truth must be exact.** The evaluation scores the detector against a
   ledger of deliberately injected failures. That ledger is only trustworthy if
   the pre-failure state is known precisely at element level. Deriving an
   element-level truth table from Synthea's longitudinal output is itself a
   mapping step, and a mistake in it would silently corrupt the reference
   standard — producing a confident, wrong performance number. Not a risk worth
   taking for realism the experiment does not need.
2. **Behavioral-health depth.** Synthea's behavioral-health modeling is thin
   relative to what this framework validates: Part 2 sensitivity segmentation,
   PHQ-9/GAD-7 instruments with clinically-banded scores, per-patient consent
   state. Most of it would have to be synthesized regardless.
3. **Auditability at small scale.** At ten patients a reviewer can read
   `source_truth.csv` and verify the expected set by hand. That is a real
   property to protect while the rules are being established.

**Limitation.** The synthetic data does not reproduce real clinical workflow
patterns, real missingness structure, or real vendor behavior. **No result here
transfers to a prevalence claim about real exchange.** Synthea is the right tool
for a realism extension once the rules are stable; `data/raw/synthea/` is
reserved for it.

---

## 2. The three-dataset comparison

**Decision.** Validation compares SOURCE_TRUTH → EXPECTED_EXCHANGE → RECEIVED,
never source directly to destination.

**Reasoning.** In behavioral health, correct privacy behavior and data loss are
indistinguishable at the destination. Both are absence. The only thing that
separates them is independent knowledge of what was authorized to move.

A framework without this step does not lose a little accuracy on Part 2 data —
it inverts the measurement. The more carefully an organization honors SUD
restrictions, the worse its data quality appears. That would make the tool
harmful to exactly the organizations it exists to help.

**Limitation.** It requires the consent state to be known and correct. The
framework validates exchange against a consent model; it does not validate the
consent model itself.

---

## 3. Modeling withheld data with an explicit notice

**Decision.** The destination has three states — `delivered`,
`withheld_notice`, and no-row-at-all — rather than two.

**Reasoning.** Three situations are otherwise identical from the destination's
point of view:

| Consent authorized it? | Destination state | Verdict |
|---|---|---|
| No | `withheld_notice` | PASS — correct exclusion |
| Yes | `withheld_notice` | FAIL — faulty restriction rule |
| Yes | no row | FAIL — silent technical loss |

Without a withholding signal, rows 2 and 3 collapse into one another. That
would still be an honest answer, but a less useful one: the second is a
consent-configuration problem and the third is an IT problem, and they go to
different people.

This models Data Segmentation for Privacy (DS4P) practice, where a receiver is
told content was redacted without being told what it was.

**Limitations.** Real DS4P notices are typically document- or section-level, not
element-level, so the framework's ability to localize a wrongful withholding to
a specific element is optimistic. And not every exchange path emits a notice at
all; where none exists, `consent_over_restriction` is undetectable and the
framework would correctly fall back to reporting `missing_element`.

---

## 4. Three-valued comparison

**Decision.** Comparators return `match` / `degraded` / `mismatch`.

**Reasoning.** `F32.1 → F32.9` (severity specifier lost) and `F32.1 → I10`
(hypertension) are both "not equal." Collapsing them discards the finding that
is most characteristic of interoperability failure: content that is
structurally valid and clinically diminished. Semantic preservation could not
be a dimension without this.

**Limitation.** It depends on a curated equivalence map — see §5.

---

## 5. Hand-curated terminology, and its measured cost

**Decision.** Equivalence relationships live in `config/code_equivalence.yaml`,
curated by hand for a small V1 vocabulary.

**Reasoning.** Blueprint Section 21 flagged terminology equivalence as a risk
and recommended starting with a small documented set. Hand curation is
auditable at this scale: every relationship can be inspected and disputed.

**Limitation — measured, not asserted.**
`config/injection_profile_blindspots.yaml` injects real degradations the map
does not cover (ICD-10-CM category ancestors, e.g. `F32.1 → F32`):

| | Detection | Classification |
|---|---|---|
| Curated | 100% | 100% |
| Uncurated | 100% | 0% (reported `value_mismatch`) |

A curated approach **does not miss things; it mislabels the things outside its
curation.** A dissertation-scale version must derive equivalence from the
ICD-10-CM hierarchy and the RxNorm relationship graph (UMLS, RxNav). Quantifying
the gap is more useful than a README caveat, and it makes the case for the
harder approach on evidence.

---

## 6. Correlation identifiers

**Decision.** Expected and received records are matched on
`exchange_element_id`, a wire identifier that survives transmission.

**Reasoning.** This models FHIR's persistent `Resource.id` / `Identifier`, which
does survive exchange in practice. It makes linkage validation well-defined: a
relinked element is still findable, so "delivered under the wrong patient" is
distinguishable from "missing here and unexpectedly present there."

**Limitation.** Load-bearing. An exchange path that does not preserve stable
identifiers requires probabilistic record matching, and matching error would
confound every downstream metric — a validator would then be measuring its own
matcher as much as the exchange. Extending to that case is real research, not a
configuration change.

---

## 7. Zero tolerance on assessment scores

**Decision.** `assessment_score` compares with tolerance exactly 0.

**Reasoning.** PHQ-9 severity bands are five points wide (0–4, 5–9, 10–14,
15–19, 20–27). Any nonzero tolerance admits a value crossing a band boundary
while the framework reports a match, which could mean a changed treatment
decision recorded as no finding. Zero requires no clinical defense; any other
value does.

**Limitation.** Zero tolerance would be wrong for measurements with genuine
instrument variance (a lab value, a vital sign). The tolerance is declared
per-element in the contract precisely so that a future element can declare a
different, defended value.

---

## 8. Verdict precedence

**Decision.** One primary verdict per element, ordered
consent > completeness > linkage > value/semantic > timeliness, with a
`secondary_findings` column retaining the rest.

**Reasoning.** Multi-verdict elements would double-count in any aggregate. A
single primary verdict makes counts well-defined; retaining secondaries means
nothing is discarded and a reader who disagrees with the ordering can re-derive
every count without rerunning anything.

**Limitation.** The ordering is a judgment, not a derivation. It is stated in
the contract rather than left implicit in the order of if-statements.

---

## 9. Non-overlapping injections

**Decision.** The injector claims each element so no two failures target the
same one.

**Reasoning.** If an element were both value-corrupted and delayed, there would
be no single correct verdict to score against, and the reference standard would
become ambiguous exactly where it needs to be sharp.

**Limitation.** Real failures co-occur, sometimes causally (a mapping defect
that both drops a subfield and degrades a code). Multi-failure elements are a
genuine extension and would require an evaluation that scores verdict *sets*
rather than single labels.

---

## 10. Bounded baseline latency

**Decision.** Every scenario's worst-case transmission latency is held below the
tightest timeliness threshold, asserted at pipeline startup.

**Reasoning.** The evaluation treats the injection ledger as an exhaustive
record of true failures. A scenario whose ordinary latency could breach a
threshold would contain true timeliness failures that were never injected, and
each would be scored as a false positive.

This is not hypothetical. Scenario B originally had base 25 + jitter 40 min
against a 60-minute crisis threshold, and a zero-injection run reported four
false positives on arrivals that genuinely were late. The framework was right;
the measurement was wrong.

**Limitation.** It means the project cannot currently study an exchange path
whose *routine* latency breaches a clinical window — which is a realistic and
interesting scenario. Doing so requires a timeliness reference standard derived
independently of the validator's own threshold logic; deriving it from the same
thresholds would score the detector against itself. **Named future work.**

---

## 11. Injections must verify their own post-conditions

**Decision.** `delay_arrival` computes the delay actually required to cross the
target element's threshold rather than applying a flat offset.

**Reasoning.** A flat 240-minute delay breaches a 60-minute crisis window and
comes nowhere near a 24-hour routine one. On ambulatory encounters it produced
ledger entries claiming timeliness failures that did not exist. The 500-patient
run reported 114 false negatives and 32% timeliness sensitivity for a detector
that was correct in every one of those cases.

The general principle, which applies to any injection-based evaluation:
**an injected failure is only ground truth if it actually produces the failure
condition.** An injector that does not check its own post-condition silently
corrupts the reference standard, and the resulting error is attributed to the
detector.

**Note on circularity.** The injector now reads the same threshold table the
engine reads. That is shared experimental specification, not circular
validation: the threshold defines what "late" means for the experiment, and the
engine still derives its verdict independently from observed timestamps. This is
categorically different from §10, where the ledger was *incomplete* — here it
was *incorrect*.

---

## 12. FHIR conformance is not claimed

**Decision.** Generated bundles are aligned to USCDI+ BH and the US Behavioral
Health Profiles IG (v0.1.0, FHIR R4) element choices, but conformance is **not
asserted**.

**Reasoning.** Asserting conformance requires running the official HL7 validator
against published StructureDefinitions. That has not been done. Claiming it
without running it would be precisely the kind of unverified assertion this
project argues against.

**Future work.** Add `$validate` / the HL7 Java validator as a distinct
pipeline stage, reported separately from exchange-quality validation — a
structurally valid resource with wrong content should show conformance PASS and
fidelity FAIL simultaneously. That contrast is the project's central claim made
visible in one table.

---

## 13. What the perfect scores mean

100% classification sensitivity and 0 false positives, at both 10- and
500-patient scale and across two rendering scenarios, is a **necessary
condition, not an achievement.** It demonstrates:

- the comparison rules are internally consistent;
- the reference standard is sound (after two defects in it were found and fixed);
- the consent denominator behaves correctly in both directions;
- normalization absorbs rendering differences without absorbing real ones;
- results are deterministic and reproducible.

It does **not** demonstrate anything about real-world failures whose modes were
never anticipated — which are the ones that matter. A detector evaluated only
against failures its own author imagined will score well by construction. The
adversarial profile exists to keep that fact visible in the numbers, and the
honest summary of these results is: *the method is ready to be tested on real
data*, not *the method works*.

---

## 14. Future work, in priority order

1. **FHIR conformance as a distinct stage** — show conformance PASS alongside fidelity FAIL on the same resource.
2. **Hierarchy-derived terminology equivalence** — replace the curated map with ICD-10-CM/RxNorm relationship traversal; re-run the blind-spot profile to measure the improvement.
3. **Multi-failure elements** — score verdict sets rather than single labels.
4. **Independent timeliness ground truth** — enables scenarios whose baseline latency breaches clinical windows.
5. **Probabilistic record matching** — remove the persistent-identifier assumption.
6. **Realistic consent workflows** — CRISP's Consent Tool as the reference model.
7. **Synthea-based realism layer** — once rules are stable and ground truth extraction can be validated.
8. **Real data, under a data-use agreement** — the only thing that converts any of this into evidence about actual exchange.
