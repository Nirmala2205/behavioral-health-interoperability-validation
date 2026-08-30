# Results and Discussion

## Results


### Micro-prototype performance

The micro-prototype was evaluated with 10 synthetic patients in each of two
exchange scenarios. Scenario A modeled a behavioral-health EHR transmitting to
a statewide health information exchange and receiving health system. Scenario B
represented the same validation problem through a differently rendered
community-mental-health-to-academic-medical-center exchange path.

Scenario A generated 184 source elements, of which 157 were authorized and
expected to cross the exchange boundary; 27 were excluded by consent. Scenario B
generated 162 source elements, with 154 authorized and eight excluded. After
controlled failure injection, completeness was 96.18% in Scenario A and 96.10%
in Scenario B, while fidelity was 96.69% and 96.62%, respectively.

Each scenario contained 18 injected failures. The framework correctly classified
all 36 failures, with no false negatives, false positives, or incorrectly
flagged consent-exclusion controls. An independent completeness calculation,
implemented separately from the validation engine, reproduced the Scenario A
result exactly (96.18%), supporting the correctness of the denominator logic.

| Measure | Scenario A | Scenario B |
|---|---:|---:|
| Source elements | 184 | 162 |
| Expected elements | 157 | 154 |
| Consent-excluded elements | 27 | 8 |
| Completeness | 96.18% | 96.10% |
| Fidelity | 96.69% | 96.62% |
| Injected failures | 18 | 18 |
| Correctly classified | 18 | 18 |
| False negatives | 0 | 0 |
| False positives | 0 | 0 |

### Scaled primary benchmark

The scaled probabilistic benchmark evaluated 500 synthetic patients per
scenario, representing 1,000 patient-scenario runs. Scenario A contained 8,421
evaluated elements and 1,557 injected failures. Scenario B contained 8,347
evaluated elements and 1,543 injected failures.

All 3,100 injected failures were detected and assigned to the expected
classification. The combined classification-sensitivity estimate was therefore
3,100/3,100, or 100% (95% Wilson CI 99.88%–100%). The framework also correctly
left all 13,668 true-negative elements unflagged, producing specificity of
13,668/13,668, or 100% (95% Wilson CI 99.97%–100%). Precision and detection
sensitivity were also 100%, with no observed false positives, false negatives,
or wrong-class detections.

| Measure | Scenario A | Scenario B | Combined |
|---|---:|---:|---:|
| Evaluated elements | 8,421 | 8,347 | 16,768 |
| Injected failures | 1,557 | 1,543 | 3,100 |
| Correctly classified | 1,557 | 1,543 | 3,100 |
| True negatives | 6,864 | 6,804 | 13,668 |
| False negatives | 0 | 0 | 0 |
| False positives | 0 | 0 | 0 |
| Classification sensitivity | 100% | 100% | 100% |
| Precision | 100% | 100% | 100% |
| Specificity | 100% | 100% | 100% |

The scenario-specific classification-sensitivity intervals were
99.75%–100% for both exchange paths. Scenario-specific specificity intervals
were 99.94%–100%. These results show that the configured normalization rules
absorbed expected representational differences—such as dose-unit conversion,
case variation, and alternate frequency notation—without generating false
findings.

### Held-out terminology evaluation

A separate adversarial profile evaluated a known limitation of the curated
terminology-equivalence map. It included documented degradations represented in
the map and uncurated ICD-10-CM category-ancestor degradations that were withheld
from the map.

All 20 held-out degradations were detected, yielding detection sensitivity of
20/20, or 100% (95% Wilson CI 83.89%–100%). Only 10 were assigned the intended
`semantic_degraded` classification. Combined classification sensitivity was
therefore 10/20, or 50% (95% Wilson CI 29.93%–70.07%). All 10 curated
degradations were classified correctly, whereas all 10 uncurated degradations
were reported as `value_mismatch`.

| Held-out class | Detected | Correctly classified |
|---|---:|---:|
| Curated degradation | 10/10 | 10/10 |
| Uncurated category ancestor | 10/10 | 0/10 |
| Combined | 20/20 | 10/20 |

The held-out result distinguishes failure detection from failure
classification. The framework recognized that every received value differed
from its expected value, but it could not infer an undocumented hierarchical
relationship. Thus, the limitation did not produce silent false negatives; it
produced clinically less informative labels.

### Reproducibility and measurement-integrity checks

A complete reproducibility run executed both scenarios twice and compared
SHA-256 hashes across generated outputs. All hashes were identical. Clean runs
with zero configured injections produced zero findings in both scenarios.

Four defects were identified during evaluation and final review. First,
baseline latency in Scenario B could independently exceed the crisis timeliness
threshold, producing genuine late arrivals absent from the injection ledger.
Second, a fixed 240-minute timeliness perturbation did not breach the 24-hour
ambulatory threshold, causing the ledger to claim failures that had not
occurred. Third, generated FHIR bundles from a prior scaled run could remain in
the exchange directory during a smaller subsequent run. Fourth, the CLI
accepted a patient-linkage FHIR failure option, but a duplicated dispatch branch
prevented that injector from executing.

The defects were corrected through bounded baseline latency, threshold-aware
delay calculation, pre-run removal of generated FHIR bundles, and explicit
patient-linkage dispatch. Regression tests were added for the stale-bundle and
dispatch failures. The final suite contained 116 passing tests.

## Discussion

### Principal findings

