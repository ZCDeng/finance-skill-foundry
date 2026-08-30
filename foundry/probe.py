from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from foundry.brief import emit_brief
from foundry.errors import FoundryError, QueryRefused
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.resources import fixture_root
from foundry.window import WindowStore

CONTRACT_FILE = "foundry.json"
CONTRACT_SCHEMA = "finance-skill-foundry/f2-skill@1"
PERIOD_TOOL_SEQUENCE = ("import", "lock", "record-questions", "emit-brief", "query-locked")
REQUIRED_SAFETY = {
    "questions_in_window": True,
    "no_read_document_books": True,
    "tag_followups": True,
}


def run_probe(var_root: Path, fixtures: Path) -> int:
    store = WindowStore(var_root)
    window = store.create()
    named = json.loads((fixtures / "named.json").read_text())
    window.import_tables(
        coa=fixtures / named["coa"],
        named=[{"id": item["id"], "path": fixtures / item["path"]} for item in named["tables"]],
        aux=fixtures / named["aux"] if named.get("aux") else None,
        map=fixtures / named["map"] if named.get("map") else None,
        units=fixtures / named["units"] if named.get("units") else None,
        drop_dir=fixtures,
    )
    window.lock()
    available = set(window.table_names())
    questions = [
        question
        for question in json.loads((fixtures / "questions.json").read_text())
        if set(question.get("required_table_ids") or []) <= available
    ]
    if not questions:
        raise FoundryError("probe fixture has no in-window questions")
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


def validate_authored_skill(skill_dir: Path) -> None:
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.is_file():
        raise FoundryError("skill must contain SKILL.md")
    text = skill_path.read_text(encoding="utf-8").strip()
    if not text:
        raise FoundryError("skill must contain authored instructions")
    contract_path = skill_dir / CONTRACT_FILE
    if not contract_path.is_file():
        raise FoundryError(f"skill must contain {CONTRACT_FILE} capability contract")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FoundryError(f"{CONTRACT_FILE} is not valid JSON") from exc
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise FoundryError(f"{CONTRACT_FILE} schema must be {CONTRACT_SCHEMA}")
    if contract.get("capability") != "f2-period-analysis":
        raise FoundryError(f"{CONTRACT_FILE} capability must be f2-period-analysis")
    if tuple(contract.get("period_tools") or ()) != PERIOD_TOOL_SEQUENCE:
        raise FoundryError(f"{CONTRACT_FILE} period_tools must be {','.join(PERIOD_TOOL_SEQUENCE)}")
    safety = contract.get("safety") or {}
    missing_safety = [key for key, value in REQUIRED_SAFETY.items() if safety.get(key) is not value]
    if missing_safety:
        raise FoundryError(f"{CONTRACT_FILE} missing safety policy: {','.join(missing_safety)}")
    declared_docs = set(contract.get("method_docs") or [])
    missing_docs = [doc for doc in ("FOUNDRY.md", "CONNECTORS.md") if doc not in declared_docs or doc not in text]
    if missing_docs:
        raise FoundryError(f"skill must bind foundry method docs: {','.join(missing_docs)}")


def mark_done(skill_dir: Path, var_root: Path, fixtures: Path | None = None) -> None:
    if skill_contains_questions(skill_dir):
        raise FoundryError("skill must not contain this-window questions")
    validate_authored_skill(skill_dir)
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
