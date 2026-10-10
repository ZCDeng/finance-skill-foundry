"""倒推 and 敏感性: what a goal or sensitivity card (foundry/dashboards.py) says of one entity's 本期 lines.

The board works these out in the renderer (app/src/views/analysis/dashboardWhatIf.ts) and the conversation here
(foundry/answer_cards.py), so both are held to app/tests/fixtures/what-if-cases.json: the same run reads the same on
the board and under the assistant's answer. Arithmetic on figures the run computed is done as the renderer does it, in
binary floating point and in the same order, and written at eight places before it is rounded for show (toFixed(8)).

Every figure here past the run's own lines is a what-if, which is why such a card is never accepted.
"""
from __future__ import annotations

import math
import re
from typing import Any

from foundry.figure_text import decimal_to_fixed, js_text

FLAG = "情景，不是实际数"
# The rows and columns of a sensitivity grid a card shows, around where the entity stands.
WINDOW = 5
MANUAL_BUDGET = re.compile(r"含手填数：[^；]*全年收入预算")


def _number(value: Any) -> float | None:
    """Number(text) for a finite figure the run wrote; None for anything else."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def fixed(value: float, places: int) -> str:
    return decimal_to_fixed(f"{value:.8f}", places)


def signed(value: float, places: int) -> str:
    return f"{'+' if value > 0 else ''}{fixed(value, places)}"


def _with_unit(text: str, unit: str) -> str:
    return f"{text} {unit}" if unit else text


def lines_of(rows: list[dict], entity: str) -> dict[str, dict]:
    """The entity's 本期 lines by metric key, each with a figure."""
    out: dict[str, dict] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("entity") == entity and row.get("scenario") == "本期" \
                and _number(row.get("value")) is not None:
            out.setdefault(row.get("metric_key"), row)
    return out


def goal_collection(lines: dict[str, dict], entity: str, target: str | None, params: dict) -> dict:
    """What reaching ``target`` (or the line itself) takes from the collection rate the run was taken at."""
    break_even, gap = lines["break_even_collection"], lines["collection_gap"]
    line = float(break_even["value"])
    current = line + float(gap["value"])
    goal = float(target[:-1]) if target else line
    points = goal - current
    at = goal - line
    revenue_row = lines.get("ttm_revenue")
    revenue = _number(revenue_row["value"]) if revenue_row else None
    vat = _number(params.get("vat_factor")) if isinstance(params, dict) else None
    vat = 1.06 if vat is None else vat
    unit = (revenue_row or {}).get("unit") or ""
    money = None if revenue is None else (points / 100) * revenue * vat
    # A rate that reads as the goal to the hundredth has reached it: neither short of it nor past it.
    met = fixed(abs(points), 2) == "0.00"
    if met:
        part = "已达到目标" if target else "正好在生死线上"
        value = f"{fixed(goal, 2)}%"
    elif money is not None:
        part = "一年还要多收" if points > 0 else "一年已比目标多收"
        value = _with_unit(fixed(abs(money), 0), unit)
    else:
        part = "收缴率还要提高" if points > 0 else "收缴率已高出目标"
        value = f"{fixed(abs(points), 2)} 个百分点"
    # Without a target the goal is the line itself, which the card shows among the run's lines.
    beside = [["目标收缴率", f"{fixed(goal, 2)}%"]] if target else []
    beside.append(["这次计算的收缴率", f"{fixed(current, 2)}%"])
    if money is not None and not met:
        beside.append(["还差" if points > 0 else "已高出", f"{fixed(abs(points), 2)} 个百分点"])
    if target:
        beside.append(["到目标时距生死线", f"{signed(at, 2)} 个百分点"])
    caption = ("以上几项读自这次计算，只有目标收缴率是假设。" if target else "以上几项读自这次计算，目标就是生死线收缴率。") + (
        f"一年回款差 = 收缴率差 × 近 12 个月营业收入 × {js_text(vat)}（回款含增值税），是估算。" if money is not None
        else "这次计算没有近 12 个月营业收入，算不出金额。")
    basis = [row for row in (break_even, gap, revenue_row) if row]
    return {"goal": "collection", "subject": f"{entity} · " + (f"收缴率到 {fixed(goal, 2)}%" if target else "收缴率回到生死线"),
            "part": part, "value": value, "beside": beside, "caption": caption, "basis": basis}


