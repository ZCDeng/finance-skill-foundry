"""Structural counts never grant authority to financial values or other runs."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from foundry.analysis import _hash
from foundry import finance_explanations as explanations
from test_finance_explanations import service as service


def model_basis():
    metrics = [f"metric_{index}" for index in range(13)]
    scope = {"organization": "Engineering Co", "ledger": "Management", "period": "2026-10",
             "currency": "CNY", "unit": "元", "scenario": "forecast"}
    result = {
        "template_id": "registered_template", "scenario_id": "scenario-current",
        "model_checks": [{"id": f"check_{index}", "status": "pass"} for index in range(12)],
        "source_binding_status": {"all_sources_verified": True},
        "rows": [{**scope, "metric_key": metric, "template_id": "registered_template",
                  "statement": "income_statement", "value_kind": "flow", "value": str(index)}
                 for index, metric in enumerate(metrics)],
    }
    run = {"id": "run-current", "engine": "finance", "execution_status": "succeeded",
           "finance_scope": {"inputs": deepcopy(scope)},
           "requirements_id": "requirements-current", "result": result, "output_hash": _hash(result)}
    requirement = {"id": "requirements-current", "scope": scope, "items": [
        {"id": metric, "metric": metric,
         "dimensions": {"metric_key": metric, "template_id": result["template_id"],
                        "scenario_id": result["scenario_id"]}} for metric in metrics]}
    facts = [{"id": str(index), "run_id": run["id"], "row": index, "column": "value",
              "semantics": {"metric": metric}} for index, metric in enumerate(metrics)]
    analysis = SimpleNamespace(_get=lambda kind, identifier: deepcopy(requirement))
    return analysis, run, requirement, facts


@pytest.mark.parametrize("field", ["organization", "ledger", "period", "currency", "unit", "scenario"])
def test_required_metric_count_checks_current_requirement_scope(field):
    def change(run, requirement, facts):
        requirement["scope"][field] = "wrong-scope"
    spans, issues = check_count("13 项 required_metrics 结果", prepared_basis(change))
    assert not spans and issues


@pytest.mark.parametrize("dimension", ["period", "statement", "value_kind", "currency", "unknown_dimension"])
def test_required_metric_count_checks_all_requested_dimensions(dimension):
    def change(run, requirement, facts):
        requirement["items"][0]["dimensions"][dimension] = "wrong-dimension"
    spans, issues = check_count("13 项 required_metrics 结果", prepared_basis(change))
    assert not spans and issues


@pytest.mark.parametrize("grain,values", [
    ("periods", ["2026-09"]), ("organizations", ["Other Co"]), ("scenarios", ["actual"]),
    ("periods", ["2026-10", "2026-11"]),
])
def test_required_metric_count_cannot_cover_wrong_or_partial_requested_grains(grain, values):
    def change(run, requirement, facts):
        requirement["items"][0][grain] = values
    spans, issues = check_count("13 项 required_metrics 结果", prepared_basis(change))
    assert not spans and issues


def test_required_metric_count_accepts_exact_native_grain_and_dimensions():
    def change(run, requirement, facts):
        item = requirement["items"][0]
        item.update(periods=["2026-10"], organizations=["Engineering Co"], scenarios=["forecast"])
        item["dimensions"].update(statement="income_statement", value_kind="flow")
    spans, issues = check_count("13 项 required_metrics 结果", prepared_basis(change))
    assert spans and not issues


@pytest.mark.parametrize("case,accepted", [
    ("uniform_source_scope", True), ("ambiguous_source_scope", False),
    ("missing_source_scope", False), ("row_scope_conflict", False),
])
def test_required_metric_count_uses_explicit_native_scenario_scope(case, accepted):
    def change(run, requirement, facts):
        for row in run["result"]["rows"]:
            row.pop("scenario")
        requirement["items"][0]["scenarios"] = ["forecast"]
        if case == "ambiguous_source_scope":
            run["finance_scope"]["other"] = {**run["finance_scope"]["inputs"], "scenario": "actual"}
        elif case == "missing_source_scope":
            run["finance_scope"]["inputs"].pop("scenario")
        elif case == "row_scope_conflict":
            run["result"]["rows"][0]["scenario"] = "actual"
    spans, issues = check_count("13 项 required_metrics 结果", prepared_basis(change))
    assert bool(spans) is accepted
    assert bool(issues) is not accepted


def prepared_basis(change=None):
    analysis, run, requirements, facts = model_basis()
    if change:
        change(run, requirements, facts)
    run["output_hash"] = _hash(run["result"])
    return {"structure_counts": explanations._structure_counts(analysis, [run], facts)}


def check_count(body, prepared=None, requirements_id="requirements-current"):
    return explanations._structure_count_spans(body, prepared or prepared_basis(), requirements_id)


@pytest.mark.parametrize("body", [
    "13 项 required_metrics 全部由来源绑定的已登记管理三表模板（registered_template，场景 scenario-current）计算得出，12 项 model_checks 全部通过。",
    "## 13 项 required_metrics 结果\n\n## 12 项 model_checks 核查结果",
    "以下 12 项模型核查均来自同一运行（run_id run-current）的 model_checks 数组，状态全部为 pass：",
    "12 项模型检查全部通过。",
])
def test_actual_structure_counts_only_ignore_the_bound_count_token(body):
    spans, issues = check_count(body)
    assert not issues
    assert spans
    assert all(body[start:end] in {"12", "13"} for start, end in spans)
    assert explanations._body_numbers(body, ignored_spans=spans) == []


@pytest.mark.parametrize("body", [
    "## 三表联动与 12 项模型检查",
    "### 风险复核及 12 项 model_checks 核查",
    "## Forecast and 12 项 model_checks 结果",
    "12 项 model_checks 全部通过（pass）：",
    "全部 12 项模型检查均通过（status=pass）。",
    "12 项 model_checks 全部通过 (pass)。",
    "## 12 项 model_checks 核查",
])
def test_bound_check_count_accepts_compound_titles_and_explicit_pass_labels(body):
    spans, issues = check_count(body)
    assert spans and not issues
    assert [body[start:end] for start, end in spans] == ["12"]
    assert explanations._body_numbers(body, ignored_spans=spans) == []


@pytest.mark.parametrize("body", [
    "## 现金为 12 项模型检查",
    "## 金额 12 项 model_checks 万元",
    "12 项 model_checks 全部通过（fail）。",
    "12 项 model_checks 全部通过（status=fail）。",
    "12 项 model_checks 全部通过（pass，现金充足）。",
    "12 项 model_checks 核查已批准过账。",
    "13 项 model_checks 全部通过（pass）。",
])
def test_extended_check_count_grammar_does_not_authorize_money_or_unsupported_status(body):
    spans, issues = check_count(body)
    assert not spans and issues


def test_pass_label_still_requires_current_unique_all_pass_check_set():
    for change in (
        lambda run, req, facts: run["result"]["model_checks"][0].update(status="fail"),
        lambda run, req, facts: run["result"]["model_checks"][0].update(id="check_1"),
    ):
        spans, issues = check_count("12 项 model_checks 全部通过（pass）。", prepared_basis(change))
        assert not spans and issues
    spans, issues = check_count("12 项 model_checks 全部通过（pass）。", requirements_id="other")
    assert not spans and issues


def test_extended_count_only_exempts_its_token_not_adjacent_amounts_or_percentages():
    body = "12 项 model_checks 全部通过（pass）：收入 12 元，增长 12%，公式 13 = 12 + 1。"
    spans, issues = check_count(body)
    assert spans and not issues
    assert [item["text"] for item in explanations._body_numbers(body, ignored_spans=spans)] == [
        "12", "12%", "13", "12", "1"]


@pytest.mark.parametrize("body,expected", [
    ("13 项 required_metrics 结果（单位：元，2026-10 整期）", ["13"]),
    ("**13 项 required_metrics 结果**（单位：元）", ["13"]),
    ("## **13 项需求结果**（单位：万元）", ["13"]),
    ("12 项 model_checks 结果：全部通过。", ["12"]),
    ("**12 项 model_checks 核查结果**：全部通过（pass），检查说明如下。", ["12"]),
    ("## 模型检查（12 项全部通过）", ["12"]),
    ("## 四、模型检查（12 项，全部通过）", ["12"]),
    ("model_checks (12 项，全部通过（status=pass）)。", ["12"]),
    ("以下 12 项 model_checks 均返回 pass，恒等式说明如下。", ["12"]),
    ("全部 12 项模型检查通过。", ["12"]),
    ("12 项核查通过。", ["12"]),
    ("13 项需求全部由 finance 引擎模型验证输出回答，12 项检查全部通过。", ["13", "12"]),
    ("## 一、2026-10 三表与现金可用性结果（13 项需求）", ["13"]),
    ("## 12 项 model_checks 核查结果\n\n全部 12 项通过（status=pass）：", ["12", "12"]),
    ("## 模型检查\n\n全部 12 项通过。", ["12"]),
    ("## 需求结果\n\n13 项需求。", ["13"]),
    ("来源均核验通过、12 项核查通过，但仍需独立复算。", ["12"]),
    ("- 无缺失档案、模型边界确认缺失、来源不符或检查失败：13 项需求全部由 finance 引擎模型验证输出回答。", ["13"]),
    ("需求覆盖：13 项需求结果。", ["13"]),
])
def test_verified_count_wording_from_live_drafts_only_exempts_count(body, expected):
    spans, issues = check_count(body)
    assert not issues
    assert [body[start:end] for start, end in spans] == expected
    assert explanations._body_numbers(body, ignored_spans=spans) == []


@pytest.mark.parametrize("body", [
    "**14 项 required_metrics 结果**（单位：元）",
    "## 模型检查（13 项，全部通过）", "全部 13 项模型检查通过。",
    "以下 12 项 model_checks 均返回 fail。",
    "模型检查（12 项，全部通过且允许过账）", "12 项 model_checks 结果：全部通过（fail）。",
    "现金为**12 项模型检查全部通过**。", "现金：12 项检查全部通过。",
    "**12 项 model_checks 结果**（单位：12万元）",
    "12 项 model_checks 结果：现金充足。", "12 项 model_checks 结果：全部通过并获利。",
    "全部 12 项通过。", "## 现金\n\n全部 12 项通过。",
    "## 模型检查\n\n## 收入\n\n全部 12 项通过。",
    "13万元需求。", "13% 项需求。", "13.0 项需求。", "−13 项需求。",
    "## 模型检查\n\n全部 13 项通过。",
    "金额检查为12项model_checks全部通过。",
    "金额检查：12 项 model_checks 万元。",
    "## 模型检查\n\n全部 12 项通过（status=pass，差异均为0）。",
])
def test_new_count_forms_reject_wrong_count_money_status_and_ambiguous_context(body):
    spans, issues = check_count(body)
    assert not spans
    assert issues or explanations._body_numbers(body)


@pytest.mark.parametrize("body", [
    "**12 项 model_checks 核查结果**：全部通过（pass）。",
    "## 模型检查（12 项，全部通过）", "全部 12 项模型检查通过。",
    "以下 12 项 model_checks 均返回 pass。", "12 项检查全部通过。",
    "## 模型检查\n\n全部 12 项通过。",
])
@pytest.mark.parametrize("invalid_basis", ["failed", "duplicate", "other_requirement", "duplicate_proof"])
def test_new_status_grammar_requires_unique_current_all_pass_proof(body, invalid_basis):
    prepared = prepared_basis()
    requirement_id = "requirements-current"
    if invalid_basis == "failed":
        prepared = prepared_basis(lambda run, req, facts: run["result"]["model_checks"][0].update(status="fail"))
    elif invalid_basis == "duplicate":
        prepared = prepared_basis(lambda run, req, facts: run["result"]["model_checks"][0].update(id="check_1"))
    elif invalid_basis == "other_requirement":
        requirement_id = "other-requirement"
    else:
        prepared["structure_counts"].append(deepcopy(prepared["structure_counts"][0]))
    spans, issues = check_count(body, prepared, requirement_id)
    assert not spans and issues


def test_new_count_forms_leave_adjacent_amounts_boundaries_and_check_values_unexempted():
    body = "**13 项需求结果**（单位：元）\n\n12 项检查全部通过：收入 13 元，增长 12%，16 项输入，8 项边界，差异 0。"
    spans, issues = check_count(body)
    assert not issues
    assert [body[start:end] for start, end in spans] == ["13", "12"]
    assert [value["text"] for value in explanations._body_numbers(body, ignored_spans=spans)] == [
        "13", "12%", "16", "8", "0"]


@pytest.mark.parametrize("body", [
    "**13 项需求结果**（单位：元）",
    "## 三表结果（13 项需求）",
    "需求覆盖：13 项需求全部由 finance 引擎模型验证输出回答。",
])
@pytest.mark.parametrize("change", [
    lambda run, requirement, facts: requirement["scope"].update(period="other-period"),
    lambda run, requirement, facts: requirement["items"][0].update(metric="unknown"),
    lambda run, requirement, facts: facts.pop(),
    lambda run, requirement, facts: run.update(engine="python"),
])
def test_requirement_synonyms_do_not_bypass_actual_scope_metric_and_fact_identity(body, change):
    spans, issues = check_count(body, prepared_basis(change))
    assert not spans and issues


def test_requirement_answer_claim_needs_verified_sources_and_unique_proof():
    body = "13 项需求全部由 finance 引擎模型验证输出回答。"
    unbound = prepared_basis(lambda run, requirement, facts: run["result"]["source_binding_status"].update(all_sources_verified=False))
    assert check_count(body, unbound)[1]
    duplicated = prepared_basis()
    duplicated["structure_counts"].append(deepcopy(duplicated["structure_counts"][1]))
    assert check_count(body, duplicated)[1]


@pytest.mark.parametrize("sign", ["−", "－"])
def test_unicode_minus_preserves_negative_amount_and_never_borrows_positive_fact(sign):
    tokens = explanations._body_numbers(f"投资现金流 {sign}60 元；筹资现金流 {sign}3 元。")
    assert [item["text"] for item in tokens] == [sign + "60", sign + "3"]
    assert [explanations._normalize_number(item["text"]) for item in tokens] == ["-60", "-3"]
    assert explanations._normalize_number(sign + "60") != explanations._normalize_number("60")
    assert explanations._normalize_number(sign + "12.5%") == "-0.125"


@pytest.mark.parametrize("sign", ["−", "－"])
def test_unicode_signed_amount_runs_through_real_validation_without_abs_matching(service, sign):
    from test_finance_explanations import _synthetic_single_value_fact

    store, _ = service
    run, fact = _synthetic_single_value_fact(store, run_id="cc" * 16, value="-60", unit="元")
    spec = {"run_ids": [run["id"]], "fact_ids": [fact["id"]]}
    correct = store.validate_explanation({**spec, "body": f"金额 {sign}60 元。"})
    wrong_sign = store.validate_explanation({**spec, "body": "金额 60 元。"})
    assert correct["status"] == "pass", correct["issues"]
    assert any(issue["code"] == "uncited_number" and issue["text"] == "60" for issue in wrong_sign["issues"])


def ordinal_table(header="#", labels=None, values=None, column=0):
    labels = ["1", "2", "3"] if labels is None else labels
    values = ["99 元", "17%", "8 = 7 + 1"] if values is None else values
    headings = ["指标", "金额"]
    headings.insert(column, header)
    lines = ["| " + " | ".join(headings) + " |", "| " + " | ".join(["---"] * 3) + " |"]
    for index, (label, value) in enumerate(zip(labels, values)):
        cells = [f"指标{'甲乙丙'[index]}", value]
        cells.insert(column, label)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


@pytest.mark.parametrize("header,column", [("#", 0), ("序号", 1), ("No.", 2)])
def test_explicit_table_ordinals_only_exempt_complete_sequence_cells(header, column):
    body = ordinal_table(header, column=column)
    spans = explanations._table_ordinal_spans(body)
    assert [body[start:end] for start, end in spans] == ["1", "2", "3"]
    assert [item["text"] for item in explanations._body_numbers(body, ignored_spans=spans)] == [
        "99", "17%", "8", "7", "1"]


@pytest.mark.parametrize("header,labels", [
    ("金额", ["1", "2", "3"]), ("序号（万元）", ["1", "2", "3"]),
    ("# 元", ["1", "2", "3"]), ("利润", ["1", "2", "3"]),
    ("#", ["1", "3", "4"]), ("#", ["1", "2", "2"]),
    ("#", ["0", "1", "2"]), ("#", ["1", "2", "4"]),
    ("#", ["1 元", "2 元", "3 元"]), ("#", ["1%", "2%", "3%"]),
    ("#", ["1", "2.0", "3"]), ("#", ["1", "+2", "3"]),
    ("#", ["1", "02", "3"]), ("#", ["1", "2 = 2", "3"]),
])
def test_table_ordinal_exception_rejects_money_percentages_and_broken_sequences(header, labels):
    assert explanations._table_ordinal_spans(ordinal_table(header, labels)) == []


def test_table_ordinals_do_not_ignore_a_malformed_row_or_a_second_ordinal_column():
    body = ordinal_table()
    assert explanations._table_ordinal_spans(body + "\n| 4 | only two cells |") == []
    assert explanations._table_ordinal_spans(body.replace("| 指标 |", "| 序号 |", 1)) == []
    assert explanations._table_ordinal_spans(body.replace("| --- | --- | --- |", "| x | x | x |")) == []


def test_sequence_format_does_not_authorize_a_false_count_title():
    body = "## 3 项 model_checks 全部通过。\n\n" + ordinal_table()
    count_spans, issues = check_count(body)
    assert issues and not count_spans
    ordinal_spans = explanations._table_ordinal_spans(body)
    assert [body[start:end] for start, end in ordinal_spans] == ["1", "2", "3"]
    assert explanations._body_numbers(body, ignored_spans=ordinal_spans)[0]["text"] == "3"


@pytest.mark.parametrize("body", [
    "12 项 required_metrics 结果", "13 项 model_checks 全部通过。",
    "现金为12项模型检查全部通过。", "金额：12 项 model_checks 万元。",
    "12 项 model_checks 已批准过账。", "12 项模型核查无需再核实金额。",
    "以下 12 项模型核查均来自同一运行（run_id other-run）的 model_checks 数组，状态全部为 pass：",
    "13 项 required_metrics 全部由来源绑定的已登记管理三表模板（other-template，场景 scenario-current）计算得出。",
    "12 项 model_checks 全部通过并实现利润。",
    "现金：12 项 model_checks 全部通过。",
    "12.0 项 model_checks 全部通过。", "-12 项 model_checks 全部通过。",
    "12% 项 model_checks 全部通过。", "+12 项 model_checks 全部通过。",
    "12 项 model_checks，全部失败。", "12 项 model_checks 核查结果，全部通过（差异为0）。",
])
def test_wrong_or_unsupported_counts_are_rejected_even_if_the_number_is_a_cited_amount(body):
    spans, issues = check_count(body)
    assert not spans
    assert issues


def test_nearby_financial_values_percentages_and_formula_operands_are_not_counts():
    body = "12 项模型检查全部通过，现金 12 元，增长 12%，利润 13 = 12 + 1。"
    spans, issues = check_count(body)
    assert not issues
    assert [number["text"] for number in explanations._body_numbers(body, ignored_spans=spans)] == [
        "12", "12%", "13", "12", "1"]


@pytest.mark.parametrize("change", [
    lambda run, req, facts: run["result"]["model_checks"][0].update(status="fail"),
    lambda run, req, facts: run["result"]["model_checks"][0].pop("status"),
    lambda run, req, facts: run["result"]["model_checks"][0].update(id="check_1"),
    lambda run, req, facts: run.update(engine="python"),
])
def test_all_pass_assertion_requires_complete_unique_native_check_set(change):
    spans, issues = check_count("12 项 model_checks 全部通过。", prepared_basis(change))
    assert not spans and issues


@pytest.mark.parametrize("change", [
    lambda run, req, facts: req["items"].pop(),
    lambda run, req, facts: facts.pop(),
    lambda run, req, facts: facts[-1]["semantics"].update(metric="metric_0"),
    lambda run, req, facts: req["items"][0]["dimensions"].update(scenario_id="other"),
    lambda run, req, facts: req["items"][0].update(metric="unregistered_metric"),
    lambda run, req, facts: req.update(id="other"),
])
def test_required_metric_count_requires_exact_actual_requirement_and_fact_set(change):
    spans, issues = check_count("13 项 required_metrics 结果", prepared_basis(change))
    assert not spans and issues


def test_other_requirement_and_client_supplied_count_are_not_authoritative():
    spans, issues = check_count("13 项 required_metrics 结果", requirements_id="other")
    assert not spans and issues
    spans, issues = check_count("12 项 model_checks 全部通过。", {"model_checks": [1] * 12})
    assert not spans and issues


def test_checks_can_be_counted_without_claiming_the_failed_check_passed():
    prepared = prepared_basis(lambda run, req, facts: run["result"]["model_checks"][0].update(status="fail"))
    spans, issues = check_count("## 12 项 model_checks 核查结果", prepared)
    assert spans and not issues


def test_fact_reference_templates_keep_distinct_metric_identity_and_exact_claim(monkeypatch):
    monkeypatch.setattr("foundry.finance_professional.cell_evidence_eligibility", lambda *a, **k: {
        "counts_as_amount_evidence": False, "status": "unverified", "reason_codes": ["unregistered_financial_semantics"]})
    run = {"id": "run", "output_hash": "hash", "result": {"template_id": "template", "scenario_id": "scenario"},
           "finance_scope": {"source": {"ledger": "ledger", "scenario": "forecast"}}}
    row = {"metric_key": "total_assets", "value": "647", "period": "2026-10", "unit": "元",
           "currency": "CNY", "statement": "balance_sheet", "value_kind": "stock", "template_id": "template",
           "source_rows": [{"dataset_id": "source", "row_index": 2, "column": "amount"}]}
    first = explanations._make_fact(run, 0, row, "value", "647", {}, {})
    second = explanations._make_fact(run, 1, {**row, "metric_key": "total_liabilities_equity"}, "value", "647", {}, {})
    for fact in (first, second):
        assert fact["metric_identity"]["metric_key"] == fact["semantics"]["metric"]
        assert fact["metric_identity"]["period"] == "2026-10"
        assert fact["metric_identity"]["scenario_id"] == "scenario"
        assert fact["metric_identity"]["scenario"] == "forecast"
        assert fact["reference_template"]["body_token"] == "{{fact:" + fact["id"] + "}}"
        assert fact["reference_template"]["claim"] == {
            "basis": "calculation", "fact_id": fact["id"], "run_id": "run", "row": fact["row"],
            "column": "value", "value": "647"}
        assert fact["source_trace"]["source_rows"] == row["source_rows"]
        assert fact["evidence_eligibility"]["counts_as_amount_evidence"] is False
        assert fact["state"] == "nonzero"
    assert first["metric_identity"]["metric_key"] != second["metric_identity"]["metric_key"]
    assert first["reference_template"]["claim"] != second["reference_template"]["claim"]
    no_scope = explanations._make_fact({**run, "finance_scope": None}, 0, row, "value", "647", {}, {})
    assert no_scope["scope"] is None  # Preserve the pre-existing fact scope shape.
    assert no_scope["id"] == first["id"]
    assert no_scope["metric_identity"]["period"] == "2026-10"
    assert no_scope["metric_identity"]["scenario_id"] == "scenario"
    assert "scenario" not in no_scope["metric_identity"]
    assert "ledger" not in no_scope["metric_identity"]


def test_real_validation_rejects_fabricated_count_even_when_equal_to_a_cited_amount(tmp_path):
    from foundry.finance_service import FinanceStore
    from foundry.task import TaskStore

    store = FinanceStore(TaskStore(tmp_path / "var").create(title="计数与金额分离"))
    bindings = {}
    for alias, revenue in (("actual", "112"), ("budget", "100")):
        path = tmp_path / f"{alias}.json"
        path.write_text(json.dumps([{"account_code": "6001", "management_account": "revenue", "amount": revenue},
                                    {"account_code": "6401", "management_account": "cost", "amount": "20"},
                                    {"account_code": "6601", "management_account": "expense", "amount": "10"}]))
        bindings[alias] = store.analysis.add_dataset(path, name=alias)["id"]
    context = store.save_context({"bindings": bindings, "scopes": {
        alias: {"organization": "公司", "ledger": "ledger", "period": "2026-09", "currency": "CNY",
                "unit": "元", "scenario": alias} for alias in bindings}})
    run = store.explain_variance({"context_id": context["id"]})
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    facts = prepared["facts"]
    claims = explanations.claims_for_facts(facts, [fact["id"] for fact in facts])
    for body in ("12 项 model_checks 全部通过。", "现金：12 项 model_checks 全部通过。", "12.0 项 model_checks 全部通过。"):
        check = explanations.validate_explanation(store.analysis, {
            "run_ids": [run["id"]], "claims": claims, "body": body,
            "structure_counts": [{"kind": "model_checks", "count": 12, "all_pass": True}],
        })
        assert check["status"] == "needs_attention"
        assert any(issue["code"] == "unverified_structure_count" for issue in check["issues"])


@pytest.mark.parametrize("private_binding", ["hidden_only", "visible_and_hidden"])
@pytest.mark.parametrize("visible_predecessor", [False, True])
def test_runtime_counts_do_not_disclose_or_certify_unreadable_requirements(tmp_path, capsys, private_binding, visible_predecessor):
    from foundry.cli import main
    from foundry.errors import FoundryError
    from foundry.finance_service import FinanceStore
    from foundry.finance_driver_templates import TEMPLATE_ID
    from test_finance_runtime_ordering import setup_case, register

    manager, runtime, context, scenario = setup_case(tmp_path)
    manager.task.record_session(runtime.session_id, role="analysis")
    previous = register(manager, context, scenario) if visible_predecessor else None
    path = tmp_path / "restricted.json"
    path.write_text('[{"amount":"991"}]')
    hidden = manager.analysis.add_dataset(path, name="Private requirement source")
    bindings = {"private": hidden["id"]}
    if private_binding == "visible_and_hidden":
        bindings.update(context["bindings"])
    private_context = manager.save_context({"bindings": bindings})
    requirement = manager.analysis_requirements_save({
        "context_id": private_context["id"],
        "bindings": bindings, "question": "Private obligation",
        **({"parent_id": previous["id"], "change_reason": "Private source changed"} if previous else {}),
        "items": [{"id": "private_requirement_member_marker", "metric": "net_income",
                   "dimensions": {"template_id": TEMPLATE_ID, "scenario_id": scenario["id"]},
                   "requires_drilldown": False}],
    })
    run = manager.run_scenario({"scenario_id": scenario["id"]})
    assert run["requirements_id"] == requirement["id"]
    visible = runtime.analysis_requirements_list({})["requirements"]
    assert requirement["id"] not in {item["id"] for item in visible}
    protected = {manager.analysis._object_path(kind, object_id): None
                 for kind, object_id in (("runs", run["id"]), ("requirements", requirement["id"]))}
    protected = {path: path.read_bytes() for path in protected}
    prepared = runtime.prepare_explanation({"run_ids": [run["id"]]})
    counts = prepared["structure_counts"]
    assert requirement["id"] not in json.dumps(counts)
    assert "private_requirement_member_marker" not in json.dumps(counts)
    assert not any(item["kind"] == "required_metrics" for item in counts)
    assert any(item["kind"] == "model_checks" for item in counts)
    spans, issues = explanations._structure_count_spans("1 项 required_metrics 结果", prepared, None)
    assert not spans and issues
    # A wider reader and the manager still see exactly their authorized set.
    wider = FinanceStore(manager.task, snapshot_ids=[*runtime.allowed, hidden["id"]], session_id="wider")
    for reader in (wider, manager):
        full = reader.prepare_explanation({"run_ids": [run["id"]]})["structure_counts"]
        requirement_count = next(item for item in full if item["kind"] == "required_metrics")
        assert requirement_count["requirements_id"] == requirement["id"]
        assert requirement_count["member_ids"] == ["private_requirement_member_marker"]
    assert all(path.read_bytes() == content for path, content in protected.items())
    if previous:
        # Explicitly bind the manager's draft to a readable requirement, while
        # its native run captured the private successor. Count metadata must
        # never be archived into quality and leak through later draft views.
        full = manager.prepare_explanation({"run_ids": [run["id"]]})
        fact = next(fact for fact in full["facts"] if fact["semantics"]["metric"] == "net_income")
        saved = manager.save_explanation_draft({
            "run_ids": [run["id"]], "requirements_id": previous["id"],
            "body": "净利润 " + fact["reference_template"]["body_token"],
            "claims": [fact["reference_template"]["claim"]],
        })
        archived = manager.analysis.get_draft(saved["id"])
        assert "structure_counts" not in archived["explanation_check"]
        assert "structure_counts" not in archived["quality"]
        # The stored check also used the private successor, so the public read
        # boundary refuses this whole draft before any draft view is produced.
        assert not runtime.analysis.draft_readable(archived, runtime.allowed)
        with pytest.raises(FoundryError, match="draft is unavailable"):
            runtime.validate_explanation({"draft_id": archived["id"]})
        capsys.readouterr()
        assert main(["--var", str(tmp_path / "var"), "--session", runtime.session_id, "analysis-state"]) == 0
        state = json.loads(capsys.readouterr().out)
        assert archived["id"] not in {draft["id"] for draft in state["drafts"]}
        assert "private_requirement_member_marker" not in json.dumps(state)
        assert requirement["id"] not in json.dumps(state)
        direct = explanations.validate_explanation(runtime.analysis, {
            "run_ids": [run["id"]], "requirements_id": previous["id"],
            "body": "1 项 required_metrics 结果", "claims": []}, _allowed=runtime.allowed)
        assert any(item["code"] == "unverified_structure_count" for item in direct["issues"])
        assert "structure_counts" not in direct
    elif private_binding == "hidden_only":
        # A later readable obligation makes the draft itself readable. Its run
        # still captured the private obligation, which manager prepare may see;
        # that preparation-only metadata must not persist into draft quality.
        current = register(manager, context, scenario, parent_id=requirement["id"],
                           change_reason="New public source obligation")
        full = manager.prepare_explanation({"run_ids": [run["id"]]})
        fact = next(fact for fact in full["facts"] if fact["semantics"]["metric"] == "net_income")
        saved = manager.save_explanation_draft({
            "run_ids": [run["id"]], "requirements_id": current["id"],
            "body": "净利润 " + fact["reference_template"]["body_token"],
            "claims": [fact["reference_template"]["claim"]],
        })
        archived = manager.analysis.get_draft(saved["id"])
        assert runtime.analysis.draft_readable(archived, runtime.allowed)
        assert "structure_counts" not in archived["explanation_check"]
        assert "structure_counts" not in archived["quality"]
        capsys.readouterr()
        assert main(["--var", str(tmp_path / "var"), "--session", runtime.session_id, "analysis-state"]) == 0
        state = json.loads(capsys.readouterr().out)
        assert archived["id"] in {draft["id"] for draft in state["drafts"]}
        assert "private_requirement_member_marker" not in json.dumps(state)
        assert requirement["id"] not in json.dumps(state)


@pytest.mark.parametrize("body,expected", [
    ("### 13 项指标", "13"),
    ("## **13 项指标结果**（单位：元）", "13"),
    ("12 项 model_checks 核查结果，全部通过。", "12"),
    ("12 项 model_checks，全部通过。", "12"),
    ("12 项模型检查结果, 全部通过（pass）。", "12"),
    ("13 项 required_metrics 全部由已登记三表模板原生计算得出。", "13"),
    ("13 项 required_metrics 全部由来源绑定模板算得。", "13"),
])
def test_r2_live_bound_count_grammar_repairs_only_confirmed_forms(body, expected):
    spans, issues = check_count(body)
    assert [body[start:end] for start, end in spans] == [expected]
    assert not issues
    assert not explanations._body_numbers(body, ignored_spans=spans)


@pytest.mark.parametrize("body", [
    "13 项指标", "现金为13项指标", "## 金额 13 项指标", "### 13 项指标万元",
    "### 13万元指标", "### 13% 项指标", "### 14 项指标",
    "13 项 required_metrics 全部由已登记三表模板原生计算得出并批准过账。",
    "14 项 required_metrics 全部由来源绑定模板算得。",
    "12 项 model_checks 核查结果，全部通过（差异为0）。",
    "12 项 model_checks 核查结果，全部通过（status=fail）。",
    "12 项 model_checks 核查结果，现金为12元。",
    "13 项 model_checks 核查结果，全部通过。",
])
def test_r2_live_grammar_preserves_false_count_status_and_amount_rejection(body):
    spans, issues = check_count(body)
    assert not spans
    assert issues or explanations._body_numbers(body)


@pytest.mark.parametrize("body", [
    "### 13 项指标",
    "12 项 model_checks 核查结果，全部通过。",
    "13 项 required_metrics 全部由已登记三表模板原生计算得出。",
])
@pytest.mark.parametrize("basis", ["missing", "duplicate", "other_requirement"])
def test_r2_live_forms_require_a_unique_current_authorized_proof(body, basis):
    prepared = prepared_basis()
    req_id = "requirements-current"
    if basis == "missing":
        prepared["structure_counts"] = []
    elif basis == "duplicate":
        prepared["structure_counts"] *= 2
    else:
        req_id = "other-requirement"
    spans, issues = check_count(body, prepared, req_id)
    assert not spans and issues


@pytest.mark.parametrize("invalid_basis", ["failed", "duplicate"])
def test_r2_comma_status_requires_actual_unique_all_pass_checks(invalid_basis):
    def change(run, requirement, facts):
        check = run["result"]["model_checks"][0]
        check.update({"status": "fail"} if invalid_basis == "failed" else {"id": "check_1"})
    spans, issues = check_count("12 项 model_checks 核查结果，全部通过。", prepared_basis(change))
    assert not spans and issues


@pytest.mark.parametrize("body", [
    "13 项 required_metrics 全部由已登记三表模板原生计算得出。",
    "13 项 required_metrics 全部由来源绑定模板算得。",
])
def test_r2_native_computed_phrase_requires_actual_source_bound_proof(body):
    prepared = prepared_basis()
    for proof in prepared["structure_counts"]:
        if proof["kind"] == "required_metrics":
            proof["source_bound"] = False
    spans, issues = check_count(body, prepared)
    assert not spans and issues


def test_r2_metric_title_count_tracks_actual_proof_without_a_fixed_number():
    def change(run, requirement, facts):
        del requirement["items"][-3:]
        del run["result"]["rows"][-3:]
        del facts[-3:]
    spans, issues = check_count("### 10 项指标", prepared_basis(change))
    assert spans and not issues


def test_r2_confirmed_forms_never_exempt_adjacent_financial_values():
    body = "### 13 项指标\n\n收入13元。12 项 model_checks 核查结果，全部通过：利润12元，增长12%，边界0。"
    spans, issues = check_count(body)
    assert not issues
    assert [body[start:end] for start, end in spans] == ["13", "12"]
    assert [item["text"] for item in explanations._body_numbers(body, ignored_spans=spans)] == ["13", "12", "12%", "0"]


@pytest.mark.parametrize("body", [
    "13 项必答指标全部取得结果、12 项模型检查全部通过。",
    "共 13 项指标全部得出。",
    "13 项 required_metrics 全部得出。",
])
def test_r2_answered_metric_count_states_need_current_source_bound_members(body):
    spans, issues = check_count(body)
    assert spans and not issues
    prepared = prepared_basis()
    for proof in prepared["structure_counts"]:
        if proof["kind"] == "required_metrics":
            proof["source_bound"] = False
    spans, issues = check_count(body, prepared)
    assert (0, 2) not in spans and issues


def test_r2_compound_enumeration_remains_outside_the_supported_count_grammar():
    body = "管理预测三表由引擎闭合推演：净利润、三类现金流、期末余额、可用现金共 13 项指标全部得出。"
    spans, issues = check_count(body)
    assert not spans and issues


@pytest.mark.parametrize("body", [
    "12 项必答指标全部取得结果。", "13 项必答指标全部未取得结果。",
    "金额13项必答指标全部取得结果。", "13% 项必答指标全部取得结果。",
    "13 项必答指标全部取得结果且差异为0。",
])
def test_r2_answered_metric_count_state_rejects_false_counts_and_financial_disguise(body):
    spans, issues = check_count(body)
    assert not spans and issues
