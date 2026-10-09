"""The packaged app must never download a DuckDB extension on its own."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pytest

from foundry import duckdb_offline

FOUNDRY = Path(__file__).resolve().parents[1] / "foundry"


def test_a_query_needing_an_extension_fails_instead_of_downloading(tmp_path: Path) -> None:
    connection = duckdb_offline.connect(str(tmp_path / "x.duckdb"))
    try:
        settings = connection.execute(
            "SELECT current_setting('autoinstall_known_extensions'), current_setting('autoload_known_extensions')"
        ).fetchone()
        assert settings == (False, False)
        # `read_xlsx` lives in the excel extension, which no build links in.
        with pytest.raises(duckdb.CatalogException):
            connection.execute("SELECT * FROM read_xlsx('missing.xlsx')")
    finally:
        connection.close()


def test_a_second_plain_connection_to_the_same_file_still_opens(tmp_path: Path) -> None:
    """SET, not config: DuckDB refuses two configs for one file in one process."""
    path = str(tmp_path / "x.duckdb")
    first = duckdb_offline.connect(path)
    first.execute("CREATE TABLE t (x INTEGER)")
    second = duckdb.connect(path)
    try:
        assert second.execute("SELECT count(*) FROM t").fetchone() == (0,)
    finally:
        second.close()
        first.close()


def test_every_connection_in_the_kit_turns_extension_downloads_off() -> None:
    """A bare `duckdb.connect(` must say why it is safe: config off, or the helper."""
    allowed = {
        "duckdb_offline.py",  # the helper itself
        "analysis_sql.py",  # CONFIG turns autoload and autoinstall off
        "analysis_parameters.py",  # config turns autoload and autoinstall off
    }
    offenders = [
        f"{path.name}:{number}"
        for path in sorted(FOUNDRY.glob("*.py"))
        if path.name not in allowed
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bduckdb\.connect\(", line)
    ]
    assert offenders == [], f"use duckdb_offline.connect: {offenders}"
