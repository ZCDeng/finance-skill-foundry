from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal

import pytest

from foundry.analysis import AnalysisStore
from foundry import cli as foundry_cli
from foundry.excel_bridge import BridgeTokenAuthority, ExcelBridgeApp, generate_manifest, main
from foundry.task import TaskStore

WORKBOOK = "wb_main"
OTHER_WORKBOOK = "wb_other"


def _app(tmp_path):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="Excel bridge")
    task.record_session("excel", role="analysis")
    authority = BridgeTokenAuthority(b"local-test-secret-local-test-secret")
    token = authority.issue(task_id=task.id, session_id="excel", ttl_seconds=60)
    app = ExcelBridgeApp(var_root=root, token_authority=authority)
    _call(app, token, "POST", "/api/register-workbook", {"workbook_id": WORKBOOK, "name": "model.xlsx", "host": {"excelApi11": True}})
    return app, task, token


def _call(app, token, method, path, payload=None):
    status, _, body = app.handle(
        method,
        path,
        {"Authorization": f"Bearer {token}"},
        json.dumps(payload or {}).encode("utf8"),
    )
    return status, json.loads(body)


def _cell(address, value="", value_type="string", number_format="General", formula=""):
    return {"address": address, "value": value, "valueType": value_type, "numberFormat": number_format, "formula": formula}


def _input_binding(binding_id="actual", address="Model!A1:G3", *, fields=None, headers=None):
    return {
        "id": binding_id,
        "name": binding_id,
        "role": "input",
        "worksheet": "Model",
        "address": address,
        "binding_type": "matrix",
        "headers": headers or ["management_account", "amount", "organization", "period", "currency", "unit", "scenario"],
        "fields": fields or [
            {"name": "management_account", "policy": "text"},
            {"name": "amount", "policy": "amount", "unit": "CNY"},
            {"name": "organization", "policy": "text"},
            {"name": "period", "policy": "text"},
            {"name": "currency", "policy": "text"},
            {"name": "unit", "policy": "text"},
            {"name": "scenario", "policy": "text"},
        ],
        "header": True,
    }


def _input_values(account="revenue", amount="120.50", org="HQ", period="2026-08", scenario="actual"):
    return [
        ["management_account", "amount", "organization", "period", "currency", "unit", "scenario"],
        [account, amount, org, period, "CNY", "yuan", scenario],
    ]


def _output_binding(*, baseline_cells=None, address="Model!H1:J3"):
    return {
        "id": "out",
        "name": "results",
        "role": "output",
        "writable": True,
        "dedicated_area": True,
        "worksheet": "Model",
        "address": address,
        "binding_type": "matrix",
        "headers": ["amount", "comment", "identifier"],
        "fields": [
            {"name": "amount", "policy": "amount", "unit": "CNY"},
            {"name": "comment", "policy": "text"},
            {"name": "identifier", "policy": "text"},
        ],
        "header": True,
        "baseline_cells": baseline_cells or {},
    }


def _import(app, token, binding_id="actual", *, alias=None, values=None, scope=None):
    return _call(
        app,
        token,
        "POST",
        "/api/import-binding",
        {
            "workbook_id": WORKBOOK,
            "binding": _input_binding(binding_id),
            "values": values or _input_values(),
            "alias": alias or binding_id,
            "scope": scope or {"ledger": "集团账套", "organization": "HQ", "period": "2026-08", "currency": "CNY", "unit": "yuan", "scenario": "actual"},
            "policy": {"source_binding": binding_id},
        },
    )


def test_context_requires_task_bound_bearer_token_and_isolates_state_by_task(tmp_path):
    app, task, token = _app(tmp_path)
    status, payload = _call(app, token, "GET", "/api/context")
    assert status == 200
    assert payload["task_id"] == task.id
    assert payload["session_id"] == "excel"
    assert payload["workbooks"][0]["id"] == WORKBOOK

    status, _, body = app.handle("GET", "/api/context", {}, b"")
    payload = json.loads(body)
    assert status == 400
    assert payload["error"]["message"] == "bridge token is required"

    other = TaskStore(tmp_path / "var").create(title="Other")
    other.record_session("other", role="analysis")
    wrong_token = BridgeTokenAuthority(b"local-test-secret-local-test-secret").issue(task_id=other.id, session_id="other")
    status, payload = _call(app, wrong_token, "GET", "/api/context")
    assert status == 200
    assert payload["task_id"] == other.id
    assert payload["workbooks"] == []


