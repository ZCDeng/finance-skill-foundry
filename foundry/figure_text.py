"""How a figure reads on screen, for the cards the assistant draws in its answer (foundry/answer_cards.py).

The board writes each figure in the renderer (app/src/views/analysis/dashboardViews.ts); a card in the conversation is
drawn in the assistant's own page, which has no access to that code. So the server writes the same text with the same
rules, ported here: grouped thousands, half away from zero, a column's ratio or amount by its name, a row's unit, a
period in words, a negative in accounting parentheses. tests/fixtures/figure_text_cases.json holds both sides to the
same answers (tests/test_figure_text.py and app/tests/figure-text-parity.test.ts), so a card in the conversation and
the board never print one figure two ways.
"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from typing import Any

from foundry.result_semantics import RESULT_METRIC_LABELS

AMOUNT_LABELS = {
    "actual": "实际", "budget": "预算", "baseline": "基准", "same_period_budget": "同期预算", "variance": "差异",
    "difference": "差异", "amount_change": "科目增减", "profit_impact": "利润影响", "contribution": "差异贡献",
    "revenue": "收入", "cost": "成本", "expense": "费用", "profit": "利润", "gross_profit": "毛利", "operating_profit": "营业利润",
}
RATIO_LABELS = {
    "attainment": "达成率", "attainment_rate": "达成率", "attainment_ratio": "达成率", "budget_attainment": "达成率",
    "budget_attainment_rate": "达成率", "budget_completion": "预算完成率", "budget_completion_rate": "预算完成率",
    "completion": "完成率", "completion_rate": "完成率", "completion_ratio": "完成率", "achievement": "达成率",
    "achievement_rate": "达成率", "achievement_ratio": "达成率", "actual_budget_rate": "实际/预算",
    "actual_budget_ratio": "实际/预算", "actual_to_budget": "实际/预算", "ratio": "差异率", "rate": "比例",
    "ratio_delta": "比例变化", "attainment_delta": "达成率变化",
}
RATIO_PCT_LABELS = {"attainment_pct": "达成率"}
RATIO_DELTA_LABELS = {"ratio_delta": "比例变化", "attainment_delta": "达成率变化"}
TEXT_LABELS = {
    "metric": "指标", "metric_key": "指标", "business_key": "业务键", "result_key": "结果键", "period": "期间",
    "granularity": "粒度", "organization": "组织", "organization_id": "组织", "scenario": "情景", "value": "数值",
    "metric_label": "指标说明", "currency": "币种", "unit": "单位", "source": "来源", "source_note": "来源说明",
    "来源": "来源", "口径与来源": "来源", "估算方法": "估算方法", "区域": "区域", "指标": "指标", "单位": "单位",
    "note": "说明", "basis": "依据", "row_basis": "依据", "validation_basis": "依据",
}
MONEY_UNIT_SEGMENTS = frozenset({"万元", "元", "亿元", "千元", "百万元"})
MONEY_TOKENS = frozenset({"amount", "revenue", "cost", "expense", "profit", "cash", "budget", "actual", "variance", "sales",
                          "income"})
NUMERIC_TYPE = re.compile(r"^(DECIMAL|NUMERIC|HUGEINT|UHUGEINT|UBIGINT|BIGINT|UINTEGER|INTEGER|USMALLINT|SMALLINT|UTINYINT"
                          r"|TINYINT|FLOAT|DOUBLE|REAL|INT[0-9]*)\b", re.IGNORECASE)
AMOUNT_NAME = re.compile(r"amount|budget|actual|variance|difference|cost|expense|profit|revenue|income|cash", re.IGNORECASE)
AMOUNT_WORD = re.compile(r"实际|预算|差异|成本|费用|利润|收入|金额|损失")

# The unit table: 比率 and ratio hold a fraction, %, pct and 百分比 a percent, 百分点 a difference of two percentages,
# 「-」 says no unit was marked (businessResults.ts unitKind).
FRACTION_UNITS = frozenset({"比率", "ratio"})
PERCENT_UNITS = frozenset({"%", "％", "pct", "百分比"})
POINT_UNITS = frozenset({"百分点"})
UNMARKED_UNITS = frozenset({"-"})

FIGURE = re.compile(r"[(（]?[-+−]?(?:¥|￥|\$)?\s*[0-9][0-9,]*(?:\.[0-9]+)?%?[)）]?(?:\s*(?:个百分点|百万元|万元|亿元|千元|元|天|倍|%))?"
                    r"(?:\s*[（(][^（）()]{1,8}[)）])?")
PURE_NEGATIVE = re.compile(r"[-−]((?:¥|￥|\$)?[0-9][0-9,]*(?:\.[0-9]+)?%?)")
NEGATIVE = re.compile(r"(?:[-−]|[(（](?=[-−]?(?:¥|￥|\$)?\s*[0-9]))")
MONTH = re.compile(r"((?:19|20)[0-9]{2})-([0-9]{2})")
YEAR = re.compile(r"((?:19|20)[0-9]{2})")
RANGE = re.compile(r"((?:19|20)[0-9]{2})-([0-9]{2}):((?:19|20)[0-9]{2})-([0-9]{2})")


def js_text(value: Any) -> str:
    """A value as the renderer's String() writes it, so both sides start from the same digits."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value == 0:
            return "0"
        if value.is_integer() and abs(value) < 1e21:
            return format(Decimal(repr(value)).to_integral_value(), "f")
        text = repr(value)
        if "e" not in text:
            return text
        # String() writes 0.00001 and 10000000000000000 where Python writes 1e-05 and 1e+16, and 1e-7 where it writes 1e-07.
        if 1e-6 <= abs(value) < 1e21:
            return format(Decimal(text), "f")
        mantissa, exponent = text.split("e")
        return f"{mantissa}e{'+' if int(exponent) >= 0 else '-'}{abs(int(exponent))}"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int) and abs(value) > 2**53:
        # JSON hands the renderer a double: past 2^53 it holds, and writes, the nearest one.
        return js_text(float(value))
    return str(value)


