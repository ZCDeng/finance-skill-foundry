from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from foundry.brief import emit_brief
from foundry.errors import FoundryError, QueryRefused
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.window import WindowStore

FIXTURE_REL = Path("fixtures/period-smoke")


def fixture_root(base: Path | None = None) -> Path:
    if base:
        return Path(base)
    return Path(__file__).resolve().parents[1] / FIXTURE_REL


def run_probe(var_root: Path, fixtures: Path) -> int:
    store = WindowStore(var_root)
    window = store.create()
    named = json.loads((fixtures / "named.json").read_text())
    window.import_tables(
        coa=fixtures / named["coa"],
        units=fixtures / named["units"],
        named=[{"id": item["id"], "path": fixtures / item["path"]} for item in named["tables"]],
        drop_dir=fixtures,
    )
    window.lock()
    questions = json.loads((fixtures / "questions.json").read_text())
    record_questions(window, questions)
    brief = emit_brief(window)
    if "稿外追问" in brief:
        raise FoundryError("probe brief carried 稿外追问")
    tagged = query_locked(window, "in-window split", required_table_ids=["gl"], split_by="unit_id")
    if not tagged.startswith("稿外追问"):
        raise FoundryError("probe expected tagged recompute")
    try:
        query_locked(window, "unnamed refuse", required_table_ids=["not_a_table"])
    except QueryRefused:
        return 0
    raise FoundryError("probe expected unnamed refuse")


def skill_contains_questions(skill_dir: Path) -> bool:
    for path in skill_dir.rglob("*"):
        if path.is_file() and path.name.lower() in {"questions.md", "questions.json"}:
            return True
    return False


def mark_done(skill_dir: Path, var_root: Path, fixtures: Path | None = None) -> None:
    if skill_contains_questions(skill_dir):
        raise FoundryError("skill must not contain this-window questions")
    code = run_probe(var_root, fixture_root(fixtures))
    if code != 0:
        raise FoundryError("fixture probe failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--var", required=True)
    parser.add_argument("--fixtures", default="")
    args = parser.parse_args(argv)
    try:
        return run_probe(Path(args.var), fixture_root(Path(args.fixtures) if args.fixtures else None))
    except FoundryError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
