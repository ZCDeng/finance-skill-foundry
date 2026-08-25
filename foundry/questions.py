from __future__ import annotations

import json
from typing import Any

from foundry.window import Window


def record_questions(window: Window, questions: list[dict[str, Any]]) -> None:
    cleaned: list[dict[str, Any]] = []
    for item in questions:
        cleaned.append(
            {
                "id": str(item["id"]),
                "text": str(item["text"]),
                "required_table_ids": [str(t) for t in item.get("required_table_ids", [])],
            }
        )
    window.questions_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n")


def load_questions(window: Window) -> list[dict[str, Any]]:
    if not window.questions_path.exists():
        return []
    return json.loads(window.questions_path.read_text())
