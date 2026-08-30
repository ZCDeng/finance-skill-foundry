from __future__ import annotations

import json
from typing import Any

from foundry.errors import LockRefused
from foundry.window import Window

def record_questions(window: Window, questions: list[dict[str, Any]]) -> None:
    if window.state != "Locked":
        raise LockRefused(f"questions refused in state {window.state}")
    if window.questions_path.exists():
        raise LockRefused("questions already recorded")
    if not isinstance(questions, list) or not questions:
        raise LockRefused("questions must be a non-empty list")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in questions:
        if not isinstance(item, dict):
            raise LockRefused("question must be an object")
        item_id = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        raw_required = item.get("required_table_ids")
        if not isinstance(raw_required, (list, tuple)):
            raise LockRefused(f"question {item_id or '<missing>'} required_table_ids must be a list")
        required = [str(t).strip() for t in raw_required if str(t).strip()]
        if not item_id:
            raise LockRefused("question id is required")
        if item_id in seen:
            raise LockRefused(f"duplicate question id: {item_id}")
        if not text:
            raise LockRefused(f"question {item_id} text is required")
        if not required:
            raise LockRefused(f"question {item_id} required_table_ids is required")
        seen.add(item_id)
        cleaned.append(
            {
                "id": item_id,
                "text": text,
                "required_table_ids": required,
            }
        )
    window.questions_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n")


def load_questions(window: Window) -> list[dict[str, Any]]:
    if not window.questions_path.exists():
        return []
    return json.loads(window.questions_path.read_text())
