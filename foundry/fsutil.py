from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, text: str) -> None:
    """Write text so a reader never sees a half-written file.

    A crash leaves either the previous content or the new content, never a
    truncated mix. Callers that write two related files should write the
    dependency first so an interrupted pair fails closed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def write_json_atomic(path: Path, payload: Any) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
