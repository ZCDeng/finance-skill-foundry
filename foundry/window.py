from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from foundry.catalog import (
    checkpoint_and_close,
    file_hash,
    load_tabular,
    quote_ident,
    require_columns,
    table_hash,
    write_table,
)
from foundry.errors import LockRefused, WindowBusy

STATES = ("Open", "Imported", "Locked", "Briefed", "FollowUp")
QUERYABLE = {"Locked", "Briefed", "FollowUp"}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


@dataclass
class Handle:
    window: Window
    name: str

    def release(self) -> None:
        self.window.release_handle(self.name)


class WindowStore:
    def __init__(self, var_root: Path) -> None:
        self.var_root = Path(var_root)
        self.windows_dir = self.var_root / "windows"
        self.formulator_dir = self.var_root / "formulator"
        self.skills_dir = self.var_root / "skills"
        self.current_path = self.var_root / "current"
        self.windows_dir.mkdir(parents=True, exist_ok=True)
        self.formulator_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def create(self) -> Window:
        window_id = uuid.uuid4().hex
        root = self.windows_dir / window_id
        root.mkdir(parents=True, exist_ok=True)
        window = Window(self, window_id)
        window._set_state("Open")
        self._set_current(window_id)
        return window

    def get(self, window_id: str) -> Window:
        root = self.windows_dir / window_id
        if not root.is_dir():
            raise LockRefused(f"unknown window {window_id}")
        return Window(self, window_id)

    def current(self) -> Window:
        if not self.current_path.exists():
            raise LockRefused("no current window")
        return self.get(self.current_path.read_text().strip())

    def _set_current(self, window_id: str) -> None:
        self.current_path.write_text(window_id + "\n")


