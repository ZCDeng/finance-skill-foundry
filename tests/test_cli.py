from __future__ import annotations

import json
from pathlib import Path

from foundry.cli import main
from foundry.probe import fixture_root


def test_cli_period_loop_and_reimport(tmp_path: Path) -> None:
    fixtures = fixture_root()
    var = tmp_path / "var"
    named = str(fixtures / "named.json")
    assert main(["--var", str(var), "create"]) == 0
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
    assert main(["--var", str(var), "workpaper"]) == 0
    assert main(["--var", str(var), "query-locked", "--text", "AR", "--tables", "ar"]) == 0
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
    assert (var / "current").exists()


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
    assert main(["--var", str(var), "import", "--named", str(descriptor)]) == 2
