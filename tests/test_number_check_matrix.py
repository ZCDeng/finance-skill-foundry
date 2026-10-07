"""The number check against the writing rules, case by case (tests/fixtures/number_check_matrix.json).

Every case names a fact, the body that cites it, and the claim presentation if any; `expect` is what the writing
rules say the check must answer. A change to the number check or to the rules must keep every row, or change the
row and its `why` with it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.finance_explanations import prepare_explanation, render_fact_template
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

MATRIX = json.loads((Path(__file__).parent / "fixtures" / "number_check_matrix.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def matrix(tmp_path_factory):
    task = TaskStore(tmp_path_factory.mktemp("number-matrix") / "var").create(title="数字核对矩阵")
    analysis = AnalysisStore(task)
    facts = {}
    for key, spec in MATRIX["facts"].items():
        column = spec["column"]
        row = {"metric_key": spec["metric_key"], column: spec["value"]}
        columns = [{"name": "metric_key", "type": "VARCHAR"}, {"name": column, "type": "DECIMAL(38,18)"}]
        if not spec.get("wide"):
            row["scenario"] = "actual"
            if spec["unit"] is not None:
                row["unit"] = spec["unit"]
                columns.append({"name": "unit", "type": "VARCHAR"})
        run_id = hashlib.md5(key.encode()).hexdigest()
        run = analysis._write(analysis._object_path("runs", run_id), {
            "task_id": analysis.task.id, "id": run_id, "bindings": {}, "assumptions": [],
            "execution_status": "succeeded", "reproducibility_status": "reproducible", "output_hash": "hash-" + key,
            "result": {"columns": columns, "rows": [row]},
        })
        facts[key] = (run, next(fact for fact in prepare_explanation(analysis, [run])["facts"] if fact["column"] == column))
    return FinanceStore(task), facts


def _label(case: dict) -> str:
    presentation = case["presentation"]
    shown = "none" if presentation is None else f"{presentation.get('scale')}{presentation.get('decimal_places')}"
    return f"{case['fact']}|{case['body']}|{shown}"


@pytest.mark.parametrize("case", MATRIX["cases"], ids=[_label(case) for case in MATRIX["cases"]])
def test_number_check_matches_the_writing_rules(matrix, case):
    store, facts = matrix
    run, fact = facts[case["fact"]]
    spec = {"body": case["body"], "run_ids": [run["id"]]}
    if case["presentation"] is None:
        spec["fact_ids"] = [fact["id"]]
    else:
        spec["claims"] = [{"basis": "calculation", "fact_id": fact["id"], "run_id": fact["run_id"], "row": fact["row"],
                           "column": fact["column"], "value": fact["value"], "presentation": case["presentation"]}]
    result = store.validate_explanation(spec)
    actual = "pass" if result["status"] == "pass" else "fail"
    assert actual == case["expect"], (case["why"], result["issues"])


@pytest.mark.parametrize("case", MATRIX["render"], ids=[f"{case['fact']}|{case['prose']}" for case in MATRIX["render"]])
def test_fact_template_writes_the_unit_once(matrix, case):
    _, facts = matrix
    _, fact = facts[case["fact"]]
    rendered, _ = render_fact_template(case["prose"].replace("{{fact}}", "{{fact:%s}}" % fact["id"]), [fact])
    assert rendered == case["expect"]


def test_matrix_covers_every_unit_kind_and_both_answers():
    units = {spec["unit"] for spec in MATRIX["facts"].values()}
    assert {"万元", "元", "比率", "ratio", "%", "％", "pct", "百分比", "百分点", "天", None} <= units
    assert {spec["column"] for spec in MATRIX["facts"].values() if spec.get("wide")} >= {
        "gap_pct", "gross_margin_pct", "cost_rate_pct", "achievement_pct", "achievement_ratio", "ratio"}
    assert {case["expect"] for case in MATRIX["cases"]} == {"pass", "fail"}
    assert all(case["why"] for case in MATRIX["cases"])
