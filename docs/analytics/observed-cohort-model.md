# Synthetic observed cohort economics — P4-T02 slice

No founder setup is needed to run the generated-data tests. This reference model
proves observed coin-economics arithmetic and input-quality rules in PostgreSQL.
It does **not** establish real cohort economics, approve paid spend, or complete
P4-T02. BigQuery execution is **unverified**.

The versioned query is
[`observed_cohort_economics_v1.sql`](../../backend/analytics/sql/observed_cohort_economics_v1.sql).
It is a read-only `SELECT` over a supplied relation named
`observed_cohort_inputs_v1`. Tests create that relation as a temporary table in the
existing pytest-django PostgreSQL database, populate generated facts and execute
the actual file. No production table, model, migration, export, scheduler or
provider connection is added.

```sh
uv run pytest backend/tests/analytics/test_observed_cohort_economics.py -q
```

Use ordinary `uv run`; the fixtures need no provider environment file or private
data. SQL lives under `backend/` so SQL changes receive the existing Backend CI
gate.

## Input contract

Supply **one already-reconciled normalized aggregate row** per complete grain,
for one report snapshot. This model does not reconcile or deduplicate individual
purchases, normalize currencies, choose attribution, allocate costs, or define
financial recognition. Those steps belong upstream and remain unimplemented here.
Do not point this synthetic reference model at real-data exports.

| Input column | PostgreSQL type | Meaning |
| --- | --- | --- |
| `cohort_window_id` | `text` | Nonblank declared scope ID that binds exactly one metadata variant in this report snapshot. |
| `cohort_id` | `text` | Nonblank acquired-cohort identity; never a person or transaction identifier. |
| `window_start_utc`, `window_end_utc` | `timestamptz` | Finite start-inclusive/end-exclusive observation window, with start strictly before end. |
| `observation_cutoff_utc` | `timestamptz` | Finite as-of cutoff for the supplied facts. A cutoff at or beyond window end is mature. |
| `reporting_currency` | `text` | Exactly `EUR`; other currencies are flagged, never converted or combined. |
| `environment` | `text` | Exactly `synthetic`; all other environments are flagged. |
| `financial_basis` | `text` | Nonblank supplied basis label for already-net recognized store coin revenue. The label does not prove reconciliation or approve a finance policy. |
| `allocation_basis` | `text` | Nonblank supplied method/version label for cohort cost/revenue allocation; the SQL never chooses an allocation. |
| `acquisition_classification` | `text` | One of `paid`, `organic`, `unpaid`, `technical_beta`, `unmatched`; categories are supplied, never inferred from spend. |
| `acquired_users` | nullable `bigint` | Deduplicated acquired-user denominator for this cohort, not MAU, installs, accounts, or merely the consented subset. |
| `original_verified_payers` | nullable `bigint` | Distinct originally completed verified coin purchasers in the same cohort/window, including those later refunded. Multiple purchases by one payer count once upstream. |
| `net_coin_revenue_eur` | nullable `numeric` | Net recognized store coin revenue already reconciled and allocated to this cohort/window; negative restated revenue is allowed. |
| `allocated_content_cost_eur` | nullable `numeric` | Supplied allocated content cost, including applicable royalty/MG/localization/delivery components exactly once. |
| `variable_infrastructure_cost_eur` | nullable `numeric` | Supplied variable infrastructure/provider cost for the same grain. |
| `acquisition_spend_eur` | nullable `numeric` | Supplied acquired-cohort spend on the same reporting basis. |

Use exact `numeric` monetary values, never binary floats. No scale or rounding
policy is imposed; divisions use PostgreSQL numeric precision. Display rounding
belongs outside the reference query. Counts and costs/spend must be nonnegative;
payers cannot exceed users when both are known. All money must be finite:
`NaN`, positive infinity and negative infinity invalidate the row. Missing numeric
inputs are permitted unknowns; they are never replaced with zero.

Required labels must contain a character outside PostgreSQL's POSIX whitespace
class; tabs, newlines and spaces alone do not make a nonblank label.

Timestamp columns represent instants. Supply timezone-aware UTC timestamps and
format result timestamps in a UTC database session; comparison is independent of
the session display timezone. This model does not infer acquisition days or build
D1/D7/D30 windows. The caller supplies the window boundaries and as-of snapshot.

The **complete grain** is the tuple of cohort ID, window start/end, cutoff,
currency, environment, financial basis, allocation basis and acquisition
classification. `cohort_window_id` is excluded from uniqueness counting so a second
ID cannot disguise duplicate totals for the same dimensions. All rows at a
duplicate grain are retained and flagged; amounts are never summed and no winner
is selected.

