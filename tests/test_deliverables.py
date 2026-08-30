from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.cli import main
from foundry.probe import fixture_root
from foundry.task import TaskStore
from foundry.window import WindowStore


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out.strip()


def _period(
    var: Path, fixtures: Path, capsys: pytest.CaptureFixture[str], *, task: str, session: str
) -> str:
    """create → import → lock → questions → brief, all bound to one task and session."""
    base = ["--var", str(var), "--task", task, "--session", session]
    assert main([*base, "create"]) == 0
    window_id = _out(capsys)
    assert (
        main(
            [
                *base,
                "import",
                "--coa",
                str(fixtures / "coa.xlsx"),
                "--units",
                str(fixtures / "units.xlsx"),
                "--map",
                str(fixtures / "map.xlsx"),
                "--named",
                str(fixtures / "named.json"),
                "--drop-dir",
                str(fixtures),
            ]
        )
        == 0
    )
    assert main([*base, "lock"]) == 0
    assert main([*base, "record-questions", "--questions", str(fixtures / "questions.json")]) == 0
    assert main([*base, "emit-brief"]) == 0
    capsys.readouterr()
    return window_id


def _new_task(var: Path, capsys: pytest.CaptureFixture[str], title: str = "2026-08 月度经营分析") -> str:
    assert main(["--var", str(var), "task-new", "--title", title, "--period", "2026-08"]) == 0
    return _out(capsys)


