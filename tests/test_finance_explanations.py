import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


@pytest.fixture
def service(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="解释质量")
    analysis = AnalysisStore(task)
    bindings = {}
    for scenario, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15])):
        path = tmp_path / f"{scenario}.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "account_code": code,
                        "management_account": account,
                        "amount": amount,
                    }
                    for code, account, amount in zip(
                        ("6001", "6401", "6601"),
                        ("revenue", "cost", "expense"),
                        amounts,
                    )
                ]
            )
        )
        bindings[scenario] = analysis.add_dataset(path, name=scenario)["id"]
    store = FinanceStore(task)
    context = store.save_context(
        {
            "bindings": bindings,
            "scopes": {
                alias: {
                    "ledger": "L1",
                    "organization": "O1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": alias,
                }
                for alias in bindings
            },
        }
    )
    return store, context


def _ratio_metric_store(tmp_path, rows, *, unit="万元"):
    task = TaskStore(tmp_path / "ratio-var").create(title="ratio")
    analysis = AnalysisStore(task)
    path = tmp_path / "ratio-ledger.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    dataset = analysis.add_dataset(path, name="ratio-ledger")
    store = FinanceStore(task)
    context = store.save_context(
        {
            "bindings": {"actual": dataset["id"]},
            "scopes": {
                "actual": {
                    "ledger": "ratio-ledger",
                    "organization": "华东",
                    "period": "2026-08",
                    "currency": "CNY",
                    "unit": unit,
                    "scenario": "actual",
                }
            },
        }
    )
    return store, context


def test_prepare_explanation_returns_stable_bound_facts_for_successful_runs(service):
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})

    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    again = store.prepare_explanation({"run_ids": [run["id"]]})

    profit = next(
        fact
        for fact in prepared["facts"]
        if fact["row"] == 3 and fact["column"] == "contribution"
    )
    assert profit["id"] == again["facts"][prepared["facts"].index(profit)]["id"]
    assert profit["value"] == "5"
    assert profit["display_value"] == "5 万元"
    assert profit["source_trace"]["output_hash"] == run["output_hash"]
    assert profit["scope"]["actual"]["ledger"] == "L1"
    assert profit["state"] == "nonzero"
    assert profit["semantics"]["materiality"]["absolute"]["threshold"] == "0"
    assert profit["id"] in prepared["required_fact_ids"]
    assert prepared["evidence_groups"][0]["group_type"] == "profit_bridge"
    assert prepared["evidence_groups"][0]["status"] == "complete"
    assert prepared["writing_guidance"]["schema_version"] == 1
    assert "{{fact:FACT_ID}}" in " ".join(prepared["writing_guidance"]["rules"])


def test_save_explanation_draft_renders_fact_templates_and_refreshes_checks(service):
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    fact = next(
        item
        for item in store.prepare_explanation({"run_ids": [run["id"]]})["facts"]
        if item["row"] == 3 and item["column"] == "contribution"
    )

    draft = store.save_explanation_draft(
        {
            "title": "利润说明",
            "body": "利润超预算 {{fact:%s}}，2026-09 继续跟踪。" % fact["id"],
            "run_ids": [run["id"]],
            "fact_ids": [fact["id"]],
        }
    )
    assert "5 万元" in draft["body"]
    assert "{{fact:" in draft["body_template"]
    assert draft["claims"][0]["fact_id"] == fact["id"]
    assert draft["claims"][0]["value"] == "5"
    assert draft["body"].startswith("利润超预算 5 万元，2026-09 继续跟踪。")
    assert "## 计算依据" in draft["body"]
    assert draft["explanation_check"]["status"] == "pass"
    assert not draft["explanation_check"]["coverage"]["missing_required_fact_ids"]

    edited = store.analysis.save_draft(
        {
            "parent_id": draft["id"],
            "body": "利润超预算 999 万元，2026-09 继续跟踪。",
        }
    )
    assert edited["claims"][0]["verification_status"] == "matches_run"
    assert "body_template" not in edited
    assert edited["explanation_check"]["status"] == "needs_attention"
    assert edited["quality"] == edited["explanation_check"]
    assert any(
        issue["code"] == "uncited_number"
        for issue in edited["explanation_check"]["issues"]
    )


def test_number_parser_keeps_percent_and_chinese_adjacent_numbers():
    from foundry.finance_explanations import _body_numbers, _numbers_from_text

    assert _numbers_from_text("58.33%") == {"0.5833"}
    assert [item["text"] for item in _body_numbers("利润5万元")] == ["5"]


def test_parent_auto_claims_do_not_duplicate_on_edit(service):
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    fact = next(
        item
        for item in store.prepare_explanation({"run_ids": [run["id"]]})["facts"]
        if item["row"] == 3 and item["column"] == "contribution"
    )
    draft = store.save_explanation_draft(
        {
            "body": "利润超预算 {{fact:%s}}" % fact["id"],
            "run_ids": [run["id"]],
            "fact_ids": [fact["id"]],
        }
    )
    edited = store.save_explanation_draft(
        {
            "parent_id": draft["id"],
            "body": "利润超预算 5 万元，经理判断与促销有关。",
            "claims": [{"basis": "professional_judgment", "reason": "经理判断"}],
        }
    )

    calculation_claims = [
        claim for claim in edited["claims"] if claim["basis"] == "calculation"
    ]
    assert len(calculation_claims) == len({claim["fact_id"] for claim in calculation_claims})
    assert len(calculation_claims) == len(edited["fact_ids"])
    assert len(
        [claim for claim in edited["claims"] if claim["basis"] == "professional_judgment"]
    ) == 1


def test_explanation_rejects_failed_or_out_of_scope_runs(service):
    store, context = service
    failed = store.explain_variance(
        {"context_id": context["id"], "actual_filters": ["not", "object"]}
    )
    with pytest.raises(FoundryError, match="successful run"):
        store.prepare_explanation({"run_ids": [failed["id"]]})

    child = FinanceStore(store.task, snapshot_ids=[context["bindings"]["actual"]])
    run = store.explain_variance({"context_id": context["id"]})
    with pytest.raises(FoundryError, match="outside"):
        child.prepare_explanation({"run_ids": [run["id"]]})


def test_prepare_explanation_carries_run_diagnostics_and_relative_materiality(service):
    store, context = service
    run = store.explain_variance(
        {
            "context_id": context["id"],
            "actual_filters": {"period": "2026-09"},
            "baseline_filters": {"period": "2026-08"},
        }
    )
    assert any(
        item["code"] == "comparison_group_missing"
        for item in run["result"]["diagnostics"]
    )

    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    assert any(
        item["code"] == "comparison_group_missing"
        for item in prepared["diagnostics"]
    )

    prepared = store.prepare_explanation(
        {"run_ids": [run["id"]], "materiality": {"relative": "0.1"}}
    )
    assert prepared["materiality"]["relative"] == {
        "threshold": "0.1",
        "denominator": "baseline_abs",
        "negative_policy": "absolute",
    }
    assert any(
        fact["semantics"]["materiality"]["relative"]["status"] == "not_applicable"
        for fact in prepared["facts"]
    )


def test_require_all_material_facts_deduplicates_same_row_semantic_groups(service):
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    facts = store.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    check = store.validate_explanation(
        {
            "body": "收入增加 20 万元，成本利润影响 -10 万元，费用利润影响 -5 万元，利润超预算 5 万元。",
            "run_ids": [run["id"]],
            "fact_ids": [
                item["id"]
                for item in facts
                if item["column"] == "contribution"
            ],
            "require_all_material_facts": True,
        }
    )

    assert check["status"] == "pass"
    assert len(check["coverage"]["missing_required_fact_ids"]) == 0


def test_validate_explanation_rejects_forged_fact_ids(service):
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    check = store.validate_explanation(
        {
            "body": "利润超预算 5 万元",
            "run_ids": [run["id"]],
            "fact_ids": ["0" * 64],
        }
    )
    assert check["status"] == "needs_attention"
    assert any(issue["code"] == "unknown_fact" for issue in check["issues"])


def test_prepare_explanation_includes_custom_sql_numeric_columns(service):
    store, context = service
    revision = store.analysis.save_analysis(
        {
            "question": "自定义毛利",
            "sql": "SELECT 42.5 AS custom_margin FROM actual LIMIT 1",
            "bindings": {"actual": context["bindings"]["actual"]},
        }
    )
    run = store.analysis.run_analysis(revision["id"])

    prepared = store.prepare_explanation({"run_ids": [run["id"]]})

    assert any(
        fact["column"] == "custom_margin" and fact["value"] == "42.5"
        for fact in prepared["facts"]
    )


def test_validate_explanation_flags_label_unit_and_direction_mismatch(service):
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    facts = store.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    profit = next(
        item
        for item in facts
        if item["row"] == 3 and item["column"] == "contribution"
    )
    cost = next(
        item
        for item in facts
        if item["row"] == 1 and item["column"] == "contribution"
    )

    check = store.validate_explanation(
        {
            "body": "成本增加 5 元，利润减少 5 万元。",
            "run_ids": [run["id"]],
            "fact_ids": [profit["id"], cost["id"]],
        }
    )

    assert check["status"] == "needs_attention"
    assert {issue["code"] for issue in check["issues"]} >= {
        "fact_label_mismatch",
        "fact_unit_mismatch",
        "fact_direction_mismatch",
    }
    mismatch = next(issue for issue in check["issues"] if issue["code"] == "fact_label_mismatch")
    assert mismatch["text"] == "5"
    assert "成本增加 5 元" in mismatch["body_excerpt"]
    assert mismatch["expected_metric"] == "cost"
    assert any("profit" in label for label in mismatch["matched_fact_labels"])
    assert "profit" in mismatch["matched_fact_metrics"]


