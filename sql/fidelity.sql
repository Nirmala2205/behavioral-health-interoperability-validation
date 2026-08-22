-- ============================================================================
-- FIDELITY BY ELEMENT
-- ============================================================================
-- Fidelity is scored only over elements that actually arrived with a value --
-- the "comparable" population. An element that never arrived cannot be
-- unfaithful; it is incomplete. Counting it in both places would report one
-- defect twice and make the two dimensions non-independent, so a reader could
-- not tell whether a low fidelity score meant corrupted values or simply a lot
-- of missing data.
--
-- Semantic degradation is broken out rather than folded into mismatches. A
-- code that arrived as a documented broader ancestor lost specificity but
-- retained meaning; a code that arrived as an unrelated concept did not. Those
-- warrant different responses from a receiving organization, so the rollup
-- keeps them separate.
-- ============================================================================

WITH comparable AS (
    SELECT *
    FROM validation_results
    WHERE exchange_expectation = 'expected'
      AND delivery_status = 'delivered'
      AND TRIM(CAST(received_value AS VARCHAR)) <> ''
)

SELECT
    scenario_id,
    element_group,
    element_name,

    COUNT(*)                                              AS comparable_elements,

    SUM(CASE WHEN verdict NOT IN ('value_mismatch', 'semantic_degraded')
             THEN 1 ELSE 0 END)                           AS values_preserved,
    SUM(CASE WHEN verdict = 'value_mismatch'   THEN 1 ELSE 0 END)
                                                          AS value_mismatches,
    SUM(CASE WHEN verdict = 'semantic_degraded' THEN 1 ELSE 0 END)
                                                          AS semantic_degradations,

    ROUND(
        100.0 * SUM(CASE WHEN verdict NOT IN ('value_mismatch', 'semantic_degraded')
                         THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        2
    )                                                     AS fidelity_pct

FROM comparable
GROUP BY scenario_id, element_group, element_name
ORDER BY scenario_id, fidelity_pct ASC, element_name;