One `cohort_window_id` reused with different metadata flags **every** variant as a
scope conflict. Different dimensions with distinct scope IDs remain separate,
including separate financial/allocation bases and windows. A restated cutoff
belongs in a new report run or explicitly distinct scope; this model does not
select the latest version or combine snapshots. Output order is unspecified.

## Outputs and missingness

Every input column is carried through for diagnosis. Six boolean flags accompany
the seven metrics:

- `metadata_valid`: required scope fields, supported currency/environment/category
  and finite ordered window metadata are valid.
- `values_valid`: supplied counts/costs are valid, payers do not exceed known
  users, and monetary values are finite. Unknown numeric inputs remain valid.
- `window_complete`: cutoff is at or after window end.
- `duplicate_grain`: more than one input row has the same complete grain.
- `scope_conflict`: a declared scope ID has incompatible metadata variants.
- `metrics_eligible`: metadata/values/window are valid and no duplicate/conflict
  exists. This is a calculation-quality flag, **not a business pass/fail verdict**
  or a guarantee that every metric has all its inputs.

If `metrics_eligible` is false, **all seven metrics are NULL**. Original inputs
remain visible as supplied diagnostic facts; do not treat those raw fields as
validated results. No apparently usable completed-window metric is emitted for
incomplete, unsupported, duplicated or conflicting input.

For eligible rows let `N` be acquired users, `P` original verified payers, `R` net
coin revenue, `C` content cost, `I` variable infrastructure, and `S` spend:

| Metric column | Formula / qualification |
| --- | --- |
| `net_coin_revenue_per_user_eur` | `R / N` |
| `payer_conversion` | `P / N`, a fraction rather than percentage points |
| `arppu_eur` | `R / P`; refunded original payers remain in `P` |
| `observed_contribution_before_acquisition_eur` | `R - C - I` |
| `observed_contribution_per_user_eur` | `(R - C - I) / N` |
| `observed_contribution_after_acquisition_eur` | `R - C - I - S` |
| `paid_cac_eur` | `S / N`, only when classification is `paid` |

Unknown operands propagate only to dependent metrics. Missing content or infra
cost suppresses contribution but preserves known revenue, conversion, ARPPU and
paid CAC. Missing spend suppresses after-acquisition contribution and CAC only.
Unknown or zero users makes per-user ratios undefined; zero/unknown payers makes
ARPPU undefined. True zero money and zero payer conversion remain zero. Negative
net revenue and contribution are valid. Nonpaid cohorts never receive a paid CAC,
even when a spend amount was supplied.

These are **observed-window** results, not LTV, a lifetime forecast, LTV:CAC,
retention, series-level allocation, or evidence of profitable acquisition. Under
D-037, ad revenue is outside this coin-only slice; the query neither adds an ad
field nor claims a measured zero. Coins credited/spent are not monetary inputs:
there is no coin-to-money conversion or second revenue recognition at unlock.
Fees, taxes and refunds have already been applied upstream and are not subtracted
again.

Generated arithmetic example: `N=100`, `P=20`, `R=150 EUR`, `C=40 EUR`,
`I=10 EUR`, `S=60 EUR` yields revenue/user `1.50 EUR`, conversion `0.20`,
ARPPU `7.50 EUR`, observed contribution before acquisition `100 EUR`,
contribution/user `1 EUR`, after acquisition `40 EUR`, and paid CAC `0.60 EUR`.
These are test constants, not live rates, a forecast, or an approved budget.

## Remaining P4-T02 scope

[Follow-up #205](https://github.com/pedroharaujo/stovio/issues/205) retains the
authoritative inputs and BigQuery validation work. P4-T02 remains open for source
normalization and deduplication, occurrence/ingestion times, original-currency and
FX provenance, late refund restatement and refunded-payer reporting, approved
attribution/lawful denominator coverage, retention, private allocation and residuals,
BigQuery execution/export/IAM/partition filters/query budgets, reconciliation to
restricted source totals, privacy/deletion and real-data approvals. Input basis
labels alone satisfy none of those gates.

D-020/P6 continue to gate real collection/export and activation. D-017 continues
to gate paid spend; a generated `paid` fixture only exercises the CAC formula.
The parent task performs independent review and broader repository checks before
the change is proposed for merge. No unavailable BigQuery/provider check is
reported as passed by these PostgreSQL tests.
