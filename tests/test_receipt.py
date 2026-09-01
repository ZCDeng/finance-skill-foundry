from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.cli import main
from foundry.resources import fixture_root
from foundry.task import TaskStore

"""
What a call archived, reported by the side that archived it.

A session can produce a brief, a workpaper and several revisions of that
workpaper without anything in the conversation saying so; the versions are
real and the operator has to leave and go looking. The first half of fixing
that is here: every write path can now say which deliverable versions it
filed, and whether each was newly appended.

Reported rather than derived, and that is the whole design. Diffing `seq`
around a call looks equivalent and is not -- `seq` is allocated under the task
lock across every window, so a concurrent follow-up on the same task lands in
the gap, and the read side resolves its own task, which is not always the one
that was written.
"""


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out.strip()


def _receipt(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(_out(capsys))


def _locked(var: Path, capsys: pytest.CaptureFixture[str], task: str | None = None) -> list[str]:
    """A window through lock and questions, ready to emit."""
    fixtures = fixture_root(None)
    base = ["--var", str(var), *(["--task", task] if task else [])]
    assert main([*base, "create"]) == 0
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
    capsys.readouterr()
    return base


def _task(var: Path, capsys: pytest.CaptureFixture[str]) -> str:
    assert main(["--var", str(var), "task-new", "--title", "2026-08 月结", "--period", "2026-08"]) == 0
    return _out(capsys)


# -- what it reports --------------------------------------------------------


def test_a_first_emit_reports_both_versions_as_newly_appended(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    base = _locked(var, capsys, _task(var, capsys))

    assert main([*base, "emit-brief", "--receipt"]) == 0
    receipt = _receipt(capsys)

    assert receipt["text"].startswith("# 本期结论稿")
    assert [(row["kind"], row["appended"]) for row in receipt["filed"]] == [
        ("brief", True),
        ("workpaper", True),
    ]
    assert all(row["cause"] == "emit-brief" for row in receipt["filed"])


def test_a_re_render_reports_the_same_versions_as_already_on_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The distinction the row alone cannot make.

    `register_bytes` returns the prior row when the bytes match, and
    `_register_period_outputs` runs on every emit. A receipt that called the
    second run an archive would tell an operator a version exists that they
    have already seen, every time they re-emit.
    """
    var = tmp_path / "var"
    base = _locked(var, capsys, _task(var, capsys))

    assert main([*base, "emit-brief", "--receipt"]) == 0
    first = _receipt(capsys)
    assert main([*base, "emit-brief", "--receipt"]) == 0
    second = _receipt(capsys)

    assert [row["appended"] for row in second["filed"]] == [False, False]
    # Same versions, not new ones.
    assert [row["seq"] for row in first["filed"]] == [row["seq"] for row in second["filed"]]
    assert [row["sha256"] for row in first["filed"]] == [row["sha256"] for row in second["filed"]]


def test_a_follow_up_reports_the_workpaper_version_it_grew(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    task = _task(var, capsys)
    base = _locked(var, capsys, task)
    assert main([*base, "emit-brief"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "--var",
                str(var),
                "--task",
                task,
                "--session",
                "sess-leader",
                "query-locked",
                "--receipt",
                "--text",
                "按核算单元拆一下",
                "--tables",
                "gl",
                "--split-by",
                "unit_id",
            ]
        )
        == 0
    )
    receipt = _receipt(capsys)

    assert receipt["text"].startswith("稿外追问")
    assert [(row["kind"], row["cause"], row["appended"]) for row in receipt["filed"]] == [
        ("workpaper", "query-locked:followup-1", True)
    ]
    assert receipt["filed"][0]["session_id"] == "sess-leader"


def test_a_late_reference_reports_its_version_and_says_nothing_otherwise(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """This verb answers by refusing or by saying nothing, and that is kept."""
    var = tmp_path / "var"
    task = _task(var, capsys)
    base = _locked(var, capsys, task)
    assert main([*base, "emit-brief"]) == 0
    capsys.readouterr()

    entries = json.dumps(
        [{"id": "ref-1", "text": "行业中位数 92.4%", "source": "中指研究院", "at": "2026-08-30"}],
        ensure_ascii=False,
    )
    plain = ["--var", str(var), "--task", task, "record-reference", "--references", entries]
    assert main([*plain, "--receipt"]) == 0
    receipt = _receipt(capsys)

    assert receipt["text"] == ""
    assert [(row["kind"], row["cause"]) for row in receipt["filed"]] == [
        ("workpaper", "record-reference:ref-1")
    ]


def test_a_window_with_no_task_files_nothing_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty receipt is not the same claim as "nothing was produced".

    A window an operator drove straight through the CLI has no timeline to hang
    versions on. The brief is still written; there is simply nowhere to file it.
    """
    var = tmp_path / "var"
    base = _locked(var, capsys)

    assert main([*base, "emit-brief", "--receipt"]) == 0
    receipt = _receipt(capsys)

    assert receipt["filed"] == []
    assert receipt["text"].startswith("# 本期结论稿")


# -- what it does not change ------------------------------------------------


def test_without_the_flag_stdout_is_what_it_always_was(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The plain CLI is a surface an operator reads and many tests assert on."""
    var = tmp_path / "var"
    task = _task(var, capsys)
    base = _locked(var, capsys, task)

    assert main([*base, "emit-brief"]) == 0
    plain = capsys.readouterr().out
    assert plain.startswith("# 本期结论稿")
    assert not plain.lstrip().startswith("{")

    assert (
        main(
            [
                "--var",
                str(var),
                "--task",
                task,
                "query-locked",
                "--text",
                "GL 合计",
                "--tables",
                "gl",
            ]
        )
        == 0
    )
    answer = capsys.readouterr().out
    # The line terminator is the plain surface's, and it is unchanged.
    assert answer.endswith("\n")
    assert not answer.lstrip().startswith("{")


def test_the_reported_rows_are_the_rows_the_store_holds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A receipt that disagreed with the timeline would be worse than none."""
    var = tmp_path / "var"
    task = _task(var, capsys)
    base = _locked(var, capsys, task)
    assert main([*base, "emit-brief", "--receipt"]) == 0
    receipt = _receipt(capsys)

    stored = TaskStore(var).get(task).deliverables()
    assert len(stored) == len(receipt["filed"])
    for filed, row in zip(receipt["filed"], stored, strict=True):
        # `appended` is the receipt's own field and is never persisted.
        assert {key: value for key, value in filed.items() if key != "appended"} == row
        assert "appended" not in row
