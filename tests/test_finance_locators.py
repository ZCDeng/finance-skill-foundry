from __future__ import annotations

import csv
from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_locators import build_source_locator, stage_source_locator_preview
from foundry.finance_model import normalize_finance_dataset
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


def _expense_xlsx(path: Path) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "费用"
    sheet["D1"] = "amount"
    sheet["E1"] = "period"
    sheet["F1"] = "currency"
    sheet["G1"] = "unit"
    sheet["H1"] = "management_account"
    sheet["I1"] = "ledger"
    sheet["J1"] = "organization"
    sheet["K1"] = "scenario"
    rows = [
        (2, 120, "revenue"),
        (3, 70, "cost"),
        (18, 20, "expense"),
    ]
    for excel_row, amount, account in rows:
        sheet[f"D{excel_row}"] = amount
        sheet[f"E{excel_row}"] = "2026-08"
        sheet[f"F{excel_row}"] = "CNY"
        sheet[f"G{excel_row}"] = "万元"
        sheet[f"H{excel_row}"] = account
        sheet[f"I{excel_row}"] = "service-co"
        sheet[f"J{excel_row}"] = "华东"
        sheet[f"K{excel_row}"] = "actual"
    book.save(path)
    return path


def _finance(tmp_path: Path, source: Path, *, metadata: dict | None = None):
    task = TaskStore(tmp_path / "var").create(title="定位")
    analysis = AnalysisStore(task)
    dataset = analysis.add_dataset(source, name="g1", metadata=metadata)
    service = FinanceStore(task)
    context = service.save_context(
        {
            "bindings": {"actual": dataset["id"]},
            "scopes": {"actual": SCOPE},
        }
    )
    return service, context, dataset


def test_cf06_xlsx_expense_locator_uses_header_cell_column(tmp_path):
    path = _expense_xlsx(tmp_path / "g1.xlsx")
    service, _context, dataset = _finance(tmp_path, path, metadata={"sheet": "费用", "mode": "table"})
    loaded = service.analysis.read_dataset(dataset["id"])
    result = normalize_finance_dataset(loaded, SCOPE)
    expense = next(row for row in result["rows"] if row["management_account"] == "expense")
    locator = expense["source_locator"]
    assert locator["dataset_id"] == dataset["id"]
    assert locator["sheet"] == "费用"
    assert locator["excel_range"] == "费用!D18"
    assert locator["source_hash"] == dataset["source_hash"]
    assert locator["kind"] == "xlsx"
    blob = str(locator)
    assert "/" not in blob
    assert "file://" not in blob


def test_cf06_row_numbers_alone_do_not_invent_excel_range():
    locator = build_source_locator(
        {
            "id": "snap",
            "source_hash": "abc",
            "source_file": "source.xlsx",
            "transformation": {
                "format": "xlsx",
                "sheet": "费用",
                "source_row_numbers": [18],
            },
        },
        18,
    )
    assert locator["sheet"] == "费用"
    assert locator["source_row"] == 18
    assert "excel_range" not in locator


def test_cf08_csv_locator_has_empty_sheet(tmp_path):
    rows = [
        row
        for row in _g1_rows()
        if row["period"] == "2026-08" and row["organization"] == "华东" and row["scenario"] == "actual"
    ]
    path = _write_csv(tmp_path / "g1.csv", rows)
    service, _context, dataset = _finance(tmp_path, path)
    loaded = service.analysis.read_dataset(dataset["id"])
    result = normalize_finance_dataset(loaded, SCOPE)
    expense = next(row for row in result["rows"] if row["management_account"] == "expense")
    locator = expense["source_locator"]
    assert locator["sheet"] == ""
    assert locator["kind"] == "csv"
    assert locator.get("preview_available") is True
    assert "excel_range" not in locator
    assert locator["source_row"]


def test_cf09_pdf_without_report_source_does_not_invent_page():
    locator = build_source_locator(
        {
            "id": "pdf-1",
            "source_hash": "deadbeef",
            "source_file": "source.pdf",
            "transformation": {"format": "pdf"},
        },
        1,
        report_source_ids=set(),
    )
    assert locator["preview_available"] is False
    assert locator.get("page") in (None, "", False) or "page" not in locator
    assert "page" not in locator