def test_import_preserves_prior_session_snapshots_and_latest_distinct_bindings(tmp_path):
    app, task, token = _app(tmp_path)
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps({"rows": [{"seed": 1}]}), encoding="utf8")
    seed = AnalysisStore(task).add_dataset(seed_path, name="seed")
    task.update_session_context("excel", snapshot_ids=[seed["id"]])

    status, first = _import(app, token, "actual", alias="actual", values=_input_values("revenue", "100"))
    assert status == 200, first
    status, second = _import(app, token, "budget", alias="budget", values=_input_values("revenue", "150", scenario="budget"), scope={"scenario": "budget"})
    assert status == 200, second
    status, third = _import(app, token, "actual", alias="actual", values=_input_values("revenue", "120"))
    assert status == 200, third

    session_ids = third["session"]["snapshot_ids"]
    assert seed["id"] in session_ids
    assert first["dataset"]["id"] in session_ids
    assert second["dataset"]["id"] in session_ids
    assert third["dataset"]["id"] in session_ids
    assert third["finance_context"]["bindings"] == {
        "actual": third["dataset"]["id"],
        "budget": second["dataset"]["id"],
    }
    assert third["finance_context"]["scopes"]["budget"] == {"scenario": "budget"}



def test_two_column_management_selection_imports_with_scope_defaults(tmp_path):
    app, _, token = _app(tmp_path)
    two_column_binding = _input_binding(
        "actual",
        "Model!A1:B2",
        headers=["management_account", "amount"],
        fields=[
            {"name": "management_account", "policy": "text"},
            {"name": "amount", "policy": "amount", "unit": "CNY"},
        ],
    )
    status, payload = _call(
        app,
        token,
        "POST",
        "/api/import-binding",
        {
            "workbook_id": WORKBOOK,
            "binding": two_column_binding,
            "values": [["management_account", "amount"], ["revenue", "88.80"]],
            "alias": "actual",
            "scope": {"ledger": "L1", "organization": "HQ", "period": "2026-08", "currency": "CNY", "unit": "yuan", "scenario": "actual"},
            "policy": {"source_binding": "actual"},
        },
    )
    assert status == 200, payload
    assert payload["dataset"]["row_count"] == 1
    assert payload["finance_context"]["bindings"] == {"actual": payload["dataset"]["id"]}
    assert payload["finance_context"]["scopes"]["actual"]["organization"] == "HQ"

def test_child_session_cannot_import_new_excel_snapshot(tmp_path):
    app, task, token = _app(tmp_path)
    task.record_session("child", role="analysis", parent_session_id="excel")
    child_token = app.token_authority.issue(task_id=task.id, session_id="child")
    status, payload = _call(
        app,
        child_token,
        "POST",
        "/api/import-binding",
        {"workbook_id": WORKBOOK, "binding": _input_binding(), "values": _input_values(), "alias": "actual"},
    )
    assert status == 400
    assert payload["error"]["message"] == "a child session cannot import new Excel snapshots"


def test_context_endpoint_supplies_authorized_successful_finance_runs(tmp_path):
    app, _, token = _app(tmp_path)
    status, imported = _import(app, token, values=_input_values("revenue", "120.50"))
    assert status == 200, imported
    status, run_payload = _call(
        app,
        token,
        "POST",
        "/api/run-metric",
        {
            "workbook_id": WORKBOOK,
            "spec": {
                "metric": {
                    "kind": "account_total",
                    "dimensions": ["organization", "period"],
                    "accounts": ["revenue"],
                }
            },
        },
    )
    assert status == 200, run_payload
    assert Decimal(run_payload["run"]["result"]["rows"][0]["amount"]) == Decimal("120.50")

    status, context = _call(app, token, "GET", "/api/context")
    assert status == 200
    assert [run["id"] for run in context["finance"]["runs"]] == [run_payload["run"]["id"]]



