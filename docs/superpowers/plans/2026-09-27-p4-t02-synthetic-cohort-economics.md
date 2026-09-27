# P4-T02 Synthetic Observed Cohort Economics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Prove a bounded coin-only observed cohort calculation against generated normalized inputs without enabling real analytics or claiming lifetime economics.

**Architecture:** A checked-in PostgreSQL SELECT consumes one supplied, pre-reconciled aggregate row per complete cohort/window/currency/environment/basis/acquisition grain. It preserves metadata and input values, flags duplicate grains and conflicting declared scope IDs, and exposes only valid completed-window metrics. Unknown input values affect only dependent metrics.

**Tech Stack:** PostgreSQL exact `numeric` arithmetic, pytest-django temporary tables, Python `Decimal` assertions.

---

P4-T02 explicitly permits synthetic model work before live dependencies. Metric
definitions come from `docs/analytics/README.md` and `docs/product/COST_MODEL.md`;
D-037 supersedes their older ad-at-launch assumptions. Ads are outside this slice,
not measured as zero. No app, migration, exporter, provider call, private data,
dependency, scheduler, attribution policy, FX policy or production activation is
added. The parent owns independent review, full gates and Git operations.

### Task 1: Define generated SQL integration cases and observe red

**Files:** Create `backend/tests/analytics/test_observed_cohort_economics.py`.

- [x] Define a transaction-scoped temporary relation named
  `observed_cohort_inputs_v1` containing text scope/basis/classification metadata,
  timezone-aware window/cutoff timestamps, nullable bigint counts and nullable
  exact numeric revenue/cost/spend inputs. All fixture values are generated.
- [x] Read the actual checked-in SQL with `Path.read_text`, execute it using the
  Django PostgreSQL cursor, and map result columns to rows. Do not duplicate the
  SQL calculations in a Python model.
- [x] Assert the generated paid case `users=100`, `payers=20`, `revenue=150`,
  `content=40`, `infra=10`, `spend=60` produces:

  ```python
  assert row["net_coin_revenue_per_user_eur"] == Decimal("1.5")
  assert row["payer_conversion"] == Decimal("0.2")
  assert row["arppu_eur"] == Decimal("7.5")
  assert row["observed_contribution_before_acquisition_eur"] == Decimal("100")
  assert row["observed_contribution_per_user_eur"] == Decimal("1")
  assert row["observed_contribution_after_acquisition_eur"] == Decimal("40")
  assert row["paid_cac_eur"] == Decimal("0.6")
  ```

- [x] Test per-input null propagation, true zeros, no/unknown denominators,
  negative recognized revenue and contribution, refunded original payer counts,
  paid-only CAC, and the exact window-end maturity boundary.
- [x] Test invalid metadata, unsupported currency/environment/classification,
  reversed/missing/infinite timestamps, whitespace-only scope labels,
  negative counts/costs, payers above users,
  and nonfinite numeric values. Invalid rows retain diagnostics but all metrics
  are NULL; unknown inputs alone do not invalidate unrelated metrics.
- [x] Test exact duplicates, incompatible metadata under one declared scope ID,
  input order independence, and isolation across cohort/window/currency/basis.
  Keep every duplicate flagged, never sum or choose a winner.
- [x] Run `uv run pytest backend/tests/analytics/test_observed_cohort_economics.py -q`;
  expected red is missing `observed_cohort_economics_v1.sql` after fixture setup.

### Task 2: Implement the versioned reference query

**Files:** Create `backend/analytics/sql/observed_cohort_economics_v1.sql`.

- [x] Build SQL CTEs to count rows per complete dimensional grain, count distinct
  metadata variants per `cohort_window_id`, and compute boolean validity/maturity
  flags. Include cutoff in the metadata: a report run supplies one as-of snapshot.
- [x] Use `IS TRUE` for nullable validity checks and exact `numeric` arithmetic.
  No row aggregation of financial values and no automatic source normalization.
