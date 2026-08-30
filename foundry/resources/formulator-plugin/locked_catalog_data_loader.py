from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from foundry.caliber import as_number
from foundry.errors import LockRefused
from foundry.catalog import quote_ident
from foundry.window import Window, WindowStore

DEFAULT_MAX_IMPORT_ROWS = 2_000_000
LOADER_NAME = "locked_catalog"

try:
    from data_formulator.data_loader.external_data_loader import ExternalDataLoader as _DFLoader
except ModuleNotFoundError as exc:  # pragma: no cover - tests run without Formulator
    # Only "Data Formulator is not installed" may fall back to the stub base
    # class. A moved module or a renamed ExternalDataLoader must raise: a
    # silent fallback would leave LockedCatalogLoader subclassing object, so
    # Formulator would come up with the locked-catalog connector unregistered
    # and nothing in the foundry would say so.
    if exc.name != "data_formulator":
        raise

    class _DFLoader:  # type: ignore[no-redef]
        pass


def max_import_rows() -> int:
    raw = os.environ.get("FOUNDRY_MAX_IMPORT_ROWS")
    if raw:
        return int(raw)
    return DEFAULT_MAX_IMPORT_ROWS


def _jsonable(value: Any) -> Any:
    try:
        return as_number(value)
    except Exception:
        return value


class LockedCatalogLoader(_DFLoader):
    """Formulator ExternalDataLoader: fetch locked catalog rows, never mutate."""

    DISPLAY_NAME = "Locked catalog"

    def __init__(self, params: dict[str, Any] | None = None, var_root: Path | None = None) -> None:
        self.params = params or {}
        raw = var_root or self.params.get("var_root") or os.environ.get("FOUNDRY_VAR")
        if not raw:
            raise LockRefused("FOUNDRY_VAR is required for the locked-catalog loader")
        self.store = WindowStore(Path(raw))
        self.window_id = str(
            self.params.get("window_id") or os.environ.get("FOUNDRY_WINDOW_ID") or ""
        ).strip()
        if not self.window_id:
            raise LockRefused("FOUNDRY_WINDOW_ID is required for the locked-catalog loader")
        self._bound: Window | None = None

    @staticmethod
    def list_params() -> list[dict[str, Any]]:
        return []

    @staticmethod
    def auth_instructions() -> str:
        return "Foundry locked catalog. Read-only. Extra sources are refused."

    @staticmethod
    def auth_mode() -> str:
        return "none"

    def _window(self) -> Window:
        """The one window this loader reads, opened once for its whole life.

        ``Window`` owns a lazily opened read-only DuckDB connection, so
        re-resolving it per call -- ``list_tables`` alone calls it once and
        every ``fetch_table`` twice more -- accumulated one connection per read
        for as long as a Formulator session stayed open. Bind once; re-read the
        state from disk on every call so a window that left the queryable
        states still fails closed.
        """
        if self._bound is None:
            self._bound = self.store.get(self.window_id)
        if self._bound.state not in {"Locked", "Briefed", "FollowUp"}:
            raise LockRefused("loader opens the catalog read-only after lock")
        return self._bound

    def close(self) -> None:
        """Release the read connection this loader opened."""
        if self._bound is not None:
            self._bound.close()
            self._bound = None

    def list_tables(self, table_filter: str | None = None) -> list[dict[str, Any]]:
        window = self._window()
        counts = []
        for name in window.table_names():
            if table_filter and table_filter not in name:
                continue
            count = window.query(f"SELECT COUNT(*) FROM {quote_ident(name)}")[0][0]
            if count > max_import_rows():
                raise LockRefused(f"{name} exceeds MAX_IMPORT_ROWS ({max_import_rows()})")
            described = window.query(f"DESCRIBE {quote_ident(name)}")
            columns = [{"name": str(row[0]), "type": str(row[1])} for row in described]
            sample_rows = window.query(f"SELECT * FROM {quote_ident(name)} LIMIT 5")
            counts.append(
                {
                    "name": name,
                    "rows": int(count),
                    "metadata": {
                        "row_count": int(count),
                        "columns": columns,
                        "sample_rows": [[_jsonable(cell) for cell in row] for row in sample_rows],
                    },
                }
            )
        return counts

    def fetch_table(
        self,
        name: str,
        columns: list[str] | None = None,
        limit: int | None = None,
        sort_columns: list[str] | None = None,
        sort_order: str = "asc",
    ) -> list[tuple[Any, ...]]:
        listed = {item["name"] for item in self.list_tables()}
        if name not in listed:
            raise LockRefused(f"extra-source load refused: {name}")
        rows = window_rows(
            self._window(),
            name,
            columns=columns,
            limit=limit,
            sort_columns=sort_columns,
            sort_order=sort_order,
        )
        if len(rows) > max_import_rows():
            raise LockRefused(f"{name} exceeds MAX_IMPORT_ROWS ({max_import_rows()})")
        return rows

    def fetch_data_as_arrow(self, source_table: str, import_options: dict[str, Any] | None = None):
        import pyarrow as pa

        import_options = import_options or {}
        unsupported = [key for key in ("sort", "filter", "filters", "source_filters") if import_options.get(key)]
        if unsupported:
            raise LockRefused(f"unsupported import options: {unsupported}")
        columns = import_options.get("columns")
        if columns is not None:
            columns = [str(col) for col in columns]
        required = import_options.get("required_columns") or import_options.get("requiredColumns") or []
        required = [str(col) for col in required]
        headers = [str(row[0]) for row in self._window().query(f"DESCRIBE {quote_ident(source_table)}")]
        missing_required = [col for col in required if col not in headers]
        if missing_required:
            raise LockRefused(f"required columns not in {source_table}: {missing_required}")
        limit = _import_limit(import_options.get("size"))
        sort_columns = import_options.get("sort_columns")
        if sort_columns is not None:
            sort_columns = [str(col) for col in sort_columns]
        sort_order = str(import_options.get("sort_order") or "asc").lower()
        rows = self.fetch_table(
            source_table,
            columns=columns,
            limit=limit,
            sort_columns=sort_columns,
            sort_order=sort_order,
        )
        if columns:
            headers = columns
        data = {header: [row[idx] for row in rows] for idx, header in enumerate(headers)}
        return pa.table(data)

    def refresh(self) -> None:
        raise LockRefused("refresh is refused")

    def load_connector(self, source: str) -> None:
        if source != LOADER_NAME:
            raise LockRefused(f"extra-source load refused: {source}")

    def starter_questions(self) -> list[str]:
        raise LockRefused("starter-question route is refused")