def goal_budget(lines: dict[str, dict], entity: str) -> dict:
    """What the full-year revenue budget still needs from each month left, against the months gone."""
    remaining_row, monthly_row = lines["revenue_budget_remaining"], lines["revenue_budget_monthly"]
    inputs = {**(remaining_row.get("inputs") or {}), **(monthly_row.get("inputs") or {})}
    unit = remaining_row.get("unit") or ""
    remaining, need = float(remaining_row["value"]), float(monthly_row["value"])
    budget, done, months = (_number(inputs.get(name)) for name in ("revenue_budget_full", "revenue", "months_elapsed"))
    manual = bool(MANUAL_BUDGET.search(remaining_row.get("note") or ""))
    # Short by what reads as 0.00 is done to the cent: neither a month's target nor an overshoot.
    short = remaining > 0 and fixed(remaining, 2) != "0.00"
    if short:
        part = f"剩余 {js_text(12 - months) if months is not None else '—'} 个月每月要做到"
        value = monthly_row.get("display_value") or _with_unit(fixed(need, 2), unit)
    elif fixed(abs(remaining), 2) == "0.00":
        part = "全年收入预算正好完成"
        value = _with_unit(decimal_to_fixed(inputs.get("revenue_budget_full"), 2), unit)
    else:
        part = "全年收入预算已完成，超出"
        value = _with_unit(fixed(-remaining, 2), unit)
    beside = [["全年收入预算（手填）" if manual else "全年收入预算", _with_unit(decimal_to_fixed(inputs.get("revenue_budget_full"), 2), unit)],
              ["本年累计", _with_unit(decimal_to_fixed(inputs.get("revenue"), 2), unit)]]
    if budget and done is not None and budget > 0:
        beside.append(["已完成", f"{fixed(done / budget * 100, 2)}%"])
    if short:
        beside.append(["还差", remaining_row.get("display_value") or _with_unit(fixed(remaining, 2), unit)])
    pace = done / months if done is not None and months else None
    if pace is not None:
        beside.append(["已过月份月均", _with_unit(fixed(pace, 2), unit)])
        if short and pace > 0:
            beside.append(["每月要比月均多", f"{signed((need / pace - 1) * 100, 1)}%"])
    caption = ("全年收入预算、本年累计和已过月数读自这次计算" + ("，全年收入预算是手填的" if manual else "")
               + "。每月要做到 = 还差 ÷ 剩余月数，是倒推，不是预测。")
    return {"goal": "budget", "subject": f"{entity} · 全年收入预算", "part": part, "value": value, "beside": beside,
            "caption": caption, "basis": [remaining_row, monthly_row]}


def _place(value: Any, candidates: list) -> tuple[int, bool]:
    """The candidate nearest ``value``, and whether ``value`` lies on the grid (within half a step of its ends)."""
    target = _number(value)
    values = [float(candidate) for candidate in candidates]
    if target is None:
        return len(values) // 2, False
    best = min(range(len(values)), key=lambda index: abs(values[index] - target))
    half = abs(values[1] - values[0]) / 2
    return best, min(values) - half <= target <= max(values) + half


def _window(index: int, size: int) -> range:
    start = min(max(index - WINDOW // 2, 0), max(size - WINDOW, 0))
    return range(start, min(start + WINDOW, size))


def sensitivity(grid: dict, gap: dict) -> dict:
    """The part of the entity's grid around where it stands, cells toned as the result page tones them."""
    margins, rates, cells = grid["gross_margins"], grid["collection_rates"], grid["cells"]
    current = grid.get("current") or {}
    row, row_on = _place(current.get("gross_margin"), margins)
    column, column_on = _place(current.get("collection_rate"), rates)
    edge = _number(grid.get("edge_below"))
    rows, columns = _window(row, len(margins)), _window(column, len(rates))

    def tone(cell: Any) -> str:
        value = float(cell)
        return "loss" if value < 0 else "edge" if edge is not None and value < edge else "gain"

    on = row_on and column_on
    cropped = len(rows) < len(margins) or len(columns) < len(rates)
    caption = (f"{grid.get('formula') or ''}。负数表示每收 100 元要倒贴的现金。"
               + ("框出的格最接近现在的位置。" if on else "现在的位置不在表内。") + ("完整的表在结果页。" if cropped else ""))
    return {
        "subject": f"{grid['entity']} · 期间费用率 {decimal_to_fixed(grid.get('expense_ratio'), 2, 100)}%",
        "corner": "毛利率 \\ 收缴率",
        "columns": [f"{decimal_to_fixed(rates[index], 1, 100)}%" for index in columns],
        "rows": [{"label": f"{decimal_to_fixed(margins[r], 0, 100)}%",
                  "cells": [{"text": decimal_to_fixed(cells[r][c], 1, 100), "tone": tone(cells[r][c]),
                             "current": on and r == row and c == column} for c in columns]} for r in rows],
        "caption": caption,
        "basis": [gap],
    }
