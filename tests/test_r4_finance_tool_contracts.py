from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.finance_mcp import (
    FinanceMcpServer,
    McpRefused,
    _tools,
    create_stdio_grant,
)
from foundry.task import TaskStore


ROOT = Path(__file__).resolve().parents[1]


def _tool(name: str) -> dict:
    tools = {tool["name"]: tool for tool in _tools()}
    return tools[name]


def _seed_context(tmp_path: Path, *, session_id: str) -> dict:
    from foundry.finance_service import FinanceStore

    store = TaskStore(tmp_path / "var")
    task = store.create(title="r4-contract", make_current=False)
    analysis = AnalysisStore(task)
    dataset = analysis.add_dataset(
        _json(
            tmp_path / "ledger.json",
            [
                {
                    "ledger": "L1",
                    "organization": "O1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "元",
                    "amount": "1",
                }
            ],
        ),
        name="ledger",
    )
    task.record_session(session_id, role="analysis")
    service = FinanceStore(task, snapshot_ids=[dataset["id"]], session_id=session_id)
    allowed = service.save_context(
        {
            "name": "allowed",
            "bindings": {"actual": dataset["id"]},
            "scopes": {
                "actual": {
                    "ledger": "L1",
                    "organization": "O1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "元",
                }
            },
        }
    )
    denied = service.save_context(
        {
            "name": "denied",
            "bindings": {"actual": dataset["id"]},
            "scopes": {
                "actual": {
                    "ledger": "L2",
                    "organization": "O2",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "元",
                }
            },
        }
    )
    return {
        "store": store,
        "task": task,
        "dataset": dataset,
        "allowed": allowed,
        "denied": denied,
        "session_id": session_id,
    }


def _json(path: Path, rows: list[dict]) -> Path:
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return path


def test_mcp_r4_schema_exposes_requirements_quality_completion_and_aging_sections():
    requirements = _tool("analysis_requirements_save")
    assert requirements["inputSchema"]["required"] == ["context_id", "question", "items"]
    assert "does not complete the original question" in requirements["description"]
    assert requirements["inputSchema"]["properties"]["items"]["items"]["properties"]["periods"]["type"] == "array"
    assert "bound snapshots" in requirements["description"]

    scenario = _tool("save_scenario")
    inputs = scenario["inputSchema"]["properties"]["inputs"]["properties"]
    status_filter = inputs["status_filter"]["properties"]
    assert {"field", "include", "exclude", "mapping"} <= set(status_filter)
    assert "excluded_detail_rows" in scenario["description"]
    assert "Current status does not prove historical status" in scenario["description"]

    run_scenario = _tool("run_scenario")
    assert "excluded_detail_rows" in run_scenario["description"]

    drilldown = _tool("drilldown_fact")
    assert drilldown["inputSchema"]["properties"]["section"]["enum"] == [
        "rows",
        "detail_rows",
        "excluded_detail_rows",
    ]

    prepare = _tool("prepare_explanation")
    assert "evidence_groups" in prepare["description"]
    assert "automatic supporting tables" in prepare["description"]

    validate = _tool("validate_explanation")
    assert "registered requirements" in validate["description"]
    assert "provenance" in validate["description"]

    save_draft = _tool("save_explanation_draft")
    assert "repair_allowed" in save_draft["description"]
    assert "no_progress" in save_draft["description"]
    assert "two-repair" in save_draft["description"]
    assert "verified_input_gap" in save_draft["description"]


def test_mcp_requirements_are_bound_to_granted_context(tmp_path: Path):
    fixture = _seed_context(tmp_path, session_id="r4-session")
    grant = create_stdio_grant(
        fixture["store"].var_root,
        task_id=fixture["task"].id,
        session_id=fixture["session_id"],
        snapshot_ids=[fixture["dataset"]["id"]],
        context_ids=[fixture["allowed"]["id"]],
    )
    server = FinanceMcpServer(
        var_root=fixture["store"].var_root,
        grant_id=grant["grant_id"],
        token=grant["token"],
    )

    saved = server._call(
        {
            "name": "analysis_requirements_save",
            "arguments": {
                "context_id": fixture["allowed"]["id"],
                "question": "解释利润并下钻",
                "items": [
                    {
                        "id": "profit",
                        "metric": "profit",
                        "requires_drilldown": True,
                    }
                ],
            },
        }
    )["structuredContent"]
    assert saved["context_id"] == fixture["allowed"]["id"]

    listed = server._call(
        {
            "name": "analysis_requirements_list",
            "arguments": {"context_id": fixture["allowed"]["id"]},
        }
    )["structuredContent"]
    assert [row["id"] for row in listed["requirements"]] == [saved["id"]]

    with pytest.raises(McpRefused, match="finance context is outside this grant"):
        server._call(
            {
                "name": "analysis_requirements_save",
                "arguments": {
                    "context_id": fixture["denied"]["id"],
                    "question": "越权问题",
                    "items": [{"id": "profit", "metric": "profit"}],
                },
            }
        )


def test_dsh_and_method_r4_contracts_are_mirrored_into_resources():
    mirrored = [
        ("dsh-plugin/finance-tools.js", "foundry/resources/dsh-plugin/finance-tools.js"),
        (
            "dsh-plugin/presets/analysis/agent.cordis.yml",
            "foundry/resources/dsh-plugin/presets/analysis/agent.cordis.yml",
        ),
        ("method/FOUNDRY.md", "foundry/resources/method/FOUNDRY.md"),
        (
            "method/financial-statements/SKILL.md",
            "foundry/resources/method/financial-statements/SKILL.md",
        ),
        ("method/reconciliation/SKILL.md", "foundry/resources/method/reconciliation/SKILL.md"),
        (
            "method/variance-analysis/SKILL.md",
            "foundry/resources/method/variance-analysis/SKILL.md",
        ),
    ]
    for source, bundled in mirrored:
        assert (ROOT / source).read_text(encoding="utf-8") == (
            ROOT / bundled
        ).read_text(encoding="utf-8")

    finance_tools = (ROOT / "dsh-plugin/finance-tools.js").read_text(encoding="utf-8")
    assert "analysis_requirements_save" in finance_tools
    assert 'organizations:{type:"array"' in finance_tools
    assert "status_filter" in finance_tools
    assert "excluded_detail_rows" in finance_tools
    assert "repair_allowed" in finance_tools

    persona = (ROOT / "dsh-plugin/presets/analysis/agent.cordis.yml").read_text(
        encoding="utf-8"
    )
    assert "analysis_requirements_save" in persona
    assert "inputs.status_filter" in persona
    assert "completion.repair_allowed" in persona
    assert "stop_reason 为 no_progress" in persona

    foundry_note = (ROOT / "method/FOUNDRY.md").read_text(encoding="utf-8")
    assert "Before calculation, save the current question contract" in foundry_note
    assert "excluded_detail_rows" in foundry_note
    assert "completion.repair_allowed" in foundry_note
