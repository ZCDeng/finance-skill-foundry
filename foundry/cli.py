from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from foundry.brief import emit_brief
from foundry.errors import FoundryError
from foundry.launch_formulator import launch_formulator, purge_formulator_home, stop_formulator
from foundry.host_profile import host_smoke
from foundry.probe import mark_done, run_probe
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.resources import fixture_root
from foundry.window import WindowStore


def _store(ns: argparse.Namespace) -> WindowStore:
    return WindowStore(Path(ns.var))



def _resolve_payload_path(base: Path | None, value: str) -> Path:
    path = Path(value)
    if base is None:
        return path
    root = base.resolve()
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FoundryError(f"named path escapes descriptor directory: {value}") from exc
    return candidate


def _named_arg(raw: str) -> tuple[list[dict] | None, dict[str, Path]]:
    if not raw:
        return None, {}
    payload = Path(raw)
    payload_file = payload.resolve() if payload.is_file() else None
    base = payload_file.parent if payload_file else None
    try:
        data = json.loads(payload_file.read_text() if payload_file else raw)
    except json.JSONDecodeError as exc:
        raise FoundryError("named argument is not valid JSON") from exc
    if isinstance(data, list):
        return [
            {**item, "path": str(_resolve_payload_path(base, str(item["path"])))}
            for item in data
        ], {}
    if isinstance(data, dict) and "tables" in data:
        defaults = {
            key: _resolve_payload_path(base, str(data[key]))
            for key in ("coa", "aux", "map", "units")
            if data.get(key)
        }
        tables = [
            {**item, "path": str(_resolve_payload_path(base, str(item["path"])))}
            for item in data["tables"]
        ]
        return tables, defaults
    if isinstance(data, dict):
        return [{"id": key, "path": str(_resolve_payload_path(base, str(value)))} for key, value in data.items()], {}
    return data, {}


def _import_kwargs(args: argparse.Namespace) -> dict:
    named, defaults = _named_arg(args.named)
    return {
        "coa": Path(args.coa) if args.coa else defaults.get("coa"),
        "named": named,
        "aux": Path(args.aux) if args.aux else defaults.get("aux"),
        "map": Path(args.map) if args.map else defaults.get("map"),
        "units": Path(args.units) if args.units else defaults.get("units"),
        "drop_dir": Path(args.drop_dir) if args.drop_dir else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foundry")
    parser.add_argument("--var", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("create")

    p_import = sub.add_parser("import")
    p_import.add_argument("--coa", default="")
    p_import.add_argument("--aux", default="")
    p_import.add_argument("--map", default="")
    p_import.add_argument("--units", default="", help="optional shortcut dim of aux")
    p_import.add_argument("--named", default="", help="JSON list of {id,path}; omit to map drop-dir stems")
    p_import.add_argument("--drop-dir", default="")

    sub.add_parser("lock")

    p_q = sub.add_parser("record-questions")
    p_q.add_argument("--questions", required=True)

    sub.add_parser("emit-brief")
    sub.add_parser("workpaper")
    sub.add_parser("method-skills")
    sub.add_parser("harness")

    p_query = sub.add_parser("query-locked")
    p_query.add_argument("--text", required=True)
    p_query.add_argument("--tables", required=True)
    p_query.add_argument("--split-by", default="")
    p_query.add_argument("--brief-window", default="")
    p_query.add_argument("--question-id", default="")

    sub.add_parser("launch-formulator")
    sub.add_parser("stop-formulator")
    sub.add_parser("purge-formulator")

    p_re = sub.add_parser("re-import")
    p_re.add_argument("--coa", default="")
    p_re.add_argument("--aux", default="")
    p_re.add_argument("--map", default="")
    p_re.add_argument("--units", default="")
    p_re.add_argument("--named", default="")
    p_re.add_argument("--drop-dir", default="")

    p_probe = sub.add_parser("probe")
    p_probe.add_argument("--fixtures", default="")

    p_done = sub.add_parser("mark-done")
    p_done.add_argument("--skill", required=True)
    p_done.add_argument("--fixtures", default="")

    p_smoke = sub.add_parser("host-smoke")
    p_smoke.add_argument("--fixtures", default="")

    args = parser.parse_args(argv)
    store = _store(args)
    try:
        if args.cmd == "create":
            print(store.create().id)
            return 0
        if args.cmd == "probe":
            return run_probe(Path(args.var), fixture_root(Path(args.fixtures) if args.fixtures else None))
        if args.cmd == "mark-done":
            mark_done(Path(args.skill), Path(args.var), Path(args.fixtures) if args.fixtures else None)
            return 0
        if args.cmd == "host-smoke":
            fixtures = fixture_root(Path(args.fixtures) if args.fixtures else None)
            return host_smoke(Path(args.var), fixtures)
        if args.cmd == "method-skills":
            from foundry.method_skills import bundled_skill_files

            for skill_id, path in bundled_skill_files().items():
                print(f"{skill_id}\t{path}")
            return 0
        if args.cmd == "harness":
            from foundry.harness import harness_text

            print(harness_text())
            return 0
        window = store.current()
        if args.cmd == "import":
            window.import_tables(**_import_kwargs(args))
            return 0
        if args.cmd == "lock":
            window.lock()
            return 0
        if args.cmd == "record-questions":
            raw = Path(args.questions)
            questions = json.loads(raw.read_text() if raw.is_file() else args.questions)
            record_questions(window, questions)
            return 0
        if args.cmd == "emit-brief":
            print(emit_brief(window), end="")
            return 0
        if args.cmd == "workpaper":
            if not window.workpaper_path.exists():
                raise FoundryError("workpaper not written")
            print(window.workpaper_path.read_text(), end="")
            return 0
        if args.cmd == "query-locked":
            print(
                query_locked(
                    window,
                    args.text,
                    required_table_ids=args.tables.split(","),
                    split_by=args.split_by or None,
                    brief_window_id=args.brief_window or None,
                    question_id=args.question_id or None,
                )
            )
            return 0
        if args.cmd == "launch-formulator":
            print(json.dumps(launch_formulator(window)))
            return 0
        if args.cmd == "stop-formulator":
            print(json.dumps(stop_formulator(window)))
            return 0
        if args.cmd == "purge-formulator":
            purge_formulator_home(window)
            return 0
        if args.cmd == "re-import":
            nxt = window.reimport(**_import_kwargs(args))
            print(nxt.id)
            return 0
    except FoundryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
