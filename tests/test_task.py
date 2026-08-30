from __future__ import annotations

from pathlib import Path

import pytest

from foundry.errors import FoundryError
from foundry.task import TaskStore, resolve_task


def _store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path / "var")


def test_create_lists_and_becomes_current(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.create(title="2026-08 月度经营分析", period="2026-08")
    assert store.current() is not None
    assert store.current().id == task.id
    listed = store.list()
    assert [item.id for item in listed] == [task.id]
    assert listed[0].meta()["title"] == "2026-08 月度经营分析"
    assert listed[0].meta()["period"] == "2026-08"


def test_blank_title_refuses(tmp_path: Path) -> None:
    with pytest.raises(FoundryError, match="task title is required"):
        _store(tmp_path).create(title="   ")


def test_unknown_task_id_refuses_by_name(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(FoundryError, match="not a task id"):
        store.get("nope")
    with pytest.raises(FoundryError, match="no such task"):
        store.get("0" * 32)


def test_bind_window_is_idempotent_and_keeps_the_first_reason(tmp_path: Path) -> None:
    """Adoption-on-touch calls this on every later step, so it must not grow rows.

    The reason matters too: a window that entered as the initial import does not
    become a re-import because a follow-up touched it three days later.
    """
    task = _store(tmp_path).create(title="T")
    first = task.bind_window("w1", reason="initial")
    again = task.bind_window("w1", reason="reimport")
    assert again == first
    task.bind_window("w2", reason="reimport")
    assert [(row["window_id"], row["reason"]) for row in task.windows()] == [
        ("w1", "initial"),
        ("w2", "reimport"),
    ]


def test_bind_window_refuses_an_unknown_reason(tmp_path: Path) -> None:
    task = _store(tmp_path).create(title="T")
    with pytest.raises(FoundryError, match="window reason must be one of"):
        task.bind_window("w1", reason="whatever")


def test_record_session_keeps_the_leaders_own_words(tmp_path: Path) -> None:
    """A session seen first through a tool call has no verbatim; filling it in later fills a hole.

    The two columns are the point. What the leader asked is written by the
    operator; what the machine computed arrives separately as the tool's own
    text, and neither is derived from the other.
    """
    task = _store(tmp_path).create(title="T")
    seen = task.record_session("sess-1", role="followup")
    assert "leader_verbatim" not in seen
    filled = task.record_session("sess-1", role="followup", leader_verbatim="华东为什么掉了？")
    assert filled["leader_verbatim"] == "华东为什么掉了？"
    assert filled["opened_at"] == seen["opened_at"]
    assert len(task.sessions()) == 1
    kept = task.record_session("sess-1", role="followup", leader_verbatim="改写过的问法")
    assert kept["leader_verbatim"] == "华东为什么掉了？"


def test_record_session_refuses_an_unknown_role(tmp_path: Path) -> None:
    task = _store(tmp_path).create(title="T")
    with pytest.raises(FoundryError, match="session role must be one of"):
        task.record_session("sess-1", role="leader")


def test_deliverable_versions_are_content_addressed(tmp_path: Path) -> None:
    task = _store(tmp_path).create(title="T")
    first = task.register_deliverable(
        window_id="w1", kind="workpaper", text="v1\n", cause="emit-brief"
    )
    second = task.register_deliverable(
        window_id="w1", kind="workpaper", text="v1 加一张附表\n", cause="query-locked:followup-1"
    )
    assert first["seq"] == 1
    assert second["seq"] == 2
    assert first["sha256"] != second["sha256"]
    assert task.artifact_text(first["sha256"]) == "v1\n"
    assert task.artifact_text(second["sha256"]) == "v1 加一张附表\n"
    assert second["cause"] == "query-locked:followup-1"


def test_re_registering_identical_bytes_adds_no_version(tmp_path: Path) -> None:
    """A re-render that changed nothing is not a version, and saying it is would lie."""
    task = _store(tmp_path).create(title="T")
    first = task.register_deliverable(window_id="w1", kind="brief", text="same\n", cause="emit-brief")
    again = task.register_deliverable(window_id="w1", kind="brief", text="same\n", cause="emit-brief")
    assert again == first
    assert len(task.deliverables()) == 1


def test_the_same_bytes_on_two_windows_are_two_versions(tmp_path: Path) -> None:
    """Dedupe is per window. Two windows that produced identical text both produced it."""
    task = _store(tmp_path).create(title="T")
    task.register_deliverable(window_id="w1", kind="brief", text="same\n", cause="emit-brief")
    task.register_deliverable(window_id="w2", kind="brief", text="same\n", cause="emit-brief")
    assert [row["window_id"] for row in task.deliverables()] == ["w1", "w2"]


def test_deliverable_refuses_an_unknown_kind(tmp_path: Path) -> None:
    task = _store(tmp_path).create(title="T")
    with pytest.raises(FoundryError, match="deliverable kind must be one of"):
        task.register_deliverable(window_id="w1", kind="pivot", text="x", cause="c")


def test_missing_artifact_refuses_by_name(tmp_path: Path) -> None:
    task = _store(tmp_path).create(title="T")
    with pytest.raises(FoundryError, match="no archived deliverable"):
        task.artifact_text("f" * 64)


def test_resolve_task_prefers_explicit_then_env_then_back_pointer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    explicit = store.create(title="explicit", make_current=False)
    from_env = store.create(title="env", make_current=False)
    back = store.create(title="back", make_current=False)
    env = {"FOUNDRY_TASK": from_env.id}

    picked = resolve_task(store, explicit=explicit.id, window_task_ids=(back.id,), env=env)
    assert picked is not None and picked.id == explicit.id

    picked = resolve_task(store, window_task_ids=(back.id,), env=env)
    assert picked is not None and picked.id == from_env.id

    picked = resolve_task(store, window_task_ids=(back.id,), env={})
    assert picked is not None and picked.id == back.id

    assert resolve_task(store, window_task_ids=(None,), env={}) is None


def test_resolve_task_skips_an_unbound_window_and_takes_the_next(tmp_path: Path) -> None:
    """The follow-up case: the brief's window is asked first, the current one second."""
    store = _store(tmp_path)
    task = store.create(title="T", make_current=False)
    picked = resolve_task(store, window_task_ids=(None, task.id), env={})
    assert picked is not None and picked.id == task.id
