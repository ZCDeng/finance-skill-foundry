from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

FIXTURES = Path(__file__).parent / "fixtures" / "finance_baseline" / "scenarios"
SCOPE = {
    "ledger": "service-co",
    "organization": "华东",
    "period": "2026-08",
    "currency": "CNY",
    "unit": "万元",
    "scenario": "actual",
}


def _g1_rows() -> list[dict]:
    with (FIXTURES / "service_ledger.csv").open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _write_csv(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "".join(
            [
                ",".join(rows[0].keys()) + "\n",
                *[
                    ",".join(str(row[key]) for key in rows[0].keys()) + "\n"
                    for row in rows
                ],
            ]
        ),
        encoding="utf-8",
    )
    return path


def _finance(tmp_path: Path):
    rows = [
        row
        for row in _g1_rows()
        if row["period"] == "2026-08"
        and row["organization"] == "华东"
        and row["scenario"] == "actual"
    ]
    task = TaskStore(tmp_path / "var").create(title="调整项")
    analysis = AnalysisStore(task)
    dataset = analysis.add_dataset(_write_csv(tmp_path / "g1.csv", rows), name="g1")
    service = FinanceStore(task)
    context = service.save_context(
        {"bindings": {"actual": dataset["id"]}, "scopes": {"actual": SCOPE}}
    )
    return service, context, dataset


def _hq_spec(context_id: str, dataset_id: str, **extra) -> dict:
    payload = {
        "context_id": context_id,
        "label": "总部费用调整",
        "amount": "5",
        "profit_impact": "5",
        "accounts": ["总部费用调整"],
        "effective_period": "2026-08",
        "basis": "professional_judgment",
        "note": "总部费用 5 不进考核利润",
        "bindings": {"actual": dataset_id},
    }
    payload.update(extra)
    return payload


def test_cf19_save_persists_fields_and_forces_include_false(tmp_path):
    service, context, dataset = _finance(tmp_path)
    record = service.finance_adjustment_save(
        _hq_spec(context["id"], dataset["id"], include_in_management_pnl=True)
    )
    assert Decimal(str(record["amount"])) == Decimal("5")
    assert Decimal(str(record["profit_impact"])) == Decimal("5")
    assert record["effective_period"] == "2026-08"
    assert record["include_in_management_pnl"] is False
    assert record["basis"] == "professional_judgment"
    assert record["label"] == "总部费用调整"


def test_cf19_source_fact_without_locator_is_rejected(tmp_path):
    service, context, dataset = _finance(tmp_path)
    with pytest.raises(FoundryError):
        service.finance_adjustment_save(
            _hq_spec(context["id"], dataset["id"], basis="source_fact")
        )


def test_cf20_confirmed_named_ids_move_profit_from_30_to_35(tmp_path):
    service, context, dataset = _finance(tmp_path)
    prior = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    book = Decimal(str(prior["result"]["rows"][0]["profit"]))
    assert book == Decimal("30")
    saved = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    confirmed = service.finance_adjustment_confirm({"id": saved["id"]})
    rerun = service.run_metric(
        {
            "context_id": context["id"],
            "metric": {"kind": "management_pnl"},
            "adjustment_ids": [confirmed["id"]],
        }
    )
    row = rerun["result"]["rows"][0]
    assert Decimal(str(row["source_total"])) == Decimal("30")
    assert Decimal(str(row["adjusted_total"])) == Decimal("35")
    assert Decimal(str(prior["result"]["rows"][0]["profit"])) == Decimal("30")


def test_cf21_old_run_stays_30_after_confirm(tmp_path):
    service, context, dataset = _finance(tmp_path)
    prior = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    saved = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    confirmed = service.finance_adjustment_confirm({"id": saved["id"]})
    service.run_metric(
        {
            "context_id": context["id"],
            "metric": {"kind": "management_pnl"},
            "adjustment_ids": [confirmed["id"]],
        }
    )
    reloaded = service.analysis.get_run(prior["id"])
    assert Decimal(str(reloaded["result"]["rows"][0]["profit"])) == Decimal("30")


def test_cf20_unconfirmed_named_id_does_not_adjust(tmp_path):
    service, context, dataset = _finance(tmp_path)
    saved = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    rerun = service.run_metric(
        {
            "context_id": context["id"],
            "metric": {"kind": "management_pnl"},
            "adjustment_ids": [saved["id"]],
        }
    )
    row = rerun["result"]["rows"][0]
    assert Decimal(str(row.get("source_total", row["profit"]))) == Decimal("30")
    assert "adjusted_total" not in row
    assert rerun["result"]["ignored_adjustments"] == [{"id": saved["id"], "reason": "not_confirmed"}]
    assert any(diag["code"] == "adjustment_not_confirmed" for diag in rerun["result"]["diagnostics"])


