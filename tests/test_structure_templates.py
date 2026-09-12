"""U4: a confirmed structure is remembered, matched, and demoted when withdrawn."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.structure_proposal import propose_workbook_structure
from foundry.structure_templates import (
    MATCH_THRESHOLD,
    differences,
    registry_for,
    similarity,
)
from foundry.task import TaskStore

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "structure"))
import build_huachen_like as fixture  # noqa: E402


def _task(tmp_path: Path, actor: str = "manager", *, store=None, period=None):
    tasks = store or TaskStore(tmp_path / "var")
    task = tasks.create(title="模板", period=period)
    return task, AnalysisStore(task), FinanceStore(task, actor=actor)


def _add(analysis: AnalysisStore, tmp_path: Path, data: bytes, name: str) -> dict:
    path = tmp_path / f"{name}.xlsx"
    path.write_bytes(data)
    return analysis.add_dataset(path, name=name, metadata={"mode": "workbook"})


def _ledger(service: FinanceStore, shell_id: str) -> list[dict]:
    proposal = service.structure_proposal_list({"dataset_id": shell_id})["proposals"][0]
    return [sheet for sheet in proposal["sheets"] if sheet["sheet"].startswith("02")]


def _confirm_august(tmp_path: Path, *, store=None, period=None):
    task, analysis, service = _task(tmp_path, store=store, period=period)
    shell = _add(analysis, tmp_path, fixture.monthly_pack(), "八月")
    service.structure_propose(shell["id"])
    service.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": _ledger(service, shell["id"])}
    )
    return task, analysis, service


def test_ae8_next_months_file_applies_the_remembered_structure(tmp_path: Path) -> None:
    task, analysis, service = _confirm_august(tmp_path)
    templates = service.structure_template_list({})["templates"]
    assert [item["weight"] for item in templates] == [1]

    september = _add(analysis, tmp_path, fixture.monthly_pack(period="2026年09月"), "九月")
    proposal = service.structure_propose(september["id"])
    matches = {item["sheet"]: item for item in proposal["template_matches"]}
    ledger_match = matches["02·GL科目余额表"]
    assert ledger_match["score"] >= MATCH_THRESHOLD
    assert ledger_match["differences"] == []
    assert ledger_match["auto_apply"] is True

    # A remembered shape applies without a card, and says so.
    state = service.dataset_structure_state(september["id"])
    assert state == "pending_acknowledgement"
    confirmation = next(
        row
        for row in service.structure_confirmation_list({"dataset_id": september["id"]})[
            "confirmations"
        ]
        if row["state"] == "pending_acknowledgement"
    )
    assert confirmation["source"] == "template"
    assert confirmation["triggered_by_actor"] == "manager"


def test_ae8_withdrawing_a_template_application_returns_the_card_and_demotes(
    tmp_path: Path,
) -> None:
    task, analysis, service = _confirm_august(tmp_path)
    september = _add(analysis, tmp_path, fixture.monthly_pack(period="2026年09月"), "九月")
    service.structure_propose(september["id"])
    applied = next(
        row
        for row in service.structure_confirmation_list({"dataset_id": september["id"]})[
            "confirmations"
        ]
        if row["source"] == "template"
    )
    service.structure_withdraw({"id": applied["id"]})
    assert service.dataset_structure_state(september["id"]) == "pending_confirmation"
    ledger_template = next(
        item
        for item in service.structure_template_list({})["templates"]
        if item["sheet"].startswith("02")
    )
    assert ledger_template["weight"] == 0
    assert ledger_template["disabled"] is True


def test_an_extra_column_falls_below_the_threshold(tmp_path: Path) -> None:
    _task_obj, analysis, service = _confirm_august(tmp_path)
    template = next(
        row
        for row in registry_for(service).list()
        if row["sheet"].startswith("02")
    )
    stored = {**template["declaration"], "sheet": template["sheet"]}
    widened = {
        **stored,
        "columns": [
            *stored["columns"],
            {"letter": "K", "header": "备注", "display": "备注", "role": "unknown"},
            {"letter": "L", "header": "审核人", "display": "审核人", "role": "unknown"},
            {"letter": "M", "header": "复核人", "display": "复核人", "role": "unknown"},
        ],
    }
    assert similarity(widened, template) < MATCH_THRESHOLD


def test_the_same_columns_in_another_order_match_but_differ(tmp_path: Path) -> None:
    _task_obj, _analysis, service = _confirm_august(tmp_path)
    template = next(
        row
        for row in registry_for(service).list()
        if row["sheet"].startswith("02")
    )
    stored = {**template["declaration"], "sheet": template["sheet"]}
    reordered = {**stored, "columns": _swap(stored["columns"], 0, 1)}
    assert similarity(reordered, template) >= MATCH_THRESHOLD
    assert "roles" in differences(reordered, template)


def _swap(columns: list[dict], left: int, right: int) -> list[dict]:
    moved = list(columns)
    moved[left], moved[right] = moved[right], moved[left]
    return moved


def test_a_wholly_rearranged_sheet_is_not_the_remembered_table(tmp_path: Path) -> None:
    _task_obj, _analysis, service = _confirm_august(tmp_path)
    template = next(
        row
        for row in registry_for(service).list()
        if row["sheet"].startswith("02")
    )
    stored = {**template["declaration"], "sheet": template["sheet"]}
    reversed_columns = {**stored, "columns": list(reversed(stored["columns"]))}
    # Same labels in a different layout is a different table, not a near miss.
    assert similarity(reversed_columns, template) < MATCH_THRESHOLD


def test_a_reordered_sheet_returns_to_the_card_pre_filled(tmp_path: Path) -> None:
    task, analysis, service = _confirm_august(tmp_path)
    data = fixture.monthly_pack(period="2026年09月")
    proposed = propose_workbook_structure(data)["sheets"]
    ledger = next(sheet for sheet in proposed if sheet["sheet"].startswith("02"))
    ledger["columns"] = _swap(ledger["columns"], 0, 1)
    from foundry.structure_templates import apply_matching_templates

    template = next(
        row for row in registry_for(service).list() if row["sheet"].startswith("02")
    )
    prepared, matches = apply_matching_templates(service, [ledger])
    match = matches[0]
    assert match["differences"]
    assert match["auto_apply"] is False
    # The card opens on this month's sheet, holding the remembered column roles.
    prefill = prepared[0]["prefill"]
    assert prepared[0]["sheet"].startswith("02")
    assert [column["role"] for column in prefill["columns"]] == [
        column["role"] for column in template["declaration"]["columns"]
    ]
    # Nothing from August's file rides along.
    assert "preview" not in prefill
    assert "scope_hints" not in prefill


def test_a_disabled_template_stops_matching(tmp_path: Path) -> None:
    task, analysis, service = _confirm_august(tmp_path)
    for template in service.structure_template_list({})["templates"]:
        service.structure_template_disable({"id": template["id"]})
    september = _add(analysis, tmp_path, fixture.monthly_pack(period="2026年09月"), "九月")
    proposal = service.structure_propose(september["id"])
    assert proposal["template_matches"] == []
    assert service.dataset_structure_state(september["id"]) == "pending_confirmation"


def test_the_template_list_carries_no_path_or_bytes(tmp_path: Path) -> None:
    _task_obj, _analysis, service = _confirm_august(tmp_path)
    listed = service.structure_template_list({})["templates"]
    assert listed
    for item in listed:
        assert set(item) == {
            "id",
            "signature",
            "sheet_pattern",
            "weight",
            "disabled",
            "sheet",
            "columns",
        }
        assert "/" not in str(item)
        assert "declaration" not in item


def test_only_the_manager_disables_a_template(tmp_path: Path) -> None:
    task, _analysis, service = _confirm_august(tmp_path)
    assistant = FinanceStore(task, actor="assistant")
    template = assistant.structure_template_list({})["templates"][0]
    with pytest.raises(FoundryError, match="only the manager"):
        assistant.structure_template_disable({"id": template["id"]})


def test_acknowledging_the_same_shape_raises_its_weight_rather_than_duplicating(
    tmp_path: Path,
) -> None:
    task, analysis, service = _confirm_august(tmp_path)
    september = _add(analysis, tmp_path, fixture.monthly_pack(period="2026年09月"), "九月")
    service.structure_propose(september["id"])
    applied = next(
        row
        for row in service.structure_confirmation_list({"dataset_id": september["id"]})[
            "confirmations"
        ]
        if row["source"] == "template"
    )
    service.structure_acknowledge({"id": applied["id"]})
    ledgers = [
        item
        for item in service.structure_template_list({})["templates"]
        if item["sheet"].startswith("02")
    ]
    assert len(ledgers) == 1
    assert ledgers[0]["weight"] == 2


def test_ae8_a_later_period_task_applies_what_august_confirmed(tmp_path: Path) -> None:
    """The whole point of remembering: a task is one period, the shelf is not.

    August and September close in separate tasks, so a registry kept under the
    task would hand September an empty shelf and the manager would confirm the
    same workbook twice. The template has to outlive the task that made it.
    """
    tasks = TaskStore(tmp_path / "var")
    _august, _august_analysis, august = _confirm_august(
        tmp_path, store=tasks, period="2026-08"
    )
    assert [item["weight"] for item in august.structure_template_list({})["templates"]] == [1]

    _september, september_analysis, september = _task(
        tmp_path, store=tasks, period="2026-09"
    )
    # A fresh task has confirmed nothing of its own, and still knows the shape.
    assert september.structure_template_list({})["templates"]

    pack = _add(
        september_analysis, tmp_path, fixture.monthly_pack(period="2026年09月"), "九月台账"
    )
    proposal = september.structure_propose(pack["id"])
    ledger_match = next(
        item
        for item in proposal["template_matches"]
        if item["sheet"] == "02·GL科目余额表"
    )
    assert ledger_match["score"] >= MATCH_THRESHOLD
    assert ledger_match["auto_apply"] is True
    assert september.dataset_structure_state(pack["id"]) == "pending_acknowledgement"
    applied = next(
        row
        for row in september.structure_confirmation_list({"dataset_id": pack["id"]})[
            "confirmations"
        ]
        if row["state"] == "pending_acknowledgement"
    )
    assert applied["source"] == "template"


def test_acknowledging_in_the_later_task_raises_the_same_record(tmp_path: Path) -> None:
    tasks = TaskStore(tmp_path / "var")
    _august, _aa, august = _confirm_august(tmp_path, store=tasks, period="2026-08")
    ledger_id = next(
        item["id"]
        for item in august.structure_template_list({})["templates"]
        if item["sheet"].startswith("02")
    )

    _september, september_analysis, september = _task(
        tmp_path, store=tasks, period="2026-09"
    )
    pack = _add(
        september_analysis, tmp_path, fixture.monthly_pack(period="2026年09月"), "九月台账"
    )
    september.structure_propose(pack["id"])
    applied = next(
        row
        for row in september.structure_confirmation_list({"dataset_id": pack["id"]})[
            "confirmations"
        ]
        if row["source"] == "template"
    )
    september.structure_acknowledge({"id": applied["id"]})

    ledgers = [
        item
        for item in september.structure_template_list({})["templates"]
        if item["sheet"].startswith("02")
    ]
    assert len(ledgers) == 1
    assert ledgers[0]["id"] == ledger_id
    assert ledgers[0]["weight"] == 2
    # August's own view is the same shelf, not a copy of it.
    assert august.structure_template_list({})["templates"] == (
        september.structure_template_list({})["templates"]
    )


def test_another_var_root_starts_with_an_empty_shelf(tmp_path: Path) -> None:
    """One var root is one tenant. Shapes do not travel between roots."""
    _task_obj, _analysis, mine = _confirm_august(tmp_path)
    assert mine.structure_template_list({})["templates"]

    _theirs, _their_analysis, theirs = _task(tmp_path / "elsewhere")
    assert theirs.structure_template_list({})["templates"] == []


def test_a_template_withdrawn_in_one_task_stops_matching_in_the_next(
    tmp_path: Path,
) -> None:
    tasks = TaskStore(tmp_path / "var")
    _august, august_analysis, august = _confirm_august(
        tmp_path, store=tasks, period="2026-08"
    )
    revision = _add(
        august_analysis, tmp_path, fixture.monthly_pack(period="2026年09月"), "九月复核"
    )
    august.structure_propose(revision["id"])
    applied = next(
        row
        for row in august.structure_confirmation_list({"dataset_id": revision["id"]})[
            "confirmations"
        ]
        if row["source"] == "template"
    )
    august.structure_withdraw({"id": applied["id"]})

    _october, october_analysis, october = _task(tmp_path, store=tasks, period="2026-10")
    pack = _add(
        october_analysis, tmp_path, fixture.monthly_pack(period="2026年10月"), "十月台账"
    )
    proposal = october.structure_propose(pack["id"])
    assert not [
        item
        for item in proposal["template_matches"]
        if item["sheet"] == "02·GL科目余额表"
    ]
    assert october.dataset_structure_state(pack["id"]) == "pending_confirmation"


def test_two_tasks_demoting_at_once_both_land(tmp_path: Path) -> None:
    """The shelf outlives the task, so two periods can reach it at once."""
    import threading

    tasks = TaskStore(tmp_path / "var")
    _august, _aa, august = _confirm_august(tmp_path, store=tasks, period="2026-08")
    ledger = next(
        row for row in registry_for(august).list() if row["sheet"].startswith("02")
    )
    shelf = registry_for(august)
    for _ in range(6):
        shelf.adjust(ledger["id"], +1, 8)
    assert shelf.read(ledger["id"])["weight"] == 7

    barrier = threading.Barrier(4)

    def demote() -> None:
        barrier.wait()
        shelf.adjust(ledger["id"], -1, 8)

    threads = [threading.Thread(target=demote) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Four withdrawals are four steps down, not one.
    assert shelf.read(ledger["id"])["weight"] == 3