def test_background_versions_match_scope_and_effective_period(service, tmp_path):
    store, context = service
    note = tmp_path / "note.md"
    note.write_text("9月广告投放提前。\n\n10月不适用。", encoding="utf-8")
    dataset = store.analysis.add_dataset(note, name="会议纪要")
    kept = store.finance_background_save(
        {
            "text": "9月广告投放提前",
            "basis": "professional_judgment",
            "scope": {"ledger": "L1", "organization": "O1", "currency": "CNY", "unit": "万元"},
            "effective_from": "2026-09",
            "effective_to": "2026-09",
            "dataset_id": dataset["id"],
            "paragraph": 1,
            "label": "广告节奏",
        }
    )
    store.finance_background_save(
        {
            "text": "另一账套原因",
            "basis": "professional_judgment",
            "scope": {"ledger": "L2", "organization": "O1"},
            "effective_from": "2026-09",
        }
    )

    run = store.explain_variance({"context_id": context["id"]})
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    assert [row["id"] for row in prepared["business_contexts"]] == [kept["id"]]

    october = store.finance_background_list(
        {
            "scope": {"ledger": "L1", "organization": "O1", "currency": "CNY", "unit": "万元"},
            "as_of": "2026-10",
        }
    )
    assert october["business_contexts"] == []
    assert store.finance_background_list({})["business_contexts"] == []


def test_background_source_fact_requires_authorized_matching_paragraph(service, tmp_path):
    store, context = service
    note = tmp_path / "note.md"
    note.write_text("9月广告投放提前。\n\n10月不适用。", encoding="utf-8")
    dataset = store.analysis.add_dataset(note, name="会议纪要")

    with pytest.raises(FoundryError, match="source_fact background requires dataset_id"):
        store.finance_background_save(
            {
                "text": "9月广告投放提前",
                "basis": "source_fact",
                "scope": {"ledger": "L1", "organization": "O1"},
                "effective_from": "2026-09",
            }
        )
    with pytest.raises(FoundryError, match="background text must come from paragraph"):
        store.finance_background_save(
            {
                "text": "不存在的原因",
                "basis": "source_fact",
                "scope": {"ledger": "L1", "organization": "O1"},
                "effective_from": "2026-09",
                "dataset_id": dataset["id"],
                "paragraph": 1,
            }
        )

    saved = store.finance_background_save(
        {
            "text": "广告投放提前",
            "basis": "source_fact",
            "context_id": context["id"],
            "effective_from": "2026-09",
            "dataset_id": dataset["id"],
            "paragraph": 1,
        }
    )
    assert saved["source"]["dataset_id"] == dataset["id"]
    assert saved["source"]["paragraph_text"] == "9月广告投放提前。"


def test_background_dates_and_external_references_are_validated(service):
    store, _context = service
    base = {
        "text": "行业价格上涨",
        "scope": {"ledger": "L1", "organization": "O1"},
        "effective_from": "2026-09",
    }
    with pytest.raises(FoundryError, match="effective_from must be YYYY-MM"):
        store.finance_background_save({**base, "effective_from": "soon"})
    with pytest.raises(FoundryError, match="effective_to cannot be earlier"):
        store.finance_background_save({**base, "effective_to": "2026-08"})
    with pytest.raises(FoundryError, match="external_reference requires"):
        store.finance_background_save({**base, "basis": "external_reference"})
    with pytest.raises(FoundryError, match="external_reference date"):
        store.finance_background_save(
            {
                **base,
                "basis": "external_reference",
                "external_reference": {"title": "价格指数", "source_date": "last week"},
            }
        )

    saved = store.finance_background_save(
        {
            **base,
            "basis": "external_reference",
            "external_reference": {
                "title": "价格指数",
                "url": "https://example.com/price",
                "source_date": "2026-09-01",
            },
        }
    )
    assert saved["external_reference"]["source_date"] == "2026-09-01"


def test_background_list_defaults_to_current_period_and_handles_null_source_parent(service):
    store, _context = service
    current = store.finance_background_save(
        {
            "text": "本期投放提前",
            "basis": "professional_judgment",
            "scope": {"ledger": "L1", "organization": "O1"},
            "effective_from": "2026-09",
            "effective_to": "2026-09",
        }
    )
    store.finance_background_save(
        {
            "text": "上期事项",
            "basis": "professional_judgment",
            "scope": {"ledger": "L1", "organization": "O1"},
            "effective_from": "2026-08",
            "effective_to": "2026-08",
        }
    )
    store.finance_background_save(
        {
            "text": "未来事项",
            "basis": "professional_judgment",
            "scope": {"ledger": "L1", "organization": "O1"},
            "effective_from": "2026-10",
        }
    )

    listed = store.finance_background_list(
        {"scope": {"ledger": "L1", "organization": "O1"}}
    )
    assert [row["id"] for row in listed["business_contexts"]] == [current["id"]]

    child = store.finance_background_save(
        {
            "parent_id": current["id"],
            "text": "本期投放提前，口径更新",
            "effective_from": "2026-09",
        }
    )
    assert child["parent_id"] == current["id"]


def test_numeric_tokens_cover_percent_chinese_and_avoid_substrings(service):
    from foundry.finance_explanations import _body_numbers, _numbers_from_text
    assert _numbers_from_text('58.33%') == {'0.5833'}
    assert [v['text'] for v in _body_numbers('利润5万元，成本15万元，期间2026-09，单号INV-007。')] == ['5', '15']
    store, context = service
    run = store.explain_variance({'context_id': context['id']})
    facts = store.prepare_explanation({'run_ids': [run['id']]})['facts']
    selected = [f for f in facts if f['column'] == 'contribution']
    checked = store.validate_explanation({'body': '收入增加20万元；成本增加10万元，对利润影响-10万元；费用增加5万元，对利润影响-5万元。合计利润增加5万元。', 'run_ids': [run['id']], 'fact_ids': [f['id'] for f in selected]})
    assert checked['status'] == 'pass', checked['issues']


def test_numeric_tokens_ignore_spreadsheet_references_but_keep_amounts():
    from foundry.finance_explanations import _body_numbers

    body = "04·合并利润表 F39=200,000,001 元，与预算本 01!O46 一致；1·revenue 仍为 7 万元；利润7!仍需核对。"

    assert [item["text"] for item in _body_numbers(body)] == ["200,000,001", "1", "7", "7"]


def test_source_less_background_stays_with_authorized_context(service):
    store, context = service
    saved = store.finance_background_save({'text': '投放提前', 'basis': 'professional_judgment', 'context_id': context['id'], 'effective_from': '2026-09'})
    limited = FinanceStore(store.task, snapshot_ids=[])
    with pytest.raises(FoundryError, match='outside|authorized'):
        limited.finance_background_list({'scope': {'ledger': 'L1', 'organization': 'O1'}})
    assert set(saved['bindings'].values()) == set(context['bindings'].values())
    with pytest.raises(FoundryError, match='outside|authorized'):
        limited.validate_explanation({'body': '原始金额120万元', 'claims': [{'basis': 'calculation', 'run_id': store.explain_variance({'context_id': context['id']})['id'], 'row': 0, 'column': 'actual', 'value': '120'}]})


def test_background_revisions_reuse_latest_applicable_text(service):
    store, context = service
    parent = store.finance_background_save({'text': '初步判断', 'context_id': context['id'], 'effective_from': '2026-09'})
    child = store.finance_background_save({'text': '修正后的判断', 'parent_id': parent['id']})
    listed = store.finance_background_list({'context_id': context['id'], 'as_of': '2026-09'})
    assert [r['id'] for r in listed['business_contexts']] == [child['id']]
    for invalid in ('2026-13', '2026-02-30'):
        with pytest.raises(FoundryError, match='date|YYYY'):
            store.finance_background_save({'text': 'x', 'context_id': context['id'], 'effective_from': invalid})


@pytest.mark.parametrize('row', [-1, True])
def test_manual_claim_validation_rejects_invalid_row(service, row):
    store, context = service
    run = store.explain_variance({'context_id': context['id']})
    check = store.validate_explanation({'body': '利润5万元', 'run_ids': [run['id']], 'claims': [
        {'basis': 'calculation', 'run_id': run['id'], 'row': row, 'column': 'contribution', 'value': '5'}]})
    assert check['status'] == 'needs_attention'
    assert any(i['code'] == 'invalid_claim_location' for i in check['issues'])


def test_manual_claim_cannot_supply_its_own_display_value_or_omit_run(service):
    store, context = service
    run = store.explain_variance({'context_id': context['id']})
    claim = {'basis': 'calculation', 'run_id': run['id'], 'row': 3, 'column': 'contribution', 'value': '5', 'display_value': '999 万元'}
    check = store.validate_explanation({'body': '利润999万元', 'run_ids': [run['id']], 'claims': [claim]})
    assert check['status'] == 'needs_attention'
    assert any(i['code'] == 'uncited_number' for i in check['issues'])
    good = store.validate_explanation({'body': '利润超预算5万元', 'run_ids': [run['id']], 'claims': [claim]})
    assert good['status'] == 'needs_attention'
    assert any(i['code'] == 'missing_required_fact' for i in good['issues'])
    assert good['coverage']['referenced_fact_count'] == 1
    omitted = store.validate_explanation({'body': '利润超预算5万元', 'run_ids': [], 'claims': [claim]})
    assert omitted['status'] == 'needs_attention'
    assert any(i['code'] == 'invalid_claim_location' for i in omitted['issues'])


