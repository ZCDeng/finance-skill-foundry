"""Method-first instructions and actual SDK reads retain their original ordering."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys

import pytest

from foundry.finance_service import FinanceStore
from foundry.task import TaskStore
from test_method_skill_runtime import ROOT, _runtime_or_skip


@pytest.mark.parametrize("prefix", ["", "foundry/resources/"])
def test_active_variance_route_cannot_substitute_connectors_for_checks(prefix):
    preset = (ROOT / prefix / "dsh-plugin/presets/analysis/agent.cordis.yml").read_text()
    skill = (ROOT / prefix / "method/variance-analysis/SKILL.md").read_text()
    fence = (ROOT / prefix / "method/FOUNDRY.md").read_text()
    assert "FOUNDRY.md 或 CONNECTORS.md" not in preset
    assert "首次计算或缺数据诊断前" in preset
    assert 'resource: "model-checks.md"' in skill.split("## Usage")[0]
    assert "CONNECTORS.md does not replace" in fence
    assert "context" in skill.split("## Usage")[0]
    assert "非空 semantic_fingerprint 本身" in preset
    assert "普通无专业规则需求可以只用完整 bindings 登记" in preset
    assert "任何计算或缺数据诊断之前，先创建或选取" not in preset


def test_all_finance_execution_entrypoints_offer_the_same_preflight():
    script = """
import {definitions} from './dsh-plugin/analysis.js';
const names = ['run_metric','explain_variance','finance_scenario_run',
 'analysis-run','analysis-script','analysis-script-start'];
console.log(JSON.stringify(definitions().filter(x=>names.includes(x.name))
 .map(x=>({name:x.name,description:x.description}))));
"""
    observed = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                              capture_output=True, text=True, timeout=30)
    assert observed.returncode == 0, observed.stderr
    schemas = json.loads(observed.stdout)
    assert len(schemas) == 6
    for schema in schemas:
        description = schema["description"]
        assert "首次计算或缺数据诊断前" in description, schema["name"]
        assert "model-checks.md" in description, schema["name"]
        assert "原生 skill" in description, schema["name"]
        assert "成功返回" in description, schema["name"]


def _scorer():
    spec = importlib.util.spec_from_file_location(
        "method_order_frozen_scorer", ROOT / "tools/finance_professional_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_sdk_method_reads_and_first_calculation_are_not_reordered(tmp_path):
    """The local scripted caller is engineering evidence, not model acceptance."""
    modules = _runtime_or_skip()
    scope = {"ledger": "SDK", "organization": "Method Lab", "period": "2026-10",
             "currency": "CNY", "unit": "元"}
    rows = [{**scope, "product": product, "scenario": scenario,
             "quantity": quantity, "price": price, "quantity_unit": "件"}
            for product, scenario, quantity, price in [
                ("A", "budget", "20", "7"), ("B", "budget", "30", "11"),
                ("A", "actual", "32", "8"), ("B", "actual", "28", "10")]]
    source = tmp_path / "independent-sales.json"
    source.write_text(json.dumps(rows))
    modes = ["ordered", "missing_checks", "early_diagnostic", "wrong_skill", "concurrent_read"]
    sessions = {mode: f"sdk-method-{mode}" for mode in modes}
    bindings = {}
    for mode, session in sessions.items():
        store = FinanceStore(TaskStore(tmp_path / "var").create(title=f"Method read ordering: {mode}"))
        dataset = store.analysis.add_dataset(source, name="Method ordering source")
        store.task.record_session(session, role="analysis")
        bindings[mode] = {"sales": dataset["id"]}
    config = tmp_path / "sdk-config.json"
    config.write_text(json.dumps({"sessions": sessions, "bindings": bindings,
                                 "scope": scope, "root": str(ROOT), "tmp": str(tmp_path)}))
    launcher = tmp_path / "foundry"
    launcher.write_text(f"#!{sys.executable}\nimport sys\nsys.dont_write_bytecode=True\n"
                        f"sys.path.insert(0,{str(ROOT)!r})\nfrom foundry.cli import main\n"
                        "raise SystemExit(main())\n")
    launcher.chmod(0o700)
    result = subprocess.run(["node", str(ROOT / "tests/finance_method_read_order_sdk.mjs"),
                             str(modules), str(config)], cwd=ROOT, capture_output=True, text=True,
                            env=os.environ | {"FOUNDRY_BIN": str(launcher),
                                              "FOUNDRY_VAR": str(tmp_path / "var")}, timeout=100)
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["provider_calls"] == 0
    skill_body = (ROOT / "method/variance-analysis/SKILL.md").read_text().split("---", 2)[2].strip()
    resources = [{"tool": "skill", "arguments": {"name": "variance-analysis"},
                  "sha256": hashlib.sha256(skill_body.encode()).hexdigest()}]
    resources.extend({"tool": "method-resource",
                      "arguments": {"skill": "variance-analysis", "resource": name},
                      "sha256": hashlib.sha256((ROOT / "method" / name).read_bytes()).hexdigest()}
                     for name in ("FOUNDRY.md", "model-checks.md"))
    scorer = _scorer()
    verdicts = {}
    for row in evidence["cases"]:
        verdict = scorer.skill_first(row["events"], session=row["session"], resources=resources)
        verdicts[row["mode"]] = verdict
        assert verdict["status"] == ("passed" if row["mode"] == "ordered" else "failed"), row
        assert row["successful_calculations"] == 1
        assert row["resource_bodies_preserved"]
        if row["mode"] == "early_diagnostic":
            assert row["failed_calculations"] == 1
            assert verdict["calculation_count"] == 2
    # Observed reads in another actual SDK session cannot authorize this one.
    ordered = evidence["cases"][0]
    assert scorer.skill_first(ordered["events"], session="other-session", resources=resources)["status"] == "failed"
    # A stale expected body cannot substitute for the current successful read.
    stale = json.loads(json.dumps(resources))
    stale[-1]["sha256"] = "0" * 64
    assert scorer.skill_first(ordered["events"], session=ordered["session"], resources=stale)["status"] == "failed"
    (tmp_path / "sdk-public-observations.json").write_text(json.dumps({
        **evidence, "frozen_verdicts": verdicts, "required_resources": resources,
        "original_model_credit": 0, "engineering_only": True,
    }, indent=2, ensure_ascii=False) + "\n")
