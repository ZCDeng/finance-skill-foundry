from __future__ import annotations

import json
import shutil
from pathlib import Path

from foundry.method_skills import (
    BUNDLED_IDS,
    BUNDLED_PACKS,
    bundled_pack_dirs,
    bundled_pack_manifest,
    bundled_skill_dirs,
    bundled_skill_manifest,
    method_root,
)

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PACK_NAMES = {
    "tearsheet",
    "dcf",
    "comps",
    "ib-deck",
    "initiate",
    "research-note",
}


def test_cf11_pack_entries_are_first_level_not_packs_nested() -> None:
    files = {pack_id: path / "SKILL.md" for pack_id, path in bundled_pack_dirs().items()}
    assert tuple(bundled_pack_dirs()) == BUNDLED_PACKS
    assert tuple(bundled_skill_dirs()) == BUNDLED_IDS
    assert set(BUNDLED_PACKS).isdisjoint(BUNDLED_IDS)
    for pack_id, path in files.items():
        assert path.is_file(), pack_id
        assert path.parent.name == pack_id
        assert "packs" not in path.parent.parts[-2:]
        text = path.read_text(encoding="utf-8")
        assert f"name: {pack_id}" in text
        assert "Do **not** refuse" in text or "不得拒绝" in text


def test_cf11_setup_and_close_are_discoverable_first_level() -> None:
    root = method_root()
    assert (root / "setup" / "SKILL.md").is_file()
    assert (root / "close" / "SKILL.md").is_file()
    assert not (root / "packs" / "close" / "SKILL.md").exists()
    assert not (root / "packs" / "setup" / "SKILL.md").exists()
    setup = (root / "setup" / "SKILL.md").read_text(encoding="utf-8")
    assert "finance_readiness" in setup
    close = (root / "close" / "SKILL.md").read_text(encoding="utf-8")
    assert "financial-statements" in close
    assert "run_metric" in close


def test_cf14_missing_close_keeps_original_method_skills(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "method"
    shutil.copytree(method_root(), dest)
    shutil.rmtree(dest / "close")
    monkeypatch.setattr("foundry.method_skills.method_root", lambda: dest)
    skills = bundled_skill_manifest()
    assert skills["ids"] == list(BUNDLED_IDS)
    assert skills["missing"] == []
    packs = bundled_pack_manifest()
    assert "close" in packs["missing"]
    assert set(BUNDLED_IDS) == set(bundled_skill_dirs())


def test_cf15_pack_files_match_packaged_resources() -> None:
    canonical = ROOT / "method"
    packaged = ROOT / "foundry" / "resources" / "method"
    for rel in ("packs.json", "setup/SKILL.md", "close/SKILL.md", "bva/SKILL.md", "cash/SKILL.md"):
        assert (canonical / rel).read_bytes() == (packaged / rel).read_bytes(), rel


def test_cf26_packs_registry_excludes_sell_side_skills() -> None:
    registry = json.loads((method_root() / "packs.json").read_text(encoding="utf-8"))
    ids = [item["id"] for item in registry["packs"]]
    assert ids == list(BUNDLED_PACKS)
    blob = json.dumps(registry)
    for name in FORBIDDEN_PACK_NAMES:
        assert name not in blob
        assert name not in BUNDLED_IDS
        assert name not in BUNDLED_PACKS
    assert bundled_pack_manifest()["exists"] is True
    cash = (method_root() / "cash" / "SKILL.md").read_text(encoding="utf-8")
    assert "receivables_aging" in cash
    assert "cash_13_weeks" in cash
    assert "payment" in cash.lower() or "支付" in cash


def test_cf11_real_provider_discovers_setup_and_close(tmp_path) -> None:
    from test_method_skill_runtime import _driver

    result = _driver(
        tmp_path,
        """
const result = await collect();
process.stdout.write(JSON.stringify(result));
""",
    )
    summaries = {skill["name"]: skill for skill in result["summaries"]}
    for pack_id in ("setup", "close"):
        assert pack_id in summaries
        loaded = result["loaded"][pack_id]
        assert loaded["path"].endswith(f"{pack_id}/SKILL.md")
        assert "/packs/" not in loaded["path"].replace("\\", "/")
        assert loaded["source"] == "bundled"
    for skill_id in BUNDLED_IDS:
        assert skill_id in summaries
        assert result["loaded"][skill_id]["path"].endswith(f"{skill_id}/SKILL.md")
