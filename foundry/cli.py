from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from foundry.brief import emit_brief
from foundry.context import resolve_context
from foundry.errors import REFUSED, FoundryError
from foundry.harness import assert_no_escaping_symlink
from foundry.launch_formulator import launch_formulator, purge_formulator_home, stop_formulator
from foundry.host_profile import host_smoke
from foundry.probe import mark_done, run_probe
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.references import record_reference
from foundry.sheet import workbook_bytes
from foundry.resources import fixture_root
from foundry.task import SESSION_ROLES, Filed, Task, TaskStore, resolve_task, session_owner
from foundry.window import Window, WindowStore


RECEIPT_HELP = (
    "wrap stdout as {text, filed}, where filed names the deliverable versions "
    "this call archived and whether each was newly appended"
)


def _say(ns: argparse.Namespace, text: str, filed: list[Filed], *, end: str = "") -> None:
    """One call's output, with or without its receipt.

    Without ``--receipt`` this is byte-for-byte what the command printed
    before, because the plain CLI is a surface an operator reads and a great
    many tests assert on. With it, the same text arrives inside an envelope
    naming what reached the timeline.

    ``filed`` is reported by the writers rather than derived from the store
    afterwards. Diffing ``seq`` around the call would look equivalent and is
    not: ``seq`` is allocated under the task lock across every window, so a
    concurrent follow-up on the same task lands in the gap, and the read side
    resolves its own task, which is not always the one that was written.
    """
    if not getattr(ns, "receipt", False):
        print(text, end=end)
        return
    # `end` is how the plain surface terminates a line, not part of the answer,
    # so the envelope carries the text without it.
    print(
        json.dumps(
            {"text": text, "filed": [record.as_receipt() for record in filed]},
            ensure_ascii=False,
        )
    )


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


