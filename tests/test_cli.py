from __future__ import annotations

import json
from pathlib import Path

from foundry.cli import main
from foundry.probe import fixture_root


def test_cli_period_loop_and_reimport(tmp_path: Path) -> None:
    fixtures = fixture_root()
    var = tmp_path / "var"
    named = json.dumps(
        [
            {"id": "gl", "path": str(fixtures / "gl.xlsx")},
            {"id": "ar", "path": str(fixtures / "ar.xlsx")},
        ]
    )
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
