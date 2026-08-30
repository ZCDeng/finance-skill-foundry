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
from foundry.task import SESSION_ROLES, Task, TaskStore, resolve_task
from foundry.window import Window, WindowStore


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



SESSION_ROLE_BY_CMD = {
    "query-locked": "followup",
    "mark-done": "author",
}
"""Which kind of conversation a command belongs to.

The role is decided by which command ran, not asked of the caller and never of
a model. Everything not named here is a period step.
"""


def _session_role(cmd: str) -> str:
    return SESSION_ROLE_BY_CMD.get(cmd, "period")


def _adopt(
    tasks: TaskStore,
    window: Window,
    ns: argparse.Namespace,
    *,
    reason: str = "initial",
    extra_task_ids: tuple[str | None, ...] = (),
) -> Task | None:
    """Bind this window to a task, and record the conversation it happened in.

    Adoption is on touch. A window created before the task store existed, or one
    an operator drove straight through the CLI, joins the first task that
    reaches it and keeps producing documents in the meantime. Both calls below
    are idempotent, so every later step on the same window is a no-op.
    """
    task = resolve_task(
        tasks,
        explicit=getattr(ns, "task", "") or None,
        window_task_ids=(*extra_task_ids, window.task_id),
    )
    if task is None:
        return None
    if window.task_id is None:
        window.bind_task(task.id)
    task.bind_window(window.id, reason=reason)
    session = str(getattr(ns, "session", "") or "").strip()
    if session:
        task.record_session(session, role=_session_role(ns.cmd))
    return task


