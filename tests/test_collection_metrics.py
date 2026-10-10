import json
from decimal import Decimal

import pytest

from foundry.analysis import AnalysisStore
from foundry.collection_metrics import (
    break_even_matrix,
    evaluate_collection_health,
    resolve_entities,
    resolve_params,
)
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

GROUP = {
    "revenue": "1000",
    "cost": "813",
    "period_expense": "70",
    "collection_rate_current": "87.32%",
    "collection_rate_total": "0.951",
    "revenue_py": "950",
    "revenue_py_full": "1500",
    "ar_end": "500",
    "contract_assets_end": "80",
    "ar_begin": "420",
    "contract_assets_begin": "60",
    "impairment": "30",
    "cash_from_sales": "950",
    "cash_from_sales_py": "940",
}


def _entity(values, name="集团", sensitivity=False):
    return {"name": name, "values": values, "sensitivity": sensitivity}


def _rows(values, **params):
    """The period rows keyed by metric, and the whole result; _all gives every scenario."""
    result = _result(values, **params)
    return {row["metric_key"]: row for row in result["rows"] if row["scenario"] == "本期"}, result


def _result(values, **params):
    entities = resolve_entities({"entities": [_entity(values)]}, {})
    return evaluate_collection_health(entities, resolve_params(params))


def _all(values, **params):
    return {(row["metric_key"], row["scenario"]): row for row in _result(values, **params)["rows"]}


def test_break_even_collection_rate_and_gap():
    rows, _ = _rows(GROUP)
    assert Decimal(rows["gross_margin"]["value"]) == Decimal("18.7")
    assert rows["gross_margin"]["unit"] == "%"
    assert Decimal(rows["expense_ratio"]["value"]) == Decimal("7")
    assert Decimal(rows["break_even_collection"]["value"]) == Decimal("88.3")
    assert rows["break_even_collection"]["display_value"] == "88.30%"
    gap = rows["collection_gap"]
    assert Decimal(gap["value"]) == (Decimal("0.8732") - Decimal("0.883")) * 100
    assert gap["unit"] == "百分点"
    assert gap["display_value"] == "-0.98 个百分点"
    assert (gap["level"], gap["level_label"]) == ("red", "红")
    assert "倒贴现金" in gap["note"]
    assert rows["collection_gap_total"]["level"] == "green"
    assert rows["collection_gap_total"]["display_value"] == "+6.80 个百分点"


def test_gap_levels_follow_thresholds():
    def level(rate):
        return _rows({**GROUP, "collection_rate_current": rate})[0]["collection_gap"]

    assert level("0.80")["note"].startswith("严重低于生死线")
    assert level("0.90")["level"] == "yellow"
    assert level("0.95")["level"] == "green"


def test_dso_uses_rebuilt_ttm_revenue_marked_estimate_and_compares_to_year_start():
    rows = _all(GROUP)
    ttm = rows[("ttm_revenue", "本期")]
    assert Decimal(ttm["value"]) == Decimal("1550")
    assert ttm["estimate"] is True and "估算" in ttm["note"]
    dso = rows[("dso", "本期")]
    assert Decimal(dso["value"]) == Decimal("580") * 365 / Decimal("1550")
    assert dso["unit"] == "天" and dso["display_value"].endswith(" 天")
    begin = rows[("dso", "年初")]
    assert Decimal(begin["value"]) == Decimal("480") * 365 / Decimal("1500")
    assert begin["level"] is None
    change = rows[("dso", "变动")]
    assert Decimal(change["value"]) == Decimal(dso["value"]) - Decimal(begin["value"])
    assert change["display_value"].startswith("+")
    assert dso["estimate"] is True
    # 136.58 days is yellow; a rise of 15 days or more lifts it one step.
    assert dso["level"] == "red"
    assert "比年初多" in dso["note"]


def test_dso_without_estimate_when_ttm_given_and_notes_missing_contract_assets():
    values = {k: v for k, v in GROUP.items() if not k.startswith("contract_assets")}
    rows, _ = _rows({**values, "revenue_ttm": "1460"})
    dso = rows["dso"]
    assert Decimal(dso["value"]) == Decimal("500") * 365 / Decimal("1460")
    assert dso["estimate"] is False
    assert "未取合同资产" in dso["note"]


