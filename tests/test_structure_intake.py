"""U5: what happens the moment a file lands — dedup, the reading, the report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "structure"))
import build_huachen_like as fixture  # noqa: E402


def _task(tmp_path: Path, actor: str = "manager"):
    task = TaskStore(tmp_path / "var").create(title="接入")
    return task, AnalysisStore(task), FinanceStore(task, actor=actor)


def _write(tmp_path: Path, data: bytes, name: str) -> Path:
    path = tmp_path / f"{name}.xlsx"
    path.write_bytes(data)
    return path


def test_ae10_the_same_file_twice_points_at_the_copy_already_filed(tmp_path: Path) -> None:
    _task_obj, analysis, _service = _task(tmp_path)
    path = _write(tmp_path, fixture.monthly_pack(), "八月")
    first = analysis.add_dataset(path, name="八月", metadata={"mode": "workbook"})
    again = analysis.add_dataset(path, name="八月再来一次", metadata={"mode": "workbook"})
    assert again["duplicate_of"] == first["id"]
    assert len(analysis.state()["datasets"]) == 1

    forced = analysis.add_dataset(
        path, name="另存一份", metadata={"mode": "workbook"}, allow_duplicate=True
    )
    assert "duplicate_of" not in forced
    assert forced["id"] != first["id"]
    assert len(analysis.state()["datasets"]) == 2


def test_a_derived_table_is_not_mistaken_for_a_second_upload(tmp_path: Path) -> None:
    _task_obj, analysis, service = _task(tmp_path)
    path = _write(tmp_path, fixture.monthly_pack(), "八月")
    shell = analysis.add_dataset(path, name="八月", metadata={"mode": "workbook"})
    service.structure_propose(shell["id"])
    proposal = service.structure_proposal_list({"dataset_id": shell["id"]})["proposals"][0]
    ledger = [sheet for sheet in proposal["sheets"] if sheet["sheet"].startswith("02")]
    service.structure_proposal_confirm({"dataset_id": shell["id"], "sheets": ledger})
    # The derived table carries the same bytes; it is the file seen through a
    # structure, not another upload of it.
    again = analysis.add_dataset(path, name="再来", metadata={"mode": "workbook"})
    assert again["duplicate_of"] == shell["id"]


def test_adding_a_workbook_reads_its_structure_at_once(tmp_path: Path) -> None:
    task, _analysis, _service = _task(tmp_path)
    path = _write(tmp_path, fixture.monthly_pack(), "八月")
    root = tmp_path / "var"
    assert (
        main(
            [
                "--var", str(root), "--task", task.id, "--actor", "manager",
                "dataset-add", "--path", str(path), "--name", "月结套表",
                "--meta", json.dumps({"mode": "workbook"}),
            ]
        )
        == 0
    )
    service = FinanceStore(task, actor="manager")
    proposals = service.structure_proposal_list({})["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["structure_state"] == "pending_confirmation"
    assert any(sheet["decision"] == "table" for sheet in proposals[0]["sheets"])


def test_a_file_with_nothing_tabular_in_it_ends_as_no_table(tmp_path: Path) -> None:
    from openpyxl import Workbook

    task, analysis, service = _task(tmp_path)
    book = Workbook()
    fixture.cover_sheet(book, "00·封面与编制说明")
    fixture.benchmark_sheet(book, "13·行业对标与假设")
    book.remove(book["Sheet"])
    path = tmp_path / "covers.xlsx"
    book.save(path)
    shell = analysis.add_dataset(path, name="只有封面", metadata={"mode": "workbook"})
    service.structure_propose(shell["id"])
    assert service.dataset_structure_state(shell["id"]) == "no_table"
    proposal = service.structure_proposal_list({"dataset_id": shell["id"]})["proposals"][0]
    assert all(sheet["decision"] == "excluded" for sheet in proposal["sheets"])
    assert all(sheet["reason"] for sheet in proposal["sheets"])


def test_readiness_waits_for_the_structure_before_naming_a_missing_field(
    tmp_path: Path,
) -> None:
    _task_obj, analysis, service = _task(tmp_path)
    path = _write(tmp_path, fixture.monthly_pack(), "八月")
    shell = analysis.add_dataset(path, name="八月", metadata={"mode": "workbook"})
    service.structure_propose(shell["id"])
    report = service.finance_readiness({})
    assert report["can_run"] == []
    assert [row["reason"] for row in report["blocked"]] == ["pending_structure"]
    assert report["structure_states"][shell["id"]] == "pending_confirmation"


def test_readiness_reads_the_confirmed_table_and_stops_probing_the_original(
    tmp_path: Path,
) -> None:
    _task_obj, analysis, service = _task(tmp_path)
    path = _write(tmp_path, fixture.monthly_pack(), "八月")
    shell = analysis.add_dataset(path, name="八月", metadata={"mode": "workbook"})
    service.structure_propose(shell["id"])
    proposal = service.structure_proposal_list({"dataset_id": shell["id"]})["proposals"][0]
    ledger = [sheet for sheet in proposal["sheets"] if sheet["sheet"].startswith("02")]
    confirmation = service.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": ledger}
    )
    report = service.finance_readiness({})
    assert not any(row["reason"] == "pending_structure" for row in report["blocked"])
    assert report["structure_states"][shell["id"]] == "confirmed"
    snapshot = next(iter(confirmation["snapshot_ids"].values()))
    assert report["structure_states"][snapshot] == "confirmed"
    # The derived table starts at the header row, so the title line carrying
    # 「2026年08月 | 单位：元」 is not in its rows. The confirmation kept it, and
    # that is what the report answers with. Currency was never stated anywhere.
    assert report["proposed_scope"]["period"] == "2026-08"
    assert report["proposed_scope"]["unit"] == "元"
    assert report["proposed_scope"]["currency"] == ""
    # And the file answers for itself, by name.
    entry = next(row for row in report["datasets"] if row["dataset_id"] == snapshot)
    assert entry["scope"]["period"] == "2026-08"
    assert entry["missing_fields"] == ["currency"]


def test_the_context_list_shows_the_same_state_the_card_does(tmp_path: Path) -> None:
    _task_obj, analysis, service = _task(tmp_path)
    path = _write(tmp_path, fixture.monthly_pack(), "八月")
    shell = analysis.add_dataset(path, name="八月", metadata={"mode": "workbook"})
    service.structure_propose(shell["id"])
    listed = {row["id"]: row for row in service.list_finance_context()["datasets"]}
    assert listed[shell["id"]]["structure_state"] == "pending_confirmation"


def test_a_csv_never_enters_the_flow_and_says_so(tmp_path: Path) -> None:
    _task_obj, analysis, service = _task(tmp_path)
    path = tmp_path / "rows.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    dataset = analysis.add_dataset(path, name="csv")
    assert service.structure_propose(dataset["id"]) is None
    assert service.dataset_structure_state(dataset["id"]) == "not_applicable"
    report = service.finance_readiness({})
    assert report["structure_states"][dataset["id"]] == "not_applicable"


def _sheets(service: FinanceStore, shell_id: str) -> list[dict]:
    return service.structure_proposal_list({"dataset_id": shell_id})["proposals"][0]["sheets"]


def test_handing_back_the_whole_proposal_is_refused_rather_than_trimmed(
    tmp_path: Path,
) -> None:
    """A caller who sends every sheet is told which one cannot be read.

    Quietly dropping the unreadable sheet would confirm something other than
    what was asked for, and nothing would say so.
    """
    _task_obj, analysis, service = _task(tmp_path)
    shell = analysis.add_dataset(
        _write(tmp_path, fixture.monthly_pack(), "八月"), name="八月", metadata={"mode": "workbook"}
    )
    service.structure_propose(shell["id"])
    with pytest.raises(FoundryError, match="cannot confirm 10·区域经营损益表"):
        service.structure_proposal_confirm(
            {"dataset_id": shell["id"], "sheets": _sheets(service, shell["id"])}
        )
    assert service.dataset_structure_state(shell["id"]) == "pending_confirmation"


def test_the_sheets_the_card_offers_confirm_in_one_go(tmp_path: Path) -> None:
    """What the card actually sends: every table it was allowed to offer."""
    _task_obj, analysis, service = _task(tmp_path)
    shell = analysis.add_dataset(
        _write(tmp_path, fixture.monthly_pack(), "八月"), name="八月", metadata={"mode": "workbook"}
    )
    service.structure_propose(shell["id"])
    offered = [
        sheet
        for sheet in _sheets(service, shell["id"])
        if sheet["decision"] == "table" and not sheet["blocked_reason"]
    ]
    record = service.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": offered}
    )
    assert "02·GL科目余额表" in record["snapshot_ids"]
    assert "10·区域经营损益表" not in record["snapshot_ids"]
    assert service.dataset_structure_state(shell["id"]) == "confirmed"


def test_a_declaration_that_can_yield_nothing_is_refused_by_name(tmp_path: Path) -> None:
    """A hand-edited or tool-composed declaration never reaches the builder.

    The card will not offer an unreadable sheet, but a declaration also arrives
    through the tool call, where nothing passed the engine first.
    """
    _task_obj, analysis, service = _task(tmp_path)
    shell = analysis.add_dataset(
        _write(tmp_path, fixture.monthly_pack(), "八月"), name="八月", metadata={"mode": "workbook"}
    )
    service.structure_propose(shell["id"])
    sheets = [s for s in _sheets(service, shell["id"]) if s["sheet"].startswith(("02", "03"))]
    blinded = dict(sheets[1])
    blinded["columns"] = [{**c, "role": "unknown"} for c in blinded["columns"]]
    blinded["amount_pairs"] = []

    with pytest.raises(FoundryError, match="cannot confirm 03·GL月结分录清单"):
        service.structure_proposal_confirm(
            {"dataset_id": shell["id"], "sheets": [sheets[0], blinded]}
        )
    # Refused as one act: the sheet ahead of it in the list was not written.
    assert service.dataset_structure_state(shell["id"]) == "pending_confirmation"
    assert not service.structure_confirmation_list({"dataset_id": shell["id"]})["confirmations"]