def test_zero_reconciliation_facts_remain_required(service):
    from foundry.finance_explanations import prepare_explanation
    store, _ = service
    payload = prepare_explanation(store.analysis, [{'id': 'zero-run', 'execution_status': 'succeeded', 'output_hash': 'fixed', 'result': {'columns': ['contribution', 'profit_impact', 'actual', 'baseline', 'interaction', 'residual'], 'rows': [
        {'metric': 'profit', 'contribution': '0', 'profit_impact': '0', 'actual': '10', 'baseline': '10', 'unit': '万元'},
        {'interaction': '0', 'residual': '0', 'unit': '元'},
    ]}}], materiality={'absolute': '100'})
    required = [fact for fact in payload['facts'] if fact['id'] in payload['required_fact_ids']]
    assert {(fact['row'], fact['column']) for fact in required} == {(0, 'contribution'), (1, 'interaction'), (1, 'residual')}
    assert all(fact['state'] == 'observed_zero' for fact in required)


def test_evidence_appendix_renders_zero_facts_and_claims(service):
    from foundry.finance_explanations import prepare_explanation, render_evidence_appendix

    store, _ = service
    payload = prepare_explanation(store.analysis, [{'id': 'zero-run', 'execution_status': 'succeeded', 'output_hash': 'fixed', 'result': {'method': 'quantity_then_price', 'columns': ['product', 'total_variance', 'quantity_contribution', 'price_contribution', 'interaction', 'residual'], 'rows': [
        {'product': '商品A', 'total_variance': '32', 'quantity_contribution': '20', 'price_contribution': '12', 'interaction': '0', 'residual': '0', 'unit': '元', 'source_rows': [{'dataset_id': 'd1', 'row': 1}]},
    ]}}])

    appendix = render_evidence_appendix(payload)

    assert '## 计算依据' in appendix['body']
    assert 'interaction：0 元（已计算为零；有来源行）' in appendix['body']
    assert 'residual：0 元（已计算为零；有来源行）' in appendix['body']
    assert '来源行 1' not in appendix['body']
    assert {claim['fact_id'] for claim in appendix['claims']} == set(appendix['fact_ids'])


def test_evidence_appendix_does_not_cite_unbacked_members(service):
    from foundry.finance_explanations import render_evidence_appendix

    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    backed = prepared["facts"][0]
    missing_fact_id = "e" * 64
    prepared["evidence_groups"] = [
        {
            "id": "appendix-regression",
            "run_id": backed["run_id"],
            "group_type": "profit_bridge",
            "label": "附录事实绑定",
            "members": [
                {
                    "row": backed["row"],
                    "column": backed["column"],
                    "label": "已验证金额",
                    "state": backed["state"],
                    "fact_id": backed["id"],
                    "value": backed["value"],
                    "display_value": backed["display_value"],
                    "unit": backed["unit"],
                    "source_row_count": 1,
                },
                {
                    "row": backed["row"],
                    "column": "profit_impact",
                    "label": "未生成事实成员",
                    "state": "nonzero",
                    "fact_id": None,
                    "value": "20",
                    "display_value": "20 万元",
                    "unit": "万元",
                    "source_row_count": 0,
                },
                {
                    "row": backed["row"],
                    "column": backed["column"],
                    "label": "错配事实成员",
                    "state": "nonzero",
                    "fact_id": missing_fact_id,
                    "value": "999",
                    "display_value": "999 万元",
                    "unit": "万元",
                    "source_row_count": 1,
                },
                {
                    "row": backed["row"],
                    "column": backed["column"],
                    "label": "同ID值错配成员",
                    "state": "nonzero",
                    "fact_id": backed["id"],
                    "value": "999",
                    "display_value": "999 万元",
                    "unit": backed["unit"],
                    "source_row_count": 1,
                },
                {
                    "row": backed["row"],
                    "column": backed["column"],
                    "label": "同ID单位错配成员",
                    "state": "nonzero",
                    "fact_id": backed["id"],
                    "value": backed["value"],
                    "display_value": backed["display_value"],
                    "unit": "元",
                    "source_row_count": 1,
                },
                {
                    "row": backed["row"],
                    "column": backed["column"],
                    "label": "同ID范围错配成员",
                    "state": "nonzero",
                    "fact_id": backed["id"],
                    "value": backed["value"],
                    "display_value": backed["display_value"],
                    "unit": backed["unit"],
                    "scope": {"period": "2099-12"},
                    "source_row_count": 1,
                },
            ],
            "closure": {"status": "passed"},
        }
    ]

    appendix = render_evidence_appendix(prepared)

    assert backed["id"] in appendix["fact_ids"]
    assert missing_fact_id not in appendix["fact_ids"]
    assert appendix["fact_ids"] == [backed["id"]]
    assert "已验证金额" in appendix["body"]
    assert "未生成事实成员：20 万元（已计算" not in appendix["body"]
    assert "错配事实成员：999 万元（已计算" not in appendix["body"]
    assert "同ID值错配成员：999 万元（已计算" not in appendix["body"]
    assert "同ID单位错配成员" in appendix["body"]
    assert "同ID范围错配成员" in appendix["body"]
    assert "未生成事实成员（非可引用" in appendix["body"]
    assert "错配事实成员（非可引用" in appendix["body"]
    assert "同ID值错配成员（非可引用" in appendix["body"]
    assert "同ID单位错配成员（非可引用" in appendix["body"]
    assert "同ID范围错配成员（非可引用" in appendix["body"]
    assert {claim["fact_id"] for claim in appendix["claims"]} == set(appendix["fact_ids"])


def test_evidence_groups_distinguish_missing_from_not_applicable(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{'id': 'partial-run', 'execution_status': 'succeeded', 'output_hash': 'fixed', 'result': {'columns': ['metric', 'contribution', 'profit_impact'], 'rows': [
        {'metric': 'revenue', 'contribution': None, 'unit': '万元'},
    ]}}])
    group = payload['evidence_groups'][0]

    assert group['status'] == 'missing_data'
    states = {(member['column'], member['state']) for member in group['members']}
    assert ('contribution', 'missing') in states
    assert ('amount_change', 'not_applicable') in states


def test_relative_materiality_records_denominator_zero_and_negative_policy(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{'id': 'relative-run', 'execution_status': 'succeeded', 'output_hash': 'fixed', 'result': {'columns': ['metric', 'actual', 'baseline', 'contribution'], 'rows': [
        {'metric': 'profit', 'actual': '5', 'baseline': '0', 'contribution': '5', 'unit': '万元'},
        {'metric': 'cost', 'actual': '-120', 'baseline': '-100', 'contribution': '-20', 'unit': '万元'},
    ]}}], materiality={'absolute': '1000', 'relative': {'threshold': '0.1', 'denominator': 'baseline_abs'}})
    by_metric = {
        fact['semantics']['metric']: fact['semantics']['materiality']['relative']
        for fact in payload['facts']
        if fact['column'] == 'contribution'
    }

    assert by_metric['profit']['status'] == 'denominator_zero'
    assert by_metric['profit']['is_material'] is False
    assert by_metric['cost']['denominator_value'] == '100'
    assert by_metric['cost']['ratio'] == '0.2'
    assert by_metric['cost']['is_material'] is True


def test_signed_relative_materiality_preserves_negative_denominator_direction(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{'id': 'signed-relative-run',
        'execution_status': 'succeeded', 'output_hash': 'fixed',
        'result': {'columns': ['metric', 'actual', 'baseline', 'contribution'], 'rows': [
            {'metric': 'cost', 'actual': '-120', 'baseline': '-100',
             'contribution': '20', 'unit': '万元'},
            {'metric': 'expense', 'actual': '-80', 'baseline': '-100',
             'contribution': '-20', 'unit': '万元'},
        ]}}], materiality={'absolute': '1000',
                           'relative': {'threshold': '0.1',
                                        'denominator': 'baseline_abs',
                                        'negative_policy': 'signed'}})
    by_metric = {
        fact['semantics']['metric']: fact['semantics']['materiality']['relative']
        for fact in payload['facts']
        if fact['column'] == 'contribution'
    }

    assert by_metric['cost']['denominator_value'] == '-100'
    assert by_metric['cost']['ratio'] == '-0.2'
    assert by_metric['cost']['absolute_ratio'] == '0.2'
    assert by_metric['cost']['is_material'] is True
    assert by_metric['cost']['status'] == 'negative_denominator'
    assert by_metric['expense']['ratio'] == '0.2'
    assert by_metric['expense']['absolute_ratio'] == '0.2'
    assert by_metric['expense']['status'] == 'negative_denominator'


def test_profit_bridge_evidence_group_checks_mathematical_closure(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{'id': 'bad-bridge', 'execution_status': 'succeeded', 'output_hash': 'fixed', 'result': {'method': 'revenue_minus_cost_minus_expense', 'columns': ['metric', 'contribution', 'unit'], 'rows': [
        {'metric': 'revenue', 'contribution': '20', 'unit': '万元'},
        {'metric': 'cost', 'contribution': '-10', 'unit': '万元'},
        {'metric': 'expense', 'contribution': '-5', 'unit': '万元'},
        {'metric': 'profit', 'contribution': '6', 'unit': '万元'},
    ]}}])
    closure = payload['evidence_groups'][0]['closure']

    assert payload['evidence_groups'][0]['status'] == 'closure_mismatch'
    assert closure == {
        'status': 'closure_mismatch',
        'equation': 'profit = revenue + cost + expense',
        'expected': '5',
        'actual': '6',
        'difference': '1',
        'inputs': {'revenue': '20', 'cost': '-10', 'expense': '-5', 'profit': '6'},
    }


