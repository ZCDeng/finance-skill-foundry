from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from foundry.errors import FoundryError
from foundry.finance_model import normalize_finance_dataset

FIXTURES = Path(__file__).parent / "fixtures" / "finance_baseline" / "scenarios"


def _csv(name: str) -> list[dict]:
    with (FIXTURES / name).open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _dataset(name: str, rows: list[dict]) -> dict:
    return {"id": name, "name": name, "rows": rows, "metadata": {"fixture": name}}


def test_normalizes_service_ledger_with_scope_control_totals_and_trace() -> None:
    result = normalize_finance_dataset(
        _dataset("service-ledger", _csv("service_ledger.csv")),
        {
            "ledger": "service-co",
            "organization": "华东",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "万元",
            "scenario": "actual",
        },
    )

    assert [row["source_row"] for row in result["rows"]] == [1, 2, 3]
    assert result["rows"][0]["dataset_id"] == "service-ledger"
    assert result["rows"][0]["trace"]["doc_id"] == "SV-202608-001"
    totals = {
        row["management_account"]: Decimal(row["amount"])
        for row in result["control_totals"]
    }
    assert totals == {
        "revenue": Decimal("120"),
        "cost": Decimal("70"),
        "expense": Decimal("20"),
    }
    signed = {
        row["management_account"]: Decimal(row["signed_amount"])
        for row in result["control_totals"]
    }
    assert signed == {
        "revenue": Decimal("-120"),
        "cost": Decimal("70"),
        "expense": Decimal("20"),
    }


def test_balance_level_rows_are_usable_without_fabricated_drilldown() -> None:
    rows = [
        {
            "ledger": "service-co",
            "organization": "华东",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "万元",
            "scenario": "actual",
            "account_code": "6001",
            "account_direction": "credit",
            "management_account": "revenue",
            "amount": "120",
            "dc_flag": "credit",
            "source_row": "1",
        }
    ]
    result = normalize_finance_dataset(
        _dataset("balance-only", rows), {"ledger": "service-co"}
    )

    assert len(result["rows"]) == 1
    assert result["rows"][0]["drilldown_available"] is False
    assert any(d["code"] == "voucher_detail_unavailable" for d in result["diagnostics"])


def test_mapping_diagnostics_manager_resolution_and_leading_zero_codes() -> None:
    account_map = {"version": "manager-v1", "rows": _csv("account_map_conflicts.csv")}
    result = normalize_finance_dataset(
        _dataset("multi-org", _csv("multi_org_ledger.csv")),
        {
            "ledger": "group-co",
            "organization": "北京主体",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
        },
        account_map=account_map,
        policy={"manager_mappings": {"6601": "expense"}},
    )

    codes = {row["account_code"] for row in result["rows"]}
    assert "01001" in codes
    cash = next(row for row in result["rows"] if row["account_code"] == "01001")
    assert cash["management_account"] == "cash"
    expense = [row for row in result["rows"] if row["account_code"] == "6601"]
    assert {row["management_account"] for row in expense} == {"expense"}
    assert result["provenance"]["account_map_version"] == "manager-v1"
    assert {d["code"] for d in result["diagnostics"]} >= {
        "duplicate_mapping",
        "parent_child_overlap",
    }


def test_mixed_currencies_are_diagnosed_when_scope_does_not_filter() -> None:
    result = normalize_finance_dataset(
        _dataset("multi-org", _csv("multi_org_ledger.csv")),
        {"ledger": "group-co", "period": "2026-08", "unit": "元"},
    )

    assert {row["currency"] for row in result["rows"]} == {"CNY", "USD"}
    assert any(
        d["code"] == "mixed_currency" and d["severity"] == "error"
        for d in result["diagnostics"]
    )


def test_g5_movement_checks_preserve_signed_credit_balances_and_special_policies() -> (
    None
):
    result = normalize_finance_dataset(
        _dataset("g5", _csv("g5_account_movements.csv")),
        {
            "ledger": "group-co",
            "organization": "北京主体",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
        },
        policy={
            "movement_policies": {
                "red_letter": "preserve",
                "closing_transfer": "preserve",
                "adjustment_period": "preserve",
            }
        },
    )

    checks = {row["account_code"]: row for row in result["movement_checks"]}
    assert checks["1122"]["status"] == "passed"
    assert Decimal(checks["1122"]["ending"]) == Decimal("110")
    assert checks["2202"]["status"] == "passed"
    assert Decimal(checks["2202"]["ending"]) == Decimal("-220")
    assert {d["code"] for d in result["diagnostics"]} >= {
        "red_letter_policy",
        "closing_transfer_policy",
        "adjustment_period_policy",
        "unposted_row",
    }


def test_explicit_yuan_to_wanyuan_conversion() -> None:
    rows = [
        {
            "ledger": "x",
            "organization": "o",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "1200000",
            "dc_flag": "credit",
            "source_row": "7",
        }
    ]
    result = normalize_finance_dataset(
        _dataset("yuan", rows),
        {"ledger": "x", "unit": "万元"},
        policy={"target_unit": "万元"},
    )

    assert result["rows"][0]["unit"] == "万元"
    assert Decimal(result["rows"][0]["amount"]) == Decimal("120")
    assert result["rows"][0]["policies"]["unit_conversion"] == "元->万元"


