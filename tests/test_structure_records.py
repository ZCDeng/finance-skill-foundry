"""U3: who confirmed a structure, what that lets them do, and what it leaves open."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.structure_records import resolve_source
from foundry.task import TaskStore

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "structure"))
import build_huachen_like as fixture  # noqa: E402

SCOPE = {
    "ledger": "华宸物业",
    "organization": "集团合并",
    "period": "2026-08",
    "currency": "CNY",
    "unit": "元",
    "scenario": "actual",
}


def _setup(tmp_path: Path, *, actor: str = "manager"):
    task = TaskStore(tmp_path / "var").create(title="结构确认")
    analysis = AnalysisStore(task)
    path = tmp_path / "pack.xlsx"
    path.write_bytes(fixture.monthly_pack())
    shell = analysis.add_dataset(path, name="月结套表", metadata={"mode": "workbook"})
    service = FinanceStore(task, actor=actor)
    service.structure_propose(shell["id"])
    return task, analysis, service, shell


def _ledger_sheets(service: FinanceStore, shell_id: str) -> list[dict]:
    proposal = service.structure_proposal_list({"dataset_id": shell_id})["proposals"][0]
    return [sheet for sheet in proposal["sheets"] if sheet["sheet"].startswith("02")]


def test_ae6_an_unconfirmed_shell_cannot_be_bound_to_a_context(tmp_path: Path) -> None:
    _task, _analysis, service, shell = _setup(tmp_path)
    assert service.dataset_structure_state(shell["id"]) == "pending_confirmation"
    with pytest.raises(FoundryError, match="pending_structure"):
        service.save_context(
            {"bindings": {"actual": shell["id"]}, "scopes": {"actual": SCOPE}}
        )


def test_ae7_an_assistant_confirmation_waits_for_the_manager(tmp_path: Path) -> None:
    task, _analysis, manager, shell = _setup(tmp_path)
    assistant = FinanceStore(task, actor="assistant")
    sheets = _ledger_sheets(assistant, shell["id"])
    confirmation = assistant.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": sheets}
    )
    assert confirmation["source"] == "assistant"
    assert confirmation["state"] == "pending_acknowledgement"
    assert manager.dataset_structure_state(shell["id"]) == "pending_acknowledgement"

    snapshot = next(iter(confirmation["snapshot_ids"].values()))
    context = manager.save_context(
        {"bindings": {"actual": snapshot}, "scopes": {"actual": SCOPE}}
    )
    run = manager.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )

    before = manager.analysis.get_run(run["id"])
    acknowledged = manager.structure_acknowledge({"id": confirmation["id"]})
    assert acknowledged["state"] == "acknowledged"
    assert acknowledged["parent_id"] == confirmation["id"]
    assert manager.dataset_structure_state(shell["id"]) == "confirmed"
    # Acknowledging settles provenance; it never reruns anything.
    after = manager.analysis.get_run(run["id"])
    assert after["output_hash"] == before["output_hash"]
    assert after["bindings"] == before["bindings"]


def test_an_unstamped_call_is_recorded_as_the_assistant(tmp_path: Path) -> None:
    task, _analysis, manager, shell = _setup(tmp_path)
    unstamped = FinanceStore(task)
    assert unstamped.actor == "assistant"
    confirmation = unstamped.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": _ledger_sheets(unstamped, shell["id"])}
    )
    assert confirmation["source"] == "assistant"
    assert confirmation["state"] == "pending_acknowledgement"


def test_a_request_cannot_claim_its_own_provenance(tmp_path: Path) -> None:
    task, _analysis, _manager, shell = _setup(tmp_path)
    assistant = FinanceStore(task, actor="assistant")
    confirmation = assistant.structure_proposal_confirm(
        {
            "dataset_id": shell["id"],
            "sheets": _ledger_sheets(assistant, shell["id"]),
            "source": "manager",
            "confirmed_by": "manager",
        }
    )
    assert confirmation["source"] == "assistant"
    assert any(
        item["code"] == "claimed_source_stripped"
        for item in confirmation.get("diagnostics") or []
    )
    assert resolve_source(None) == "assistant"


def test_a_confirmation_request_cannot_carry_a_path_or_bytes(tmp_path: Path) -> None:
    _task, _analysis, service, shell = _setup(tmp_path)
    for forbidden in ({"path": "/tmp/x.xlsx"}, {"bytes": "UEs="}, {"url": "http://x"}):
        with pytest.raises(FoundryError, match="path, URL or workbook bytes"):
            service.structure_proposal_confirm({"dataset_id": shell["id"], **forbidden})


def test_a_stale_proposal_revision_is_refused(tmp_path: Path) -> None:
    _task, _analysis, service, shell = _setup(tmp_path)
    sheets = _ledger_sheets(service, shell["id"])
    service.structure_propose(shell["id"])  # a second read moves the revision on
    with pytest.raises(FoundryError, match="moved on"):
        service.structure_proposal_confirm(
            {"dataset_id": shell["id"], "sheets": sheets, "revision": 1}
        )


def test_an_undecided_debit_credit_side_blocks_confirmation(tmp_path: Path) -> None:
    task = TaskStore(tmp_path / "var").create(title="未定方向")
    analysis = AnalysisStore(task)
    path = tmp_path / "nocat.xlsx"
    path.write_bytes(fixture.no_category_ledger())
    shell = analysis.add_dataset(path, name="余额表", metadata={"mode": "workbook"})
    service = FinanceStore(task, actor="manager")
    service.structure_propose(shell["id"])
    with pytest.raises(FoundryError, match="debit/credit side"):
        service.structure_proposal_confirm({"dataset_id": shell["id"]})


def test_a_narrow_session_can_read_the_table_it_just_confirmed(tmp_path: Path) -> None:
    task, _analysis, _manager, shell = _setup(tmp_path)
    session = task.open_session(seat="analysis") if hasattr(task, "open_session") else None
    narrow = FinanceStore(task, snapshot_ids=[shell["id"]], actor="assistant")
    confirmation = narrow.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": _ledger_sheets(narrow, shell["id"])}
    )
    snapshot = next(iter(confirmation["snapshot_ids"].values()))
    assert snapshot in narrow.allowed
    assert narrow.dataset_structure_state(snapshot) == "pending_acknowledgement"
    del session


def test_a_session_cannot_confirm_a_shell_outside_its_own_scope(tmp_path: Path) -> None:
    task, _analysis, _manager, shell = _setup(tmp_path)
    stranger = FinanceStore(task, snapshot_ids=[], actor="assistant")
    with pytest.raises(FoundryError, match="outside this session context"):
        stranger.structure_proposal_confirm({"dataset_id": shell["id"]})
    with pytest.raises(FoundryError, match="outside this session context"):
        stranger.structure_proposal_list({"dataset_id": shell["id"]})


def test_rejecting_an_assistant_confirmation_returns_the_file_to_the_card(
    tmp_path: Path,
) -> None:
    task, _analysis, manager, shell = _setup(tmp_path)
    assistant = FinanceStore(task, actor="assistant")
    confirmation = assistant.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": _ledger_sheets(assistant, shell["id"])}
    )
    snapshot = next(iter(confirmation["snapshot_ids"].values()))
    rejected = manager.structure_reject({"id": confirmation["id"]})
    assert rejected["state"] == "withdrawn"
    assert rejected["parent_id"] == confirmation["id"]
    assert manager.dataset_structure_state(shell["id"]) == "pending_confirmation"
    # The table is not deleted; it is marked, so runs that used it still explain.
    assert manager.dataset_structure_state(snapshot) == "withdrawn"
    assert manager.analysis.read_dataset(snapshot)["id"] == snapshot


def test_only_the_manager_settles_a_confirmation(tmp_path: Path) -> None:
    task, _analysis, _manager, shell = _setup(tmp_path)
    assistant = FinanceStore(task, actor="assistant")
    confirmation = assistant.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": _ledger_sheets(assistant, shell["id"])}
    )
    for call in (assistant.structure_acknowledge, assistant.structure_reject):
        with pytest.raises(FoundryError, match="only the manager"):
            call({"id": confirmation["id"]})


def test_a_second_confirmation_is_refused_while_one_is_in_force(tmp_path: Path) -> None:
    _task, _analysis, service, shell = _setup(tmp_path)
    sheets = _ledger_sheets(service, shell["id"])
    service.structure_proposal_confirm({"dataset_id": shell["id"], "sheets": sheets})
    with pytest.raises(FoundryError, match="already has a confirmed table structure"):
        service.structure_proposal_confirm({"dataset_id": shell["id"], "sheets": sheets})


def test_a_sheet_the_proposal_never_offered_is_refused(tmp_path: Path) -> None:
    _task, _analysis, service, shell = _setup(tmp_path)
    sheets = _ledger_sheets(service, shell["id"])
    invented = [{**sheets[0], "sheet": "凭空捏造的表"}]
    with pytest.raises(FoundryError, match="not in the proposal"):
        service.structure_proposal_confirm({"dataset_id": shell["id"], "sheets": invented})


def test_a_table_dataset_outside_the_flow_stays_bindable(tmp_path: Path) -> None:
    task = TaskStore(tmp_path / "var").create(title="CSV")
    analysis = AnalysisStore(task)
    path = tmp_path / "rows.csv"
    path.write_text(
        "ledger,organization,period,currency,unit,scenario,management_account,amount\n"
        "华宸物业,集团合并,2026-08,CNY,元,actual,revenue,120\n",
        encoding="utf-8",
    )
    dataset = analysis.add_dataset(path, name="csv")
    service = FinanceStore(task, actor="manager")
    assert service.dataset_structure_state(dataset["id"]) == "not_applicable"
    context = service.save_context(
        {"bindings": {"actual": dataset["id"]}, "scopes": {"actual": SCOPE}}
    )
    assert context["bindings"]["actual"] == dataset["id"]