def test_price_quantity_evidence_group_checks_mathematical_closure(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{'id': 'bad-pq', 'execution_status': 'succeeded', 'output_hash': 'fixed', 'result': {'method': 'quantity_then_price', 'columns': ['product', 'total_variance', 'quantity_contribution', 'price_contribution', 'interaction', 'residual', 'unit'], 'rows': [
        {'product': '商品A', 'total_variance': '31', 'quantity_contribution': '20', 'price_contribution': '12', 'interaction': '0', 'residual': '0', 'unit': '元'},
    ]}}])
    closure = payload['evidence_groups'][0]['closure']

    assert closure['status'] == 'closure_mismatch'
    assert closure['equation'] == 'total_variance = quantity_contribution + price_contribution + interaction + residual'
    assert closure['expected'] == '32'
    assert closure['actual'] == '31'
    assert closure['difference'] == '-1'


def test_evidence_group_rejects_mismatched_units_and_scopes(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    unit_payload = prepare_explanation(store.analysis, [{'id': 'unit-run', 'execution_status': 'succeeded', 'output_hash': 'fixed', 'result': {'method': 'revenue_minus_cost_minus_expense', 'columns': ['metric', 'contribution', 'unit'], 'rows': [
        {'metric': 'revenue', 'contribution': '20', 'unit': '万元'},
        {'metric': 'cost', 'contribution': '-10', 'unit': '元'},
        {'metric': 'expense', 'contribution': '-5', 'unit': '万元'},
        {'metric': 'profit', 'contribution': '5', 'unit': '万元'},
    ]}}])
    scope_payload = prepare_explanation(store.analysis, [{'id': 'scope-run', 'execution_status': 'succeeded', 'output_hash': 'fixed', 'result': {'method': 'revenue_minus_cost_minus_expense', 'columns': ['metric', 'contribution', 'actual_scope'], 'rows': [
        {'metric': 'revenue', 'contribution': '20', 'unit': '万元', 'actual_scope': {'ledger': 'L1'}},
        {'metric': 'cost', 'contribution': '-10', 'unit': '万元', 'actual_scope': {'ledger': 'L1'}},
        {'metric': 'expense', 'contribution': '-5', 'unit': '万元', 'actual_scope': {'ledger': 'L1'}},
        {'metric': 'profit', 'contribution': '5', 'unit': '万元', 'actual_scope': {'ledger': 'L2'}},
    ]}}])

    assert unit_payload['evidence_groups'][0]['closure']['status'] == 'unit_mismatch'
    assert scope_payload['evidence_groups'][0]['closure']['status'] == 'scope_mismatch'


def test_generic_sql_groups_are_marked_unsupported_without_forcing_actual_baseline(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{'id': 'sql-run', 'execution_status': 'succeeded', 'output_hash': 'fixed', 'result': {'columns': ['actual', 'baseline', 'custom_margin'], 'rows': [
        {'actual': '120', 'baseline': '100', 'custom_margin': '20', 'unit': '万元'},
    ]}}])
    required = {
        fact['column']
        for fact in payload['facts']
        if fact['id'] in payload['required_fact_ids']
    }

    assert payload['evidence_groups'][0]['status'] == 'unsupported'
    assert payload['evidence_groups'][0]['closure']['status'] == 'unsupported'
    assert required == {'custom_margin'}


def test_sql_percentage_points_render_once_and_reject_hundredfold_body(service):
    store, context = service
    revision = store.analysis.save_analysis({'question': 'percentage points', 'bindings': context['bindings'],
        'sql': 'SELECT CAST(58.33 AS DECIMAL(10,2)) AS cost_rate_pct FROM actual LIMIT 1'})
    run = store.analysis.run_analysis(revision['id'])
    prepared = store.prepare_explanation({'run_ids': [run['id']]})
    fact = next(f for f in prepared['facts'] if f['column'] == 'cost_rate_pct')
    assert fact['display_value'] == '58.33%'
    for body, expected in [('成本率58.33%。', 'pass'), ('成本率5833%。', 'needs_attention')]:
        check = store.validate_explanation({'body': body, 'run_ids': [run['id']], 'fact_ids': [fact['id']]})
        assert check['status'] == expected


def test_generic_calculation_row_uses_declared_column_types_for_missing_members(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{
        "id": "typed-generic",
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": [
                {"name": "ledger", "type": "VARCHAR"},
                {"name": "organization", "type": "VARCHAR"},
                {"name": "period", "type": "VARCHAR"},
                {"name": "account_id", "type": "VARCHAR"},
                {"name": "display_value", "type": "VARCHAR"},
                {"name": "period_span", "type": "INTERVAL"},
                {"name": "geo_point", "type": "POINT"},
                {"name": "amount", "type": "DECIMAL(18,2)"},
            ],
            "rows": [{
                "ledger": "L1",
                "organization": "总部",
                "period": "2026-08",
                "account_id": "1001",
                "display_value": "暂无金额",
                "period_span": None,
                "geo_point": None,
                "amount": None,
                "unit": "万元",
            }],
        },
    }])

    group = payload["evidence_groups"][0]
    assert group["status"] == "missing_data"
    assert [(member["column"], member["state"]) for member in group["members"]] == [("amount", "missing")]


def test_generic_value_column_uses_row_unit_without_relaxing_ratio_or_count(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    run = _write_synthetic_run(store.analysis, {
        "id": "99999999999999999999999999999999",
        "bindings": {},
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": [
                {"name": "metric", "type": "VARCHAR"},
                {"name": "value", "type": "DECIMAL(38,4)"},
                {"name": "ratio", "type": "DECIMAL(18,6)"},
                {"name": "row_count", "type": "INTEGER"},
                {"name": "unit", "type": "VARCHAR"},
            ],
            "rows": [{
                "metric": "revenue_ytd",
                "value": "3256440000",
                "ratio": "0.0398",
                "row_count": "50",
                "unit": "元",
            }],
        },
    })
    prepared = prepare_explanation(store.analysis, [run])
    facts = {fact["column"]: fact for fact in prepared["facts"]}

    assert facts["value"]["display_value"] == "3256440000 元"
    assert facts["value"]["unit"] == "元"
    assert facts["ratio"]["display_value"] == "3.98%"
    assert facts["ratio"]["unit"] == "%"
    assert facts["row_count"]["display_value"] == "50 条"
    assert facts["row_count"]["unit"] == "条"

    checked = store.validate_explanation({
        "body": "04·合并利润表 C5=3256440000 元；归母净利率 3.98%，城市公司 50 条。",
        "run_ids": [run["id"]],
        "fact_ids": [fact["id"] for fact in facts.values()],
    })

    assert checked["status"] == "pass", checked["issues"]


def test_chinese_wide_result_reads_row_unit_and_keeps_ratio_percent(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    run = _write_synthetic_run(store.analysis, {
        "id": "abababababababababababababababab",
        "bindings": {},
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "scope": {"organization": "合并", "unit": "万元"},
        "result": {
            "columns": [
                {"name": "项目", "type": "VARCHAR"},
                {"name": "收入_实际_1_8月", "type": "DECIMAL(38,4)"},
                {"name": "收入_达成率_1_8月", "type": "DECIMAL(18,6)"},
                {"name": "单位", "type": "VARCHAR"},
            ],
            "rows": [{
                "项目": "营业收入",
                "收入_实际_1_8月": "325644.0000",
                "收入_达成率_1_8月": "0.945301",
                "单位": "万元",
            }],
        },
    })

    prepared = prepare_explanation(store.analysis, [run])
    facts = {fact["column"]: fact for fact in prepared["facts"]}
    members = {
        member["column"]: member
        for member in prepared["evidence_groups"][0]["members"]
    }

    assert facts["收入_实际_1_8月"]["unit"] == "万元"
    assert facts["收入_实际_1_8月"]["display_value"] == "325,644.0000 万元"
    assert facts["收入_实际_1_8月"]["semantics"]["role"] == "amount"
    assert members["收入_实际_1_8月"]["semantic_role"] == "amount"
    assert facts["收入_达成率_1_8月"]["unit"] == "%"
    assert facts["收入_达成率_1_8月"]["display_value"] == "94.53%"
    assert facts["收入_达成率_1_8月"]["semantics"]["role"] == "ratio"
    assert members["收入_达成率_1_8月"]["semantic_role"] == "ratio"


def test_chinese_wide_result_uses_run_scope_unit_without_leaking_to_ratio(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    run = _write_synthetic_run(store.analysis, {
        "id": "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
        "bindings": {},
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "scope": {"organization": "合并", "unit": "万元"},
        "result": {
            "columns": [
                {"name": "项目", "type": "VARCHAR"},
                {"name": "经营利润_实际_1_8月", "type": "DECIMAL(38,4)"},
                {"name": "利润达成率_1_8月", "type": "DECIMAL(18,6)"},
            ],
            "rows": [{
                "项目": "经营利润",
                "经营利润_实际_1_8月": "24564.3000",
                "利润达成率_1_8月": "0.775438",
            }],
        },
    })

    prepared = prepare_explanation(store.analysis, [run])
    facts = {fact["column"]: fact for fact in prepared["facts"]}

    assert facts["经营利润_实际_1_8月"]["unit"] == "万元"
    assert facts["经营利润_实际_1_8月"]["display_value"] == "24,564.3000 万元"
    assert facts["利润达成率_1_8月"]["unit"] == "%"
    assert facts["利润达成率_1_8月"]["display_value"] == "77.54%"



def test_generic_value_fact_uses_metric_key_for_semantics_without_changing_value_contract(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{
        "id": "metric-key-run",
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": [
                {"name": "metric_key", "type": "VARCHAR"},
                {"name": "value", "type": "DECIMAL(38,4)"},
                {"name": "unit", "type": "VARCHAR"},
            ],
            "rows": [{
                "metric_key": "operating_profit",
                "value": "21086.0000",
                "unit": "万元",
                "scenario": "actual_ytd",
            }],
        },
    }])
    fact = next(fact for fact in payload["facts"] if fact["column"] == "value")

    assert fact["value"] == "21086.0000"
    assert fact["semantics"]["metric"] == "operating_profit"
    assert fact["label"] == "operating_profit / value / actual_ytd"


