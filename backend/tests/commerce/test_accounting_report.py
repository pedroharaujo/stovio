from __future__ import annotations

import json
from io import StringIO
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.profiles import get_or_create_profile
from apps.catalog.models import Episode, EpisodeAccessMode, PublicationStatus
from apps.commerce.models import CoinPack, PurchaseDecision, PurchaseEvent, PurchaseIdentity
from apps.commerce.services import fulfill, purchase_identity
from apps.commerce.verification import normalize
from apps.entitlements.models import EpisodeEntitlement
from apps.entitlements.policy import resolve_episode_policy
from apps.wallet.models import CoinLedgerEntry, CoinUnlock, Wallet
from apps.wallet.services import resolve_unlock, unlock_episode
from tests.catalog.builders import make_episode, make_published_title
from tests.commerce.builders import configure, payload

COUNT_KEYS = {
    "wallets",
    "ledger_entries",
    "ledger_balance_coins",
    "purchase_decisions",
    "purchase_events",
    "unlock_receipts",
    "unlock_cancellations",
    "coin_entitlements",
}
DISCREPANCY_KEYS = {
    "wallet_balance_out_of_bounds",
    "invalid_ledger_entries",
    "purchase_decision_ledger_mismatches",
    "purchase_decisions_without_events",
    "purchase_events_without_decisions",
    "purchase_event_status_mismatches",
    "unlock_ledger_mismatches",
    "unlock_debits_without_receipts",
    "conflicting_unlock_requests",
    "charged_unlocks_without_coin_entitlements",
    "coin_entitlements_without_charged_unlocks",
}
REVIEW_KEYS = {
    "quarantined_decisions",
    "quarantined_events",
    "credited_decisions_with_quarantined_events",
}
COVERAGE_KEYS = {
    "unattributed_purchase_credits",
    "detached_wallets",
    "charged_unlocks_without_current_episode",
}


@pytest.fixture(autouse=True)
def synthetic_mode(settings: Any) -> None:
    configure(settings)
    settings.COIN_SPENDING_MODE = "test"


def report(*, inconsistent: bool = False) -> dict[str, Any]:
    output = StringIO()
    if inconsistent:
        with pytest.raises(
            CommandError, match="Local commerce integrity discrepancies detected"
        ) as error:
            call_command("reconcile_commerce", stdout=output)
        assert error.value.returncode == 1
    else:
        call_command("reconcile_commerce", stdout=output)
    result: dict[str, Any] = json.loads(output.getvalue())
    assert set(result) == {
        "schema_version",
        "provider_checked",
        "local_integrity",
        "counts",
        "discrepancies",
        "review",
        "coverage",
    }
    assert result["schema_version"] == 1
    assert result["provider_checked"] is False
    assert result["local_integrity"] == ("inconsistent" if inconsistent else "consistent")
    for section, keys in (
        ("counts", COUNT_KEYS),
        ("discrepancies", DISCREPANCY_KEYS),
        ("review", REVIEW_KEYS),
        ("coverage", COVERAGE_KEYS),
    ):
        assert set(result[section]) == keys
        assert all(type(value) is int for value in result[section].values())
    assert any(result["discrepancies"].values()) is inconsistent
    return result


def credit(**changes: Any) -> PurchaseIdentity:
    owner = purchase_identity(get_or_create_profile("generated-report-owner"))
    assert fulfill(normalize(payload(str(owner.pk), **changes))).status == "credited"
    return owner


def coin_history(**changes: Any) -> tuple[PurchaseIdentity, Episode, CoinUnlock]:
    owner = credit(**changes)
    series, _ = make_published_title(title="Generated accounting fixture")
    episode = make_episode(series, order=6, publication_status=PublicationStatus.PUBLISHED)
    episode.access_mode, episode.coin_price = EpisodeAccessMode.COIN, 4
    episode.save(update_fields=["access_mode", "coin_price"])
    assert owner.wallet.user_profile is not None
    receipt, _ = unlock_episode(
        owner.wallet.user_profile,
        episode.public_id,
        uuid4(),
        expected_policy_version=resolve_episode_policy(episode).version,
        expected_coin_price=4,
    )
    return owner, episode, receipt


@pytest.mark.django_db
def test_empty_report_has_exact_aggregate_contract_without_creating_state() -> None:
    result = report()
    for section in ("counts", "discrepancies", "review", "coverage"):
        assert not any(result[section].values())


