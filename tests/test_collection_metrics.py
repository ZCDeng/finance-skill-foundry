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
    entities = resolve_entities({"entities": [_entity(values)]}, {})
    result = evaluate_collection_health(entities, resolve_params(params))
    return {row["metric_key"]: row for row in result["rows"]}, result


def test_break_even_collection_rate_and_gap():
    rows, _ = _rows(GROUP)
    assert Decimal(rows["gross_margin"]["value"]) == Decimal("0.187")
    assert Decimal(rows["expense_ratio"]["value"]) == Decimal("0.07")
    assert Decimal(rows["break_even_collection"]["value"]) == Decimal("0.883")
    assert rows["break_even_collection"]["display_value"] == "88.30%"
    gap = rows["collection_gap"]
    assert Decimal(gap["value"]) == Decimal("0.8732") - Decimal("0.883")
    assert gap["display_value"] == "-0.98pp"
    assert (gap["level"], gap["level_label"]) == ("red", "红")
    assert "倒贴现金" in gap["note"]
    assert rows["collection_gap_total"]["level"] == "green"


def test_gap_levels_follow_thresholds():
    def level(rate):
        return _rows({**GROUP, "collection_rate_current": rate})[0]["collection_gap"]

    assert level("0.80")["note"].startswith("严重低于生死线")
    assert level("0.90")["level"] == "yellow"
    assert level("0.95")["level"] == "green"


def test_dso_uses_rebuilt_ttm_revenue_marked_estimate_and_compares_to_year_start():
    rows, _ = _rows(GROUP)
    ttm = rows["ttm_revenue"]
    assert Decimal(ttm["value"]) == Decimal("1550")
    assert ttm["estimate"] is True and "估算" in ttm["note"]
    dso = rows["dso"]
    assert Decimal(dso["value"]) == Decimal("580") * 365 / Decimal("1550")
    assert dso["compare_label"] == "年初"
    assert Decimal(dso["compare_value"]) == Decimal("480") * 365 / Decimal("1500")
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


def test_implied_collection_and_reconciliation_to_reported_rate():
    rows, _ = _rows(GROUP)
    implied = rows["implied_collection"]
    assert Decimal(implied["value"]) == 1 - Decimal("130") / Decimal("1060")
    assert implied["estimate"] is True
    check = rows["implied_vs_reported"]
    assert check["level"] == "yellow"
    assert "对不上" in check["note"]


def test_implied_collection_out_of_range_is_not_judged():
    rows, _ = _rows({**GROUP, "ar_end": "1500"})
    implied = rows["implied_collection"]
    assert implied["level"] == "unknown"
    assert "超出合理区间" in implied["note"]


def test_cash_collection_ratio_against_prior_year():
    rows, _ = _rows(GROUP)
    cash = rows["cash_collection_ratio"]
    assert Decimal(cash["value"]) == Decimal("950") / Decimal("1060")
    assert cash["compare_label"] == "上年同期"
    assert Decimal(cash["compare_value"]) == Decimal("940") / (Decimal("950") * Decimal("1.06"))
    assert cash["level"] == "yellow"
    assert cash["change_display"].endswith("pp")
    assert "cash_from_sales_py" in cash["inputs"] and "revenue_py" in cash["inputs"]


def test_vat_factor_is_a_parameter():
    rows, result = _rows(GROUP, vat_factor="1.09")
    assert Decimal(rows["cash_collection_ratio"]["value"]) == Decimal("950") / Decimal("1090")
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
    assert Decimal(rows["provision_ratio"]["value"]) == Decimal("0.2")
    assert Decimal(rows["aging_over_1y_share"]["value"]) == Decimal("0.375")
    assert Decimal(rows["related_party_provision_ratio"]["value"]) == Decimal("0.9")
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


def test_unknown_input_and_param_are_refused():
    with pytest.raises(FoundryError, match="unknown collection_health input"):
        _rows({**GROUP, "revenu": "1"})
    with pytest.raises(FoundryError, match="unknown collection_health params"):
        resolve_params({"vat": "1.06"})


def test_manual_inputs_are_named_on_the_rows_that_read_them():
    rows, _ = _rows(GROUP)
    assert "含手填数" in rows["gross_margin"]["note"]
    assert "营业收入（本期）" in rows["gross_margin"]["note"]


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
    rows = {row["metric_key"]: (index, row) for index, row in enumerate(run["result"]["rows"])}
    index, gap = rows["collection_gap"]
    assert gap["level"] == "red"
    assert "含手填数" not in gap["note"]
    assert {ref["column"] for ref in gap["source_rows"]} == {"本年累计"}
    assert service.drilldown_fact({"run_id": run["id"], "row": index})["total"] == 4
    assert run["result"]["sensitivity"][0]["expense_ratio"] == "0.07"
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
    rows = {row["metric_key"]: row for row in run["result"]["rows"]}
    assert rows["break_even_collection"]["display_value"] == "91.14%"
    assert rows["collection_gap"]["display_value"] == "-3.22pp"
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
    gaps = {row["entity"]: row for row in run["result"]["rows"] if row["metric_key"] == "collection_gap"}
    assert set(gaps) == {"上海城市公司"}
    assert gaps["上海城市公司"]["level"] == "green"
    entities = {row["entity"] for row in run["result"]["rows"]}
    assert entities == {"上海城市公司", "杭州城市公司"}
    skipped = [d for d in run["result"]["diagnostics"] if d["code"] == "collection_metric_skipped"]
    assert any(d["entity"] == "杭州城市公司" and any(i["metric_key"] == "collection_gap" for i in d["skipped"])
               for d in skipped)