class Window:
    def __init__(self, store: WindowStore, window_id: str) -> None:
        self.store = store
        self.id = window_id
        self.root = store.windows_dir / window_id
        self._write_con: duckdb.DuckDBPyConnection | None = None
        self._ro_con: duckdb.DuckDBPyConnection | None = None

    def catalog_path(self) -> Path:
        return self.root / "catalog.duckdb"

    @property
    def lock_path(self) -> Path:
        return self.root / "lock.json"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    @property
    def handles_path(self) -> Path:
        return self.root / "handles.json"

    @property
    def extras_path(self) -> Path:
        return self.root / "extras.json"

    @property
    def questions_path(self) -> Path:
        return self.root / "questions.json"

    @property
    def brief_path(self) -> Path:
        return self.root / "brief.md"

    @property
    def followup_path(self) -> Path:
        return self.root / "followup.jsonl"

    @property
    def state(self) -> str:
        data = _read_json(self.state_path, {"state": "Open"})
        return str(data["state"])

    def _set_state(self, state: str) -> None:
        _write_json(self.state_path, {"state": state})

    def import_tables(
        self,
        *,
        coa: Path,
        units: Path,
        named: list[dict[str, Any]],
        drop_dir: Path | None = None,
    ) -> dict[str, Any]:
        if self.state not in {"Open", "Imported"}:
            raise LockRefused("import only before lock")
        if not named:
            raise LockRefused("named-table list is empty")
        staging = self.root / "catalog.duckdb.staging"
        staging.unlink(missing_ok=True)
        wal = Path(str(staging) + ".wal")
        wal.unlink(missing_ok=True)
        con = duckdb.connect(str(staging))
        try:
            manifest = self._load_into(con, coa=Path(coa), units=Path(units), named=named)
        except Exception:
            con.close()
            staging.unlink(missing_ok=True)
            wal.unlink(missing_ok=True)
            raise
        checkpoint_and_close(con)
        wal.unlink(missing_ok=True)
        target = self.catalog_path()
        target.unlink(missing_ok=True)
        staging.replace(target)
        _write_json(self.lock_path, {**manifest, "locked": False})
        extras = self._list_extras(drop_dir, coa=Path(coa), units=Path(units), named=named)
        _write_json(self.extras_path, extras)
        self._set_state("Imported")
        return manifest

    def _load_into(
        self,
        con: duckdb.DuckDBPyConnection,
        *,
        coa: Path,
        units: Path,
        named: list[dict[str, Any]],
    ) -> dict[str, Any]:
        coa_headers, coa_rows = load_tabular(coa)
        require_columns(coa_headers, ["account_code", "account_name"], "CoA")
        if not coa_rows:
            raise LockRefused("CoA is empty")
        units_headers, units_rows = load_tabular(units)
        require_columns(units_headers, ["unit_id", "unit_name"], "units")
        if not units_rows:
            raise LockRefused("units are empty")
        write_table(con, "coa", coa_headers, coa_rows)
        write_table(con, "units", units_headers, units_rows)
        named_meta: dict[str, Any] = {}
        for item in named:
            table_id = str(item["id"])
            path = Path(item["path"])
            headers, rows = load_tabular(path)
            if not rows:
                raise LockRefused(f"named table {table_id} has zero rows")
            write_table(con, table_id, headers, rows)
            named_meta[table_id] = {
                "path": str(path),
                "source_hash": file_hash(path),
                "loaded_hash": self._live_hash(con, table_id),
            }
        return {
            "window_id": self.id,
            "coa": {
                "path": str(coa),
                "source_hash": file_hash(coa),
                "loaded_hash": self._live_hash(con, "coa"),
            },
            "units": {
                "path": str(units),
                "source_hash": file_hash(units),
                "loaded_hash": self._live_hash(con, "units"),
            },
            "named": named_meta,
        }

    def lock(self) -> dict[str, Any]:
        if self.state == "Locked" or self.lock_path.exists() and _read_json(self.lock_path, {}).get("locked"):
            raise LockRefused("already locked; re-import to take a source edit")
        if self.state != "Imported" or not self.catalog_path().exists():
            raise LockRefused("no lockable catalog")
        manifest = _read_json(self.lock_path, {})
        if not manifest.get("named"):
            raise LockRefused("named-table list is empty")
        con = duckdb.connect(str(self.catalog_path()))
        try:
            for table_id, meta in manifest["named"].items():
                count = con.execute(f"SELECT COUNT(*) FROM {quote_ident(table_id)}").fetchone()
                if not count or count[0] == 0:
                    raise LockRefused(f"named table {table_id} has zero rows")
                live = self._live_hash(con, table_id)
                if live != meta["loaded_hash"]:
                    raise LockRefused(f"loaded hash does not match source for {table_id}")
        finally:
            checkpoint_and_close(con)
        self._write_con = None
        self._ro_con = duckdb.connect(str(self.catalog_path()), read_only=True)
        manifest["locked"] = True
        _write_json(self.lock_path, manifest)
        self._set_state("Locked")
        return manifest

    def _live_hash(self, con: duckdb.DuckDBPyConnection, table: str) -> str:
        rel = con.execute(f"SELECT * FROM {quote_ident(table)}").fetchall()
        headers = [d[0] for d in con.description or []]
        return table_hash(headers, [tuple(row) for row in rel])

    def hashes(self) -> dict[str, Any]:
        manifest = _read_json(self.lock_path, {})
        return {
            "coa": manifest.get("coa", {}).get("source_hash"),
            "units": manifest.get("units", {}).get("source_hash"),
            "named": {k: v.get("source_hash") for k, v in manifest.get("named", {}).items()},
        }

    def extras(self) -> list[str]:
        return list(_read_json(self.extras_path, []))

    def table_names(self) -> list[str]:
        con = self._reader()
        rows = con.execute("SHOW TABLES").fetchall()
        return [str(row[0]) for row in rows]

    def query(self, sql: str) -> list[tuple[Any, ...]]:
        if self.state not in QUERYABLE:
            raise LockRefused(f"query refused in state {self.state}")
        return [tuple(row) for row in self._reader().execute(sql).fetchall()]

    def write_sql(self, sql: str) -> None:
        if self.state in QUERYABLE:
            raise LockRefused("catalog is read-only after lock")
        if self._write_con is None:
            self._write_con = duckdb.connect(str(self.catalog_path()))
        self._write_con.execute(sql)

    def register_handle(self, name: str) -> Handle:
        handles = set(_read_json(self.handles_path, []))
        handles.add(name)
        _write_json(self.handles_path, sorted(handles))
        return Handle(self, name)

    def release_handle(self, name: str) -> None:
        handles = set(_read_json(self.handles_path, []))
        handles.discard(name)
        _write_json(self.handles_path, sorted(handles))

    def reimport(
        self,
        *,
        coa: Path,
        units: Path,
        named: list[dict[str, Any]],
        drop_dir: Path | None = None,
    ) -> Window:
        handles = _read_json(self.handles_path, [])
        if handles:
            raise WindowBusy(f"read handles remain: {handles}")
        if self._ro_con is not None:
            self._ro_con.close()
            self._ro_con = None
        nxt = self.store.create()
        nxt.import_tables(coa=coa, units=units, named=named, drop_dir=drop_dir)
        return nxt

    def _reader(self) -> duckdb.DuckDBPyConnection:
        if self.state not in QUERYABLE:
            raise LockRefused(f"catalog not readable in state {self.state}")
        if self._ro_con is None:
            self._ro_con = duckdb.connect(str(self.catalog_path()), read_only=True)
        return self._ro_con

    def _list_extras(
        self,
        drop_dir: Path | None,
        *,
        coa: Path,
        units: Path,
        named: list[dict[str, Any]],
    ) -> list[str]:
        if drop_dir is None:
            return []
        known = {coa.resolve(), units.resolve(), *(Path(item["path"]).resolve() for item in named)}
        extras: list[str] = []
        for path in drop_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.resolve() in known:
                continue
            extras.append(str(path.relative_to(drop_dir)))
        return extras
