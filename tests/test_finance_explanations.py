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