def test_contract_assets_at_year_end_only_are_left_out_of_both_ends():
    values = {k: v for k, v in GROUP.items() if k != "contract_assets_begin"}
    rows = _all({**values, "ar_end": "100", "contract_assets_end": "300", "ar_begin": "90"})
    assert Decimal(rows[("ar_buildup", "本期")]["value"]) == Decimal("1")  # (100 - 90) / 1000, in percent
    assert Decimal(rows[("dso", "本期")]["value"]) == Decimal("100") * 365 / Decimal("1550")
    assert "年初缺合同资产" in rows[("dso", "本期")]["note"]


def test_implied_collection_and_reconciliation_to_reported_rate():
    rows, _ = _rows(GROUP)
    implied = rows["implied_collection"]
    assert Decimal(implied["value"]) == (1 - Decimal("130") / Decimal("1060")) * 100
    assert implied["estimate"] is True
    check = rows["implied_vs_reported"]
    assert check["level"] == "yellow"
    assert "对不上" in check["note"]


def test_negative_impairment_as_reported_under_cas_is_read_as_a_loss():
    positive, _ = _rows(GROUP)
    negative, _ = _rows({**GROUP, "impairment": "-30"})
    for key in ("implied_collection", "impairment_to_gross_profit"):
        assert negative[key]["value"] == positive[key]["value"]
        assert "按绝对值计" in negative[key]["note"]


def test_implied_collection_out_of_range_is_not_judged_nor_its_reconciliation():
    rows, _ = _rows({**GROUP, "ar_end": "1500"})
    for key in ("implied_collection", "implied_vs_reported"):
        assert rows[key]["level"] == "unknown"
        assert "超出合理区间" in rows[key]["note"]


def test_nonpositive_ttm_and_gross_profit_are_not_judged():
    rows, _ = _rows({**GROUP, "revenue_py_full": "-1000"})
    assert rows["dso"]["level"] == "unknown"
    rows, _ = _rows({**GROUP, "cost": "1100"})
    assert rows["impairment_to_gross_profit"]["level"] == "unknown"


def test_cash_collection_ratio_against_prior_year():
    rows = _all(GROUP)
    cash = rows[("cash_collection_ratio", "本期")]
    assert Decimal(cash["value"]) == Decimal("950") / Decimal("1060") * 100
    prior = rows[("cash_collection_ratio", "上年同期")]
    assert Decimal(prior["value"]) == Decimal("940") / (Decimal("950") * Decimal("1.06")) * 100
    assert "cash_from_sales_py" in prior["inputs"] and "revenue_py" in prior["inputs"]
    change = rows[("cash_collection_ratio", "变动")]
    assert change["unit"] == "百分点" and change["display_value"].endswith(" 个百分点")
    assert cash["level"] == "yellow"


def test_vat_factor_is_a_parameter():
    rows, result = _rows(GROUP, vat_factor="1.09")
    assert Decimal(rows["cash_collection_ratio"]["value"]) == Decimal("950") / Decimal("1090") * 100
    assert result["params"]["vat_factor"] == "1.09"


def test_impairment_and_provision_structure():
    rows, _ = _rows(
        {
            **GROUP,
            "ar_gross": "800",
            "provision": "160",
            "ar_over_1y": "300",
            "related_ar": "100",
            "related_provision": "90",
            "ar_gross_py": "700",
            "provision_py": "154",
            "ar_over_1y_py": "210",
        }
    )
    assert rows["impairment_to_gross_profit"]["level"] == "yellow"
    assert Decimal(rows["provision_ratio"]["value"]) == Decimal("20")
    assert Decimal(rows["aging_over_1y_share"]["value"]) == Decimal("37.5")
    assert Decimal(rows["related_party_provision_ratio"]["value"]) == Decimal("90")
    # Older receivables with a lower provision rate than last year.
    assert rows["provision_ratio"]["level"] == "yellow"
    assert "拨备没跟上" in rows["provision_ratio"]["note"]


def test_missing_inputs_skip_metrics_and_say_which():
    rows, result = _rows({"revenue": "100", "cost": "80"})
    assert set(rows) == {"gross_margin"}
    skipped = result["diagnostics"][0]
    assert skipped["code"] == "collection_metric_skipped"
    assert {item["metric_key"] for item in skipped["skipped"]} >= {"dso", "collection_gap"}


def test_no_metric_at_all_is_an_error():
    _, result = _rows({"ar_end": "10"})
    assert result["rows"] == []
    assert result["diagnostics"][-1]["severity"] == "error"


def test_rate_that_looks_like_a_percentage_needs_a_scale():
    with pytest.raises(FoundryError, match="looks like a percentage"):
        _rows({**GROUP, "collection_rate_current": "87.32"})
    # A margin or expense ratio above one is a percentage written without its sign.
    with pytest.raises(FoundryError, match="looks like a percentage"):
        _rows({"expense_ratio": "1.2"})