def test_management_pnl_without_accounts_filter_returns_full_profit(tmp_path):
    app, _, token = _app(tmp_path)
    values = [
        ["management_account", "amount", "organization", "period", "currency", "unit", "scenario"],
        ["revenue", "120", "HQ", "2026-08", "CNY", "yuan", "actual"],
        ["cost", "70", "HQ", "2026-08", "CNY", "yuan", "actual"],
        ["expense", "20", "HQ", "2026-08", "CNY", "yuan", "actual"],
    ]
    status, imported = _import(app, token, values=values)
    assert status == 200, imported
    status, run_payload = _call(
        app,
        token,
        "POST",
        "/api/run-metric",
        {
            "workbook_id": WORKBOOK,
            "spec": {
                "metric": {
                    "kind": "management_pnl",
                    "dimensions": ["organization", "period"],
                }
            },
        },
    )
    assert status == 200, run_payload
    row = run_payload["run"]["result"]["rows"][0]
    assert Decimal(row["revenue"]) == Decimal("120")
    assert Decimal(row["cost"]) == Decimal("70")
    assert Decimal(row["expense"]) == Decimal("20")
    assert Decimal(row["profit"]) == Decimal("30")

def test_preview_uses_registered_baseline_with_formula_hash_and_ignores_caller_override(tmp_path):
    app, _, token = _app(tmp_path)
    baseline = {"H2": _cell("H2", "=SUM(A1:A2)", "string", "General", "=SUM(A1:A2)")}
    status, payload = _call(app, token, "POST", "/api/register-bindings", {"workbook_id": WORKBOOK, "bindings": [_output_binding(baseline_cells=baseline)]})
    assert status == 200, payload

    current_same_value_changed_formula = {"H2": _cell("H2", "=SUM(A1:A2)", "string", "General", "=SUM(A1:A3)")}
    status, preview_payload = _call(
        app,
        token,
        "POST",
        "/api/preview-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "writes": [{"address": "H2", "field": "amount", "value": "30", "baseline_hash": "caller-cannot-clear-conflict"}],
            "current_cells": current_same_value_changed_formula,
        },
    )
    assert status == 200, preview_payload
    preview = preview_payload["preview"]
    assert preview["cells"][0]["conflict"] is True
    assert preview["cells"][0]["baseline_hash"] != "caller-cannot-clear-conflict"


def test_apply_validates_current_cells_and_returns_only_selected_cell_writes(tmp_path):
    app, _, token = _app(tmp_path)
    current = {
        "H2": _cell("H2", "old"),
        "I2": _cell("I2", "keep me"),
        "J2": _cell("J2", "00123"),
    }
    status, payload = _call(app, token, "POST", "/api/register-bindings", {"workbook_id": WORKBOOK, "bindings": [_output_binding(baseline_cells=current)]})
    assert status == 200, payload
    status, preview_payload = _call(
        app,
        token,
        "POST",
        "/api/preview-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "writes": [
                {"address": "H2", "field": "amount", "value": "12.30"},
                {"address": "I2", "field": "comment", "value": "=literal"},
                {"address": "J2", "field": "identifier", "value": "00123"},
            ],
            "current_cells": current,
        },
    )
    assert status == 200, preview_payload
    preview = preview_payload["preview"]
    assert preview["conflicts"] == []
    assert preview["cells"][0]["new_value"] == 12.3
    assert preview["cells"][1]["cell_type"] == "text"
    assert preview["cells"][1]["number_format"] == "@"
    assert preview["cells"][2]["new_value"] == "00123"
    assert preview["cells"][2]["number_format"] == "@"

    changed = {**current, "H2": _cell("H2", "manager edit")}
    status, payload = _call(
        app,
        token,
        "POST",
        "/api/apply-output",
        {"workbook_id": WORKBOOK, "binding_id": "out", "preview_id": preview["id"], "current_cells": changed},
    )
    assert status == 400
    assert payload["error"]["message"] == "cell changed since preview: H2"

    status, applied = _call(
        app,
        token,
        "POST",
        "/api/apply-output",
        {"workbook_id": WORKBOOK, "binding_id": "out", "preview_id": preview["id"], "current_cells": current, "resolutions": {"I2": "keep"}},
    )
    assert status == 200, applied
    assert applied["applied"] == [
        {"address": "H2", "field": "amount", "value": 12.3, "cell_type": "number", "number_format": "General"},
        {"address": "J2", "field": "identifier", "value": "00123", "cell_type": "text", "number_format": "@"},
    ]
    assert [cell["address"] for cell in applied["kept"]] == ["I2"]



