#!/usr/bin/env python3
"""Verify Finance MCP with an installed external MCP client."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import re
import uuid
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

from foundry.analysis import AnalysisStore
from foundry.finance_mcp import create_stdio_grant, revoke_stdio_grant, write_client_config
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

SERVER_NAME = "finance-skill-foundry"
TOOL_NAMES = ("list_finance_context", "run_metric", "drilldown_fact")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an installed-client Finance MCP verification.")
    parser.add_argument("--client", default="codex", choices=("claude", "codex"))
    parser.add_argument("--output", default="build/finance-mcp-client-verification.json")
    parser.add_argument("--codex-path", default="", help="explicit Codex CLI binary for --client codex")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {"client": args.client, "status": "blocked"}
    try:
        if args.client == "claude":
            evidence.update(_verify_claude(timeout=args.timeout))
        elif args.client == "codex":
            evidence.update(_verify_codex(timeout=args.timeout, codex_path=args.codex_path or None))
    except Exception as exc:
        evidence.update({"status": "blocked", "blocker": str(exc)})
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "evidence_path": str(output)}, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["status"] == "passed" else 2


def _verify_claude(*, timeout: int) -> dict[str, Any]:
    claude = shutil.which("claude")
    if not claude:
        return {"status": "blocked", "blocker": "claude CLI is not installed"}
    version = subprocess.run([claude, "--version"], check=False, text=True, capture_output=True, timeout=20).stdout.strip()
    mcp_help = subprocess.run([claude, "mcp", "--help"], check=False, text=True, capture_output=True, timeout=20).stdout
    with tempfile.TemporaryDirectory(prefix="finance-mcp-client-") as tmp:
        root = Path(tmp)
        fixture = _seed(root)
        config_path = root / "finance-mcp-client.json"
        grant = create_stdio_grant(
            fixture["store"].var_root,
            task_id=fixture["task"].id,
            session_id=fixture["session_id"],
            snapshot_ids=[fixture["dataset"]["id"]],
            context_ids=[fixture["context"]["id"]],
        )
        config = write_client_config(grant, config_path=config_path)
        prompt = (
            "Use the finance-skill-foundry MCP server only. "
            "Call list_finance_context, then call run_metric using the visible context_id with "
            "metric kind management_pnl, dimensions organization and period, and scenario_bindings actual=actual. "
            "Return a compact JSON object with keys profit, unit, evidence_count, context_id."
        )
        command = [
            claude,
            "--print",
            "--output-format",
            "json",
            "--mcp-config",
            str(config_path),
            "--strict-mcp-config",
            "--allowedTools",
            "mcp__finance-skill-foundry__list_finance_context,mcp__finance-skill-foundry__run_metric",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            prompt,
        ]
        env = dict(os.environ)
        env.pop("FOUNDRY_MCP_TOKEN", None)
        run = subprocess.run(command, cwd=Path.cwd(), text=True, capture_output=True, timeout=timeout, env=env)
        evidence = {
            "status": "passed" if run.returncode == 0 else "blocked",
            "client": "claude",
            "client_version": version,
            "client_mcp_help_mentions_config": "--mcp-config" in subprocess.run(
                [claude, "--help"], check=False, text=True, capture_output=True, timeout=20
            ).stdout,
            "client_mcp_help_mentions_add": "add" in mcp_help and "stdio" in mcp_help,
            "config_file_mode": oct(config_path.stat().st_mode & 0o777),
            "grant_id": config["grant_id"],
            "server_name": SERVER_NAME,
            "configured_local_mcp_servers": [SERVER_NAME],
            "command": _redacted_command(command),
            "stdout": _limit(run.stdout),
            "stderr": _limit(run.stderr),
            "returncode": run.returncode,
            "expected": {"profit": "30", "unit": "万元", "context_id": fixture["context"]["id"]},
        }
        parsed = _parse_claude_json(run.stdout)
        if parsed is not None:
            evidence["parsed_result"] = parsed
            if isinstance(parsed, dict) and parsed.get("terminal_reason") == "api_error":
                evidence["blocker"] = str(parsed.get("result") or "Claude CLI API error")
            text = json.dumps(parsed, ensure_ascii=False)
            evidence["status"] = "passed" if all(value in text for value in ("30", "万元", fixture["context"]["id"])) else "blocked"
        if evidence["status"] != "passed":
            evidence.setdefault("blocker", "Claude CLI did not return the expected MCP-derived finance result")
            evidence["alternative_installed_client"] = _codex_client_evidence()
        return evidence


def _verify_codex(*, timeout: int, codex_path: str | None = None) -> dict[str, Any]:
    codex = codex_path if codex_path else shutil.which("codex")
    if not codex:
        return {"status": "blocked", "blocker": "codex CLI is not installed"}
    codex = str(Path(codex)) if codex_path else str(codex)
    if codex_path and not Path(codex).is_file():
        return {"status": "blocked", "blocker": f"codex CLI path is not a file: {codex}"}
    version = subprocess.run([codex, "--version"], check=False, text=True, capture_output=True, timeout=20).stdout.strip()
    mcp_help = subprocess.run([codex, "mcp", "--help"], check=False, text=True, capture_output=True, timeout=20).stdout
    exec_help = subprocess.run([codex, "exec", "--help"], check=False, text=True, capture_output=True, timeout=20).stdout
    with tempfile.TemporaryDirectory(prefix="finance-mcp-codex-") as tmp:
        root = Path(tmp)
        fixture = _seed(root)
        expected = _expected_direct(fixture)
        grant = create_stdio_grant(
            fixture["store"].var_root,
            task_id=fixture["task"].id,
            session_id=fixture["session_id"],
            snapshot_ids=[fixture["dataset"]["id"]],
            context_ids=[fixture["context"]["id"]],
        )
        codex_home = root / "codex-home"
        _prepare_codex_home(codex_home, grant["env"])
        schema = root / "schema.json"
        schema.write_text(json.dumps(_output_schema(), ensure_ascii=False), encoding="utf-8")
        last = root / "last-message.json"
        prompt = _codex_success_prompt(fixture["context"]["id"])
        command = [
            codex,
            "exec",
            "--ephemeral",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--json",
            "--approve-for-me",
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(last),
            "-C",
            str(Path.cwd()),
            prompt,
        ]
        env = dict(os.environ)
        env["CODEX_HOME"] = str(codex_home)
        env.pop("FOUNDRY_MCP_TOKEN", None)
        run = subprocess.run(command, cwd=Path.cwd(), text=True, capture_output=True, timeout=timeout, env=env)
        parsed = _load_json_if_exists(last)
        success = _codex_success_matches(parsed, expected, fixture["context"]["id"])

        revoke_stdio_grant(fixture["store"].var_root, grant["grant_id"])
        revoked_last = root / "revoked-last-message.json"
        revoked_command = [*command]
        revoked_command[revoked_command.index(str(last))] = str(revoked_last)
        revoked_run = subprocess.run(revoked_command[:-1] + [_codex_revoked_prompt()], cwd=Path.cwd(), text=True, capture_output=True, timeout=timeout, env=env)
        revoked_parsed = _load_json_if_exists(revoked_last)
        revoked_rejected, revoked_source = _revoked_rejection_seen(revoked_run.stdout, revoked_run.stderr, revoked_parsed)

        configured = _configured_codex_identity(codex_home / "config.toml")
        evidence = {
            "status": "passed" if success and revoked_rejected else "blocked",
            "client": "codex",
            "client_version": version,
            "client_binary": codex,
            "client_mcp_management_available": "Manage external MCP servers" in mcp_help,
            "client_exec_config_override_available": "--config" in exec_help,
            "configured_model": configured.get("model"),
            "configured_model_provider": configured.get("model_provider"),
            "codex_home_mode": oct(codex_home.stat().st_mode & 0o777),
            "auth_copy_mode": _mode(codex_home / "auth.json"),
            "config_file_mode": _mode(codex_home / "config.toml"),
            "grant_id": grant["grant_id"],
            "server_name": SERVER_NAME,
            "configured_local_mcp_servers": [SERVER_NAME],
            "command": _redacted_command(command),
            "returncode": run.returncode,
            "stdout": _redact(_limit(run.stdout)),
            "stderr": _redact(_limit(run.stderr)),
            "parsed_result": parsed,
            "expected": expected,
            "revoked_returncode": revoked_run.returncode,
            "revoked_stdout": _redact(_limit(revoked_run.stdout)),
            "revoked_stderr": _redact(_limit(revoked_run.stderr)),
            "revoked_parsed_result": revoked_parsed,
            "revoked_rejection_seen": revoked_rejected,
            "revoked_rejection_source": revoked_source,
        }
        if evidence["status"] != "passed":
            if run.returncode != 0:
                evidence["blocker"] = _codex_error(run.stdout, run.stderr) or "Codex CLI success run failed"
            elif not success:
                evidence["blocker"] = "Codex CLI did not return the expected MCP-derived list/run/drilldown result"
            elif not revoked_rejected:
                evidence["blocker"] = "Codex CLI did not surface a revoked-grant MCP rejection"
        return evidence


def _seed(root: Path) -> dict[str, Any]:
    store = TaskStore(root / "var")
    task = store.create(title="synthetic-g1", make_current=False)
    analysis = AnalysisStore(task)
    source = root / "g1.json"
    source.write_text(
        json.dumps(
            [
                {
                    "ledger": "G1",
                    "organization": "Synthetic G1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                    "management_account": "revenue",
                    "amount": "120",
                    "source_row": "1",
                    "doc_id": "G1-R",
                    "line_id": "1",
                },
                {
                    "ledger": "G1",
                    "organization": "Synthetic G1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                    "management_account": "cost",
                    "amount": "70",
                    "source_row": "2",
                    "doc_id": "G1-C",
                    "line_id": "2",
                },
                {
                    "ledger": "G1",
                    "organization": "Synthetic G1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                    "management_account": "expense",
                    "amount": "20",
                    "source_row": "3",
                    "doc_id": "G1-E",
                    "line_id": "3",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    dataset = analysis.add_dataset(source, name="synthetic-g1")
    session_id = str(uuid.uuid4())
    task.record_session(session_id, role="analysis")
    service = FinanceStore(task, snapshot_ids=[dataset["id"]], session_id=session_id)
    context = service.save_context(
        {
            "name": "synthetic-g1-context",
            "bindings": {"actual": dataset["id"]},
            "scopes": {
                "actual": {
                    "ledger": "G1",
                    "organization": "Synthetic G1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": "actual",
                }
            },
            "policies": {"actual": {}},
        }
    )
    return {"store": store, "task": task, "dataset": dataset, "context": context, "session_id": session_id}


def _expected_direct(fixture: dict[str, Any]) -> dict[str, Any]:
    service = FinanceStore(fixture["task"], snapshot_ids=[fixture["dataset"]["id"]], session_id=fixture["session_id"])
    metric = service.run_metric(
        {
            "context_id": fixture["context"]["id"],
            "metric": {
                "kind": "management_pnl",
                "dimensions": ["organization", "period"],
                "scenario_bindings": {"actual": "actual"},
            },
        }
    )
    row = metric["result"]["rows"][0]
    drill = service.drilldown_fact({"run_id": metric["id"], "row": 0, "column": "profit"})
    return {
        "context_id": fixture["context"]["id"],
        "profit": str(row["profit"]),
        "unit": row["unit"],
        "evidence_count": len(row["evidence"]["profit"]),
        "drilldown_count": int(drill["total"]),
    }


def _prepare_codex_home(codex_home: Path, server_env: dict[str, str]) -> None:
    source_home = Path.home() / ".codex"
    auth = source_home / "auth.json"
    if not auth.is_file():
        raise RuntimeError("Codex auth.json is not available")
    codex_home.mkdir(parents=True, exist_ok=True)
    codex_home.chmod(0o700)
    shutil.copyfile(auth, codex_home / "auth.json")
    (codex_home / "auth.json").chmod(0o600)
    config = _minimal_codex_config(source_home / "config.toml")
    config.extend(
        [
            f'[mcp_servers."{SERVER_NAME}"]',
            f'command = "{_toml_string(sys.executable)}"',
            'args = ["-m", "foundry.finance_mcp"]',
            'startup_timeout_sec = 20',
            f'[mcp_servers."{SERVER_NAME}".env]',
        ]
    )
    for key, value in sorted(server_env.items()):
        config.append(f'{key} = "{_toml_string(value)}"')
    path = codex_home / "config.toml"
    path.write_text("\n".join(config) + "\n", encoding="utf-8")
    path.chmod(0o600)



def _configured_codex_identity(config_path: Path) -> dict[str, str]:
    if tomllib is None or not config_path.is_file():
        return {}
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    result = {}
    for key in ("model", "model_provider"):
        value = data.get(key)
        if isinstance(value, str) and value:
            result[key] = value
    return result

def _minimal_codex_config(config_path: Path) -> list[str]:
    if tomllib is None or not config_path.is_file():
        return []
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    lines = []
    for key in ("model", "model_provider", "model_reasoning_effort", "service_tier"):
        value = data.get(key)
        if isinstance(value, str) and value:
            lines.append(f'{key} = "{_toml_string(value)}"')
    return lines


def _toml_string(value: str) -> str:
    return str(value).replace('\\', '\\\\').replace('"', '\\"')


def _output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "contexts_seen": {"type": "integer"},
            "context_id": {"type": "string"},
            "profit": {"type": "string"},
            "unit": {"type": "string"},
            "evidence_count": {"type": "integer"},
            "drilldown_count": {"type": "integer"},
            "tools_used": {"type": "array", "items": {"type": "string"}},
            "revoked_denied": {"type": "boolean"},
            "denial_message": {"type": "string"},
        },
        "required": ["contexts_seen", "context_id", "profit", "unit", "evidence_count", "drilldown_count", "tools_used", "revoked_denied", "denial_message"],
    }


def _codex_success_prompt(context_id: str) -> str:
    return (
        "Use only the finance-skill-foundry MCP tools. Do not use shell commands or inspect files. "
        "First use the MCP tool list implicitly available to you and then call list_finance_context. "
        f"Use context_id {context_id}. Call run_metric with metric kind management_pnl, dimensions organization and period, "
        "and scenario_bindings actual=actual. Then call drilldown_fact with the run_id returned by run_metric, row 0, and column profit. "
        "Return only JSON matching the schema: contexts_seen, context_id, profit as a string, unit, evidence_count for profit, "
        "drilldown_count, tools_used, revoked_denied=false, denial_message=''."
    )


def _codex_revoked_prompt() -> str:
    return (
        "Use only the finance-skill-foundry MCP tools. Do not use shell commands or inspect files. "
        "Call list_finance_context. The grant has been revoked; report whether the MCP call is denied. "
        "Return only JSON matching the schema with contexts_seen=0, context_id='', profit='', unit='', evidence_count=0, "
        "drilldown_count=0, tools_used containing list_finance_context, revoked_denied true when access is denied, and denial_message."
    )


def _codex_success_matches(parsed: Any, expected: dict[str, Any], context_id: str) -> bool:
    if not isinstance(parsed, dict):
        return False
    tools = set(parsed.get("tools_used") or [])
    return (
        parsed.get("context_id") == context_id
        and str(parsed.get("profit")) == expected["profit"]
        and parsed.get("unit") == expected["unit"]
        and int(parsed.get("evidence_count") or -1) == expected["evidence_count"]
        and int(parsed.get("drilldown_count") or -1) == expected["drilldown_count"]
        and set(TOOL_NAMES).issubset(tools)
    )


def _revoked_rejection_seen(stdout: str, stderr: str, parsed: Any) -> tuple[bool, str]:
    parsed_text = json.dumps(parsed, ensure_ascii=False) if parsed is not None else ""
    text = f"{stdout}\n{stderr}\n{parsed_text}".lower()
    if isinstance(parsed, dict) and parsed.get("revoked_denied") is True:
        return True, "model_result"
    if "access denied" in text and "-32001" in text and "mcp" in text:
        return True, "codex_mcp_startup_event"
    return False, ""


def _load_json_if_exists(path: Path) -> Any:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _mode(path: Path) -> str | None:
    if not path.exists():
        return None
    return oct(stat.S_IMODE(path.stat().st_mode))


def _redacted_command(command: list[str]) -> list[str]:
    redacted = []
    skip_next = False
    for item in command:
        if skip_next:
            redacted.append("<path>")
            skip_next = False
        elif item in {"--mcp-config", "--output-schema", "--output-last-message", "-C"}:
            redacted.append(item)
            skip_next = True
        else:
            redacted.append(item)
    return redacted


def _limit(text: str, maximum: int = 6000) -> str:
    return text if len(text) <= maximum else text[:maximum] + "...<truncated>"


def _redact(text: str) -> str:
    home = str(Path.home())
    text = text.replace(home, "<home>")
    text = re.sub(r"https://\S+", "<url>", text)
    text = re.sub(r"(?i)(access[_-]?token|refresh[_-]?token|authorization|bearer)([^\n]*)", r"\1=<redacted>", text)
    return text


def _parse_claude_json(text: str) -> Any:
    try:
        envelope = json.loads(text)
    except ValueError:
        return None
    if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
        try:
            return json.loads(envelope["result"])
        except ValueError:
            return envelope
    return envelope


def _codex_error(stdout: str, stderr: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get("message") or event.get("error") or event.get("msg")
        if message:
            return str(message)
    if stderr.strip():
        return _limit(stderr.strip(), 1000)
    return None


def _codex_client_evidence() -> dict[str, Any]:
    codex = shutil.which("codex")
    if not codex:
        return {"client": "codex", "installed": False}
    version = subprocess.run([codex, "--version"], check=False, text=True, capture_output=True, timeout=20).stdout.strip()
    mcp_help = subprocess.run([codex, "mcp", "--help"], check=False, text=True, capture_output=True, timeout=20).stdout
    exec_help = subprocess.run([codex, "exec", "--help"], check=False, text=True, capture_output=True, timeout=20).stdout
    return {
        "client": "codex",
        "installed": True,
        "version": version,
        "mcp_management_available": "Manage external MCP servers" in mcp_help,
        "exec_config_override_available": "--config" in exec_help,
    }


if __name__ == "__main__":
    raise SystemExit(main())
