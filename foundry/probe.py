from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from foundry.brief import emit_brief
from foundry.caliber import table_key
from foundry.catalog import quote_ident
from foundry.errors import REFUSED, FoundryError, QueryRefused
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.resources import fixture_root
from foundry.tags import OUTSIDE, RECOMPUTED
from foundry.window import Window, WindowStore
from foundry.workpaper import load_schedules

CONTRACT_FILE = "foundry.json"
CONTRACT_SCHEMA = "finance-skill-foundry/f2-skill@1"
PERIOD_TOOL_SEQUENCE = ("import", "lock", "record-questions", "emit-brief", "query-locked")
REQUIRED_SAFETY = {
    "questions_in_window": True,
    "no_read_document_books": True,
    "tag_followups": True,
}
PROBE_SPLIT_TEXT = "in-window split"
PROBE_SPLIT_TABLE = "gl"
PROBE_SPLIT_BY = "unit_id"
PROBE_REFUSE_TEXT = "unnamed refuse"
PROBE_ABSENT_TABLE = "not_a_table"
FOLLOWUP_TAG = f"{OUTSIDE} / {RECOMPUTED}"
ANSWER_NOTE_OPEN = "（"


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise FoundryError(f"probe cannot read amount {value!r} as a number") from exc


def _locked_split(window: Window, table: str, split_by: str) -> dict[str, Decimal]:
    """Recompute the split straight off the locked catalog, without query_locked."""
    columns = [str(row[0]) for row in window.query(f"DESCRIBE {quote_ident(table)}")]
    for column in (split_by, "amount"):
        if column not in columns:
            raise FoundryError(f"probe fixture table {table} has no {column} column")
    totals: dict[str, Decimal] = {}
    for row in window.query(f"SELECT * FROM {quote_ident(table)}"):
        record = dict(zip(columns, row))
        key = str(record[split_by])
        totals[key] = totals.get(key, Decimal(0)) + _decimal(record["amount"])
    if not totals:
        raise FoundryError(f"probe fixture table {table} has no rows to split")
    return totals


def _parse_split(tagged: str) -> dict[str, Decimal]:
    head, arrow, body = tagged.partition(" → ")
    if not arrow or head != f"{FOLLOWUP_TAG}: {PROBE_SPLIT_TEXT}":
        raise FoundryError(f"probe expected tagged recompute, got: {tagged}")
    # An answer may close with a （窗口: …）note naming the window it came from.
    # The split itself is everything before that note.
    body = body.partition(ANSWER_NOTE_OPEN)[0].strip()
    parsed: dict[str, Decimal] = {}
    for chunk in body.split(", "):
        key, sep, amount = chunk.partition("=")
        if not sep or not key.strip():
            raise FoundryError(f"probe expected tagged recompute to carry a split, got: {tagged}")
        parsed[key.strip()] = _decimal(amount.strip())
    return parsed


def _assert_tagged_recompute(tagged: str, expected: dict[str, Decimal]) -> None:
    parsed = _parse_split(tagged)
    if parsed != expected:
        raise FoundryError(
            f"probe recompute does not match locked {PROBE_SPLIT_TABLE}: "
            f"expected {_render_split(expected)}, got {_render_split(parsed)}"
        )


def _render_split(split: dict[str, Decimal]) -> str:
    return ", ".join(f"{key}={split[key]}" for key in sorted(split))


def _assert_followup_persisted(window: Window, expected: dict[str, Decimal]) -> None:
    items = [item for item in load_schedules(window).get("items") or [] if item.get("origin") == "followup"]
    if len(items) != 1:
        raise FoundryError(f"probe expected one persisted {OUTSIDE} workpaper item, got {len(items)}")
    item = items[0]
    if item.get("text") != PROBE_SPLIT_TEXT:
        raise FoundryError(f"probe {OUTSIDE} workpaper item lost its question: {item.get('text')!r}")
    if item.get("table") != PROBE_SPLIT_TABLE or item.get("split_by") != PROBE_SPLIT_BY:
        raise FoundryError(
            f"probe {OUTSIDE} workpaper item lost its source: "
            f"table={item.get('table')!r} split_by={item.get('split_by')!r}"
        )
    if item.get("tag") != FOLLOWUP_TAG:
        raise FoundryError(f"probe {OUTSIDE} workpaper item is tagged {item.get('tag')!r}")
    recorded: dict[str, Decimal] = {}
    for line in item.get("lines") or []:
        key = str(line.get("node_id") or "")
        recorded[key] = recorded.get(key, Decimal(0)) + _decimal(line.get("amount"))
    if recorded != expected:
        raise FoundryError(
            f"probe {OUTSIDE} workpaper lines do not match locked {PROBE_SPLIT_TABLE}: "
            f"expected {_render_split(expected)}, got {_render_split(recorded)}"
        )
    total = sum(expected.values(), Decimal(0))
    if item.get("recomputed") is None or _decimal(item["recomputed"]) != total:
        raise FoundryError(
            f"probe {OUTSIDE} workpaper item recomputed {item.get('recomputed')!r}, locked total is {total}"
        )
    if not window.workpaper_path.exists() or PROBE_SPLIT_TEXT not in window.workpaper_path.read_text():
        raise FoundryError(f"probe expected the {OUTSIDE} recompute to reach the workpaper")
    if not window.followup_path.exists():
        raise FoundryError(f"probe expected the {OUTSIDE} recompute to be recorded in followup.jsonl")
    records = [json.loads(line) for line in window.followup_path.read_text().splitlines() if line.strip()]
    if not any(record.get("text") == PROBE_SPLIT_TEXT and record.get("tag") == OUTSIDE for record in records):
        raise FoundryError(f"probe expected the {OUTSIDE} recompute to be recorded in followup.jsonl")


def _fixture_json(fixtures: Path, name: str) -> Any:
    """Read one fixture file, refusing rather than raising a raw OSError.

    ``--fixtures`` is operator input, and a done-gate that answers a wrong path
    with a traceback tells the author nothing about what to fix.
    """
    if not fixtures.is_dir():
        raise FoundryError(f"probe fixtures directory is missing: {fixtures}")
    path = fixtures / name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FoundryError(f"probe fixture is unreadable: {path}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FoundryError(f"probe fixture is not valid JSON: {path}") from exc


def run_probe(var_root: Path, fixtures: Path) -> int:
    try:
        store = WindowStore(var_root)
    except OSError as exc:
        raise FoundryError(f"--var is not a usable directory: {var_root} ({exc.strerror})") from exc
    window = store.create(make_current=False)
    named = _fixture_json(fixtures, "named.json")
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
        for question in _fixture_json(fixtures, "questions.json")
        if {table_key(table) for table in question.get("required_table_ids") or []} <= available
    ]
    if not questions:
        raise FoundryError("probe fixture has no in-window questions")
    record_questions(window, questions)
    brief = emit_brief(window)
    if OUTSIDE in brief:
        raise FoundryError(f"probe brief carried {OUTSIDE}")
    expected = _locked_split(window, PROBE_SPLIT_TABLE, PROBE_SPLIT_BY)
    tagged = query_locked(
        window, PROBE_SPLIT_TEXT, required_table_ids=[PROBE_SPLIT_TABLE], split_by=PROBE_SPLIT_BY
    )
    _assert_tagged_recompute(tagged, expected)
    _assert_followup_persisted(window, expected)
    try:
        query_locked(window, PROBE_REFUSE_TEXT, required_table_ids=[PROBE_ABSENT_TABLE])
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
    except FoundryError as exc:
        print(str(exc), file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