def test_unknown_input_and_param_are_refused():
    with pytest.raises(FoundryError, match="unknown collection_health input"):
        _rows({**GROUP, "revenu": "1"})
    with pytest.raises(FoundryError, match="unknown collection_health params"):
        resolve_params({"vat": "1.06"})


def test_manual_inputs_are_named_on_the_rows_that_read_them():
    rows, _ = _rows(GROUP)
    assert "含手填数" in rows["gross_margin"]["note"]
    assert "营业收入（本期）" in rows["gross_margin"]["note"]


def test_the_full_year_revenue_budget_is_worked_back_over_the_months_left():
    from foundry.what_if import goal_budget, lines_of

    rows, result = _rows({**GROUP, "revenue_budget_full": "1600", "months_elapsed": "8"})
    assert Decimal(rows["revenue_budget_remaining"]["value"]) == Decimal("600")
    assert Decimal(rows["revenue_budget_monthly"]["value"]) == Decimal("150")
    assert rows["revenue_budget_monthly"]["inputs"] == {"revenue_budget_full": "1600", "revenue": "1000", "months_elapsed": "8"}
    # A budget given as a bare number is the manager's, and the card says so.
    assert "全年收入预算" in rows["revenue_budget_remaining"]["note"]
    view = goal_budget(lines_of(result["rows"], "集团"), "集团")
    assert (view["part"], view["beside"][0][0]) == ("剩余 4 个月每月要做到", "全年收入预算（手填）")
    assert ["每月要比月均多", "+20.0%"] in view["beside"]
    # Met already: what is left is negative and each month needs nothing more; at month 12 there is no month left.
    met, _ = _rows({**GROUP, "revenue_budget_full": "900", "months_elapsed": "8"})
    assert (Decimal(met["revenue_budget_remaining"]["value"]), Decimal(met["revenue_budget_monthly"]["value"])) == (Decimal("-100"), 0)
    december, _ = _rows({**GROUP, "revenue_budget_full": "1600", "months_elapsed": "12"})
    assert "revenue_budget_remaining" in december and "revenue_budget_monthly" not in december
    assert "revenue_budget_remaining" not in _rows(GROUP)[0]


def test_break_even_matrix_uses_the_entity_expense_ratio():
    entities = resolve_entities({"entities": [_entity(GROUP, sensitivity=True)]}, {})
    params = resolve_params({})
    matrix = break_even_matrix(entities[0], params)
    assert matrix["gross_margins"][0] == "0.10" and matrix["gross_margins"][-1] == "0.30"
    assert matrix["collection_rates"][0] == "0.75" and matrix["collection_rates"][-1] == "1.000"
    # Each cell is collection - (1 - gross margin) - expense ratio.
    row = matrix["gross_margins"].index("0.14")
    assert Decimal(matrix["cells"][row][0]) == Decimal("0.75") - Decimal("0.86") - Decimal("0.07")
    assert matrix["current"]["collection_rate"] == "0.8732"
    result = evaluate_collection_health(entities, params)
    assert result["sensitivity"][0]["entity"] == "集团"


SHEET = [
    {"指标": "营业收入", "本年累计": "1,000.00", "上年同期累计": "950", "单位": "万元"},
    {"指标": "营业成本", "本年累计": "813", "上年同期累计": "780", "单位": "万元"},
    {"指标": "期间费用", "本年累计": "70", "上年同期累计": "66", "单位": "万元"},
    {"指标": "本年账单收缴率", "本年累计": "87.32%", "上年同期累计": "89.10%", "单位": "%"},
    {"指标": "销售商品、提供劳务收到的现金", "本年累计": "950", "上年同期累计": "940", "单位": "万元"},
]


def _service(tmp_path, rows, unit="万元"):
    task = TaskStore(tmp_path / "var").create(title="回款健康")
    service = FinanceStore(task)
    path = tmp_path / "kpi.json"
    path.write_text(json.dumps(rows, ensure_ascii=False))
    dataset = AnalysisStore(task).add_dataset(path, name="kpi")
    context = service.save_context(
        {"bindings": {"kpi": dataset["id"]}, "scopes": {"kpi": {"currency": "CNY", "unit": unit}}}
    )
    return service, context


def _cell(name, column="本年累计"):
    return {"alias": "kpi", "match": {"指标": name}, "column": column}


