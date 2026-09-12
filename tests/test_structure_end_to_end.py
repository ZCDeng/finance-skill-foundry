"""U9: the whole path, on a workbook shaped like the manager's own.

First load with a card, an assistant-assisted confirmation, next month's file
arriving against a remembered shape, and a repeat upload — walked end to end and
checked against the figures the consolidated income statement carries.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.finance_service import FinanceStore
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


def _cli(root: Path, task_id: str, *args: str, actor: str = "manager") -> int:
    return main(["--var", str(root), "--task", task_id, "--actor", actor, *args])


def _account_map(service: FinanceStore) -> dict:
    rows = [
        {"account_code": code, "management_account": account}
        for code, *_rest in fixture.LEDGER_ROWS
        if (account := fixture.management_account(code))
    ]
    return service.save_account_map({"name": "华宸损益映射", "rows": rows})


def test_the_whole_path_on_a_month_end_pack(tmp_path: Path, capsys) -> None:
    root = tmp_path / "var"
    task = TaskStore(root).create(title="华宸 2026-08 月结")
    analysis = AnalysisStore(task)
    manager = FinanceStore(task, actor="manager")

    # --- F1. The manager adds the pack; the reading happens at once. ---
    august = tmp_path / "华宸_2026年08月.xlsx"
    august.write_bytes(fixture.monthly_pack())
    assert _cli(root, task.id, "dataset-add", "--path", str(august), "--name", "八月套表",
                "--meta", json.dumps({"mode": "workbook"})) == 0
    capsys.readouterr()
    shell = analysis.state()["datasets"][0]

    report = manager.finance_readiness({})
    assert [row["reason"] for row in report["blocked"]] == ["pending_structure"]
    assert report["structure_states"][shell["id"]] == "pending_confirmation"

    proposal = manager.structure_proposal_list({"dataset_id": shell["id"]})["proposals"][0]
    decisions = {sheet["sheet"]: sheet for sheet in proposal["sheets"]}

    # AE4: the cover, the KPI board and the benchmark page are not the books.
    for name in ("00·封面与编制说明", "01·核心指标看板", "13·行业对标与假设"):
        assert decisions[name]["decision"] == "excluded"
        assert decisions[name]["reason"] == "presentation_sheet"
    for name in ("02·GL科目余额表", "03·GL月结分录清单", "10·区域经营损益表", "11·城市公司明细表"):
        assert decisions[name]["decision"] == "table"

    ledger = decisions["02·GL科目余额表"]
    assert ledger["header_row"] == 4  # AE1
    assert ledger["scope_hints"] == {"period": "2026-08", "currency": "", "unit": "元"}  # AE5
    period_pair = next(pair for pair in ledger["amount_pairs"] if pair["primary"])
    assert period_pair["label"] == "本期发生额"
    assert period_pair["direction"]["kind"] == "by_category"
    assert len([row for row in ledger["excluded_rows"] if row["reason"] == "section"]) == 5

    journal = decisions["03·GL月结分录清单"]  # AE3
    roles = {column["role"]: column["letter"] for column in journal["columns"]}
    assert sorted(journal["fill_down_columns"]) == sorted(
        [roles["doc_id"], roles["date"], roles["summary"]]
    )
    assert len(journal["excluded_rows"]) == len(fixture.VOUCHERS) + 1

    confirmation = manager.structure_proposal_confirm(
        {"dataset_id": shell["id"], "revision": proposal["revision"], "sheets": [ledger, journal]}
    )
    assert confirmation["source"] == "manager"
    assert confirmation["state"] == "confirmed"

    # Confirmed: the report reads the tables, not the workbook it came from.
    settled = manager.finance_readiness({})
    assert not any(row["reason"] == "pending_structure" for row in settled["blocked"])
    assert settled["structure_states"][shell["id"]] == "confirmed"

    # --- The figures the consolidated income statement carries. ---
    snapshot = confirmation["snapshot_ids"]["02·GL科目余额表"]
    account_map = _account_map(manager)
    context = manager.save_context(
        {
            "name": "华宸 2026-08 管理损益",
            "bindings": {"actual": snapshot},
            "account_map_id": account_map["id"],
            "scopes": {"actual": SCOPE},
        }
    )
    run = manager.run_metric(
        {"context_id": context["id"], "metric": {"kind": "management_pnl"}}
    )
    row = run["result"]["rows"][0]
    expected = fixture.expected_pnl()
    assert Decimal(row["revenue"]) == Decimal(expected["revenue"])
    assert Decimal(row["cost"]) == Decimal(expected["cost"])
    assert Decimal(row["expense"]) == Decimal(expected["expense"])

    # AE2: a figure opens at the cell in the file she uploaded.
    prepared = manager.prepare_explanation({"run_ids": [run["id"]]})
    fact = next(item for item in prepared["facts"] if item.get("column") == "expense")
    located = manager.open_source_locator({"fact_id": fact["id"]})
    assert located["status"] == "ok"
    assert located["locator"]["sheet"] == "02·GL科目余额表"
    assert located["locator"]["excel_range"].startswith("02·GL科目余额表!G")
    assert "/" not in json.dumps(located, ensure_ascii=False)

    # --- F4 / AE10. The same file again is answered, not filed. ---
    before = len(analysis.state()["datasets"])
    again = analysis.add_dataset(august, name="八月套表（再次）", metadata={"mode": "workbook"})
    assert again["duplicate_of"] == shell["id"]
    assert len(analysis.state()["datasets"]) == before

    # --- F3 / AE8. Next month's pack matches the remembered shape. ---
    september = tmp_path / "华宸_2026年09月.xlsx"
    september.write_bytes(fixture.monthly_pack(period="2026年09月"))
    assert _cli(root, task.id, "dataset-add", "--path", str(september), "--name", "九月套表",
                "--meta", json.dumps({"mode": "workbook"})) == 0
    capsys.readouterr()
    next_shell = next(
        item for item in analysis.state()["datasets"] if item["name"] == "九月套表"
    )
    assert manager.dataset_structure_state(next_shell["id"]) == "pending_acknowledgement"
    applied = next(
        item
        for item in manager.structure_confirmation_list({"dataset_id": next_shell["id"]})[
            "confirmations"
        ]
        if item["source"] == "template"
    )
    assert applied["triggered_by_actor"] == "manager"

    manager.structure_withdraw({"id": applied["id"]})
    assert manager.dataset_structure_state(next_shell["id"]) == "pending_confirmation"


def test_the_assistant_confirms_on_the_managers_word_and_she_settles_it(
    tmp_path: Path,
) -> None:
    """F2: readiness says pending, the assistant reads it back, she acknowledges."""
    root = tmp_path / "var"
    task = TaskStore(root).create(title="对话里确认")
    analysis = AnalysisStore(task)
    path = tmp_path / "pack.xlsx"
    path.write_bytes(fixture.monthly_pack())
    shell = analysis.add_dataset(path, name="月结套表", metadata={"mode": "workbook"})

    assistant = FinanceStore(task, actor="assistant")
    assistant.structure_propose(shell["id"])
    report = assistant.finance_readiness({})
    assert [row["reason"] for row in report["blocked"]] == ["pending_structure"]

    proposal = assistant.structure_proposal_list({"dataset_id": shell["id"]})["proposals"][0]
    ledger = [sheet for sheet in proposal["sheets"] if sheet["sheet"].startswith("02")]
    confirmation = assistant.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": ledger}
    )
    assert confirmation["source"] == "assistant"
    assert confirmation["state"] == "pending_acknowledgement"

    manager = FinanceStore(task, actor="manager")
    acknowledged = manager.structure_acknowledge({"id": confirmation["id"]})
    assert acknowledged["state"] == "acknowledged"
    assert manager.dataset_structure_state(shell["id"]) == "confirmed"
    # Every step says who took it.
    sources = [
        (row["source"], row["state"], row["triggered_by_actor"])
        for row in manager.structure_confirmation_list({"dataset_id": shell["id"]})[
            "confirmations"
        ]
    ]
    assert ("assistant", "pending_acknowledgement", "assistant") in sources
    assert ("assistant", "acknowledged", "manager") in sources


def test_an_undecided_side_is_asked_rather_than_guessed(tmp_path: Path) -> None:
    """AE9: no category column, so nobody may pick the side on her behalf."""
    from foundry.errors import FoundryError

    task = TaskStore(tmp_path / "var").create(title="未定方向")
    analysis = AnalysisStore(task)
    path = tmp_path / "nocat.xlsx"
    path.write_bytes(fixture.no_category_ledger())
    shell = analysis.add_dataset(path, name="余额表", metadata={"mode": "workbook"})
    service = FinanceStore(task, actor="manager")
    service.structure_propose(shell["id"])

    proposal = service.structure_proposal_list({"dataset_id": shell["id"]})["proposals"][0]
    sheet = proposal["sheets"][0]
    assert sheet["amount_pairs"][0]["direction"] == {"kind": "undecided"}
    try:
        service.structure_proposal_confirm({"dataset_id": shell["id"], "sheets": [sheet]})
    except FoundryError as error:
        assert "debit/credit side" in str(error)
    else:  # pragma: no cover - the confirmation must not succeed
        raise AssertionError("an undecided side must not confirm")

    sheet["amount_pairs"][0]["direction"] = {"kind": "fixed", "side": "credit"}
    confirmed = service.structure_proposal_confirm(
        {"dataset_id": shell["id"], "sheets": [sheet]}
    )
    assert confirmed["state"] == "confirmed"