def test_english_ratio_detection_uses_tokens_not_substrings(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    run = _write_synthetic_run(store.analysis, {
        "id": "efefefefefefefefefefefefefefefef",
        "bindings": {},
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": [
                {"name": "corporate_expense", "type": "DECIMAL(38,4)"},
                {"name": "operational_cost", "type": "DECIMAL(38,4)"},
                {"name": "duration_months", "type": "DECIMAL(38,4)"},
                {"name": "attainment_rate", "type": "DECIMAL(18,6)"},
                {"name": "unit", "type": "VARCHAR"},
            ],
            "rows": [{
                "corporate_expense": "100",
                "operational_cost": "100",
                "duration_months": "100",
                "attainment_rate": "1",
                "unit": "万元",
            }],
        },
    })

    prepared = prepare_explanation(store.analysis, [run])
    facts = {fact["column"]: fact for fact in prepared["facts"]}

    assert facts["corporate_expense"]["semantics"]["role"] == "amount"
    assert facts["corporate_expense"]["display_value"] == "100 万元"
    assert facts["operational_cost"]["semantics"]["role"] == "amount"
    assert facts["operational_cost"]["display_value"] == "100 万元"
    assert facts["duration_months"]["semantics"]["role"] == "value"
    assert facts["duration_months"]["display_value"] == "100"
    assert facts["attainment_rate"]["semantics"]["role"] == "ratio"
    assert facts["attainment_rate"]["display_value"] == "100.00%"



@pytest.mark.parametrize("identity_type", ["VARCHAR", "INTEGER"])
def test_typed_identity_columns_do_not_become_amount_facts(service, identity_type):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{
        "id": "typed-identities",
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": [
                {"name": "ledger", "type": identity_type},
                {"name": "account_id", "type": identity_type},
                {"name": "period", "type": "VARCHAR"},
                {"name": "amount", "type": "DECIMAL(18,2)"},
                {"name": "numerator_exact", "type": "VARCHAR"},
                {"name": "denominator_exact", "type": "VARCHAR"},
                {"name": "ratio_exact", "type": "VARCHAR"},
            ],
            "rows": [{
                "ledger": "202609",
                "account_id": "1001",
                "period": "2026-08",
                "amount": "5",
                "numerator_exact": "70",
                "denominator_exact": "120",
                "ratio_exact": "0.58333333333333333333333333333333333333333333333333333333333333333333333333333333",
                "unit": "万元",
            }],
        },
    }])
    by_column = {fact["column"]: fact for fact in payload["facts"]}

    assert set(by_column) == {"amount", "numerator_exact", "denominator_exact", "ratio_exact"}
    assert by_column["amount"]["display_value"] == "5 万元"
    assert by_column["numerator_exact"]["display_value"] == "70 万元"
    assert by_column["denominator_exact"]["display_value"] == "120 万元"
    assert by_column["ratio_exact"]["display_value"] == "58.33%"


def test_control_totals_row_count_keeps_count_unit_and_rejects_money_unit(service):
    store, context = service
    run = store.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    row_count = next(fact for fact in prepared["facts"] if fact["column"] == "row_count")
    amount = next(
        fact
        for fact in prepared["facts"]
        if fact["column"] == "amount" and fact["value"] == "120"
    )

    assert row_count["value"] == "1"
    assert row_count["display_value"] == "1 条"
    assert row_count["unit"] == "条"
    assert row_count["semantics"]["role"] == "count"
    assert row_count["source_trace"]["source_row_count"] == 1
    assert amount["display_value"] == "120 万元"
    assert amount["unit"] == "万元"
    assert amount["semantics"]["role"] == "amount"

    good = store.validate_explanation({
        "body": "控制合计记录数为 1 条。",
        "run_ids": [run["id"]],
        "fact_ids": [row_count["id"]],
        "materiality": {"absolute": "1000"},
    })
    bad = store.validate_explanation({
        "body": "控制合计记录数为 1 元。",
        "run_ids": [run["id"]],
        "fact_ids": [row_count["id"]],
        "materiality": {"absolute": "1000"},
    })

    assert good["status"] == "pass", good["issues"]
    assert bad["status"] == "needs_attention"
    assert any(issue["code"] == "fact_unit_mismatch" for issue in bad["issues"])


def test_evidence_appendix_renders_control_count_without_money_unit(service):
    from foundry.finance_explanations import render_evidence_appendix

    store, context = service
    run = store.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})

    appendix = render_evidence_appendix(prepared)

    assert "row_count / actual / 2026-09：1 条（已计算；有来源行）" in appendix["body"]
    assert "row_count / actual / 2026-09：1 万元" not in appendix["body"]


def test_generated_appendix_row_headings_do_not_trigger_uncited_numbers(service):
    store, context = service
    run = store.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})

    draft = store.save_explanation_draft({
        "body": "控制合计见计算依据。",
        "run_ids": [run["id"]],
    })

    assert draft["body"].count("row_count /") >= 2
    assert "### 结果行 2" in draft["body"]
    assert "uncited_number" not in {
        issue["code"] for issue in draft["explanation_check"]["issues"]
    }


def test_tampered_appendix_amount_still_fails_number_check(service):
    from foundry.finance_explanations import render_evidence_appendix

    store, context = service
    run = store.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    appendix = render_evidence_appendix(prepared)
    tampered = appendix["body"].replace("120 万元", "121 万元", 1)
    assert tampered != appendix["body"]

    check = store.validate_explanation({
        "body": tampered,
        "run_ids": [run["id"]],
        "fact_ids": appendix["fact_ids"],
        "claims": appendix["claims"],
    })

    assert check["status"] == "needs_attention"
    assert any(
        issue["code"] == "uncited_number" and issue.get("text") == "121"
        for issue in check["issues"]
    )


def test_manual_calculation_claim_without_fact_stays_unknown(service):
    store, _ = service
    run = _write_synthetic_run(store.analysis, {
        "id": "dddddddddddddddddddddddddddddddd",
        "bindings": {},
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": ["metric", "contribution"],
            "rows": [{
                "metric": "revenue",
                "contribution": "20",
                "profit_impact": "20",
                "unit": "万元",
            }],
        },
    })

    check = store.validate_explanation({
        "body": "收入利润影响20万元。",
        "run_ids": [run["id"]],
        "claims": [{
            "basis": "calculation",
            "run_id": run["id"],
            "row": 0,
            "column": "profit_impact",
            "value": "20",
            "display_value": "20 万元",
        }],
    })

    assert check["status"] == "needs_attention"
    assert any(issue["code"] == "unknown_fact" for issue in check["issues"])


def test_quantity_and_unit_price_do_not_inherit_money_unit_without_explicit_unit(service):
    store, _ = service
    run = _write_synthetic_run(store.analysis, {
        "id": "cccccccccccccccccccccccccccccccc",
        "bindings": {},
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": [
                {"name": "quantity", "type": "DECIMAL"},
                {"name": "actual_quantity", "type": "DECIMAL", "unit": "件"},
                {"name": "unit_price", "type": "DECIMAL"},
                {"name": "actual_price", "type": "DECIMAL", "unit": "元/件"},
                {"name": "amount", "type": "DECIMAL"},
            ],
            "rows": [{
                "quantity": "2",
                "actual_quantity": "3",
                "unit_price": "9",
                "actual_price": "10",
                "amount": "18",
                "unit": "万元",
            }],
        },
    })
    payload = store.prepare_explanation({"run_ids": [run["id"]]})
    facts = {fact["column"]: fact for fact in payload["facts"]}

    assert facts["quantity"]["display_value"] == "2"
    assert facts["quantity"].get("unit") is None
    assert facts["quantity"]["semantics"]["role"] == "quantity"
    assert facts["actual_quantity"]["display_value"] == "3 件"
    assert facts["actual_quantity"]["unit"] == "件"
    assert facts["unit_price"]["display_value"] == "9"
    assert facts["unit_price"].get("unit") is None
    assert facts["unit_price"]["semantics"]["role"] == "unit_price"
    assert facts["actual_price"]["display_value"] == "10 元/件"
    assert facts["actual_price"]["unit"] == "元/件"
    assert facts["amount"]["display_value"] == "18 万元"

    unknown_quantity = store.validate_explanation({
        "body": "数量为 2 万元。",
        "run_ids": [run["id"]],
        "fact_ids": [facts["quantity"]["id"]],
        "materiality": {"absolute": "1000"},
    })
    quantity_with_unit = store.validate_explanation({
        "body": "数量为 3 件。",
        "run_ids": [run["id"]],
        "fact_ids": [facts["actual_quantity"]["id"]],
        "materiality": {"absolute": "1000"},
    })
    unit_price = store.validate_explanation({
        "body": "单价为 10 元/件。",
        "run_ids": [run["id"]],
        "fact_ids": [facts["actual_price"]["id"]],
        "materiality": {"absolute": "1000"},
    })

    assert unknown_quantity["status"] == "needs_attention"
    assert any(issue["code"] == "fact_unit_mismatch" for issue in unknown_quantity["issues"])
    assert quantity_with_unit["status"] == "pass", quantity_with_unit["issues"]
    assert unit_price["status"] == "pass", unit_price["issues"]


