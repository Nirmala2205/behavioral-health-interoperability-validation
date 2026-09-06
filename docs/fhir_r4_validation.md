# FHIR R4 Validation Record

## Scope

The tracked synthetic FHIR exchange corpus was validated against the HL7 FHIR R4 base specification.

- Validation date: 2026-09-06
- HL7 FHIR Validator: 6.10.2
- Validator build commit: d06577dbc5c6
- FHIR version: 4.0.1 (R4)
- Tracked bundles validated: 18
- Scenario A bundles: 9
- Scenario B bundles: 9

## Result

Across all 18 tracked bundles:

- Errors: 0
- Warnings: 286
- Informational notes: 65

Each bundle completed with zero validation errors.

Representative warnings included:

- missing narrative text (`dom-6`) best-practice recommendations;
- missing `Observation.performer` best-practice recommendations;
- UCUM `{score}` annotation recommendations;
- synthetic/local code systems such as `urn:bhiv:sensitivity` that are not defined in the base terminology packages;
- Consent terminology and value-set recommendations.

## Reproduction

The validated files were the JSON bundles tracked by Git under:

- `fhir/exchange/scenario_A/`
- `fhir/exchange/scenario_B/`

The file list can be reproduced with:

```powershell
$files = git ls-files "fhir/exchange/scenario_A/*.json" "fhir/exchange/scenario_B/*.json"
```

Validation was run with:

```powershell
java -jar tools\validator_cli.jar $files -version 4.0.1
```

The validator binary is intentionally not stored in the repository.

## Interpretation

This result demonstrates that the tested synthetic corpus produced no errors under validation against the HL7 FHIR R4 4.0.1 base specification.

It does not establish:

- conformance to a behavioral-health implementation guide;
- conformance to any jurisdiction-specific implementation guide;
- absence of warnings or terminology issues;
- production readiness;
- interoperability certification.

The remaining warnings and informational messages are retained as known limitations of the synthetic proof-of-concept corpus.
