from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

pytestmark = pytest.mark.django_db

SQL_PATH = Path(__file__).resolve().parents[2] / "analytics/sql/observed_cohort_economics_v1.sql"
START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=7)
METRICS = {
    "net_coin_revenue_per_user_eur": Decimal("1.5"),
    "payer_conversion": Decimal("0.2"),
    "arppu_eur": Decimal("7.5"),
    "observed_contribution_before_acquisition_eur": Decimal("100"),
    "observed_contribution_per_user_eur": Decimal("1"),
    "observed_contribution_after_acquisition_eur": Decimal("40"),
    "paid_cac_eur": Decimal("0.6"),
}
FLAGS = {
    "metadata_valid",
    "values_valid",
    "window_complete",
    "duplicate_grain",
    "scope_conflict",
    "metrics_eligible",
}
CONTRIBUTION = {
    "observed_contribution_before_acquisition_eur",
    "observed_contribution_per_user_eur",
    "observed_contribution_after_acquisition_eur",
}


def generated(**changes: Any) -> dict[str, Any]:
    return {
        "cohort_window_id": "generated-scope-a",
        "cohort_id": "generated-cohort-a",
        "window_start_utc": START,
        "window_end_utc": END,
        "observation_cutoff_utc": END,
        "reporting_currency": "EUR",
        "environment": "synthetic",
        "financial_basis": "generated-net-recognized-v1",
        "allocation_basis": "generated-cohort-allocation-v1",
        "acquisition_classification": "paid",
        "acquired_users": 100,
        "original_verified_payers": 20,
        "net_coin_revenue_eur": Decimal("150"),
        "allocated_content_cost_eur": Decimal("40"),
        "variable_infrastructure_cost_eur": Decimal("10"),
        "acquisition_spend_eur": Decimal("60"),
        **changes,
    }