def test_actual_and_baseline_quantity_share_quantity_unit_without_money_fallback(service):
    store, _ = service
    run = _write_synthetic_run(store.analysis, {
        "id": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "bindings": {},
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": [
                {"name": "actual_quantity", "type": "DECIMAL"},
                {"name": "baseline_quantity", "type": "DECIMAL"},
                {"name": "amount", "type": "DECIMAL"},
            ],
            "rows": [{
                "actual_quantity": "8",
                "baseline_quantity": "5",
                "quantity_unit": "件",
                "amount": "80",
                "unit": "元",
            }],
        },
    })
    payload = store.prepare_explanation({"run_ids": [run["id"]]})
    facts = {fact["column"]: fact for fact in payload["facts"]}

    assert facts["actual_quantity"]["display_value"] == "8 件"
    assert facts["actual_quantity"]["unit"] == "件"
    assert facts["actual_quantity"]["semantics"]["role"] == "quantity"
    assert facts["baseline_quantity"]["display_value"] == "5 件"
    assert facts["baseline_quantity"]["unit"] == "件"
    assert facts["baseline_quantity"]["semantics"]["role"] == "quantity"
    assert facts["amount"]["display_value"] == "80 元"


def test_source_row_count_column_is_count_not_money(service):
    from foundry.finance_explanations import prepare_explanation

    store, _ = service
    payload = prepare_explanation(store.analysis, [{
        "id": "source-count-run",
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": [
                {"name": "source_row_count", "type": "VARCHAR"},
                {"name": "amount", "type": "DECIMAL"},
            ],
            "rows": [{"source_row_count": "2", "amount": "9", "unit": "元"}],
        },
    }])
    facts = {fact["column"]: fact for fact in payload["facts"]}

    assert facts["source_row_count"]["display_value"] == "2 条"
    assert facts["source_row_count"]["unit"] == "条"
    assert facts["source_row_count"]["semantics"]["role"] == "count"
    assert facts["amount"]["display_value"] == "9 元"



def _presentation_claim_for_fact(fact, presentation):
    return {
        "basis": "calculation",
        "fact_id": fact["id"],
        "run_id": fact["run_id"],
        "row": fact["row"],
        "column": fact["column"],
        "value": fact["value"],
        "presentation": presentation,
    }


def _synthetic_single_value_fact(store, *, run_id, value, unit="万元", metric_key="operating_profit"):
    from foundry.finance_explanations import prepare_explanation

    run = _write_synthetic_run(store.analysis, {
        "id": run_id,
        "bindings": {},
        "assumptions": [],
        "execution_status": "succeeded",
        "reproducibility_status": "reproducible",
        "output_hash": "hash-" + run_id[:8],
        "result": {
            "columns": [
                {"name": "metric_key", "type": "VARCHAR"},
                {"name": "value", "type": "DECIMAL(38,18)"},
                {"name": "unit", "type": "VARCHAR"},
            ],
            "rows": [{"metric_key": metric_key, "value": value, "unit": unit, "scenario": "actual_ytd"}],
        },
    })
    fact = next(fact for fact in prepare_explanation(store.analysis, [run])["facts"] if fact["column"] == "value")
    return run, fact


def test_claim_presentation_allows_only_decimal_derived_display_tokens(service):
    store, _ = service
    run, fact = _synthetic_single_value_fact(
        store,
        run_id="11111111111111111111111111111111",
        value="21086.0040",
    )
    claim = _presentation_claim_for_fact(
        fact,
        {"decimal_places": 2, "scale": "identity", "rounding": "half_up"},
    )

    good = store.validate_explanation({"body": "管理利润为21,086.00万元。", "run_ids": [run["id"]], "claims": [claim]})
    bad = store.validate_explanation({"body": "管理利润为21,086.01万元。", "run_ids": [run["id"]], "claims": [claim]})
    percent_unit = store.validate_explanation({"body": "管理利润为21,086.00%。", "run_ids": [run["id"]], "claims": [claim]})

    budget_run, budget_fact = _synthetic_single_value_fact(
        store,
        run_id="66666666666666666666666666666666",
        value="64441.3769",
    )
    budget_claim = _presentation_claim_for_fact(
        budget_fact,
        {"decimal_places": 2, "scale": "identity", "rounding": "half_up"},
    )
    matching_unit = store.validate_explanation({"body": "预算为64,441.38 万元。", "run_ids": [budget_run["id"]], "claims": [budget_claim]})
    mismatched_unit = store.validate_explanation({"body": "预算为64,441.38 元。", "run_ids": [budget_run["id"]], "claims": [budget_claim]})

    assert good["status"] == "pass", good["issues"]
    assert matching_unit["status"] == "pass", matching_unit["issues"]
    assert any(issue["code"] == "uncited_number" and issue["text"] == "21,086.01" for issue in bad["issues"])
    assert any(issue["code"] == "uncited_number" and issue["text"] == "21,086.00%" for issue in percent_unit["issues"])
    assert any(issue["code"] == "uncited_number" and issue["text"] == "64,441.38" for issue in mismatched_unit["issues"])


def test_claim_presentation_does_not_allow_unknown_or_mismatched_fact(service):
    store, _ = service
    run, fact = _synthetic_single_value_fact(
        store,
        run_id="22222222222222222222222222222222",
        value="100.0040",
    )
    presentation = {"decimal_places": 2, "scale": "identity", "rounding": "half_up"}
    unknown = _presentation_claim_for_fact(fact, presentation)
    unknown["fact_id"] = "f" * 64
    mismatch = _presentation_claim_for_fact(fact, presentation)
    mismatch["value"] = "100.0140"
    extra_field = _presentation_claim_for_fact(fact, {**presentation, "unit": "元"})

    unknown_check = store.validate_explanation({"body": "金额100.00万元。", "run_ids": [run["id"]], "claims": [unknown]})
    mismatch_check = store.validate_explanation({"body": "金额100.00万元。", "run_ids": [run["id"]], "claims": [mismatch]})
    extra_field_check = store.validate_explanation({"body": "金额100.00万元。", "run_ids": [run["id"]], "claims": [extra_field]})

    assert any(issue["code"] == "invalid_presentation" and issue["reason"] == "presentation_requires_bound_fact" for issue in unknown_check["issues"])
    assert any(issue["code"] == "unknown_fact" for issue in unknown_check["issues"])
    assert any(issue["code"] == "invalid_presentation" and issue["reason"] == "claim_does_not_match_fact" for issue in mismatch_check["issues"])
    assert any(issue["code"] == "fact_claim_mismatch" for issue in mismatch_check["issues"])
    assert any(issue["code"] == "invalid_presentation" and issue["reason"] == "unsupported_presentation_fields" for issue in extra_field_check["issues"])


def test_claim_presentation_preserves_negative_sign_and_percent_requires_ratio(service):
    store, _ = service
    amount_run, amount_fact = _synthetic_single_value_fact(
        store,
        run_id="33333333333333333333333333333333",
        value="-6106.3769",
        unit="万元",
    )
    ratio_run, ratio_fact = _synthetic_single_value_fact(
        store,
        run_id="44444444444444444444444444444444",
        value="0.945301122594983360",
        unit="比率",
        metric_key="achievement_ratio",
    )
    amount_claim = _presentation_claim_for_fact(amount_fact, {"decimal_places": 2, "scale": "identity", "rounding": "half_up"})
    invalid_percent = _presentation_claim_for_fact(amount_fact, {"decimal_places": 2, "scale": "percent", "rounding": "half_up"})
    ratio_claim = _presentation_claim_for_fact(ratio_fact, {"decimal_places": 2, "scale": "percent", "rounding": "half_up"})

    signed = store.validate_explanation({"body": "利润差异-6,106.38万元。", "run_ids": [amount_run["id"]], "claims": [amount_claim]})
    unsigned = store.validate_explanation({"body": "利润差异6,106.38万元。", "run_ids": [amount_run["id"]], "claims": [amount_claim]})
    bad_percent = store.validate_explanation({"body": "金额-610,637.69%。", "run_ids": [amount_run["id"]], "claims": [invalid_percent]})
    ratio = store.validate_explanation({"body": "收入达成率94.53%。", "run_ids": [ratio_run["id"]], "claims": [ratio_claim]})

    assert signed["status"] == "pass", signed["issues"]
    assert any(issue["code"] == "uncited_number" and issue["text"] == "6,106.38" for issue in unsigned["issues"])
    assert any(issue["code"] == "invalid_presentation" and issue["reason"] == "percent_requires_ratio_fact" for issue in bad_percent["issues"])
    assert ratio["status"] == "pass", ratio["issues"]