def test_apply_selected_addresses_keep_unselected_preview_cells(tmp_path):
    app, _, token = _app(tmp_path)
    current = {
        "H2": _cell("H2", "old amount"),
        "I2": _cell("I2", "old comment"),
        "J2": _cell("J2", "old id"),
    }
    _call(app, token, "POST", "/api/register-bindings", {"workbook_id": WORKBOOK, "bindings": [_output_binding(baseline_cells=current)]})
    status, preview_payload = _call(
        app,
        token,
        "POST",
        "/api/preview-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "writes": [
                {"address": "H2", "field": "amount", "value": "12.30"},
                {"address": "I2", "field": "comment", "value": "manager note"},
                {"address": "J2", "field": "identifier", "value": "00123"},
            ],
            "current_cells": current,
        },
    )
    assert status == 200, preview_payload
    preview = preview_payload["preview"]

    status, applied = _call(
        app,
        token,
        "POST",
        "/api/apply-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "preview_id": preview["id"],
            "current_cells": current,
            "selected_addresses": ["H2"],
        },
    )
    assert status == 200, applied
    assert [cell["address"] for cell in applied["applied"]] == ["H2"]
    assert [cell["address"] for cell in applied["kept"]] == ["I2", "J2"]

    status, payload = _call(
        app,
        token,
        "POST",
        "/api/apply-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "preview_id": preview["id"],
            "current_cells": current,
            "selected_addresses": ["Z9"],
        },
    )
    assert status == 400
    assert payload["error"]["message"] == "selected address is not in preview: Z9"


def test_output_ack_updates_only_confirmed_baselines_for_next_preview(tmp_path):
    app, _, token = _app(tmp_path)
    initial = {"H2": _cell("H2", 0, "Double"), "I2": _cell("I2", "keep") }
    _call(app, token, "POST", "/api/register-bindings", {"workbook_id": WORKBOOK, "bindings": [_output_binding(baseline_cells=initial)]})

    status, first_preview_payload = _call(
        app,
        token,
        "POST",
        "/api/preview-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "writes": [
                {"address": "H2", "field": "amount", "value": "30"},
                {"address": "I2", "field": "comment", "value": "kept"},
            ],
            "current_cells": initial,
        },
    )
    assert status == 200, first_preview_payload
    first_preview = first_preview_payload["preview"]
    status, applied = _call(
        app,
        token,
        "POST",
        "/api/apply-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "preview_id": first_preview["id"],
            "current_cells": initial,
            "selected_addresses": ["H2"],
        },
    )
    assert status == 200, applied
    assert [cell["address"] for cell in applied["applied"]] == ["H2"]

    status, rejected = _call(
        app,
        token,
        "POST",
        "/api/ack-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "preview_id": first_preview["id"],
            "cells": [_cell("I2", "kept")],
        },
    )
    assert status == 400
    assert rejected["error"]["message"] == "ack address was not authorized for write: I2"

    status, mismatch = _call(
        app,
        token,
        "POST",
        "/api/ack-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "preview_id": first_preview["id"],
            "cells": [_cell("H2", 31, "Double")],
        },
    )
    assert status == 400
    assert mismatch["error"]["message"] == "ack cell value does not match authorized write: H2"

    written_30 = {"H2": _cell("H2", 30, "Double"), "I2": _cell("I2", "keep")}
    status, ack = _call(
        app,
        token,
        "POST",
        "/api/ack-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "preview_id": first_preview["id"],
            "cells": [written_30["H2"]],
        },
    )
    assert status == 200, ack
    assert ack["updated_baselines"] == ["H2"]

    status, second_preview_payload = _call(
        app,
        token,
        "POST",
        "/api/preview-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "writes": [{"address": "H2", "field": "amount", "value": "40"}],
            "current_cells": written_30,
        },
    )
    assert status == 200, second_preview_payload
    assert second_preview_payload["preview"]["conflicts"] == []

    manager_changed = {"H2": _cell("H2", 35, "Double")}
    status, conflict_payload = _call(
        app,
        token,
        "POST",
        "/api/preview-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "writes": [{"address": "H2", "field": "amount", "value": "40"}],
            "current_cells": manager_changed,
        },
    )
    assert status == 200, conflict_payload
    assert conflict_payload["preview"]["cells"][0]["conflict"] is True