@pytest.fixture(autouse=True)
def input_relation() -> None:
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TEMPORARY TABLE observed_cohort_inputs_v1 (
                cohort_window_id text, cohort_id text,
                window_start_utc timestamptz, window_end_utc timestamptz,
                observation_cutoff_utc timestamptz,
                reporting_currency text, environment text,
                financial_basis text, allocation_basis text, acquisition_classification text,
                acquired_users bigint, original_verified_payers bigint,
                net_coin_revenue_eur numeric, allocated_content_cost_eur numeric,
                variable_infrastructure_cost_eur numeric, acquisition_spend_eur numeric
            ) ON COMMIT DROP
        """)


def insert(*rows: dict[str, Any]) -> None:
    columns = tuple(generated())
    placeholders = ", ".join(["%s"] * len(columns))
    with connection.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO observed_cohort_inputs_v1 ({', '.join(columns)}) VALUES ({placeholders})",
            [[row[column] for column in columns] for row in rows],
        )


def evaluate(*, diagnostics_only: bool = False) -> list[dict[str, Any]]:
    sql = SQL_PATH.read_text(encoding="utf-8")
    if diagnostics_only:
        # PostgreSQL supports infinite timestamps; Python datetime cannot decode
        # them. Project diagnostics around the actual query without its raw inputs.
        projection = ", ".join(sorted(FLAGS | METRICS.keys()))
        sql = f"SELECT {projection} FROM ({sql.rstrip().removesuffix(';')}) AS observed"
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def assert_suppressed(row: dict[str, Any]) -> None:
    assert row["metrics_eligible"] is False
    assert {key: row[key] for key in METRICS} == dict.fromkeys(METRICS)


def test_known_mature_cohort_uses_checked_in_read_only_sql_and_exact_decimals() -> None:
    source = generated()
    insert(source)
    with CaptureQueriesContext(connection) as queries:
        [row] = evaluate()
    assert len(queries) == 1
    assert row.keys() == source.keys() | FLAGS | METRICS.keys()
    assert {key: row[key] for key in source} == source
    assert {key: row[key] for key in METRICS} == METRICS
    assert all(isinstance(row[key], Decimal) for key in METRICS)
    assert row["metrics_eligible"] is True
    assert row["window_complete"] is True  # Exactly at the UTC window end is mature.
    assert row["duplicate_grain"] is row["scope_conflict"] is False
    assert not any(
        token in queries[0]["sql"].upper() for token in ("INSERT ", "UPDATE ", "DELETE ")
    )


def test_empty_input_returns_no_invented_cohort() -> None:
    assert evaluate() == []


@pytest.mark.parametrize(
    ("column", "unknown"),
    [
        (
            "acquired_users",
            {
                "net_coin_revenue_per_user_eur",
                "payer_conversion",
                "observed_contribution_per_user_eur",
                "paid_cac_eur",
            },
        ),
        ("original_verified_payers", {"payer_conversion", "arppu_eur"}),
        ("net_coin_revenue_eur", CONTRIBUTION | {"net_coin_revenue_per_user_eur", "arppu_eur"}),
        ("allocated_content_cost_eur", CONTRIBUTION),
        ("variable_infrastructure_cost_eur", CONTRIBUTION),
        ("acquisition_spend_eur", {"observed_contribution_after_acquisition_eur", "paid_cac_eur"}),
    ],
)
def test_missing_input_suppresses_only_dependent_metrics(column: str, unknown: set[str]) -> None:
    insert(generated(**{column: None}))
    [row] = evaluate()
    assert row["metrics_eligible"] is True
    assert {key: row[key] for key in METRICS} == {
        key: None if key in unknown else value for key, value in METRICS.items()
    }


@pytest.mark.parametrize("users", [0, None])
def test_zero_or_unknown_users_and_zero_payers_have_undefined_ratios(users: int | None) -> None:
    insert(generated(acquired_users=users, original_verified_payers=0))
    [row] = evaluate()
    assert row["metrics_eligible"] is True
    assert all(
        row[key] is None
        for key in (
            "net_coin_revenue_per_user_eur",
            "payer_conversion",
            "arppu_eur",
            "observed_contribution_per_user_eur",
            "paid_cac_eur",
        )
    )
    assert row["observed_contribution_before_acquisition_eur"] == Decimal("100")
    assert row["observed_contribution_after_acquisition_eur"] == Decimal("40")


def test_zero_payers_preserve_zero_conversion_but_arppu_is_undefined() -> None:
    insert(generated(original_verified_payers=0))
    [row] = evaluate()
    assert row["payer_conversion"] == Decimal("0")
    assert row["arppu_eur"] is None
    assert row["net_coin_revenue_per_user_eur"] == Decimal("1.5")


def test_true_zero_money_remains_zero_including_fully_refunded_original_payers() -> None:
    insert(
        generated(
            net_coin_revenue_eur=0,
            allocated_content_cost_eur=0,
            variable_infrastructure_cost_eur=0,
            acquisition_spend_eur=0,
        )
    )
    [row] = evaluate()
    assert row["original_verified_payers"] == 20
    assert {key: row[key] for key in METRICS} == {
        **dict.fromkeys(METRICS, Decimal("0")),
        "payer_conversion": Decimal("0.2"),
    }


def test_negative_net_revenue_and_contribution_are_valid_without_recomputing_refunds() -> None:
    insert(generated(net_coin_revenue_eur=Decimal("-50")))
    [row] = evaluate()
    assert row["metrics_eligible"] is True
    assert {key: row[key] for key in METRICS} == {
        "net_coin_revenue_per_user_eur": Decimal("-0.5"),
        "payer_conversion": Decimal("0.2"),
        "arppu_eur": Decimal("-2.5"),
        "observed_contribution_before_acquisition_eur": Decimal("-100"),
        "observed_contribution_per_user_eur": Decimal("-1"),
        "observed_contribution_after_acquisition_eur": Decimal("-160"),
        "paid_cac_eur": Decimal("0.6"),
    }


@pytest.mark.parametrize("classification", ["organic", "unpaid", "technical_beta", "unmatched"])
def test_nonpaid_cohorts_never_claim_paid_cac(classification: str) -> None:
    insert(generated(acquisition_classification=classification))
    [row] = evaluate()
    assert row["metrics_eligible"] is True
    assert row["paid_cac_eur"] is None
    assert row["observed_contribution_after_acquisition_eur"] == Decimal("40")


def test_cutoff_before_window_end_suppresses_all_completed_window_metrics() -> None:
    insert(generated(observation_cutoff_utc=END - timedelta(microseconds=1)))
    [row] = evaluate()
    assert row["metadata_valid"] is True
    assert row["window_complete"] is False
    assert_suppressed(row)


@pytest.mark.parametrize(
    "change",
    [
        {"cohort_window_id": None},
        {"cohort_id": " "},
        {"financial_basis": ""},
        {"allocation_basis": None},
        {"reporting_currency": "USD"},
        {"environment": "production"},
        {"acquisition_classification": "unknown"},
        {"window_start_utc": None},
        {"window_end_utc": START},
        {"window_end_utc": START - timedelta(days=1)},
        {"observation_cutoff_utc": None},
    ],
)
def test_invalid_scope_metadata_preserves_diagnostics_without_metrics(
    change: dict[str, Any],
) -> None:
    insert(generated(**change))
    [row] = evaluate()
    assert row["metadata_valid"] is False
    assert_suppressed(row)


@pytest.mark.parametrize(
    "column", ["cohort_window_id", "cohort_id", "financial_basis", "allocation_basis"]
)
def test_whitespace_only_required_labels_are_invalid(column: str) -> None:
    insert(generated(**{column: "\t\r\n "}))
    [row] = evaluate()
    assert row["metadata_valid"] is False
    assert_suppressed(row)


@pytest.mark.parametrize("column", ["window_start_utc", "window_end_utc", "observation_cutoff_utc"])
@pytest.mark.parametrize("value", ["infinity", "-infinity"])
def test_infinite_temporal_metadata_suppresses_every_metric(column: str, value: str) -> None:
    insert(generated(**{column: value}))
    [row] = evaluate(diagnostics_only=True)
    assert row["metadata_valid"] is False
    assert_suppressed(row)


@pytest.mark.parametrize(
    "change",
    [
        {"acquired_users": -1},
        {"original_verified_payers": -1},
        {"original_verified_payers": 101},
        {"allocated_content_cost_eur": -1},
        {"variable_infrastructure_cost_eur": -1},
        {"acquisition_spend_eur": -1},
        {"net_coin_revenue_eur": Decimal("NaN")},
        {"allocated_content_cost_eur": Decimal("Infinity")},
        {"variable_infrastructure_cost_eur": Decimal("-Infinity")},
    ],
)
def test_invalid_counts_costs_and_nonfinite_money_are_not_usable(change: dict[str, Any]) -> None:
    insert(generated(**change))
    [row] = evaluate()
    assert row["values_valid"] is False
    assert_suppressed(row)


@pytest.mark.parametrize("different_id", [False, True])
def test_duplicate_complete_grains_are_all_flagged_even_under_different_ids(
    different_id: bool,
) -> None:
    other = "generated-scope-b" if different_id else "generated-scope-a"
    insert(generated(), generated(cohort_window_id=other, net_coin_revenue_eur=Decimal("999")))
    rows = evaluate()
    assert len(rows) == 2
    assert {row["net_coin_revenue_eur"] for row in rows} == {Decimal("150"), Decimal("999")}
    for row in rows:
        assert row["duplicate_grain"] is True
        assert row["scope_conflict"] is False
        assert_suppressed(row)


@pytest.mark.parametrize(
    "change",
    [
        {"cohort_id": "generated-other"},
        {"window_start_utc": START - timedelta(days=1)},
        {"window_end_utc": END - timedelta(days=1)},
        {"observation_cutoff_utc": END + timedelta(days=1)},
        {"reporting_currency": "USD"},
        {"environment": "production"},
        {"financial_basis": "generated-financial-v2"},
        {"allocation_basis": "generated-allocation-v2"},
        {"acquisition_classification": "organic"},
    ],
)
def test_reused_scope_id_with_incompatible_metadata_invalidates_every_variant(
    change: dict[str, Any],
) -> None:
    insert(generated(), generated(**change))
    rows = evaluate()
    assert len(rows) == 2
    for row in rows:
        assert row["scope_conflict"] is True
        assert row["duplicate_grain"] is False
        assert_suppressed(row)


@pytest.mark.parametrize("reverse", [False, True])
def test_distinct_dimensions_stay_separate_and_input_order_cannot_change_results(
    reverse: bool,
) -> None:
    changes: list[dict[str, Any]] = [
        {},
        {"cohort_id": "generated-other"},
        {"window_start_utc": START - timedelta(days=1)},
        {"financial_basis": "generated-financial-v2"},
        {"allocation_basis": "generated-allocation-v2"},
        {"reporting_currency": "USD"},
    ]
    rows = [
        generated(
            cohort_window_id=f"generated-scope-{index}", net_coin_revenue_eur=index * 100, **change
        )
        for index, change in enumerate(changes)
    ]
    insert(*(reversed(rows) if reverse else rows))
    actual = {row["cohort_window_id"]: row for row in evaluate()}
    assert len(actual) == len(rows)
    for index in range(len(changes)):
        row = actual[f"generated-scope-{index}"]
        assert row["duplicate_grain"] is row["scope_conflict"] is False
        if index == 5:
            assert_suppressed(row)
        else:
            assert row["net_coin_revenue_per_user_eur"] == Decimal(index)
            assert row["observed_contribution_before_acquisition_eur"] == Decimal(index * 100 - 50)
