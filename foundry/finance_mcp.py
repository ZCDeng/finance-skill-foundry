"""Minimal stdio MCP adapter for task-scoped finance analysis."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import secrets
import sys
import uuid
from pathlib import Path
from typing import Any, TextIO

from foundry.analysis import AnalysisStore, _assert_id, _safe_text
from foundry.analysis_data import json_value, load_json
from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic
from foundry.task import TaskStore, session_owner

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "finance-skill-foundry"
SERVER_VERSION = "0.1.0"
MAX_MESSAGE_BYTES = 1024 * 1024
GRANT_ENV = {
    "var_root": "FOUNDRY_MCP_VAR_ROOT",
    "grant_id": "FOUNDRY_MCP_GRANT_ID",
    "token": "FOUNDRY_MCP_TOKEN",
}
COMMANDS = {"finance-mcp-serve", "finance-mcp-grant", "finance-mcp-revoke"}


class McpRefused(FoundryError):
    pass


def create_stdio_grant(
    var_root: Path,
    *,
    task_id: str,
    session_id: str,
    snapshot_ids: list[str] | None = None,
    context_ids: list[str] | None = None,
    grant_root: Path | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Create a revocable task/session grant for a local stdio MCP server.

    The returned token is shown once to the caller for subprocess environment
    injection. Only its hash is stored on disk.
    """

    store = TaskStore(Path(var_root))
    task = store.get(task_id)
    owner = session_owner(store, session_id)
    if owner is None or owner.id != task.id:
        raise FoundryError("session is not registered on this task")
    session = next(row for row in task.sessions() if row["session_id"] == session_id)
    ceiling = list(snapshot_ids) if snapshot_ids is not None else list(session.get("snapshot_ids", []))
    if not ceiling:
        raise FoundryError("grant requires at least one snapshot id")
    session_ceiling = set(session.get("snapshot_ids", []))
    if not set(ceiling).issubset(session_ceiling):
        raise FoundryError("grant snapshots exceed the session context")
    for snapshot_id in ceiling:
        _assert_id(snapshot_id)
        AnalysisStore(task).read_dataset(snapshot_id)
    for context_id in context_ids or []:
        _assert_id(context_id)
        _finance_store(task, snapshot_ids=ceiling, session_id=session_id, context_revision=session.get("context_revision"))._read("contexts", context_id)

    plain = token or secrets.token_urlsafe(32)
    grant_id = uuid.uuid4().hex
    root = _grant_root(Path(var_root), grant_root)
    record = {
        "schema_version": 1,
        "grant_id": grant_id,
        "task_id": task.id,
        "session_id": session_id,
        "context_revision": session.get("context_revision", 1),
        "snapshot_ids": ceiling,
        "context_ids": list(context_ids or []),
        "token_hash": _token_hash(plain),
        "revoked": False,
    }
    path = _grant_path(root, grant_id)
    write_json_atomic(path, record)
    try:
        path.chmod(0o600)
        root.chmod(0o700)
    except OSError:
        pass
    return {
        "grant_id": grant_id,
        "token": plain,
        "env": {
            GRANT_ENV["var_root"]: str(Path(var_root)),
            GRANT_ENV["grant_id"]: grant_id,
            GRANT_ENV["token"]: plain,
        },
        "command": [sys.executable, "-m", "foundry.finance_mcp"],
    }


def write_client_config(
    grant: dict[str, Any],
    *,
    config_path: Path | None = None,
    server_name: str = SERVER_NAME,
    frozen: bool | None = None,
) -> dict[str, Any]:
    """Write a protected MCP client config containing the one-time token."""

    env = grant.get("env")
    if not isinstance(env, dict):
        raise FoundryError("grant result is missing environment")
    if config_path is None:
        var_root = Path(str(env[GRANT_ENV["var_root"]]))
        config_path = _grant_root(var_root, None) / f"{_assert_id(grant['grant_id'])}.mcp.json"
    config_path = Path(config_path)
    command = client_command(frozen=frozen)
    payload = {
        "mcpServers": {
            _safe_text(server_name, "server name", required=True, maximum=80): {
                "type": "stdio",
                "command": command[0],
                "args": command[1:],
                "env": env,
            }
        }
    }
    _write_new_json_file(config_path, payload)
    return {"config_path": str(config_path), "grant_id": grant["grant_id"]}


def client_command(*, frozen: bool | None = None) -> list[str]:
    use_frozen = frozen if frozen is not None else getattr(sys, "frozen", False)
    if use_frozen:
        return [sys.executable, "finance-mcp-serve"]
    return [sys.executable, "-m", "foundry.finance_mcp"]


