"""JSON CLI facade for the task-owned analysis service."""

from __future__ import annotations

import json
from pathlib import Path

from foundry.analysis import (ANALYSIS_UNAVAILABLE, DRAFT_UNAVAILABLE, PARENT_UNAVAILABLE, REPORT_EXPORT_FORMATS,
                              AnalysisStore, _inherited_fields)
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
    "report-pptx-read",
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
    p = sub.add_parser("report-pptx-read", help="a PPTX source's slide text and tables, for review; never an export")
    p.add_argument("--source", required=True)
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


def _bound_draft(context, service, draft, cache=None):
    """Report presentation cannot widen a session's source permissions (AnalysisStore.draft_snapshots; ``cache`` as
    there). The manager reads a draft whose own runs and records read."""
    if context.session_id:
        _bound(context, {f"source{index}": dataset_id
                         for index, dataset_id in enumerate(sorted(service.draft_snapshots(draft, cache=cache)))})
        return
    for run_id in draft.get("run_ids", []):
        service.get_run(run_id)
    for claim in draft.get("claims", []):
        if isinstance(claim, dict) and claim.get("run_id"):
            service.get_run(claim["run_id"])
    _bound_evidence(context, service, draft)
    _bound_requirements(context, service, draft)


def _parent_draft(context, service, parent_id):
    """The draft a revision names as its parent. A session is refused one it may not read exactly as an unknown id."""
    if not parent_id:
        return {}
    try:
        parent = service.get_draft(parent_id)
        _bound_draft(context, service, parent)
    except FoundryError:
        if not context.session_id:
            raise
        raise FoundryError(PARENT_UNAVAILABLE) from None
    return parent


def _named_draft(context, service, draft_id):
    """A draft a command names by id. A session is refused one it may not read exactly as an unknown id, as
    FinanceStore._named_draft refuses it."""
    try:
        draft = service.get_draft(draft_id)
        _bound_draft(context, service, draft)
    except FoundryError:
        if not context.session_id:
            raise
        raise FoundryError(DRAFT_UNAVAILABLE) from None
    return draft


def _named_analysis(context, service, analysis_id):
    """A saved analysis a command names by id. A session is refused one bound to a file it may not read exactly as an
    unknown or malformed id, as analysis-state leaves it out; the manager as before."""
    try:
        analysis = service.get_analysis(analysis_id)
        _bound(context, analysis["bindings"])
    except FoundryError:
        if not context.session_id:
            raise
        raise FoundryError(ANALYSIS_UNAVAILABLE) from None
    return analysis


def _bound_requirements(context, service, spec):
    """The requirements version a spec or a saved analysis names. A session is refused one it may not read exactly as
    an unknown or malformed id (AnalysisStore.named_requirements); the manager as before."""
    if not spec.get("requirements_id"):
        return
    if context.session_id:
        service.named_requirements(spec["requirements_id"], _ceiling(context))
        return
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


def _ceiling(context):
    """The snapshots this session may read; None outside a session (the manager's full view)."""
    return set(context.snapshot_ids) if context.session_id else None


