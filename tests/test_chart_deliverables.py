from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

SCOPE = {"ledger": "L1", "organization": "O1", "currency": "CNY", "unit": "万元"}


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _g1(tmp_path: Path):
    task = TaskStore(tmp_path / "var").create(title="图表")
    service = FinanceStore(task)
    rows = [
        {"ledger": "service-co", "organization": "华东", "period": "2026-08", "currency": "CNY", "unit": "万元", "scenario": "actual", "management_account": "revenue", "amount": "120"},
        {"ledger": "service-co", "organization": "华东", "period": "2026-08", "currency": "CNY", "unit": "万元", "scenario": "actual", "management_account": "cost", "amount": "70"},
        {"ledger": "service-co", "organization": "华东", "period": "2026-08", "currency": "CNY", "unit": "万元", "scenario": "actual", "management_account": "expense", "amount": "20"},
    ]
    dataset = service.analysis.add_dataset(_write(tmp_path / "g1.json", rows), name="g1")
    context = service.save_context(
        {
            "bindings": {"actual": dataset["id"]},
            "scopes": {
                "actual": {
                    "ledger": "service-co",
                    "organization": "华东",
                    "period": "2026-08",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                }
            },
        }
    )
    run = service.run_metric({"context_id": context["id"], "metric": {"kind": "management_pnl"}})
    return service, context, dataset, run


def _cash(tmp_path: Path):
    task = TaskStore(tmp_path / "cash").create(title="现金图")
    service = FinanceStore(task)
    bindings = {}
    for alias, rows in {
        "receipts": [{"id": "R1", "date": "2026-09-25", "amount": "100"}],
        "payments": [{"id": "P1", "date": "2026-09-28", "amount": "60"}],
    }.items():
        bindings[alias] = AnalysisStore(task).add_dataset(_write(tmp_path / f"{alias}.json", rows), name=alias)["id"]
    context = service.save_context({"bindings": bindings, "scopes": {alias: SCOPE for alias in bindings}})
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "cash_13_weeks",
            "inputs": {
                "opening_cash": "50",
                "start_date": "2026-09-24",
                "actual_cutoff": "2026-09-23",
                "scope": SCOPE,
            },
            "label": "基准",
        }
    )
    run = service.run_scenario({"scenario_id": scenario["id"]})
    return service, context, scenario, run


def test_cf27_save_reopens_original_series_without_rerun(tmp_path: Path) -> None:
    service, _context, dataset, run = _g1(tmp_path)
    chart = service.chart_deliverable_save({"run_id": run["id"]})
    stored = service.analysis.root / "charts" / f"{chart['id']}.json"
    assert stored.is_file()
    opened = service.chart_deliverable_open({"id": chart["id"]})
    assert opened["run_id"] == run["id"]
    assert opened["snapshot_hashes"]["actual"] == dataset["data_hash"]
    assert opened["series"]["rows"] == run["result"]["rows"]
    assert opened["content_hash"] == chart["content_hash"]
    listed = service.chart_deliverable_list({})
    assert [row["id"] for row in listed["charts"]] == [chart["id"]]


def test_cf27f_foreign_task_and_narrow_session_cannot_touch_chart(tmp_path: Path) -> None:
    service, _context, dataset, run = _g1(tmp_path)
    chart = service.chart_deliverable_save({"run_id": run["id"]})
    other = FinanceStore(TaskStore(tmp_path / "other").create(title="外任务"))
    with pytest.raises(FoundryError):
        other.chart_deliverable_open({"id": chart["id"]})
    assert other.chart_deliverable_list({})["charts"] == []
    with pytest.raises(FoundryError):
        other.chart_deliverable_save({"run_id": run["id"]})
    narrow = FinanceStore(service.task, snapshot_ids={"not-this-snapshot"})
    assert narrow.chart_deliverable_list({})["charts"] == []
    with pytest.raises(FoundryError, match="session context|outside"):
        narrow.chart_deliverable_open({"id": chart["id"]})
    with pytest.raises(FoundryError, match="session context|outside"):
        narrow.chart_deliverable_save({"run_id": run["id"]})
    empty = FinanceStore(service.task)
    with pytest.raises(FoundryError, match="bindings"):
        empty.chart_deliverable_save({"run_id": run["id"], "bindings": {}})


def test_cf27_rejects_locator_scratch_as_chart(tmp_path: Path) -> None:
    service, _context, _dataset, run = _g1(tmp_path)
    with pytest.raises(FoundryError, match="scratch|preview|path"):
        service.chart_deliverable_save(
            {"run_id": run["id"], "preview_path": "artifacts/preview/abc/sheet.xlsx"}
        )


