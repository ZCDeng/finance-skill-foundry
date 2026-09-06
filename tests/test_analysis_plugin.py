"""The new preset publishes real analysis interfaces without widening legacy seats."""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "dsh-plugin"
NODE = shutil.which("node")
PROFILE = json.loads((PLUGIN / "package.json").read_text())["dsh"]["foundry"]["profiles"]["analysis"]


def _node(tmp_path: Path, body: str, env: dict[str, str] | None = None):
    if not NODE:
        pytest.skip("node is unavailable")
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        f'import {{ apply, definitions, allowlist }} from "{(PLUGIN / "analysis.js").as_uri()}";\n'
        + body
    )
    result = subprocess.run([NODE, str(driver)], text=True, capture_output=True,
                            env={**os.environ, **(env or {})}, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_analysis_registers_its_own_complete_scope(tmp_path: Path):
    result = _node(tmp_path, """
const seen = [], restrictions = [], guards = [];
apply({on: () => {}, tools: {register: (d) => seen.push(d), restrict: (r) => restrictions.push(r),
  schemas: () => [{name: 'create'}, {name: 'univer_execute'}], guard: (g) => guards.push(g)}});
process.stdout.write(JSON.stringify({names: seen.map((d) => d.name), restrictions,
  guards: [guards[0]({name: 'analysis-run'}) ?? null, guards[0]({name: 'late-shell'})],
  descriptions: Object.fromEntries(seen.map((d) => [d.name, d.description]))}));
""")
    assert result["names"] == PROFILE["tools"]
    assert result["restrictions"] == [{"deny": ["create", "univer_execute"]}]
    assert result["guards"] == [None, "analysis cannot execute late-shell"]
    assert {"create", "import", "lock", "query-locked", "bash", "read", "univer_execute"}.isdisjoint(
        PROFILE["tools"] + PROFILE["harnessTools"]
    )
    assert "SQL" in result["descriptions"]["analysis-save"]
    assert "不会自动变成公式" in result["descriptions"]["analysis-save"]
    assert "left_keys" in result["descriptions"]["analysis-save"]


def test_analysis_save_relationship_schema_names_actual_join_contract(tmp_path: Path):
    result = _node(tmp_path, """
const save = definitions().find((d) => d.name === 'analysis-save');
const relationship = save.parameters.properties.spec.properties.relationships.items;
process.stdout.write(JSON.stringify({
  required: relationship.required,
  additionalProperties: relationship.additionalProperties,
  properties: Object.keys(relationship.properties),
  cardinality: relationship.properties.cardinality.enum,
  hasEmptyItems: JSON.stringify(save.parameters).includes('"relationships":{"type":"array","items":{}'),
}));
""")
    assert result["required"] == ["left", "right", "left_keys", "right_keys", "cardinality"]
    assert result["additionalProperties"] is False
    assert {"source", "target", "on", "keys"}.isdisjoint(result["properties"])
    assert result["cardinality"] == ["one-to-one", "one-to-many", "many-to-one", "many-to-many"]
    assert result["hasEmptyItems"] is False


def test_analysis_draft_claim_schema_names_basis_and_zero_based_rows(tmp_path: Path):
    result = _node(tmp_path, """
const draft = definitions().find((d) => d.name === 'analysis-draft');
const claim = draft.parameters.properties.spec.properties.claims.items;
process.stdout.write(JSON.stringify({
  required: claim.required,
  basis: claim.properties.basis.enum,
  rowMinimum: claim.properties.row.minimum,
  rowType: claim.properties.row.type,
  hasEmptyItems: JSON.stringify(draft.parameters).includes('"claims":{"type":"array","items":{"type":"object"}'),
}));
""")
    assert result["required"] == ["basis"]
    assert result["basis"] == [
        "source_fact",
        "calculation",
        "external_reference",
        "user_assumption",
        "professional_judgment",
    ]
    assert result["rowType"] == "integer"
    assert result["rowMinimum"] == 0
    assert result["hasEmptyItems"] is False


def test_analysis_executes_real_argument_shapes_and_session_only_binding(tmp_path: Path):
    log = tmp_path / "argv.jsonl"
    shim = tmp_path / "foundry"
    shim.write_text("#!/usr/bin/env python3\nimport json,os,sys\n"
                    "with open(os.environ['ANALYSIS_ARGV_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                    "print(json.dumps({'result': {'amount': '9007199254740993.01'}}))\n")
    shim.chmod(0o755)
    result = _node(tmp_path, """
const tools = Object.fromEntries(definitions().map((d) => [d.name, d]));
const exec = {agent: {id: 'analysis-session'}};
const inputs = {
 'analysis-state': {},
 'analysis-refresh': {},
 'dataset-add': {path: '/task/uploads/actual.csv', name: '实际', meta: {currency: 'CNY'}},
 'dataset-read': {dataset: 'snapshot-1'},
 'method-resource': {skill: 'variance-analysis', resource: 'FOUNDRY.md'},
 'analysis-save': {spec: {question: '差异', sql: 'SELECT amount FROM actual', bindings: {actual: 'snapshot-1'}}},
 'analysis-run': {analysis: 'analysis-1'},
 'analysis-script': {spec: {language: 'python', code: "print('done')", bindings: {actual: 'snapshot-1'}}},
 'analysis-script-start': {spec: {code: "print('done')", bindings: {actual: 'snapshot-1'}}},
 'analysis-jobs': {},
 'analysis-job-output': {job: 'job-1'},
 'analysis-draft': {spec: {title: '经营分析', body: '收入', run_ids: ['run-1']}},
 'analysis-export': {draft: 'draft-1', format: 'xlsx'},
 'analysis-method-save': {analysis: 'analysis-1', name: '经营分析'},
 'analysis-method-apply': {method: 'method-1', bindings: {actual: 'snapshot-2'}, parameters: ['1.23'], question: '下一期'},
 'list_finance_context': {},
 'finance_context_save': {spec: {bindings: {actual: 'snapshot-1'}, scopes: {actual: {ledger: 'L1', currency: 'CNY', unit: '元'}}}},
 'finance_map_save': {spec: {rows: [{account_code: '001', management_account: 'revenue'}]}},
 'run_metric': {spec: {context_id: 'context-1', metric: {kind: 'management_pnl'}}},
 'explain_variance': {spec: {context_id: 'context-1'}},
 'drilldown_fact': {spec: {run_id: 'run-1', row: 0}},
 'prepare_explanation': {spec: {run_ids: ['run-1'], materiality: {absolute: '10'}}},
 'validate_explanation': {spec: {body: '收入 {{fact:abc}}', run_ids: ['run-1'], fact_ids: ['abc']}},
 'save_explanation_draft': {spec: {body: '经理判断', claims: [{basis: 'professional_judgment', reason: '客户反馈'}]}},
 'finance_background_save': {spec: {text: '客户结构变化', basis: 'professional_judgment', scope: {ledger: 'L1', organization: 'O1'}, effective_from: '2026-09-01'}},
 'finance_background_list': {spec: {scope: {ledger: 'L1', organization: 'O1'}, as_of: '2026-09-30'}},
 'finance_scenario_save': {spec: {context_id: 'context-1', kind: 'cash_13_weeks', inputs: {opening_cash: '50'}, label: '基准'}},
 'finance_scenario_run': {spec: {scenario_id: 'scenario-1'}},
 'finance_source_list': {},
 'finance_source_refresh': {spec: {path: '/task/uploads/new.csv', scope: {source_id: 'file', tenant_id: 'T1', ledger_id: 'L1', organization_id: 'O1', period: '2026-09', currency: 'CNY', cutoff_at: '2026-09-06'}}},
 'workbook_inspect': {spec: {dataset_id: 'snapshot-1'}},
 'workbook_bind': {spec: {dataset_id: 'snapshot-1', source: {kind: 'named_range', name: 'Result'}, fields: [{name: 'amount', policy: 'amount'}]}},
 'workbook_read': {spec: {binding_id: 'binding-1'}},
 'workbook_preview': {spec: {binding_id: 'binding-1', writes: [{cell: 'A1', field: 'amount', value: '10'}]}},
 'workbook_apply': {spec: {patch_id: 'patch-1', resolutions: {A1: 'keep'}}},
 'analysis_requirements_save': {spec: {context_id: 'context-1', question: '解释利润', items: [{id: 'profit', metric: 'profit'}]}},
 'analysis_requirements_list': {spec: {context_id: 'context-1'}},
};
const results = [];
for (const [name, input] of Object.entries(inputs)) results.push(await tools[name].execute(input, exec));
process.stdout.write(JSON.stringify(results));
""", {"FOUNDRY_VAR": str(tmp_path / "var"), "FOUNDRY_BIN": str(shim),
       "FOUNDRY_TASK": "wrong-ambient-task", "ANALYSIS_ARGV_LOG": str(log)})
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    direct = [name for name in PROFILE["tools"] if name not in {"analysis-delegate", "analysis-job-cancel", "analysis-job-retry"}]
    assert len(rows) == len(direct)
    aliases = {"analysis-jobs": "analysis-job-list", "analysis-job-output": "analysis-job-show"}
    for row, tool in zip(rows, direct):
        assert row[:5] == ["--var", str(tmp_path / "var"), "--session", "analysis-session", aliases.get(tool, tool.replace("_", "-"))]
        assert "--task" not in row
    assert rows[4][4:] == ["method-resource", "--skill", "variance-analysis", "--resource", "FOUNDRY.md"]
    assert json.loads(rows[5][6])["bindings"] == {"actual": "snapshot-1"}
    method_call = next(row for row in rows if row[4] == "analysis-method-apply")
    assert method_call[5:] == ["--method", "method-1", "--bindings", '{"actual":"snapshot-2"}',
                            "--parameters", '["1.23"]', "--question", "下一期"]
    for value in result:
        assert json.loads(value["stdout"])["result"]["amount"] == "9007199254740993.01"
        assert value["filed"] == []


def test_analysis_refuses_unbound_calls_and_model_supplied_context(tmp_path: Path):
    result = _node(tmp_path, """
const tools = Object.fromEntries(definitions().map((d) => [d.name, d]));
const outcomes = [];
for (const [name, input, exec] of [
 ['analysis-state', {}, {}],
 ['analysis-state', {task: 'spoofed'}, {agent: {id: 'session'}}],
 ['analysis-run', {}, {agent: {id: 'session'}}],
]) {
 try { await tools[name].execute(input, exec); outcomes.push({accepted: true}); }
 catch (error) { outcomes.push({message: error.message, refused: error.refused}); }
}
process.stdout.write(JSON.stringify(outcomes));
""", {"FOUNDRY_TASK": "must-not-be-a-fallback"})
    assert result[0]["refused"] is True
    assert "registered session" in result[0]["message"]
    assert "未声明参数 task" in result[1]["message"]
    assert "缺少必填参数 analysis" in result[2]["message"]


def test_analysis_refuses_string_arguments_without_expanding_characters(tmp_path: Path):
    result = _node(tmp_path, """
const tools = Object.fromEntries(definitions().map((d) => [d.name, d]));
try {
  await tools['analysis-run'].execute(JSON.stringify({analysis: 'a'}), {agent: {id: 'session'}});
  process.stdout.write(JSON.stringify({accepted: true}));
} catch (error) {
  process.stdout.write(JSON.stringify({message: error.message, refused: error.refused}));
}
""", {"FOUNDRY_VAR": str(tmp_path / "var"), "FOUNDRY_BIN": "/bin/false"})
    assert result["refused"] is True
    assert "参数必须为对象" in result["message"]
    assert "未声明参数" not in result["message"]


def test_analysis_preset_installs_with_harness_and_wheel_resource():
    from foundry.harness import preset_ids

    assert "analysis" in preset_ids()
    rows = yaml.safe_load((PLUGIN / "presets" / "analysis" / "agent.cordis.yml").read_text())
    names = {row["name"] for row in rows}
    assert "finance-skill-foundry-dsh/analysis" in names
    assert {"@deepseek-ai/dsh-tool-skill", "@deepseek-ai/dsh-tool-web",
            "@deepseek-ai/dsh-tool-ask-user"} <= names
    assert not {"finance-skill-foundry-dsh/period-scope", "finance-skill-foundry-dsh/f3-scope"} & names
    mirror = ROOT / "foundry" / "resources" / "dsh-plugin"
    for relative in ("analysis.js", "analysis-runtime.js", "finance-tools.js", "index.js", "package.json", "presets/analysis/agent.cordis.yml",
                     "presets/analysis/preset.yml"):
        assert (PLUGIN / relative).read_bytes() == (mirror / relative).read_bytes(), relative


def test_analysis_plugin_executes_real_financial_analysis_and_isolated_script(tmp_path: Path):
    """The model-facing wrapper crosses the real CLI/session/broker boundaries."""
    from decimal import Decimal
    from openpyxl import load_workbook
    from foundry.analysis import AnalysisStore
    from foundry.task import TaskStore

    executable = ROOT / ".venv" / "bin" / "foundry"
    if not executable.is_file():
        pytest.skip("the local Foundry CLI entry point is unavailable")
    var = tmp_path / "var"
    task = TaskStore(var).create(title="收入分析")
    task.record_session("plugin-e2e", role="analysis")
    upload = task.root / "analysis" / "uploads" / "actual.csv"
    upload.parent.mkdir(parents=True)
    upload.write_text("region,revenue\nNorth,70.01\nSouth,30.02\n")
    result = _node(tmp_path, """
const tools = Object.fromEntries(definitions().map((d) => [d.name, d]));
const exec = {agent: {id: 'plugin-e2e'}};
const call = async (name, input) => JSON.parse((await tools[name].execute(input, exec)).stdout);
const dataset = await call('dataset-add', {path: process.env.FOUNDRY_TEST_UPLOAD, name: '实际收入'});
const revision = await call('analysis-save', {spec: {
 question: '北区收入', sql: 'SELECT SUM(revenue) AS revenue FROM actual WHERE region = ?',
 parameters: ['North'], bindings: {actual: dataset.id}, metrics: [{name: 'revenue', currency: 'CNY'}]
}});
const run = await call('analysis-run', {analysis: revision.id});
const draft = await call('analysis-draft', {spec: {
 title: '北区收入分析', body: '北区收入 70.01，口径来自实际收入资料。', run_ids: [run.id],
 claims: [{basis: 'calculation', run_id: run.id, row: 0, column: 'revenue', value: '70.01'}]
}});
const md = await call('analysis-export', {draft: draft.id, format: 'md'});
const xlsx = await call('analysis-export', {draft: draft.id, format: 'xlsx'});
const script = await call('analysis-script', {spec: {bindings: {actual: dataset.id}, code:
 `import os, json\nfrom pathlib import Path\nfrom decimal import Decimal\ndata = json.loads((Path(os.environ['FOUNDRY_INPUTS']) / 'actual.json').read_text())\nvalue = sum(Decimal(row['revenue']) for row in data['rows'] if row['region'] == 'North')\nPath('summary.txt').write_text(str(value))\nprint(value)`
}});
const state = await call('analysis-state', {});
process.stdout.write(JSON.stringify({dataset, run, draft, md, xlsx, script, state}));
""", {"FOUNDRY_VAR": str(var), "FOUNDRY_BIN": str(executable),
       "FOUNDRY_TASK": "wrong-ambient-task", "FOUNDRY_TEST_UPLOAD": str(upload)})
    assert result["state"]["task_id"] == task.id
    assert result["state"]["context"]["session_id"] == "plugin-e2e"
    assert result["state"]["context"]["snapshot_ids"] == [result["dataset"]["id"]]
    assert Decimal(result["run"]["result"]["rows"][0]["revenue"]) == Decimal("70.01")
    assert result["run"]["session_id"] == "plugin-e2e"
    assert result["draft"]["publication_status"] == "draft"
    assert result["draft"]["review_status"] == "unreviewed"
    for exported in (result["md"], result["xlsx"]):
        assert hashlib.sha256(Path(exported["path"]).read_bytes()).hexdigest() == exported["sha256"]
    assert "70.01" in Path(result["md"]["path"]).read_text()
    assert load_workbook(result["xlsx"]["path"]).active["A1"].value == "北区收入分析"
    script = result["script"]
    if script["runner_status"] == "unavailable":
        pytest.skip("SQL/export paths passed; OS-isolated script runner is unavailable")
    assert script["execution_status"] == "succeeded", script
    assert script["stdout"].strip() == "70.01"
    output = AnalysisStore(task).output_path(script["id"], "summary.txt")
    assert Path(output["path"]).read_text() == "70.01"
    assert hashlib.sha256(Path(output["path"]).read_bytes()).hexdigest() == output["sha256"]
