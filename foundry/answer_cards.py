"""Cards in the assistant's answer: figures drawn under its reply in the conversation, as the board would draw them.

The assistant names cards; the server draws them. A card names a stored run and which of its rows it shows, checked
as a board card is checked (foundry/dashboards.py normalize_select), and every figure on it is written here from that
run with the board's own rules (foundry/figure_text.py). So a card shows only a figure a run holds, in the words the
board prints it, and a card that names the wrong rows is refused rather than drawn with the wrong figure. Nothing is
stored: a card in the conversation is not a deliverable. 钉到看板 is the manager's own click, and it goes through the
board's own save (notes/intelligent-ui-borrowing-plan-20261010.md, 五).

Seven kinds:

- ``figure``: one figure of an analysis run, named as a board figure card names it; or one rate or amount of a
  收费明细 collection run, for the whole or one group.
- ``compare``: two to four figures side by side, each named as a figure card. Nothing is computed between them.
- ``rank``: an analysis run's rows ranked as a board rank card ranks them, or a collection run's groups by one figure.
- ``bridge``: one group's profit bridge of a variance run, as a board bridge card draws it.
- ``trend``: one figure of an analysis run across the periods its rows hold, oldest first.
- ``goal`` (倒推): a collection-health run's lines worked back from a target collection rate or the revenue budget, as
  the board's goal card works them (foundry/what_if.py); or a 收费明细 collection run's bills: how much more a rate
  needs collected to reach a target.
- ``sensitivity`` (敏感性表): the part of a collection-health run's grid around where its entity stands.

Goal and sensitivity cards are what-ifs: each carries 情景，不是实际数.

The 接着问 questions under the cards are text only: a click puts one in the composer for the manager to edit and send.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from decimal import Decimal, InvalidOperation

from foundry import dashboards, what_if
from foundry.dashboard_snapshot import BRIDGE_DELTAS, bridge_lines, ranked
from foundry.errors import FoundryError
from foundry.figure_text import (
    accounting,
    cell_text,
    column_label,
    decimal_to_fixed,
    format_period,
    group_digits,
    js_text,
    row_unit,
    scenario_words,
    split_display,
)

KINDS = ("figure", "compare", "rank", "bridge", "trend", "goal", "sensitivity")
MAX_CARDS = 3
MAX_FOLLOW_UPS = 3
MAX_FOLLOW_UP = 40
MAX_COMPARE = 4
MAX_TREND = 24
MIN_TREND = 3
# The board lists a figure's other lines beside it, at most six (dashboardViews.figureView, Dashboard.tsx).
MAX_BESIDE = 6
ID = re.compile(r"[0-9a-f]{32}")

# What the board writes beside an analysis figure of the actual column (BusinessResultView.tsx kpiFor).
BUDGET_FIELDS = ("budget", "baseline", "same_period_budget")
DIFFERENCE_FIELDS = ("variance", "difference", "amount_change", "profit_impact", "contribution")
RATE_FIELDS = ("attainment_rate", "attainment_pct", "achievement_pct", "completion_pct", "attainment", "attainment_ratio",
               "budget_attainment", "budget_attainment_rate", "budget_completion", "budget_completion_rate",
               "completion_rate", "completion", "achievement_rate", "achievement", "actual_budget_rate",
               "actual_budget_ratio", "actual_to_budget", "ratio")

# A collection run's figures a card may show: its words, whether it is a rate, and what the 收费明细 panel lists
# under it (BillingPanel.tsx Kpi).
COLLECTION_FIGURES: dict[str, tuple[str, str, tuple[tuple[str, str], ...]]] = {
    "collection_rate_current": ("当期收缴率", "rate", (("receivable", "本年应收"), ("collected", "当期已收"))),
    "arrears_recovery_rate": ("清欠率", "rate", (("arrears_opening", "年初往年欠费"), ("arrears_collected", "本年收回"))),
    "collection_rate_total": ("综合收缴率", "rate", (("outstanding", "未收合计"), ("advance_balance", "预收余额"))),
    "collection_rate_month": ("本月收缴率", "rate", (("month_receivable", "本月应收"), ("month_collected", "本月已收"))),
    "waiver_rate": ("减免率", "rate", (("waiver", "减免额"),)),
    "household_rate": ("交清的户占比", "rate", ()),
    "receivable": ("本年应收", "amount", ()),
    "collected": ("当期已收", "amount", ()),
    "month_receivable": ("本月应收", "amount", ()),
    "month_collected": ("本月已收", "amount", ()),
    "arrears_opening": ("年初往年欠费", "amount", ()),
    "arrears_collected": ("本年收回往年欠费", "amount", ()),
    "outstanding": ("未收合计", "amount", ()),
    "advance_balance": ("预收余额", "amount", ()),
    "waiver": ("减免额", "amount", ()),
}
# The rates a goal card can work back on a collection run: the rate, its base and what has come in against it.
GOAL_FIGURES: dict[str, tuple[str, tuple[str, str], tuple[str, str]]] = {
    "collection_rate_current": ("当期收缴率", ("receivable", "本年应收"), ("collected", "当期已收")),
    "collection_rate_month": ("本月收缴率", ("month_receivable", "本月应收"), ("month_collected", "本月已收")),
    "arrears_recovery_rate": ("清欠率", ("arrears_opening", "年初往年欠费"), ("arrears_collected", "本年收回往年欠费")),
}
MAX_GOAL_GROUPS = 5
GROUP_LABELS = {"nature": "房产性质", "project": "项目", "fee_item": "收费项目", "customer_type": "客户性质",
                "type": "房产类型", "owner": "产权归属", "city": "城市公司"}
CALIBER_STATUS = {"confirmed": "已确认口径", "default": "默认口径（未确认）", "trial": "试算"}
CALIBER_KEYS = {"year_start_month": "年度起始月", "total_method": "综合收缴率算法", "related_owners": "关联方",
                "exclude_related": "剔除关联方", "excluded_fee_items": "不计入的收费项目"}

# How the result page names a run's state and engine (presentation.tsx STATUS, figureSourceInfo.ts engineLabels).
STATUS = {"pending": "未计算", "running": "计算中", "succeeded": "计算成功", "success": "计算成功", "failed": "计算失败",
          "unreviewed": "未阅", "reviewed": "已阅", "accepted": "经理认可"}
ENGINES = {"sql": "SQL 计算", "python": "脚本计算", "shell": "脚本计算", "finance": "财务引擎",
           "structured_aggregate": "按结构汇总"}
# The row fields that say where a figure came from (figureSourceInfo.ts sourceFields).
SOURCE_FIELDS = (("source", "取数"), ("来源", "取数"), ("source_note", "说明"), ("口径与来源", "口径与来源"),
                 ("actual_label", "实际"), ("budget_label", "预算"), ("caliber", "口径"), ("口径", "口径"),
                 ("formula", "公式"), ("公式", "公式"))
MAX_SOURCE_LINE = 300


class Card(Exception):
    """A card that cannot be drawn, with the reason in the words the assistant reads."""


def _health(run: dict) -> bool:
    result = run.get("result") or {}
    return run.get("engine") == "finance" and result.get("scenario_kind") == "collection_health" \
        and isinstance(result.get("rows"), list)


def _rows(run: dict) -> list[dict]:
    rows = (run.get("result") or {}).get("rows")
    return rows if isinstance(rows, list) else []


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _shown(text: str) -> dict:
    return accounting(text)


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Card(f"{label} is required text")
    if len(value.strip()) > maximum:
        raise Card(f"{label} is longer than {maximum} characters")
    if "\n" in value or "\r" in value:
        raise Card(f"{label} is one line")
    return value.strip()


# --- analysis runs --------------------------------------------------------------------------------


def _value_for(row: dict, names: tuple[str, ...]) -> str:
    """The first of these fields with a value, as the board's KPI card writes it (BusinessResultView.tsx valueFor)."""
    for name in names:
        if name in row and row[name] not in (None, ""):
            return cell_text(row[name], name, row)
    return "—"