def _adopt(
    tasks: TaskStore,
    window: Window,
    ns: argparse.Namespace,
    *,
    reason: str = "initial",
    extra_task_ids: tuple[str | None, ...] = (),
) -> Task | None:
    """Bind this window to the resolved task after validating session ownership.

    Adoption is on touch. A window created before the task store existed, or one
    an operator drove straight through the CLI, joins the first task that
    reaches it and keeps producing documents in the meantime. Both calls below
    are idempotent, so every later step on the same window is a no-op.

    Adoption only ever claims an unowned window. ``Window.bind_task`` has always
    refused to move a back-pointer that is already set -- "moving the pointer
    would leave those pointing at a timeline that no longer claims them" -- but
    that guard sat on one direction of a two-way binding. Reaching a window that
    another task owns skipped it entirely and went straight to
    ``task.bind_window``, so the chain gained a window whose own pointer still
    named someone else. Measured: ``--task A query-locked --brief-window <B's>``
    put B's window in A's chain while B kept the back-pointer. The two
    directions now refuse on the same rule.
    """
    task = resolve_task(
        tasks,
        explicit=getattr(ns, "task", "") or None,
        window_task_ids=(*extra_task_ids, window.task_id),
        session_id=getattr(ns, "session", "") or None,
    )
    if task is None:
        return None
    if window.task_id is None:
        window.bind_task(task.id)
    elif window.task_id != task.id:
        raise FoundryError(
            f"window {window.id} belongs to task {window.task_id}, not {task.id}; "
            "a follow-up answers on the timeline that owns the brief"
        )
    task.bind_window(window.id, reason=reason)
    session = str(getattr(ns, "session", "") or "").strip()
    if session and reason == "initial" and ns.cmd == "create":
        task.update_session_context(session, window_id=window.id)
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
    supplied = sys.argv[1:] if argv is None else argv
    if supplied and supplied[0] == "--_foundry-job-worker":
        from foundry.analysis_jobs import worker_main

        return worker_main(supplied[1:])
    parser = argparse.ArgumentParser(prog="foundry")
    parser.add_argument("--var", required=True)
    parser.add_argument(
        "--task",
        default="",
        help="task id; session calls use their registered task; sessionless CLI accepts FOUNDRY_TASK",
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

    p_ref = sub.add_parser("record-reference")
    p_ref.add_argument("--references", required=True)
    p_ref.add_argument("--receipt", action="store_true", help=RECEIPT_HELP)

    p_brief = sub.add_parser("emit-brief")
    p_brief.add_argument("--receipt", action="store_true", help=RECEIPT_HELP)

    p_wp = sub.add_parser("workpaper")
    p_wp.add_argument("--window", default="", help="window id; omit for the registered session or selected task window")

    p_method_skills = sub.add_parser("method-skills")
    p_method_skills.add_argument("--json", action="store_true", help="print the bundled skill root, ids, and file hashes")
    sub.add_parser("harness")

    p_presets = sub.add_parser("install-presets")
    p_presets.add_argument(
        "--dsh-home",
        default="",
        help="the harness home; omit to take DSH_HOME from the environment",
    )

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
    p_query.add_argument("--receipt", action="store_true", help=RECEIPT_HELP)

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
    p_task_rename = sub.add_parser("task-rename")
    p_task_rename.add_argument("--task", default=argparse.SUPPRESS, help="explicit task id")
    p_task_rename.add_argument("--title", required=True)
    sub.add_parser("deliverables")

    p_text = sub.add_parser("deliverable-text")
    p_text.add_argument("--sha", required=True, help="sha256 of an archived version")

    p_file = sub.add_parser("deliverable-path")
    p_file.add_argument("--sha", required=True, help="sha256 of an archived version")
    p_file.add_argument("--ext", default=".md", help="the row's ext; .xlsx for a workbook")

    p_session = sub.add_parser("record-session")
    p_session.add_argument("--role", default="", help=f"one of {SESSION_ROLES}; omit to derive")
    p_session.add_argument("--window", default="", help="bind this existing task window")
    p_session.add_argument("--parent-session", default="", help="inherit a registered parent context")
    p_session.add_argument("--workspace", default="", help="trusted runtime workspace directory")
    p_session.add_argument(
        "--verbatim",
        default="",
        help="what the leader actually asked, in their own words, not the executed query",
    )

    p_export = sub.add_parser("export")
    p_export.add_argument("--window", default="", help="window id; omit for the registered session or selected task window")
    p_export.add_argument("--kind", default="brief", choices=("brief", "workpaper"))
    p_export.add_argument(
        "--format",
        dest="fmt",
        default="md",
        choices=("md", "xlsx"),
        help="md files the rendered document as it stands; xlsx writes the whole window as a workbook",
    )

    p_probe = sub.add_parser("probe")
    p_probe.add_argument("--fixtures", default="")

    p_done = sub.add_parser("mark-done")
    p_done.add_argument("--skill", required=True)
    p_done.add_argument("--fixtures", default="")

    p_smoke = sub.add_parser("host-smoke")
    p_smoke.add_argument("--fixtures", default="")

    from foundry import analysis_cli, analysis_jobs, excel_bridge, finance_cli, finance_mcp

    analysis_cli.add_parsers(sub)
    analysis_jobs.add_parsers(sub)
    finance_cli.add_parsers(sub)
    finance_mcp.add_parsers(sub)
    excel_bridge.add_parsers(sub)
    args = parser.parse_args(argv)
    try:
        # Refuse unknown/mismatched sessions before a store constructor can
        # create directories or any command can append an unowned window.
        if args.session and args.cmd != "record-session":
            resolve_context(Path(args.var), session_id=args.session, task_id=args.task or None)
        if args.cmd == "task-rename":
            if not args.task:
                raise FoundryError("task-rename needs an explicit --task")
            task = TaskStore(Path(args.var)).get(args.task)
            metadata = task.rename(args.title)
            print(json.dumps({"task_id": task.id, "title": metadata["title"]}, ensure_ascii=False))
            return 0
        if finance_mcp.dispatch(args) or analysis_jobs.dispatch(args) or analysis_cli.dispatch(args) or finance_cli.dispatch(args) or excel_bridge.dispatch(args):
            return 0
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
        if args.cmd in {
            "task-show",
            "deliverables",
            "record-session",
            "deliverable-text",
            "deliverable-path",
        }:
            if args.cmd == "record-session":
                if args.parent_session:
                    task = resolve_context(
                        Path(args.var), session_id=args.parent_session,
                        task_id=args.task or None,
                    ).task
                else:
                    task = session_owner(tasks, args.session) if args.session else None
                    if task is not None and args.task and args.task != task.id:
                        raise FoundryError(f"session {args.session} already belongs to task {task.id}")
                    task = task or resolve_task(tasks, explicit=args.task or None) or tasks.current()
            else:
                task = resolve_context(
                    Path(args.var), session_id=args.session or None, task_id=args.task or None,
                ).task
            if task is None:
                raise FoundryError("no task; pass --task or run task-new")
            if args.cmd == "deliverables":
                print(json.dumps(task.deliverables(), ensure_ascii=False))
                return 0
            if args.cmd == "deliverable-text":
                # Addressed by digest, never by path. A caller naming a file
                # could name any file; a caller naming a sha can only reach a
                # version this task actually filed.
                print(task.artifact_text(args.sha), end="")
                return 0
            if args.cmd == "deliverable-path":
                # The same rule, for a version that is not text. The caller
                # still names a digest; what comes back is where this task
                # filed it, so the app can hand it to the operator's own
                # spreadsheet software without ever choosing a path itself.
                print(str(task.artifact_path(args.sha, ext=args.ext)))
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
                            session, role=role, leader_verbatim=args.verbatim or None,
                            window_id=args.window or None,
                            parent_session_id=args.parent_session or None,
                            workspace_path=Path(args.workspace) if args.workspace else None,
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
            # Validate an explicit task before creating an orphan on failure.
            resolve_task(tasks, explicit=args.task or None, session_id=args.session or None)
            created = store.create()
            _adopt(tasks, created, args)
            print(created.id)
            return 0
        if args.cmd == "probe":
            return run_probe(Path(args.var), fixture_root(Path(args.fixtures) if args.fixtures else None))
        if args.cmd == "mark-done":
            result = mark_done(
                Path(args.skill), Path(args.var), Path(args.fixtures) if args.fixtures else None,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.cmd == "host-smoke":
            fixtures = fixture_root(Path(args.fixtures) if args.fixtures else None)
            return host_smoke(Path(args.var), fixtures)
        if args.cmd == "method-skills":
            from foundry.method_skills import bundled_skill_files, bundled_skill_manifest

            if args.json:
                print(json.dumps(bundled_skill_manifest(), ensure_ascii=False))
                return 0
            for skill_id, path in bundled_skill_files().items():
                print(f"{skill_id}\t{path}")
            return 0
        if args.cmd == "harness":
            from foundry.harness import harness_text

            print(harness_text())
            return 0
        if args.cmd == "install-presets":
            from foundry.harness import install_presets

            home = args.dsh_home or os.environ.get("DSH_HOME") or ""
            if not home:
                raise FoundryError("install-presets needs --dsh-home or DSH_HOME")
            for path in install_presets(Path(home)):
                print(path)
            return 0
        addressed_id = (
            getattr(args, "brief_window", "") or getattr(args, "window", "") or None
        )
        context = resolve_context(
            Path(args.var), session_id=args.session or None, task_id=args.task or None,
            window_id=addressed_id, require_window=True,
        )
        window = context.window
        assert window is not None
        if args.cmd == "export":
            target = store.get(args.window) if args.window else window
            task = _adopt(tasks, target, args)
            if task is None:
                raise FoundryError("export needs a task; pass --task or run task-new")
            if args.fmt == "xlsx":
                # One workbook for the whole window rather than one per kind:
                # the conclusions and the schedules behind them are the same
                # document to the person reading it, and they are two files
                # only because markdown cannot hold a tab.
                if not target.brief_path.exists():
                    raise FoundryError("brief not written")
                print(
                    json.dumps(
                        task.register_bytes(
                            window_id=target.id,
                            kind="export",
                            data=workbook_bytes(target, task=task.meta()),
                            cause="export:xlsx",
                            session_id=args.session or None,
                            ext=".xlsx",
                        ).row,
                        ensure_ascii=False,
                    )
                )
                return 0
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
        if args.cmd == "record-reference":
            raw = Path(args.references)
            try:
                references = json.loads(raw.read_text() if raw.is_file() else args.references)
            except json.JSONDecodeError as exc:
                raise FoundryError("references argument is not valid JSON") from exc
            except OSError as exc:
                raise FoundryError(f"references file is unreadable: {args.references}") from exc
            if isinstance(references, dict):
                references = [references]
            _adopt(tasks, window, args)
            filed = []
            record_reference(
                window, references, session_id=args.session or None, filed=filed
            )
            # Silent without the flag, as it has always been: this verb answers
            # by refusing or by saying nothing.
            if args.receipt:
                _say(args, "", filed)
            return 0
        if args.cmd == "emit-brief":
            _adopt(tasks, window, args)
            filed: list[Filed] = []
            text = emit_brief(window, session_id=args.session or None, filed=filed)
            _say(args, text, filed)
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
            filed = []
            answer = query_locked(
                window,
                args.text,
                required_table_ids=args.tables.split(","),
                split_by=args.split_by or None,
                brief_window_id=args.brief_window or None,
                question_id=args.question_id or None,
                session_id=args.session or None,
                brief_sha=args.brief_sha or None,
                filed=filed,
            )
            _say(args, answer, filed, end="\n")
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
                if args.session:
                    task.update_session_context(args.session, window_id=nxt.id)
            print(nxt.id)
            return 0
    except FoundryError as exc:
        print(str(exc), file=sys.stderr)
        return REFUSED
    return REFUSED


if __name__ == "__main__":
    sys.exit(main())
