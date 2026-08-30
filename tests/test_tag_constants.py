"""#43: every user-facing tag string routes through foundry.tags.

A retag in ``tags.py`` must move every label at once. A literal left behind
does not fail -- it goes stale beside a fresh one in the same rendered item,
which is worse than a crash because it still looks like a workpaper.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from foundry import tags
from foundry.workpaper import render_workpaper

ROOT = Path(__file__).resolve().parents[1]
TAG_VALUES = {
    name: value
    for name, value in vars(tags).items()
    if name.isupper() and isinstance(value, str)
}
SOURCES = sorted(
    [path for path in (ROOT / "foundry").glob("*.py") if path.name != "tags.py"]
    + list((ROOT / "formulator-plugin").glob("*.py"))
)


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_module_inlines_a_tag_literal(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    # Docstrings and comments may name a tag; code may not.
    code = "\n".join(
        line for line in source.splitlines() if not re.match(r"\s*#", line)
    )
    code = re.sub(r'"""(?:.|\n)*?"""', "", code)
    for name, value in TAG_VALUES.items():
        assert value not in code, f"{path.name} inlines {name} instead of importing it"


def test_workpaper_origin_label_follows_a_retag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retag OUTSIDE and the 来源 line must move with 标签, not stay behind."""
    monkeypatch.setattr("foundry.workpaper.OUTSIDE", "稿外追问X")
    payload = {
        "window_id": "w",
        "hashes": {},
        "items": [
            {
                "id": "followup-1",
                "text": "AR 合计",
                "tag": tags.RECOMPUTED,
                "origin": "followup",
                "table": "ar",
                "recomputed": 40,
                "lines": [],
            }
        ],
    }
    rendered = render_workpaper(payload)
    assert "来源: 稿外追问X" in rendered
    assert f"标签: 稿外追问X / {tags.RECOMPUTED}" in rendered