def _window_inputs(window: Window) -> list[dict[str, Any]]:
    """What this window was built from, read off its own manifest.

    There is no second index file. The manifest already names every role, the
    operator's original path, the archived copy and its digest, so deriving the
    view keeps one source of truth for what came in.
    """
    if not window.lock_path.exists():
        return []
    manifest = json.loads(window.lock_path.read_text())
    rows: list[dict[str, Any]] = []
    entries: list[tuple[str, Any]] = [
        *((role, manifest.get(role)) for role in ("coa", "aux", "map", "units")),
        *sorted((manifest.get("named") or {}).items()),
    ]
    for role, meta in entries:
        if not isinstance(meta, dict) or not meta.get("archived"):
            continue
        archived = window.root / str(meta["archived"])
        rows.append(
            {
                "role": role,
                "origin_path": meta.get("path"),
                "archived": meta.get("archived"),
                "sha256": meta.get("source_hash"),
                "bytes": archived.stat().st_size if archived.is_file() else None,
                "present": archived.is_file(),
                "derived_from": meta.get("derived_from"),
            }
        )
    return rows


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
    parser.add_argument(
        "--task",
        default="",
        help="task id; omit to take FOUNDRY_TASK, then the addressed window's own task",
    )
    parser.add_argument(
        "--session",
        default="",
        help="conversation id this call happened in; the harness supplies it per call",
    )
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
    p_query.add_argument(
        "--brief-sha",
        default="",
        help="sha256 of the exported brief the leader read; anchors the answer to that version",
    )

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

    p_task_new = sub.add_parser("task-new")
    p_task_new.add_argument("--title", required=True)
    p_task_new.add_argument("--period", default="", help="the period this task closes, e.g. 2026-08")
    p_task_new.add_argument("--skill", default="", help="authored skill id, when there is one")

    sub.add_parser("task-list")
    sub.add_parser("task-show")
    sub.add_parser("deliverables")

    p_session = sub.add_parser("record-session")
    p_session.add_argument("--role", default="", help=f"one of {SESSION_ROLES}; omit to derive")
    p_session.add_argument(
        "--verbatim",
        default="",
        help="what the leader actually asked, in their own words, not the executed query",
    )

    p_export = sub.add_parser("export")
    p_export.add_argument("--window", default="", help="window id; omit for the current window")
    p_export.add_argument("--kind", default="brief", choices=("brief", "workpaper"))

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
        tasks = TaskStore(Path(args.var))
        if args.cmd == "task-new":
            task = tasks.create(
                title=args.title,
                period=args.period or None,
                skill_id=args.skill or None,
            )
            print(task.id)
            return 0
        if args.cmd == "task-list":
            print(
                json.dumps(
                    [
                        {**task.meta(), "windows": len(task.windows())}
                        for task in tasks.list()
                    ],
                    ensure_ascii=False,
                )
            )
            return 0
        if args.cmd in {"task-show", "deliverables", "record-session"}:
            task = resolve_task(tasks, explicit=args.task or None)
            if task is None:
                task = tasks.current()
            if task is None:
                raise FoundryError("no task; pass --task or run task-new")
            if args.cmd == "deliverables":
                print(json.dumps(task.deliverables(), ensure_ascii=False))
                return 0
            if args.cmd == "record-session":
                session = str(args.session or "").strip()
                if not session:
                    raise FoundryError("record-session needs --session")
                role = args.role or "followup"
                if role not in SESSION_ROLES:
                    raise FoundryError(f"session role must be one of {SESSION_ROLES}: {role}")
                print(
                    json.dumps(
                        task.record_session(
                            session, role=role, leader_verbatim=args.verbatim or None
                        ),
                        ensure_ascii=False,
                    )
                )
                return 0
            windows = []
            for row in task.windows():
                target = store.get(str(row["window_id"]))
                windows.append({**row, "state": target.state, "inputs": _window_inputs(target)})
            print(
                json.dumps(
                    {
                        "task": task.meta(),
                        "windows": windows,
                        "sessions": task.sessions(),
                        "deliverables": task.deliverables(),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.cmd == "create":
            created = store.create()
            _adopt(tasks, created, args)
            print(created.id)
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
        if args.cmd == "export":
            target = store.get(args.window) if args.window else window
            task = _adopt(tasks, target, args)
            if task is None:
                raise FoundryError("export needs a task; pass --task or run task-new")
            path = target.brief_path if args.kind == "brief" else target.workpaper_path
            if not path.exists():
                raise FoundryError(f"{args.kind} not written")
            print(
                json.dumps(
                    task.register_deliverable(
                        window_id=target.id,
                        kind="export",
                        text=path.read_text(),
                        cause=f"export:{args.kind}",
                        session_id=args.session or None,
                    ),
                    ensure_ascii=False,
                )
            )
            return 0
        if args.cmd == "import":
            _adopt(tasks, window, args)
            window.import_tables(**_import_kwargs(args))
            return 0
        if args.cmd == "lock":
            _adopt(tasks, window, args)
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
            _adopt(tasks, window, args)
            record_questions(window, questions)
            return 0
        if args.cmd == "emit-brief":
            _adopt(tasks, window, args)
            print(emit_brief(window, session_id=args.session or None), end="")
            return 0
        if args.cmd == "workpaper":
            if not window.workpaper_path.exists():
                raise FoundryError("workpaper not written")
            print(window.workpaper_path.read_text(), end="")
            return 0
        if args.cmd == "query-locked":
            # The follow-up belongs to the task that owns the brief under
            # discussion, not to whatever window happens to be current: a
            # re-import since that brief moved current on, and the answer still
            # has to land on the timeline the leader is reading.
            addressed = store.get(args.brief_window) if args.brief_window else window
            _adopt(tasks, addressed, args, extra_task_ids=(addressed.task_id,))
            print(
                query_locked(
                    window,
                    args.text,
                    required_table_ids=args.tables.split(","),
                    split_by=args.split_by or None,
                    brief_window_id=args.brief_window or None,
                    question_id=args.question_id or None,
                    session_id=args.session or None,
                    brief_sha=args.brief_sha or None,
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
            task = _adopt(tasks, window, args)
            nxt = window.reimport(**_import_kwargs(args))
            if task is not None:
                # The successor joins the same task, marked as the re-import it
                # is. The old window keeps its brief and its follow-ups; the
                # chain is what makes them one period rather than two.
                nxt.bind_task(task.id)
                task.bind_window(nxt.id, reason="reimport")
            print(nxt.id)
            return 0
    except FoundryError as exc:
        print(str(exc), file=sys.stderr)
        return REFUSED
    return REFUSED


if __name__ == "__main__":
    sys.exit(main())
