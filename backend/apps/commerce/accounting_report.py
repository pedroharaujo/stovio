"""Aggregate local accounting checks; no provider lookup or financial mutation."""

from __future__ import annotations

import json
from typing import Any

from django.db import connection

from apps.wallet.models import MAX_BALANCE_COINS, MAX_ENTRY_COINS

# One statement gives every check the same PostgreSQL snapshot without locking
# writers or materializing individual histories in Python. Never consult today's
# product registry/pack amounts: the immutable decision is the credited snapshot.
REPORT_SQL = """
WITH wallet_balances AS (
    SELECT w.id, w.user_profile_id, COALESCE(SUM(l.amount), 0) AS balance
    FROM wallet_wallet w
    LEFT JOIN wallet_coinledgerentry l ON l.wallet_id = w.id
    GROUP BY w.id, w.user_profile_id
), purchase_facts AS (
    SELECT d.id, d.status,
        (
            (d.status = 'credited' AND d.coins BETWEEN 1 AND %(max_entry)s
                AND l.id IS NOT NULL AND i.id IS NOT NULL
                AND l.kind = 'purchase' AND l.amount = d.coins
                AND l.wallet_id = i.wallet_id AND l.reference = d.id)
            OR (d.status = 'quarantined' AND d.coins = 0 AND d.ledger_entry_id IS NULL)
        ) IS TRUE AS valid_ledger,
        EXISTS (SELECT 1 FROM commerce_purchaseevent e WHERE e.decision_id = d.id)
            AS has_event,
        EXISTS (SELECT 1 FROM commerce_purchaseevent e
                WHERE e.decision_id = d.id AND e.status = 'quarantined') AS has_quarantine
    FROM commerce_purchasedecision d
    LEFT JOIN wallet_coinledgerentry l ON l.id = d.ledger_entry_id
    LEFT JOIN commerce_purchaseidentity i ON i.id = d.identity_id
), event_facts AS (
    SELECT e.status, d.id AS decision_id,
        (e.status IN ('credited', 'quarantined') AND
            (e.status <> 'credited' OR d.id IS NULL OR d.status = 'credited'))
            IS TRUE AS valid_status
    FROM commerce_purchaseevent e
    LEFT JOIN commerce_purchasedecision d ON d.id = e.decision_id
), unlock_facts AS (
    SELECT u.id, u.charged_coins, w.user_profile_id, ep.id AS episode_id,
        (
            (u.charged_coins = 0 AND u.ledger_entry_id IS NULL)
            OR (u.charged_coins > 0 AND u.charged_coins = u.expected_coin_price
                AND l.id IS NOT NULL AND l.wallet_id = u.wallet_id
                AND l.kind = 'unlock' AND l.amount = -u.charged_coins::bigint)
        ) IS TRUE AS valid_ledger,
        EXISTS (SELECT 1 FROM wallet_coinunlockcancellation c
                WHERE c.wallet_id = u.wallet_id AND c.request_id = u.request_id)
            AS has_cancellation,
        EXISTS (SELECT 1 FROM entitlements_episodeentitlement ent
                WHERE ent.user_profile_id = w.user_profile_id
                  AND ent.episode_id = ep.id AND ent.source = 'coin') AS has_entitlement
    FROM wallet_coinunlock u
    LEFT JOIN wallet_coinledgerentry l ON l.id = u.ledger_entry_id
    JOIN wallet_wallet w ON w.id = u.wallet_id
    LEFT JOIN catalog_episode ep ON ep.public_id = u.episode_public_id
), entitlement_facts AS (
    SELECT EXISTS (
        SELECT 1 FROM wallet_coinunlock u
        JOIN wallet_wallet w ON w.id = u.wallet_id
        JOIN wallet_coinledgerentry l ON l.id = u.ledger_entry_id
        WHERE w.user_profile_id = ent.user_profile_id AND u.episode_public_id = ep.public_id
          AND u.charged_coins > 0 AND u.charged_coins = u.expected_coin_price
          AND l.wallet_id = u.wallet_id AND l.kind = 'unlock'
          AND l.amount = -u.charged_coins::bigint
    ) AS has_charge
    FROM entitlements_episodeentitlement ent
    JOIN catalog_episode ep ON ep.id = ent.episode_id
    WHERE ent.source = 'coin'
)
SELECT json_build_object(
    'counts', json_build_object(
        'wallets', (SELECT COUNT(*) FROM wallet_balances),
        'ledger_entries', (SELECT COUNT(*) FROM wallet_coinledgerentry),
        'ledger_balance_coins', (SELECT COALESCE(SUM(balance), 0) FROM wallet_balances),
        'purchase_decisions', (SELECT COUNT(*) FROM purchase_facts),
        'purchase_events', (SELECT COUNT(*) FROM event_facts),
        'unlock_receipts', (SELECT COUNT(*) FROM unlock_facts),
        'unlock_cancellations', (SELECT COUNT(*) FROM wallet_coinunlockcancellation),
        'coin_entitlements', (SELECT COUNT(*) FROM entitlement_facts)
    ),
    'discrepancies', json_build_object(
        'wallet_balance_out_of_bounds',
            (SELECT COUNT(*) FROM wallet_balances
             WHERE balance < 0 OR balance > %(max_balance)s),
        'invalid_ledger_entries',
            (SELECT COUNT(*) FROM wallet_coinledgerentry l
             WHERE (l.amount BETWEEN -%(max_entry)s AND %(max_entry)s AND (
                 (l.kind = 'purchase' AND l.amount > 0)
                 OR (l.kind = 'unlock' AND l.amount < 0)
                 OR (l.kind = 'correction' AND l.amount <> 0)
             )) IS NOT TRUE),
        'purchase_decision_ledger_mismatches',
            (SELECT COUNT(*) FROM purchase_facts WHERE NOT valid_ledger),
        'purchase_decisions_without_events',
            (SELECT COUNT(*) FROM purchase_facts WHERE NOT has_event),
        'purchase_events_without_decisions',
            (SELECT COUNT(*) FROM event_facts WHERE decision_id IS NULL),
        'purchase_event_status_mismatches',
            (SELECT COUNT(*) FROM event_facts WHERE NOT valid_status),
        'unlock_ledger_mismatches',
            (SELECT COUNT(*) FROM unlock_facts WHERE NOT valid_ledger),
        'unlock_debits_without_receipts',
            (SELECT COUNT(*) FROM wallet_coinledgerentry l WHERE l.kind = 'unlock'
             AND NOT EXISTS (SELECT 1 FROM wallet_coinunlock u WHERE u.ledger_entry_id = l.id)),
        'conflicting_unlock_requests',
            (SELECT COUNT(*) FROM unlock_facts WHERE has_cancellation),
        'charged_unlocks_without_coin_entitlements',
            (SELECT COUNT(*) FROM unlock_facts
             WHERE charged_coins > 0 AND user_profile_id IS NOT NULL
               AND episode_id IS NOT NULL AND NOT has_entitlement),
        'coin_entitlements_without_charged_unlocks',
            (SELECT COUNT(*) FROM entitlement_facts WHERE NOT has_charge)
    ),
    'review', json_build_object(
        'quarantined_decisions',
            (SELECT COUNT(*) FROM purchase_facts WHERE status = 'quarantined'),
        'quarantined_events',
            (SELECT COUNT(*) FROM event_facts WHERE status = 'quarantined'),
        'credited_decisions_with_quarantined_events',
            (SELECT COUNT(*) FROM purchase_facts WHERE status = 'credited' AND has_quarantine)
    ),
    'coverage', json_build_object(
        'unattributed_purchase_credits',
            (SELECT COUNT(*) FROM wallet_coinledgerentry l WHERE l.kind = 'purchase'
             AND NOT EXISTS (
                 SELECT 1 FROM commerce_purchasedecision d WHERE d.ledger_entry_id = l.id)),
        'detached_wallets',
            (SELECT COUNT(*) FROM wallet_balances WHERE user_profile_id IS NULL),
        'charged_unlocks_without_current_episode',
            (SELECT COUNT(*) FROM unlock_facts WHERE charged_coins > 0 AND episode_id IS NULL)
    )
)
"""


def build_accounting_report() -> dict[str, Any]:
    """Return fixed aggregate fields only; database failures propagate to the command."""
    with connection.cursor() as cursor:
        cursor.execute(
            REPORT_SQL,
            {"max_entry": MAX_ENTRY_COINS, "max_balance": MAX_BALANCE_COINS},
        )
        value = cursor.fetchone()[0]
    report: dict[str, Any] = json.loads(value) if isinstance(value, str) else value
    report.update(
        schema_version=1,
        provider_checked=False,
        local_integrity="inconsistent" if any(report["discrepancies"].values()) else "consistent",
    )
    return report
