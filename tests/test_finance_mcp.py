from __future__ import annotations

import json
import subprocess
import sys
from argparse import ArgumentParser
from types import SimpleNamespace
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.finance_mcp import add_parsers, client_command, create_stdio_grant, dispatch, revoke_stdio_grant, write_client_config
from foundry.task import TaskStore


def _finance_store(*args, **kwargs):
    from foundry.finance_service import FinanceStore

    return FinanceStore(*args, **kwargs)


def _json(path: Path, rows: list[dict]) -> Path:
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return path


def _seed(tmp_path: Path, *, title: str, session: str, organization: str, profit: str) -> dict:
    store = TaskStore(tmp_path / "var")
    task = store.create(title=title, make_current=False)
    analysis = AnalysisStore(task)
    revenue = str(int(profit) + 90)
    dataset = analysis.add_dataset(
        _json(
            tmp_path / f"{title}.json",
            [
                {
                    "ledger": title,
                    "organization": organization,
                    "period": "2026-08",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                    "management_account": "revenue",
                    "amount": revenue,
                    "source_row": "7",
                    "doc_id": f"{title}-R",
                    "line_id": "1",
                },
                {
                    "ledger": title,
                    "organization": organization,
                    "period": "2026-08",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                    "management_account": "cost",
                    "amount": "70",
                    "source_row": "8",
                    "doc_id": f"{title}-C",
                    "line_id": "2",
                },
                {
                    "ledger": title,
                    "organization": organization,
                    "period": "2026-08",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                    "management_account": "expense",
                    "amount": "20",
                    "source_row": "9",
                    "doc_id": f"{title}-E",
                    "line_id": "3",
                },
            ],
        ),
        name=f"{title} ledger",
    )
    task.record_session(session, role="analysis")
    context = _finance_store(task, snapshot_ids=[dataset["id"]], session_id=session).save_context(
        {
            "name": f"{title} context",
            "bindings": {"actual": dataset["id"]},
            "scopes": {
                "actual": {
                    "ledger": title,
                    "organization": organization,
                    "period": "2026-08",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                }
            },
            "policies": {"actual": {}},
        }
    )
    spec = {
        "context_id": context["id"],
        "metric": {
            "id": "pnl",
            "kind": "management_pnl",
            "dimensions": ["organization", "period"],
            "scenario_bindings": {"actual": "actual"},
        },
    }
    return {"store": store, "task": task, "dataset": dataset, "context": context, "spec": spec, "session": session}


