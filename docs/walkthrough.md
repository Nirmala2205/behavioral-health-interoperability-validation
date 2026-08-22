# Walkthrough: One Element, End to End

Read this before an interview. It follows a single data element through every
stage of the pipeline and explains what each stage decides and why. Once you can
narrate this one element, you can answer almost any question about the project —
every other element takes the same path.

At the end there is a set of questions an admissions committee or faculty member
is likely to ask, with the reasoning you would need. **Do not memorize answers.**
Understand the decision behind each one; a follow-up question will find the
difference immediately.

---

## The element

Patient `A-P0003`, encounter `A-P0003-E01`, a PHQ-9 total score of **18**.

Its identifier throughout the pipeline:

```
A:A-P0003:A-P0003-E01:OBS1:assessment_score
│ │        │            │    └─ which field
│ │        │            └─ which clinical group in the encounter
│ │        └─ which encounter
│ └─ which patient
└─ which scenario
```

The identifier is human-readable on purpose. When a result says something
failed, you should be able to tell what and where without a lookup.

---

## Stage 1 — SOURCE_TRUTH

`src/generate/synthetic_source.py`

The simulated sending EHR holds this row:

| field | value |
|---|---|
| `element_value` | `18` |
| `sensitivity_class` | `routine` |
| `encounter_class` | `AMB` |

**What's decided here:** the sensitivity class. This element sits under a
depression diagnosis (`F32.1`), which is not in the Part 2 prefix list, so it is
`routine`. Had the encounter's diagnosis been `F10.20` (alcohol dependence), the
whole clinical group — code, display, onset, and any assessment or medication
under it — would be `sud_part2`.

**Why the group, not the field:** withholding an SUD diagnosis code while
exchanging the display text "Alcohol dependence, uncomplicated" would disclose
exactly what the restriction exists to protect.

---

## Stage 2 — EXPECTED_EXCHANGE

`src/transform/expected_exchange.py`

Patient `A-P0003`'s consent state is `authorized_all`, which authorizes both
`routine` and `sud_part2`. So:

| field | value |
|---|---|
| `authorized` | `True` |
| `exchange_expectation` | `expected` |

**This is the most important stage in the project.** It sets the denominator.

If this patient were `part2_restricted` and the element were `sud_part2`, it
would be marked `excluded_by_consent` — and then its *absence* at the
destination would be a **PASS**, not a gap. Note that the element is still
carried forward rather than filtered away, because the framework must also check
that a restricted element did *not* arrive. A validator that iterates only the
expected set cannot detect an unauthorized disclosure at all.

> **If you remember one thing:** the comparison is not source vs. destination.
> It is source → *expected/authorized* → received. In behavioral health,
> lawfully withheld data and lost data look identical downstream, and only the
> consent layer separates them.

---

## Stage 3 — FHIR R4

`src/transform/fhir_builder.py`

```json
{
  "resourceType": "Observation",
  "code": { "coding": [{ "system": "http://loinc.org", "code": "44249-1" }] },
  "subject": { "reference": "Patient/A-P0003" },
  "encounter": { "reference": "Encounter/A-P0003-E01" },
  "valueQuantity": { "value": 18.0, "code": "{score}" }
}
```

**Why this is not the validation:** if `18.0` became `8.0` here, this resource
would still be perfectly conformant FHIR. Structural validation passes it. That
gap — between *well-formed* and *faithful* — is the project's whole subject.

---

## Stage 4 — Wire rendering

`src/transform/destination.py`

Scenario A emits `18`. Scenario B, modeling a different sending system, would
emit medication doses in grams and frequencies as `QD` instead of `daily`.

**Why this matters:** none of that is a data-quality failure. It is rendering. A
framework that reports it is producing false positives — and would be useless
across the heterogeneous senders the research question is actually about. This
is exactly what Scenario B is for.

---

## Stage 5 — Failure injection

`src/inject_failures/injector.py`

Suppose the injector selects this element for `alter_numeric_value`:

- **18 → 8** (band-crossing: moderately severe → mild)
- Ledger entry: `expected_detection: value_mismatch`, original `18`, injected `8`

**Why band-crossing rather than ±1:** PHQ-9 severity bands are five points wide.
An injected error should be one that would change a clinical interpretation, not
a cosmetic perturbation a detector could be excused for missing.

**Why a ledger at all:** without it, "the dashboard shows 500 errors" is
unfalsifiable. The ledger is the reference standard the detector is scored
against.

---

## Stage 6 — Validation

`src/validate/engine.py`

1. **Expectation** → `expected`. Not the consent branch.
2. **Present?** Yes, `delivery_status = delivered`. Not missing.
3. **Linkage?** Patient and encounter match. Pass.
4. **Value:** normalize both sides with `numeric` → `18.0` vs `8.0`. Compare with
   `numeric_exact`, tolerance `0` → **MISMATCH**.
5. **Timeliness:** latency 12 min, AMB threshold 1440 min. Pass.

One finding, so the primary verdict is `value_mismatch`, dimension `fidelity`.
Had there been two findings, precedence
(consent > completeness > linkage > value/semantic > timeliness) picks the
primary and the rest go to `secondary_findings`.

