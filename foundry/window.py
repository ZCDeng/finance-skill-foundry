from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from foundry.caliber import (
    AUX_COLUMNS,
    MAP_COLUMNS,
    UNITS_COLUMNS,
    filter_map_rows,
    units_as_aux_rows,
)
from foundry.catalog import (
    checkpoint_and_close,
    file_hash,
    load_tabular,
    quote_ident,
    require_columns,
    sql_identifier,
    table_hash,
    write_table,
)
from foundry.errors import LockRefused, WindowBusy
from foundry.harness import merge_import_sources

STATES = ("Open", "Imported", "Locked", "Briefed", "FollowUp")
QUERYABLE = {"Locked", "Briefed", "FollowUp"}
WINDOW_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _write_json(path: Path, payload: Any) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(text)
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


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

    def create(self, *, make_current: bool = True) -> Window:
        window_id = uuid.uuid4().hex
        root = self.windows_dir / window_id
        root.mkdir(parents=True, exist_ok=True)
        window = Window(self, window_id)
        window._set_state("Open")
        if make_current:
            self._set_current(window_id)
        return window

    def get(self, window_id: str) -> Window:
        if not WINDOW_ID_RE.fullmatch(window_id):
            raise LockRefused(f"unknown window {window_id}")
        root = self.windows_dir / window_id
        if not root.is_dir():
            raise LockRefused(f"unknown window {window_id}")
        return Window(self, window_id)

    def current(self) -> Window:
        if not self.current_path.exists():
            raise LockRefused("no current window")
        return self.get(self.current_path.read_text().strip())

    def _set_current(self, window_id: str) -> None:
        self.get(window_id)
        _write_text_atomic(self.current_path, window_id + "\n")


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
    def schedules_path(self) -> Path:
        return self.root / "schedules.json"

    @property
    def workpaper_path(self) -> Path:
        return self.root / "workpaper.md"

    @property
    def state(self) -> str:
        data = _read_json(self.state_path, {"state": "Open"})
        return str(data["state"])

    def _set_state(self, state: str) -> None:
        _write_json(self.state_path, {"state": state})

    def import_tables(
        self,
        *,
        coa: Path | None = None,
        named: list[dict[str, Any]] | None = None,
        aux: Path | None = None,
        map: Path | None = None,
        units: Path | None = None,
        drop_dir: Path | None = None,
    ) -> dict[str, Any]:
        if self.state not in {"Open", "Imported"}:
            raise LockRefused("import only before lock")
        resolved = merge_import_sources(
            coa=coa,
            named=named,
            aux=aux,
            map=map,
            units=units,
            drop_dir=drop_dir,
        )
        coa = resolved.coa
        named = resolved.named
        aux = resolved.aux
        map = resolved.map
        units = resolved.units
        if coa is None:
            raise LockRefused("CoA is missing")
        if not named:
            raise LockRefused("named-table list is empty")
        named = self._normalize_named(named)
        self._assert_table_identifiers(named)
        staging = self.root / "catalog.duckdb.staging"
        staging.unlink(missing_ok=True)
        wal = Path(str(staging) + ".wal")
        wal.unlink(missing_ok=True)
        con = duckdb.connect(str(staging))
        try:
            manifest = self._load_into(
                con,
                coa=Path(coa),
                named=named,
                aux=Path(aux) if aux else None,
                map=Path(map) if map else None,
                units=Path(units) if units else None,
            )
        except Exception:
            con.close()
            staging.unlink(missing_ok=True)
            wal.unlink(missing_ok=True)
            raise
        checkpoint_and_close(con)
        wal.unlink(missing_ok=True)
        target = self.catalog_path()
        staging.replace(target)
        _write_json(self.lock_path, {**manifest, "locked": False})
        extras = self._list_extras(
            drop_dir,
            coa=Path(coa),
            named=named,
            aux=Path(aux) if aux else None,
            map=Path(map) if map else None,
            units=Path(units) if units else None,
        )
        extras.extend(f"map:orphan:{code}" for code in manifest.get("map_orphans", []))
        _write_json(self.extras_path, extras)
        self._set_state("Imported")
        return manifest

    def _normalize_named(self, named: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for item in named:
            if not isinstance(item, dict) or not item.get("id") or not item.get("path"):
                raise LockRefused("named table requires id and path")
            cleaned.append({"id": str(item["id"]).strip().lower().replace(" ", "_"), "path": str(item["path"])})
        return cleaned

    def _assert_table_identifiers(self, named: list[dict[str, Any]]) -> None:
        tables = ["coa", "aux", "map", "units", *(str(item["id"]) for item in named)]
        seen: dict[str, str] = {}
        for table in tables:
            ident = sql_identifier(table)
            prior = seen.get(ident)
            if prior is not None:
                raise LockRefused(f"table identifier collision: {prior} and {table}")
            seen[ident] = table

    def _load_into(
        self,
        con: duckdb.DuckDBPyConnection,
        *,
        coa: Path,
        named: list[dict[str, Any]],
        aux: Path | None,
        map: Path | None,
        units: Path | None,
    ) -> dict[str, Any]:
        coa_headers, coa_rows = load_tabular(coa)
        require_columns(coa_headers, ["account_code", "account_name"], "CoA")
        if not coa_rows:
            raise LockRefused("CoA is empty")
        write_table(con, "coa", coa_headers, coa_rows)
        manifest: dict[str, Any] = {
            "window_id": self.id,
            "coa": self._file_meta(con, coa, "coa"),
            "named": {},
        }
        aux_headers = list(AUX_COLUMNS)
        aux_rows: list[tuple[Any, ...]] = []
        if aux is not None:
            aux_headers, loaded_aux = load_tabular(aux)
            require_columns(aux_headers, AUX_COLUMNS, "aux")
            if not loaded_aux:
                raise LockRefused("aux is empty")
            aux_rows.extend(loaded_aux)
            manifest["aux"] = {"path": str(aux), "source_hash": file_hash(aux)}
        if units is not None:
            units_headers, units_rows = load_tabular(units)
            require_columns(units_headers, UNITS_COLUMNS, "units")
            if not units_rows:
                raise LockRefused("units are empty")
            write_table(con, "units", units_headers, units_rows)
            if aux is None:
                aux_rows.extend(units_as_aux_rows(units_headers, units_rows))
            manifest["units"] = self._file_meta(con, units, "units")
        if aux_rows:
            write_table(con, "aux", aux_headers if aux is not None else AUX_COLUMNS, aux_rows)
            loaded = self._live_hash(con, "aux")
            if "aux" in manifest:
                manifest["aux"]["loaded_hash"] = loaded
            else:
                manifest["aux"] = {"path": str(units), "loaded_hash": loaded}
        if map is not None:
            map_headers, map_rows = load_tabular(map)
            require_columns(map_headers, MAP_COLUMNS, "map")
            if not map_rows:
                raise LockRefused("map is empty")
            coa_codes = {str(row[coa_headers.index("account_code")]).strip() for row in coa_rows}
            kept, orphans = filter_map_rows(map_headers, map_rows, coa_codes)
            if not kept:
                raise LockRefused("map has no in-window rows")
            write_table(con, "map", map_headers, kept)
            manifest["map"] = self._file_meta(con, map, "map")
            manifest["map_orphans"] = orphans
        named_meta: dict[str, Any] = {}
        for item in named:
            table_id = str(item["id"])
            path = Path(item["path"])
            headers, rows = load_tabular(path)
            if not rows:
                raise LockRefused(f"named table {table_id} has zero rows")
            write_table(con, table_id, headers, rows)
            named_meta[table_id] = self._file_meta(con, path, table_id)
        manifest["named"] = named_meta
        return manifest

    def _file_meta(self, con: duckdb.DuckDBPyConnection, path: Path, table: str) -> dict[str, str]:
        return {
            "path": str(path),
            "source_hash": file_hash(path),
            "loaded_hash": self._live_hash(con, table),
        }

    def lock(self) -> dict[str, Any]:
        if self.state == "Locked" or self.lock_path.exists() and _read_json(self.lock_path, {}).get("locked"):
            raise LockRefused("already locked; re-import to take a source edit")
        if self.state != "Imported" or not self.catalog_path().exists():
            raise LockRefused("no lockable catalog")
        if self._write_con is not None:
            checkpoint_and_close(self._write_con)
            self._write_con = None
        manifest = _read_json(self.lock_path, {})
        if not manifest.get("named"):
            raise LockRefused("named-table list is empty")
        if manifest.get("window_id") != self.id:
            raise LockRefused("manifest window does not match catalog window")
        manifest_tables = self._manifest_tables(manifest)
        con = duckdb.connect(str(self.catalog_path()))
        try:
            actual_tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
            if actual_tables != set(manifest_tables):
                raise LockRefused("catalog tables do not match manifest")
            for table_id, meta in manifest_tables.items():
                count = con.execute(f"SELECT COUNT(*) FROM {quote_ident(table_id)}").fetchone()
                if not count or count[0] == 0:
                    raise LockRefused(f"table {table_id} has zero rows")
                if meta.get("source_hash") and meta.get("path"):
                    if file_hash(Path(meta["path"])) != meta["source_hash"]:
                        raise LockRefused(f"source hash changed for {table_id}")
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

    def _manifest_tables(self, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
        tables: dict[str, dict[str, Any]] = {}
        for table in ("coa", "aux", "map", "units"):
            meta = manifest.get(table)
            if meta is None:
                continue
            if not isinstance(meta, dict) or not meta.get("loaded_hash") or not meta.get("path"):
                raise LockRefused(f"manifest metadata is incomplete for {table}")
            tables[table] = meta
        for table_id, meta in (manifest.get("named") or {}).items():
            if not isinstance(meta, dict) or not meta.get("loaded_hash") or not meta.get("path"):
                raise LockRefused(f"manifest metadata is incomplete for {table_id}")
            tables[str(table_id)] = meta
        if "coa" not in tables:
            raise LockRefused("manifest metadata is incomplete for coa")
        return tables

    def _live_hash(self, con: duckdb.DuckDBPyConnection, table: str) -> str:
        rel = con.execute(f"SELECT * FROM {quote_ident(table)}").fetchall()
        headers = [d[0] for d in con.description or []]
        return table_hash(headers, [tuple(row) for row in rel])

    def hashes(self) -> dict[str, Any]:
        manifest = _read_json(self.lock_path, {})
        return {
            "coa": manifest.get("coa", {}).get("source_hash"),
            "aux": manifest.get("aux", {}).get("source_hash") or manifest.get("aux", {}).get("loaded_hash"),
            "map": manifest.get("map", {}).get("source_hash"),
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
        coa: Path | None = None,
        named: list[dict[str, Any]] | None = None,
        aux: Path | None = None,
        map: Path | None = None,
        units: Path | None = None,
        drop_dir: Path | None = None,
    ) -> Window:
        handles = _read_json(self.handles_path, [])
        if handles:
            raise WindowBusy(f"read handles remain: {handles}")
        if self._ro_con is not None:
            self._ro_con.close()
            self._ro_con = None
        nxt = self.store.create(make_current=False)
        try:
            nxt.import_tables(coa=coa, named=named, aux=aux, map=map, units=units, drop_dir=drop_dir)
        except Exception:
            shutil.rmtree(nxt.root, ignore_errors=True)
            raise
        self.store._set_current(nxt.id)
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
        named: list[dict[str, Any]],
        aux: Path | None = None,
        map: Path | None = None,
        units: Path | None = None,
    ) -> list[str]:
        if drop_dir is None:
            return []
        known = {coa.resolve(), *(Path(item["path"]).resolve() for item in named)}
        for extra in (aux, map, units):
            if extra is not None:
                known.add(Path(extra).resolve())
        extras: list[str] = []
        for path in drop_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.resolve() in known:
                continue
            extras.append(str(path.relative_to(drop_dir)))
        return extras
