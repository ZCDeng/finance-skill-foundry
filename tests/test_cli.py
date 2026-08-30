from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from foundry.cli import main
from foundry.probe import fixture_root

COA_CSV = "account_code,account_name\n1001,Cash\n"
GL_CSV = "account_code,account_name,amount\n1001,Cash,10\n"


def _run_period_loop(var: Path, fixtures: Path, capsys: pytest.CaptureFixture[str]) -> str:
    """Drive create → import → lock → questions → brief, returning the window id."""
    assert main(["--var", str(var), "create"]) == 0
    window_id = capsys.readouterr().out.strip()
    assert (
        main(
            [
                "--var",
                str(var),
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
    assert main(["--var", str(var), "lock"]) == 0
    assert main(["--var", str(var), "record-questions", "--questions", str(fixtures / "questions.json")]) == 0
    assert main(["--var", str(var), "emit-brief"]) == 0
    capsys.readouterr()
    return window_id


def test_cli_period_loop_and_reimport(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixtures = fixture_root()
    var = tmp_path / "var"
    named = str(fixtures / "named.json")
    assert main(["--var", str(var), "create"]) == 0
    first_id = capsys.readouterr().out.strip()
    assert first_id
    assert (
        main(
            [
                "--var",
                str(var),
                "import",
                "--coa",
                str(fixtures / "coa.xlsx"),
                "--units",
                str(fixtures / "units.xlsx"),
                "--map",
                str(fixtures / "map.xlsx"),
                "--named",
                named,
                "--drop-dir",
                str(fixtures),
            ]
        )
        == 0
    )
    assert main(["--var", str(var), "lock"]) == 0
    assert main(["--var", str(var), "record-questions", "--questions", str(fixtures / "questions.json")]) == 0

    assert main(["--var", str(var), "emit-brief"]) == 0
    brief = capsys.readouterr().out
    assert "结论" in brief
    assert "稿外追问" not in brief

    assert main(["--var", str(var), "workpaper"]) == 0
    workpaper = capsys.readouterr().out
    assert "本期计算底稿" in workpaper
    assert first_id in workpaper

    assert main(["--var", str(var), "query-locked", "--text", "AR", "--tables", "ar"]) == 0
    answer = capsys.readouterr().out.strip()
    assert answer.startswith("稿外追问")
    assert "我重算" in answer
    # The answer names the window it was computed from (#19), then closes.
    assert answer.endswith(f"→ 40（窗口: {first_id}）")

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
                "--named",
                named,
                "--drop-dir",
                str(fixtures),
            ]
        )
        == 0
    )
    second_id = capsys.readouterr().out.strip()
    assert second_id and second_id != first_id
    assert (var / "current").read_text().strip() == second_id


def test_cli_named_envelope_supplies_defaults(tmp_path: Path) -> None:
    fixtures = fixture_root()
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    assert main(["--var", str(var), "import", "--named", str(fixtures / "named.json")]) == 0
    assert main(["--var", str(var), "lock"]) == 0


def test_cli_named_envelope_cannot_escape_its_directory(tmp_path: Path) -> None:
    var = tmp_path / "var"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("account_code,account_name,amount\n1001,Cash,1\n", encoding="utf-8")
    descriptor = bundle / "named.json"
    descriptor.write_text(
        json.dumps(
            {
                "coa": "../outside.csv",
                "tables": [{"id": "gl", "path": "../outside.csv"}],
            }
        ),
        encoding="utf-8",
    )

    assert main(["--var", str(var), "create"]) == 0
    assert main(["--var", str(var), "import", "--named", str(descriptor)]) == 3


def test_cli_symlinked_named_descriptor_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A symlinked descriptor would otherwise move the allowed-source boundary."""
    var = tmp_path / "var"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "coa.csv").write_text(COA_CSV, encoding="utf-8")
    (outside / "gl.csv").write_text(GL_CSV, encoding="utf-8")
    (outside / "named.json").write_text(
        json.dumps({"coa": "coa.csv", "tables": [{"id": "gl", "path": "gl.csv"}]}),
        encoding="utf-8",
    )
    drop = tmp_path / "drop"
    drop.mkdir()
    descriptor = drop / "named.json"
    os.symlink(outside / "named.json", descriptor)

    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()
    assert main(["--var", str(var), "import", "--named", str(descriptor)]) == 3
    assert "must not be a symlink" in capsys.readouterr().err


def test_cli_named_entry_without_path_refuses_instead_of_crashing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()
    assert main(["--var", str(var), "import", "--named", '[{"id": "gl"}]']) == 3
    err = capsys.readouterr().err
    assert err.strip() == "named table requires id and path"


def test_cli_named_scalar_payload_refuses_instead_of_crashing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()
    assert main(["--var", str(var), "import", "--named", "42"]) == 3
    err = capsys.readouterr().err
    assert "named payload must be" in err
    assert err.count("\n") == 1


def test_cli_named_dict_without_tables_key_names_the_missing_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixtures = fixture_root()
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()
    payload = json.dumps({"coa": str(fixtures / "coa.xlsx"), "gl": str(fixtures / "gl.xlsx")})
    assert main(["--var", str(var), "import", "--named", payload]) == 3
    err = capsys.readouterr().err
    assert "missing the tables key" in err
    assert "coa" in err
    assert "CoA is missing" not in err


def test_cli_named_id_to_path_map_still_loads(tmp_path: Path) -> None:
    fixtures = fixture_root()
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    payload = json.dumps({"gl": str(fixtures / "gl.xlsx"), "ar": str(fixtures / "ar.xlsx")})
    assert main(["--var", str(var), "import", "--coa", str(fixtures / "coa.xlsx"), "--named", payload]) == 0


def test_cli_inline_questions_json_refuses_instead_of_crashing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()
    assert main(["--var", str(var), "record-questions", "--questions", "{not json"]) == 3
    err = capsys.readouterr().err
    assert err.strip() == "questions argument is not valid JSON"


def test_cli_workpaper_reads_the_window_that_answered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixtures = fixture_root()
    var = tmp_path / "var"
    first_id = _run_period_loop(var, fixtures, capsys)

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
                "--named",
                str(fixtures / "named.json"),
                "--drop-dir",
                str(fixtures),
            ]
        )
        == 0
    )
    second_id = capsys.readouterr().out.strip()
    assert second_id != first_id

    assert (
        main(
            [
                "--var",
                str(var),
                "query-locked",
                "--brief-window",
                first_id,
                "--text",
                "AR 合计",
                "--tables",
                "ar",
            ]
        )
        == 0
    )
    assert "稿外追问" in capsys.readouterr().out

    # the successor window holds no workpaper yet
    assert main(["--var", str(var), "workpaper"]) == 3
    assert "workpaper not written" in capsys.readouterr().err

    assert main(["--var", str(var), "workpaper", "--window", first_id]) == 0
    printed = capsys.readouterr().out
    assert "本期计算底稿" in printed
    assert "稿外追问" in printed
    assert "AR 合计" in printed


def test_cli_workpaper_rejects_unknown_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()
    assert main(["--var", str(var), "workpaper", "--window", "nope"]) == 3
    assert "unknown window nope" in capsys.readouterr().err


def test_cli_refusal_exit_code_is_distinct_from_argparse_usage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()

    assert main(["--var", str(var), "lock"]) == 3
    assert capsys.readouterr().err.strip() == "no lockable catalog"

    with pytest.raises(SystemExit) as usage:
        main(["--var", str(var), "lock", "--nope"])
    assert usage.value.code == 2


# --- #40 a symlinked directory moves the boundary the same way -------------


def test_cli_named_descriptor_behind_a_symlinked_directory_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`drop/sub -> /outside` makes every file in the target a legal sibling."""
    var = tmp_path / "var"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "coa.csv").write_text(COA_CSV, encoding="utf-8")
    (outside / "gl.csv").write_text(GL_CSV, encoding="utf-8")
    (outside / "named.json").write_text(
        json.dumps({"coa": "coa.csv", "tables": [{"id": "gl", "path": "gl.csv"}]}),
        encoding="utf-8",
    )
    drop = tmp_path / "drop"
    drop.mkdir()
    os.symlink(outside, drop / "sub", target_is_directory=True)

    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()
    assert main(["--var", str(var), "import", "--named", str(drop / "sub" / "named.json")]) == 3
    assert "leaves its directory" in capsys.readouterr().err


