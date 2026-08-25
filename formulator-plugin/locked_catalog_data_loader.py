from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from foundry.errors import LockRefused
from foundry.window import WindowStore

DEFAULT_MAX_IMPORT_ROWS = 2_000_000
LOADER_NAME = "locked_catalog"

try:
    from data_formulator.data_loader.external_data_loader import ExternalDataLoader as _DFLoader
except Exception:  # pragma: no cover - tests run without Formulator
    class _DFLoader:  # type: ignore[no-redef]
        pass


def max_import_rows() -> int:
    raw = os.environ.get("FOUNDRY_MAX_IMPORT_ROWS")
    if raw:
        return int(raw)
    return DEFAULT_MAX_IMPORT_ROWS


class LockedCatalogLoader(_DFLoader):
    """Formulator ExternalDataLoader: fetch locked catalog rows, never mutate."""

    DISPLAY_NAME = "Locked catalog"

    def __init__(self, params: dict[str, Any] | None = None, var_root: Path | None = None) -> None:
        self.params = params or {}
        raw = var_root or self.params.get("var_root") or os.environ.get("FOUNDRY_VAR")
        if not raw:
            raise LockRefused("FOUNDRY_VAR is required for the locked-catalog loader")
        self.store = WindowStore(Path(raw))

    @staticmethod
    def list_params() -> list[dict[str, Any]]:
        return []

    @staticmethod
    def auth_instructions() -> str:
        return "Foundry locked catalog. Read-only. Extra sources are refused."

    @staticmethod
    def auth_mode() -> str:
        return "none"

    def list_tables(self, table_filter: str | None = None) -> list[dict[str, Any]]:
        window = self.store.current()
        if window.state not in {"Locked", "Briefed", "FollowUp"}:
            raise LockRefused("loader opens the catalog read-only after lock")
        counts = []
        for name in window.table_names():
            if table_filter and table_filter not in name:
                continue
            count = window.query(f'SELECT COUNT(*) FROM "{name}"')[0][0]
            if count > max_import_rows():
                raise LockRefused(f"{name} exceeds MAX_IMPORT_ROWS ({max_import_rows()})")
            counts.append({"name": name, "rows": int(count)})
        return counts

    def fetch_table(self, name: str) -> list[tuple[Any, ...]]:
        listed = {item["name"] for item in self.list_tables()}
        if name not in listed:
            raise LockRefused(f"extra-source load refused: {name}")
        rows = window_rows(self.store.current(), name)
        if len(rows) > max_import_rows():
            raise LockRefused(f"{name} exceeds MAX_IMPORT_ROWS ({max_import_rows()})")
        return rows

    def fetch_data_as_arrow(self, source_table: str, import_options: dict[str, Any] | None = None):
        import pyarrow as pa

        rows = self.fetch_table(source_table)
        if not rows:
            return pa.table({})
        headers = [row[0] for row in self.store.current().query(f'DESCRIBE "{source_table}"')]
        columns = {header: [row[idx] for row in rows] for idx, header in enumerate(headers)}
        return pa.table(columns)

    def refresh(self) -> None:
        raise LockRefused("refresh is refused")

    def load_connector(self, source: str) -> None:
        if source != LOADER_NAME:
            raise LockRefused(f"extra-source load refused: {source}")

    def starter_questions(self) -> list[str]:
        raise LockRefused("starter-question route is refused")


def window_rows(window, name: str) -> list[tuple[Any, ...]]:
    return window.query(f'SELECT * FROM "{name}"')