@pytest.mark.django_db
def test_healthy_report_uses_one_read_only_snapshot_and_all_ledger_kinds(settings: Any) -> None:
    owner, episode, receipt = coin_history()
    assert receipt.ledger_entry is not None
    assert receipt.ledger_entry.reference != receipt.pk
    assert owner.wallet.user_profile is not None
    CoinLedgerEntry.objects.create(
        wallet=owner.wallet,
        reference=uuid4(),
        kind="correction",
        amount=-2,
    )
    unlock_episode(
        owner.wallet.user_profile,
        episode.public_id,
        uuid4(),
        expected_policy_version=resolve_episode_policy(episode).version,
        expected_coin_price=4,
    )
    resolve_unlock(
        owner.wallet.user_profile,
        episode.public_id,
        uuid4(),
        expected_policy_version=resolve_episode_policy(episode).version,
        expected_coin_price=4,
    )
    Wallet.objects.create(user_profile=get_or_create_profile("generated-empty-wallet"))
    # Reporting historical records needs neither purchase activation nor a registry.
    settings.COIN_PURCHASE_MODE = "disabled"
    settings.COIN_PURCHASE_PRODUCTS = []
    with (
        CaptureQueriesContext(connection) as queries,
        patch("apps.commerce.revenuecat.lookup_purchase") as provider,
        patch("apps.commerce.reconciliation.lookup_purchase") as reconciliation,
    ):
        result = report()
        provider.assert_not_called()
        reconciliation.assert_not_called()
    assert len(queries) == 1
    sql = queries[0]["sql"].upper()
    assert sql.lstrip().startswith(("WITH", "SELECT"))
    assert not any(word in sql for word in ("INSERT ", "UPDATE ", "DELETE ", "FOR UPDATE"))
    assert result["counts"] == {
        "wallets": 2,
        "ledger_entries": 3,
        "ledger_balance_coins": 7,
        "purchase_decisions": 1,
        "purchase_events": 1,
        "unlock_receipts": 2,
        "unlock_cancellations": 1,
        "coin_entitlements": 1,
    }
    assert not any(result["review"].values())
    assert not any(result["coverage"].values())


@pytest.mark.django_db
@pytest.mark.parametrize("timing", ["before_credit", "after_credit", "after_spend"])
def test_refunds_and_successful_replays_remain_review_without_structural_errors(
    timing: str,
) -> None:
    owner = purchase_identity(get_or_create_profile("generated-report-refund"))
    changes = {"transaction_id": "generated-report-transaction"}
    before_credit = timing == "before_credit"
    if timing == "after_spend":
        owner, _, _ = coin_history(**changes)
    elif not before_credit:
        fulfill(normalize(payload(str(owner.pk), **changes)))
    fulfill(normalize(payload(str(owner.pk), type="REFUND", **changes)))
    fulfill(normalize(payload(str(owner.pk), **changes)))
    result = report()
    assert (
        result["counts"]["ledger_balance_coins"]
        == {
            "before_credit": 0,
            "after_credit": 13,
            "after_spend": 9,
        }[timing]
    )
    assert result["review"] == {
        "quarantined_decisions": int(before_credit),
        "quarantined_events": 2 if before_credit else 1,
        "credited_decisions_with_quarantined_events": int(not before_credit),
    }


@pytest.mark.django_db
@pytest.mark.parametrize("deleted", ["account", "episode", "both"])
def test_deleted_account_or_catalog_retains_consistent_history(deleted: str) -> None:
    owner, episode, _ = coin_history()
    if deleted in {"account", "both"}:
        assert owner.wallet.user_profile is not None
        owner.wallet.user_profile.delete()
    if deleted in {"episode", "both"}:
        episode.delete()
    result = report()
    assert result["counts"]["ledger_balance_coins"] == 9
    assert result["counts"]["coin_entitlements"] == 0
    assert result["coverage"] == {
        "unattributed_purchase_credits": 0,
        "detached_wallets": int(deleted in {"account", "both"}),
        "charged_unlocks_without_current_episode": int(deleted in {"episode", "both"}),
    }


