-- ============================================================================
-- RUN-LEVEL VALIDATION SUMMARY
-- ============================================================================
-- One row per validation run per scenario. This is the table Power BI Page 1
-- reads directly.
--
-- Every rate below has an explicitly stated denominator, and NULLIF guards
-- every division. A zero denominator here is not a hypothetical: a scenario in
-- which every patient is fully restricted has zero expected elements, and its
-- completeness is genuinely undefined. Returning NULL says "not applicable";
-- returning 0 would say "everything was lost," which is the opposite of what
-- happened.
-- ============================================================================

SELECT
    run_id,
    scenario_id,

    -- Population -----------------------------------------------------------
    COUNT(*)                                                    AS total_source_elements,
    SUM(CASE WHEN exchange_expectation = 'expected' THEN 1 ELSE 0 END)
                                                                AS expected_elements,
    SUM(CASE WHEN exchange_expectation = 'excluded_by_consent' THEN 1 ELSE 0 END)
                                                                AS consent_excluded_elements,

    -- Completeness ---------------------------------------------------------
    SUM(CASE WHEN exchange_expectation = 'expected'
              AND delivery_status = 'delivered'
              AND TRIM(CAST(received_value AS VARCHAR)) <> ''
             THEN 1 ELSE 0 END)                                 AS elements_received,
    ROUND(
        100.0 * SUM(CASE WHEN exchange_expectation = 'expected'
                          AND delivery_status = 'delivered'
                          AND TRIM(CAST(received_value AS VARCHAR)) <> ''
                         THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN exchange_expectation = 'expected' THEN 1 ELSE 0 END), 0),
        2
    )                                                           AS completeness_pct,

    -- Fidelity (denominator = comparable elements only) --------------------
    SUM(CASE WHEN exchange_expectation = 'expected'
              AND delivery_status = 'delivered'
              AND TRIM(CAST(received_value AS VARCHAR)) <> ''
             THEN 1 ELSE 0 END)                                 AS comparable_elements,
    ROUND(
        100.0 * SUM(CASE WHEN exchange_expectation = 'expected'
                          AND delivery_status = 'delivered'
                          AND TRIM(CAST(received_value AS VARCHAR)) <> ''
                          AND verdict NOT IN ('value_mismatch', 'semantic_degraded')
                         THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN exchange_expectation = 'expected'
                           AND delivery_status = 'delivered'
                           AND TRIM(CAST(received_value AS VARCHAR)) <> ''
                          THEN 1 ELSE 0 END), 0),
        2
    )                                                           AS fidelity_pct,

    -- Failures by dimension ------------------------------------------------
    SUM(CASE WHEN verdict = 'missing_element'          THEN 1 ELSE 0 END) AS f_missing,
    SUM(CASE WHEN verdict = 'subfield_dropped'         THEN 1 ELSE 0 END) AS f_subfield_dropped,
    SUM(CASE WHEN verdict = 'value_mismatch'           THEN 1 ELSE 0 END) AS f_value_mismatch,
    SUM(CASE WHEN verdict = 'semantic_degraded'        THEN 1 ELSE 0 END) AS f_semantic_degraded,
    SUM(CASE WHEN verdict = 'patient_linkage'          THEN 1 ELSE 0 END) AS f_patient_linkage,
    SUM(CASE WHEN verdict = 'encounter_linkage'        THEN 1 ELSE 0 END) AS f_encounter_linkage,
    SUM(CASE WHEN verdict = 'timeliness'               THEN 1 ELSE 0 END) AS f_timeliness,
    SUM(CASE WHEN verdict = 'unauthorized_disclosure'  THEN 1 ELSE 0 END) AS f_unauthorized_disclosure,
    SUM(CASE WHEN verdict = 'consent_over_restriction' THEN 1 ELSE 0 END) AS f_consent_over_restriction,

    -- Correct behavior -------------------------------------------------------
    -- Reported alongside the failures on purpose. A run showing 40 authorized
    -- exclusions and 0 unauthorized disclosures is evidence the consent layer
    -- worked, and that is a finding worth surfacing rather than an absence.
    SUM(CASE WHEN verdict = 'authorized_exclusion' THEN 1 ELSE 0 END)
                                                                AS correct_authorized_exclusions,
    SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END)            AS total_pass,
    SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END)            AS total_fail

FROM validation_results
GROUP BY run_id, scenario_id
ORDER BY run_id, scenario_id;
