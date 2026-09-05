from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.brief import emit_brief
from foundry.errors import LockRefused
from foundry.questions import record_questions
from foundry.references import load_references, record_reference
from foundry.tags import EXTERNAL, NOT_IN_WINDOW, OUTSIDE, RECOMPUTED
from foundry.window import WindowStore

BENCHMARK = {
    "id": "ref-1",
    "text": "行业物业费收缴率中位数 92.4%",
    "source": "中指研究院《2026 中国物业服务百强企业研究报告》",
    "at": "2026-08-30",
}


def _xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(headers)
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _locked(tmp_path: Path):
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1122", "应收账款"]]),
        named=[
            {
                "id": "ar",
                "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["1122", 400]]),
            }
        ],
        drop_dir=drop,
    )
    window.lock()
    return window


def test_a_reference_reaches_the_brief_marked_and_sourced(tmp_path: Path) -> None:
    window = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "应收合计", "required_table_ids": ["ar"]}])
    record_reference(window, [BENCHMARK])
    brief = emit_brief(window)

    assert f"## {EXTERNAL}" in brief
    assert BENCHMARK["text"] in brief
    # The source and the date are the reason the line is allowed to be there.
    assert BENCHMARK["source"] in brief
    assert BENCHMARK["at"] in brief
    # And the figure this window did compute keeps its own word, on its own line.
    assert RECOMPUTED in brief


def test_a_reference_is_never_recomputed(tmp_path: Path) -> None:
    """The brief may cite it; the workpaper may not tick it.

    A schedule row is a line out of the locked catalog. A benchmark has no
    lines, and a workpaper that showed one would be inventing the thing the
    whole product exists to make impossible.
    """
    window = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "应收合计", "required_table_ids": ["ar"]}])
    record_reference(window, [BENCHMARK])
    emit_brief(window)

    paper = window.workpaper_path.read_text()
    section = paper[paper.index(BENCHMARK["text"]) :]
    assert EXTERNAL in section
    assert "无附表行" in section
    # Not one of the lock's words anywhere between this heading and the next.
    head = section[: section.find("\n## ", 1) if "\n## " in section[1:] else len(section)]
    assert RECOMPUTED not in head


def test_a_reference_may_not_wear_the_locks_words(tmp_path: Path) -> None:
    window = _locked(tmp_path)
    for word in (RECOMPUTED, OUTSIDE, NOT_IN_WINDOW):
        with pytest.raises(LockRefused, match="brief's own mark"):
            record_reference(
                window, [{**BENCHMARK, "id": f"ref-{word}", "text": f"同业口径 {word} 92.4%"}]
            )
    assert load_references(window) == []


def test_a_reference_without_a_source_or_a_date_is_refused(tmp_path: Path) -> None:
    window = _locked(tmp_path)
    for missing in ("source", "at"):
        entry = {**BENCHMARK}
        entry[missing] = ""
        with pytest.raises(LockRefused, match=missing):
            record_reference(window, [entry])
    assert load_references(window) == []


def test_references_accumulate_and_ids_stay_unique(tmp_path: Path) -> None:
    """Found one at a time, over a conversation, so the call appends."""
    window = _locked(tmp_path)
    record_reference(window, [BENCHMARK])
    record_reference(window, [{**BENCHMARK, "id": "ref-2", "text": "百强平均周转 106 天"}])
    assert [entry["id"] for entry in load_references(window)] == ["ref-1", "ref-2"]

    with pytest.raises(LockRefused, match="duplicate reference id: ref-1"):
        record_reference(window, [{**BENCHMARK, "text": "另一个说法"}])
    assert len(load_references(window)) == 2


def test_references_are_refused_before_the_lock(tmp_path: Path) -> None:
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match="state Open"):
        record_reference(window, [BENCHMARK])


def test_a_followup_cannot_quote_a_reference_as_the_briefs_figure(tmp_path: Path) -> None:
    """A cited benchmark sits on the brief without becoming one of its numbers.

    `query-locked` decides between 报表声称 (this is already on the brief) and
    稿外追问 (this is a new question) by looking the text up in the brief's
    facts. A reference is in that file too, and matching against it would let a
    number someone else published come back wearing the word this window
    reserves for its own arithmetic.
    """
    from foundry.query import query_locked

    window = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "应收合计", "required_table_ids": ["ar"]}])
    record_reference(window, [BENCHMARK])
    emit_brief(window)

    answer = query_locked(
        window, BENCHMARK["text"], required_table_ids=["ar"], question_id=BENCHMARK["id"]
    )
    assert answer.startswith(OUTSIDE)


def test_the_brief_facts_reader_hands_out_lock_figures_only(tmp_path: Path) -> None:
    """The boundary itself, not the behaviour that currently depends on it.

    Both of `query.py`'s lookups would miss a reference anyway, because neither
    can match a record that names no tables. This pins the rule rather than the
    accident: whatever is written against this list next gets lock figures.
    """
    import json

    from foundry.query import _facts

    window = _locked(tmp_path)
    (window.root / "brief_facts.json").write_text(
        json.dumps(
            [
                {"id": "q1", "basis": "lock", "tag": RECOMPUTED, "required_table_ids": ["ar"]},
                {"id": "old", "tag": RECOMPUTED, "required_table_ids": ["ar"]},
                {"id": "ref-1", "basis": "external", "tag": EXTERNAL, "required_table_ids": ["ar"]},
            ],
            ensure_ascii=False,
        )
    )
    # The undated fact keeps its meaning; only the cited one is dropped.
    assert [fact["id"] for fact in _facts(window)] == ["q1", "old"]


