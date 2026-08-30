from __future__ import annotations

import json
import re
import shutil
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
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
    TABULAR_EXTS,
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
from foundry.fsutil import write_json_atomic as _write_json
from foundry.fsutil import write_text_atomic as _write_text_atomic
from foundry.harness import merge_import_sources
from foundry.locking import exclusive

STATES = ("Open", "Imported", "Locked", "Briefed", "FollowUp")
QUERYABLE = {"Locked", "Briefed", "FollowUp"}
WINDOW_ID_RE = re.compile(r"^[0-9a-f]{32}$")
LIFECYCLE_LOCK_TIMEOUT = 10.0


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


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
    def inputs_dir(self) -> Path:
        """Where the bytes this window was built from live.

        Import copies every source file in here and then parses the copy, so
        the window holds its own inputs rather than a path into whatever
        directory the operator happened to export into. Delete the original and
        the window still answers for itself; hand the directory to an auditor
        and they get the workbooks, not a list of file names.
        """
        return self.root / "inputs"

    @property
    def task_path(self) -> Path:
        return self.root / "task"

    @property
    def task_id(self) -> str | None:
        """Which task owns this window, if one has adopted it.

        A back-pointer rather than a lookup through every task's chain: the
        window is what a period step already has in hand, and reading one line
        beats scanning the task store to find out where it belongs.
        """
        if not self.task_path.exists():
            return None
        value = self.task_path.read_text(encoding="utf-8").strip()
        return value or None

    def bind_task(self, task_id: str) -> None:
        """Adopt this window into a task, once.

        Re-binding to the same task is a no-op so adoption-on-touch can call it
        freely. Re-binding to a different one is refused: a window's follow-ups,
        deliverable versions and successor chain are already recorded against
        the first task, and moving the pointer would leave those pointing at a
        timeline that no longer claims them.
        """
        current = self.task_id
        if current == task_id:
            return
        if current is not None:
            raise LockRefused(f"window {self.id} already belongs to task {current}")
        _write_text_atomic(self.task_path, f"{task_id}\n")

    @property
    def lifecycle_lock_path(self) -> Path:
        return self.root / ".lock"

    @property
    def formulator_home(self) -> Path:
        return self.store.formulator_dir / self.id

    @property
    def formulator_pid_path(self) -> Path:
        """The single-instance Formulator lease for this window.

        ``launch-formulator`` claims this file with ``O_EXCL`` before it spawns
        anything and only registers the ``formulator`` handle once the server
        answered, so between those two points the handle list is empty while a
        Formulator is coming up. Re-import reads the lease, not just the
        handles, or it would cross the fence during that window.
        """
        return self.formulator_home / "pid"

    def lifecycle_lock(self, *, timeout: float | None = None) -> AbstractContextManager[None]:
        """Serialize one whole lifecycle step of this window across processes.

        Import, lock and re-import each read state, rewrite the catalog and then
        write state back. Without mutual exclusion two processes can both pass
        the state check and leave state, manifest and catalog disagreeing, so
        every one of those steps runs inside this lock. Held by the window that
        is being mutated, keyed on ``<window>/.lock``.
        """
        wait = LIFECYCLE_LOCK_TIMEOUT if timeout is None else timeout
        return exclusive(self.lifecycle_lock_path, timeout=wait)

    def close(self) -> None:
        """Release the DuckDB connections this window opened.

        A window is a cheap identity object that callers construct freely, but
        it owns lazily opened connections. Long-lived callers close them here
        instead of accumulating one connection per read.
        """
        if self._write_con is not None:
            checkpoint_and_close(self._write_con)
            self._write_con = None
        if self._ro_con is not None:
            self._ro_con.close()
            self._ro_con = None

    def __enter__(self) -> Window:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

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
        with self.lifecycle_lock():
            return self._import_tables_locked(
                coa=coa,
                named=named,
                aux=aux,
                map=map,
                units=units,
                drop_dir=drop_dir,
            )

    def _import_tables_locked(
        self,
        *,
        coa: Path | None,
        named: list[dict[str, Any]] | None,
        aux: Path | None,
        map: Path | None,
        units: Path | None,
        drop_dir: Path | None,
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
        # The archive is staged for the same reason the catalog is. A second
        # import must not delete the bytes behind the window that is currently
        # importable until the new set has been read whole; a failure halfway
        # would otherwise leave a catalog whose inputs are gone.
        staging_inputs = self.root / "inputs.staging"
        shutil.rmtree(staging_inputs, ignore_errors=True)
        con = duckdb.connect(str(staging))
        try:
            manifest = self._load_into(
                con,
                coa=Path(coa),
                named=named,
                aux=Path(aux) if aux else None,
                map=Path(map) if map else None,
                units=Path(units) if units else None,
                dest_dir=staging_inputs,
            )
        except Exception:
            con.close()
            staging.unlink(missing_ok=True)
            wal.unlink(missing_ok=True)
            shutil.rmtree(staging_inputs, ignore_errors=True)
            raise
        checkpoint_and_close(con)
        wal.unlink(missing_ok=True)
        target = self.catalog_path()
        staging.replace(target)
        # Catalog first, then the archive it was parsed from. An interruption
        # between the two leaves the previous archive beside the new catalog,
        # which lock() catches on the source digest rather than accepting.
        shutil.rmtree(self.inputs_dir, ignore_errors=True)
        staging_inputs.replace(self.inputs_dir)
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
        """Normalize each id the way the catalog writer will.

        ``write_table`` routes the CREATE through ``sql_identifier``, so an id
        such as ``ar-2024-08`` lands in DuckDB as ``ar_2024_08``. Normalizing
        here keeps the manifest key, the created table and ``SHOW TABLES`` in
        agreement; otherwise the window imports and can then never lock.
        ``given_id`` keeps the operator's spelling for error messages.
        """
        cleaned: list[dict[str, Any]] = []
        for item in named:
            if not isinstance(item, dict) or not item.get("id") or not item.get("path"):
                raise LockRefused("named table requires id and path")
            given = str(item["id"]).strip()
            cleaned.append({"id": sql_identifier(given), "given_id": given, "path": str(item["path"])})
        return cleaned

    def _assert_table_identifiers(self, named: list[dict[str, Any]]) -> None:
        tables = [
            ("coa", "coa"),
            ("aux", "aux"),
            ("map", "map"),
            ("units", "units"),
            *((str(item["id"]), str(item.get("given_id") or item["id"])) for item in named),
        ]
        seen: dict[str, str] = {}
        for table, given in tables:
            ident = sql_identifier(table)
            prior = seen.get(ident)
            if prior is not None:
                raise LockRefused(f"table identifier collision: {prior} and {given}")
            seen[ident] = given

    def _load_into(
        self,
        con: duckdb.DuckDBPyConnection,
        *,
        coa: Path,
        named: list[dict[str, Any]],
        aux: Path | None,
        map: Path | None,
        units: Path | None,
        dest_dir: Path,
    ) -> dict[str, Any]:
        coa_file, coa_hash, coa_headers, coa_rows = self._read_source(coa, "coa", dest_dir)
        require_columns(coa_headers, ["account_code", "account_name"], "CoA")
        if not coa_rows:
            raise LockRefused("CoA is empty")
        write_table(con, "coa", coa_headers, coa_rows)
        manifest: dict[str, Any] = {
            "window_id": self.id,
            "coa": self._file_meta(
                con, coa, self._archived_ref(coa_file, dest_dir), "coa", coa_hash
            ),
            "named": {},
        }
        aux_headers = list(AUX_COLUMNS)
        aux_rows: list[tuple[Any, ...]] = []
        units_ref: str | None = None
        if aux is not None:
            aux_file, aux_hash, aux_headers, loaded_aux = self._read_source(aux, "aux", dest_dir)
            require_columns(aux_headers, AUX_COLUMNS, "aux")
            if not loaded_aux:
                raise LockRefused("aux is empty")
            aux_rows.extend(loaded_aux)
            manifest["aux"] = {
                "path": str(aux),
                "archived": self._archived_ref(aux_file, dest_dir),
                "source_hash": aux_hash,
            }
        if units is not None:
            units_file, units_hash, units_headers, units_rows = self._read_source(
                units, "units", dest_dir
            )
            require_columns(units_headers, UNITS_COLUMNS, "units")
            if not units_rows:
                raise LockRefused("units are empty")
            write_table(con, "units", units_headers, units_rows)
            if aux is None:
                aux_rows.extend(units_as_aux_rows(units_headers, units_rows))
            units_ref = self._archived_ref(units_file, dest_dir)
            manifest["units"] = self._file_meta(con, units, units_ref, "units", units_hash)
        if aux_rows:
            write_table(con, "aux", aux_headers if aux is not None else AUX_COLUMNS, aux_rows)
            loaded = self._live_hash(con, "aux")
            if "aux" in manifest:
                manifest["aux"]["loaded_hash"] = loaded
            else:
                # Derived from the units file, not supplied as an aux source.
                # The discriminator keeps consumers from reading this table
                # digest as if it were the digest of a file the manager handed in.
                # It points at the units archive for the same reason: there is
                # no aux file to point at, and naming one would invent a source.
                manifest["aux"] = {
                    "derived_from": "units",
                    "path": str(units),
                    "archived": units_ref,
                    "loaded_hash": loaded,
                }
        if map is not None:
            map_file, map_hash, map_headers, map_rows = self._read_source(map, "map", dest_dir)
            require_columns(map_headers, MAP_COLUMNS, "map")
            if not map_rows:
                raise LockRefused("map is empty")
            coa_codes = {str(row[coa_headers.index("account_code")]).strip() for row in coa_rows}
            kept, orphans = filter_map_rows(map_headers, map_rows, coa_codes)
            if not kept:
                raise LockRefused("map has no in-window rows")
            write_table(con, "map", map_headers, kept)
            manifest["map"] = self._file_meta(
                con, map, self._archived_ref(map_file, dest_dir), "map", map_hash
            )
            manifest["map_orphans"] = orphans
        named_meta: dict[str, Any] = {}
        for item in named:
            table_id = str(item["id"])
            path = Path(item["path"])
            archived, source_hash, headers, rows = self._read_source(path, table_id, dest_dir)
            if not rows:
                raise LockRefused(f"named table {table_id} has zero rows")
            write_table(con, table_id, headers, rows)
            named_meta[table_id] = self._file_meta(
                con, path, self._archived_ref(archived, dest_dir), table_id, source_hash
            )
        manifest["named"] = named_meta
        return manifest

    def _archive_source(self, path: Path, role: str, dest_dir: Path) -> tuple[Path, str]:
        """Copy the operator's file into the window before anything reads it.

        Everything downstream -- the parse, the manifest digest, ``lock()``'s
        verification -- then works from bytes this window owns. The previous
        shape read the operator's disk at import and again at lock, which made
        a window that could stop being lockable because a file moved, and left
        no way to show an auditor what the numbers were built from.

        The old hash-parse-hash guard narrows to one job here. Copying is not
        atomic against a writer, so a torn copy is possible; hashing the source
        before and after and the copy in between catches both a file that
        changed under the copy and a copy that did not land whole.
        """
        suffix = path.suffix.lower()
        if suffix not in TABULAR_EXTS:
            raise LockRefused(f"unsupported import format: {path.suffix}")
        digest = file_hash(path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{role}{suffix}"
        tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(path, tmp)
            if file_hash(tmp) != digest or file_hash(path) != digest:
                raise LockRefused(f"source changed while it was being copied: {path}")
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        return dest, digest

    def _read_source(
        self, path: Path, role: str, dest_dir: Path
    ) -> tuple[Path, str, list[str], list[tuple[Any, ...]]]:
        """Archive a source file, then parse the archived copy.

        Parsing the copy rather than the original is what makes the manifest
        digest and the catalog rows describe the same bytes by construction,
        instead of by a race the import has to keep re-checking.
        """
        archived, digest = self._archive_source(path, role, dest_dir)
        headers, rows = load_tabular(archived)
        return archived, digest, headers, rows

    def _archived_ref(self, archived: Path, dest_dir: Path) -> str:
        """The archive path as the window will hold it once the import lands.

        Recorded relative to the window root and pointing at ``inputs/``, not
        at the staging directory the import is currently filling: the manifest
        is written after the swap, and a reader resolving it must not be handed
        a name that only existed mid-import.
        """
        return str(Path("inputs") / archived.relative_to(dest_dir))

    def _file_meta(
        self,
        con: duckdb.DuckDBPyConnection,
        path: Path,
        archived_ref: str,
        table: str,
        source_hash: str,
    ) -> dict[str, str]:
        return {
            "path": str(path),
            "archived": archived_ref,
            "source_hash": source_hash,
            "loaded_hash": self._live_hash(con, table),
        }

    def lock(self) -> dict[str, Any]:
        with self.lifecycle_lock():
            return self._lock_locked()

    def _lock_locked(self) -> dict[str, Any]:
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
                if meta.get("source_hash"):
                    self._verify_source(table_id, meta)
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

    def _verify_source(self, table_id: str, meta: dict[str, Any]) -> None:
        """Re-hash one table's bytes before the window locks.

        Two different questions, and the split is the point.

        The archived copy answers "is this window still intact". It is the copy
        the catalog was parsed from, so a locked window no longer depends on the
        operator's disk: moving or deleting the export after import cannot make
        the window unlockable, and the digest on the manifest describes bytes
        the window can still produce on demand.

        The original answers "has she changed her mind since importing". A file
        that is still on disk and no longer matches means she edited a master
        table after importing it, and locking the imported bytes anyway would
        silently ship the version she just replaced. Caliber changes travel
        through a re-import, so this refuses and says so.

        A source that is simply gone is not an error. Keeping its bytes is what
        the archive is for.

        A window imported before the archive existed has no ``archived`` key. It
        falls back to the original alone, and refuses when that is missing too,
        because then nothing at all can be verified.
        """
        expected = str(meta["source_hash"])
        archived = meta.get("archived")
        if archived:
            if file_hash(self.root / str(archived)) != expected:
                raise LockRefused(f"archived input changed for {table_id}")
        origin = Path(str(meta["path"]))
        if not origin.is_file():
            if not archived:
                raise LockRefused(f"source is gone and was never archived for {table_id}")
            return
        if file_hash(origin) != expected:
            raise LockRefused(f"source hash changed for {table_id}; re-import to take the edit")

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
        aux_meta = manifest.get("aux", {}) or {}
        aux_source = aux_meta.get("source_hash")
        aux_digest = aux_source or aux_meta.get("loaded_hash")
        # aux carries either a source-file digest or, when the table was derived
        # from units, a loaded-table digest. The kind travels with the digest so
        # a reviewer can tell a source change from a different import route.
        aux_kind: str | None = None
        if aux_digest:
            aux_kind = "source" if aux_source else "derived"
        return {
            "coa": manifest.get("coa", {}).get("source_hash"),
            "aux": aux_digest,
            "aux_kind": aux_kind,
            "aux_derived_from": aux_meta.get("derived_from"),
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
        # The lease check, the successor import and the current-window flip are
        # one step: a lease registered between the check and the flip would
        # otherwise keep serving the old catalog after the fence was crossed.
        # launch-formulator takes this same lock for its whole startup, so a
        # launch is either wholly before this block or wholly after it.
        with self.lifecycle_lock():
            handles = _read_json(self.handles_path, [])
            if handles:
                raise WindowBusy(f"read handles remain: {handles}")
            if self.formulator_pid_path.exists():
                raise WindowBusy(
                    "a Formulator lease is still held for this window; run stop-formulator first"
                )
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