def test_long_decimal_is_written_as_text_to_preserve_excel_precision(tmp_path):
    app, _, token = _app(tmp_path)
    current = {"H2": _cell("H2", "")}
    _call(app, token, "POST", "/api/register-bindings", {"workbook_id": WORKBOOK, "bindings": [_output_binding(baseline_cells=current)]})
    status, payload = _call(
        app,
        token,
        "POST",
        "/api/preview-output",
        {
            "workbook_id": WORKBOOK,
            "binding_id": "out",
            "writes": [{"address": "H2", "field": "amount", "value": "12345678901234567890.1234"}],
            "current_cells": current,
        },
    )
    assert status == 200, payload
    cell = payload["preview"]["cells"][0]
    assert cell["cell_type"] == "text"
    assert cell["number_format"] == "@"
    assert cell["new_value"] == "12345678901234567890.1234"


def test_workbook_identity_and_range_scope_are_enforced(tmp_path):
    app, _, token = _app(tmp_path)
    current = {"H2": _cell("H2", "")}
    _call(app, token, "POST", "/api/register-workbook", {"workbook_id": OTHER_WORKBOOK, "name": "other.xlsx", "host": {}})
    _call(app, token, "POST", "/api/register-bindings", {"workbook_id": WORKBOOK, "bindings": [_output_binding(baseline_cells=current)]})
    status, payload = _call(
        app,
        token,
        "POST",
        "/api/preview-output",
        {"workbook_id": OTHER_WORKBOOK, "binding_id": "out", "writes": [{"address": "H2", "field": "amount", "value": "1"}], "current_cells": current},
    )
    assert status == 400
    assert payload["error"]["message"] == "binding is not registered"

    status, payload = _call(
        app,
        token,
        "POST",
        "/api/preview-output",
        {"workbook_id": WORKBOOK, "binding_id": "out", "writes": [{"address": "Z9", "field": "amount", "value": "1"}], "current_cells": {"Z9": _cell("Z9", "")}},
    )
    assert status == 400
    assert payload["error"]["message"] == "write target outside output binding: Z9"


def test_bridge_state_integrity_and_body_boundaries(tmp_path):
    app, task, token = _app(tmp_path)
    state_path = task.root / "analysis" / "excel_bridge" / "state.json"
    raw = json.loads(state_path.read_text(encoding="utf8"))
    raw["workbooks"][WORKBOOK]["name"] = "tampered.xlsx"
    state_path.write_text(json.dumps(raw), encoding="utf8")
    status, payload = _call(app, token, "GET", "/api/context")
    assert status == 400
    assert payload["error"]["message"] == "bridge state integrity check failed"

    app2, _, token2 = _app(tmp_path / "other")
    status, payload = _call(app2, token2, "POST", "/api/register-workbook", {"workbook_id": WORKBOOK, "host": {"x": "y"}})
    assert status == 200, payload
    status, _, body = app2.handle("POST", "/api/register-workbook", {"Authorization": f"Bearer {token2}"}, b"{" + b"x" * (8 * 1024 * 1024 + 1) + b"}")
    assert status == 400
    assert json.loads(body)["error"]["message"] == "request body is too large"


