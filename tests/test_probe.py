from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

import pytest

from foundry import probe as probe_module
from foundry.errors import REFUSED, FoundryError
from foundry.probe import (
    PROBE_REFUSE_TEXT,
    PROBE_SPLIT_BY,
    PROBE_SPLIT_TABLE,
    PROBE_SPLIT_TEXT,
    mark_done,
    run_probe,
    skill_contains_questions,
    validate_authored_skill,
)
from foundry.query import query_locked as real_query_locked
from foundry.tags import OUTSIDE, RECOMPUTED
from foundry.window import Window, WindowStore
from openpyxl import Workbook

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "period-smoke"
# host-smoke loads the shipped dsh bundle, so it needs node the way the
# node-driven tests in test_plugin.py do.
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")


def authored_skill_text() -> str:
    return """# method

This skill is an F2 finance method skill.

It follows FOUNDRY.md and CONNECTORS.md, reads only the locked period brief,
uses query-locked for follow-up calculations, and labels anything outside the
locked window as 稿外追问.
"""


def write_contract(skill: Path, *, period_tools: list[str] | None = None) -> None:
    (skill / "foundry.json").write_text(
        json.dumps(
            {
                "schema": "finance-skill-foundry/f2-skill@1",
                "capability": "f2-period-analysis",
                "period_tools": period_tools
                or ["import", "lock", "record-questions", "emit-brief", "query-locked"],
                "safety": {
                    "questions_in_window": True,
                    "no_read_document_books": True,
                    "tag_followups": True,
                },
                "method_docs": ["FOUNDRY.md", "CONNECTORS.md"],
            }
        )
    )


def test_probe_passes_on_fixture_subset(tmp_path: Path) -> None:
    assert run_probe(tmp_path / "var", FIXTURES) == 0


def test_chat_only_skill_cannot_mark_done(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# chat only\n")
    (skill / "questions.md").write_text("1. 利润?\n")
    with pytest.raises(FoundryError, match="questions"):
        mark_done(skill, tmp_path / "var", FIXTURES)


def test_empty_skill_cannot_mark_done(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("")
    with pytest.raises(FoundryError, match="authored instructions"):
        mark_done(skill, tmp_path / "var", FIXTURES)


def test_keyword_pile_chat_shell_without_contract_cannot_mark_done(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "# method\n\nFOUNDRY.md CONNECTORS.md query-locked 稿外追问 import lock emit-brief\n"
    )
    with pytest.raises(FoundryError, match="foundry.json capability contract"):
        validate_authored_skill(skill)


def test_contract_missing_any_f2_tool_fails(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(authored_skill_text())
    write_contract(skill, period_tools=["import", "lock", "record-questions", "emit-brief"])
    with pytest.raises(FoundryError, match="period_tools"):
        validate_authored_skill(skill)


def test_mark_done_after_probe(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(authored_skill_text())
    write_contract(skill)
    status = mark_done(skill, tmp_path / "var", FIXTURES)
    assert status == {
        "contract_status": "valid",
        "engine_status": "passed",
        "method_status": "not_executed",
    }


def test_questions_file_detected() -> None:
    assert skill_contains_questions(Path(__file__).resolve().parents[1] / "fixtures" / "period-smoke") is True


def _fixture_copy(
    tmp_path: Path,
    *,
    gl_rows: list[list[object]] | None = None,
    questions: list[dict[str, object]] | None = None,
) -> Path:
    root = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, root)
    if gl_rows is not None:
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["account_code", "unit_id", "amount"])
        for row in gl_rows:
            ws.append(row)
        wb.save(root / "gl.xlsx")
    if questions is not None:
        (root / "questions.json").write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
    return root


def _probe_window(var_root: Path, *, exclude: set[str] = frozenset()) -> Window:
    ids = sorted(path.name for path in (var_root / "windows").iterdir() if path.is_dir())
    remaining = [window_id for window_id in ids if window_id not in exclude]
    assert len(remaining) == 1, remaining
    return WindowStore(var_root).get(remaining[0])


def _followup_item(var_root: Path, *, exclude: set[str] = frozenset()) -> dict[str, object]:
    window = _probe_window(var_root, exclude=exclude)
    payload = json.loads(window.schedules_path.read_text())
    items = [item for item in payload["items"] if item["origin"] == "followup"]
    assert len(items) == 1, items
    return items[0]


def _answering(answer: str) -> Callable[..., str]:
    """query_locked stand-in that fakes the split answer and keeps the refuse path real."""

    def fake(window: Window, text: str, **kwargs: object) -> str:
        if text == PROBE_REFUSE_TEXT:
            return real_query_locked(window, text, **kwargs)  # type: ignore[arg-type]
        return answer

    return fake


def _operator_window(var_root: Path) -> Window:
    store = WindowStore(var_root)
    window = store.create()
    window.import_tables(
        coa=FIXTURES / "coa.xlsx",
        units=FIXTURES / "units.xlsx",
        named=[{"id": "gl", "path": FIXTURES / "gl.xlsx"}],
    )
    return window


# --- finding 2: the probe must never repoint var/current at the fixture window ---


def test_probe_leaves_the_operator_current_window_alone(tmp_path: Path) -> None:
    var = tmp_path / "var"
    operator = _operator_window(var)
    before = (var / "current").read_text()
    assert run_probe(var, FIXTURES) == 0
    assert (var / "current").read_text() == before
    assert WindowStore(var).current().id == operator.id


def test_mark_done_leaves_the_operator_current_window_alone(tmp_path: Path) -> None:
    var = tmp_path / "var"
    operator = _operator_window(var)
    before = (var / "current").read_text()
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(authored_skill_text())
    write_contract(skill)
    mark_done(skill, var, FIXTURES)
    assert (var / "current").read_text() == before
    assert WindowStore(var).current().id == operator.id


@needs_node
def test_host_smoke_cli_leaves_the_operator_current_window_alone(tmp_path: Path) -> None:
    from foundry.cli import main as cli_main

    var = tmp_path / "var"
    operator = _operator_window(var)
    before = (var / "current").read_text()
    assert cli_main(["--var", str(var), "host-smoke", "--fixtures", str(FIXTURES)]) == 0
    assert (var / "current").read_text() == before
    assert WindowStore(var).current().id == operator.id


def test_probe_window_is_not_the_operator_window(tmp_path: Path) -> None:
    var = tmp_path / "var"
    operator = _operator_window(var)
    assert run_probe(var, FIXTURES) == 0
    probe_window = _probe_window(var, exclude={operator.id})
    assert probe_window.id != operator.id


# --- finding 9: every done-gate guard must be individually provable ---


def test_probe_refuses_a_brief_that_carries_the_followup_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe_module, "emit_brief", lambda window: f"# 本期结论稿\n\n{OUTSIDE}: 泄漏\n")
    with pytest.raises(FoundryError, match="probe brief carried"):
        run_probe(tmp_path / "var", FIXTURES)


def test_probe_refuses_an_untagged_recompute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        probe_module,
        "query_locked",
        _answering(f"{RECOMPUTED}: {PROBE_SPLIT_TEXT} → OU1=70, OU2=30"),
    )
    with pytest.raises(FoundryError, match="probe expected tagged recompute"):
        run_probe(tmp_path / "var", FIXTURES)


