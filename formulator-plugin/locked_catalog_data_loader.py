from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from foundry.errors import LockRefused
from foundry.window import WindowStore

DEFAULT_MAX_IMPORT_ROWS = 2_000_000
LOADER_NAME = "locked_catalog"


def max_import_rows() -> int:
    raw = os.environ.get("FOUNDRY_MAX_IMPORT_ROWS")
    if raw:
        return int(raw)
    return DEFAULT_MAX_IMPORT_ROWS


class LockedCatalogLoader:
    """Formulator ExternalDataLoader: fetch locked catalog rows, never mutate."""

    def __init__(self, var_root: Path | None = None) -> None:
        raw = var_root or os.environ.get("FOUNDRY_VAR")
        if not raw:
            raise LockRefused("FOUNDRY_VAR is required for the locked-catalog loader")
        self.store = WindowStore(Path(raw))

    def list_tables(self) -> list[dict[str, Any]]:
        window = self.store.current()
        if window.state not in {"Locked", "Briefed", "FollowUp"}:
            raise LockRefused("loader opens the catalog read-only after lock")
        counts = []
        for name in window.table_names():
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

    def refresh(self) -> None:
        raise LockRefused("refresh is refused")

    def load_connector(self, source: str) -> None:
        if source != LOADER_NAME:
            raise LockRefused(f"extra-source load refused: {source}")

    def starter_questions(self) -> list[str]:
        raise LockRefused("starter-question route is refused")


def window_rows(window, name: str) -> list[tuple[Any, ...]]:
    return window.query(f'SELECT * FROM "{name}"')


# Official scanner looks for a loader class in *_data_loader.py
ExternalDataLoader = LockedCatalogLoader
