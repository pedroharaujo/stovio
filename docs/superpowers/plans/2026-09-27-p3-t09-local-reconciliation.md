# P3-T09 Local Commerce Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a repeatable, read-only aggregate report of local commerce history consistency, a bounded first slice of P3-T09.

**Architecture:** A Django management command runs one PostgreSQL aggregate statement so all counts share one statement snapshot. Immutable historical decisions, ledger entries and unlock receipts are compared with each other; current pack configuration and provider services are never consulted. Quarantines and historical credits without purchase decisions remain separate review/coverage counts.

**Tech Stack:** Django management commands, PostgreSQL, Python, pytest-django.

---

Scope follows accepted ADR 0006 and P3-T09. This slice adds no schema, API,
mobile, repair, provider request, scheduler, production activation, or financial
policy. Account/catalog deletion is expected history retention. This report is
neither provider reconciliation nor release clearance. The parent agent owns
independent review, full gates and the final commit; this implementation worker
stays in the existing isolated branch and does not commit or create worktrees.

### Task 1: Specify the command's observable contract

**Files:**
- Create: `backend/tests/commerce/test_accounting_report.py`

- [x] Write command integration tests using the existing generated purchase and
  catalog builders, real fulfillment and real coin unlock services. Invoke with:

  ```python
  output = StringIO()
  call_command("reconcile_commerce", stdout=output)
  report = json.loads(output.getvalue())
  assert report["schema_version"] == 1
  assert report["provider_checked"] is False
  assert report["local_integrity"] == "consistent"
  assert not any(report["discrepancies"].values())
  ```

- [x] Assert the exact fixed-key aggregate output for empty and healthy history,
  including corrections, charged/zero-charge receipts, and cancellation.
- [x] Cover refund-before-credit, refund-after-credit and subsequent successful
  events without treating quarantine as corruption or clearing historical review.
- [x] Cover retained history after account/catalog deletion and changed packs.
- [x] Insert only states permitted by existing guards: unattributed historical
  purchase credits, orphan unlock debits, decisions without events, orphan events,
  credited events linked to quarantine, missing/reversed coin entitlement proof.
  Assert discrepancy exit status separately from review-only success. Existing
  guard tests remain responsible for mutations the database rejects.
- [x] Capture command SQL and reject writes, row locks and provider calls. Assert
  one report statement, fixed output keys and no identifiers or record strings.
- [x] Raise a generated `DatabaseError` from the query boundary; assert a fixed
  redacted `CommandError`, nonzero exit and no stdout success payload.
- [x] Run `uv run pytest backend/tests/commerce/test_accounting_report.py -q`.
  Expected red: `CommandError: Unknown command: 'reconcile_commerce'`.

### Task 2: Implement one aggregate snapshot and safe command

**Files:**
- Create: `backend/apps/commerce/accounting_report.py`
- Create: `backend/apps/commerce/management/commands/reconcile_commerce.py`

- [x] Build a PostgreSQL `WITH ... SELECT` statement whose single result is
  fixed-key JSON. Aggregate wallet balances with `COALESCE(SUM(amount), 0)` over
  every ledger kind and check `0 <= balance <= MAX_BALANCE_COINS`.
- [x] Check credited purchase decisions against ledger kind, amount, wallet and
  decision-ID reference. Check quarantine's zero coins/no entry shape, missing
  event links and credited-event status compatibility.
- [x] Check charged receipts against wallet/debit/price snapshots; zero charge
  requires no entry. Detect orphan unlock debits and completed/cancelled request
  overlap. Never compare debit reference to receipt ID.
- [x] Check coin entitlements in both directions while requiring current account
  and episode for the forward check. Count detached wallets and deleted episodes
  only as coverage context. Never restore entitlements.
- [x] Count quarantined decisions/events, credited decisions with any quarantine,
  and purchase credits without decisions separately from structural discrepancies.
- [x] Expose `build_accounting_report() -> dict[str, Any]`; the command uses:

  ```python
  try:
      report = build_accounting_report()
  except DatabaseError:
      raise CommandError("Local commerce report query failed.") from None
  self.stdout.write(json.dumps(report, sort_keys=True))
  if report["local_integrity"] == "inconsistent":
      raise CommandError("Local commerce integrity discrepancies detected.")
  ```

- [x] Run the focused command tests until green without disabling database guards.

### Task 3: Document boundaries and verify the slice

**Files:**
- Create: `docs/runbooks/commerce-reconciliation.md`
- Modify: `docs/README.md`

- [x] Document `uv run python backend/manage.py reconcile_commerce`, each count
  group, expected deletion/refund behavior, nonzero exit semantics and private
  operational handling. State that corrections, provider reconciliation, reward
  reconciliation, support roles and genuine purchase/refund evidence remain open
  P3-T09 work; output does not approve activation or retention policy.
- [x] Add the runbook to the existing commerce runbook links.
- [x] Run `uv run pytest backend/tests/commerce/test_accounting_report.py -q`.
- [x] Run `uv run ruff check backend/apps/commerce/accounting_report.py backend/apps/commerce/management/commands/reconcile_commerce.py backend/tests/commerce/test_accounting_report.py`.
- [x] Run `uv run ruff format --check backend/apps/commerce/accounting_report.py backend/apps/commerce/management/commands/reconcile_commerce.py backend/tests/commerce/test_accounting_report.py`.
- [x] Run `pnpm backend:typecheck`.
- [x] Self-review joins, statement snapshot, output allowlist, error redaction and
  read-only scope; return exact evidence and limitations to the parent reviewer.

Do not use `--env-file` for generated tests. Full backend, contract and repository
checks are reserved for the parent after independent review.

## Execution evidence

- Red: `uv run pytest backend/tests/commerce/test_accounting_report.py -q` —
  16 failures, all reaching the missing `reconcile_commerce` command.
- Initial green: the same command with `--tb=short` — 16 passed in 5.31s.
- Final focused tests, extended to include refund after spending:
  `uv run pytest backend/tests/commerce/test_accounting_report.py -q` —
  17 passed in 4.83s.
- Focused `uv run ruff check` and `uv run ruff format --check` commands from
  Task 3 — pass; three files formatted.
- `pnpm backend:typecheck` — pass, 245 source files.
- `git diff --check` — pass.

Self-review confirmed: the single statement emits aggregate fields only; nullable
compound validity uses `IS TRUE`; any quarantined event preserves review; account
and catalog deletion skip the applicable forward entitlement check; purchase
amounts come from immutable decisions; no debit-reference/receipt-ID comparison,
provider/configuration lookup, writes or repair exists. Existing database guards
were never disabled for tests.

Parent integration: independent specification and correctness reviews found no
actionable gaps. `pnpm backend:check` passed (800 tests; lint, format, types and
migration checks clear), `pnpm contract:check` passed, and
`python scripts/check_repository_foundation.py` passed (61 repository tests,
safety scan and governance). Remaining full P3-T09 work is tracked in issue #203.