def test_scenario_reads_cells_and_drills_back_to_source_rows(tmp_path):
    service, context = _service(tmp_path, SHEET)
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "collection_health",
            "label": "集团回款健康",
            "inputs": {
                "entities": [
                    {
                        "name": "集团",
                        "sensitivity": True,
                        "values": {
                            "revenue": _cell("营业收入"),
                            "cost": _cell("营业成本"),
                            "period_expense": _cell("期间费用"),
                            "collection_rate_current": _cell("本年账单收缴率"),
                            "cash_from_sales": _cell("销售商品、提供劳务收到的现金"),
                            "revenue_py": _cell("营业收入", "上年同期累计"),
                            "cash_from_sales_py": _cell("销售商品、提供劳务收到的现金", "上年同期累计"),
                        },
                    }
                ]
            },
        }
    )
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded"
    rows = {
        row["metric_key"]: (index, row)
        for index, row in enumerate(run["result"]["rows"])
        if row["scenario"] == "本期"
    }
    index, gap = rows["collection_gap"]
    assert gap["level"] == "red"
    assert "含手填数" not in gap["note"]
    assert {ref["column"] for ref in gap["source_rows"]} == {"本年累计"}
    assert service.drilldown_fact({"run_id": run["id"], "row": index})["total"] == 4
    assert run["result"]["sensitivity"][0]["expense_ratio"] == "0.07"
    # Every figure is a fact a draft can cite, with the unit its row states.
    from foundry.finance_explanations import _facts_for_run

    facts = {(fact["row"], fact["column"]): fact for fact in _facts_for_run(run, {"absolute": "0"})}
    assert facts[(index, "value")]["unit"] == "百分点"
    assert facts[(index, "value")]["display_value"] == "-0.98 个百分点"
    again = service.run_scenario({"scenario_id": scenario["id"]})
    assert again["output_hash"] == run["output_hash"]


def test_scenario_refuses_a_cell_that_matches_more_than_one_row(tmp_path):
    service, context = _service(tmp_path, [*SHEET, SHEET[0]])
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "collection_health",
            "inputs": {"entities": [{"name": "集团", "values": {"revenue": _cell("营业收入")}}]},
        }
    )
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "failed"
    assert "exactly one row" in run["error"]


def test_scenario_refuses_mixed_amount_units(tmp_path):
    service, context = _service(tmp_path, SHEET)
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "collection_health",
            "inputs": {
                "entities": [
                    {
                        "name": "集团",
                        "values": {
                            "revenue": _cell("营业收入"),
                            "cost": {**_cell("营业成本"), "unit": "元"},
                        },
                    }
                ]
            },
        }
    )
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "failed"
    assert "mixes amount units" in run["error"]


def test_reported_ratios_on_a_kpi_dashboard_are_read_as_reported(tmp_path):
    # The layout and figures of a property group's 01·核心指标看板 (labels keep their full-width indent).
    dashboard = [
        {"指标": "综合毛利率", "本年累计": 0.1805330360762059},
        {"指标": "期间费用率", "本年累计": 0.09195931753694218},
        {"指标": "\u3000本年账单物业费收缴率", "本年累计": 0.879185},
        {"指标": "综合收缴率（含往年欠费）", "本年累计": 0.824},
    ]
    service, context = _service(tmp_path, dashboard)

    def cell(name):
        return {"alias": "kpi", "match": {"指标": name}, "column": "本年累计"}

    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "collection_health",
            "inputs": {
                "entities": [
                    {
                        "name": "集团",
                        "values": {
                            "gross_margin": cell("综合毛利率"),
                            "expense_ratio": cell("期间费用率"),
                            "collection_rate_current": cell("本年账单物业费收缴率"),
                            "collection_rate_total": cell("综合收缴率（含往年欠费）"),
                        },
                    }
                ]
            },
        }
    )
    run = service.run_scenario({"scenario_id": scenario["id"]})
    rows = {row["metric_key"]: row for row in run["result"]["rows"] if row["scenario"] == "本期"}
    assert rows["break_even_collection"]["display_value"] == "91.14%"
    assert rows["collection_gap"]["display_value"] == "-3.22 个百分点"
    assert rows["collection_gap"]["level"] == "red"
    assert rows["collection_gap_total"]["note"].startswith("严重低于生死线")