def test_claim_presentation_persists_and_appears_in_audit_projection(service):
    from foundry.report_projection import build_report_projection

    store, _ = service
    run, fact = _synthetic_single_value_fact(
        store,
        run_id="55555555555555555555555555555555",
        value="21086.0040",
    )
    claim = _presentation_claim_for_fact(
        fact,
        {"decimal_places": 2, "scale": "identity", "rounding": "half_up"},
    )

    draft = store.save_explanation_draft({
        "title": "presentation",
        "body": "管理利润为21,086.00万元。",
        "run_ids": [run["id"]],
        "claims": [claim],
    })
    persisted = store.analysis.get_draft(draft["id"])
    audit = build_report_projection(persisted, mode="audit")

    persisted_claim = next(item for item in persisted["claims"] if item.get("fact_id") == fact["id"])
    assert persisted_claim["verification_status"] == "matches_run"
    assert persisted_claim["presentation"] == claim["presentation"]
    assert persisted["explanation_check"]["status"] == "pass", persisted["explanation_check"]["issues"]
    assert '"presentation"' in audit["body"]
    assert '"decimal_places":2' in audit["body"]

def _write_synthetic_run(analysis, run):
    saved = analysis._write(
        analysis._object_path("runs", run["id"]),
        {"task_id": analysis.task.id, **run},
    )
    return saved


def _synthetic_profit_bridge_run(run_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", rows=None):
    return {
        "id": run_id,
        "bindings": {},
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "method": "revenue_minus_cost_minus_expense",
            "columns": ["metric", "contribution", "actual", "baseline", "unit"],
            "rows": rows or [
                {"metric": "revenue", "contribution": "20", "actual": "120", "baseline": "100", "unit": "万元"},
                {"metric": "cost", "contribution": "-10", "actual": "70", "baseline": "60", "unit": "万元"},
                {"metric": "expense", "contribution": "-5", "actual": "20", "baseline": "15", "unit": "万元"},
                {"metric": "profit", "contribution": "5", "actual": "30", "baseline": "25", "unit": "万元"},
            ],
        },
    }


def _synthetic_pq_run(run_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"):
    return {
        "id": run_id,
        "bindings": {},
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "method": "quantity_then_price",
            "columns": [
                "product",
                "total_variance",
                "quantity_contribution",
                "price_contribution",
                "interaction",
                "residual",
                "unit",
            ],
            "rows": [{
                "product": "商品A",
                "total_variance": "32",
                "quantity_contribution": "20",
                "price_contribution": "12",
                "interaction": "0",
                "residual": "0",
                "unit": "元",
            }],
        },
    }


def _fact_ids_for_group(prepared, group_type, *, column=None):
    group = next(group for group in prepared["evidence_groups"] if group["group_type"] == group_type)
    return [
        member["fact_id"]
        for member in group["members"]
        if member.get("fact_id") and (column is None or member["column"] == column)
    ]


def test_profit_bridge_body_closure_expression_accepts_f13_shape(service):
    store, _context = service
    run = _write_synthetic_run(store.analysis, _synthetic_profit_bridge_run())
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    fact_ids = _fact_ids_for_group(prepared, "profit_bridge", column="contribution")

    check = store.validate_explanation({
        "body": "利润桥闭合成立：收入贡献 20 万元、成本利润影响 -10 万元、费用利润影响 -5 万元，合计与利润增加一致（20 − 10 − 5 = 5）。",
        "run_ids": [run["id"]],
        "fact_ids": fact_ids,
    })

    assert check["status"] == "pass", check["issues"]
    assert "fact_label_mismatch" not in {issue["code"] for issue in check["issues"]}


def test_price_quantity_body_closure_expression_accepts_explicit_bridge(service):
    store, _context = service
    run = _write_synthetic_run(store.analysis, _synthetic_pq_run())
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    fact_ids = _fact_ids_for_group(prepared, "price_quantity_bridge")

    check = store.validate_explanation({
        "body": "量价桥闭合：数量贡献 20 元、价格贡献 12 元、交互项 0 元、残差 0 元，等式（20 + 12 + 0 + 0 = 32）。",
        "run_ids": [run["id"]],
        "fact_ids": fact_ids,
    })

    assert check["status"] == "pass", check["issues"]


@pytest.mark.parametrize(
    "body",
    [
        "利润合计（20 + 10 − 5 = 25）。",
        "利润合计（20 − 10 − 5 = 6）。",
        "利润合计（30 + 25 = 5）。",
    ],
)
def test_supported_body_closure_expression_rejects_bad_arithmetic_or_group(service, body):
    store, _context = service
    run = _write_synthetic_run(store.analysis, _synthetic_profit_bridge_run())
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    fact_ids = [fact["id"] for fact in prepared["facts"]]

    check = store.validate_explanation({
        "body": body,
        "run_ids": [run["id"]],
        "fact_ids": fact_ids,
    })

    assert check["status"] == "needs_attention"
    assert any(issue["code"] == "body_closure_mismatch" for issue in check["issues"])


def test_body_closure_expression_requires_all_same_group_members_referenced(service):
    store, _context = service
    run = _write_synthetic_run(store.analysis, _synthetic_profit_bridge_run())
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    fact_ids = _fact_ids_for_group(prepared, "profit_bridge", column="contribution")
    incomplete = fact_ids[:1] + fact_ids[2:]

    check = store.validate_explanation({
        "body": "利润合计（20 − 10 − 5 = 5）。",
        "run_ids": [run["id"]],
        "fact_ids": incomplete,
    })

    assert check["status"] == "needs_attention"
    assert any(issue["code"] == "body_closure_mismatch" for issue in check["issues"])


def test_body_closure_expression_rejects_cross_group_numbers(service):
    store, _context = service
    rows = [
        {"metric": "revenue", "product": "A", "contribution": "20", "actual": "120", "baseline": "100", "unit": "万元"},
        {"metric": "cost", "product": "A", "contribution": "-10", "actual": "70", "baseline": "60", "unit": "万元"},
        {"metric": "expense", "product": "A", "contribution": "-5", "actual": "20", "baseline": "15", "unit": "万元"},
        {"metric": "profit", "product": "A", "contribution": "5", "actual": "30", "baseline": "25", "unit": "万元"},
        {"metric": "revenue", "product": "B", "contribution": "25", "actual": "145", "baseline": "120", "unit": "万元"},
        {"metric": "cost", "product": "B", "contribution": "-15", "actual": "95", "baseline": "80", "unit": "万元"},
        {"metric": "expense", "product": "B", "contribution": "0", "actual": "10", "baseline": "10", "unit": "万元"},
        {"metric": "profit", "product": "B", "contribution": "10", "actual": "40", "baseline": "30", "unit": "万元"},
    ]
    run = _write_synthetic_run(store.analysis, _synthetic_profit_bridge_run(rows=rows))
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    fact_ids = [fact["id"] for fact in prepared["facts"] if fact["column"] == "contribution"]

    check = store.validate_explanation({
        "body": "利润合计（20 − 10 − 0 = 10）。",
        "run_ids": [run["id"]],
        "fact_ids": fact_ids,
    })

    assert check["status"] == "needs_attention"
    assert any(issue["code"] == "body_closure_mismatch" for issue in check["issues"])


@pytest.mark.parametrize("prefix", ["", "利润桥如下。", "利润桥分析："])
def test_body_closure_expression_does_not_borrow_profit_bridge_for_revenue_target(service, prefix):
    store, _context = service
    run = _write_synthetic_run(store.analysis, _synthetic_profit_bridge_run())
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    fact_ids = _fact_ids_for_group(prepared, "profit_bridge", column="contribution")

    check = store.validate_explanation({
        "body": prefix + "收入合计（20 − 10 − 5 = 5）。",
        "run_ids": [run["id"]],
        "fact_ids": fact_ids,
    })

    assert check["status"] == "needs_attention"
    codes = {issue["code"] for issue in check["issues"]}
    assert "body_closure_mismatch" not in codes
    assert "fact_label_mismatch" in codes


def test_body_closure_expression_preserves_fraction_beside_large_integer():
    from foundry.finance_explanations import _parse_signed_closure_expression

    assert _parse_signed_closure_expression(
        "1000000000000000000000000000000 + 0.1 - 1000000000000000000000000000000 = 0.1"
    )["balanced"]
    assert not _parse_signed_closure_expression(
        "1000000000000000000000000000000 + 0.1 - 1000000000000000000000000000000 = 0"
    )["balanced"]


def test_body_closure_expression_rejects_larger_unparsed_expression(service):
    store, _context = service
    run = _write_synthetic_run(store.analysis, _synthetic_profit_bridge_run())
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    fact_ids = _fact_ids_for_group(prepared, "profit_bridge", column="contribution")

    check = store.validate_explanation({
        "body": "利润合计（100 × 20 − 10 − 5 = 5）。",
        "run_ids": [run["id"]],
        "fact_ids": fact_ids,
    })

    assert check["status"] == "needs_attention"
    codes = {issue["code"] for issue in check["issues"]}
    assert "body_closure_mismatch" not in codes
    assert "uncited_number" in codes


def test_run_metric_ratio_builds_closed_ratio_evidence_group(service):
    store, context = service
    run = store.run_metric({
        "context_id": context["id"],
        "metric": {
            "kind": "ratio",
            "dimensions": ["organization", "period"],
            "numerator_accounts": ["cost"],
            "denominator_accounts": ["revenue"],
            "filters": {"scenario": "actual"},
        },
    })

    payload = store.prepare_explanation({"run_ids": [run["id"]]})
    group = payload["evidence_groups"][0]
    by_column = {member["column"]: member for member in group["members"]}

    assert group["group_type"] == "ratio"
    assert group["status"] == "complete"
    assert group["closure"]["status"] == "passed"
    assert group["closure"]["equation"] == "ratio = numerator / denominator"
    assert group["closure"]["inputs"] == {"numerator": "70", "denominator": "120"}
    assert by_column["numerator"]["display_value"] == "70 万元"
    assert by_column["denominator"]["display_value"] == "120 万元"
    assert by_column["ratio"]["display_value"] == "58.33%"
    assert by_column["ratio"]["unit"] == "%"


