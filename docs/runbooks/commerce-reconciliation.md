# Local commerce consistency report — P3-T09

No founder setup is needed for generated local tests. Engineering can run this
read-only command against an authorized, migrated PostgreSQL database:

```sh
uv run python backend/manage.py reconcile_commerce
```

Use the intended database configuration. The command does not need purchase
activation, a current product registry, or provider credentials. It issues one
aggregate SQL statement: every count uses the same PostgreSQL statement snapshot,
without locking wallet rows or loading individual histories into Python.

This is the **local consistency slice of P3-T09**, not provider reconciliation or
release clearance. It makes no provider requests, repairs, ledger adjustments,
entitlement grants, schema changes, or activation changes. A locally consistent
database can still be missing a provider purchase/refund that never arrived.

## Output and exits

Standard output is one JSON object with fixed keys and aggregate scalar values:

- `schema_version: 1` identifies this output contract.
- `provider_checked: false` always states the coverage boundary.
- `local_integrity` is `consistent` or `inconsistent`, determined only by
  `discrepancies`.
- `counts` includes wallets, ledger entries, total ledger balance in coins,
  purchase decisions/events, unlock receipts/cancellations and coin entitlements.
- `discrepancies` contains the structural checks below.
- `review` contains quarantined decisions, quarantined events, and credited
  decisions with at least one quarantined event.
- `coverage` contains purchase credits without purchase decisions, detached
  wallets, and charged unlocks whose catalog episode no longer exists.

Exit **0** means no structural discrepancies were found, even if review or
coverage counts are nonzero. Exit **1** with a complete JSON report means one or
more structural discrepancies were found. A database/query failure exits **1**,
prints only a fixed failure message to standard error, and emits no report or
partial success payload. Database error details are not included.

No account, wallet, transaction, purchase, request, episode, product, reason,
hash, provider payload or row-level identifier is emitted. Operational aggregates
can still be sensitive; do not put real-data report output in the public repository
or public pull-request evidence. Use generated fixtures for reproducible evidence.

## Structural checks

| Discrepancy key | Meaning |
| --- | --- |
| `wallet_balance_out_of_bounds` | Sum of **all** ledger kinds, including corrections, is outside zero through `MAX_BALANCE_COINS`. There is no cached wallet balance to compare. |
| `invalid_ledger_entries` | An entry violates the allowed kind, sign or per-entry amount bounds. |
| `purchase_decision_ledger_mismatches` | A credit lacks its matching purchase entry, amount, wallet identity or decision-ID reference; or a quarantine violates its zero-coins/no-entry shape. |
| `purchase_decisions_without_events` | A local decision has no local event. |
| `purchase_events_without_decisions` | An event lacks a local decision. |
| `purchase_event_status_mismatches` | An event has an unsupported status or claims credit for a noncredited decision. |
| `unlock_ledger_mismatches` | A charged receipt lacks its matching wallet debit and recorded price, or a zero-charge receipt has an entry. |
| `unlock_debits_without_receipts` | An unlock debit lacks a receipt. |
| `conflicting_unlock_requests` | The same wallet/request has both completed and cancelled terminal records. |
| `charged_unlocks_without_coin_entitlements` | A charged receipt lacks a coin entitlement while both its account and catalog episode still exist. |
| `coin_entitlements_without_charged_unlocks` | A current coin entitlement lacks a matching charged receipt and wallet debit. |

Counts can overlap; their sum is not a count of distinct affected purchases or
accounts. The existing database guards also prevent many of these malformed
states from being inserted. This command checks consistency; it does not replace
those guards or prove every possible form of corruption absent.

## Expected history and review

- A refund before credit leaves a quarantined decision with no coins or entry.
  Missing identity on that quarantine is expected.
- A refund or conflicting event after credit preserves the original credit and
  requires review. **Any** quarantined event keeps that credited decision in the
  review count, even after later successful events. Multiple distinct events for
  one transaction are legitimate.
- Historical bonus credits are compared with the immutable decision amount,
  never today's pack or registry. D-041's bonus offers and registry floor can
  legitimately produce different historical amounts.
- An unlock debit's reference need not equal its receipt ID. Zero-charge receipts
  legitimately have no ledger entry.
- Purchase entries predating commerce decisions can remain unattributed. They
  are a coverage warning, not automatic proof of corruption or a repair request.
- Deleted accounts detach wallets and remove their entitlements; deleted catalog
  episodes also remove their entitlements. Retained history remains valid. These
  checks never recreate accounts, episodes or entitlements.

Structural discrepancies need engineering investigation before applicable release
clearance. Review/coverage counts need their own contextual investigation and do
not authorize confiscation, refunds, compensating credits, or direct history edits.

## Remaining P3-T09 work

Provider transaction/refund comparison, rewarded-ad reconciliation, scheduling,
least-privilege support, approved compensating adjustments and audit, financial
exports, and genuine Google tester purchase/refund/reinstall evidence remain open.
Track the remaining work in [issue #203](https://github.com/pedroharaujo/stovio/issues/203).
Production financial/privacy/retention decisions and release gates remain under
the approved decision register and ADR 0006. This slice does not complete P3-T09.

Focused generated-data validation (no private provider environment file):

```sh
uv run pytest backend/tests/commerce/test_accounting_report.py -q
```