def test_entity_table_gives_one_entity_per_named_row(tmp_path):
    city = [
        {"区域": "华东区域（合计）", "城市公司": None, "营业收入": None, "营业成本": None, "期间费用": None, "本年收缴率": None},
        {"区域": None, "城市公司": "上海城市公司", "营业收入": 21540.0656, "营业成本": 16505.5013,
         "期间费用": 1545.0316, "本年收缴率": 0.93},
        {"区域": None, "城市公司": "杭州城市公司", "营业收入": 16699.0034, "营业成本": 12795.9416,
         "期间费用": 1197.7906, "本年收缴率": None},
        {"区域": None, "城市公司": "合计", "营业收入": 38239.069, "营业成本": 29301.4429,
         "期间费用": 2742.8222, "本年收缴率": 0.9},
    ]
    service, context = _service(tmp_path, city)
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "collection_health",
            "inputs": {
                "entity_tables": [
                    {
                        "alias": "kpi",
                        "name_column": "城市公司",
                        "exclude": ["合计"],
                        "columns": {
                            "revenue": "营业收入",
                            "cost": "营业成本",
                            "period_expense": "期间费用",
                            "collection_rate_current": "本年收缴率",
                        },
                    }
                ]
            },
        }
    )
    run = service.run_scenario({"scenario_id": scenario["id"]})
    gaps = {
        row["entity"]: row
        for row in run["result"]["rows"]
        if row["metric_key"] == "collection_gap" and row["scenario"] == "本期"
    }
    assert set(gaps) == {"上海城市公司"}
    assert gaps["上海城市公司"]["level"] == "green"
    entities = {row["entity"] for row in run["result"]["rows"]}
    assert entities == {"上海城市公司", "杭州城市公司"}
    skipped = [d for d in run["result"]["diagnostics"] if d["code"] == "collection_metric_skipped"]
    assert any(d["entity"] == "杭州城市公司" and any(i["metric_key"] == "collection_gap" for i in d["skipped"])
               for d in skipped)


def test_entity_table_refuses_a_column_it_does_not_have(tmp_path):
    service, context = _service(tmp_path, SHEET)
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "collection_health",
            "inputs": {
                "entity_tables": [
                    {"alias": "kpi", "name_column": "指标", "columns": {"revenue": "本年累计", "cost": "成本X"}}
                ]
            },
        }
    )
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "failed"
    assert "成本X" in run["error"]


def test_entity_table_rate_column_written_in_percent_needs_a_scale():
    rows = {
        "t": [
            {"公司": "甲", "费用率": 0.9, "source": {"source_row": 1}},
            {"公司": "乙", "费用率": 7.2, "source": {"source_row": 2}},
        ]
    }
    with pytest.raises(FoundryError, match="looks like a percentage"):
        resolve_entities(
            {"entity_tables": [{"alias": "t", "name_column": "公司", "columns": {"expense_ratio": "费用率"}}]}, rows
        )


def test_amount_without_a_unit_beside_amounts_with_one_is_refused():
    rows = {
        "a": [{"指标": "营业收入", "值": "1000", "source": {"source_row": 1}}],
        "b": [{"指标": "收现", "值": "950000", "source": {"source_row": 1}}],
    }
    with pytest.raises(FoundryError, match="without a unit"):
        resolve_entities(
            {
                "entities": [
                    {
                        "name": "集团",
                        "values": {
                            "revenue": {"alias": "a", "match": {"指标": "营业收入"}, "column": "值"},
                            "cash_from_sales": {"alias": "b", "match": {"指标": "收现"}, "column": "值"},
                        },
                    }
                ]
            },
            rows,
            {"a": "万元", "b": None},
        )
    # 万 and 万元 are the same unit.
    entities = resolve_entities(
        {
            "entities": [
                {
                    "name": "集团",
                    "values": {
                        "revenue": {"alias": "a", "match": {"指标": "营业收入"}, "column": "值"},
                        "cash_from_sales": {"alias": "b", "match": {"指标": "收现"}, "column": "值", "unit": "万"},
                    },
                }
            ]
        },
        rows,
        {"a": "万元", "b": None},
    )
    assert entities[0]["unit"] == "万元"


def test_source_row_is_read_as_a_number_and_not_beside_match():
    rows = {"a": [{"指标": "营业收入", "值": "1000", "source": {"source_row": 2}}]}
    entities = resolve_entities(
        {"entities": [{"name": "集团", "values": {"revenue": {"alias": "a", "source_row": "2", "column": "值"}}}]},
        rows,
    )
    assert entities[0]["values"]["revenue"] == Decimal("1000")
    with pytest.raises(FoundryError, match="both match and source_row"):
        resolve_entities(
            {
                "entities": [
                    {
                        "name": "集团",
                        "values": {
                            "revenue": {"alias": "a", "source_row": 2, "match": {"指标": "x"}, "column": "值"}
                        },
                    }
                ]
            },
            rows,
        )


