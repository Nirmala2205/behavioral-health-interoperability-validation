-- ============================================================================
-- COMPLETENESS BY ELEMENT
-- ============================================================================
-- Runs against the validation_results table in DuckDB.
--
-- The SQL layer is not a second implementation of the validation logic -- that
-- would create two sources of truth that can silently disagree. It is the
-- aggregation layer: the Python engine decides element-level verdicts, SQL
-- rolls them up, and Power BI displays the rollup without recomputing
-- anything in DAX (a Blueprint Section 19 success condition).
--
-- THE DENOMINATOR IS THE WHOLE POINT
-- The WHERE clause below is the single most important line in this file:
--
--     WHERE exchange_expectation = 'expected'
--
-- Consent-excluded elements are filtered out before any counting happens. An
-- element the patient never authorized to move cannot be "missing" -- counting
-- it would mean an organization's completeness score falls the more carefully
-- it honors 42 CFR Part 2 restrictions.
-- ============================================================================

SELECT
    scenario_id,
    element_group,
    element_name,
    required,

    COUNT(*)                                             AS expected_elements,

    -- "Received" means a delivered record carrying a value. A withholding
    -- notice is not receipt, and neither is an empty delivered record.
    SUM(CASE WHEN delivery_status = 'delivered'
              AND TRIM(CAST(received_value AS VARCHAR)) <> ''
             THEN 1 ELSE 0 END)                          AS elements_received,

    SUM(CASE WHEN verdict = 'missing_element' THEN 1 ELSE 0 END)
                                                         AS missing_elements,
    SUM(CASE WHEN verdict = 'subfield_dropped' THEN 1 ELSE 0 END)
                                                         AS subfields_dropped,
    SUM(CASE WHEN verdict = 'consent_over_restriction' THEN 1 ELSE 0 END)
                                                         AS wrongly_withheld,

    ROUND(
        100.0 * SUM(CASE WHEN delivery_status = 'delivered'
                          AND TRIM(CAST(received_value AS VARCHAR)) <> ''
                         THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        2
    )                                                    AS completeness_pct

FROM validation_results
WHERE exchange_expectation = 'expected'
GROUP BY scenario_id, element_group, element_name, required
ORDER BY scenario_id, completeness_pct ASC, element_name;