def _draft_visible(context, service, draft, cache=None):
    try:
        _bound_draft(context, service, draft, cache)
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
        # The task's versions, runs and refresh batches, read once for every run, draft and receipt the session reads
        # (run_in_view).
        cache: dict = {}
        result = service.state(_ceiling(context), cache=cache)
        if context.session_id:
            from foundry.source_refresh import snapshots_in_view

            allowed = set(context.snapshot_ids)
            # A refreshed snapshot names the prior its batch reads with (SourceRefreshService.batches_in_view).
            result["datasets"] = snapshots_in_view(service, [d for d in result["datasets"] if d["id"] in allowed],
                                                   allowed, cache=cache)
            result["analyses"] = [
                a for a in result["analyses"] if set(a["bindings"].values()) <= allowed
            ]
            result["runs"] = [
                r for r in result["runs"] if set(r["bindings"].values()) <= allowed
            ]
            run_ids = {r["id"] for r in result["runs"]}
            read: dict = {}
            result["drafts"] = [
                d for d in result["drafts"]
                if set(d["run_ids"]) <= run_ids and _draft_visible(context, service, d, read)
            ]
            result["evidence_checks"] = [
                c for c in result["evidence_checks"]
                if set((c.get("bindings") or {}).values()) <= allowed and (c.get("location") or {}).get("run_id") in run_ids
            ]
        listed = {d["id"] for d in result["drafts"]} if context.session_id else None
        # The requirements versions the drafts' checks and their receipts read, each read once for the listing.
        versions: dict = {}
        # A receipt reads the way its draft reads (AnalysisStore.completion_in_view).
        result["completions"] = [
            receipt for receipt in service.completions_in_view(result["completions"], _ceiling(context),
                                                               readable_ids=listed, versions=versions, cache=cache)
            if receipt is not None
        ]
        result["drafts"] = [service.draft_in_view(d, _ceiling(context), readable_ids=listed, versions=versions,
                                                  cache=cache)
                            for d in result["drafts"]]
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
            allowed=_ceiling(context),
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
        from foundry.source_refresh import snapshots_in_view

        _bound(context, {"dataset": args.dataset})
        [result] = snapshots_in_view(service, [service.read_dataset(args.dataset)], _ceiling(context))
    elif args.cmd == "analysis-save":
        spec = _json(args.spec, "analysis spec")
        _bound(context, spec.get("bindings", {}))
        _bound_requirements(context, service, spec)
        if context.session_id and spec.get("parent_id"):
            # A parent the session may not read is refused as an unknown one, not saved as the revision's parent.
            _named_analysis(context, service, spec["parent_id"])
        result = service.save_analysis(spec)
    elif args.cmd == "analysis-run":
        analysis = _named_analysis(context, service, args.analysis)
        # A session runs the analysis as analysis-state reads it (analysis_in_view): pinned to the version it reads.
        _bound_requirements(context, service, service.analysis_in_view(analysis, _ceiling(context)))
        result = service.run_analysis(
            args.analysis,
            session_id=context.session_id,
            context_revision=context.context_revision,
            allowed=_ceiling(context),
        )
    elif args.cmd == "analysis-draft":
        spec = _json_spec(args, "draft spec")
        if context.session_id and spec.get("review_status", "unreviewed") != "unreviewed":
            raise FoundryError("professional review must be recorded by the manager, not the runtime session")
        parent = _parent_draft(context, service, spec.get("parent_id"))
        _bound_evidence(context, service, spec)
        _bound_requirements(context, service, spec)
        from foundry.report_visuals import materialize_document

        # A revision that takes its parent's document takes its prose (save_draft sees the document in the spec).
        inherited = _inherited_fields(spec, parent) & {"body"}
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
            if context.session_id and isinstance(claim, dict) and claim.get("run_id"):
                # Whatever its basis, the draft rests on the run a claim names (AnalysisStore.draft_snapshots).
                _bound(context, service.get_run(claim["run_id"])["bindings"])
        # Evidence freshness reads only the files this session may read, as the finance draft path does. The save and
        # the draft it returns are one read (AnalysisStore.save_draft).
        cache = {}
        result = service.draft_in_view(service.save_draft(spec, _allowed=_ceiling(context), _inherited=inherited,
                                                          _cache=cache), _ceiling(context), cache=cache)
    elif args.cmd == "analysis-export":
        _named_draft(context, service, args.draft)
        result = service.export_draft(args.draft, args.format, mode=args.mode, allowed=_ceiling(context))
    elif args.cmd in {"report-draft-read", "report-projection-read"}:
        draft = _named_draft(context, service, args.draft)
        result = (service.projection_for_draft(args.draft, args.mode, allowed=_ceiling(context))
                  if args.cmd == "report-projection-read" else service.draft_in_view(draft, _ceiling(context)))
    elif args.cmd == "report-source-add":
        result = service.add_report_source(_uploaded_path(context, args.path))
    elif args.cmd == "report-source-read":
        result = service.read_report_source(args.source)
    elif args.cmd == "report-xlsx-read":
        result = service.read_report_xlsx(args.source, sheet=args.sheet, range_ref=getattr(args, "range"))
    elif args.cmd == "report-pptx-read":
        result = service.read_report_pptx(args.source)
    elif args.cmd == "report-export-register":
        # The desktop files what it rendered; a conversation exports through analysis-export, which renders on
        # the server, so no conversation decides what the manager's export returns.
        if context.session_id:
            raise FoundryError("report-export-register is the desktop's export receipt and does not take a session")
        _bound_draft(context, service, service.get_draft(args.draft))
        result = service.register_report_export(args.draft, args.format, _uploaded_path(context, args.path),
                                                content_mode=args.mode, projection_hash=args.projection_hash,
                                                allowed=_ceiling(context))
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
        _named_analysis(context, service, args.analysis)
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
            allowed=_ceiling(context),
        )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return True