def test_a_period_files_one_brief_and_one_workpaper(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    var = tmp_path / "var"
    task_id = _new_task(var, capsys)
    window_id = _period(var, fixture_root(None), capsys, task=task_id, session="sess-period")

    rows = TaskStore(var).get(task_id).deliverables()
    assert [row["kind"] for row in rows] == ["brief", "workpaper"]
    assert all(row["window_id"] == window_id for row in rows)
    assert all(row["cause"] == "emit-brief" for row in rows)
    assert all(row["session_id"] == "sess-period" for row in rows)
    assert [row["seq"] for row in rows] == [1, 2]


def test_a_follow_up_adds_a_workpaper_version_naming_its_schedule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The claim the versioning exists for.

    A follow-up rewrites `workpaper.md` in place. Without a version per write
    the audit trail holds one filename and no way to say which answer came from
    which shape of it.
    """
    var = tmp_path / "var"
    fixtures = fixture_root(None)
    task_id = _new_task(var, capsys)
    window_id = _period(var, fixtures, capsys, task=task_id, session="sess-period")

    assert (
        main(
            [
                "--var",
                str(var),
                "--session",
                "sess-leader",
                "query-locked",
                "--text",
                "按核算单元拆一下",
                "--tables",
                "gl",
                "--split-by",
                "unit_id",
                "--brief-window",
                window_id,
            ]
        )
        == 0
    )
    capsys.readouterr()

    task = TaskStore(var).get(task_id)
    rows = task.deliverables()
    assert [row["kind"] for row in rows] == ["brief", "workpaper", "workpaper"]
    latest = rows[-1]
    assert latest["cause"] == "query-locked:followup-1"
    assert latest["session_id"] == "sess-leader"
    assert latest["sha256"] != rows[1]["sha256"]
    # The brief did not move. emit_brief is idempotent and a follow-up never
    # rewrites it, so there is exactly one version of what the leader read.
    assert [row["kind"] for row in rows].count("brief") == 1
    assert "followup-1" in task.artifact_text(latest["sha256"])


def test_the_follow_up_row_carries_its_task_and_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    fixtures = fixture_root(None)
    task_id = _new_task(var, capsys)
    window_id = _period(var, fixtures, capsys, task=task_id, session="sess-period")
    assert (
        main(
            [
                "--var",
                str(var),
                "--session",
                "sess-leader",
                "query-locked",
                "--text",
                "按核算单元拆一下",
                "--tables",
                "gl",
                "--split-by",
                "unit_id",
                "--brief-window",
                window_id,
            ]
        )
        == 0
    )
    capsys.readouterr()
    window = WindowStore(var).get(window_id)
    rows = [json.loads(line) for line in window.followup_path.read_text().splitlines() if line.strip()]
    assert rows[-1]["task_id"] == task_id
    assert rows[-1]["session_id"] == "sess-leader"


def test_two_sessions_land_on_one_task_with_their_own_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The leader asks again two days later, in a new conversation."""
    var = tmp_path / "var"
    fixtures = fixture_root(None)
    task_id = _new_task(var, capsys)
    window_id = _period(var, fixtures, capsys, task=task_id, session="sess-period")
    for session, text in (("sess-day1", "按核算单元拆一下"), ("sess-day3", "再按分析节点拆一下")):
        args = [
            "--var",
            str(var),
            "--session",
            session,
            "query-locked",
            "--text",
            text,
            "--tables",
            "gl",
            "--split-by",
            "unit_id" if session == "sess-day1" else "analysis_node",
            "--brief-window",
            window_id,
        ]
        assert main(args) == 0
    capsys.readouterr()

    task = TaskStore(var).get(task_id)
    assert [row["session_id"] for row in task.sessions()] == [
        "sess-period",
        "sess-day1",
        "sess-day3",
    ]
    assert [row["role"] for row in task.sessions()] == ["period", "followup", "followup"]
    workpapers = [row for row in task.deliverables() if row["kind"] == "workpaper"]
    assert [row["session_id"] for row in workpapers] == ["sess-period", "sess-day1", "sess-day3"]


def test_the_leaders_own_words_are_recorded_beside_the_executed_query(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two columns, and neither is derived from the other.

    The model may rephrase what it sends to `query-locked`. What the leader
    asked is written once by the operator when the conversation opens.
    """
    var = tmp_path / "var"
    fixtures = fixture_root(None)
    task_id = _new_task(var, capsys)
    window_id = _period(var, fixtures, capsys, task=task_id, session="sess-period")
    assert (
        main(
            [
                "--var",
                str(var),
                "--task",
                task_id,
                "--session",
                "sess-leader",
                "record-session",
                "--role",
                "followup",
                "--verbatim",
                "华东这个月怎么回事？",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "--var",
                str(var),
                "--session",
                "sess-leader",
                "query-locked",
                "--text",
                "按核算单元拆收入",
                "--tables",
                "gl",
                "--split-by",
                "unit_id",
                "--brief-window",
                window_id,
            ]
        )
        == 0
    )
    capsys.readouterr()

    task = TaskStore(var).get(task_id)
    session = next(row for row in task.sessions() if row["session_id"] == "sess-leader")
    assert session["leader_verbatim"] == "华东这个月怎么回事？"
    window = WindowStore(var).get(window_id)
    rows = [json.loads(line) for line in window.followup_path.read_text().splitlines() if line.strip()]
    assert rows[-1]["text"] == "按核算单元拆收入"


def test_export_files_the_version_the_leader_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    task_id = _new_task(var, capsys)
    window_id = _period(var, fixture_root(None), capsys, task=task_id, session="sess-period")
    assert main(["--var", str(var), "--task", task_id, "export", "--kind", "brief"]) == 0
    exported = json.loads(_out(capsys))
    assert exported["kind"] == "export"
    assert exported["cause"] == "export:brief"
    assert exported["window_id"] == window_id
    task = TaskStore(var).get(task_id)
    brief = next(row for row in task.deliverables() if row["kind"] == "brief")
    # Same bytes, filed twice on purpose: one is what the window produced, the
    # other is what was handed out, and a later follow-up cites the second.
    assert exported["sha256"] == brief["sha256"]


def test_re_import_puts_the_successor_on_the_same_task(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    fixtures = fixture_root(None)
    task_id = _new_task(var, capsys)
    window_id = _period(var, fixtures, capsys, task=task_id, session="sess-period")
    assert (
        main(
            [
                "--var",
                str(var),
                "re-import",
                "--coa",
                str(fixtures / "coa.xlsx"),
                "--units",
                str(fixtures / "units.xlsx"),
                "--map",
                str(fixtures / "map.xlsx"),
                "--named",
                str(fixtures / "named.json"),
                "--drop-dir",
                str(fixtures),
            ]
        )
        == 0
    )
    successor = _out(capsys)
    task = TaskStore(var).get(task_id)
    assert [(row["window_id"], row["reason"]) for row in task.windows()] == [
        (window_id, "initial"),
        (successor, "reimport"),
    ]


def test_a_window_with_no_task_still_works_and_is_adopted_on_touch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No task is not an error. It is a window nothing has claimed yet."""
    var = tmp_path / "var"
    fixtures = fixture_root(None)
    assert main(["--var", str(var), "create"]) == 0
    window_id = _out(capsys)
    assert (
        main(
            [
                "--var",
                str(var),
                "import",
                "--coa",
                str(fixtures / "coa.xlsx"),
                "--named",
                str(fixtures / "named.json"),
                "--drop-dir",
                str(fixtures),
            ]
        )
        == 0
    )
    assert main(["--var", str(var), "lock"]) == 0
    assert WindowStore(var).get(window_id).task_id is None

    task_id = _new_task(var, capsys)
    assert (
        main(["--var", str(var), "--task", task_id, "record-questions", "--questions", str(fixtures / "questions.json")])
        == 0
    )
    assert WindowStore(var).get(window_id).task_id == task_id
    assert [row["window_id"] for row in TaskStore(var).get(task_id).windows()] == [window_id]


def test_task_show_reports_the_chain_the_inputs_and_the_versions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    task_id = _new_task(var, capsys)
    window_id = _period(var, fixture_root(None), capsys, task=task_id, session="sess-period")
    assert main(["--var", str(var), "--task", task_id, "task-show"]) == 0
    payload = json.loads(_out(capsys))
    assert payload["task"]["id"] == task_id
    assert payload["task"]["period"] == "2026-08"
    assert [row["window_id"] for row in payload["windows"]] == [window_id]
    assert payload["windows"][0]["state"] == "Briefed"
    inputs = {row["role"]: row for row in payload["windows"][0]["inputs"]}
    assert "coa" in inputs and inputs["coa"]["present"] is True
    assert inputs["coa"]["bytes"] > 0
    assert [row["kind"] for row in payload["deliverables"]] == ["brief", "workpaper"]


def test_task_commands_refuse_by_name_with_no_task(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    var = tmp_path / "var"
    assert main(["--var", str(var), "task-show"]) == 3
    assert "no task" in capsys.readouterr().err


def test_the_follow_up_is_anchored_to_the_exported_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Which sheet of paper the leader was holding.

    A window has one brief but can be exported more than once, so the window id
    alone does not say which version a question was asked against.
    """
    var = tmp_path / "var"
    fixtures = fixture_root(None)
    task_id = _new_task(var, capsys)
    window_id = _period(var, fixtures, capsys, task=task_id, session="sess-period")
    assert main(["--var", str(var), "--task", task_id, "export", "--kind", "brief"]) == 0
    exported = json.loads(_out(capsys))

    assert (
        main(
            [
                "--var",
                str(var),
                "--session",
                "sess-leader",
                "query-locked",
                "--text",
                "按核算单元拆收入",
                "--tables",
                "gl",
                "--split-by",
                "unit_id",
                "--brief-window",
                window_id,
                "--brief-sha",
                exported["sha256"],
            ]
        )
        == 0
    )
    capsys.readouterr()
    window = WindowStore(var).get(window_id)
    row = [json.loads(line) for line in window.followup_path.read_text().splitlines() if line.strip()][-1]
    assert row["brief_sha"] == exported["sha256"]
    # No second copy of the leader's wording: the session row holds it once, and
    # `session_id` is the pointer.
    assert row["session_id"] == "sess-leader"
    assert "leader_verbatim" not in row