def _rate_label(row: dict) -> str:
    field = next((name for name in RATE_FIELDS if row.get(name) not in (None, "")), None) \
        or next((name for name in RATE_FIELDS if name in row), None)
    if field is None:
        return "达成率"
    label = column_label(field)
    return "达成率" if label == field else label


def analysis_figure(run: dict, select: Any) -> tuple[dict, dict]:
    """One figure of a run as the board's figure card shows it, and the selector it was read with."""
    try:
        select = dashboards.normalize_select("figure", select, run)
    except FoundryError as exc:
        raise Card(str(exc)) from None
    rows = _rows(run)
    row = dashboards.matching_rows(rows, select["match"])[0][1]
    column = select["column"]
    if _health(run):
        beside = [[js_text(item.get("scenario")), js_text(item.get("display_value"))] for item in rows
                  if item is not row and item.get("entity") == row.get("entity") and item.get("metric_key") == row.get("metric_key")]
        view = {"subject": js_text(row.get("entity")), "part": js_text(row.get("scenario")),
                "value": _shown(js_text(row.get("display_value"))), "beside": beside[:MAX_BESIDE],
                "level": row.get("level") if isinstance(row.get("level"), str) else None,
                "level_label": row.get("level_label") or None, "row": row}
        return view, select
    period = "未声明期间" if row.get("period") in (None, "") else format_period(row["period"])
    unit = "未声明单位" if row.get("unit") in (None, "") else js_text(row["unit"])
    beside: list[list[str]] = []
    if column == "actual":
        budget = "预算（估算）" if row.get("same_period_budget_estimated") is True else "预算"
        beside = [[label, text] for label, text in ((budget, _value_for(row, BUDGET_FIELDS)),
                                                    ("差异", _value_for(row, DIFFERENCE_FIELDS)),
                                                    (_rate_label(row), _value_for(row, RATE_FIELDS)))
                  if text and text != "—"]
    view = {"subject": f"{period} · {unit}", "part": "实际" if column == "actual" else column_label(column),
            "value": _shown(cell_text(row.get(column), column, row)), "beside": beside, "level": None,
            "level_label": None, "row": row}
    return view, select