def test_cf10_missing_locator_is_unavailable(tmp_path, monkeypatch):
    path = _expense_xlsx(tmp_path / "g1.xlsx")
    service, context, _dataset = _finance(tmp_path, path, metadata={"sheet": "费用", "mode": "table"})
    run = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    stripped = {
        **run,
        "result": {
            **run["result"],
            "rows": [
                {
                    **run["result"]["rows"][0],
                    "source_rows": [
                        {key: value for key, value in ref.items() if key != "source_locator"}
                        for ref in run["result"]["rows"][0]["source_rows"]
                    ],
                    "evidence": {
                        column: [
                            {key: value for key, value in ref.items() if key != "source_locator"}
                            for ref in refs
                        ]
                        for column, refs in run["result"]["rows"][0]["evidence"].items()
                    },
                }
            ],
        },
    }
    monkeypatch.setattr(service.analysis, "get_run", lambda _run_id: stripped)
    opened = service.open_source_locator(
        {"run_id": run["id"], "row": 0, "column": "expense"}
    )
    assert opened["status"] == "locator_unavailable"


def test_cf10f_foreign_or_unauthorized_locator_is_forbidden(tmp_path):
    path = _expense_xlsx(tmp_path / "g1.xlsx")
    service, context, dataset = _finance(tmp_path, path, metadata={"sheet": "费用", "mode": "table"})
    run = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    fact_id = next(
        fact["id"]
        for fact in prepared["facts"]
        if fact.get("column") == "expense"
    )
    child = FinanceStore(service.task, snapshot_ids=["not-the-dataset"])
    by_run = child.open_source_locator({"run_id": run["id"], "row": 0, "column": "expense"})
    by_fact = child.open_source_locator({"fact_id": fact_id})
    assert by_run["status"] == "locator_forbidden"
    assert by_fact["status"] == "locator_forbidden"
    blob = str(by_run) + str(by_fact)
    assert "/" not in blob or "locator_forbidden" in blob
    assert dataset["id"] not in str(by_run.get("locator") or {})

    other = TaskStore(tmp_path / "other").create(title="外人")
    foreign = FinanceStore(other)
    assert foreign.open_source_locator({"run_id": run["id"], "row": 0, "column": "expense"})[
        "status"
    ] == "locator_forbidden"


def test_open_source_locator_returns_path_free_preview_handle(tmp_path):
    path = _expense_xlsx(tmp_path / "g1.xlsx")
    service, context, dataset = _finance(tmp_path, path, metadata={"sheet": "费用", "mode": "table"})
    run = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    opened = service.open_source_locator({"run_id": run["id"], "row": 0, "column": "expense"})
    assert opened["status"] == "ok"
    assert opened["locator"]["excel_range"] == "费用!D18"
    assert opened["locator"]["source_hash"] == dataset["source_hash"]
    assert opened["preview"]["available"] is True
    assert opened["preview"]["handle"]
    blob = str(opened)
    assert "file://" not in blob
    assert str(path) not in blob


def test_open_source_locator_rejects_path_arguments(tmp_path):
    path = _expense_xlsx(tmp_path / "g1.xlsx")
    service, context, dataset = _finance(tmp_path, path, metadata={"sheet": "费用", "mode": "table"})
    run = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    with pytest.raises(FoundryError):
        service.open_source_locator(
            {"run_id": run["id"], "row": 0, "column": "expense", "dataset_id": dataset["id"]}
        )
    with pytest.raises(FoundryError):
        service.open_source_locator({"path": str(path)})


def test_stage_preview_copies_xlsx_into_digest_scratch_not_analysis(tmp_path):
    path = _expense_xlsx(tmp_path / "g1.xlsx")
    service, context, dataset = _finance(tmp_path, path, metadata={"sheet": "费用", "mode": "table"})
    run = service.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    dest = stage_source_locator_preview(
        service, {"run_id": run["id"], "row": 0, "column": "expense"}
    )
    digest = dataset["source_hash"]
    scratch = service.task.artifacts_dir / "preview" / digest
    assert dest.parent == scratch
    assert dest.name == f"{digest}.xlsx"
    assert dest.read_bytes() == path.read_bytes()
    assert scratch.resolve() not in service.analysis.root.resolve().parents
    assert service.analysis.root.resolve() not in dest.resolve().parents
    with pytest.raises(FoundryError):
        stage_source_locator_preview(
            service, {"run_id": run["id"], "row": 0, "column": "expense", "path": str(path)}
        )