def test_ratio_evidence_group_reports_zero_and_negative_denominators(tmp_path):
    rows = [
        {"management_account": "cost", "amount": "70"},
    ]
    store, context = _ratio_metric_store(tmp_path, rows)
    zero_run = store.run_metric({
        "context_id": context["id"],
        "metric": {
            "kind": "ratio",
            "numerator_accounts": ["cost"],
            "denominator_accounts": ["revenue"],
        },
    })
    zero_group = store.prepare_explanation({"run_ids": [zero_run["id"]]})["evidence_groups"][0]
    zero_members = {member["column"]: member for member in zero_group["members"]}
    assert zero_group["status"] == "not_applicable"
    assert zero_group["closure"]["denominator_status"] == "zero"
    assert zero_group["closure"]["expected"] is None
    assert zero_members["ratio"]["state"] == "not_applicable"

    rows = [
        {"management_account": "cost", "amount": "70"},
        {"management_account": "revenue", "amount": "-120"},
    ]
    store, context = _ratio_metric_store(tmp_path, rows)
    negative_run = store.run_metric({
        "context_id": context["id"],
        "metric": {
            "kind": "ratio",
            "numerator_accounts": ["cost"],
            "denominator_accounts": ["revenue"],
        },
    })
    negative_group = store.prepare_explanation({"run_ids": [negative_run["id"]]})["evidence_groups"][0]
    ratio_member = next(member for member in negative_group["members"] if member["column"] == "ratio")
    assert negative_group["status"] == "complete"
    assert negative_group["closure"]["denominator_status"] == "negative"
    assert negative_group["closure"]["expected"] == negative_group["closure"]["actual"]
    assert ratio_member["display_value"] == "-58.33%"
    assert ratio_member["unit"] == "%"


def test_ratio_evidence_group_flags_missing_and_tampered_ratios(service):
    from foundry.finance_explanations import prepare_explanation

    store, context = service
    missing_payload = prepare_explanation(store.analysis, [{
        "id": "missing-ratio",
        "execution_status": "succeeded",
        "output_hash": "fixed",
        "result": {
            "columns": ["numerator", "denominator", "ratio"],
            "rows": [{"numerator": None, "denominator": None, "ratio": None, "unit": "万元"}],
        },
    }])
    missing_group = missing_payload["evidence_groups"][0]
    missing_members = {member["column"]: member for member in missing_group["members"]}
    assert missing_group["status"] == "missing_data"
    assert missing_group["closure"]["missing"] == ["numerator", "denominator"]
    assert missing_members["ratio"]["state"] == "missing"

    run = store.run_metric({
        "context_id": context["id"],
        "metric": {
            "kind": "ratio",
            "dimensions": ["organization", "period"],
            "numerator_accounts": ["cost"],
            "denominator_accounts": ["revenue"],
            "filters": {"scenario": "actual"},
        },
    })
    tampered = json.loads(json.dumps(run))
    tampered["id"] = "tampered-ratio"
    tampered["result"]["rows"][0]["ratio"] = "0.5"
    tampered["result"]["rows"][0]["ratio_exact"] = "0.5"
    tampered_payload = prepare_explanation(store.analysis, [tampered])
    closure = tampered_payload["evidence_groups"][0]["closure"]
    assert tampered_payload["evidence_groups"][0]["status"] == "closure_mismatch"
    assert closure["expected"] != closure["actual"]
    assert closure["actual"] == "0.5"


def test_validate_explanation_returns_readability_suggestions_without_failing_finance_status(service):
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    fact_ids = [
        fact["id"]
        for fact in prepared["facts"]
        if fact["column"] == "contribution"
    ]

    body = (
        "利润桥闭合成立：收入贡献 20 万元、成本利润影响 -10 万元、费用利润影响 -5 万元，"
        "合计与利润增加一致（20 − 10 − 5 = 5）；本段随后又把结论、数据、条件、原因、行动和证据说明继续压在一起，"
        "读者需要在同一段里同时判断经营节奏、费用使用、收入确认和后续复核安排。"
        "虽然管理层仍需补充业务证据，但当前文字没有把结论短段、驱动条列、公式和附注拆开。"
    )
    check = store.validate_explanation({
        "body": body,
        "run_ids": [run["id"]],
        "fact_ids": fact_ids,
    })

    assert check["status"] == "pass", check["issues"]
    assert check["readability"]["status"] == "suggestions"
    assert {issue["code"] for issue in check["readability"]["issues"]} >= {
        "dense_paragraph",
        "inline_formula",
    }
    assert not check["issues"]


def test_validate_explanation_accepts_short_sections_standalone_formula_and_notes(service):
    store, context = service
    run = store.explain_variance({"context_id": context["id"]})
    prepared = store.prepare_explanation({"run_ids": [run["id"]]})
    fact_ids = [
        fact["id"]
        for fact in prepared["facts"]
        if fact["column"] == "contribution"
    ]

    body = (
        "结论：利润超预算5万元，主要由收入因素抵消成本费用因素。[^1]\n\n"
        "- 收入贡献20万元。\n"
        "- 成本利润影响 -10万元。\n"
        "- 费用利润影响 -5万元。\n\n"
        "利润合计：20 − 10 − 5 = 5。\n\n"
        "[^1]: 金额来自本次成功运行结果；业务原因仍需管理层证据。"
    )
    check = store.validate_explanation({
        "body": body,
        "run_ids": [run["id"]],
        "fact_ids": fact_ids,
    })

    assert check["status"] == "pass", check["issues"]
    assert check["readability"] == {"status": "clear", "issues": []}


def test_structured_generated_appendix_canonical_markdown_stays_trusted(service):
    from foundry.report_documents import report_document_from_markdown_body

    store, context = service
    run = store.run_metric({
        "context_id": context["id"],
        "metric": {"kind": "control_totals"},
    })
    document = report_document_from_markdown_body("控制合计见计算依据。")

    draft = store.save_explanation_draft({
        "title": "结构化控制合计",
        "document": document,
        "run_ids": [run["id"]],
    })

    assert draft["evidence_appendix"] not in draft["body"]
    assert "### 结果行 2" in draft["body"]
    assert draft["explanation_check"]["status"] == "pass", draft["explanation_check"]["issues"]

    checked = store.validate_explanation({"draft_id": draft["id"]})

    assert checked["status"] == "pass", checked["issues"]
    assert checked["readability"] == {"status": "clear", "issues": []}


def test_structured_generated_appendix_canonical_markdown_tamper_stays_untrusted(service):
    from foundry.report_documents import report_document_from_markdown_body

    store, context = service
    run = store.run_metric({
        "context_id": context["id"],
        "metric": {"kind": "control_totals"},
    })
    document = report_document_from_markdown_body("控制合计见计算依据。")
    draft = store.save_explanation_draft({
        "title": "结构化控制合计",
        "document": document,
        "run_ids": [run["id"]],
    })
    tampered = store.analysis.save_draft({
        "parent_id": draft["id"],
        "body": draft["body"].replace("120 万元", "121 万元", 1),
    })

    assert tampered["explanation_check"]["status"] == "needs_attention"
    assert any(
        issue["code"] == "uncited_number"
        and issue.get("text") == "121"
        and issue.get("origin") == "manager_body"
        for issue in tampered["explanation_check"]["issues"]
    )


def test_money_reads_with_thousands_separators() -> None:
    """53,262,500 is read; 53262500 is counted a digit at a time."""
    from foundry.finance_explanations import _display_value

    assert _display_value("53262500", "expense", "元") == "53,262,500 元"
    assert _display_value("414696250", "revenue", "元") == "414,696,250 元"
    # A ratio is not money and keeps its own shape.
    assert _display_value("12.84", "gross_margin_pct", "元") == "12.84%"
    assert _display_value("0.1284", "ratio", "元") == "12.84%"
    # Nothing else is regrouped.
    assert _display_value("2026-08", "period", "") == "2026-08"


def test_the_unit_is_written_once_even_when_the_manager_writes_it() -> None:
    """「{{fact}} 元」 rendered as 「53,262,500 元 元」."""
    from foundry.finance_explanations import render_fact_template

    fact_id = "a" * 64
    facts = [{
        "id": fact_id, "display_value": "53,262,500 元", "unit": "元",
        "value": "53262500", "column": "expense",
    }]
    token = "{{fact:%s}}" % fact_id
    text, used = render_fact_template(f"本月期间费用 {token} 元。", facts)
    assert text == "本月期间费用 53,262,500 元。"
    assert used == [fact_id]
    # The fact still carries the unit where the prose does not.
    plain, _ = render_fact_template(f"本月期间费用 {token}。", facts)
    assert plain == "本月期间费用 53,262,500 元。"
    # 元 starting a longer word is not the unit being written out.
    other, _ = render_fact_template(f"本月期间费用 {token} 元旦前结清。", facts)
    assert other == "本月期间费用 53,262,500 元 元旦前结清。"
    # And a different unit after the token is left alone.
    mixed, _ = render_fact_template(f"本月期间费用 {token} 万元口径。", facts)
    assert mixed == "本月期间费用 53,262,500 元 万元口径。"
