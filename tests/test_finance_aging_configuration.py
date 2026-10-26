"""A cutoff date is not a source period, and custom buckets have a typed contract."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from foundry.errors import FoundryError
from foundry.finance_scenarios import compute_receivables_aging
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


SCOPE = {"ledger": "L", "organization": "O", "currency": "CNY", "unit": "万元"}
INVOICES = [
    {**SCOPE, "id": "B13-030", "issue_date": "2026-08-01", "due_date": "2026-08-31", "amount": "40"},
    {**SCOPE, "id": "B13-031", "issue_date": "2026-08-01", "due_date": "2026-08-30", "amount": "60"},
]
BUCKETS = [{"name": "0-30天", "min": 0, "max": 30}, {"name": "31-60天", "min": 31, "max": 60}]


@pytest.mark.parametrize("buckets", [
    [{"label": "0-30天", "min_days": 0, "max_days": 30}],
    [{"name": "a", "min": 0, "max": 30, "label": "conflict"}],
    [{"name": "a", "min": True, "max": 30}],
    [{"name": "a", "min": "0", "max": 30}],
    [{"name": "a", "min": 0, "max": 30.5}],
    [{"name": "a", "min": 1, "max": 30}],
    [{"name": "a", "min": 0, "max": 30}, {"name": "b", "min": 30, "max": 60}],
    [{"name": "a", "min": 0, "max": 30}, {"name": "b", "min": 32, "max": 60}],
    [{"name": "a", "min": 0, "max": 30}, {"name": "a", "min": 31, "max": None}],
    [{"name": "not_due", "min": 0, "max": None}],
    [],
    [{"name": "a", "min": 0, "max": None}, {"name": "b", "min": 31, "max": 60}],
    [{"name": "a", "min": 0, "max": -1}],
    [{"name": " a ", "min": 0, "max": None}],
])
def test_malformed_buckets_are_rejected_even_with_no_source_rows(buckets):
    with pytest.raises(FoundryError, match="buckets"):
        compute_receivables_aging([], as_of="2026-09-30", scope=SCOPE, buckets=buckets)


def test_original_30_31_day_boundary_uses_cutoff_without_inventing_a_period():
    result = compute_receivables_aging(INVOICES, as_of="2026-09-30", scope=SCOPE, buckets=BUCKETS)
    assert [(row["invoice_id"], row["overdue_days"], row["bucket"], row["bucket_label"], row["open_amount"])
            for row in result["detail_rows"]] == [
                ("B13-030", 30, "0-30", "0-30天", "40"), ("B13-031", 31, "31-60", "31-60天", "60")]
    assert len(result["detail_rows"]) == 2


def test_period_filter_on_unperiodized_invoices_is_not_an_empty_zero_result():
    with pytest.raises(FoundryError, match="scope.period.*as_of"):
        compute_receivables_aging(INVOICES, as_of="2026-09-30", scope={**SCOPE, "period": "2026-09-30"})


def test_explicit_source_period_filter_still_selects_only_its_own_invoices():
    invoices = [{**INVOICES[0], "period": "2026-08"}, {**INVOICES[1], "period": "2026-09"}]
    result = compute_receivables_aging(invoices, as_of="2026-09-30", scope={**SCOPE, "period": "2026-08"})
    assert [row["invoice_id"] for row in result["detail_rows"]] == ["B13-030"]


def test_invalid_buckets_fail_before_scenario_persistence(tmp_path):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="账龄配置边界"))
    path = tmp_path / "invoices.json"
    path.write_text(json.dumps(INVOICES))
    dataset = service.analysis.add_dataset(path, name="invoices")
    context = service.save_context({"bindings": {"invoices": dataset["id"]}, "scopes": {"invoices": SCOPE}})
    with pytest.raises(FoundryError, match="buckets.*name.*min.*max"):
        service.save_scenario({"context_id": context["id"], "kind": "receivables_aging", "inputs": {
            "as_of": "2026-09-30", "scope": SCOPE,
            "buckets": [{"label": "0-30天", "min_days": 0, "max_days": 30}]}})
    assert service._list("scenarios") == []


def test_real_aging_run_diagnoses_missing_period_and_keeps_failed_run_after_repair(tmp_path):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="账龄真实保存运行"))
    path = tmp_path / "invoices.json"
    path.write_text(json.dumps(INVOICES))
    dataset = service.analysis.add_dataset(path, name="invoices")
    context = service.save_context({"bindings": {"invoices": dataset["id"]}, "scopes": {"invoices": SCOPE}})
    bad = service.save_scenario({"context_id": context["id"], "kind": "receivables_aging", "inputs": {
        "as_of": "2026-09-30", "scope": {**SCOPE, "period": "2026-09-30"}}})
    failed = service.run_scenario({"scenario_id": bad["id"]})
    assert failed["execution_status"] == "failed"
    assert "scope.period" in failed["error"] and "as_of" in failed["error"]
    failed_path = service.analysis._object_path("runs", failed["id"])
    before = failed_path.read_bytes()
    corrected = service.save_scenario({"parent_id": bad["id"], "changes": {"scope": SCOPE, "buckets": BUCKETS}})
    run = service.run_scenario({"scenario_id": corrected["id"]})
    assert run["execution_status"] == "succeeded", run.get("error")
    assert [(row["overdue_days"], row["bucket"], row["bucket_label"], row["open_amount"])
            for row in run["result"]["detail_rows"]] == [
        (30, "0-30", "0-30天", "40"), (31, "31-60", "31-60天", "60")]
    assert all(row["source_rows"] for row in run["result"]["detail_rows"])
    assert failed_path.read_bytes() == before


def test_mcp_and_registered_plugin_advertise_and_validate_canonical_bucket_schema(tmp_path):
    from foundry.finance_mcp import _tools

    root = Path(__file__).resolve().parents[1]
    mcp = next(tool for tool in _tools() if tool["name"] == "save_scenario")
    inputs = mcp["inputSchema"]["properties"]["inputs"]["properties"]
    assert "source period" in inputs["as_of"]["description"]
    ajv = root / "app/extra/dsh/node_modules/ajv/dist/ajv.js"
    assert ajv.is_file(), "Check schema through the existing registered runtime validator"
    script = tmp_path / "bucket-contract.mjs"
    script.write_text(f"""
import {{ FINANCE_TOOLS }} from {json.dumps((root / 'dsh-plugin/finance-tools.js').as_uri())};
import Ajv from {json.dumps(ajv.as_uri())};
const plugin = FINANCE_TOOLS.finance_scenario_save.parameters.properties.spec.properties.inputs.properties.buckets;
const schemas = [plugin, {json.dumps(inputs['buckets'])}];
const samples = {json.dumps([BUCKETS, [{'name': 'all', 'min': 0, 'max': None}], [{'label': '0-30', 'min_days': 0, 'max_days': 30}], [{'name': 'a', 'min': False}], [], [{'name': 'a', 'min': 0, 'extra': 1}], [{'name': 'a', 'min': 0, 'max': 1.2}]])};
process.stdout.write(JSON.stringify(schemas.map(schema => {{
  const validate = new Ajv({{strict:false}}).compile(schema);
  return samples.map(sample => validate(sample));
}})));
""")
    result = subprocess.run([shutil.which("node") or "node", str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [[True, True, False, False, False, False, False]] * 2
