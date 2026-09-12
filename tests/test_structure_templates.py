"""U4: a confirmed structure is remembered, matched, and demoted when withdrawn."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.structure_proposal import propose_workbook_structure
from foundry.structure_templates import MATCH_THRESHOLD, differences, similarity
from foundry.task import TaskStore

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "structure"))
import build_huachen_like as fixture  # noqa: E402


def _task(tmp_path: Path, actor: str = "manager"):
    task = TaskStore(tmp_path / "var").create(title="模板")
    return task, AnalysisStore(task), FinanceStore(task, actor=actor)


def _add(analysis: AnalysisStore, tmp_path: Path, data: bytes, name: str) -> dict:
    path = tmp_path / f"{name}.xlsx"
    path.write_bytes(data)
    return analysis.add_dataset(path, name=name, metadata={"mode": "workbook"})


def _ledger(service: FinanceStore, shell_id: str) -> list[dict]:
    proposal = service.structure_proposal_list({"dataset_id": shell_id})["proposals"][0]
    return [sheet for sheet in proposal["sheets"] if sheet["sheet"].startswith("02")]


def _confirm_august(tmp_path: Path):
    task, analysis, service = _task(tmp_path)
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
        for row in service._list("structure_templates")
        if row["declaration"]["sheet"].startswith("02")
    )
    stored = template["declaration"]
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
        for row in service._list("structure_templates")
        if row["declaration"]["sheet"].startswith("02")
    )
    stored = template["declaration"]
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
        for row in service._list("structure_templates")
        if row["declaration"]["sheet"].startswith("02")
    )
    stored = template["declaration"]
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

    prepared, matches = apply_matching_templates(service, [ledger])
    match = matches[0]
    assert match["differences"]
    assert match["auto_apply"] is False
    assert prepared[0]["prefill"]["sheet"].startswith("02")


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