def analysis_rank(run: dict, select: Any) -> tuple[dict, dict]:
    try:
        select = dashboards.normalize_select("rank", select, run)
    except FoundryError as exc:
        raise Card(str(exc)) from None
    health = _health(run)
    unit, items = "", []
    for row, value in ranked({"select": select}, run):
        if health and isinstance(row.get("display_value"), str):
            figure, written = split_display(row["display_value"])
        else:
            figure, written = group_digits(row.get(select["column"])), js_text(row["unit"]) if isinstance(row.get("unit"), str) else ""
        unit = unit or written
        note = row.get("level_label") if isinstance(row.get("level_label"), str) and row.get("level_label") else None
        items.append({"label": js_text(row.get(select["label"])), "value": value, "text": figure, "note": note,
                      "level": row.get("level") if health and isinstance(row.get("level"), str) else None})
    reference = select.get("reference")
    view = {"items": items, "unit": unit,
            "reference": {"value": _float(reference["value"]), "label": reference["label"]} if reference else None,
            "order": select["order"]}
    return view, select


def _side_unit(scope: Any) -> str | None:
    unit = scope.get("unit") if isinstance(scope, dict) else None
    if isinstance(unit, list):
        return None
    return unit if isinstance(unit, str) else ""


def _bridge_unit(row: dict) -> str | None:
    """The profit line's unit (RunPanel.tsx rowUnit): its own, else both sides' agreeing one; None when they differ."""
    if isinstance(row.get("unit"), str) and row["unit"]:
        return row["unit"]
    actual, baseline = _side_unit(row.get("actual_scope")), _side_unit(row.get("baseline_scope"))
    if actual is None or baseline is None or (actual and baseline and actual != baseline):
        return None
    return actual or baseline or ""


def _variance_labels(run: dict) -> tuple[str, str]:
    """The two sides of a variance run in words (RunPanel.tsx financeVarianceCopy)."""
    comparison = (run.get("result") or {}).get("comparison")
    comparison = comparison if isinstance(comparison, dict) else {}

    def words(value: Any, default: str) -> str:
        return default if value is None else js_text(value)

    def period(filters: Any) -> str:
        value = filters.get("period") if isinstance(filters, dict) else None
        return value if isinstance(value, str) else ""

    actual = words(comparison.get("actual_scenario"), "actual")
    baseline = words(comparison.get("baseline_scenario"), "baseline")
    actual_period, baseline_period = period(comparison.get("actual_filters")), period(comparison.get("baseline_filters"))
    same_words = format_period(actual_period) == format_period(baseline_period)

    def with_period(text: str, value: str) -> str:
        if actual_period != baseline_period and value:
            return f"{text}（{value if same_words else (format_period(value) or '—')}）"
        return text

    actual_label = with_period(scenario_words(actual, "actual"), actual_period)
    baseline_label = with_period(scenario_words(baseline, "baseline"), baseline_period)
    if actual_label == baseline_label:
        baseline_label = f"对照（{baseline_label}）"
    return baseline_label, actual_label


def _bridge_number(value: Any) -> float | None:
    text = "" if value is None else js_text(value).strip()
    return float(text) if re.fullmatch(r"[-+]?[0-9]*\.?[0-9]+", text) else None


def analysis_bridge(run: dict, select: Any) -> tuple[dict, dict]:
    try:
        select = dashboards.normalize_select("bridge", select, run)
    except FoundryError as exc:
        raise Card(str(exc)) from None
    found = [row for _, row in dashboards.matching_rows(_rows(run), select["match"])]
    lines = bridge_lines({"select": select}, run)
    if lines is None:
        raise Card("a bridge card names one group's profit, revenue, cost and expense lines; "
                   "add the group's columns to match")
    if any(row.get("comparison_status") == "partial" for row in found):
        raise Card("this group has a 缺项 (comparison_status partial); its bridge would not close")
    profit = next(row for row in found if row.get("metric") == "profit")
    unit = _bridge_unit(profit)
    if unit is None:
        raise Card("the two sides of this group are in different units; it has no bridge")
    baseline_label, actual_label = _variance_labels(run)
    labels = {"baseline": f"{baseline_label}利润", "revenue": "收入", "cost": "成本", "expense": "费用",
              "actual": f"{actual_label}利润"}
    steps = []
    for line, value in lines:
        number = _bridge_number(value)
        if number is None:
            raise Card(f"the {line} line of this group has no figure; it has no bridge")
        steps.append({"label": labels[line], "kind": "delta" if line in BRIDGE_DELTAS else "total", "value": number,
                      "text": group_digits(js_text(value).strip())})
    moved = sum(step["value"] for step in steps[1:-1])
    if abs(steps[0]["value"] + moved - steps[-1]["value"]) > 0.005 * len(steps):
        raise Card("this group's contributions do not add up to the change in profit; it has no bridge")
    subject = " · ".join(format_period(text) if name == "period" else text for name, text in select["match"].items())
    return {"steps": steps, "unit": unit, "subject": subject}, select