- [x] Gate every output metric on valid metadata/values, completed window, unique
  grain and consistent scope. Use NULL arithmetic and zero-safe denominators:

  ```sql
  CASE WHEN metrics_eligible
       THEN net_coin_revenue_eur / NULLIF(acquired_users, 0)
  END AS net_coin_revenue_per_user_eur
  ```

- [x] Subtract content and infra once for observed contribution; subtract supplied
  acquisition spend once for after-acquisition contribution. CAC additionally
  requires `acquisition_classification = 'paid'`. Do not invent ad, lifetime,
  retention, series-allocation or business pass/fail outputs.
- [x] Rerun the focused suite to green; inspect exact Decimal outputs and flags.

### Task 3: Document contract and verify

**Files:** Create `docs/analytics/observed-cohort-model.md`; modify
`docs/analytics/README.md` only for the slice link/status.

- [x] Document the full temporary-relation contract, complete grain, scope-ID
  conflict rule, UTC half-open windows, inclusive cutoff maturity, NULL behavior,
  metric formulas and generated example. Label PostgreSQL validation and unverified
  BigQuery execution explicitly.
- [x] State that source normalization/deduplication, currency/FX provenance,
  refund restatement, attribution and lawful denominators, retention/deletion,
  allocation, BigQuery execution/IAM/budgets and real-data approvals remain open
  P4-T02 work. A synthetic paid case does not authorize spending.
- [x] Run `uv run pytest backend/tests/analytics/test_observed_cohort_economics.py -q`.
- [x] Run `uv run ruff check backend/tests/analytics/test_observed_cohort_economics.py`.
- [x] Run `uv run ruff format --check backend/tests/analytics/test_observed_cohort_economics.py`.
- [x] Run `pnpm backend:typecheck` and `git diff --check`.
- [x] Self-review null/zero handling, metadata isolation, duplicate rejection,
  financial precision, no live data access and no policy/activation claims; hand
  exact evidence to the parent for independent review and full gates.

Use ordinary `uv run`, never a provider `--env-file`. Remain in the supplied
branch; do not create worktrees, commit, push or install dependencies.

## Execution evidence

- Red: `uv run pytest backend/tests/analytics/test_observed_cohort_economics.py -q --tb=short`
  — 51 expected failures because the checked-in SQL file did not yet exist.
- Initial green: the same command — 51 passed in 3.11s.
- Initial implementation: `uv run pytest backend/tests/analytics/test_observed_cohort_economics.py -q`
  — 51 passed in 2.89s.
- Independent-review regressions:
  `uv run pytest backend/tests/analytics/test_observed_cohort_economics.py -q -k 'whitespace_only or infinite_temporal' --tb=short`
  — 4 expected whitespace-only label failures and 6 passing infinite-timestamp
  cases before replacing space-only trimming with a POSIX whitespace predicate.
- Final after review: `uv run pytest backend/tests/analytics/test_observed_cohort_economics.py -q`
  — 61 passed in 3.17s. Infinite timestamps are supplied through SQL parameters;
  tests project flags/metrics around the actual checked-in query to avoid Python
  datetime decoding of preserved infinite input values.
- `uv run ruff check backend/tests/analytics/test_observed_cohort_economics.py`
  — pass.
- `uv run ruff format --check backend/tests/analytics/test_observed_cohort_economics.py`
  — pass.
- `pnpm backend:typecheck` — pass, 243 source files.
- `git diff --check` — pass.

Self-review confirmed exact numeric calculations, NULL propagation, no integer
division, zero-safe denominators, negative net revenue/contribution, nonfinite
money rejection, all-row duplicate/conflict suppression, and metadata isolation.
The query is read-only and references only the supplied aggregate relation. No ad,
lifetime, forecast, business-threshold, provider, source-ingestion or activation
behavior was introduced. Documentation links remaining work in #205 and preserves
the explicit PostgreSQL-only evidence boundary. Parent integration verified
`pnpm backend:check` after the review fixes (844 passed; lint, format, types and
migrations clear), `pnpm contract:check`, and
`python scripts/check_repository_foundation.py` (61 repository tests, safety scan
and governance). Independent review closed with no remaining findings. P4-T02
itself remains open under #205.
