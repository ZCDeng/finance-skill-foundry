from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.brief import emit_brief
from foundry.errors import LockRefused
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.window import WindowStore


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


def _coa(drop: Path) -> Path:
    return _xlsx(
        drop / "coa.xlsx",
        ["account_code", "account_name"],
        [["1001", "Cash"], ["6001", "Revenue"]],
    )


def _units(drop: Path) -> Path:
    return _xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "华东"], ["OU2", "华南"]])


def _gl(drop: Path, amount: int = 100) -> Path:
    return _xlsx(
        drop / "gl.xlsx",
        ["account_code", "unit_id", "amount"],
        [["6001", "OU1", amount], ["6001", "OU2", amount * 2]],
    )


def _imported(tmp_path: Path):
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        units=_units(drop),
        named=[{"id": "gl", "path": _gl(drop)}],
        drop_dir=drop,
    )
    return drop, window


def test_import_archives_every_source_it_parsed(tmp_path: Path) -> None:
    drop, window = _imported(tmp_path)
    archived = sorted(path.name for path in window.inputs_dir.iterdir())
    assert archived == ["coa.xlsx", "gl.xlsx", "units.xlsx"]
    manifest = json.loads(window.lock_path.read_text())
    assert manifest["coa"]["archived"] == "inputs/coa.xlsx"
    assert manifest["named"]["gl"]["archived"] == "inputs/gl.xlsx"
    assert manifest["units"]["archived"] == "inputs/units.xlsx"
    # The operator's own path stays on the manifest for display; it is no longer
    # what anything reads.
    assert manifest["coa"]["path"] == str(drop / "coa.xlsx")


def test_a_window_whose_sources_are_gone_still_locks_and_reports(tmp_path: Path) -> None:
    """The whole point of the archive.

    She exports from the ERP into Downloads, imports, and empties Downloads. The
    window has to keep working, and an auditor has to still be able to open the
    workbook the numbers came from.
    """
    drop, window = _imported(tmp_path)
    shutil.rmtree(drop)
    window.lock()
    record_questions(window, [{"id": "q1", "text": "收入合计", "required_table_ids": ["gl"]}])
    brief = emit_brief(window)
    assert "300" in brief
    assert window.workpaper_path.exists()
    answer = query_locked(window, "按单元拆收入", required_table_ids=["gl"], split_by="unit_id")
    assert "OU1=100" in answer
    assert (window.inputs_dir / "gl.xlsx").is_file()


def test_editing_a_source_between_import_and_lock_still_refuses(tmp_path: Path) -> None:
    """Archiving must not turn a caliber change into a silent no-op.

    She edited the units file after importing it. Locking the imported bytes
    anyway would ship the version she just replaced, without saying so.
    """
    drop, window = _imported(tmp_path)
    _xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU9", "改过了"]])
    with pytest.raises(LockRefused, match="source hash changed for units; re-import"):
        window.lock()


def test_a_tampered_archive_refuses_the_lock(tmp_path: Path) -> None:
    _, window = _imported(tmp_path)
    (window.inputs_dir / "gl.xlsx").write_bytes(b"not a workbook")
    with pytest.raises(LockRefused, match="archived input changed for gl"):
        window.lock()


def test_a_second_import_replaces_the_archive_whole(tmp_path: Path) -> None:
    """A named table dropped on re-run must not leave its bytes behind.

    A stale archive entry would describe an input this window does not hold,
    which is exactly the claim the archive exists to make honest.
    """
    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(
        coa=_coa(drop),
        named=[{"id": "gl", "path": _gl(drop)}, {"id": "ar", "path": _xlsx(drop / "ar.xlsx", ["account_code", "amount"], [["1001", 5]])}],
        drop_dir=drop,
    )
    assert (window.inputs_dir / "ar.xlsx").is_file()
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}])
    assert sorted(path.name for path in window.inputs_dir.iterdir()) == ["coa.xlsx", "gl.xlsx"]


def test_a_failed_second_import_keeps_the_previous_archive(tmp_path: Path) -> None:
    drop, window = _imported(tmp_path)
    before = (window.inputs_dir / "gl.xlsx").read_bytes()
    empty = _xlsx(drop / "empty.xlsx", ["account_code", "amount"], [])
    with pytest.raises(LockRefused):
        window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": empty}])
    assert (window.inputs_dir / "gl.xlsx").read_bytes() == before
    assert not (window.root / "inputs.staging").exists()


def test_an_unreadable_format_refuses_naming_the_operators_file(tmp_path: Path) -> None:
    """Refuse before copying, while the message can still name what she pointed at."""
    drop = tmp_path / "drop"
    drop.mkdir(parents=True, exist_ok=True)
    bad = drop / "gl.txt"
    bad.write_text("account_code,amount\n1001,1\n")
    window = WindowStore(tmp_path / "var").create()
    with pytest.raises(LockRefused, match=r"unsupported import format: \.txt"):
        window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": bad}])
    assert not window.inputs_dir.exists()


def test_the_archive_is_what_gets_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins the ordering, not just the outcome.

    Copy first, parse the copy. Reading the operator's file for the rows and the
    copy only for the digest would pass every test above and still leave the
    manifest describing bytes the catalog never saw.
    """
    import foundry.window as window_module

    drop = tmp_path / "drop"
    window = WindowStore(tmp_path / "var").create()
    parsed: list[Path] = []
    real = window_module.load_tabular

    def record(path: Path):  # type: ignore[no-untyped-def]
        parsed.append(Path(path))
        return real(path)

    monkeypatch.setattr(window_module, "load_tabular", record)
    window.import_tables(coa=_coa(drop), named=[{"id": "gl", "path": _gl(drop)}], drop_dir=drop)
    staging = window.root / "inputs.staging"
    assert parsed and all(path.parent == staging for path in parsed)
