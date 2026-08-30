from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.cli import main
from foundry.errors import FoundryError, LockRefused, QueryRefused
from foundry.harness import DROP_EXTS, LINE_LEAKS, file_upload_companion, harness_text, map_drop
from foundry.host_profile import REQUIRED_TOOLS, HostProfile
from foundry.window import WindowStore

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "dsh-plugin" / "package.json"
OVERLAY = ROOT / "dsh-plugin" / "file-upload.overlay.yml"
FIXTURES = ROOT / "fixtures" / "period-smoke"


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


def test_companion_is_pinned_input_drop() -> None:
    companion = file_upload_companion()
    declared = json.loads(PACKAGE.read_text())["dsh"]["foundry"]["companions"]["file-upload"]
    assert companion == declared
    assert companion["package"] == "dsh-file-upload"
    assert companion["version"] == "0.4.3"
    assert companion["role"] == "input-drop"
    assert LINE_LEAKS <= set(companion["omitTools"])
    assert companion["config"]["allowedExtensions"] == ["xlsx", "csv", "json"]
    assert companion["config"]["inlineTextLimit"] == 0
    assert OVERLAY.is_file()
    overlay = OVERLAY.read_text()
    assert "read_document" in overlay
    assert "input drop" in overlay


def test_period_and_f3_omit_read_document() -> None:
    foundry = json.loads(PACKAGE.read_text())["dsh"]["foundry"]
    assert "read_document" in foundry["profiles"]["period"]["omit"]
    assert "read_document" in foundry["profiles"]["f3"]["omit"]
    assert ".dsh-uploads" in foundry["profiles"]["f3"]["deny_paths"]


def test_startup_fails_if_read_document_mounted() -> None:
    with pytest.raises(FoundryError, match="line leak"):
        HostProfile("period", [*REQUIRED_TOOLS, "read_document"])


def test_f3_denies_read_document_and_upload_path(tmp_path: Path) -> None:
    f3 = HostProfile.f3()
    with pytest.raises(QueryRefused, match="read_document"):
        f3.execute(WindowStore(tmp_path / "var").create(), "read_document")
    assert f3.deny_path(tmp_path / ".dsh-uploads" / "coa.xlsx") is True


def test_map_drop_uses_reserved_stems(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]])
    _xlsx(drop / "aux.xlsx", ["dim_id", "dim_name", "member_id", "member_name"], [["unit", "Unit", "OU1", "North"]])
    _xlsx(drop / "map.xlsx", ["source_account_code", "analysis_node_id", "analysis_node_name"], [["1001", "cash", "Cash"]])
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 70]])
    (drop / "notes.txt").write_text("ignore")
    (drop / "questions.json").write_text("[]")
    mapped = map_drop(drop)
    assert mapped.coa == drop / "coa.xlsx"
    assert mapped.aux == drop / "aux.xlsx"
    assert mapped.map == drop / "map.xlsx"
    assert mapped.units is None
    assert mapped.named == [{"id": "gl", "path": drop / "gl.xlsx"}]
    assert "notes.txt" in mapped.skipped


def test_map_drop_refuses_duplicate_stems(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 1]])
    (drop / "gl.csv").write_text("account_code,amount\n1001,2\n")
    with pytest.raises(LockRefused, match="two files"):
        map_drop(drop)


def test_map_drop_refuses_symlinks(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    drop.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("account_code,amount\n1001,1\n", encoding="utf-8")
    (drop / "gl.csv").symlink_to(outside)

    with pytest.raises(LockRefused, match="symlink"):
        map_drop(drop)


def test_map_drop_refuses_a_symlinked_drop_root(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    _xlsx(outside / "gl.xlsx", ["account_code", "amount"], [["1001", 1]])
    drop = tmp_path / "uploads"
    drop.symlink_to(outside, target_is_directory=True)

    with pytest.raises(LockRefused, match="symlink"):
        map_drop(drop)


def test_import_from_upload_drop_only(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]])
    _xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]])
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(drop_dir=drop)
    window.lock()
    assert "gl" in window.table_names()
    assert "coa" in window.table_names()
    assert "units" in window.table_names()


def test_explicit_named_does_not_absorb_drop_extras() -> None:
    from foundry.harness import merge_import_sources

    mapped = map_drop(FIXTURES)
    assert mapped.coa == FIXTURES / "coa.xlsx"
    assert {item["id"] for item in mapped.named} >= {"gl", "ar", "notes"}
    store_named = [{"id": "gl", "path": FIXTURES / "gl.xlsx"}]
    resolved = merge_import_sources(
        coa=None,
        named=store_named,
        aux=None,
        map=None,
        units=None,
        drop_dir=FIXTURES,
    )
    assert resolved.named == store_named
    assert resolved.coa == FIXTURES / "coa.xlsx"


def test_cli_harness_prints_pin(tmp_path: Path) -> None:
    assert main(["--var", str(tmp_path / "var"), "harness"]) == 0
    text = harness_text()
    assert "dsh-file-upload@0.4.3" in text
    assert "input-drop" in text
    assert "read_document" in text


def test_cli_import_from_drop_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]])
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 40]])
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    assert main(["--var", str(var), "import", "--drop-dir", str(drop)]) == 0
    capsys.readouterr()
    assert (var / "current").exists()


def test_drop_exts_match_catalog() -> None:
    assert DROP_EXTS == {".xlsx", ".csv", ".json"}


def test_import_json_from_upload_drop(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]])
    (drop / "gl.json").write_text(json.dumps([{"account_code": "1001", "amount": "12.50"}]))
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(drop_dir=drop)
    window.lock()
    assert window.query("SELECT SUM(amount) FROM gl")[0][0].to_eng_string() == "12.50"