def test_cf28_child_scenario_new_chart_leaves_parent_hash(tmp_path: Path) -> None:
    service, _context, scenario, parent_run = _cash(tmp_path)
    parent = service.chart_deliverable_save({"run_id": parent_run["id"]})
    child = service.save_scenario(
        {
            "parent_id": scenario["id"],
            "changes": {"scenario": {"delay_receipts_days": 14, "label": "延迟两周"}},
            "label": "延迟两周",
        }
    )
    child_run = service.run_scenario({"scenario_id": child["id"]})
    child_chart = service.chart_deliverable_save({"run_id": child_run["id"], "parent_id": parent["id"]})
    reopened = service.chart_deliverable_open({"id": parent["id"]})
    assert reopened["content_hash"] == parent["content_hash"]
    assert child_chart["content_hash"] != parent["content_hash"]
    assert child_chart["parent_id"] == parent["id"]
    assert child_run["result"]["rows"][0]["closing_cash"] == "-10"
    assert parent_run["result"]["rows"][0]["closing_cash"] == "90"


def test_cf29_missing_original_snapshot_fails_closed(tmp_path: Path) -> None:
    service, _context, dataset, run = _g1(tmp_path)
    chart = service.chart_deliverable_save({"run_id": run["id"]})
    replacement = service.analysis.add_dataset(
        _write(tmp_path / "newer.json", [{"management_account": "revenue", "amount": "999"}]),
        name="newer",
    )
    opened = service.chart_deliverable_open({"id": chart["id"]})
    assert opened["snapshot_hashes"]["actual"] == dataset["data_hash"]
    assert opened["snapshot_hashes"]["actual"] != replacement["data_hash"]
    shutil.rmtree(service.analysis.root / "datasets" / dataset["id"])
    with pytest.raises(FoundryError, match="snapshot"):
        service.chart_deliverable_open({"id": chart["id"]})


def test_chart_save_ignores_caller_series_and_rejects_scratch_text(tmp_path: Path) -> None:
    service, _context, _dataset, run = _g1(tmp_path)
    spoofed = service.chart_deliverable_save(
        {"run_id": run["id"], "series": {"columns": ["profit"], "rows": [{"profit": "999"}]}}
    )
    opened = service.chart_deliverable_open({"id": spoofed["id"]})
    assert opened["series"]["rows"] == run["result"]["rows"]
    with pytest.raises(FoundryError, match="scratch|preview"):
        service.chart_deliverable_save(
            {"run_id": run["id"], "label": "artifacts/preview/abc/sheet.xlsx"}
        )


def test_charts_and_locator_scratch_never_enter_the_deliverable_history(tmp_path: Path) -> None:
    import csv

    from foundry.finance_locators import stage_source_locator_preview

    task = TaskStore(tmp_path / "csvtask").create(title="图表与预览")
    service = FinanceStore(task)
    rows = [
        {"ledger": "service-co", "organization": "华东", "period": "2026-08", "currency": "CNY", "unit": "万元", "scenario": "actual", "management_account": "revenue", "amount": "120"},
        {"ledger": "service-co", "organization": "华东", "period": "2026-08", "currency": "CNY", "unit": "万元", "scenario": "actual", "management_account": "cost", "amount": "70"},
        {"ledger": "service-co", "organization": "华东", "period": "2026-08", "currency": "CNY", "unit": "万元", "scenario": "actual", "management_account": "expense", "amount": "20"},
    ]
    source = tmp_path / "g1.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    dataset = service.analysis.add_dataset(source, name="g1")
    context = service.save_context(
        {
            "bindings": {"actual": dataset["id"]},
            "scopes": {"actual": {"ledger": "service-co", "organization": "华东", "period": "2026-08", "currency": "CNY", "unit": "万元", "scenario": "actual"}},
        }
    )
    run = service.run_metric({"context_id": context["id"], "metric": {"kind": "management_pnl"}})
    before = len(task.deliverables())
    saved = service.chart_deliverable_save({"run_id": run["id"], "label": "利润图"})
    scratch = stage_source_locator_preview(service, {"run_id": run["id"], "row": 0, "column": "expense"})
    assert scratch.is_file()
    assert len(task.deliverables()) == before
    listed = service.chart_deliverable_list({})["charts"]
    assert [row["id"] for row in listed] == [saved["id"]]
    persisted = service._read("charts", saved["id"])
    assert set(persisted["bindings"].values()) == {dataset["id"]}
    assert persisted["run_id"] == run["id"]
    assert persisted["snapshot_hashes"] == run["input_hashes"]
    blob = json.dumps(listed, ensure_ascii=False)
    assert str(scratch) not in blob
    assert "artifacts/preview" not in blob