def _finance_store(*args, **kwargs):
    from foundry.finance_service import FinanceStore

    return FinanceStore(*args, **kwargs)


def _write_new_json_file(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FoundryError(f"client config already exists: {path}")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink():
        raise FoundryError(f"client config parent must not be a symlink: {parent}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        path.chmod(0o600)


def revoke_stdio_grant(var_root: Path, grant_id: str, *, grant_root: Path | None = None) -> dict[str, Any]:
    root = _grant_root(Path(var_root), grant_root)
    path = _grant_path(root, grant_id)
    record = _read_grant(path)
    record["revoked"] = True
    write_json_atomic(path, record)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return {"grant_id": grant_id, "revoked": True}


def add_parsers(sub) -> None:
    sub.add_parser("finance-mcp-serve")
    grant = sub.add_parser("finance-mcp-grant")
    grant.add_argument("--spec", required=True)
    revoke = sub.add_parser("finance-mcp-revoke")
    revoke.add_argument("--grant-id", required=True)


def dispatch(args) -> bool:
    if args.cmd not in COMMANDS:
        return False
    if args.cmd in {"finance-mcp-grant", "finance-mcp-revoke"} and str(getattr(args, "session", "") or "").strip():
        raise FoundryError("finance MCP grant commands must be run by a local operator without --session")
    if args.cmd == "finance-mcp-serve":
        token = os.environ.get(GRANT_ENV["token"])
        grant_id = os.environ.get(GRANT_ENV["grant_id"])
        var_root = os.environ.get(GRANT_ENV["var_root"]) or getattr(args, "var", None)
        if not token or not grant_id or not var_root:
            raise FoundryError("missing Finance MCP grant environment")
        serve(FinanceMcpServer(var_root=Path(var_root), grant_id=grant_id, token=token))
        return True
    if args.cmd == "finance-mcp-grant":
        spec = _grant_spec(args.spec)
        if spec.get("session_driven"):
            raise FoundryError("finance MCP grants must be issued by a local operator command")
        grant = create_stdio_grant(
            Path(args.var),
            task_id=spec["task_id"],
            session_id=spec["session_id"],
            snapshot_ids=spec.get("snapshot_ids"),
            context_ids=spec.get("context_ids"),
        )
        result = write_client_config(
            grant,
            config_path=Path(spec["config_path"]) if spec.get("config_path") else None,
            server_name=spec.get("server_name", SERVER_NAME),
            frozen=spec.get("frozen"),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return True
    revoke_stdio_grant(Path(args.var), args.grant_id)
    print(json.dumps({"grant_id": args.grant_id, "revoked": True}, ensure_ascii=False, sort_keys=True))
    return True


class FinanceMcpServer:
    def __init__(self, *, var_root: Path, grant_id: str, token: str, grant_root: Path | None = None) -> None:
        self.var_root = Path(var_root)
        self.grant_id = grant_id
        self.token = token
        self.grant_root = grant_root
        self.initialize_completed = False
        self.initialized = False
        self.negotiated_version = PROTOCOL_VERSION

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            raise JsonRpcError(-32600, "Invalid Request")
        params = _object_params(message)
        if "id" not in message:
            if message["method"] == "notifications/initialized" and self.initialize_completed:
                self.initialized = True
            return None
        method = message["method"]
        if method == "initialize":
            return self._initialize(message["id"], params)
        if method == "ping":
            return _ok(message["id"], {})
        if not self.initialized:
            raise JsonRpcError(-32002, "server is not initialized")
        if method == "tools/list":
            self._authorized()
            return _ok(message["id"], {"tools": _tools()})
        if method == "tools/call":
            return _ok(message["id"], self._call(params))
        raise JsonRpcError(-32601, "Method not found")

    def _initialize(self, request_id: str | int, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        self.negotiated_version = requested if requested == PROTOCOL_VERSION else PROTOCOL_VERSION
        self.initialize_completed = True
        return _ok(
            request_id,
            {
                "protocolVersion": self.negotiated_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "title": "Finance Skill Foundry",
                    "version": SERVER_VERSION,
                },
                "instructions": "Task-scoped finance analysis tools. Grants are checked on every request.",
            },
        )

    def _authorized(self) -> tuple[dict[str, Any], Any, dict[str, Any]]:
        record = _read_grant(_grant_path(_grant_root(self.var_root, self.grant_root), self.grant_id))
        if record.get("revoked"):
            raise McpRefused("grant revoked")
        if not hmac.compare_digest(str(record.get("token_hash") or ""), _token_hash(self.token)):
            raise McpRefused("grant token invalid")
        task_id = _assert_id(record.get("task_id"))
        store = TaskStore(self.var_root)
        task = store.get(task_id)
        session_id = str(record.get("session_id") or "")
        owner = session_owner(store, session_id)
        if owner is None or owner.id != task.id:
            raise McpRefused("session is not registered on this task")
        session = next(row for row in task.sessions() if row["session_id"] == session_id)
        if session.get("context_revision", 1) != record.get("context_revision", 1):
            raise McpRefused("grant context revision is stale")
        snapshots = list(record.get("snapshot_ids") or [])
        if not snapshots or not set(snapshots).issubset(set(session.get("snapshot_ids", []))):
            raise McpRefused("grant snapshots exceed the session context")
        for snapshot_id in snapshots:
            _assert_id(snapshot_id)
        return record, task, session

    def _service(self) -> tuple[dict[str, Any], Any]:
        grant, task, session = self._authorized()
        return grant, _finance_store(
            task,
            snapshot_ids=list(grant["snapshot_ids"]),
            session_id=session["session_id"],
            context_revision=session.get("context_revision", 1),
        )

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise JsonRpcError(-32602, "invalid tool call")
        name = params["name"]
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict) or isinstance(arguments, bool):
            raise JsonRpcError(-32602, "tool arguments must be an object")
        grant, service = self._service()
        if name not in TOOL_METHODS:
            raise JsonRpcError(-32602, "unknown tool")
        try:
            if name == "list_finance_context":
                result = self._filter_context_list(grant, service.list_finance_context())
            else:
                self._authorize_context(grant, service, name, arguments)
                result = getattr(service, TOOL_METHODS[name])(arguments)
        except McpRefused:
            raise
        except FoundryError as exc:
            return _tool_error(str(exc), getattr(exc, "details", None))
        except Exception as exc:
            raise JsonRpcError(-32000, "finance tool failed") from exc
        payload = json_value(result)
        return _tool_result(payload, is_error=False)

    def _filter_context_list(self, grant: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        allowed = set(grant.get("context_ids") or [])
        if not allowed:
            return result
        contexts = [row for row in result.get("contexts", []) if row.get("id") in allowed]
        account_map_ids = {row.get("account_map_id") for row in contexts if row.get("account_map_id")}
        return {
            **result,
            "contexts": contexts,
            "account_maps": [row for row in result.get("account_maps", []) if row.get("id") in account_map_ids],
            "scenarios": [row for row in result.get("scenarios", []) if row.get("context_id") in allowed],
            "metric_definitions": [row for row in result.get("metric_definitions", []) if row.get("context_id") in allowed],
        }

    def _authorize_context(self, grant: dict[str, Any], service: Any, tool: str, spec: dict[str, Any]) -> None:
        allowed = set(grant.get("context_ids") or [])
        if not allowed:
            return
        context_ids: set[str] = set()
        analysis = service.analysis
        if spec.get("context_id"):
            context_ids.add(_assert_id(spec["context_id"]))
        if spec.get("definition_id"):
            context_ids.add(service._read("metric_definitions", spec["definition_id"])["context_id"])
        if spec.get("scenario_id"):
            context_ids.add(service._read("scenarios", spec["scenario_id"])["context_id"])
        if spec.get("parent_id") and tool == "analysis_requirements_save":
            parent = analysis._get("requirements", spec["parent_id"])
            if parent.get("context_id"):
                context_ids.add(parent["context_id"])
            else:
                raise McpRefused("requirements parent has no grant-verifiable context")
        if spec.get("parent_id") and tool == "save_scenario":
            context_ids.add(service._read("scenarios", spec["parent_id"])["context_id"])
        for run_id in [spec.get("run_id"), *spec.get("run_ids", [])]:
            if run_id:
                context_ids.add(_run_finance_context(analysis, run_id))
        if spec.get("draft_id") and tool == "validate_explanation":
            draft = _draft(analysis, spec["draft_id"])
            for run_id in draft.get("run_ids", []):
                context_ids.add(_run_finance_context(analysis, run_id))
        if spec.get("parent_id") and tool == "save_explanation_draft":
            draft = _draft(analysis, spec["parent_id"])
            for run_id in draft.get("run_ids", []):
                context_ids.add(_run_finance_context(analysis, run_id))
        for claim in spec.get("claims", []):
            if isinstance(claim, dict) and claim.get("run_id"):
                context_ids.add(_run_finance_context(analysis, claim["run_id"]))
            if isinstance(claim, dict) and claim.get("dataset_id"):
                dataset_id = _assert_id(claim["dataset_id"])
                if dataset_id not in set(grant.get("snapshot_ids") or []):
                    raise McpRefused("finance source is outside this grant")
        if spec.get("dataset_id"):
            dataset_id = _assert_id(spec["dataset_id"])
            if dataset_id not in set(grant.get("snapshot_ids") or []):
                raise McpRefused("finance source is outside this grant")
        if not context_ids and tool in {
            "finance_background_save",
            "finance_background_list",
        }:
            context_ids.update(_context_ids_matching_scope(service, allowed, spec))
        if not context_ids or not context_ids <= allowed:
            raise McpRefused("finance context is outside this grant")


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


TOOL_METHODS = {
    "analysis_requirements_save": "analysis_requirements_save",
    "analysis_requirements_list": "analysis_requirements_list",
    "list_finance_context": "list_finance_context",
    "run_metric": "run_metric",
    "explain_variance": "explain_variance",
    "save_scenario": "save_scenario",
    "run_scenario": "run_scenario",
    "drilldown_fact": "drilldown_fact",
    "prepare_explanation": "prepare_explanation",
    "validate_explanation": "validate_explanation",
    "save_explanation_draft": "save_explanation_draft",
    "finance_background_save": "finance_background_save",
    "finance_background_list": "finance_background_list",
}


def _tools() -> list[dict[str, Any]]:
    text = {"type": "string"}
    context_id = {
        "type": "string",
        "description": "Finance context id returned by list_finance_context.",
        "pattern": "^[0-9a-f]{32}$",
    }
    run_id = {
        "type": "string",
        "description": "Finance run id returned by run_metric, explain_variance, or run_scenario.",
        "pattern": "^[0-9a-f]{32}$",
    }
    metric_schema = {
        "type": "object",
        "required": ["kind"],
        "properties": {
            "kind": {"type": "string", "enum": ["management_pnl", "ratio", "account_total", "control_totals"]},
            "dimensions": {"type": "array", "items": text},
            "scenario_bindings": {"type": "object"},
            "filters": {"type": "object"},
            "numerator_accounts": {"type": "array", "items": text},
            "denominator_accounts": {"type": "array", "items": text},
            "accounts": {"type": "array", "items": text},
            "account_signs": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Explicit sign multipliers by management account; ratio tools return exact and display values separately.",
            },
            "aggregate_dimensions": {"type": "boolean"},
        },
        "additionalProperties": True,
    }
    materiality_schema = {
        "type": "object",
        "properties": {
            "absolute": text,

        },
        "additionalProperties": True,
    }
    status_filter_schema = {
        "type": "object",
        "description": "Receivables status filter declared by the source adapter or manager. Canonical status meanings are supplied by mapping; the tool does not hardcode enterprise status semantics.",
        "properties": {
            "field": text,
            "include": {"type": "array", "items": text},
            "exclude": {"type": "array", "items": text},
            "mapping": {
                "type": "object",
                "additionalProperties": {"type": "array", "items": text},
                "description": "Canonical status to source values, for example disputed -> source labels. An unmapped status is reported as unknown.",
            },
        },
        "additionalProperties": True,
    }
    basis_schema = {
        "type": "string",
        "enum": [
            "source_fact",
            "external_reference",
            "user_assumption",
            "professional_judgment",
        ],
    }
    scope_schema = {
        "type": "object",
        "properties": {
            "ledger": text,
            "organization": text,
            "period": text,
            "currency": text,
            "unit": text,
        },
        "additionalProperties": True,
    }
    scenario_inputs_schema = {
        "type": "object",
        "properties": {
            "invoices_alias": text,
            "activity_alias": text,
            "as_of": text,
            "scope": scope_schema,
            "buckets": {"type": "array", "items": {"type": "object"}},
            "status_filter": status_filter_schema,
            "opening_cash": text,
            "start_date": text,
            "actual_cutoff": text,
            "receipts_alias": text,
            "payments_alias": text,
            "scenario": {"type": "object"},
            "drivers": {"type": "array", "items": {"type": "object"}},
            "values": {"type": "object"},
            "manager_assumptions": {"type": "object"},
        },
        "additionalProperties": True,
    }
    return [
        {
            "name": "analysis_requirements_save",
            "description": "Before calculation, persist versioned user question, scope, required semantic metrics and requested drilldowns. Removing items requires a change reason; it does not complete the original question. Returned support is independently checked against bound snapshots; requires_input asks for data or field mapping, never zero substitution. support.items name the accepted_evidence that can answer each item now and the blocked_evidence with its blockers. scope.unit and currency only constrain amount items, never ratio items; the ledger is proven by the bound snapshot hashes and is not copied onto result rows. Hierarchy levels such as drilldown are refused as dimensions; the refusal's details.suggested_items can be resubmitted unchanged. A level carried over unchanged from the parent version is dropped from the new version and recorded in authoring_warnings. Hierarchy levels written into scope are refused the same way (details.suggested_scope can be resubmitted); scope.granularity only describes the analysis and never filters rows.",
            "inputSchema": {"type": "object", "required": ["context_id", "question", "items"], "properties": {
                "context_id": context_id, "question": text, "scope": scope_schema, "parent_id": text, "change_reason": text,
                "items": {"type": "array", "items": {"type": "object", "required": ["id", "metric"], "properties": {
                    "id": text, "metric": text, "label": text,
                    "dimensions": {"type": "object", "description": "Result-row filter fields the cited row must carry verbatim (metric_key, management_account, product) and the method/dimension/scenario_compare intents. Hierarchy levels such as drilldown are not dimensions: list each drilldown target in organizations or save it as its own item; use requires_drilldown for per-cell source tracing."},
                    "periods": {"type": "array", "items": text, "description": "All periods the requirement must cover; dimensions.period remains scalar."}, "organizations": {"type": "array", "items": text, "description": "Every organization that must be covered, crossed with every requested period. Leave shared scope.organization empty for a multi-organization requirement."},
                    "scenarios": {"type": "array", "items": text, "description": "Every result scenario key that must be covered, as the run rows state it."},
                    "requires_drilldown": {"type": "boolean"},
                    "grain_basis": {"type": "array", "description": "Optional declarations for grains the source does not state. basis=estimate needs method; only those grains accept a factor_recipe_id estimate, which stays estimated and is never answered. If no recipe can reproduce the coefficient, set factor_reproducible=false with a reason: the grain stays pending for the manager and must not be filled with another coefficient. basis=unavailable needs a reason and only counts as missing data after the manager confirms it.", "items": {"type": "object", "required": ["basis"], "properties": {
                        "basis": {"type": "string", "enum": ["estimate", "unavailable"]},
                        "organizations": {"type": "array", "items": text}, "periods": {"type": "array", "items": text}, "scenarios": {"type": "array", "items": text},
                        "method": text, "factor_reproducible": {"type": "boolean"}, "reason": text}}}}},
                },
            }},
        },
        {
            "name": "analysis_requirements_list",
            "description": "Read the versioned requirements for this authorized financial context.",
            "inputSchema": {"type": "object", "required": ["context_id"], "properties": {"context_id": context_id}},
        },
        {
            "name": "list_finance_context",
            "title": "List finance context",
            "description": "List finance snapshots, contexts, account maps, scenarios, metric definitions, and capabilities available to the scoped grant.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "run_metric",
            "title": "Run finance metric",
            "description": "Run a saved or inline finance metric within the granted task, session, snapshots, and finance context scope.",
            "inputSchema": {
                "type": "object",
                "required": ["context_id", "metric"],
                "properties": {
                    "context_id": context_id,
                    "question": text,
                    "metric": metric_schema,
                    "definition_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "parent_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "assumptions": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "explain_variance",
            "title": "Explain finance variance",
            "description": "Compute a variance bridge within the granted task, session, snapshots, and finance context scope.",
            "inputSchema": {
                "type": "object",
                "required": ["context_id"],
                "properties": {
                    "context_id": context_id,
                    "question": text,
                    "kind": {"type": "string", "enum": ["profit_bridge", "price_quantity"]},
                    "actual_scenario": text,
                    "baseline_scenario": text,
                    "dimensions": {"type": "array", "items": text},
                    "method": {"type": "string", "enum": ["quantity_then_price", "base_weights_with_interaction"]},
                    "actual_filters": {"type": "object"},
                    "baseline_filters": {"type": "object"},
                    "negative_budget_policy": {"type": "string", "enum": ["absolute_baseline", "signed_baseline"]},
                    "missing_groups_as_zero": {"type": "boolean"},
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "prepare_explanation",
            "title": "Prepare finance explanation facts",
            "description": "Prepare stable fact ids, exact values, display values, scopes, semantics, diagnostics, evidence_groups, automatic supporting tables, and writing_guidance from granted successful finance runs. Call this after successful runs that answer the registered requirements; draft with short conclusions, bullet/table drivers, independent formulas, and chapter-end footnotes.",
            "inputSchema": {
                "type": "object",
                "required": ["run_ids"],
                "properties": {
                    "run_ids": {"type": "array", "minItems": 1, "items": run_id},
                    "materiality": materiality_schema,
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "validate_explanation",
            "title": "Validate finance explanation draft",
            "description": "Check the current draft body against granted fact ids, run cells, exact values, display rounding, units, directions, registered requirements, provenance and completeness. evidence_recipes are re-evaluated against the archived snapshots by the server; a supplied evidence_report is ignored. It also returns independent readability suggestions for dense paragraphs or inline formula stacking. It does not approve the draft.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "body": text,
                    "run_ids": {"type": "array", "items": run_id},
                    "fact_ids": {"type": "array", "items": text},
                    "claims": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "save_scenario",
            "title": "Save finance scenario",
            "description": "Save receivables aging, 13-week cash, or driver-model scenarios without payment or posting capability. Aging inputs support invoices_alias, activity_alias, as_of, buckets and status_filter {field, include, exclude, mapping}. Mapping follows source/manager status semantics; rows, detail_rows and excluded_detail_rows retain stable keys, as_of, balances and source evidence. Current status does not prove historical status.",
            "inputSchema": {
                "type": "object",
                "required": ["label"],
                "properties": {
                    "context_id": context_id,
                    "kind": {"type": "string", "enum": ["receivables_aging", "cash_13_weeks", "driver_model"]},
                    "inputs": scenario_inputs_schema,
                    "label": text,
                    "parent_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "changes": {"type": "object"},
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "run_scenario",
            "title": "Run finance scenario",
            "description": "Run a saved finance scenario and generate a task-local finance run with source evidence. Aging outputs expose rows, detail_rows and excluded_detail_rows; use drilldown_fact with section to inspect the relevant row set.",
            "inputSchema": {
                "type": "object",
                "required": ["scenario_id"],
                "properties": {
                    "scenario_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "question": text,
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "drilldown_fact",
            "title": "Drill down finance fact",
            "description": "Return source rows behind a finance run result without exposing arbitrary filesystem paths. section can target rows, detail_rows, or excluded_detail_rows.",
            "inputSchema": {
                "type": "object",
                "required": ["run_id", "row"],
                "properties": {
                    "run_id": run_id,
                    "section": {"type": "string", "enum": ["rows", "detail_rows", "excluded_detail_rows"]},
                    "row": {"type": "integer", "minimum": 0},
                    "column": text,
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "save_explanation_draft",
            "title": "Save finance explanation draft",
            "description": "Save a task-local explanation draft linked to granted finance runs and source claims. Keep {{fact:FACT_ID}} where each number appears; use chapter-end footnotes such as [^1] for source locations, not as numeric placeholders. The returned quality keeps finance checks separate from readability suggestions, and completion preserves editable drafts, repair_allowed, stop_reason such as no_progress, and the bounded two-repair workflow. awaiting_input with verified_input_gap ends this reply with a verified data or mapping gap; original requirements remain incomplete. Every requirement is an amount except ratios, items that only ask for ratio scenarios, counts and physical quantities such as sales_volume; an unrecognised metric name is an amount too, and so is a quantity or area whose name also names an amount (price_volume, revenue_by_area). An amount is answered by: (1) a cited run cell with a passing direct/sum/diff evidence recipe whose sources are the requirement's bound snapshots and whose scale is 1 or an exact unit power; (2) a finance-engine explain_variance closure, only for metric revenue/cost/expense/profit on items without scenarios; (3) for an item whose metric is a ledger account, the finance engine's run_metric account_total row (accounts listing only that account); (4) for account items that list periods/organizations and for control_totals, the run_metric result set: cite every row's amount and check each row with drilldown_fact; (5) for amounts other than revenue/cost/expense/profit and the price-quantity bridge (price_quantity, price_volume and other names that pair a price with a volume), the finance engine's own output of that metric (finance_scenario_run open_amount, closing_cash) or that metric's column in a server-side structured_aggregate run (a declarative plan saved in the app, not a script) on the requirement's single bound snapshot; (6) for metric price_quantity, the finance engine's explain_variance price-quantity bridge (total_variance, quantity_contribution, price_contribution and interaction of one row), or a recipe as in (1). Every value the draft cites for a requirement grain must count on one of these paths: a counted cell never vouches for another value cited for the same grain, so back the extra value or drop it from the body and claims. Script output and script-built closures never count for an amount, run_metric management_pnl rows do not count for revenue/cost/expense/profit, ratio recipes never prove amounts, and factor recipes only reach estimated for grains declared as estimates (a unit scale may sit next to the factor; the coefficient belongs in the ratio recipe). A run counts only when it binds the requirement's snapshots under the requirement's alias names (any alias when the requirement has one binding); rebind_run names them. A finance-engine run counts only when the scope of every bound input in its finance_scope matches the requirement scope (a cash_13_weeks run on receipts and payments: both); rescope_run names that scope. The finance-engine paths (2)-(6) need at least one bound snapshot the finance engine reads rows from (an amount column, revenue/cost/expense columns, or a column the finance context maps to amount). When no bound snapshot does (workbook files, empty tables, tables without an amount column such as a regional budget sheet), they are blocked with bindings_without_engine_rows for the manager, and a context or run on other snapshots never counts (other bindings), so do not save a finance context or rerun for them. A workbook bound beside a table the engine reads blocks nothing. When a run_metric result set on the requirement's bindings still does not answer, engine_run_does_not_cover_requirement names the run, the fields blank on every row and the unmapped accounts; rerunning it unchanged gives the same rows. Compute with exact decimals (not binary floats) and keep full precision in run results (a value that terminates must equal the recipe exactly; a quotient that does not terminate, from a ratio recipe or a factor estimate, must keep at least 28 significant digits, Python Decimal's default, and may use a higher precision or another order of operations), write the requirement metric as metric_key and currency/unit on every row (only a finance-engine run's finance_scope stands in for row fields; a script or SQL run's scope is not read), and never copy the ledger text onto rows. A script cell is traced to its source by the recipe add_source_recipe names; drilldown_fact only verifies finance-engine and structured_aggregate rows. awaiting_manager means only estimates awaiting acceptance, declared gaps, a structure awaiting the manager or bindings the engine reads no rows from remain; stop repairing and report them.",
            "inputSchema": {
                "type": "object",
                "required": ["body"],
                "properties": {
                    "title": text,
                    "body": text,
                    "run_ids": {"type": "array", "items": run_id},
                    "fact_ids": {"type": "array", "items": text},
                    "claims": {"type": "array", "items": {"type": "object"}},
                    "parent_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "finance_background_save",
            "title": "Save finance business background",
            "description": "Version a manager-supplied or sourced business context note for the granted finance context/scope and effective period.",
            "inputSchema": {
                "type": "object",
                "required": ["text", "basis"],
                "properties": {
                    "context_id": context_id,
                    "text": text,
                    "basis": basis_schema,
                    "scope": scope_schema,
                    "effective_from": text,
                    "effective_to": text,
                    "external_reference": {"type": "object", "properties": {key: text for key in ("title", "url", "source_date", "retrieved_at")}},
                    "dataset_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "paragraph": {"type": "integer", "minimum": 1},
                    "parent_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "label": text,
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "finance_background_list",
            "title": "List finance business background",
            "description": "List only granted and period-applicable business context notes for an explanation run or finance context.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context_id": context_id,
                    "scope": scope_schema,
                    "as_of": text,
                },
                "additionalProperties": True,
            },
        },
    ]


def _run_finance_context(analysis: Any, run_id: str) -> str:
    try:
        run = analysis.get_run(run_id)
    except FoundryError as exc:
        raise McpRefused("finance run is outside this grant") from exc
    context_id = run.get("finance_context_id")
    if not context_id:
        raise McpRefused("finance run is outside this grant")
    return context_id


def _draft(analysis: Any, draft_id: str) -> dict[str, Any]:
    try:
        return analysis.get_draft(draft_id)
    except FoundryError as exc:
        raise McpRefused("finance draft is outside this grant") from exc


def _context_ids_matching_scope(
    service: Any, allowed: set[str], spec: dict[str, Any]
) -> set[str]:
    scope = spec.get("scope")
    if not isinstance(scope, dict) or not scope:
        return set()
    matches = set()
    for context_id in allowed:
        try:
            context = service._read("contexts", context_id)
        except FoundryError:
            continue
        scopes = context.get("scopes", {})
        if not isinstance(scopes, dict):
            continue
        for candidate in scopes.values():
            if _scope_contains(candidate, scope):
                matches.add(context_id)
                break
    return matches


def _scope_contains(candidate: Any, requested: dict[str, Any]) -> bool:
    if not isinstance(candidate, dict):
        return False
    for key, value in requested.items():
        if value in (None, ""):
            continue
        if candidate.get(key) != value:
            return False
    return True


def serve(server: FinanceMcpServer, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
                response = _err(None, -32600, "message too large")
                stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                stdout.flush()
                continue
            message = json.loads(line)
            if not isinstance(message, dict):
                raise JsonRpcError(-32600, "Invalid Request")
            response = server.handle(message)
        except json.JSONDecodeError:
            response = _err(None, -32700, "Parse error")
        except McpRefused:
            response = _err(_request_id_from_line(line), -32001, "access denied")
        except JsonRpcError as exc:
            response = _err(_request_id_from_line(line), exc.code, exc.message)
        except Exception:
            response = _err(_request_id_from_line(line), -32000, "internal server error")
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Finance Skill Foundry MCP stdio server.")
    parser.add_argument("--var-root", default=os.environ.get(GRANT_ENV["var_root"]))
    parser.add_argument("--grant-id", default=os.environ.get(GRANT_ENV["grant_id"]))
    args = parser.parse_args(argv)
    token = os.environ.get(GRANT_ENV["token"])
    if not args.var_root or not args.grant_id or not token:
        sys.stderr.write("missing Finance MCP grant environment\n")
        return 2
    serve(FinanceMcpServer(var_root=Path(args.var_root), grant_id=args.grant_id, token=token))
    return 0


def _grant_root(var_root: Path, grant_root: Path | None) -> Path:
    root = Path(grant_root) if grant_root is not None else var_root / "mcp-grants"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _grant_path(root: Path, grant_id: str) -> Path:
    return root / f"{_assert_id(grant_id)}.json"


def _read_grant(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise McpRefused("grant unavailable") from exc
    if record.get("grant_id") != path.stem:
        raise McpRefused("grant integrity failed")
    return record


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _grant_spec(value: str) -> dict[str, Any]:
    spec = load_json(value)
    if not isinstance(spec, dict):
        raise FoundryError("finance MCP grant spec must be a JSON object")
    for key in ("task_id", "session_id"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            raise FoundryError(f"finance MCP grant spec requires {key}")
    _assert_id(spec["task_id"])
    if "snapshot_ids" in spec:
        if not isinstance(spec["snapshot_ids"], list) or any(not isinstance(item, str) for item in spec["snapshot_ids"]):
            raise FoundryError("snapshot_ids must be a list of snapshot id strings")
        for item in spec["snapshot_ids"]:
            _assert_id(item)
    if "context_ids" in spec:
        if not isinstance(spec["context_ids"], list) or any(not isinstance(item, str) for item in spec["context_ids"]):
            raise FoundryError("context_ids must be a list of finance context id strings")
        for item in spec["context_ids"]:
            _assert_id(item)
    if spec.get("config_path") is not None and not isinstance(spec["config_path"], str):
        raise FoundryError("config_path must be a string")
    if spec.get("server_name") is not None and not isinstance(spec["server_name"], str):
        raise FoundryError("server_name must be a string")
    if spec.get("frozen") is not None and not isinstance(spec["frozen"], bool):
        raise FoundryError("frozen must be a boolean")
    return spec


def _ok(request_id: str | int, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _err(request_id: str | int | None, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _object_params(message: dict[str, Any]) -> dict[str, Any]:
    if "params" not in message:
        return {}
    params = message["params"]
    if not isinstance(params, dict) or isinstance(params, bool):
        raise JsonRpcError(-32602, "params must be an object")
    return params


def _tool_result(payload: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, sort_keys=True)}],
        "structuredContent": payload,
        "isError": is_error,
    }


# Refusals whose structured details only echo the caller's own request (never a server path) and that the
# caller needs in order to self-correct; each also has a path-free message for when the text is blanked.
PUBLIC_REFUSALS = {
    "requirement_dimension_not_row_filter": (
        "requirement dimensions hold hierarchy levels, not result-row filters; resubmit details.suggested_items "
        "unchanged, list each drilldown target in organizations or save it as its own item"
    ),
    "requirement_scope_not_row_filter": (
        "requirement scope holds hierarchy levels, not result-row filters; resubmit details.suggested_scope "
        "unchanged, list each drilldown target in organizations or save it as its own item"
    ),
}


def _tool_error(message: str, details: Any = None) -> dict[str, Any]:
    code = details.get("code") if isinstance(details, dict) else None
    public = details if code in PUBLIC_REFUSALS else None
    if "/" in message or "\\" in message:
        message = PUBLIC_REFUSALS.get(code, "finance request refused")
    return _tool_result({"error": "finance request refused", "message": message,
                         **({"details": public} if public else {})}, is_error=True)


def _request_id_from_line(line: str) -> str | int | None:
    try:
        message = json.loads(line)
    except ValueError:
        return None
    return message.get("id") if isinstance(message, dict) else None


if __name__ == "__main__":
    raise SystemExit(main())