def test_assistant_tools_offer_the_kind_the_engine_accepts():
    from pathlib import Path

    from foundry.finance_service import SCENARIO_KINDS

    root = Path(__file__).resolve().parents[1]
    for path in (root / "dsh-plugin/finance-tools.js", root / "foundry/resources/dsh-plugin/finance-tools.js"):
        text = path.read_text(encoding="utf-8")
        for kind in SCENARIO_KINDS:
            assert f'"{kind}"' in text, (path, kind)
        assert "entity_tables" in text


def test_only_collection_health_results_carry_the_kind_and_table_rows_their_origin(tmp_path):
    service, context = _service(tmp_path, SHEET)
    scenario = service.save_scenario(
        {
            "context_id": context["id"],
            "kind": "collection_health",
            "inputs": {
                "entities": [{"name": "集团", "values": {"revenue": _cell("营业收入"), "cost": _cell("营业成本")}}],
                "entity_tables": [{"alias": "kpi", "name_column": "指标", "exclude": ["营业收入", "营业成本", "期间费用", "本年账单收缴率"],
                                   "columns": {"revenue": "本年累计", "cash_from_sales": "上年同期累计"}}],
            },
        }
    )
    result = service.run_scenario({"scenario_id": scenario["id"]})["result"]
    assert result["scenario_kind"] == "collection_health"
    assert {row["entity"]: row["entity_origin"] for row in result["rows"]} == {
        "集团": "declared", "销售商品、提供劳务收到的现金": "table"}
    driver = service.save_scenario({"context_id": context["id"], "kind": "driver_model", "inputs": {
        "drivers": [{"name": "x", "direct_assumption": True}], "manager_assumptions": {"x": {"value": "1"}}}})
    # Older runs of the other kinds keep their output hash: nothing new is stamped on them.
    assert "scenario_kind" not in service.run_scenario({"scenario_id": driver["id"]})["result"]


def test_full_year_is_estimated_at_last_years_pace_and_le_is_read_against_it():
    rows = _all(
        {
            "revenue": "325644",
            "revenue_py": "331613",
            "revenue_py_full": "500000",
            "revenue_le": "500000",
            "net_profit": "15374",
            "net_profit_py": "20274",
            "net_profit_py_full": "23698",
            "net_profit_le": "23698",
            "impairment_py": "-4000",
            "impairment_py_full": "-11000",
            "months_elapsed": "8",
        }
    )
    seasonal = rows[("net_profit_full_year_seasonal", "本期")]
    assert Decimal(seasonal["value"]) == Decimal("15374") / (Decimal("20274") / Decimal("23698"))
    assert seasonal["estimate"] is True and "估算" in seasonal["note"]
    linear = rows[("net_profit_full_year_linear", "本期")]
    assert Decimal(linear["value"]) == Decimal("15374") * 12 / 8
    assert linear["level"] is None and "不进结论" in linear["note"]
    # LE 23,698 against 17,970 at last year's pace.
    gap = rows[("net_profit_le_gap", "本期")]
    assert gap["level"] == "yellow" and "偏乐观" in gap["note"]
    assert rows[("revenue_le_gap", "本期")]["level"] == "green"
    progress = rows[("impairment_progress_py", "本期")]
    assert Decimal(progress["value"]) == Decimal("4000") / Decimal("11000") * 100
    assert progress["level"] == "yellow" and "后几个月" in progress["note"]


def test_full_year_at_last_years_pace_is_not_judged_on_a_loss_year_and_months_are_checked():
    rows, _ = _rows({"net_profit": "100", "net_profit_py": "-50", "net_profit_py_full": "200", "net_profit_le": "300"})
    assert rows["net_profit_full_year_seasonal"]["level"] == "unknown"
    assert rows["net_profit_le_gap"]["level"] == "unknown"
    with pytest.raises(FoundryError, match="months_elapsed"):
        _rows({"net_profit": "100", "months_elapsed": "13"})