def test_cf22_locator_must_sit_in_record_bindings(tmp_path):
    service, context, dataset = _finance(tmp_path)
    other = TaskStore(tmp_path / "other").create(title="外任务")
    foreign = AnalysisStore(other).add_dataset(
        _write_csv(tmp_path / "foreign.csv", _g1_rows()[:3]), name="foreign"
    )
    with pytest.raises(FoundryError):
        service.finance_adjustment_save(
            _hq_spec(
                context["id"],
                dataset["id"],
                locator={"dataset_id": foreign["id"], "kind": "csv", "source_row": 2},
            )
        )


def test_cf23_unlocated_exclusion_cannot_claim_source_fact(tmp_path):
    service, context, dataset = _finance(tmp_path)
    record = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    assert record["basis"] in {"user_assumption", "professional_judgment"}


def test_empty_bindings_are_invisible_to_session(tmp_path):
    service, context, dataset = _finance(tmp_path)
    with pytest.raises(FoundryError):
        service.finance_adjustment_save(
            {
                **_hq_spec(context["id"], dataset["id"]),
                "bindings": {},
            }
        )


def test_overlapping_accounts_without_parent_id_are_rejected(tmp_path):
    service, context, dataset = _finance(tmp_path)
    first = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    with pytest.raises(FoundryError):
        service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    child = service.finance_adjustment_save(
        _hq_spec(context["id"], dataset["id"], parent_id=first["id"], amount="4", profit_impact="4")
    )
    assert child["parent_id"] == first["id"]


def test_effective_period_mismatch_is_ignored(tmp_path):
    service, context, dataset = _finance(tmp_path)
    saved = service.finance_adjustment_save(
        _hq_spec(context["id"], dataset["id"], effective_period="2026-07")
    )
    confirmed = service.finance_adjustment_confirm({"id": saved["id"]})
    rerun = service.run_metric(
        {
            "context_id": context["id"],
            "metric": {"kind": "management_pnl"},
            "adjustment_ids": [confirmed["id"]],
        }
    )
    row = rerun["result"]["rows"][0]
    assert Decimal(str(row.get("source_total", row["profit"]))) == Decimal("30")
    assert "adjusted_total" not in row
    ignored = rerun["result"]["ignored_adjustments"]
    assert ignored[0]["id"] == confirmed["id"]
    assert ignored[0]["reason"] == "period_not_in_run"


def test_unknown_adjustment_id_fails_loudly(tmp_path):
    service, context, _dataset = _finance(tmp_path)
    with pytest.raises(FoundryError, match="unknown adjustment ids"):
        service.run_metric(
            {
                "context_id": context["id"],
                "metric": {"kind": "management_pnl"},
                "adjustment_ids": ["0" * 32],
            }
        )


def test_confirmed_but_unnamed_adjustment_is_not_applied(tmp_path):
    service, context, dataset = _finance(tmp_path)
    saved = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    service.finance_adjustment_confirm({"id": saved["id"]})
    rerun = service.run_metric({"context_id": context["id"], "metric": {"kind": "management_pnl"}})
    row = rerun["result"]["rows"][0]
    assert Decimal(str(row["profit"])) == Decimal("30")
    assert "adjusted_total" not in row


def test_named_ancestor_of_a_confirmed_revision_is_not_double_counted(tmp_path):
    service, context, dataset = _finance(tmp_path)
    pending = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    first = service.finance_adjustment_confirm({"id": pending["id"]})
    revision = service.finance_adjustment_save(
        _hq_spec(context["id"], dataset["id"], parent_id=first["id"], amount="7", profit_impact="7")
    )
    final = service.finance_adjustment_confirm({"id": revision["id"]})
    rerun = service.run_metric(
        {
            "context_id": context["id"],
            "metric": {"kind": "management_pnl"},
            "adjustment_ids": [first["id"], final["id"]],
        }
    )
    row = rerun["result"]["rows"][0]
    assert Decimal(str(row["source_total"])) == Decimal("30")
    assert Decimal(str(row["adjusted_total"])) == Decimal("37")
    assert row["applied_adjustment_ids"] == [final["id"]]
    assert rerun["result"]["ignored_adjustments"] == [{"id": first["id"], "reason": "superseded"}]
    listed = {row["id"]: row for row in service.finance_adjustment_list({"context_id": context["id"]})["adjustments"]}
    assert listed[pending["id"]]["superseded_by"] == first["id"]
    assert listed[first["id"]]["superseded_by"] == revision["id"]
    assert listed[revision["id"]]["superseded_by"] == final["id"]
    assert "superseded_by" not in listed[final["id"]]


