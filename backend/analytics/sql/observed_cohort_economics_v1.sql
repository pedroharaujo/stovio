-- P4-T02 synthetic PostgreSQL reference model; BigQuery execution is unverified.
-- Input: one pre-reconciled aggregate per complete cohort/window grain.
-- Contract: docs/analytics/observed-cohort-model.md. This SELECT never reads
-- operational/provider records or changes the supplied financial/allocation basis.
WITH scope_variants AS (
    SELECT cohort_window_id,
        COUNT(DISTINCT (
            cohort_id, window_start_utc, window_end_utc, observation_cutoff_utc,
            reporting_currency, environment, financial_basis, allocation_basis,
            acquisition_classification
        )) > 1 AS scope_conflict
    FROM observed_cohort_inputs_v1
    GROUP BY cohort_window_id
), checked AS (
    SELECT i.*,
        (
            i.cohort_window_id ~ '[^[:space:]]'
            AND i.cohort_id ~ '[^[:space:]]'
            AND i.financial_basis ~ '[^[:space:]]'
            AND i.allocation_basis ~ '[^[:space:]]'
            AND i.reporting_currency = 'EUR'
            AND i.environment = 'synthetic'
            AND i.acquisition_classification IN (
                'paid', 'organic', 'unpaid', 'technical_beta', 'unmatched'
            )
            AND ISFINITE(i.window_start_utc) AND ISFINITE(i.window_end_utc)
            AND ISFINITE(i.observation_cutoff_utc)
            AND i.window_start_utc < i.window_end_utc
        ) IS TRUE AS metadata_valid,
        (
            (i.acquired_users IS NULL OR i.acquired_users >= 0)
            AND (i.original_verified_payers IS NULL OR i.original_verified_payers >= 0)
            AND (i.acquired_users IS NULL OR i.original_verified_payers IS NULL
                 OR i.original_verified_payers <= i.acquired_users)
            AND (i.allocated_content_cost_eur IS NULL OR i.allocated_content_cost_eur >= 0)
            AND (i.variable_infrastructure_cost_eur IS NULL
                 OR i.variable_infrastructure_cost_eur >= 0)
            AND (i.acquisition_spend_eur IS NULL OR i.acquisition_spend_eur >= 0)
            AND NOT EXISTS (
                SELECT 1 FROM (VALUES
                    (i.net_coin_revenue_eur), (i.allocated_content_cost_eur),
                    (i.variable_infrastructure_cost_eur), (i.acquisition_spend_eur)
                ) AS money(amount)
                WHERE amount IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
            )
        ) IS TRUE AS values_valid,
        (i.observation_cutoff_utc >= i.window_end_utc) IS TRUE AS window_complete,
        COUNT(*) OVER (PARTITION BY
            i.cohort_id, i.window_start_utc, i.window_end_utc, i.observation_cutoff_utc,
            i.reporting_currency, i.environment, i.financial_basis, i.allocation_basis,
            i.acquisition_classification
        ) > 1 AS duplicate_grain,
        s.scope_conflict
    FROM observed_cohort_inputs_v1 i
    JOIN scope_variants s ON s.cohort_window_id IS NOT DISTINCT FROM i.cohort_window_id
), eligible AS (
    SELECT checked.*,
        metadata_valid AND values_valid AND window_complete
            AND NOT duplicate_grain AND NOT scope_conflict AS metrics_eligible
    FROM checked
), contribution AS (
    SELECT eligible.*,
        CASE WHEN metrics_eligible THEN
            net_coin_revenue_eur - allocated_content_cost_eur - variable_infrastructure_cost_eur
        END AS observed_contribution_before_acquisition_eur
    FROM eligible
)
SELECT cohort_window_id, cohort_id, window_start_utc, window_end_utc, observation_cutoff_utc,
    reporting_currency, environment, financial_basis, allocation_basis, acquisition_classification,
    acquired_users, original_verified_payers, net_coin_revenue_eur, allocated_content_cost_eur,
    variable_infrastructure_cost_eur, acquisition_spend_eur,
    metadata_valid, values_valid, window_complete, duplicate_grain, scope_conflict, metrics_eligible,
    CASE WHEN metrics_eligible THEN
        net_coin_revenue_eur / NULLIF(acquired_users, 0)
    END AS net_coin_revenue_per_user_eur,
    CASE WHEN metrics_eligible THEN
        original_verified_payers::numeric / NULLIF(acquired_users, 0)
    END AS payer_conversion,
    CASE WHEN metrics_eligible THEN
        net_coin_revenue_eur / NULLIF(original_verified_payers, 0)
    END AS arppu_eur,
    observed_contribution_before_acquisition_eur,
    observed_contribution_before_acquisition_eur / NULLIF(acquired_users, 0)
        AS observed_contribution_per_user_eur,
    observed_contribution_before_acquisition_eur - acquisition_spend_eur
        AS observed_contribution_after_acquisition_eur,
    CASE WHEN metrics_eligible AND acquisition_classification = 'paid' THEN
        acquisition_spend_eur / NULLIF(acquired_users, 0)
    END AS paid_cac_eur
FROM contribution;