@pytest.mark.django_db
def test_report_preserves_bonus_credit_after_pack_and_registry_change(settings: Any) -> None:
    pack = CoinPack.objects.create(product_id="synthetic_consumable", base_coins=100, bonus="0.20")
    credit(purchased_at_ms=int(timezone.now().timestamp() * 1000))
    pack.is_active = False
    pack.save()
    CoinPack.objects.create(product_id="synthetic_consumable", base_coins=200, bonus="0.50")
    settings.COIN_PURCHASE_PRODUCTS[0]["coins"] = 999
    result = report()
    assert result["counts"]["ledger_balance_coins"] == 120
    assert not any(result["coverage"].values())


@pytest.mark.django_db
def test_unattributed_historical_credit_is_coverage_but_orphan_debit_is_error() -> None:
    wallet = Wallet.objects.create(user_profile=get_or_create_profile("generated-legacy-wallet"))
    CoinLedgerEntry.objects.create(wallet=wallet, reference=uuid4(), kind="purchase", amount=10)
    assert report()["coverage"]["unattributed_purchase_credits"] == 1
    CoinLedgerEntry.objects.create(wallet=wallet, reference=uuid4(), kind="unlock", amount=-2)
    result = report(inconsistent=True)
    assert result["discrepancies"] == {
        **dict.fromkeys(DISCREPANCY_KEYS, 0),
        "unlock_debits_without_receipts": 1,
    }
    assert result["coverage"]["unattributed_purchase_credits"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("problem", ["missing_event", "orphan_event", "credited_quarantine"])
def test_purchase_history_link_discrepancies_exit_nonzero(problem: str) -> None:
    if problem == "orphan_event":
        PurchaseEvent.objects.create(
            event_key="a" * 64,
            fingerprint="b" * 64,
            status="quarantined",
            reason="generated",
        )
        key = "purchase_events_without_decisions"
    else:
        decision = PurchaseDecision.objects.create(
            transaction_key="c" * 64,
            claim_fingerprint="d" * 64,
            status="quarantined",
            reason="generated",
        )
        key = "purchase_decisions_without_events"
        if problem == "credited_quarantine":
            PurchaseEvent.objects.create(
                event_key="e" * 64,
                fingerprint="f" * 64,
                decision=decision,
                status="credited",
                reason="generated",
            )
            key = "purchase_event_status_mismatches"
    assert report(inconsistent=True)["discrepancies"] == {
        **dict.fromkeys(DISCREPANCY_KEYS, 0),
        key: 1,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("missing", ["entitlement", "charged_receipt"])
def test_extant_coin_entitlements_require_matching_charge_in_both_directions(missing: str) -> None:
    owner, episode, _ = coin_history()
    if missing == "entitlement":
        EpisodeEntitlement.objects.filter(episode=episode).delete()
        key = "charged_unlocks_without_coin_entitlements"
    else:
        extra = make_episode(
            episode.series, order=7, publication_status=PublicationStatus.PUBLISHED
        )
        assert owner.wallet.user_profile is not None
        EpisodeEntitlement.objects.create(
            user_profile=owner.wallet.user_profile,
            episode=extra,
            source="coin",
        )
        key = "coin_entitlements_without_charged_unlocks"
    assert report(inconsistent=True)["discrepancies"] == {
        **dict.fromkeys(DISCREPANCY_KEYS, 0),
        key: 1,
    }


@pytest.mark.django_db
def test_report_never_emits_identifiers_or_record_strings() -> None:
    owner, episode, receipt = coin_history()
    decision = PurchaseDecision.objects.get()
    event = PurchaseEvent.objects.get()
    encoded = json.dumps(report())
    for value in (
        str(owner.pk),
        str(owner.wallet_id),
        str(receipt.pk),
        receipt.policy_version,
        episode.public_id,
        decision.transaction_key,
        decision.claim_fingerprint,
        decision.product_id,
        decision.application_id,
        decision.approval_reference,
        decision.reason,
        event.event_key,
        event.fingerprint,
        "generated-report-owner",
    ):
        assert value not in encoded


@pytest.mark.django_db
def test_query_failure_is_redacted_and_emits_no_success_payload() -> None:
    output = StringIO()
    with patch(
        "django.db.backends.utils.CursorWrapper.execute",
        side_effect=DatabaseError("generated-private-provider-payload"),
    ):
        with pytest.raises(CommandError) as error:
            call_command("reconcile_commerce", stdout=output)
    assert str(error.value) == "Local commerce report query failed."
    assert error.value.returncode == 1
    assert output.getvalue() == ""
