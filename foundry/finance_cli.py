"""Task/session scoped finance business commands."""

from __future__ import annotations

import json
from pathlib import Path

from foundry.analysis_cli import _json, _uploaded_path
from foundry.analysis_data import json_value
from foundry.context import resolve_context
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.finance_files import FinanceFiles
from foundry.source_refresh import SourceRefreshService, SourceScope

OPERATIONS = {
    "finance-context-save": "save_context",
    "finance-map-save": "save_account_map",
    "finance-metric-save": "save_metric_definition",
    "run-metric": "run_metric",
    "explain-variance": "explain_variance",
    "drilldown-fact": "drilldown_fact",
    "save-explanation-draft": "save_explanation_draft",
    "finance-scenario-save": "save_scenario",
    "finance-scenario-run": "run_scenario",
}
FILE_OPERATIONS = {f"workbook-{name}": name for name in ("inspect", "bind", "read", "preview", "apply")}
LIST_COMMANDS = {"list-finance-context", "finance-source-list"}
COMMANDS = {*LIST_COMMANDS, *OPERATIONS, *FILE_OPERATIONS, "finance-source-refresh"}


def add_parsers(sub):
    for command in sorted(LIST_COMMANDS):
        sub.add_parser(command)
    for command in sorted(COMMANDS - LIST_COMMANDS):
        sub.add_parser(command).add_argument("--spec", required=True)


def _refresh_source(context, spec):
    if context.session_id:
        session = next(row for row in context.task.sessions() if row["session_id"] == context.session_id)
        if session.get("parent_session_id"):
            raise FoundryError("child sessions cannot refresh source snapshots beyond their inherited context")
    scope = spec.get("scope")
    if not isinstance(scope, dict):
        raise FoundryError("source refresh requires an explicit scope object")
    try:
        source_scope = SourceScope(**scope)
    except TypeError as exc:
        raise FoundryError("source scope requires source/tenant/ledger/organization/period/currency/cutoff fields") from exc
    if not isinstance(spec.get("path"), str) or not spec["path"].strip():
        raise FoundryError("source refresh requires an uploaded file path")
    result = SourceRefreshService(context.task).refresh_file(
        _uploaded_path(context, spec["path"]), scope=source_scope,
        product=spec.get("product", "file"), version=spec.get("version", "export"),
        name=spec.get("name"), metadata=spec.get("metadata"),
        file_identity_policy=spec.get("file_identity_policy", "snapshot_only"),
    )
    result = {**result, "effective_dataset_id": result.get("dataset_id") or result.get("prior_snapshot_id")}
    if context.session_id:
        # Keep prior snapshots available for reproducible historic runs.
        # New calculations explicitly select the newly published dataset.
        row = context.task.update_session_context(
            context.session_id, snapshot_ids=list(dict.fromkeys([*context.snapshot_ids, result["effective_dataset_id"]])),
        )
        result = {**result, "context_revision": row["context_revision"]}
    return result


def dispatch(args):
    if args.cmd not in COMMANDS:
        return False
    context = resolve_context(Path(args.var), session_id=args.session or None, task_id=args.task or None)
    if context.task is None:
        raise FoundryError("finance analysis requires a task")
    service = FinanceStore(context.task, snapshot_ids=context.snapshot_ids if context.session_id else None,
                           session_id=context.session_id, context_revision=context.context_revision)
    if args.cmd == "list-finance-context":
        result = service.list_finance_context()
    elif args.cmd == "finance-source-list":
        batches = SourceRefreshService(context.task).batches()
        if context.session_id:
            batches = [row for row in batches if (row.get("dataset_id") or row.get("prior_snapshot_id")) in context.snapshot_ids]
        result = {"batches": batches}
    elif args.cmd == "finance-source-refresh":
        result = _refresh_source(context, _json(args.spec, "source refresh spec"))
    elif args.cmd in FILE_OPERATIONS:
        files = FinanceFiles(context.task, snapshot_ids=context.snapshot_ids if context.session_id else None)
        result = getattr(files, FILE_OPERATIONS[args.cmd])(_json(args.spec, "workbook spec"))
    else:
        result = getattr(service, OPERATIONS[args.cmd])(_json(args.spec, "finance spec"))
    print(json.dumps(json_value(result), ensure_ascii=False, allow_nan=False))
    return True