def analysis_trend(run: dict, select: Any) -> dict:
    if not isinstance(select, dict):
        raise Card("a trend card's select is an object")
    match = dashboards._match(select.get("match"))
    column = select.get("column")
    period = select.get("period", "period")
    if not isinstance(column, str) or not column or not isinstance(period, str) or not period:
        raise Card("a trend card names the figure's column, and the period column if it is not period")
    points, seen = [], set()
    for _, row in dashboards.matching_rows(_rows(run), match):
        when, value = row.get(period), _float(row.get(column))
        if when in (None, "") or value is None:
            continue
        key = js_text(when)
        if key in seen:
            raise Card(f"two rows hold {key}; name the rows of one line only, so each period has one figure")
        seen.add(key)
        points.append({"period": key, "label": format_period(key), "value": value,
                       "text": cell_text(row.get(column), column, row), "row": row})
    if len(points) < MIN_TREND:
        raise Card(f"a trend card needs at least {MIN_TREND} periods with a figure; these rows hold {len(points)}")
    if len(points) > MAX_TREND:
        raise Card(f"a trend card shows at most {MAX_TREND} periods")
    points.sort(key=lambda point: point["period"])
    units = {js_text(row_unit(point["row"]) or "") for point in points}
    if len(units) > 1:
        raise Card(f"these rows are in different units ({'、'.join(sorted(units))}); name the rows of one line only")
    unit = row_unit(points[0]["row"])
    return {"points": points, "unit": "" if unit is None else js_text(unit), "part": column_label(column),
            "subject": " · ".join(match.values())}


def analysis_source(store, run: dict, row: dict | None) -> dict:
    """Where an analysis card's figures came from, as the result page's 来源 card says it (figureSourceInfo.ts)."""
    lines, seen = [], set()
    for field, label in SOURCE_FIELDS:
        value = (row or {}).get(field)
        if value in (None, ""):
            continue
        text = js_text(value)
        if text in seen or text == "—":
            continue
        seen.add(text)
        lines.append([label, text[:MAX_SOURCE_LINE]])
    files = []
    for alias, dataset_id in (run.get("bindings") or {}).items():
        try:
            name = store.analysis._get("datasets", dataset_id).get("name") or alias
        except FoundryError:
            name = alias
        files.append({"name": name, "digest": js_text((run.get("input_hashes") or {}).get(alias) or "")[:12]})
    computed = " · ".join(part for part in (
        STATUS.get(run.get("review_status"), run.get("review_status") or ""),
        ENGINES.get(run.get("engine"), run.get("engine") or "")) if part)
    return {"kind": "analysis", "run_id": run["id"], "analysis_id": run.get("analysis_id"), "at": run.get("created_at"),
            "computed": computed, "lines": lines, "files": files}


# --- collection runs ------------------------------------------------------------------------------


def _percent(rate: Any) -> str:
    return "—" if rate is None else f"{decimal_to_fixed(rate, 2, 100)}%"


def _collection_text(kind: str, value: Any) -> str:
    return _percent(value) if kind == "rate" else decimal_to_fixed(value, 2)


def _figure_key(value: Any) -> str:
    if value not in COLLECTION_FIGURES:
        raise Card("figure is one of: " + ", ".join(COLLECTION_FIGURES))
    return value


def _group_words(key: dict) -> str:
    return " · ".join("（空）" if value is None else js_text(value) for value in key.values())


def _collection_figures(run: dict, group: Any) -> tuple[dict, str]:
    """The figures of the whole run, or of the one group ``group`` names, and the words for which."""
    result = run.get("result") or {}
    if group is None:
        return result.get("figures") or {}, "全部"
    if not isinstance(group, dict) or not group:
        raise Card("group names a group of the run: {column: text}, as its groups are keyed")
    groups = [row for row in result.get("groups") or []
              if set(row.get("key") or {}) == set(group)
              and all(("" if row["key"][name] is None else js_text(row["key"][name])) == js_text(text).strip()
                      for name, text in group.items())]
    if not result.get("groups"):
        raise Card("this collection run has no groups; run it again grouped (group_by) to show one group")
    if len(groups) != 1:
        names = "、".join(GROUP_LABELS.get(name, name) for name in (result["groups"][0].get("key") or {}))
        some = "；".join(json.dumps(row.get("key"), ensure_ascii=False) for row in result["groups"][:8])
        raise Card(f"group names {len(groups)} of the run's groups; they are keyed by {names}: {some}"
                   + ("…" if len(result["groups"]) > 8 else ""))
    return groups[0].get("figures") or {}, _group_words(groups[0]["key"])


