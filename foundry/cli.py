from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from foundry.brief import emit_brief
from foundry.errors import FoundryError
from foundry.launch_formulator import launch_formulator
from foundry.host_profile import host_smoke
from foundry.probe import mark_done, run_probe
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.window import WindowStore


def _store(ns: argparse.Namespace) -> WindowStore:
    return WindowStore(Path(ns.var))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foundry")
    parser.add_argument("--var", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("create")

    p_import = sub.add_parser("import")
    p_import.add_argument("--coa", required=True)
    p_import.add_argument("--aux", default="")
    p_import.add_argument("--map", default="")
    p_import.add_argument("--units", default="", help="optional shortcut dim of aux")
    p_import.add_argument("--named", required=True, help="JSON list of {id,path}")
    p_import.add_argument("--drop-dir", default="")

    sub.add_parser("lock")

    p_q = sub.add_parser("record-questions")
    p_q.add_argument("--questions", required=True)

    sub.add_parser("emit-brief")
    sub.add_parser("workpaper")

    p_query = sub.add_parser("query-locked")
    p_query.add_argument("--text", required=True)
    p_query.add_argument("--tables", required=True)
    p_query.add_argument("--split-by", default="")
    p_query.add_argument("--brief-window", default="")

    sub.add_parser("launch-formulator")

    p_re = sub.add_parser("re-import")
    p_re.add_argument("--coa", required=True)
    p_re.add_argument("--aux", default="")
    p_re.add_argument("--map", default="")
    p_re.add_argument("--units", default="")
    p_re.add_argument("--named", required=True)
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
            return run_probe(Path(args.var), Path(args.fixtures) if args.fixtures else Path("fixtures/period-smoke"))
        if args.cmd == "mark-done":
            mark_done(Path(args.skill), Path(args.var), Path(args.fixtures) if args.fixtures else None)
            return 0
        if args.cmd == "host-smoke":
            fixtures = Path(args.fixtures) if args.fixtures else Path(__file__).resolve().parents[1] / "fixtures" / "period-smoke"
            return host_smoke(Path(args.var), fixtures)
        window = store.current()
        if args.cmd == "import":
            named = json.loads(Path(args.named).read_text() if Path(args.named).is_file() else args.named)
            window.import_tables(
                coa=Path(args.coa),
                named=named,
                aux=Path(args.aux) if args.aux else None,
                map=Path(args.map) if args.map else None,
                units=Path(args.units) if args.units else None,
                drop_dir=Path(args.drop_dir) if args.drop_dir else None,
            )
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
                )
            )
            return 0
        if args.cmd == "launch-formulator":
            print(json.dumps(launch_formulator(window)))
            return 0
        if args.cmd == "re-import":
            named = json.loads(Path(args.named).read_text() if Path(args.named).is_file() else args.named)
            nxt = window.reimport(
                coa=Path(args.coa),
                named=named,
                aux=Path(args.aux) if args.aux else None,
                map=Path(args.map) if args.map else None,
                units=Path(args.units) if args.units else None,
                drop_dir=Path(args.drop_dir) if args.drop_dir else None,
            )
            print(nxt.id)
            return 0
    except FoundryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