def test_adjustments_are_rejected_outside_management_pnl(tmp_path):
    service, context, dataset = _finance(tmp_path)
    saved = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    confirmed = service.finance_adjustment_confirm({"id": saved["id"]})
    with pytest.raises(FoundryError, match="management_pnl"):
        service.run_metric(
            {
                "context_id": context["id"],
                "metric": {"kind": "control_totals"},
                "adjustment_ids": [confirmed["id"]],
            }
        )


def test_parent_id_must_point_at_the_overlapped_row(tmp_path):
    service, context, dataset = _finance(tmp_path)
    hq = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    other = service.finance_adjustment_save(
        _hq_spec(context["id"], dataset["id"], label="研发补贴", accounts=["研发补贴"])
    )
    with pytest.raises(FoundryError, match="parent_id"):
        service.finance_adjustment_save(
            _hq_spec(context["id"], dataset["id"], parent_id=other["id"], amount="4", profit_impact="4")
        )
    assert hq["id"] != other["id"]


def test_multi_month_adjustments_apply_to_their_own_month_rows():
    from foundry.finance_adjustments import apply_to_metric, run_periods, select_applied

    july = {"id": "adj-07", "include_in_management_pnl": True, "effective_period": "2026-07", "profit_impact": "5", "accounts": ["hq"]}
    august = {"id": "adj-08", "include_in_management_pnl": True, "effective_period": "2026-08", "profit_impact": "3", "accounts": ["hq"]}
    result = {
        "columns": ["period", "profit"],
        "rows": [
            {"period": "2026-07", "profit": "10"},
            {"period": "2026-08", "profit": "30"},
        ],
    }
    periods = run_periods({"scopes": {"actual": {"period": "2026-07"}}}, result)
    assert periods == {"2026-07", "2026-08"}
    applied, ignored = select_applied(["adj-07", "adj-08"], [july, august], periods=periods)
    assert ignored == []
    adjusted = apply_to_metric(result, applied)
    by_period = {row["period"]: row for row in adjusted["rows"]}
    assert Decimal(by_period["2026-07"]["adjusted_total"]) == Decimal("15")
    assert by_period["2026-07"]["applied_adjustment_ids"] == ["adj-07"]
    assert Decimal(by_period["2026-08"]["adjusted_total"]) == Decimal("33")
    assert by_period["2026-08"]["applied_adjustment_ids"] == ["adj-08"]
    assert len(adjusted["rows"]) == 2


def test_narrow_session_cannot_list_wide_adjustment(tmp_path):
    service, context, dataset = _finance(tmp_path)
    saved = service.finance_adjustment_save(_hq_spec(context["id"], dataset["id"]))
    wide = service.finance_adjustment_list({"context_id": context["id"]})
    assert any(row["id"] == saved["id"] for row in wide["adjustments"])
    narrow = FinanceStore(service.task, snapshot_ids=set())
    listed = narrow.finance_adjustment_list({"context_id": context["id"]})
    assert listed["adjustments"] == []


def test_hq_impact_applies_once_across_identity_rows():
    from foundry.finance_adjustments import apply_to_metric

    result = apply_to_metric(
        {
            "columns": ["organization", "profit"],
            "rows": [
                {"organization": "华东", "profit": "30", "period": "2026-08"},
                {"organization": "华南", "profit": "30", "period": "2026-08"},
            ],
        },
        [{"id": "adj-1", "profit_impact": "5", "effective_period": "2026-08"}],
    )
    rows = result["rows"]
    by_org = {row.get("organization"): row for row in rows if row.get("organization")}
    assert Decimal(str(by_org["华东"]["adjusted_total"])) == Decimal("30")
    assert Decimal(str(by_org["华南"]["adjusted_total"])) == Decimal("30")
    totals = [row for row in rows if not row.get("organization")]
    assert len(totals) == 1
    assert Decimal(str(totals[0]["adjusted_total"])) == Decimal("65")


def test_adjustment_save_rejects_caller_bindings_not_on_context(tmp_path):
    service, context, dataset = _finance(tmp_path)
    extra = service.analysis.add_dataset(_write_csv(tmp_path / "other.csv", _g1_rows()[:3]), name="extra")
    with pytest.raises(FoundryError, match="bindings"):
        service.finance_adjustment_save(
            _hq_spec(context["id"], dataset["id"], bindings={"actual": dataset["id"], "other": extra["id"]})
        )
    with pytest.raises(FoundryError, match="path|locator"):
        service.finance_adjustment_save(
            _hq_spec(
                context["id"],
                dataset["id"],
                basis="source_fact",
                locator={"dataset_id": dataset["id"], "path": "/tmp/secret.xlsx"},
            )
        )