def collection_figure(run: dict, figure: Any, group: Any) -> dict:
    key = _figure_key(figure)
    label, kind, parts = COLLECTION_FIGURES[key]
    figures, subject = _collection_figures(run, group)
    value = figures.get(key)
    if value is None:
        raise Card(f"{label} has no figure here (its base is zero)")
    beside = []
    reported = (figures.get("reported") or {}).get(key) if group is None else None
    if reported:
        beside.append(["套表", _percent(reported.get("reported"))])
        if reported.get("difference_points") is not None:
            beside.append(["差", f"{reported['difference_points']} 个百分点"])
    beside += [[words, decimal_to_fixed(figures.get(field), 2)] for field, words in parts if figures.get(field) is not None]
    return {"subject": subject, "part": label, "value": _shown(_collection_text(kind, value)),
            "beside": beside[:MAX_BESIDE], "level": None, "level_label": None}


def collection_rank(run: dict, spec: dict) -> dict:
    key = _figure_key(spec.get("figure"))
    label, kind, _ = COLLECTION_FIGURES[key]
    groups = (run.get("result") or {}).get("groups") or []
    if not groups:
        raise Card("this collection run has no groups; run it again grouped (group_by) to rank them")
    order = spec.get("order", "asc")
    if order not in dashboards.ORDERS:
        raise Card("a rank card orders asc or desc")
    limit = spec.get("limit", 10)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= dashboards.MAX_RANK:
        raise Card(f"a rank card shows 1 to {dashboards.MAX_RANK} rows")
    scale = 100 if kind == "rate" else 1
    rows = [(row, _float((row.get("figures") or {}).get(key))) for row in groups]
    rows = [(row, value * scale) for row, value in rows if value is not None]
    if len(rows) < 2:
        raise Card("a rank card needs at least two groups with a figure to rank")
    rows.sort(key=lambda pair: pair[1], reverse=order == "desc")
    items = [{"label": _group_words(row["key"]),
              "value": value,
              "text": decimal_to_fixed(row["figures"][key], 2, scale), "note": None, "level": None}
             for row, value in rows[:limit]]
    reference = spec.get("reference")
    if reference is not None:
        if not isinstance(reference, dict) or _float(reference.get("value")) is None:
            raise Card("a rank card reference is a figure with a label")
        # Written as the run writes its rates (0.8 for 80%), and drawn on the bars' scale.
        reference = {"value": _float(reference["value"]) * scale,
                     "label": _text(reference.get("label"), "reference label", dashboards.MAX_TITLE)}
    by = "、".join(GROUP_LABELS.get(name, name) for name in (groups[0].get("key") or {}))
    return {"items": items, "unit": "%" if kind == "rate" else "", "reference": reference, "order": order,
            "part": label, "subject": f"按{by}"}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(js_text(value).strip().replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _still_needed(figures: dict, base: str, done: str, rate: Decimal) -> Decimal | None:
    """What the bills still need collected for the rate to reach ``rate``: base × rate − what has come in."""
    whole, came = _decimal(figures.get(base)), _decimal(figures.get(done))
    if whole is None or came is None or whole <= 0:
        return None
    return whole * rate - came


def collection_goal(run: dict, spec: dict) -> dict:
    """How much more a collection rate needs collected to reach the target, from the run's own bills."""
    key = spec.get("figure", "collection_rate_current")
    if key not in GOAL_FIGURES:
        raise Card("a goal card on a collection run works back " + ", ".join(GOAL_FIGURES))
    label, (base, base_words), (done, done_words) = GOAL_FIGURES[key]
    if spec.get("target") is None:
        raise Card("a goal card on a collection run names its target, a rate with its %, such as 92%")
    try:
        target = dashboards.goal_target(spec["target"])
    except FoundryError as exc:
        raise Card(str(exc)) from None
    rate = Decimal(target[:-1]) / 100
    figures, subject = _collection_figures(run, spec.get("group"))
    need = _still_needed(figures, base, done, rate)
    if need is None:
        raise Card(f"{label} has no {base_words} here to work back from")
    shown = f"{decimal_to_fixed(target[:-1], 2)}%"
    beside = [[f"目标{label}", shown], [f"{label}（这次计算）", _percent(figures.get(key))],
              [base_words, decimal_to_fixed(figures.get(base), 2)], [done_words, decimal_to_fixed(figures.get(done), 2)]]
    groups = None
    every = (run.get("result") or {}).get("groups") or []
    if spec.get("group") is None and every:
        short = [(row, _still_needed(row.get("figures") or {}, base, done, rate)) for row in every]
        short = sorted(((row, amount) for row, amount in short if amount is not None and amount > 0),
                       key=lambda pair: pair[1], reverse=True)[:MAX_GOAL_GROUPS]
        by = "、".join(GROUP_LABELS.get(name, name) for name in (every[0].get("key") or {}))
        if short:
            groups = {"title": f"按{by}，还要收得最多的 {len(short)} 个",
                      "lines": [[_group_words(row["key"]), decimal_to_fixed(format(amount, "f"), 2)] for row, amount in short]}
    # What reads as 0.00 either way has reached the target: neither still to collect nor collected past it.
    met = decimal_to_fixed(format(abs(need), "f"), 2) == "0.00"
    return {"subject": f"{subject} · {label}到 {shown}",
            "part": "已达到目标" if met else "还要收" if need > 0 else "已超过目标，多收了",
            "value": {"text": shown if met else decimal_to_fixed(format(abs(need), "f"), 2), "negative": False},
            "beside": beside, "groups": groups, "basis": [],
            "caption": f"还要收 = {base_words} × 目标{label} − {done_words}，按这次计算的口径和截止日算；之后新出的账单不在里面。"}


def collection_source(run: dict) -> dict:
    caliber = run.get("caliber") or {}
    status = caliber.get("status")
    words = f"已确认口径 · 第 {caliber['version']} 版" if status == "confirmed" and caliber.get("version") \
        else CALIBER_STATUS.get(status, js_text(status))
    lines = [["口径", words]]
    if status == "trial":
        differs = "、".join(CALIBER_KEYS.get(name, name) for name in caliber.get("differs") or [])
        lines.append(["注意", f"这次和已确认口径不同的地方：{differs}。经理确认口径前，这些数只作参考。"])
    window = (run.get("result") or {}).get("window") or {}
    if window:
        lines.append(["范围", f"本年 {window.get('year_start')} 起到 {window.get('as_of')}"])
    files = []
    for entry in (run.get("inputs") or {}).values():
        for file in entry.get("files") or []:
            files.append({"name": f"{entry.get('name')} · {file.get('name')}", "digest": js_text(file.get("sha256") or "")[:12]})
    return {"kind": "collection", "run_id": run["id"], "at": run.get("created_at"), "computed": "收费明细计算",
            "lines": lines, "files": files, "trial": status == "trial"}


# --- one card -------------------------------------------------------------------------------------


class Reader:
    """The runs one call reads, each once: analysis runs through the store's own authorization, collection runs from
    the task's 收费明细 folder."""

    def __init__(self, store):
        self.store = store
        self.analysis: dict[str, dict] = {}
        self.collection: dict[str, dict] = {}

    def run(self, run_id: Any) -> dict:
        if not isinstance(run_id, str) or not ID.fullmatch(run_id):
            raise Card("run_id is the 32-character id of a run that succeeded")
        if run_id not in self.analysis:
            try:
                run = self.store._named_run(run_id)
            except FoundryError as exc:
                raise Card(str(exc)) from None
            if run.get("execution_status") not in {"succeeded", "success"}:
                raise Card("a card reads a run that succeeded")
            self.analysis[run_id] = run
        return self.analysis[run_id]

    def collection_run(self, run_id: Any) -> dict:
        from foundry.billing_detail import BillingDetailStore

        if not isinstance(run_id, str) or not ID.fullmatch(run_id):
            raise Card("collection_run_id is the 32-character id collection_run returned")
        if run_id not in self.collection:
            try:
                self.collection[run_id] = BillingDetailStore(self.store.task).read_run(run_id)
            except FoundryError as exc:
                raise Card(str(exc)) from None
        return self.collection[run_id]


def _figure(reader: Reader, spec: dict) -> dict:
    """One figure, of an analysis run or a collection run, with its source and what 钉到看板 would pin."""
    if spec.get("collection_run_id") is not None:
        if spec.get("run_id") is not None:
            raise Card("a figure reads run_id or collection_run_id, not both")
        run = reader.collection_run(spec["collection_run_id"])
        return {**collection_figure(run, spec.get("figure"), spec.get("group")), "source": collection_source(run), "pin": None}
    run = reader.run(spec.get("run_id"))
    view, select = analysis_figure(run, spec.get("select"))
    row = view.pop("row")
    return {**view, "source": analysis_source(reader.store, run, row), "pin": {"kind": "figure", "run_id": run["id"], "select": select}}


def analysis_what_if(kind: str, run: dict, select: Any) -> tuple[dict, dict, dict]:
    """A goal or sensitivity card on a collection-health run, as the board's card says it; its selector; its first line."""
    if not _health(run):
        raise Card(f"a {kind} card reads a collection health run (finance_scenario_run kind=collection_health)")
    try:
        normalized = dashboards.normalize_select(kind, select, run)
    except FoundryError as exc:
        raise Card(str(exc)) from None
    rows = _rows(run)
    entity = next(row for _, row in dashboards.matching_rows(rows, normalized["match"]))["entity"]
    lines = what_if.lines_of(rows, entity)
    if kind == "sensitivity":
        view = what_if.sensitivity(dashboards.sensitivity_grid(run["result"], entity), lines["collection_gap"])
    elif normalized["goal"] == "budget":
        view = what_if.goal_budget(lines, js_text(entity))
    else:
        view = what_if.goal_collection(lines, js_text(entity), normalized.get("target"), (run.get("result") or {}).get("params") or {})
    basis = view.pop("basis")
    view["basis"] = [[js_text(row.get("metric_label") or row.get("metric_key")), js_text(row.get("display_value"))] for row in basis]
    if kind == "goal":
        view["value"] = {"text": view["value"], "negative": False}
        view["groups"] = None
    else:
        # A cell in accounting form, as the board's Figure prints it: (3.7) in the muted red below the line.
        for row in view["rows"]:
            for cell in row["cells"]:
                cell.update(_shown(cell["text"]))
    return view, normalized, basis[0]


def draw(reader: Reader, card: Any) -> dict:
    if not isinstance(card, dict):
        raise Card("a card is an object")
    kind = card.get("kind")
    if kind not in KINDS:
        raise Card("kind is one of: " + ", ".join(KINDS))
    title = _text(card.get("title"), "title", dashboards.MAX_TITLE)
    if kind == "figure":
        drawn = _figure(reader, card)
        pin = drawn.pop("pin")
        return {"kind": kind, "title": title, **drawn, "pin": {**pin, "title": title} if pin else None}
    if kind == "compare":
        items = card.get("items")
        if not isinstance(items, list) or not 2 <= len(items) <= MAX_COMPARE:
            raise Card(f"a compare card shows 2 to {MAX_COMPARE} figures in items")
        drawn = []
        for index, item in enumerate(items, 1):
            if not isinstance(item, dict):
                raise Card(f"item {index} is an object")
            try:
                one = _figure(reader, item)
            except Card as exc:
                raise Card(f"item {index}: {exc}") from None
            one.pop("pin")
            drawn.append(one)
        return {"kind": kind, "title": title, "items": drawn, "pin": None}
    if kind == "rank":
        if card.get("collection_run_id") is not None:
            run = reader.collection_run(card["collection_run_id"])
            return {"kind": kind, "title": title, **collection_rank(run, card), "source": collection_source(run), "pin": None}
        run = reader.run(card.get("run_id"))
        view, select = analysis_rank(run, card.get("select"))
        return {"kind": kind, "title": title, **view, "source": analysis_source(reader.store, run, None),
                "pin": {"kind": "rank", "title": title, "run_id": run["id"], "select": select}}
    if kind == "goal" and card.get("collection_run_id") is not None:
        if card.get("run_id") is not None:
            raise Card("a goal card reads run_id or collection_run_id, not both")
        run = reader.collection_run(card["collection_run_id"])
        return {"kind": kind, "title": title, "flag": what_if.FLAG, **collection_goal(run, card),
                "source": collection_source(run), "pin": None}
    run = reader.run(card.get("run_id"))
    if kind in ("goal", "sensitivity"):
        view, select, first = analysis_what_if(kind, run, card.get("select"))
        return {"kind": kind, "title": title, "flag": what_if.FLAG, **view, "source": analysis_source(reader.store, run, first),
                "pin": {"kind": kind, "title": title, "run_id": run["id"], "select": select}}
    if kind == "bridge":
        view, select = analysis_bridge(run, card.get("select"))
        return {"kind": kind, "title": title, **view, "source": analysis_source(reader.store, run, None),
                "pin": {"kind": "bridge", "title": title, "run_id": run["id"], "select": select}}
    view = analysis_trend(run, card.get("select"))
    first = view["points"][0].pop("row")
    for point in view["points"][1:]:
        point.pop("row")
    return {"kind": kind, "title": title, **view, "source": analysis_source(reader.store, run, first), "pin": None}


# --- the call -------------------------------------------------------------------------------------


def _follow_ups(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_FOLLOW_UPS:
        raise FoundryError(f"follow_ups is a list of at most {MAX_FOLLOW_UPS} questions")
    out = []
    for index, text in enumerate(value, 1):
        try:
            question = _text(text, f"follow-up {index}", MAX_FOLLOW_UP)
        except Card as exc:
            raise FoundryError(str(exc)) from None
        if question not in out:
            out.append(question)
    return out


def _summary(card: dict) -> str:
    """One card in a line, for the assistant: what the manager now sees under the reply."""
    if card["kind"] == "figure":
        beside = "；".join(f"{label} {text}" for label, text in card["beside"])
        return f"数字卡「{card['title']}」：{card['subject']} {card['part']} {card['value']['text']}" + (f"（{beside}）" if beside else "")
    if card["kind"] == "compare":
        return f"对比卡「{card['title']}」：" + "；".join(
            f"{item['subject']} {item['part']} {item['value']['text']}" for item in card["items"])
    if card["kind"] == "rank":
        items, unit = card["items"], card["unit"]

        def shown(text: str) -> str:
            return f"{text}{unit}" if unit in ("", "%") else f"{text} {unit}"

        return (f"排名卡「{card['title']}」：{len(items)} 条，第一 {items[0]['label']} {shown(items[0]['text'])}，"
                f"最后 {items[-1]['label']} {shown(items[-1]['text'])}")
    if card["kind"] == "bridge":
        return f"利润桥「{card['title']}」：" + "，".join(f"{step['label']} {step['text']}" for step in card["steps"]) \
            + (f"（{card['unit']}）" if card["unit"] else "")
    if card["kind"] == "goal":
        return f"倒推卡「{card['title']}」（情景）：{card['subject']}，{card['part']} {card['value']['text']}"
    if card["kind"] == "sensitivity":
        here = next((cell["text"] for row in card["rows"] for cell in row["cells"] if cell["current"]), None)
        return (f"敏感性表「{card['title']}」（情景）：{card['subject']}，{len(card['rows'])} 行 × {len(card['columns'])} 列"
                + (f"，现在的位置 {here}" if here else "，现在的位置不在表内"))
    points = card["points"]
    return (f"趋势卡「{card['title']}」：{len(points)} 期，{points[0]['label']} {points[0]['text']} 到 "
            f"{points[-1]['label']} {points[-1]['text']}")


def answer_cards(store, spec: Any) -> dict:
    """The cards and 接着问 questions under one reply, drawn from stored runs; refused whole if one card is wrong."""
    if not isinstance(spec, dict):
        raise FoundryError("answer cards spec must be an object")
    cards = spec.get("cards") or []
    if not isinstance(cards, list) or len(cards) > MAX_CARDS:
        raise FoundryError(f"cards is a list of at most {MAX_CARDS} cards")
    follow_ups = _follow_ups(spec.get("follow_ups"))
    if not cards and not follow_ups:
        raise FoundryError("name at least one card or one follow-up question")
    reader, drawn = Reader(store), []
    for index, card in enumerate(cards, 1):
        try:
            drawn.append(draw(reader, card))
        except Card as exc:
            raise FoundryError(f"card {index}: {exc}") from None
    lines = [f"回答下方已画出 {len(drawn)} 张卡：" if drawn else "回答下方没有卡。"]
    lines += [f"{index}. {_summary(card)}" for index, card in enumerate(drawn, 1)]
    if follow_ups:
        lines.append("接着问：" + "；".join(follow_ups))
    lines.append("卡上的数由运行直接取出，经理可以看来源、打开结果；读分析运行的数字卡、排名卡、利润桥、倒推卡和敏感性表"
                 "可以由经理钉到看板。倒推卡和敏感性表是情景，不是实际数。"
                 "回答已经结束：不要再写一遍卡上的内容，不要说卡已经放上看板。")
    return {"task_id": store.task.id, "cards": drawn, "follow_ups": follow_ups, "text": "\n".join(lines)}


def proposed_card(store, card: dict) -> dict | None:
    """A card the assistant just proposed for the board, drawn as the conversation draws one; None when it cannot be.

    Drawn after the proposal is written, so it must never fail the call: a proposal that stands is not undone by how
    it is shown."""
    try:
        reader = Reader(store)
        title = card["title"]
        if card["kind"] != "scenario":
            drawn = draw(reader, {"kind": card["kind"], "title": title, "run_id": card["run_id"], "select": card["select"]})
            return {**drawn, "pin": None}
        run = reader.run(card["run_id"])
        rows = [row for _, row in dashboards.matching_rows(_rows(run), card["select"].get("match") or {})
                if row.get("metric_key") in dashboards.SCENARIO_LINES]
        rows.sort(key=lambda row: dashboards.SCENARIO_LINES.index(row["metric_key"]))
        return {"kind": "scenario", "title": title, "subject": js_text(rows[0].get("entity")) if rows else "",
                "lines": [[js_text(row.get("metric_label") or row.get("metric_key")), js_text(row.get("display_value"))]
                          for row in rows],
                "source": analysis_source(store, run, None), "pin": None}
    except Exception:  # noqa: BLE001 - showing a proposal never undoes it
        return None
