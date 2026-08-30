"""One place says which harness this kit runs on.

The pin appeared in three: the README's prose, the app's fetch script, and
whatever was actually installed. Two of those can drift silently, and the third
only tells you on a machine that has it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECLARED = json.loads((ROOT / "dsh-plugin" / "package.json").read_text())["dsh"]["foundry"]["harness"]


def test_the_readme_pins_what_the_kit_declares() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pin = f"{DECLARED['package']}@{DECLARED['version']}"
    assert f"`{pin}`" in readme, f"README does not pin {pin}"


def test_the_app_stages_what_the_kit_declares() -> None:
    script = ROOT / "app" / "scripts" / "fetch-harness.mjs"
    if not script.is_file():
        return
    text = script.read_text(encoding="utf-8")
    # The script reads the pin rather than restating it, which is the point.
    assert "dsh.foundry.harness" in text or "foundry.harness" in text, script


def test_the_entry_path_is_the_one_the_app_resolves() -> None:
    resources = ROOT / "app" / "electron" / "harness" / "resources.ts"
    if not resources.is_file():
        return
    parts = re.findall(r"'([^']+)'", resources.read_text(encoding="utf-8"))
    for segment in DECLARED["entry"].split("/"):
        assert segment in parts, f"{segment} is not in the entry the app builds"