def _group(integer: str) -> str:
    head = len(integer) % 3 or 3
    return ",".join([integer[:head], *(integer[index:index + 3] for index in range(head, len(integer), 3))])


def group_digits(value: Any) -> str:
    """A decimal with its thousands grouped and every place it was written with (figures.ts groupDigits)."""
    if value is None or value == "":
        return "—"
    text = js_text(value).strip()
    found = re.fullmatch(r"([+-]?)([0-9]+)(\.[0-9]+)?", text)
    if not found:
        return text
    return f"{found[1]}{_group(found[2])}{found[3] or ''}"


def decimal_to_fixed(value: Any, places: int, multiplier: int = 1) -> str:
    """A decimal at fixed places, half away from zero in exact arithmetic, thousands grouped (figures.ts decimalToFixed)."""
    if value is None or value == "":
        return "—"
    text = js_text(value).strip().replace(",", "")
    found = re.fullmatch(r"([+-])?([0-9]+)(?:\.([0-9]+))?", text)
    if not found:
        return js_text(value)
    sign, integer, fraction = found[1], found[2], found[3] or ""
    current = int(f"{integer}{fraction}") * multiplier
    excess = len(fraction) - places
    if excess > 0:
        divisor = 10 ** excess
        rounded = current // divisor + (1 if current % divisor >= divisor // 2 else 0)
    else:
        rounded = current * 10 ** -excess
    raw = str(rounded).rjust(places + 1, "0")
    whole, part = (raw[:-places], raw[-places:]) if places else (raw, "")
    return f"{'-' if sign == '-' and rounded else ''}{_group(whole)}{'.' + part if places else ''}"


def accounting(text: str) -> dict:
    """A figure in accounting form (figures.ts accountingFigure): a bare negative in parentheses, a figure with a unit
    word keeping its minus sign; ``negative`` says it takes the muted red. Text that is not one figure stays."""
    trimmed = text.strip()
    if not FIGURE.fullmatch(trimmed):
        return {"text": text, "negative": False}
    pure = PURE_NEGATIVE.fullmatch(trimmed)
    if pure:
        return {"text": f"({pure[1]})", "negative": True}
    return {"text": trimmed, "negative": bool(NEGATIVE.match(trimmed))}


def format_period(value: Any) -> str:
    """A period in words (period.ts formatPeriod): 2026-08 reads 2026 年 8 月, 2026-01:2026-08 reads 2026 年 1–8 月."""
    if value is None or value == "":
        return ""
    text = js_text(value)
    if YEAR.fullmatch(text):
        return f"{text} 年"
    month = MONTH.fullmatch(text)
    if month:
        return f"{month[1]} 年 {int(month[2])} 月" if 1 <= int(month[2]) <= 12 else text
    found = RANGE.fullmatch(text)
    if not found:
        return text
    start_year, start_month, end_year, end_month = found.groups()
    if not (1 <= int(start_month) <= 12 and 1 <= int(end_month) <= 12):
        return text
    start, end = int(start_year) * 12 + int(start_month), int(end_year) * 12 + int(end_month)
    if start > end:
        return text
    if start == end:
        return f"{end_year} 年 {int(end_month)} 月"
    if start_year == end_year:
        return f"{start_year} 年 {int(start_month)}–{int(end_month)} 月"
    return f"{start_year} 年 {int(start_month)} 月–{end_year} 年 {int(end_month)} 月"


def _names_money(key: str) -> bool:
    return (any(segment in MONEY_UNIT_SEGMENTS for segment in re.split(r"[_\-\s/]+", key))
            or any(token in MONEY_TOKENS for token in re.split(r"[^a-z0-9]+", key)))


