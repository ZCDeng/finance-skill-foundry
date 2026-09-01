from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.cli import main
from foundry.errors import FoundryError
from foundry.resources import fixture_root
from foundry.task import TaskStore, session_owner

"""
One task owns its own windows and its own conversations.

The task chain's whole claim is that a closing period owns its windows, its
sessions and every version of every document it produced. Two calls could
reach across it, and both reproduced on a real store before these tests
existed:

    a session already recorded on task A recomputed against task B's locked
    catalog, and ended up on both session lists while B grew a workpaper
    version caused by a conversation held about A

    `--task A query-locked --brief-window <B's window>` put B's window into
    A's chain, while that window's own back-pointer still said B

Neither broke provenance -- both figures were derivable from the lock they
named, and both were marked 稿外追问. What broke was the timeline: a document
version on a task, from a conversation that task never had.
"""


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out.strip()


def _closed(var: Path, title: str, period: str, capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    """A task carried through one whole close. Returns its id and its window's."""
    fixtures = fixture_root(None)
    assert main(["--var", str(var), "task-new", "--title", title, "--period", period]) == 0
    task_id = _out(capsys)
    base = ["--var", str(var), "--task", task_id]
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
    assert main([*base, "emit-brief"]) == 0
    capsys.readouterr()
    window_id = json.loads(
        _capture(var, task_id, capsys)
    )["windows"][-1]["window_id"]
    return task_id, window_id


def _capture(var: Path, task_id: str, capsys: pytest.CaptureFixture[str]) -> str:
    assert main(["--var", str(var), "--task", task_id, "task-show"]) == 0
    return _out(capsys)


def _two_tasks(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    var = tmp_path / "var"
    a, window_a = _closed(var, "A 期", "2026-07", capsys)
    b, window_b = _closed(var, "B 期", "2026-08", capsys)
    return var, a, window_a, b, window_b


def _followup(var: Path, window: str, *top: str) -> int:
    """One follow-up. `--session` and `--task` are top-level; `--brief-window` is not."""
    return main(
        [
            "--var",
            str(var),
            *top,
            "query-locked",
            "--text",
            "GL 合计",
            "--tables",
            "gl",
            "--brief-window",
            window,
        ]
    )


# -- a conversation belongs to one task -------------------------------------


def test_a_session_recorded_on_one_task_cannot_be_recorded_on_another(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var, a, window_a, b, window_b = _two_tasks(tmp_path, capsys)

    assert _followup(var, window_a, "--session", "sess-leader") == 0
    capsys.readouterr()
    assert session_owner(TaskStore(var), "sess-leader").id == a

    # The same conversation, pointed at the other task's window.
    assert _followup(var, window_b, "--session", "sess-leader") == 3
    assert "already belongs to task" in capsys.readouterr().err

    detail = json.loads(_capture(var, b, capsys))
    assert detail["sessions"] == [], "the foreign conversation reached B's timeline"
    # And B produced nothing from it: two versions, both from its own close.
    assert {row["cause"] for row in detail["deliverables"]} == {"emit-brief"}


def test_the_same_session_may_keep_asking_its_own_task(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal is about reaching across, not about asking twice.

    A leader's follow-up on an older window of the same task is what
    `--brief-window` is for, and a re-import makes it the ordinary case.
    """
    var, a, window_a, _b, _window_b = _two_tasks(tmp_path, capsys)

    for _ in range(2):
        assert _followup(var, window_a, "--session", "sess-leader") == 0
    capsys.readouterr()

    detail = json.loads(_capture(var, a, capsys))
    assert [row["session_id"] for row in detail["sessions"]] == ["sess-leader"]
    assert sum(1 for row in detail["deliverables"] if row["cause"].startswith("query-locked")) == 2


def test_a_call_with_no_session_is_not_asked_the_question(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`session_id` is absent on the probe, on tests, and on the plain CLI.

    A rule that refused when it could not find an owner would refuse those, so
    the check only fires when a conversation is named and already placed.
    """
    var, _a, window_a, _b, _window_b = _two_tasks(tmp_path, capsys)
    assert _followup(var, window_a) == 0
    capsys.readouterr()
    assert session_owner(TaskStore(var), "") is None
    assert session_owner(TaskStore(var), "never-seen") is None


# -- a window belongs to one task -------------------------------------------


def test_a_task_cannot_claim_a_window_another_task_owns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other direction of the same binding.

    `Window.bind_task` has always refused to move a back-pointer that is set.
    `Task.bind_window` had no such guard, and adoption skipped the first check
    entirely when the window was already owned -- so the chain could gain a
    window that named someone else.
    """
    var, a, _window_a, b, window_b = _two_tasks(tmp_path, capsys)

    assert _followup(var, window_b, "--task", a) == 3
    assert "belongs to task" in capsys.readouterr().err

    detail = json.loads(_capture(var, a, capsys))
    assert [row["window_id"] for row in detail["windows"]] != [window_b]
    assert window_b not in [row["window_id"] for row in detail["windows"]]
    # The back-pointer never moved either, so the two directions still agree.
    assert (var / "windows" / window_b / "task").read_text().strip() == b


def test_adoption_still_claims_a_window_nobody_owns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Adoption on touch is the behaviour the guard must not cost.

    A window an operator drove straight through the CLI has no owner, and the
    first task that reaches it still takes it.
    """
    var = tmp_path / "var"
    fixtures = fixture_root(None)
    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()
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
    capsys.readouterr()

    assert main(["--var", str(var), "task-new", "--title", "补记", "--period", "2026-08"]) == 0
    task_id = _out(capsys)
    assert main(["--var", str(var), "--task", task_id, "record-questions", "--questions",
                 str(fixtures / "questions.json")]) == 0
    capsys.readouterr()

    detail = json.loads(_capture(var, task_id, capsys))
    assert len(detail["windows"]) == 1


def test_the_owner_scan_reads_the_store_it_was_given(tmp_path: Path) -> None:
    """An empty store answers, rather than raising on a missing directory."""
    assert session_owner(TaskStore(tmp_path / "var"), "sess-leader") is None


def test_record_session_refuses_directly_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The rule lives on the writer, so a library caller meets it as well."""
    var, a, window_a, b, _window_b = _two_tasks(tmp_path, capsys)
    assert _followup(var, window_a, "--session", "sess-leader") == 0
    capsys.readouterr()

    store = TaskStore(var)
    with pytest.raises(FoundryError, match="already belongs to task"):
        store.get(b).record_session("sess-leader", role="followup")
    # Its own task keeps accepting it, idempotently.
    assert store.get(a).record_session("sess-leader", role="followup")["session_id"] == "sess-leader"
