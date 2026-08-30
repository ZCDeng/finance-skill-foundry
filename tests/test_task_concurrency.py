"""The task store's append paths are read-modify-write, so they run under a lock.

`register_deliverable` derives the next `seq` from the rows already on disk, so
two processes that read before either writes both reach the same number and the
timeline ends up with two rows claiming one seq. Dropping the lock fails the test
below on every run at four writers, which is what makes it a race test rather
than a hopeful one.

`bind_window` and `record_session` are the same read-modify-write under the same
lock, but their duplicate window is one file read wide instead of a read plus a
hash plus an artifact write. Unlocked, they only sometimes duplicate -- around
one run in three at twelve writers -- so a race test for them would be a test
that sometimes lies. Their idempotence is pinned directly in `test_task.py`
instead, and the lock they share with the assertion below is what carries them
across processes.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

from foundry.task import TaskStore

WRITERS = 4


def _task(tmp_path: Path):
    store = TaskStore(tmp_path / "var")
    return store, store.create(title="并发")


def _run(script: str, args: list[list[str]]) -> None:
    start = f"{time.time() + 1.0:.6f}"
    children = [
        subprocess.Popen([sys.executable, "-c", script, start, *extra]) for extra in args
    ]
    for child in children:
        assert child.wait(timeout=60) == 0


def test_concurrent_deliverables_get_distinct_sequence_numbers(tmp_path: Path) -> None:
    store, task = _task(tmp_path)
    script = textwrap.dedent(
        f"""
        from pathlib import Path
        import sys
        import time
        from foundry.task import TaskStore

        start = float(sys.argv[1])
        task = TaskStore(Path({str(store.var_root)!r})).get({task.id!r})
        while time.time() < start:
            time.sleep(0.005)
        task.register_deliverable(
            window_id="w1", kind="workpaper", text=sys.argv[2], cause=sys.argv[3]
        )
        """
    )
    _run(script, [[f"底稿 {index}\n", f"query-locked:followup-{index}"] for index in range(WRITERS)])

    rows = task.deliverables()
    assert len(rows) == WRITERS
    assert sorted(row["seq"] for row in rows) == list(range(1, WRITERS + 1))
    assert len({row["sha256"] for row in rows}) == WRITERS
    for row in rows:
        assert task.artifact_text(row["sha256"])
