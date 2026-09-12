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


def test_the_field_map_knows_the_spelling_the_proposal_engine_proposes() -> None:
    """Two alias tables for one vocabulary have to agree.

    The structure proposal engine names a column 科目代码; this table only knew
    科目编码, so a raw import read every account code as blank and filed the
    rows under __unmapped__ without saying anything.
    """
    from foundry.structure_proposal import ROLE_ALIASES
    from foundry.finance_model import DEFAULT_FIELD_MAP

    shared = {
        "account_code": "account_code",
        "account_name": "account_name",
        "amount": "amount",
        "doc_id": "doc_id",
        "line_id": "line_id",
        "period": "period",
        "currency": "currency",
        "unit": "unit",
    }
    for role, field in shared.items():
        missing = set(ROLE_ALIASES[role]) - set(DEFAULT_FIELD_MAP[field])
        assert not missing, f"{field} does not know {sorted(missing)}"


def test_a_row_with_no_account_code_says_so_rather_than_falling_through() -> None:
    from foundry.finance_model import normalize_finance_dataset

    normalized = normalize_finance_dataset(
        {"id": "d", "name": "d", "rows": [
            {"科目名称": "主营业务收入", "金额": "400", "期间": "2026-08",
             "币种": "CNY", "单位": "元"},
        ]},
        {"ledger": "l", "organization": "o", "period": "2026-08",
         "currency": "CNY", "unit": "元", "scenario": "actual"},
        account_map={"rows": []},
    )
    codes = [d["code"] for d in normalized["diagnostics"]]
    assert "missing_account_code" in codes
    assert normalized["rows"][0]["management_account"] == "__unmapped__"


def test_an_unmapped_chart_of_accounts_is_one_line_naming_the_codes() -> None:
    """128 warnings for 128 accounts buried every other diagnostic."""
    from foundry.finance_model import normalize_finance_dataset

    rows = [
        {"科目代码": f"6{index:03d}", "金额": "10", "期间": "2026-08",
         "币种": "CNY", "单位": "元"}
        for index in range(40)
    ]
    normalized = normalize_finance_dataset(
        {"id": "d", "name": "d", "rows": rows},
        {"ledger": "l", "organization": "o", "period": "2026-08",
         "currency": "CNY", "unit": "元", "scenario": "actual"},
        account_map={"rows": []},
    )
    unmapped = [d for d in normalized["diagnostics"] if d["code"] == "unmapped_account"]
    assert len(unmapped) == 1
    assert unmapped[0]["count"] == 40
    assert len(unmapped[0]["account_codes"]) == 12
    assert "6000" in unmapped[0]["message"]


def test_a_voucher_number_alone_is_enough_to_drill_down() -> None:
    """A file export names the voucher; the ERP's line number is its own.

    Requiring both left every real export permanently un-drillable, while the
    row itself is the line and the evidence reference already says which.
    """
    from foundry.finance_model import voucher_reference

    assert voucher_reference({"凭证号": "记-2026-08-001"}) == {
        "doc_id": "记-2026-08-001",
        "line_id": "",
    }
    assert voucher_reference({"凭证号": "记-1", "行号": "3"})["line_id"] == "3"
    assert voucher_reference({"科目代码": "6001"}) is None