def test_full_year_pace_refuses_a_tiny_share_a_ytd_loss_a_reversal_and_a_prior_month_count():
    rows, _ = _rows({"net_profit": "5", "net_profit_py": "1", "net_profit_py_full": "1000", "net_profit_le": "100"})
    assert rows["net_profit_le_gap"]["level"] == "unknown" and "很小一部分" in rows["net_profit_le_gap"]["note"]
    rows, _ = _rows({"net_profit": "-100", "net_profit_py": "50", "net_profit_py_full": "100", "net_profit_le": "-150"})
    assert rows["net_profit_le_gap"]["level"] == "unknown"
    rows, _ = _rows({"impairment_py": "200", "impairment_py_full": "-1000"})
    assert rows["impairment_progress_py"]["level"] == "unknown"
    with pytest.raises(FoundryError, match="no prior-year counterpart"):
        _rows({"revenue": "50", "revenue_py": "40", "months_elapsed": "6", "months_elapsed_py": "0"})


LEDGER = [
    {"合同": "A", "续约状态": "正常在约", "确认收入": "600", "账单": "600", "实收": "570", "在岗人数": "30", "source": {"source_row": 1}},
    {"合同": "B", "续约状态": "12个月内到期", "确认收入": "200", "账单": "200", "实收": "176", "在岗人数": "10", "source": {"source_row": 2}},
    {"合同": "C", "续约状态": "拟退场", "确认收入": "100", "账单": "100", "实收": "60", "在岗人数": "6", "source": {"source_row": 3}},
    {"合同": "D", "续约状态": "正常在约", "确认收入": "100", "账单": None, "实收": "95", "在岗人数": "4", "source": {"source_row": 4}},
]


def test_contract_ledger_sums_give_renewal_exposure_and_exiting_collection():
    def total(column, *statuses, **extra):
        where = {"续约状态": list(statuses)} if statuses else {"合同": ["A", "B", "C", "D"]}
        return {"alias": "ledger", "column": column, "sum_where": where, **extra}

    entities = resolve_entities(
        {
            "entities": [
                {
                    "name": "集团",
                    "values": {
                        "contract_revenue": total("确认收入"),
                        "revenue_at_risk": total("确认收入", "12个月内到期", "拟退场"),
                        "billed_exiting": total("账单", "拟退场"),
                        "collected_exiting": total("实收", "拟退场"),
                        "billed_staying": total("账单", "正常在约", "12个月内到期", require_columns=["账单", "实收"]),
                        "collected_staying": total("实收", "正常在约", "12个月内到期", require_columns=["账单", "实收"]),
                        "revenue": total("确认收入"),
                        "headcount": total("在岗人数"),
                        "area_begin": {"alias": "area", "match": {"项目": "年初"}, "column": "面积"},
                        "area_end": {"alias": "area", "match": {"项目": "年末"}, "column": "面积"},
                        "area_exit": {"alias": "area", "match": {"项目": "低效退场"}, "column": "面积"},
                        "area_nonrenewal": {"alias": "area", "match": {"项目": "到期未续约"}, "column": "面积"},
                    },
                }
            ]
        },
        {
            "ledger": LEDGER,
            "area": [
                {"项目": "年初", "面积": "18840", "unit": "万㎡", "source": {"source_row": 1}},
                {"项目": "年末", "面积": "20000", "unit": "万㎡", "source": {"source_row": 2}},
                {"项目": "低效退场", "面积": "300", "unit": "万㎡", "source": {"source_row": 3}},
                {"项目": "到期未续约", "面积": "200", "unit": "万㎡", "source": {"source_row": 4}},
            ],
        },
        {"ledger": "万元", "area": None},
    )
    rows = {row["metric_key"]: row for row in evaluate_collection_health(entities, resolve_params({}))["rows"]
            if row["scenario"] == "本期"}
    assert Decimal(rows["renewal_exposure"]["value"]) == Decimal("30")
    assert rows["renewal_exposure"]["level"] == "red"
    assert len(rows["renewal_exposure"]["source_rows"]) == 6  # 4 rows for the total, 2 at risk
    assert Decimal(rows["exiting_collection_rate"]["value"]) == Decimal("60")
    # The staying side skips D's blank bill: 746 of 800.
    assert Decimal(rows["staying_collection_rate"]["value"]) == Decimal("746") / Decimal("800") * 100
    assert "退场多因收缴不足" in rows["exiting_collection_gap"]["note"]
    assert rows["revenue_per_head"]["unit"] == "万元/人" and Decimal(rows["revenue_per_head"]["value"]) == 20
    assert rows["area_per_head"]["unit"] == "万㎡/人" and Decimal(rows["area_per_head"]["value"]) == 400
    assert Decimal(rows["area_exit_share"]["value"]) == Decimal("500") / Decimal("18840") * 100