def _known_ratio(key: str) -> bool:
    if key in RATIO_LABELS or key in RATIO_PCT_LABELS or re.search(r"达成率|完成率|比例|率$", key):
        return True
    return bool(re.search(r"毛利率|收缴率|率_", key)) and not _names_money(key)


def column_semantics(name: str, column_type: str | None = None) -> str:
    """What a column's figures are, by its name (businessResults.ts columnSemantics): amount, ratio, ratio_pct,
    ratio_delta or text."""
    key = name.lower()
    if key in RATIO_DELTA_LABELS or key.endswith(("_pp", "_point_delta")):
        return "ratio_delta"
    if key in RATIO_PCT_LABELS or key.endswith("_pct"):
        return "ratio_pct"
    if _known_ratio(key):
        return "ratio"
    if (key in AMOUNT_LABELS or AMOUNT_NAME.search(key) or AMOUNT_WORD.search(key)
            or any(segment in MONEY_UNIT_SEGMENTS for segment in re.split(r"[_\-\s/]+", key))):
        return "amount"
    if NUMERIC_TYPE.match(column_type or ""):
        return "amount"
    return "text"


def column_label(name: str) -> str:
    """A column's name in words (businessResults.ts businessColumnLabel); a name it does not know stays."""
    key = name.lower()
    for table in (AMOUNT_LABELS, RATIO_LABELS, RATIO_PCT_LABELS, TEXT_LABELS):
        if key in table:
            return table[key]
    return name


def business_value(value: Any, semantics: str) -> str:
    """One value by what its column holds (businessResults.ts formatBusinessValue)."""
    if value is None or value == "":
        return "—"
    if semantics == "ratio":
        return f"{decimal_to_fixed(value, 2, 100)}%"
    if semantics == "ratio_pct":
        return f"{decimal_to_fixed(value, 2)}%"
    if semantics == "ratio_delta":
        return f"{decimal_to_fixed(value, 2, 100)} 个百分点"
    if semantics == "amount":
        return decimal_to_fixed(value, 2)
    if isinstance(value, (dict, list)):
        return _json(value)
    text = js_text(value)
    return RESULT_METRIC_LABELS.get(text, text)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def unit_kind(unit: Any) -> str | None:
    """How a unit reads a value: points, decimal, percent, unmarked, or None for an amount unit or none."""
    text = ("" if unit is None else js_text(unit)).strip().lower()
    if text in POINT_UNITS:
        return "points"
    if text in FRACTION_UNITS:
        return "decimal"
    if text in PERCENT_UNITS:
        return "percent"
    if text in UNMARKED_UNITS:
        return "unmarked"
    return None


def row_unit(row: dict) -> Any:
    """The row's unit: the first of unit, 单位 that is neither null nor empty."""
    return next((row[key] for key in ("unit", "单位") if row.get(key) not in (None, "")), None)


def cell_text(value: Any, name: str, row: dict, semantics: str | None = None) -> str:
    """One cell as the result area writes it (businessResults.ts formatBusinessCell, for a figure's own column)."""
    semantics = semantics or column_semantics(name)
    if name.lower() == "period" or name == "期间":
        return "—" if value is None or value == "" else format_period(value)
    if name == "value":
        kind = unit_kind(row_unit(row))
        if kind == "points":
            return "—" if value is None or value == "" else f"{decimal_to_fixed(value, 2)} 个百分点"
        if kind == "decimal":
            return business_value(value, "ratio")
        if kind == "percent":
            return business_value(value, "ratio_pct")
        if kind == "unmarked":
            if value is None or value == "":
                return "—"
            return f"{_json(value) if isinstance(value, (dict, list)) else js_text(value)}（未标单位）"
        return business_value(value, semantics)
    return business_value(value, semantics)


def split_display(text: str) -> tuple[str, str]:
    """A figure a run wrote with its unit (82.12%, -3.22 个百分点) as the figure and the unit (dashboardModel.ts)."""
    found = re.fullmatch(r"\s*([+-]?[0-9,]*\.?[0-9]+)\s*(.*)", text)
    if not found:
        return text, ""
    return found[1].removeprefix("+"), found[2].strip()


def scenario_words(label: str, side: str) -> str:
    """One side of a comparison in words (RunPanel.tsx scenarioWords)."""
    if re.fullmatch(r"actual", label, re.IGNORECASE) or label == "实际":
        return "实际"
    estimate = bool(re.search(r"estimat|估算|推算|预估", label, re.IGNORECASE))
    if re.search(r"budget|预算", label, re.IGNORECASE):
        return "预算（估算）" if estimate else "预算"
    if re.search(r"forecast|预测|rolling|滚动", label, re.IGNORECASE):
        return "预测"
    if label == "baseline":
        return "对照"
    return label if side == "actual" else f"对照（{label}）"