class McpClient:
    def __init__(self, env: dict[str, str]) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "foundry.finance_mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**env, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        )

    def request(self, request_id: int, method: str, params: dict | None = None) -> dict:
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def notify(self, method: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def raw(self, line: str) -> dict:
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def close(self) -> None:
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        self.proc.wait(timeout=5)


def _handshake(client: McpClient) -> None:
    initialized = client.request(
        1,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    )
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert initialized["result"]["capabilities"]["tools"]["listChanged"] is False
    client.notify("notifications/initialized")
    assert client.request(2, "ping")["result"] == {}


def _seed_cash(tmp_path: Path) -> dict:
    store = TaskStore(tmp_path / "var")
    task = store.create(title="cash", make_current=False)
    analysis = AnalysisStore(task)
    bindings = {}
    rows_by_alias = {
        "receipts": [{"id": "R1", "date": "2026-09-25", "amount": "100"}],
        "payments": [{"id": "P1", "date": "2026-09-28", "amount": "60"}],
    }
    for alias, rows in rows_by_alias.items():
        bindings[alias] = analysis.add_dataset(_json(tmp_path / f"{alias}.json", rows), name=alias)["id"]
    task.record_session("cash-session", role="analysis")
    scope = {"ledger": "L1", "organization": "O1", "currency": "CNY", "unit": "万元"}
    service = _finance_store(task, snapshot_ids=list(bindings.values()), session_id="cash-session")
    context = service.save_context({"bindings": bindings, "scopes": {alias: scope for alias in bindings}, "policies": {}})
    spec = {
        "context_id": context["id"],
        "kind": "cash_13_weeks",
        "inputs": {"opening_cash": "50", "start_date": "2026-09-24", "actual_cutoff": "2026-09-23", "scope": scope},
        "label": "base cash",
    }
    return {"store": store, "task": task, "bindings": bindings, "context": context, "spec": spec, "service": service}


@pytest.mark.parametrize(("title", "organization", "profit"), [("alpha", "华东", "30"), ("beta", "华南", "45")])
def test_stdio_mcp_tool_flow_matches_direct_finance_service(tmp_path: Path, title: str, organization: str, profit: str) -> None:
    fixture = _seed(tmp_path, title=title, session=f"{title}-session", organization=organization, profit=profit)
    direct = _finance_store(
        fixture["task"],
        snapshot_ids=[fixture["dataset"]["id"]],
        session_id=fixture["session"],
    ).run_metric(fixture["spec"])
    grant = create_stdio_grant(
        fixture["store"].var_root,
        task_id=fixture["task"].id,
        session_id=fixture["session"],
        snapshot_ids=[fixture["dataset"]["id"]],
        context_ids=[fixture["context"]["id"]],
    )
    client = McpClient(grant["env"])
    try:
        _handshake(client)
        tools = client.request(3, "tools/list")["result"]["tools"]
        by_name = {tool["name"]: tool for tool in tools}
        assert set(by_name) >= {
            "run_metric",
            "drilldown_fact",
            "prepare_explanation",
            "validate_explanation",
            "save_explanation_draft",
            "finance_background_save",
            "finance_background_list",
            "save_scenario",
            "run_scenario",
        }
        assert by_name["run_metric"]["inputSchema"]["required"] == ["context_id", "metric"]
        assert by_name["run_metric"]["inputSchema"]["properties"]["metric"]["required"] == ["kind"]
        ratio = by_name["run_metric"]["inputSchema"]["properties"]["metric"]["properties"]
        assert {"numerator_accounts", "denominator_accounts", "account_signs"} <= set(ratio)
        assert by_name["run_scenario"]["inputSchema"]["required"] == ["scenario_id"]
        assert by_name["prepare_explanation"]["inputSchema"]["required"] == ["run_ids"]
        assert by_name["finance_background_save"]["inputSchema"]["properties"]["basis"]["enum"] == [
            "source_fact",
            "external_reference",
            "user_assumption",
            "professional_judgment",
        ]
        response = client.request(4, "tools/call", {"name": "run_metric", "arguments": fixture["spec"]})
        result = response["result"]["structuredContent"]
    finally:
        client.close()

    direct_row = direct["result"]["rows"][0]
    mcp_row = result["result"]["rows"][0]
    assert mcp_row["profit"] == direct_row["profit"] == profit
    assert mcp_row["unit"] == direct_row["unit"] == "万元"
    assert mcp_row["evidence"]["profit"] == direct_row["evidence"]["profit"]


def test_grant_is_hashed_revocable_and_checked_per_request(tmp_path: Path) -> None:
    fixture = _seed(tmp_path, title="revoked", session="revoked-session", organization="华北", profit="31")
    grant = create_stdio_grant(
        fixture["store"].var_root,
        task_id=fixture["task"].id,
        session_id=fixture["session"],
        snapshot_ids=[fixture["dataset"]["id"]],
        context_ids=[fixture["context"]["id"]],
    )
    stored = json.loads((fixture["store"].var_root / "mcp-grants" / f"{grant['grant_id']}.json").read_text())
    assert stored["token_hash"]
    assert grant["token"] not in json.dumps(stored)

    client = McpClient(grant["env"])
    try:
        _handshake(client)
        assert "tools" in client.request(3, "tools/list")["result"]
        revoke_stdio_grant(fixture["store"].var_root, grant["grant_id"])
        denied = client.request(4, "tools/list")
    finally:
        client.close()
    assert denied["error"] == {"code": -32001, "message": "access denied"}


def test_context_bound_list_filters_same_snapshot_records(tmp_path: Path) -> None:
    fixture = _seed(tmp_path, title="scoped", session="scope-session", organization="华东", profit="30")
    service = _finance_store(
        fixture["task"],
        snapshot_ids=[fixture["dataset"]["id"]],
        session_id=fixture["session"],
    )
    other = service.save_context(
        {
            "name": "same snapshot other context",
            "bindings": {"actual": fixture["dataset"]["id"]},
            "scopes": {
                "actual": {
                    "ledger": "scoped",
                    "organization": "华南",
                    "period": "2026-08",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                }
            },
            "policies": {"actual": {}},
        }
    )
    definition = service.save_metric_definition(
        {"context_id": fixture["context"]["id"], "metric": fixture["spec"]["metric"], "name": "granted metric"}
    )
    hidden_definition = service.save_metric_definition(
        {"context_id": other["id"], "metric": fixture["spec"]["metric"], "name": "hidden metric"}
    )
    visible_scenario = service.save_scenario(
        {
            "context_id": fixture["context"]["id"],
            "kind": "driver_model",
            "inputs": {"drivers": [{"name": "revenue", "formula": "1", "depends_on": []}]},
            "label": "visible",
        }
    )
    hidden_scenario = service.save_scenario(
        {
            "context_id": other["id"],
            "kind": "driver_model",
            "inputs": {"drivers": [{"name": "revenue", "formula": "1", "depends_on": []}]},
            "label": "hidden",
        }
    )
    grant = create_stdio_grant(
        fixture["store"].var_root,
        task_id=fixture["task"].id,
        session_id=fixture["session"],
        snapshot_ids=[fixture["dataset"]["id"]],
        context_ids=[fixture["context"]["id"]],
    )
    client = McpClient(grant["env"])
    try:
        _handshake(client)
        listed = client.request(4, "tools/call", {"name": "list_finance_context", "arguments": {}})["result"]["structuredContent"]
        denied = client.request(5, "tools/call", {"name": "run_metric", "arguments": {**fixture["spec"], "context_id": other["id"]}})
    finally:
        client.close()
    assert [row["id"] for row in listed["contexts"]] == [fixture["context"]["id"]]
    assert [row["id"] for row in listed["metric_definitions"]] == [definition["id"]]
    assert hidden_definition["id"] not in json.dumps(listed)
    assert [row["id"] for row in listed["scenarios"]] == [visible_scenario["id"]]
    assert hidden_scenario["id"] not in json.dumps(listed)
    assert other["id"] not in json.dumps(listed)
    assert denied["error"] == {"code": -32001, "message": "access denied"}


def test_mcp_explanation_tools_cannot_cross_granted_run_or_context(tmp_path: Path) -> None:
    alpha = _seed(tmp_path / "a", title="alpha", session="alpha-session", organization="华东", profit="30")
    beta = _seed(tmp_path / "b", title="beta", session="beta-session", organization="华南", profit="45")
    beta_run = _finance_store(
        beta["task"],
        snapshot_ids=[beta["dataset"]["id"]],
        session_id=beta["session"],
    ).run_metric(beta["spec"])
    grant = create_stdio_grant(
        alpha["store"].var_root,
        task_id=alpha["task"].id,
        session_id=alpha["session"],
        snapshot_ids=[alpha["dataset"]["id"]],
        context_ids=[alpha["context"]["id"]],
    )
    client = McpClient(grant["env"])
    try:
        _handshake(client)
        prepare = client.request(4, "tools/call", {"name": "prepare_explanation", "arguments": {"run_ids": [beta_run["id"]]}})
        validate = client.request(5, "tools/call", {"name": "validate_explanation", "arguments": {"run_ids": [beta_run["id"]], "body": "x"}})
        background = client.request(6, "tools/call", {"name": "finance_background_save", "arguments": {"context_id": beta["context"]["id"], "text": "x", "basis": "professional_judgment"}})
    finally:
        client.close()
    assert prepare["error"] == {"code": -32001, "message": "access denied"}
    assert validate["error"] == {"code": -32001, "message": "access denied"}
    assert background["error"] == {"code": -32001, "message": "access denied"}


def test_mcp_background_tools_accept_matching_granted_scope_without_context_id(tmp_path: Path) -> None:
    fixture = _seed(tmp_path, title="bg", session="bg-session", organization="华东", profit="30")
    grant = create_stdio_grant(
        fixture["store"].var_root,
        task_id=fixture["task"].id,
        session_id=fixture["session"],
        snapshot_ids=[fixture["dataset"]["id"]],
        context_ids=[fixture["context"]["id"]],
    )
    scope = {"ledger": "bg", "organization": "华东"}
    client = McpClient(grant["env"])
    try:
        _handshake(client)
        saved = client.request(
            4,
            "tools/call",
            {
                "name": "finance_background_save",
                "arguments": {
                    "text": "华东客户结构变化由经理确认。",
                    "basis": "professional_judgment",
                    "scope": scope,
                    "effective_from": "2026-08",
                },
            },
        )["result"]["structuredContent"]
        listed = client.request(
            5,
            "tools/call",
            {
                "name": "finance_background_list",
                "arguments": {"scope": scope, "as_of": "2026-08"},
            },
        )["result"]["structuredContent"]
    finally:
        client.close()
    assert saved["scope"] == scope
    assert [row["id"] for row in listed["business_contexts"]] == [saved["id"]]


def test_granted_scenario_tools_match_direct_service(tmp_path: Path) -> None:
    fixture = _seed_cash(tmp_path)
    direct_scenario = fixture["service"].save_scenario(fixture["spec"])
    direct = fixture["service"].run_scenario({"scenario_id": direct_scenario["id"]})
    grant = create_stdio_grant(
        fixture["store"].var_root,
        task_id=fixture["task"].id,
        session_id="cash-session",
        snapshot_ids=list(fixture["bindings"].values()),
        context_ids=[fixture["context"]["id"]],
    )
    client = McpClient(grant["env"])
    try:
        _handshake(client)
        saved = client.request(4, "tools/call", {"name": "save_scenario", "arguments": fixture["spec"]})["result"]["structuredContent"]
        result = client.request(5, "tools/call", {"name": "run_scenario", "arguments": {"scenario_id": saved["id"]}})["result"]["structuredContent"]
    finally:
        client.close()
    assert result["result"]["rows"][0]["closing_cash"] == direct["result"]["rows"][0]["closing_cash"] == "90"
    assert result["result"]["rows"][0]["unit"] == direct["result"]["rows"][0]["unit"] == "万元"
    assert result["result"]["rows"][0]["source_rows"] == direct["result"]["rows"][0]["source_rows"]


def test_tool_business_errors_are_tool_errors_not_protocol_auth_denials(tmp_path: Path) -> None:
    fixture = _seed(tmp_path, title="business", session="business-session", organization="华东", profit="30")
    grant = create_stdio_grant(
        fixture["store"].var_root,
        task_id=fixture["task"].id,
        session_id=fixture["session"],
        snapshot_ids=[fixture["dataset"]["id"]],
        context_ids=[fixture["context"]["id"]],
    )
    client = McpClient(grant["env"])
    try:
        _handshake(client)
        response = client.request(
            4,
            "tools/call",
            {"name": "save_scenario", "arguments": {"context_id": fixture["context"]["id"], "kind": "bad", "label": "bad"}},
        )
    finally:
        client.close()
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["error"] == "finance request refused"
    assert "scenario kind" in response["result"]["structuredContent"]["message"]


def test_protocol_state_params_and_message_size_are_strict(tmp_path: Path) -> None:
    fixture = _seed(tmp_path, title="strict", session="strict-session", organization="华东", profit="30")
    grant = create_stdio_grant(
        fixture["store"].var_root,
        task_id=fixture["task"].id,
        session_id=fixture["session"],
        snapshot_ids=[fixture["dataset"]["id"]],
        context_ids=[fixture["context"]["id"]],
    )
    client = McpClient(grant["env"])
    try:
        client.notify("notifications/initialized")
        assert client.request(1, "tools/list")["error"] == {"code": -32002, "message": "server is not initialized"}
        unsupported = client.request(2, "initialize", {"protocolVersion": "1900-01-01", "capabilities": {}})
        assert unsupported["result"]["protocolVersion"] == "2025-06-18"
        client.notify("notifications/initialized")
        assert client.request(3, "tools/call", {"name": "list_finance_context", "arguments": False})["error"] == {
            "code": -32602,
            "message": "tool arguments must be an object",
        }
        assert client.request(4, "tools/call", {"name": "list_finance_context", "arguments": []})["error"] == {
            "code": -32602,
            "message": "tool arguments must be an object",
        }
        assert client.raw(json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping", "params": []}))["error"] == {
            "code": -32602,
            "message": "params must be an object",
        }
        assert client.raw("x" * (1024 * 1024 + 1))["error"] == {"code": -32600, "message": "message too large"}
    finally:
        client.close()


def test_cross_task_context_is_denied_without_leaking_paths(tmp_path: Path) -> None:
    alpha = _seed(tmp_path / "a", title="alpha", session="alpha-session", organization="华东", profit="30")
    beta = _seed(tmp_path / "b", title="beta", session="beta-session", organization="华南", profit="45")
    grant = create_stdio_grant(
        alpha["store"].var_root,
        task_id=alpha["task"].id,
        session_id=alpha["session"],
        snapshot_ids=[alpha["dataset"]["id"]],
        context_ids=[alpha["context"]["id"]],
    )
    client = McpClient(grant["env"])
    try:
        _handshake(client)
        denied = client.request(4, "tools/call", {"name": "run_metric", "arguments": beta["spec"]})
    finally:
        client.close()
    assert denied["error"] == {"code": -32001, "message": "access denied"}
    assert str(tmp_path) not in json.dumps(denied)


def test_unknown_session_cannot_create_grant(tmp_path: Path) -> None:
    fixture = _seed(tmp_path, title="unknown", session="known-session", organization="华东", profit="30")
    with pytest.raises(Exception, match="session"):
        create_stdio_grant(
            fixture["store"].var_root,
            task_id=fixture["task"].id,
            session_id="missing-session",
            snapshot_ids=[fixture["dataset"]["id"]],
        )


def test_packaged_cli_registration_grant_config_and_revoke(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = _seed(tmp_path, title="cli", session="cli-session", organization="华东", profit="30")
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_parsers(sub)
    config_path = tmp_path / "client-config.json"
    spec = {
        "task_id": fixture["task"].id,
        "session_id": fixture["session"],
        "snapshot_ids": [fixture["dataset"]["id"]],
        "context_ids": [fixture["context"]["id"]],
        "config_path": str(config_path),
        "frozen": True,
    }
    args = parser.parse_args(["finance-mcp-grant", "--spec", json.dumps(spec)])
    args.var = str(fixture["store"].var_root)

    assert dispatch(args) is True
    stdout = capsys.readouterr().out
    result = json.loads(stdout)
    assert set(result) == {"config_path", "grant_id"}
    assert "FOUNDRY_MCP_TOKEN" not in stdout
    assert config_path.stat().st_mode & 0o777 == 0o600

    config = json.loads(config_path.read_text())
    server = config["mcpServers"]["finance-skill-foundry"]
    assert [server["command"], *server["args"]] == [sys.executable, "finance-mcp-serve"]
    assert server["env"]["FOUNDRY_MCP_GRANT_ID"] == result["grant_id"]
    assert server["env"]["FOUNDRY_MCP_TOKEN"]

    revoke_args = parser.parse_args(["finance-mcp-revoke", "--grant-id", result["grant_id"]])
    revoke_args.var = str(fixture["store"].var_root)
    assert dispatch(revoke_args) is True
    revoked = json.loads((fixture["store"].var_root / "mcp-grants" / f"{result['grant_id']}.json").read_text())
    assert revoked["revoked"] is True


def test_client_command_uses_module_for_dev_and_subcommand_for_frozen() -> None:
    assert client_command(frozen=False) == [sys.executable, "-m", "foundry.finance_mcp"]
    assert client_command(frozen=True) == [sys.executable, "finance-mcp-serve"]


def test_grant_cli_refuses_session_driven_issuance(tmp_path: Path) -> None:
    fixture = _seed(tmp_path, title="operator", session="operator-session", organization="华东", profit="30")
    args = SimpleNamespace(
        cmd="finance-mcp-grant",
        var=str(fixture["store"].var_root),
        spec=json.dumps(
            {
                "task_id": fixture["task"].id,
                "session_id": fixture["session"],
                "snapshot_ids": [fixture["dataset"]["id"]],
                "session_driven": True,
            }
        ),
    )
    with pytest.raises(Exception, match="local operator"):
        dispatch(args)


def test_client_config_refuses_existing_file_and_symlink(tmp_path: Path) -> None:
    fixture = _seed(tmp_path, title="config-safe", session="config-session", organization="华东", profit="30")
    grant = create_stdio_grant(
        fixture["store"].var_root,
        task_id=fixture["task"].id,
        session_id=fixture["session"],
        snapshot_ids=[fixture["dataset"]["id"]],
        context_ids=[fixture["context"]["id"]],
    )
    existing = tmp_path / "existing.json"
    existing.write_text("{}", encoding="utf-8")
    with pytest.raises(Exception, match="already exists"):
        write_client_config(grant, config_path=existing)

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(Exception, match="already exists"):
        write_client_config(grant, config_path=link)


def test_grant_and_revoke_reject_session_bound_cli_args(tmp_path: Path) -> None:
    fixture = _seed(tmp_path, title="session-cli", session="session-cli", organization="华东", profit="30")
    spec = {
        "task_id": fixture["task"].id,
        "session_id": fixture["session"],
        "snapshot_ids": [fixture["dataset"]["id"]],
    }
    grant_args = SimpleNamespace(
        cmd="finance-mcp-grant",
        var=str(fixture["store"].var_root),
        session=fixture["session"],
        spec=json.dumps(spec),
    )
    with pytest.raises(Exception, match="local operator"):
        dispatch(grant_args)

    revoke_args = SimpleNamespace(
        cmd="finance-mcp-revoke",
        var=str(fixture["store"].var_root),
        session=fixture["session"],
        grant_id="0" * 32,
    )
    with pytest.raises(Exception, match="local operator"):
        dispatch(revoke_args)


def test_registered_cli_rejects_session_grant_and_unknown_session(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from foundry.cli import main as foundry_main

    fixture = _seed(tmp_path, title="real-cli", session="real-cli-session", organization="华东", profit="30")
    spec = json.dumps(
        {
            "task_id": fixture["task"].id,
            "session_id": fixture["session"],
            "snapshot_ids": [fixture["dataset"]["id"]],
        }
    )
    code = foundry_main([
        "--var",
        str(fixture["store"].var_root),
        "--session",
        fixture["session"],
        "finance-mcp-grant",
        "--spec",
        spec,
    ])
    captured = capsys.readouterr()
    assert code != 0
    assert "local operator" in captured.err

    code = foundry_main([
        "--var",
        str(fixture["store"].var_root),
        "--session",
        "missing-session",
        "finance-mcp-grant",
        "--spec",
        spec,
    ])
    captured = capsys.readouterr()
    assert code != 0
    assert "session" in captured.err