def test_cli_drop_dir_behind_a_symlinked_directory_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The drop entry point must draw the boundary where --named draws it."""
    var = tmp_path / "var"
    outside = tmp_path / "outside" / "inner"
    outside.mkdir(parents=True)
    (outside / "coa.csv").write_text(COA_CSV, encoding="utf-8")
    (outside / "gl.csv").write_text(GL_CSV, encoding="utf-8")
    drop = tmp_path / "drop"
    drop.mkdir()
    os.symlink(tmp_path / "outside", drop / "sub", target_is_directory=True)

    assert main(["--var", str(var), "create"]) == 0
    capsys.readouterr()
    assert main(["--var", str(var), "import", "--drop-dir", str(drop / "sub" / "inner")]) == 3
    assert "leaves its directory" in capsys.readouterr().err


def test_cli_accepts_a_descriptor_under_an_in_place_symlink(tmp_path: Path) -> None:
    """A link that stays inside its own directory moves nothing; /tmp is one."""
    var = tmp_path / "var"
    real = tmp_path / "drop" / "real"
    real.mkdir(parents=True)
    (real / "coa.csv").write_text(COA_CSV, encoding="utf-8")
    (real / "gl.csv").write_text(GL_CSV, encoding="utf-8")
    (real / "named.json").write_text(
        json.dumps({"coa": "coa.csv", "tables": [{"id": "gl", "path": "gl.csv"}]}),
        encoding="utf-8",
    )
    os.symlink(real, tmp_path / "drop" / "alias", target_is_directory=True)

    assert main(["--var", str(var), "create"]) == 0
    assert main(["--var", str(var), "import", "--named", str(tmp_path / "drop" / "alias" / "named.json")]) == 0
    assert main(["--var", str(var), "lock"]) == 0


# --- #5 residual: --var is operator input too -------------------------------


def test_cli_refuses_an_unusable_var_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    not_a_dir = tmp_path / "notadir.txt"
    not_a_dir.write_text("", encoding="utf-8")

    assert main(["--var", str(not_a_dir), "create"]) == 3
    err = capsys.readouterr().err
    assert "--var is not a usable directory" in err
    assert "Traceback" not in err


# --- #32 residual: an explicit window id is the whole address ---------------


def test_cli_workpaper_by_window_id_without_a_current_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    var = tmp_path / "var"
    fixtures = fixture_root(None)
    window_id = _run_period_loop(var, fixtures, capsys)
    assert main(["--var", str(var), "workpaper", "--window", window_id]) == 0
    capsys.readouterr()

    (var / "current").unlink()
    assert main(["--var", str(var), "workpaper", "--window", window_id]) == 0
    assert "本期计算底稿" in capsys.readouterr().out

    assert main(["--var", str(var), "workpaper"]) == 3
    assert "no current window" in capsys.readouterr().err
