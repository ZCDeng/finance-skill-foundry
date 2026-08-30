"""Regressions for the workpaper: #26 (one locked follow-up transaction) and
#36 (the 锁哈希 line must pin every source that produced the numbers)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from openpyxl import Workbook

from foundry.brief import emit_brief
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.window import WindowStore
from foundry.workpaper import _hash_line


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


def _briefed(tmp_path: Path):
    drop = tmp_path / "drop"
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(
        coa=_xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]]),
        units=_xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]]),
        named=[
            {"id": "gl", "path": _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])},
            {"id": "ar", "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["1001", 40]])},
        ],
        drop_dir=drop,
    )
    window.lock()
    record_questions(window, [{"id": "q1", "text": "GL 合计", "required_table_ids": ["gl"]}])
    emit_brief(window)
    return store, window


def _hold_lock(lock_path: Path, ready: Path, seconds: float) -> subprocess.Popen[bytes]:
    script = textwrap.dedent(
        f"""
        from pathlib import Path
        import time
        from foundry.locking import exclusive

        with exclusive(Path({str(lock_path)!r})):
            Path({str(ready)!r}).write_text("held")
            time.sleep({seconds})
        """
    )
    return subprocess.Popen([sys.executable, "-c", script])


def test_followup_waits_for_the_window_lock(tmp_path: Path) -> None:
    """#26 -- id allocation, the jsonl append, the schedule and the workpaper are
    one transaction, so a follow-up cannot start while another holds the window."""
    _, window = _briefed(tmp_path)
    ready = tmp_path / "held"
    child = _hold_lock(window.root / ".lock", ready, 0.8)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "lock holder never started"
        started = time.monotonic()
        answer = query_locked(window, "AR 合计", required_table_ids=["ar"])
        waited = time.monotonic() - started
    finally:
        child.wait(timeout=30)

    assert answer.startswith("稿外追问")
    assert waited >= 0.3, f"follow-up did not wait for the window lock (waited {waited:.3f}s)"
    payload = json.loads(window.schedules_path.read_text())
    assert [item["id"] for item in payload["items"] if item["origin"] == "followup"] == ["followup-1"]


def test_concurrent_followups_keep_both_schedule_items(tmp_path: Path) -> None:
    """#26 -- two simultaneous follow-ups must not both allocate followup-1 and
    then overwrite each other's schedule list."""
    _, window = _briefed(tmp_path)
    var_root = window.store.var_root
    script = textwrap.dedent(
        f"""
        from pathlib import Path
        import sys
        import time
        from foundry.query import query_locked
        from foundry.window import WindowStore

        start = float(sys.argv[1])
        window = WindowStore(Path({str(var_root)!r})).get({window.id!r})
        while time.time() < start:
            time.sleep(0.005)
        query_locked(window, sys.argv[2], required_table_ids=["ar"])
        """
    )
    start = f"{time.time() + 1.0:.6f}"
    children = [
        subprocess.Popen([sys.executable, "-c", script, start, f"AR 追问 {index}"])
        for index in range(2)
    ]
    for child in children:
        assert child.wait(timeout=60) == 0

    payload = json.loads(window.schedules_path.read_text())
    followups = [item for item in payload["items"] if item["origin"] == "followup"]
    assert sorted(item["id"] for item in followups) == ["followup-1", "followup-2"]
    assert len({item["text"] for item in followups}) == 2
    paper = window.workpaper_path.read_text()
    assert "followup-1" in paper and "followup-2" in paper
    assert len(window.followup_path.read_text().strip().splitlines()) == 2


def test_hash_line_carries_the_units_digest(tmp_path: Path) -> None:
    """#36 -- units produced the aux the numbers were cut by; the line must pin it."""
    _, window = _briefed(tmp_path)
    hashes = window.hashes()
    assert hashes["units"], "fixture did not import a units file"

    paper = window.workpaper_path.read_text()

    assert f"units={hashes['units']}" in paper


def test_hash_line_marks_a_units_derived_aux() -> None:
    """#36 -- a units-derived aux digest is a loaded-table hash, not a file hash.

    `Window.hashes()` may report the kind as a sibling key, inside the aux entry
    or under `aux_loaded`; whichever shape arrives, the label must not claim the
    digest belongs to an aux file on disk.
    """
    assert "aux(derived)=abc" in _hash_line({"aux": "abc", "aux_derived_from": "units"})
    assert "aux(derived)=abc" in _hash_line({"aux": {"loaded_hash": "abc", "derived_from": "units"}})
    assert "aux(derived)=abc" in _hash_line({"aux_loaded": "abc"})
    # A manifest written before derived_from existed carries no marker of its
    # own; hashes() still classifies it from the missing source digest.
    assert "aux(derived)=abc" in _hash_line({"aux": "abc", "aux_kind": "derived"})
    assert "aux(derived)=abc" in _hash_line({"aux": {"loaded_hash": "abc"}})
    assert "aux=abc" in _hash_line({"aux": "abc"})
    assert "aux=abc" in _hash_line({"aux": {"source_hash": "abc"}})
    assert "aux" not in _hash_line({"coa": "c", "map": None})