def test_sum_where_refuses_a_rate_and_a_filter_that_matches_nothing():
    rows = {"ledger": LEDGER}
    with pytest.raises(FoundryError, match="only an amount"):
        resolve_entities({"entities": [{"name": "x", "values": {
            "collection_rate_current": {"alias": "ledger", "column": "实收", "sum_where": {"合同": "A"}}}}]}, rows)
    with pytest.raises(FoundryError, match="found no figure"):
        resolve_entities({"entities": [{"name": "x", "values": {
            "revenue": {"alias": "ledger", "column": "确认收入", "sum_where": {"续约状态": "已续签待生效"}}}}]}, rows)


def test_risk_radar_adds_the_signals_it_can_read_and_names_the_rest():
    rows, _ = _rows(
        {
            **GROUP,
            "operating_profit": "-5",
            "collection_rate_current": "0.80",
            "collection_rate_current_py": "0.85",
            "revenue_budget_full": "1800",
            "months_elapsed": "8",
        }
    )
    risk = rows["risk_score"]
    # Loss 2, impairment 16% of gross profit 1, DSO 136.58 days 1, 8.3pp below the line 2, rate down 5pp 1,
    # revenue up on last year 0, 1000 of a 1200 pace (83%) 1.
    assert risk["value"] == "8" and risk["level"] == "red" and risk["display_value"] == "8 分"
    assert "营业利润为负（2分）" in risk["note"] and "不计入月结" in risk["note"]
    assert "无法判断" not in risk["note"]
    rows, _ = _rows({"revenue": "100", "revenue_py": "90", "cost": "80", "period_expense": "5"})
    assert "risk_score" not in rows  # one readable signal is not a radar
    rows, _ = _rows({"revenue": "100", "revenue_py": "90", "cost": "80", "period_expense": "5",
                     "collection_rate_current": "0.9"})
    assert rows["risk_score"]["level"] == "green" and "无法判断：营业利润为负" in rows["risk_score"]["note"]


def test_sum_where_guards_against_silent_misreads():
    rows = {"t": [
        {"城市": "A", "编号": 1.0, "人": "3", "unit": "人", "source": {"source_row": 1}},
        {"城市": "B", "编号": 2, "人": "4", "unit": "人", "source": {"source_row": 2}},
        {"城市": "合计", "编号": None, "人": "7", "source": {"source_row": 3}},
    ]}

    def resolve(values):
        return resolve_entities({"entities": [{"name": "x", "values": values}]}, rows)

    # A number cell matches the same number written as text.
    assert resolve({"headcount": {"alias": "t", "column": "人", "sum_where": {"编号": ["1", "2"]}}})[0]["values"]["headcount"] == 7
    with pytest.raises(FoundryError, match="at least one column"):
        resolve({"headcount": {"alias": "t", "column": "人", "sum_where": {}}})
    with pytest.raises(FoundryError, match="cannot sit beside"):
        resolve_entities({"entity_tables": [{"alias": "t", "name_column": "城市", "columns": {
            "headcount": {"column": "人", "sum_where": {"城市": ["A", "B"]}}}}]}, rows)
    with pytest.raises(FoundryError, match="column 账单X is not in the table"):
        resolve({"headcount": {"alias": "t", "column": "人", "sum_where": {"城市": "A"}, "require_columns": ["账单X"]}})
    mixed = {"t": [
        {"城市": "A", "金额": "3", "unit": "元", "source": {"source_row": 1}},
        {"城市": "B", "金额": "4", "unit": "万元", "source": {"source_row": 2}},
    ]}
    with pytest.raises(FoundryError, match="one unit at a time"):
        resolve_entities({"entities": [{"name": "x", "values": {
            "revenue": {"alias": "t", "column": "金额", "sum_where": {"城市": ["A", "B"]}}}}]}, mixed)


def test_risk_radar_orange_and_a_formula_that_follows_its_parameters():
    values = {**GROUP, "operating_profit": "-5", "collection_rate_current": "0.86"}
    rows, _ = _rows(values)
    # Loss 2, impairment 16% 1, DSO 136.58 days 1, 2.3pp below the line 1: 5 points.
    assert rows["risk_score"]["value"] == "5" and rows["risk_score"]["level"] == "orange"
    assert rows["risk_score"]["level_label"] == "橙"
    assert rows["risk_score"]["estimate"] is True and "估算" in rows["risk_score"]["note"]
    rows, _ = _rows(values, risk_red_at="5", impairment_red_above="0.15")
    assert rows["risk_score"]["level"] == "red"
    assert "不低于 5 分红" in rows["risk_score"]["formula"] and "超过 15% 2 分" in rows["risk_score"]["formula"]
