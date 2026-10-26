"""Stable machine identifiers keep localized aging labels out of named cells."""
from copy import deepcopy
from decimal import Decimal

import pytest

from foundry.errors import FoundryError
from foundry.finance_scenarios import compute_receivables_aging


SCOPE = {"ledger": "L", "organization": "O", "unit": "万元"}
BUCKETS = [
    {"name": "0-30天", "min": 0, "max": 30},
    {"name": "31-60天", "min": 31, "max": 60},
    {"name": "61-90天", "min": 61, "max": 90},
    {"name": "90+天", "min": 91, "max": None},
]


def invoice(key, due, amount, currency="CNY"):
    return {**SCOPE, "id": key, "currency": currency, "due_date": due, "amount": amount}


def test_standard_localized_labels_keep_boundary_identity_currency_and_zero_rows():
    original = deepcopy(BUCKETS)
    result = compute_receivables_aging([
        invoice("cny30", "2026-08-31", "40"),
        invoice("cny31", "2026-08-30", "60"),
        invoice("usd30", "2026-08-31", "20", "USD"),
    ], as_of="2026-09-30", scope=SCOPE, buckets=BUCKETS)
    assert BUCKETS == original
    nonzero = {(r["currency"], r["bucket"]): Decimal(r["open_amount"])
               for r in result["rows"] if Decimal(r["open_amount"])}
    assert nonzero == {("CNY", "0-30"): Decimal(40), ("CNY", "31-60"): Decimal(60),
                       ("USD", "0-30"): Decimal(20)}
    assert [(r["overdue_days"], r["bucket"], r["bucket_label"]) for r in result["detail_rows"]] == [
        (30, "0-30", "0-30天"), (31, "31-60", "31-60天"), (30, "0-30", "0-30天")]
    assert len(result["rows"]) == 10
    assert len({r["result_key"] for r in result["rows"]}) == 10
    assert all(r["as_of"] == "2026-09-30" and r["unit"] == "万元" for r in result["rows"])
    assert any(r["bucket"] == "61-90" and r["open_amount"] == "0" for r in result["rows"])
    assert {r["name"] for r in result["columns"]} >= {"bucket", "bucket_label"}
    assert {r["name"] for r in result["detail_columns"]} >= {"bucket", "bucket_label"}


@pytest.mark.parametrize("custom", [
    [{"name": "recent", "min": 0, "max": 30}, {"name": "late", "min": 31, "max": None}],
    [{"name": "0-30天", "min": 0, "max": 20}, {"name": "other", "min": 21, "max": None}],
])
def test_custom_names_and_nonstandard_bounds_are_not_inferred(custom):
    result = compute_receivables_aging([invoice("i", "2026-09-25", "1")],
        as_of="2026-09-30", scope=SCOPE, buckets=custom)
    detail = result["detail_rows"][0]
    assert detail["bucket"] == custom[0]["name"]
    assert detail["bucket_label"] == custom[0]["name"]


def test_alias_collision_is_rejected_before_any_source_data_is_needed():
    with pytest.raises(FoundryError, match="buckets.*identit"):
        compute_receivables_aging([], as_of="2026-09-30", scope=SCOPE, buckets=[
            {"name": "0-30天", "min": 0, "max": 30},
            {"name": "0-30", "min": 31, "max": None},
        ])


def test_default_and_localized_standard_bucket_keys_are_the_same():
    invoices = [invoice("i", "2026-08-30", "10")]
    default = compute_receivables_aging(invoices, as_of="2026-09-30", scope=SCOPE)
    localized = compute_receivables_aging(invoices, as_of="2026-09-30", scope=SCOPE, buckets=BUCKETS)
    assert [(r["bucket"], r["result_key"], r["open_amount"]) for r in localized["rows"]] == [
        (r["bucket"], r["result_key"], r["open_amount"]) for r in default["rows"]]
