"""The 参考结果 practice task: the 华宸物业 August pack taken through every step the guide walks.

``build_reference`` runs on a freshly filed copy of the practice pack, with the installed engine, so
the figures it shows are the ones this version computes (a stored snapshot would show an older
engine's answer, or not open at all). Every confirmation and decision here is the example's: the
task's marker says ``kind: reference`` and the app says, on every page of it, that these were
filled in by the example and not by a manager. The steps are the guide's 跟着做 path:

1. 表结构：every data sheet confirmed; the KPI board adopted as a table; the formula sample's
   unreadable comparison sheet left out.
2. 勾稽控制：the suggested checks confirmed, plus F-02 across workbooks and the AR roll-forward;
   each difference decided with a written reason.
3. 范围与回款与现金：the scope (2026-08 · 华宸物业 · 万元 · CNY) and the collection-health run over
   the KPI board and every city company.
4. 文稿：a paragraph on the group's collection whose every number cites the run, two of them traced
   back to the board's own cells.
5. 收费明细：海口城市公司's billing export filed, its columns confirmed, the industry-common 口径
   confirmed as it stands, and the rates run by 房产性质 against the 套表's 本年收缴率 for the city.
6. 看板：the 回款健康 board over the collection run, its figures and ranking accepted as the example's (each
   card says so) and its 回款情景 card pinned, since a what-if is never accepted.

Two differences are left 待外部确认 on purpose: the example shows what a close looks like while it
waits on another department, which is where most real closes stand.
"""

from __future__ import annotations

from typing import Any

from foundry.errors import FoundryError

MONTH_CLOSE = "华宸物业_2026年08月_月结财务套表_GL-AP-AR-CF.xlsx"
BUDGET = "华宸物业_2026年度_全面预算与合同台账.xlsx"
DETAIL = "华宸物业_2026年08月_明细长表.xlsx"
FORMULA = "华宸物业_2026年08月_公式体检样本.xlsx"
MINUTES = "华宸物业_2026年08月_经营分析会纪要.md"

# Sheets of the formula sample that carry nothing a calculation can read (#REF!, an external link).
LEFT_OUT = {FORMULA: {"上年同期对比"}}

DECIDER = "示例预置"
PERIOD, COMPANY, UNIT, CURRENCY = "2026-08", "华宸物业", "万元", "CNY"
QUESTION = "8 月月结：收缴率是否守住生死线，哪些城市公司在拖累回款"