def test_present_mismatched_scope_filters_except_explicit_unit_conversion() -> None:
    rows = [
        {
            "ledger": "x",
            "organization": "east",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "10000",
        },
        {
            "ledger": "x",
            "organization": "west",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "20000",
        },
    ]
    result = normalize_finance_dataset(
        _dataset("scoped", rows),
        {"ledger": "x", "organization": "east", "unit": "万元"},
        policy={"target_unit": "万元"},
    )

    assert len(result["rows"]) == 1
    assert result["rows"][0]["organization"] == "east"
    assert Decimal(result["rows"][0]["amount"]) == Decimal("1")


def test_multi_valued_auxiliary_is_preserved_and_diagnosed() -> None:
    rows = [
        {
            "ledger": "x",
            "organization": "east",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
            "management_account": "revenue",
            "amount": "10",
            "aux_department": "A;B",
        }
    ]
    result = normalize_finance_dataset(_dataset("aux", rows), {"ledger": "x"})

    assert result["rows"][0]["auxiliaries"]["department"] == ["A", "B"]
    assert any(d["code"] == "multi_valued_auxiliary" for d in result["diagnostics"])


def test_source_shaped_rows_take_scalar_scope_defaults_and_status_filtering() -> None:
    rows = [
        {
            "document_id": "DOC-1",
            "line_id": "1",
            "organization_id": "O1",
            "management_account": "revenue",
            "amount": "10",
            "_source_row_state": "active",
            "source_row_number": "7",
        },
        {
            "document_id": "DOC-2",
            "line_id": "1",
            "ledger_id": "L1",
            "organization_id": "O1",
            "management_account": "revenue",
            "amount": "99",
            "_source_row_state": "deleted",
            "source_row_number": "8",
        },
        {
            "document_id": "DOC-3",
            "line_id": "1",
            "ledger_id": "L1",
            "organization_id": "O1",
            "management_account": "cost",
            "amount": "30",
            "status": "duplicate_pull",
            "source_row_number": "9",
        },
    ]
    result = normalize_finance_dataset(
        _dataset("source-shaped", rows),
        {
            "ledger": "L1",
            "organization": "O1",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
            "scenario": "actual",
        },
    )

    assert [row["ledger"] for row in result["rows"]] == ["L1", "L1", "L1"]
    assert [row["organization"] for row in result["rows"]] == ["O1", "O1", "O1"]
    assert result["rows"][0]["period"] == "2026-09"
    assert result["rows"][0]["currency"] == "CNY"
    assert result["rows"][0]["trace"]["doc_id"] == "DOC-1"
    assert result["rows"][1]["source_status"] == "deleted"
    assert result["rows"][2]["source_status"] == "duplicate_pull"
    assert [
        (row["management_account"], row["amount"]) for row in result["control_totals"]
    ] == [("revenue", "10")]
    assert {diag["code"] for diag in result["diagnostics"]} >= {
        "inactive_source_row",
    }


def test_list_scope_does_not_invent_missing_identity_values() -> None:
    rows = [
        {
            "management_account": "revenue",
            "amount": "10",
            "currency": "CNY",
            "unit": "元",
        }
    ]
    result = normalize_finance_dataset(
        _dataset("list-scope", rows),
        {"ledger": ["L1", "L2"], "currency": "CNY", "unit": "元"},
    )

    assert result["rows"] == []


def test_high_volume_normalization_diagnostics_are_bounded_by_code() -> None:
    rows = [
        {
            "ledger": "L1",
            "organization": "O1",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
            "management_account": "revenue",
            "amount": "1",
            "source_row": str(index),
        }
        for index in range(20)
    ]
    result = normalize_finance_dataset(
        _dataset("balance-manager", rows), {"ledger": "L1"}
    )
    voucher_diags = [
        diag
        for diag in result["diagnostics"]
        if diag["code"] == "voucher_detail_unavailable"
    ]

    assert len(voucher_diags) == 1
    assert voucher_diags[0]["count"] == 20
    assert len(voucher_diags[0]["sample_row_refs"]) <= 5


def test_scoped_source_rows_shares_scope_alias_and_inactive_filtering() -> None:
    from foundry.finance_model import scoped_source_rows

    rows = [
        {
            "ledger_id": "L1",
            "organization_id": "O1",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
            "quantity": "12",
            "price": "11",
            "document_id": "DOC-1",
            "source_row_number": "3",
        },
        {
            "ledger_id": "L1",
            "organization_id": "O1",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
            "quantity": "99",
            "price": "99",
            "_source_row_state": "deleted",
            "source_row_number": "4",
        },
    ]
    scoped = scoped_source_rows(
        _dataset("source-shaped", rows),
        {
            "ledger": "L1",
            "organization": "O1",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
        },
    )

    assert len(scoped) == 1
    assert scoped[0]["ledger"] == "L1"
    assert scoped[0]["organization"] == "O1"
    assert scoped[0]["doc_id"] == "DOC-1"
    assert scoped[0]["quantity"] == "12"
    assert scoped[0]["source"] == {
        "dataset_id": "source-shaped",
        "row_index": 1,
        "source_row": 3,
    }


def test_scoped_source_rows_refuses_unit_relabel_without_conversion_policy() -> None:
    from foundry.finance_model import scoped_source_rows

    rows = [
        {
            "ledger": "L1",
            "organization": "O1",
            "period": "2026-09",
            "currency": "CNY",
            "unit": "元",
            "amount": "10000",
        }
    ]

    try:
        scoped_source_rows(_dataset("yuan", rows), {"ledger": "L1", "unit": "万元"})
    except FoundryError as exc:
        assert "explicit conversion" in str(exc)
    else:
        raise AssertionError("unit mismatch must be refused")