def test_a_reference_found_after_the_brief_lands_on_the_workpaper(tmp_path: Path) -> None:
    """The moment a leader asks how a figure compares is while reading the brief.

    There is no re-emitting the brief by then, so the reference goes where every
    other post-brief answer goes: onto the workpaper, with the window moved to
    `FollowUp` and a deliverable version whose cause names it.
    """
    window = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "应收合计", "required_table_ids": ["ar"]}])
    emit_brief(window)

    record_reference(window, [{**BENCHMARK, "id": "ref-late"}])
    assert window.state == "FollowUp"

    paper = window.workpaper_path.read_text()
    assert BENCHMARK["text"] in paper
    assert BENCHMARK["source"] in paper
    # Not `来源: brief` -- the leader who read the brief never saw this line.
    late = paper[paper.index(BENCHMARK["text"]) :]
    assert "来源: 稿外补录" in late
    # And not a follow-up either: nothing was recomputed.
    assert OUTSIDE not in late
    # The brief is untouched -- it was written before this was known.
    assert BENCHMARK["text"] not in window.brief_path.read_text()
    # The deliverable version this files is asserted at the CLI level, where a
    # window actually has a task: see `test_deliverables.py`.


def _run_while_first_read_is_paused(first, second, entered, release) -> None:
    """Force the stale-read interleaving, while allowing a correct lock to block."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_call = pool.submit(first)
        try:
            assert entered.wait(timeout=5), "first operation never reached its read"
            second_call = pool.submit(second)
            try:
                second_call.result(timeout=0.3)
            except TimeoutError:
                # A transaction spanning the read keeps the second writer out.
                pass
        finally:
            release.set()
        first_call.result(timeout=10)
        second_call.result(timeout=10)


@pytest.mark.parametrize("briefed", [False, True])
def test_concurrent_reference_appends_keep_both_references_and_schedules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, briefed: bool
) -> None:
    import threading

    import foundry.references as reference_module
    from foundry.workpaper import load_schedules

    window = _locked(tmp_path)
    record_questions(window, [{"id": "q1", "text": "应收合计", "required_table_ids": ["ar"]}])
    if briefed:
        emit_brief(window)
    entered, release = threading.Event(), threading.Event()
    original_load = reference_module.load_references

    def paused_load(target):
        loaded = original_load(target)
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=5), "first reference read was not released"
        return loaded

    monkeypatch.setattr(reference_module, "load_references", paused_load)
    _run_while_first_read_is_paused(
        lambda: record_reference(window, [BENCHMARK]),
        lambda: record_reference(window, [{**BENCHMARK, "id": "ref-2"}]),
        entered,
        release,
    )
    assert {entry["id"] for entry in load_references(window)} == {"ref-1", "ref-2"}
    if not briefed:
        emit_brief(window)
    assert {item["id"] for item in load_schedules(window)["items"]} == {"q1", "ref-1", "ref-2"}
    assert "ref-1" in window.workpaper_path.read_text()
    assert "ref-2" in window.workpaper_path.read_text()


def test_reference_arriving_during_emit_is_in_a_traced_workpaper_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    import foundry.brief as brief_module
    from foundry.task import TaskStore
    from foundry.workpaper import load_schedules

    window = _locked(tmp_path)
    task = TaskStore(window.store.var_root).create(title="并发分析")
    window.bind_task(task.id)
    record_questions(window, [{"id": "q1", "text": "应收合计", "required_table_ids": ["ar"]}])
    entered, release = threading.Event(), threading.Event()
    original_load = brief_module.load_references

    def paused_load(target):
        loaded = original_load(target)
        entered.set()
        assert release.wait(timeout=5), "brief reference read was not released"
        return loaded

    monkeypatch.setattr(brief_module, "load_references", paused_load)
    _run_while_first_read_is_paused(
        lambda: emit_brief(window),
        lambda: record_reference(window, [BENCHMARK]),
        entered,
        release,
    )
    assert {entry["id"] for entry in load_references(window)} == {"ref-1"}
    assert {item["id"] for item in load_schedules(window)["items"]} == {"q1", "ref-1"}
    assert window.state == "FollowUp"
    assert BENCHMARK["text"] not in window.brief_path.read_text()
    assert BENCHMARK["text"] in window.workpaper_path.read_text()
    versions = [row for row in task.deliverables() if row["kind"] == "workpaper"]
    assert any(BENCHMARK["text"] in task.artifact_text(row["sha256"]) for row in versions)


def test_emit_archives_the_workpaper_it_wrote_before_a_late_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    import foundry.brief as brief_module
    from foundry.task import TaskStore

    window = _locked(tmp_path)
    task = TaskStore(window.store.var_root).create(title="底稿版本归档")
    window.bind_task(task.id)
    record_questions(window, [{"id": "q1", "text": "应收合计", "required_table_ids": ["ar"]}])
    entered, release = threading.Event(), threading.Event()
    original_register = brief_module.register_window_deliverable

    def paused_register(*args, **kwargs):
        if kwargs["kind"] == "brief":
            entered.set()
            assert release.wait(timeout=5), "brief archive was not released"
        return original_register(*args, **kwargs)

    monkeypatch.setattr(brief_module, "register_window_deliverable", paused_register)
    _run_while_first_read_is_paused(
        lambda: emit_brief(window),
        lambda: record_reference(window, [BENCHMARK]),
        entered,
        release,
    )
    versions = [row for row in task.deliverables() if row["kind"] == "workpaper"]
    initial = [row for row in versions if row["cause"] == "emit-brief"]
    late = [row for row in versions if row["cause"] == "record-reference:ref-1"]
    assert len(initial) == len(late) == 1
    assert BENCHMARK["text"] not in task.artifact_text(initial[0]["sha256"])
    assert BENCHMARK["text"] in task.artifact_text(late[0]["sha256"])