This proof-of-concept demonstrates a reproducible method for measuring whether
behavioral-health information survives an exchange process completely,
faithfully, semantically, in the correct clinical context, within a useful time
window, and in accordance with consent. Its central methodological choice is to
compare received data with the expected authorized exchange set rather than
directly with the source record.

That distinction is consequential in behavioral health. An element withheld
because of a valid consent restriction and an element lost because of a mapping
failure may both be absent at the destination. A direct source-to-destination
comparison treats both as missing. By establishing the authorized exchange set
before validation, the framework removes correctly withheld elements from the
completeness denominator while retaining unauthorized disclosure and
over-restriction as separately measurable outcomes.

### Interpretation of the primary benchmark

The primary benchmark’s perfect observed scores establish internal consistency,
not external validity. The framework correctly detected and classified the
failure modes defined by its experimental contract, maintained zero findings in
clean runs, and generalized across two configured rendering scenarios. The
Wilson intervals provide sample-size-aware bounds for these synthetic
experiments, but they do not convert synthetic observations into estimates of
real-world performance.

High performance is expected when an injector and validator are designed from
the same failure taxonomy. The primary benchmark therefore answers a bounded
question: whether the implemented rules behave as specified when known
conditions are introduced. It does not establish how often such conditions
occur in operational exchange or whether the taxonomy includes the most
important unanticipated failures.

### Terminology classification as the principal measured limitation

The held-out evaluation exposes the most important measured limitation. A
curated equivalence map can identify a semantic degradation only when the
relevant relationship has been documented in advance. When an ICD-10-CM code
was replaced with an uncurated category ancestor, the framework detected the
difference but labeled it as a generic value mismatch.

This behavior is safer than a false negative because the alteration remains
visible. However, it reduces the explanatory value of the result and may send
an investigation toward the wrong remediation path. A semantic degradation may
indicate excessive mapping generalization, whereas an unrelated value mismatch
may suggest corruption, incorrect selection, or record association error.
Future versions should derive relationships from authoritative terminology
structures, including ICD-10-CM hierarchy and RxNorm concept relationships,
rather than relying primarily on a hand-maintained YAML map.

### Importance of validating the evaluation machinery

The four defects found during development illustrate that detector evaluation
is itself a data-quality problem. Two defects corrupted the reference standard:
one omitted genuine baseline failures, and another recorded a perturbation that
did not satisfy its claimed post-condition. A third violated run isolation by
allowing stale generated artifacts to survive. A fourth disconnected an
advertised CLI option from the injector it was intended to invoke.

In each case, an apparently poor or successful metric could have been
misinterpreted without independent checks. Injection-based evaluation therefore
requires at least three safeguards: every injected failure must satisfy an
explicit post-condition, every requested injection must enter the evaluated
execution path, and every run must begin from a controlled state. Clean-run
controls, independent denominator calculations, reproducible hashes, and
dispatch-level regression tests are not auxiliary engineering conveniences;
they are part of the validity argument.

### Threats to validity

The study uses deterministic synthetic data and does not include production EHR
or HIE records. Synthetic prevalence, injection rates, and benchmark metrics
must not be interpreted as estimates of national or organizational exchange
quality. The two scenarios model representational variation but do not capture
the full range of vendor-specific schemas, implementation-guide deviations,
workflow behavior, or operational latency.

Consent is modeled as an element-level authorization decision. Real 42 CFR Part
2 and organizational consent workflows may operate at document, episode,
purpose-of-use, recipient, or redisclosure levels and may vary by jurisdiction.
The prototype also assumes persistent correlation identifiers, including FHIR
resource identifiers, survive exchange. Systems that regenerate identifiers or
lack stable cross-system linkage require probabilistic or rules-based matching
before element-level validation can occur.

Although the bundles use FHIR R4 resources and behavioral-health-relevant
elements, the study does not claim formal conformance with a complete
implementation guide. Structural conformance testing with published
StructureDefinitions should remain a separate pipeline stage. Conformance and
content fidelity answer complementary questions: a resource may be structurally
valid while carrying incomplete, incorrect, delayed, or unauthorized clinical
content.

Finally, the framework detects and classifies discrepancies but does not repair
them. Operational adoption would require investigation workflows, provenance,
issue prioritization, and governance processes beyond the scope of this
prototype.

### Future work

The next research stages should:

1. add official FHIR profile validation as a separately reported pipeline stage;
2. replace curated terminology equivalence with hierarchy- and graph-derived relationships;
3. evaluate multiple simultaneous failures affecting the same clinical element;
4. test identifier loss and probabilistic record linkage;
5. expand consent modeling to document-, recipient-, and purpose-specific rules;
6. introduce additional independently designed exchange scenarios and failure profiles;
7. evaluate de-identified or appropriately governed real exchange data under a data-use agreement; and
8. assess whether validation findings support efficient human investigation and remediation.

### Conclusion

The framework provides a bounded, testable approach to behavioral-health
interoperability validation. It separates lawful withholding from data loss,
measures multiple dimensions of exchange quality, preserves a ground-truth
failure ledger, and reports detection and classification performance
separately. Across the primary synthetic benchmark, all 3,100 configured
failures were correctly classified with no observed false positives. The
held-out evaluation reduced classification sensitivity to 50%, demonstrating
that the strongest result is not the perfect primary score but the framework’s
ability to reveal and quantify its own limitation.

The appropriate conclusion is therefore not that the method has been validated
for operational exchange. Rather, the prototype has reached the point where its
assumptions, failure taxonomy, measurement process, and known limitations are
explicit enough to support evaluation with independently designed and
eventually real-world data.