def test_probe_refuses_a_recompute_it_never_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        probe_module,
        "query_locked",
        _answering(f"{OUTSIDE} / {RECOMPUTED}: {PROBE_SPLIT_TEXT} → OU1=70, OU2=30"),
    )
    with pytest.raises(FoundryError, match="persisted .* workpaper item, got 0"):
        run_probe(tmp_path / "var", FIXTURES)


def test_probe_refuses_when_an_unnamed_table_is_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(window: Window, text: str, **kwargs: object) -> str:
        if text == PROBE_REFUSE_TEXT:
            return f"{RECOMPUTED}: {text} → 0"
        return real_query_locked(window, text, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(probe_module, "query_locked", fake)
    with pytest.raises(FoundryError, match="probe expected unnamed refuse"):
        run_probe(tmp_path / "var", FIXTURES)


def test_probe_refuses_a_fixture_with_no_in_window_questions(tmp_path: Path) -> None:
    fixtures = _fixture_copy(
        tmp_path,
        questions=[{"id": "q-cf", "text": "现金流净额?", "required_table_ids": ["cash_flow"]}],
    )
    with pytest.raises(FoundryError, match="no in-window questions"):
        run_probe(tmp_path / "var", fixtures)


def test_mark_done_propagates_a_probe_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(authored_skill_text())
    write_contract(skill)
    monkeypatch.setattr(probe_module, "emit_brief", lambda window: f"# 本期结论稿\n\n{OUTSIDE}: 泄漏\n")
    with pytest.raises(FoundryError, match="probe brief carried"):
        mark_done(skill, tmp_path / "var", FIXTURES)


# --- finding 10: the gate reads the locked catalog, it does not check a label ---


def test_probe_pins_the_fixture_split_totals_and_source(tmp_path: Path) -> None:
    var = tmp_path / "var"
    assert run_probe(var, FIXTURES) == 0
    item = _followup_item(var)
    assert item["table"] == PROBE_SPLIT_TABLE
    assert item["split_by"] == PROBE_SPLIT_BY
    assert item["tag"] == f"{OUTSIDE} / {RECOMPUTED}"
    assert {line["node_id"]: line["amount"] for line in item["lines"]} == {"OU1": 70, "OU2": 30}
    assert item["recomputed"] == 100
    window = _probe_window(var)
    records = [json.loads(line) for line in window.followup_path.read_text().splitlines() if line.strip()]
    assert [record["tag"] for record in records] == [OUTSIDE]
    assert PROBE_SPLIT_TEXT in window.workpaper_path.read_text()


def test_probe_answer_changes_with_the_locked_fixture_data(tmp_path: Path) -> None:
    fixtures = _fixture_copy(tmp_path, gl_rows=[["1001", "OU1", 11], ["1001", "OU2", 5]])
    var = tmp_path / "var"
    assert run_probe(var, fixtures) == 0
    item = _followup_item(var)
    assert {line["node_id"]: line["amount"] for line in item["lines"]} == {"OU1": 11, "OU2": 5}
    assert item["recomputed"] == 16


def test_probe_refuses_a_stale_answer_after_the_locked_data_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixtures = _fixture_copy(tmp_path, gl_rows=[["1001", "OU1", 11], ["1001", "OU2", 5]])
    monkeypatch.setattr(
        probe_module,
        "query_locked",
        _answering(f"{OUTSIDE} / {RECOMPUTED}: {PROBE_SPLIT_TEXT} → OU1=70, OU2=30"),
    )
    with pytest.raises(FoundryError, match="does not match locked gl"):
        run_probe(tmp_path / "var", fixtures)


@pytest.mark.parametrize(
    "answer",
    [
        f"{OUTSIDE} / {RECOMPUTED}: {PROBE_SPLIT_TEXT} → recomputed",
        f"{OUTSIDE} / {RECOMPUTED}: {PROBE_SPLIT_TEXT} → ",
        f"{OUTSIDE} / {RECOMPUTED}: {PROBE_SPLIT_TEXT} → OU1=70",
        f"{OUTSIDE} / {RECOMPUTED}: {PROBE_SPLIT_TEXT} → OU1=1, OU2=2",
        f"{OUTSIDE} / {RECOMPUTED}: 另一个问题 → OU1=70, OU2=30",
        f"{OUTSIDE}",
    ],
)
def test_probe_refuses_a_fabricated_tagged_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    monkeypatch.setattr(probe_module, "query_locked", _answering(answer))
    with pytest.raises(FoundryError, match="probe (expected tagged recompute|recompute does not match)"):
        run_probe(tmp_path / "var", FIXTURES)


# --- finding 34: python -m foundry.probe must say why it refused ---


def test_probe_module_main_prints_the_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixtures = _fixture_copy(
        tmp_path,
        questions=[{"id": "q-cf", "text": "现金流净额?", "required_table_ids": ["cash_flow"]}],
    )
    code = probe_module.main(["--var", str(tmp_path / "var"), "--fixtures", str(fixtures)])
    captured = capsys.readouterr()
    assert code == REFUSED
    assert "no in-window questions" in captured.err


def test_both_probe_entrypoints_report_the_same_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#34 -- authoring/SKILL.md sends authors to both; they must agree."""
    from foundry.cli import main as cli_main

    fixtures = _fixture_copy(
        tmp_path,
        questions=[{"id": "q-cf", "text": "现金流净额?", "required_table_ids": ["cash_flow"]}],
    )
    module_code = probe_module.main(["--var", str(tmp_path / "var-a"), "--fixtures", str(fixtures)])
    module_err = capsys.readouterr().err
    cli_code = cli_main(["--var", str(tmp_path / "var-b"), "probe", "--fixtures", str(fixtures)])
    cli_err = capsys.readouterr().err

    assert module_code == cli_code == REFUSED
    assert module_err == cli_err
    assert "no in-window questions" in cli_err


def test_probe_refuses_an_unusable_var_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    not_a_dir = tmp_path / "notadir.txt"
    not_a_dir.write_text("", encoding="utf-8")
    code = probe_module.main(["--var", str(not_a_dir), "--fixtures", str(FIXTURES)])
    captured = capsys.readouterr()
    assert code == REFUSED
    assert "--var is not a usable directory" in captured.err
    assert "Traceback" not in captured.err


def test_probe_refuses_a_missing_fixtures_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = probe_module.main(
        ["--var", str(tmp_path / "var"), "--fixtures", str(tmp_path / "nowhere")]
    )
    captured = capsys.readouterr()
    assert code == REFUSED
    assert "fixtures directory is missing" in captured.err


def test_probe_module_main_returns_zero_on_the_shipped_fixture(tmp_path: Path) -> None:
    assert probe_module.main(["--var", str(tmp_path / "var"), "--fixtures", str(FIXTURES)]) == 0


# --- finding 43: the gate compares against foundry.tags, not inlined literals ---


def test_probe_routes_tag_strings_through_foundry_tags() -> None:
    source = Path(probe_module.__file__).read_text(encoding="utf-8")
    assert "from foundry.tags import" in source
    assert OUTSIDE not in source
    assert RECOMPUTED not in source
