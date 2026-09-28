"""JSON CLI facade for the task-owned analysis service."""

from __future__ import annotations

import json
from pathlib import Path

from foundry.analysis import REPORT_EXPORT_FORMATS, AnalysisStore
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
    "report-draft-read",
    "report-projection-read",
    "report-source-add",
    "report-source-read",
    "report-xlsx-read",
    "report-export-register",
    "analysis-deliverables",
    "analysis-export-path",
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
    p.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="file these bytes again even though the task already holds them",
    )
    p = sub.add_parser("dataset-read")
    p.add_argument("--dataset", required=True)
    p = sub.add_parser("analysis-save")
    p.add_argument("--spec", required=True)
    p = sub.add_parser("analysis-run")
    p.add_argument("--analysis", required=True)
    p = sub.add_parser("analysis-draft")
    _spec_arg(p)
    p = sub.add_parser("analysis-export")
    p.add_argument("--draft", required=True)
    p.add_argument("--format", choices=["md", "xlsx"], default="md")
    p.add_argument("--mode", choices=["management", "audit"], default="management")
    p = sub.add_parser("report-draft-read")
    p.add_argument("--draft", required=True)
    p = sub.add_parser("report-projection-read")
    p.add_argument("--draft", required=True)
    p.add_argument("--mode", choices=["management", "audit"], default="management")
    p = sub.add_parser("report-source-add")
    p.add_argument("--path", required=True)
    p = sub.add_parser("report-source-read")
    p.add_argument("--source", required=True)
    p = sub.add_parser("report-xlsx-read")
    p.add_argument("--source", required=True)
    p.add_argument("--sheet")
    p.add_argument("--range")
    p = sub.add_parser("report-export-register")
    p.add_argument("--draft", required=True)
    p.add_argument("--format", choices=["md", "xlsx", "docx", "pdf", "html"], required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--mode", choices=["management", "audit"], default="management")
    p.add_argument("--projection-hash")
    sub.add_parser("analysis-deliverables", help="成果库: newest draft per revision chain and every filed export")
    p = sub.add_parser("analysis-export-path", help="where this task filed one export, by digest and format")
    p.add_argument("--sha", required=True, help="sha256 of a filed export")
    p.add_argument("--format", choices=sorted(REPORT_EXPORT_FORMATS), required=True)
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


def _spec_arg(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--spec")
    group.add_argument("--spec-file")


def _json_spec(args, label):
    if getattr(args, "spec_file", None):
        path = Path(args.spec_file).expanduser()
        if not path.is_file() or path.is_symlink():
            raise FoundryError(f"{label} spec file must be a regular file")
        if path.stat().st_size > MAX_SPEC_FILE_BYTES:
            raise FoundryError(f"{label} spec file exceeds 32 MiB")
        return _json(path.read_text(encoding="utf-8"), label)
    return _json(args.spec, label)


MAX_SPEC_FILE_BYTES = 32 * 1024 * 1024


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


def _bound_draft(context, service, draft):
    """Report presentation cannot widen a session's source permissions."""
    for run_id in draft.get("run_ids", []):
        _bound(context, service.get_run(run_id)["bindings"])
    for claim in draft.get("claims", []):
        if isinstance(claim, dict):
            if claim.get("dataset_id"):
                _bound(context, {"source": claim["dataset_id"]})
            if claim.get("run_id"):
                _bound(context, service.get_run(claim["run_id"])["bindings"])
    _bound_evidence(context, service, draft)
    _bound_requirements(context, service, draft)


def _bound_requirements(context, service, spec):
    if spec.get("requirements_id"):
        _bound(context, service._get("requirements", spec["requirements_id"]).get("bindings", {}))


def _bound_evidence(context, service, spec):
    from foundry.financial_evidence import consistency_dataset_ids, recipe_dataset_ids

    recipes = spec.get("evidence_recipes", [])
    for dataset_id in recipe_dataset_ids(recipes) | consistency_dataset_ids(spec.get("consistency_sources", [])):
        _bound(context, {"source": dataset_id})
    for recipe in recipes:
        claim = recipe.get("claim", {})
        if claim.get("run_id"):
            _bound(context, service.get_run(claim["run_id"])["bindings"])


def _draft_visible(context, service, draft):
    try:
        _bound_draft(context, service, draft)
    except FoundryError:
        return False
    return True


def _propose_structure(context, dataset, actor):
    """Read the new file's shape straight away, so the card is there to answer.

    Structure records live in the finance store while datasets live in the
    analysis store, so the reading is triggered here, where both are in hand,
    rather than from inside the dataset write itself.
    """
    from foundry.finance_service import FinanceStore

    service = FinanceStore(
        context.task,
        snapshot_ids=None,
        session_id=context.session_id,
        actor=actor,
    )
    record = service.structure_propose(dataset["id"], source=service.actor)
    if record is None:
        return None
    return {
        "id": record["id"],
        "revision": record["revision"],
        "structure_state": service.dataset_structure_state(dataset["id"]),
        "template_matches": record.get("template_matches") or [],
    }


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
                if set(d["run_ids"]) <= run_ids and _draft_visible(context, service, d)
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
            allow_duplicate=getattr(args, "allow_duplicate", False),
        )
        if result.get("duplicate_of"):
            # Same bytes already filed; nothing was written, so nothing widens.
            pass
        else:
            if context.session_id:
                row = context.task.update_session_context(
                    context.session_id, snapshot_ids=[*context.snapshot_ids, result["id"]]
                )
                result = {**result, "context_revision": row["context_revision"]}
            result = {
                **result,
                "structure_proposal": _propose_structure(
                    context, result, getattr(args, "actor", "") or None
                ),
            }
    elif args.cmd == "dataset-read":
        _bound(context, {"dataset": args.dataset})
        result = service.read_dataset(args.dataset)
    elif args.cmd == "analysis-save":
        spec = _json(args.spec, "analysis spec")
        _bound(context, spec.get("bindings", {}))
        _bound_requirements(context, service, spec)
        result = service.save_analysis(spec)
    elif args.cmd == "analysis-run":
        analysis = service.get_analysis(args.analysis)
        _bound(context, analysis["bindings"])
        _bound_requirements(context, service, analysis)
        result = service.run_analysis(
            args.analysis,
            session_id=context.session_id,
            context_revision=context.context_revision,
        )
    elif args.cmd == "analysis-draft":
        spec = _json_spec(args, "draft spec")
        if context.session_id and spec.get("review_status", "unreviewed") != "unreviewed":
            raise FoundryError("professional review must be recorded by the manager, not the runtime session")
        parent = service.get_draft(spec["parent_id"]) if spec.get("parent_id") else {}
        _bound_draft(context, service, parent)
        _bound_evidence(context, service, spec)
        _bound_requirements(context, service, spec)
        from foundry.report_visuals import materialize_document

        visual_document = spec.get("document")
        if visual_document is None and "body" not in spec:
            visual_document = parent.get("document")
        if visual_document is not None:
            document, visual_runs, _ = materialize_document(
                service, visual_document, authorize=lambda bindings: _bound(context, bindings))
            run_ids = spec.get("run_ids", parent.get("run_ids", []))
            if not isinstance(run_ids, list):
                raise FoundryError("run_ids must be an array")
            spec = {**spec, "document": document, "run_ids": list(dict.fromkeys([*run_ids, *visual_runs]))}
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
        _bound_draft(context, service, draft)
        result = service.export_draft(args.draft, args.format, mode=args.mode)
    elif args.cmd in {"report-draft-read", "report-projection-read"}:
        draft = service.get_draft(args.draft)
        _bound_draft(context, service, draft)
        result = service.projection_for_draft(args.draft, args.mode) if args.cmd == "report-projection-read" else draft
    elif args.cmd == "report-source-add":
        result = service.add_report_source(_uploaded_path(context, args.path))
    elif args.cmd == "report-source-read":
        result = service.read_report_source(args.source)
    elif args.cmd == "report-xlsx-read":
        result = service.read_report_xlsx(args.source, sheet=args.sheet, range_ref=getattr(args, "range"))
    elif args.cmd == "report-export-register":
        _bound_draft(context, service, service.get_draft(args.draft))
        result = service.register_report_export(args.draft, args.format, _uploaded_path(context, args.path),
                                                content_mode=args.mode, projection_hash=args.projection_hash)
    elif args.cmd in {"analysis-deliverables", "analysis-export-path"}:
        from foundry.analysis_deliverables import export_path, list_analysis_deliverables

        # The manager's library across every draft; a conversation reads what its context grants instead.
        if context.session_id:
            raise FoundryError(f"{args.cmd} is the desktop library view and does not take a session")
        result = (
            list_analysis_deliverables(service)
            if args.cmd == "analysis-deliverables"
            else {"path": str(export_path(service, args.sha, args.format))}
        )
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
        _bound_requirements(context, service, spec)
        result = service.run_script(
            spec,
            session_id=context.session_id,
            context_revision=context.context_revision,
        )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return True
