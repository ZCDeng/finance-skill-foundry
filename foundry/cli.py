from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from foundry.brief import emit_brief
from foundry.errors import REFUSED, FoundryError
from foundry.harness import assert_no_escaping_symlink
from foundry.launch_formulator import launch_formulator, purge_formulator_home, stop_formulator
from foundry.host_profile import host_smoke
from foundry.probe import mark_done, run_probe
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.resources import fixture_root
from foundry.window import WindowStore


def _store(ns: argparse.Namespace) -> WindowStore:
    """Open the store, turning an unusable ``--var`` into a refusal.

    ``--var`` is operator input like any other flag, and ``WindowStore`` creates
    directories on construction. Left unguarded it hands a caller a raw
    traceback with absolute paths on stderr and exit 1, which the dsh plugin
    then rethrows verbatim into the model's context.
    """
    try:
        return WindowStore(Path(ns.var))
    except OSError as exc:
        raise FoundryError(f"--var is not a usable directory: {ns.var} ({exc.strerror})") from exc



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


NAMED_SHAPES = (
    "named payload must be a list of {id,path}, an {id: path} map, "
    "or an envelope with a tables key"
)

DEFAULT_KEYS = ("coa", "aux", "map", "units")


def _named_entry(base: Path | None, item: Any) -> dict:
    if not isinstance(item, dict) or not item.get("id") or not item.get("path"):
        raise FoundryError("named table requires id and path")
    return {**item, "path": str(_resolve_payload_path(base, str(item["path"])))}


def _named_arg(raw: str) -> tuple[list[dict] | None, dict[str, Path]]:
    if not raw:
        return None, {}
    payload = Path(raw)
    payload_file = payload if payload.is_file() else None
    if payload_file is not None:
        # Two boundary moves, both of which make the descriptor's directory
        # something other than what the operator pointed at: the descriptor
        # itself being a link out, and a linked directory on the way down to it.
        assert_no_escaping_symlink(payload_file, "named descriptor")
        if payload_file.is_symlink():
            raise FoundryError(f"named descriptor must not be a symlink: {raw}")
    base = payload_file.parent if payload_file else None
    try:
        data = json.loads(payload_file.read_text() if payload_file else raw)
    except json.JSONDecodeError as exc:
        raise FoundryError("named argument is not valid JSON") from exc
    except OSError as exc:
        raise FoundryError(f"named descriptor is unreadable: {raw}") from exc
    if isinstance(data, list):
        return [_named_entry(base, item) for item in data], {}
    if isinstance(data, dict) and "tables" in data:
        defaults = {
            key: _resolve_payload_path(base, str(data[key]))
            for key in DEFAULT_KEYS
            if data.get(key)
        }
        tables = data["tables"]
        if not isinstance(tables, list):
            raise FoundryError("named envelope tables must be a list of {id,path}")
        return [_named_entry(base, item) for item in tables], defaults
    if isinstance(data, dict):
        stray = [key for key in DEFAULT_KEYS if key in data]
        if stray:
            raise FoundryError(
                f"named envelope is missing the tables key (saw {', '.join(stray)})"
            )
        return [
            {"id": key, "path": str(_resolve_payload_path(base, str(value)))}
            for key, value in data.items()
        ], {}
    raise FoundryError(NAMED_SHAPES)


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
    p_import.add_argument(
        "--named",
        default="",
        help=(
            "JSON (or a path to a JSON file): a list of {id,path}, an {id: path} map, "
            "or an envelope with tables plus optional coa/aux/map/units; "
            "omit to map drop-dir stems"
        ),
    )
    p_import.add_argument("--drop-dir", default="")

    sub.add_parser("lock")

    p_q = sub.add_parser("record-questions")
    p_q.add_argument("--questions", required=True)

    sub.add_parser("emit-brief")

    p_wp = sub.add_parser("workpaper")
    p_wp.add_argument("--window", default="", help="window id; omit for the current window")

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
    try:
        store = _store(args)
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
        if args.cmd == "workpaper" and args.window:
            # An explicit window id is the whole address. Resolving `current`
            # first would refuse a workpaper that is on disk just because a
            # re-import (or a fresh var) left no current window behind.
            target = store.get(args.window)
            if not target.workpaper_path.exists():
                raise FoundryError("workpaper not written")
            print(target.workpaper_path.read_text(), end="")
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
            try:
                questions = json.loads(raw.read_text() if raw.is_file() else args.questions)
            except json.JSONDecodeError as exc:
                raise FoundryError("questions argument is not valid JSON") from exc
            except OSError as exc:
                raise FoundryError(f"questions file is unreadable: {args.questions}") from exc
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
        return REFUSED
    return REFUSED


if __name__ == "__main__":
    sys.exit(main())