class Reference:
    """One pass over a filed practice task, as the manager would take it."""

    def __init__(self, task) -> None:
        from foundry.analysis import AnalysisStore
        from foundry.finance_service import FinanceStore

        self.task = task
        self.analysis = AnalysisStore(task)
        self.manager = FinanceStore(task, actor="manager")
        self.datasets = {row["name"]: row for row in self.analysis.state()["datasets"]}
        self.tables: dict[str, dict[str, str]] = {}

    def dataset(self, name: str) -> dict:
        try:
            return self.datasets[name]
        except KeyError as exc:
            raise FoundryError(f"the example pack is missing {name}") from exc

    # -- 1. 表结构 -------------------------------------------------------------------------

    def confirm_structures(self) -> None:
        for name, dataset in self.datasets.items():
            if not name.endswith(".xlsx"):
                continue
            proposal = self.manager.structure_proposal_list({"dataset_id": dataset["id"]})["proposals"][0]
            sheets = []
            for sheet in proposal["sheets"]:
                if sheet["sheet"] in LEFT_OUT.get(name, set()):
                    continue
                if sheet["decision"] == "table" and not sheet.get("blocked_reason"):
                    sheets.append(sheet)
                elif sheet.get("adoptable"):
                    # 当作数据表：the KPI board is where the pack states its headline rates.
                    sheets.append({**sheet, "decision": "table"})
            confirmed = self.manager.structure_proposal_confirm(
                {"dataset_id": dataset["id"], "revision": proposal["revision"], "sheets": sheets}
            )
            self.tables[name] = confirmed["snapshot_ids"]
        self.datasets = {row["name"]: row for row in self.analysis.state()["datasets"]}

    # -- 2. 勾稽控制 -----------------------------------------------------------------------

    def side(self, workbook: str, sheet: str, cell: str) -> dict:
        dataset = self.dataset(workbook)
        return {"dataset_id": dataset["id"], "source_hash": dataset["source_hash"], "sheet": sheet, "range": cell}

    def confirm_controls(self) -> None:
        suggested = [row["control"] for row in self.manager.finance_controls_propose({})["suggestions"]]
        self.manager.finance_controls_save({"confirm": True, "origin": "suggested", "controls": suggested})
        ar = "07·AR账龄及减值"
        declared = [
            {"kind": "tie_out", "label": "合同台账本年实收 = 月结区域实收",
             "left": self.side(BUDGET, "11·物业服务合同台账", "T5:T604"),
             "right": self.side(MONTH_CLOSE, "08·AR收缴率与欠费", "C11"), "tolerance": "1"},
            {"kind": "formula", "formula": "signed_sum", "label": "应收滚动：年初 + 新增 − 收回 − 核销 = 期末",
             "inputs": {"begin": self.side(MONTH_CLOSE, ar, "B34"), "new": self.side(MONTH_CLOSE, ar, "B35"),
                        "collected": self.side(MONTH_CLOSE, ar, "B36"), "written_off": self.side(MONTH_CLOSE, ar, "B38")},
             "right": self.side(MONTH_CLOSE, ar, "B39")},
        ]
        self.manager.finance_controls_save({"confirm": True, "controls": declared})
        self.manager.finance_controls_run({})

    def decide_differences(self) -> None:
        for row in self.manager.finance_controls_list({})["controls"]:
            result = row.get("result") or {}
            if row.get("state") != "confirmed" or result.get("status") not in {"break", "error"}:
                continue
            self.manager.finance_control_disposition_save({"control_id": row["id"], **_decision(row["control"]["label"])})


    # -- 3. 回款与现金 ----------------------------------------------------------------------

    def collection_health(self) -> dict:
        """The group from the KPI board and every city company from its detail sheet, in 万元."""
        tables = self.tables[MONTH_CLOSE]
        context = self.manager.save_context({
            "name": "华宸物业 2026 年 8 月月结",
            "bindings": {"kpi": tables["01·核心指标看板"], "city": tables["11·城市公司明细表"]},
            "scopes": {
                "kpi": {"period": PERIOD, "organization": COMPANY, "unit": UNIT, "currency": CURRENCY},
                # City rows retain their own organizations; the sheet is not a group-only source.
                "city": {"period": PERIOD, "unit": UNIT, "currency": CURRENCY},
            },
        })
        self.manager.analysis_requirements_save({
            "context_id": context["id"], "question": QUESTION, "items": [],
            "scope": {"period": PERIOD, "organization": COMPANY, "unit": UNIT, "currency": CURRENCY},
        })

        def kpi(label: str, column: str = "col_C_本年累计") -> dict:
            return {"alias": "kpi", "match": {"col_A_指标": label}, "column": column}

        group = {
            "revenue": kpi("营业收入（万元）"),
            "revenue_py": kpi("营业收入（万元）", "col_D_上年同期累计"),
            "revenue_py_full": kpi("营业收入（万元）", "col_H_上年全年"),
            "revenue_budget_full": kpi("营业收入（万元）", "col_F_全年预算"),
            "gross_margin": kpi("综合毛利率"),
            "expense_ratio": kpi("期间费用率"),
            "operating_profit": kpi("营业利润（万元）"),
            # The board states last year's full year for the parent's share only, so all three read it.
            "net_profit": kpi("归属于母公司净利润（万元）"),
            "net_profit_py": kpi("归属于母公司净利润（万元）", "col_D_上年同期累计"),
            "net_profit_py_full": kpi("归属于母公司净利润（万元）", "col_H_上年全年"),
            "collection_rate_current": kpi("本年账单物业费收缴率"),
            "collection_rate_current_py": kpi("本年账单物业费收缴率", "col_D_上年同期累计"),
            "collection_rate_total": kpi("综合收缴率（含往年欠费）"),
            "ar_end": kpi("应收账款账面余额（万元）"),
            "months_elapsed": 8,
        }
        city = {"alias": "city", "name_column": "organization", "exclude": ["合计", "总计"],
                "columns": {"revenue": "col_E_营业收入", "cost": "col_F_营业成本", "period_expense": "col_I_期间费用",
                            "impairment": "col_J_减值损失", "operating_profit": "col_K_营业利润",
                            "ar_end": "col_L_应收账款", "collection_rate_current": "col_M_本年收缴率"}}
        scenario = self.manager.save_scenario({
            "context_id": context["id"], "kind": "collection_health", "label": "回款健康（集团与城市公司）",
            # The group's 敏感性表 (毛利率 × 收缴率 → 距生死线) is on its board.
            "inputs": {"entities": [{"name": COMPANY, "values": group, "sensitivity": True}], "entity_tables": [city]},
        })
        return self.manager.run_scenario({"scenario_id": scenario["id"]})


    # -- 4. 文稿 ---------------------------------------------------------------------------

    def draft(self, run: dict) -> dict:
        """The manager's paragraph on the group's collection, every number tied to the run or a cell."""
        from decimal import ROUND_HALF_UP, Decimal

        from foundry.finance_explanations import prepare_explanation

        rows = run["result"]["rows"]
        facts = {fact["row"]: fact for fact in prepare_explanation(self.analysis, [run])["facts"]
                 if fact["column"] == "value"}
        claims: list[dict] = []
        located: dict[str, dict] = {}

        def written(key: str) -> str:
            index = next(i for i, row in enumerate(rows) if row["entity"] == COMPANY and row["metric_key"] == key)
            fact = facts[index]
            located[key] = fact
            claims.append({"basis": "calculation", "fact_id": fact["id"], "run_id": run["id"], "row": index,
                           "column": "value", "value": fact["value"],
                           "presentation": {"decimal_places": 2, "scale": "identity", "rounding": "half_up"}})
            return f"{Decimal(fact['value']).quantize(Decimal('0.01'), ROUND_HALF_UP):,.2f}"

        body = (
            f"1-8 月综合毛利率 {written('gross_margin')}%，期间费用率 {written('expense_ratio')}%，"
            f"按此测算的收缴率生死线为 {written('break_even_collection')}%。"
            f"本年账单物业费收缴率距生死线 {written('collection_gap')} 个百分点，"
            f"综合收缴率距生死线 {written('collection_gap_total')} 个百分点，每收一百元物业费仍在倒贴现金。"
            f"近十二个月营业收入 {written('ttm_revenue')} 万元，应收账款周转 {written('dso')} 天。"
            "合同台账本年实收与月结区域实收、应收滚动两处差异已转合同管理部和应收会计核对，结论待其回复后更新。"
        )
        board = self.dataset(MONTH_CLOSE)
        # The two ratios the board states itself, read back from their cells (the board keeps fractions).
        recipes = [
            {"id": key, "kind": "direct", "scale": "100", "unit": "%",
             "claim": {"run_id": run["id"], "row": located[key]["row"], "column": "value"},
             "dataset_id": board["id"], "source_hash": board["source_hash"], "sheet": "01·核心指标看板", "range": cell}
            for key, cell in (("gross_margin", "C14"), ("expense_ratio", "C19"))
        ]
        return self.manager.save_explanation_draft({
            "title": "华宸物业 8 月回款与现金", "body": body, "run_ids": [run["id"]],
            "claims": claims, "evidence_recipes": recipes,
        })


    # -- 6. 看板 ---------------------------------------------------------------------------

    def dashboard(self, run: dict) -> dict:
        """The 回款健康 template's cards as the app lays them (app/src/views/analysis/dashboardTemplates.ts)."""
        rows = run["result"]["rows"]
        accepted = {"state": "accepted", "note": BOARD_NOTE}
        cards = [{"kind": "figure", "title": row["metric_label"][:60], **accepted, "run_id": run["id"], "template": "collection",
                  "select": {"match": {"entity": COMPANY, "metric_key": key, "scenario": "本期"}, "column": "value"}}
                 for key in BOARD_FIGURES for row in rows
                 if row["entity"] == COMPANY and row["metric_key"] == key and row["scenario"] == "本期"]
        cards.append({"kind": "rank", "title": "各主体距生死线（从低到高）", **accepted, "run_id": run["id"], "template": "collection",
                      "select": {"match": {"metric_key": "collection_gap", "scenario": "本期", "entity_origin": "table"},
                                 "label": "entity", "column": "value", "order": "asc", "limit": 10,
                                 "reference": {"value": "0", "label": "生死线"}}})
        cards.append({"kind": "scenario", "title": "回款情景：收缴率变了会怎样", "state": "pinned", "run_id": run["id"],
                      "template": "collection", "select": {"match": {"entity": COMPANY, "scenario": "本期"}}})
        cards.append({"kind": "goal", "title": "倒推：收缴率回到生死线要多收多少", "state": "pinned", "run_id": run["id"],
                      "template": "collection", "select": {"match": {"entity": COMPANY, "scenario": "本期"}, "goal": "collection"}})
        cards.append({"kind": "sensitivity", "title": "敏感性：毛利率和收缴率一起变", "state": "pinned", "run_id": run["id"],
                      "template": "collection", "select": {"match": {"entity": COMPANY, "scenario": "本期"}}})
        return self.manager.dashboard_save({"parent_id": None, "cards": cards})


