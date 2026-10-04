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
    "analysis-requirements-save": "analysis_requirements_save",
    "analysis-requirements-list": "analysis_requirements_list",
    "finance-context-save": "save_context",
    "finance-map-save": "save_account_map",
    "finance-metric-save": "save_metric_definition",
    "run-metric": "run_metric",
    "explain-variance": "explain_variance",
    "drilldown-fact": "drilldown_fact",
    "open-source-locator": "open_source_locator",
    "prepare-explanation": "prepare_explanation",
    "validate-explanation": "validate_explanation",
    "save-explanation-draft": "save_explanation_draft",
    "finance-background-save": "finance_background_save",
    "finance-background-list": "finance_background_list",
    "finance-adjustment-save": "finance_adjustment_save",
    "finance-adjustment-list": "finance_adjustment_list",
    "finance-adjustment-confirm": "finance_adjustment_confirm",
    "report-template-list": "report_template_list",
    "report-template-publish": "report_template_publish",
    "report-template-apply": "report_template_apply",
    "chart-deliverable-save": "chart_deliverable_save",
    "chart-deliverable-open": "chart_deliverable_open",
    "chart-deliverable-list": "chart_deliverable_list",
    "analysis-circle-select": "analysis_circle_select",
    "structure-proposal-list": "structure_proposal_list",
    "structure-proposal-confirm": "structure_proposal_confirm",
    "structure-confirmation-list": "structure_confirmation_list",
    "structure-acknowledge": "structure_acknowledge",
    "structure-reject": "structure_reject",
    "structure-withdraw": "structure_withdraw",
    "structure-template-list": "structure_template_list",
    "structure-template-disable": "structure_template_disable",
    "finance-scenario-save": "save_scenario",
    "finance-scenario-run": "run_scenario",
    "finance-controls-propose": "finance_controls_propose",
    "finance-controls-sources": "finance_controls_sources",
    "finance-controls-preview": "finance_controls_preview",
    "finance-controls-save": "finance_controls_save",
    "finance-controls-confirm": "finance_controls_confirm",
    "finance-controls-retire": "finance_controls_retire",
    "finance-controls-run": "finance_controls_run",
    "finance-controls-list": "finance_controls_list",
    "finance-control-settings-save": "finance_control_settings_save",
    "finance-control-disposition-save": "finance_control_disposition_save",
    "finance-control-disposition-review": "finance_control_disposition_review",
    "finance-control-finding-save": "finance_control_finding_save",
    "finance-control-confirmation-sheet": "finance_control_confirmation_sheet",
}
FILE_OPERATIONS = {f"workbook-{name}": name for name in ("inspect", "bind", "read", "preview", "apply")}
FILE_OPERATIONS["workbook-range-preview"] = "range_preview"
FILE_OPERATIONS["workbook-health"] = "health"
OPERATIONS["finance-completion-recover"] = "recover_completion_draft"
LIST_COMMANDS = {
    "list-finance-context",
    "finance-source-list",
    "finance-completion-recoveries",
    "finance-readiness",
    "finance-close-status",
}
COMPLETION_COMMANDS = {"finance-completion-begin", "finance-completion-status", "finance-completion-stop"}
COMMANDS = {*LIST_COMMANDS, *OPERATIONS, *FILE_OPERATIONS, *COMPLETION_COMMANDS, "finance-source-refresh", "source-locator-preview-file"}


def add_parsers(sub):
    for command in sorted(LIST_COMMANDS):
        sub.add_parser(command)
    for command in sorted(COMMANDS - LIST_COMMANDS):
        parser = sub.add_parser(command)
        if command == "save-explanation-draft":
            from foundry.analysis_cli import _spec_arg

            _spec_arg(parser)
        else:
            parser.add_argument("--spec", required=True)
        if command == "save-explanation-draft":
            # Runtime-injected CLI coordinates, never model spec fields.
            parser.add_argument("--completion-operation")
            parser.add_argument("--completion-call-id")


def _refresh_source(context, spec, actor=None):
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
    if result.get("dataset_id"):
        service = FinanceStore(
            context.task,
            session_id=context.session_id,
            actor=actor,
        )
        proposal = service.structure_propose(result["dataset_id"])
        if proposal is not None:
            result = {
                **result,
                "structure_proposal": {
                    "id": proposal["id"],
                    "revision": proposal["revision"],
                    "structure_state": service.dataset_structure_state(
                        result["dataset_id"]
                    ),
                },
            }
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
                           session_id=context.session_id, context_revision=context.context_revision,
                           actor=getattr(args, "actor", "") or None)
    if args.cmd == "finance-completion-recoveries":
        if context.session_id:
            raise FoundryError("completion recovery requires the task editor")
        from foundry.finance_completion_operations import list_completion_recoveries
        result = list_completion_recoveries(context.task)
    elif args.cmd in COMPLETION_COMMANDS:
        if not context.session_id:
            raise FoundryError("completion operations require a registered runtime session")
        from foundry.finance_completion_operations import CompletionOperationStore
        operations = CompletionOperationStore(context.task, context.session_id, context.snapshot_ids)
        spec = _json(args.spec, "completion runtime spec")
        if args.cmd == "finance-completion-begin":
            result = operations.begin(spec.get("request_key"), policy=spec.get("policy"))
        elif args.cmd == "finance-completion-status":
            result = operations.get(spec.get("operation_id"))
        else:
            result = operations.stop(spec.get("operation_id"), spec.get("reason"))
    elif args.cmd == "save-explanation-draft" and getattr(args, "completion_operation", None):
        if not context.session_id or not args.completion_call_id:
            raise FoundryError("runtime completion save requires session and call id")
        result = service.save_completion_draft(
            args.completion_operation, args.completion_call_id,
            _json_spec(args, "finance spec"),
        )
    elif args.cmd == "save-explanation-draft" and getattr(args, "completion_call_id", None):
        raise FoundryError("completion call id requires an operation")
    elif args.cmd == "list-finance-context":
        result = service.list_finance_context()
    elif args.cmd == "finance-readiness":
        result = service.finance_readiness({})
    elif args.cmd == "finance-close-status":
        result = service.finance_close_status({})
    elif args.cmd == "finance-source-list":
        batches = SourceRefreshService(context.task).batches()
        if context.session_id:
            batches = [row for row in batches if (row.get("dataset_id") or row.get("prior_snapshot_id")) in context.snapshot_ids]
        result = {"batches": batches}
    elif args.cmd == "finance-source-refresh":
        result = _refresh_source(
            context, _json(args.spec, "source refresh spec"), getattr(args, "actor", "") or None
        )
    elif args.cmd == "source-locator-preview-file":
        from foundry.finance_locators import stage_source_locator_preview
        print(stage_source_locator_preview(service, _json(args.spec, "finance spec")))
        return True
    elif args.cmd in FILE_OPERATIONS:
        files = FinanceFiles(context.task, snapshot_ids=context.snapshot_ids if context.session_id else None)
        result = getattr(files, FILE_OPERATIONS[args.cmd])(_json(args.spec, "workbook spec"))
    else:
        result = getattr(service, OPERATIONS[args.cmd])(
            _json_spec(args, "finance spec") if args.cmd == "save-explanation-draft" else _json(args.spec, "finance spec")
        )
    print(json.dumps(json_value(result), ensure_ascii=False, allow_nan=False))
    return True


def _json_spec(args, label):
    from foundry.analysis_cli import _json_spec as read_json_spec

    return read_json_spec(args, label)