def _import_limit(size: Any) -> int:
    cap = max_import_rows()
    if size in (None, ""):
        return cap
    try:
        parsed = int(size)
    except (TypeError, ValueError) as exc:
        raise LockRefused("import option size must be an integer") from exc
    if parsed < 0:
        raise LockRefused("import option size must be non-negative")
    return min(parsed, cap)


def window_rows(
    window,
    name: str,
    columns: list[str] | None = None,
    limit: int | None = None,
    sort_columns: list[str] | None = None,
    sort_order: str = "asc",
) -> list[tuple[Any, ...]]:
    headers = [str(row[0]) for row in window.query(f"DESCRIBE {quote_ident(name)}")]
    selected = columns or headers
    order_cols = sort_columns or []
    missing = [col for col in [*selected, *order_cols] if col not in headers]
    if missing:
        raise LockRefused(f"columns not in {name}: {missing}")
    projection = ", ".join(quote_ident(col) for col in selected)
    sql = f"SELECT {projection} FROM {quote_ident(name)}"
    if order_cols:
        if sort_order not in {"asc", "desc"}:
            raise LockRefused("sort_order must be asc or desc")
        sql += " ORDER BY " + ", ".join(f"{quote_ident(col)} {sort_order.upper()}" for col in order_cols)
    if limit is not None:
        sql += f" LIMIT {limit}"
    return window.query(sql)