def test_cli_add_parsers_dispatch_supports_root_integration(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="Excel bridge")
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("f" * 64, encoding="utf8")

    assert foundry_cli.main(["--var", str(root), "excel-bridge-manifest", "--port", "9443"]) == 0
    assert "https://localhost:9443/taskpane.html" in capsys.readouterr().out

    assert foundry_cli.main([
        "--var", str(root), "excel-bridge-token", "--task", task.id, "--session", "excel", "--secret-file", str(secret_file)
    ]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["task_id"] == task.id
    assert out["session_id"] == "excel"
    assert any(row["session_id"] == "excel" and row["role"] == "analysis" for row in TaskStore(root).get(task.id).sessions())


def test_cli_secret_comes_from_env_or_file_not_argv(tmp_path, monkeypatch, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="Excel bridge")
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("f" * 64, encoding="utf8")
    rc = main(["token", "--var", str(root), "--task", task.id, "--session", "excel", "--secret-file", str(secret_file)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["task_id"] == task.id
    assert out["session_id"] == "excel"
    assert "token" in out

    monkeypatch.setenv("FOUNDRY_EXCEL_BRIDGE_SECRET", "e" * 64)
    rc = main(["token", "--var", str(root), "--task", task.id, "--session", "excel"])
    assert rc == 0

    with pytest.raises(SystemExit):
        main(["token", "--var", str(root), "--task", task.id, "--session", "excel", "--secret", "nope"])


def test_static_manifest_is_localhost_https_and_icon_png_packaged_from_resources(tmp_path):
    app, _, _ = _app(tmp_path)
    status, headers, body = app.handle("GET", "/manifest.xml?port=9443", {}, b"")
    assert status == 200
    assert headers["Content-Type"].startswith("application/xml")
    text = body.decode("utf8")
    assert "https://localhost:9443/taskpane.html" in text
    assert "https://localhost:9443/icon.png" in text
    assert '<Group id="Foundry.Group">' in text
    assert text.index('<Label resid="Foundry.GroupLabel"/>') < text.index('<Icon>') < text.index('<Control xsi:type="Button" id="Foundry.Open">')
    assert text.count('<bt:Image size="16" resid="Icon.16"/>') == 2
    assert "http://localhost" not in text
    assert "PowerQuery" not in text
    assert "https://localhost:9443/taskpane.html" in generate_manifest(port=9443)

    status, headers, body = app.handle("GET", "/icon.png", {}, b"")
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert body.startswith(b"\x89PNG")

    status, headers, body = app.handle("GET", "/taskpane.html", {}, b"")
    assert status == 200
    assert b"\xe6\x9c\xac\xe5\x9c\xb0\xe6\xa1\xa5\xe8\xbf\x9e\xe6\x8e\xa5\xe4\xbb\xa4\xe7\x89\x8c" in body



def test_taskpane_selection_and_visible_status_ui_are_regression_guarded():
    html = Path("excel-addin/taskpane.html").read_text(encoding="utf8")
    css = Path("excel-addin/taskpane.css").read_text(encoding="utf8")
    js = Path("excel-addin/taskpane.js").read_text(encoding="utf8")

    assert '<div id="status" class="status" role="status" aria-live="polite">' in html
    assert '<label for="bindingList">当前绑定区域</label>' in html
    assert '<select id="bindingList"></select>' in html
    assert '<button id="applyOutput" disabled>应用选中单元格</button>' in html
    assert 'id="bindingList" size=' not in html
    assert '--fnd-ink: #111827;' in css
    assert '--fnd-muted: #4b5563;' in css
    assert 'border-color: var(--fnd-outline);' in css
    assert 'GrayText' not in css
    assert 'CanvasText' not in css
    assert 'function chooseSelectValue' in js
    assert 'state.selectedBindingId = id;' in js
    assert 'state.selectedRunId = result.run.id;' in js
    assert '运行结果缺少输出列' in js
    assert 'selected_addresses: selectedAddresses' in js
    assert 'api("/api/ack-output"' in js
    assert 'ackCells' in js
    assert 'function clearPreview(message = "")' in js
    assert 'state.previewGeneration += 1;' in js
    assert 'if (generation !== state.previewGeneration)' in js
    assert '$("applyOutput").disabled = true;' in js
    assert '$("applyOutput").disabled = false;' in js
    assert 'clearPreview("绑定区域已切换，请重新预览写入。")' in js
    assert 'clearPreview("运行结果已切换，请重新预览写入。")' in js
    assert 'setStatus(message, "error")' in js
    assert 'fieldPreset").value === "output"' in js
    assert 'id="metricAccountsWrap"' in html
    assert '$("metricAccountsWrap").hidden = !simple || !accountTotal;' in js
    assert 'if (spec.metric.kind === "account_total")' in js
    assert 'spec.metric.accounts = splitCsv($("metricAccounts").value);' in js
    management_block = js[js.index('function metricSpec'):js.index('async function runMetric')]
    assert 'accounts: splitCsv' not in management_block
    readme = Path("excel-addin/README.md").read_text(encoding="utf8")
    assert "tools/verify_excel_host.py" in readme
    assert "B2=130" in readme and "H2=80" in readme

def test_development_assets_match_packaged_resource_mirror():
    for name in ["taskpane.html", "taskpane.js", "taskpane.css", "manifest.xml", "README.md", "icon.png", "icon.svg"]:
        assert (Path("excel-addin") / name).read_bytes() == (Path("foundry/resources/excel-addin") / name).read_bytes()