**The counterfactual worth knowing:** if the injected value had been the *code*
`F32.9` instead of the score `8`, the comparator would have consulted the
equivalence map, found `F32.9` listed as a documented broader ancestor of
`F32.1`, and returned **DEGRADED** → `semantic_degraded`. Same "not equal", very
different finding.

---

## Stage 7 — Aggregation and evaluation

`sql/*.sql`, `src/metrics/evaluate.py`

SQL rolls element-level verdicts into completeness and fidelity. **Power BI does
no logic** — it displays these tables. Recomputing rules in DAX would create a
second source of truth that can silently disagree with the first.

Evaluation then compares verdicts against the ledger:

- ledger says `value_mismatch`, engine says `value_mismatch` → **classification TP**
- detected but named wrong → **detection TP, classification FN** (counted separately)
- not flagged → **FN**
- flagged with no ledger entry → **FP**

**Why detection and classification are scored separately:** a framework that
catches everything but names half of it wrongly has perfect detection
sensitivity and mediocre classification accuracy. Reporting only the first
number overstates what the tool can tell a user.

---

## Likely interview questions

**"How would you measure completeness?"**
Expected elements received over total expected. The interesting part is the
denominator: consent-excluded elements are removed before counting. In
behavioral health, withheld and lost data look identical downstream, so a
framework comparing source to destination directly reports lawful Part 2
restrictions as data loss — and the more carefully an organization protects
patients, the worse its score looks. A patient who authorized nothing has a
denominator of zero, which I report as undefined rather than 0%.

**"How do you know your framework works?"**
I inject known failures and keep a ledger of exactly what was broken, then score
the detector against it: TP, FP, FN, TN, sensitivity, precision, specificity.
100% classification sensitivity with 0 false positives at 500-patient scale. But
I'd add that this is a necessary condition, not an achievement — a detector
evaluated only against failures I imagined will score well by construction. So I
also built an adversarial profile that injects a degradation my equivalence map
deliberately doesn't cover. It catches all of them and misclassifies all of
them: 100% detection, 0% classification. That's the honest characterization of a
curated-terminology approach.

**"Isn't this just FHIR validation?"**
No, and the difference is the point. Conformance validation asks whether a
resource is well-formed. An Observation with `valueQuantity: 8` where the
patient scored 18 is perfectly conformant. A Condition coded F32.9 where the
source said F32.1 is perfectly conformant. Both pass structural validation. I'm
asking whether the expected clinical content actually survived — a complementary
question, not a competing one.

**"How do you separate a semantic degradation from a wrong value?"**
A documented equivalence map. If the received code is a recorded broader
ancestor of the expected one, meaning partially survived and I call it
`semantic_degraded`. If there's no documented relationship, it's
`value_mismatch`. To a binary comparator both are just "not equal", and a
receiving organization would respond to them very differently — one is a
mapping-depth problem, the other is a wrong-record problem.

**"What's the biggest weakness?"**
That the failures are ones I designed the detector to find. The synthetic
environment makes the injector and validator complementary by construction. The
adversarial profile pushes against that, and the two measurement bugs I found —
one where the ledger was incomplete, one where it was incorrect — are documented
in the repo because both times the *detector* was right and the *measurement*
was wrong. What would actually validate the method is real data under a
data-use agreement.

**"How does this connect to your job?"**
It started from a reporting problem I traced at work: a query returning fewer
records than it should because of what it was reading from, which only became
visible when I reconciled against source tables. The lesson wasn't about that
specific system — it was that silent downstream incompleteness stays invisible
unless you deliberately reconcile against a trusted source. This project turns
that instinct into a method: define source truth, define what's authorized to
move, simulate the exchange, break things in known ways, and measure whether a
validator catches them.

**"Why behavioral health specifically?"**
It's where the problem is worst and studied least. 68% of behavioral health
facilities have an EHR but only 19% participate in an HIE, and 67% don't know
whether one is available to them. HITECH's $25B in adoption incentives excluded
these facilities, so the sector never built the exchange infrastructure physical
health spent fifteen years accumulating. And 42 CFR Part 2 adds a consent layer
that makes correct behavior and failure look the same — which is a genuinely
interesting measurement problem, not just a harder version of the general one.

**"What would your dissertation actually be?"**
Roughly three studies. Characterize what completeness and fidelity failures
actually occur across real behavioral-health organizations, systematically
rather than anecdotally. Build a focused detection method targeting whichever
failure types turn out to matter most. Evaluate it against data from
organizations that had no part in building it. This prototype is a small,
honest version of the middle study — enough to show I understand the shape of
the problem, not a claim that I've done it.

---

## Things to be careful about

- **Never call the numbers real-world failure rates.** Injection rates are experimental parameters chosen to exercise the detector. Synthetic prevalence means nothing.
- **Never claim conformance you haven't run.** The bundles are *aligned to* USCDI+ BH and the US BH Profiles IG; the HL7 validator has not been run against them. That's stated in the methodology note and it's on the future-work list.
- **Never claim novelty you haven't checked.** FHIR validation and data-quality frameworks exist. The contribution is the integration — end-to-end, consent-aware, behavioral-health-specific — and that framing is "subject to formal literature review," which you have not yet done.
- **Lead with the limitations.** They're the strongest part of the project. Anyone can produce a dashboard; being able to say precisely where your own method breaks, with a number attached, is the thing that reads as research maturity.