# The 回款健康 template's figures, in its order; the example's run has the first four.
BOARD_FIGURES = ("collection_gap", "collection_gap_total", "break_even_collection", "dso", "ar_buildup", "cash_collection_ratio")
BOARD_NOTE = "示例预置的认可，不是经理的认可。"


def _decision(label: str) -> dict[str, Any]:
    """What the example decides on each planted difference, with the reason a manager would write."""
    if "台账" in label:
        return {"decision": "pending_external", "counterparty": "合同管理部",
                "reason": "合同台账本年实收比月结区域实收少 2,793.28 万元，五个区域都少，请合同管理部核对台账收款登记是否漏记",
                "decided_by_name": DECIDER}
    if "应收滚动" in label:
        return {"decision": "pending_external", "counterparty": "应收会计",
                "reason": "期末余额比年初 + 新增 − 收回 − 核销多 1,200 万元，疑似本期收回少记，请应收会计核对回款流水后更正",
                "decided_by_name": DECIDER}
    return {"decision": "waived",
            "reason": "账单年度坏账分项按应收余额逐年计提，合计取总账 1231 账龄组合数，两者口径不同；本月按总账数出报表，差异在附注说明",
            "decided_by_name": DECIDER}


def billing(task) -> dict:
    """Step 5: the 收费明细 filed and confirmed, the default 口径 confirmed, and the rates run."""
    from foundry import billing_sample
    from foundry.billing_detail import DEFAULT_CALIBER, BillingDetailStore
    from foundry.sample_task import add_billing

    details = add_billing(task, confirm=True)
    store = BillingDetailStore(task, actor="manager")
    store.caliber_confirm(params=DEFAULT_CALIBER)
    return store.collection_run({
        **{kind: row["id"] for kind, row in details.items()},
        "as_of": billing_sample.AS_OF_TEXT, "group_by": ["nature"],
        "reported": {"collection_rate_current": billing_sample.REPORTED_CURRENT},
    })


def build_reference(task) -> dict:
    """Take a freshly filed practice task through the whole route; any step that fails raises."""
    reference = Reference(task)
    reference.confirm_structures()
    reference.confirm_controls()
    reference.decide_differences()
    run = reference.collection_health()
    if run.get("execution_status") != "succeeded":
        raise FoundryError(f"the example collection run failed: {run.get('error')}")
    draft = reference.draft(run)
    collection = billing(task)
    board = reference.dashboard(run)
    return {"run_id": run["id"], "draft_id": draft["id"], "collection_run_id": collection["id"], "dashboard_id": board["id"]}
