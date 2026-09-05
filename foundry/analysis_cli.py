"""JSON CLI facade for the task-owned analysis service."""

from __future__ import annotations

import json
from pathlib import Path

from foundry.analysis import AnalysisStore
from foundry.analysis_data import json_value, load_json
from foundry.context import resolve_context
from foundry.errors import FoundryError

COMMANDS = {
    "method-resource",
    "analysis-state",
    "dataset-add",
    "dataset-read",
    "analysis-save",
    "analysis-run",
    "analysis-draft",
    "analysis-export",
    "analysis-method-save",
    "analysis-method-apply",
    "analysis-refresh",
    "analysis-script",
    "analysis-output",
}


def add_parsers(sub):
    p = sub.add_parser("method-resource")
    p.add_argument("--skill", required=True)
    p.add_argument("--resource", required=True)
    sub.add_parser("analysis-state")
    sub.add_parser("analysis-refresh")
    p = sub.add_parser("dataset-add")
    p.add_argument("--path", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--meta", default="{}")
    p = sub.add_parser("dataset-read")
    p.add_argument("--dataset", required=True)
    p = sub.add_parser("analysis-save")
    p.add_argument("--spec", required=True)
    p = sub.add_parser("analysis-run")
    p.add_argument("--analysis", required=True)
    p = sub.add_parser("analysis-draft")
    p.add_argument("--spec", required=True)
    p = sub.add_parser("analysis-export")
    p.add_argument("--draft", required=True)
    p.add_argument("--format", choices=["md", "xlsx"], default="md")
    p = sub.add_parser("analysis-method-save")
    p.add_argument("--analysis", required=True)
    p.add_argument("--name", required=True)
    p = sub.add_parser("analysis-method-apply")
    p.add_argument("--method", required=True)
    p.add_argument("--bindings", required=True)
    p.add_argument("--question")
    p.add_argument("--parameters", default="[]")
    p = sub.add_parser("analysis-script")
    p.add_argument("--spec", required=True)
    p = sub.add_parser("analysis-output")
    p.add_argument("--run", required=True)
    p.add_argument("--output", required=True)


def _json(value, label):
    result = load_json(value)
    if not isinstance(result, dict):
        raise FoundryError(f"{label} must be a JSON object")
    return result


def _bound(context, bindings):
    if not isinstance(bindings, dict):
        raise FoundryError("bindings must be a JSON object")
    if any(not isinstance(value, str) for value in bindings.values()):
        raise FoundryError("snapshot IDs must be strings")
    if context.session_id:
        unknown = set(bindings.values()) - set(context.snapshot_ids)
        if unknown:
            raise FoundryError(
                "snapshots are outside this session context; use analysis-refresh to include task datasets"
            )


def _uploaded_path(context, value):
    source = Path(value).expanduser()
    if not context.session_id:
        return source
    workspace = context.workspace_path
    if workspace is None:
        raise FoundryError("session has no registered workspace for uploaded files")
    if not source.is_absolute():
        source = workspace / source
    resolved = source.resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise FoundryError("dataset source is outside the registered session workspace")
    current = source
    while current != workspace and current != current.parent:
        if current.is_symlink():
            raise FoundryError("uploaded dataset cannot use symbolic links")
        current = current.parent
    # Default workspace shares a parent with broker-owned records; uploads are
    # the only writable/authorized sources there. Custom workspaces are scoped
    # by the trusted registration, but still cannot read canonical task records.
    canonical = context.task.root / "analysis"
    if resolved.is_relative_to(canonical.resolve()):
        allowed = [
            workspace / "uploads",
            workspace / "inputs",
            workspace / ".dsh-uploads",
        ]
        if not any(resolved.is_relative_to(root.resolve()) for root in allowed):
            raise FoundryError("dataset source is not an uploaded/authorized input")
    return source


def dispatch(args) -> bool:
    if args.cmd not in COMMANDS:
        return False
    context = resolve_context(
        Path(args.var), session_id=args.session or None, task_id=args.task or None
    )
    if context.task is None:
        raise FoundryError("analysis requires a task; run task-new or provide --task")
    service = AnalysisStore(context.task)
    if args.cmd == "method-resource":
        from foundry.method_skills import read_method_resource

        result = read_method_resource(args.skill, args.resource)
    elif args.cmd == "analysis-state":
        result = service.state()
        if context.session_id:
            allowed = set(context.snapshot_ids)
            result["datasets"] = [d for d in result["datasets"] if d["id"] in allowed]
            result["analyses"] = [
                a for a in result["analyses"] if set(a["bindings"].values()) <= allowed
            ]
            result["runs"] = [
                r for r in result["runs"] if set(r["bindings"].values()) <= allowed
            ]
            run_ids = {r["id"] for r in result["runs"]}
            result["drafts"] = [
                d
                for d in result["drafts"]
                if set(d["run_ids"]) <= run_ids
                and all(
                    not c.get("dataset_id") or c["dataset_id"] in allowed
                    for c in d["claims"]
                )
            ]
        result["context"] = {
            "session_id": context.session_id,
            "context_revision": context.context_revision,
            "snapshot_ids": list(context.snapshot_ids),
            "workspace_id": context.workspace_id,
        }
    elif args.cmd == "analysis-refresh":
        if not context.session_id:
            raise FoundryError("analysis-refresh requires a registered --session")
        ids = [r["id"] for r in service.state()["datasets"]]
        session = next(
            r for r in context.task.sessions() if r["session_id"] == context.session_id
        )
        if session.get("parent_session_id"):
            ceiling = session.get("snapshot_ceiling", session.get("snapshot_ids", []))
            ids = [snapshot_id for snapshot_id in ids if snapshot_id in ceiling]
        row = context.task.update_session_context(context.session_id, snapshot_ids=ids)
        result = {
            "task_id": context.task.id,
            "session_id": context.session_id,
            "context_revision": row["context_revision"],
            "snapshot_ids": row["snapshot_ids"],
        }
    elif args.cmd == "dataset-add":
        if context.session_id:
            session = next(
                r
                for r in context.task.sessions()
                if r["session_id"] == context.session_id
            )
            if session.get("parent_session_id"):
                raise FoundryError(
                    "child sessions cannot add snapshots beyond their inherited context; return the output to the parent session"
                )
        result = service.add_dataset(
            _uploaded_path(context, args.path),
            name=args.name,
            metadata=_json(args.meta, "metadata"),
        )
        if context.session_id:
            row = context.task.update_session_context(
                context.session_id, snapshot_ids=[*context.snapshot_ids, result["id"]]
            )
            result = {**result, "context_revision": row["context_revision"]}
    elif args.cmd == "dataset-read":
        _bound(context, {"dataset": args.dataset})
        result = service.read_dataset(args.dataset)
    elif args.cmd == "analysis-save":
        spec = _json(args.spec, "analysis spec")
        _bound(context, spec.get("bindings", {}))
        result = service.save_analysis(spec)
    elif args.cmd == "analysis-run":
        analysis = service.get_analysis(args.analysis)
        _bound(context, analysis["bindings"])
        result = service.run_analysis(
            args.analysis,
            session_id=context.session_id,
            context_revision=context.context_revision,
        )
    elif args.cmd == "analysis-draft":
        spec = _json(args.spec, "draft spec")
        parent = service.get_draft(spec["parent_id"]) if spec.get("parent_id") else {}
        for run_id in [
            *parent.get("run_ids", []),
            *spec.get("run_ids", parent.get("run_ids", [])),
        ]:
            _bound(context, service.get_run(run_id)["bindings"])
        for claim in [*parent.get("claims", []), *spec.get("claims", [])]:
            if isinstance(claim, dict) and claim.get("dataset_id"):
                _bound(context, {"source": claim["dataset_id"]})
        result = service.save_draft(spec)
    elif args.cmd == "analysis-export":
        draft = service.get_draft(args.draft)
        for run_id in draft["run_ids"]:
            _bound(context, service.get_run(run_id)["bindings"])
        result = service.export_draft(args.draft, args.format)
    elif args.cmd == "analysis-output":
        run = service.get_run(args.run)
        _bound(context, run["bindings"])
        result = service.output_path(args.run, args.output)
    elif args.cmd == "analysis-method-save":
        analysis = service.get_analysis(args.analysis)
        _bound(context, analysis["bindings"])
        result = service.save_method(args.analysis, args.name)
    elif args.cmd == "analysis-method-apply":
        bindings = _json(args.bindings, "bindings")
        _bound(context, bindings)
        result = service.apply_method(
            args.method,
            bindings,
            question=args.question,
            parameters=json_value(load_json(args.parameters)),
        )
    else:
        spec = _json(args.spec, "script spec")
        _bound(context, spec.get("bindings", {}))
        result = service.run_script(
            spec,
            session_id=context.session_id,
            context_revision=context.context_revision,
        )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return True
