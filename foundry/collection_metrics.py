"""Collection and cash-health metrics over a month-close pack's own cells.

A service business pays its staff, subcontractors and utilities in cash every month but
only collects part of what it bills, so whether a unit is earning cash turns on its
collection rate as much as on its margin. These metrics put that into numbers: the
break-even collection rate (1 - gross margin + expense ratio), how far the actual rate
sits from it, days of receivables, the collection rate implied by the receivables
movement, how much cash the revenue brought in, and how much of gross profit impairment
ate. The formulas are general; the defaults (a 6% VAT factor, the thresholds) follow
property management, where they were first worked out, and every one is a parameter.

Every value is read from a named cell of a confirmed table snapshot, and a metric whose
inputs are not all there is skipped and listed, never guessed. Results that rest on an
estimate (trailing-twelve-month revenue rebuilt from year-to-date figures, the implied
collection rate) say so on the row.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from foundry.display_numbers import display_amount, display_percent
from foundry.errors import FoundryError

DOMAIN = "foundry.finance.collection_health.v1"

DEFAULT_PARAMS: dict[str, str] = {
    # Cash received includes output VAT; revenue does not.
    "vat_factor": "1.06",
    "days_per_year": "365",
    # An implied collection rate outside this range is distorted by acquisitions,
    # disposals or reclassification and is not read.
    "implied_collection_min": "0.3",
    "implied_collection_max": "1.3",
    # Distance from the break-even collection rate, in fractions (0.03 = 3pp).
    "gap_yellow_below": "0.03",
    "gap_severe_below": "-0.05",
    "dso_yellow_above": "120",
    "dso_red_above": "180",
    "dso_rise_days": "15",
    "impairment_yellow_above": "0.15",
    "impairment_red_above": "0.30",
    "implied_gap_flag": "0.03",
    "cash_ratio_drop_yellow": "0.03",
    "cash_ratio_drop_red": "0.05",
    "buildup_rise_yellow": "0.02",
    "buildup_rise_red": "0.05",
    # A latest estimate this far from the seasonal one (either way) is worth a second look.
    "le_gap_flag": "0.10",
    # Last year booked less than this share of its impairment by the same point: the rest comes late.
    "impairment_progress_flag": "0.5",
    # Last year's same-period share of its full year below this makes the pace meaningless.
    "seasonal_share_min": "0.1",
    "renewal_exposure_yellow": "0.15",
    "renewal_exposure_red": "0.25",
    # Risk radar: score bands and the signals that are not other metrics' lights.
    "risk_red_at": "6",
    "risk_orange_at": "4",
    "risk_yellow_at": "2",
    "risk_revenue_decline": "0.05",
    "risk_collection_drop": "0.03",
    "risk_budget_lag": "0.10",
    # Break-even sensitivity grid.
    "matrix_margin_from": "0.10",
    "matrix_margin_to": "0.30",
    "matrix_margin_step": "0.02",
    "matrix_collection_from": "0.75",
    "matrix_collection_to": "1.00",
    "matrix_collection_step": "0.025",
}

INPUT_LABELS: dict[str, str] = {
    "revenue": "营业收入（本期）",
    "revenue_le": "营业收入最新预估（LE）",
    "net_profit": "净利润（本期）",
    "net_profit_py_full": "上年全年净利润",
    "net_profit_le": "净利润最新预估（LE）",
    "impairment_py_full": "上年全年减值损失",
    "months_elapsed": "已过月数",
    "area_begin": "在管面积年初",
    "area_end": "在管面积期末",
    "area_exit": "低效退场面积",
    "area_nonrenewal": "到期未续约面积",
    "contract_revenue": "合同确认收入合计",
    "revenue_at_risk": "12个月内到期及拟退场合同的确认收入",
    "billed_exiting": "拟退场合同账单",
    "collected_exiting": "拟退场合同实收",
    "billed_staying": "在约合同账单",
    "collected_staying": "在约合同实收",
    "headcount": "在岗人数",
    "operating_profit": "营业利润（本期）",
    "revenue_budget_full": "全年收入预算",
    "cost": "营业成本（本期）",
    "gross_profit": "毛利（本期）",
    "period_expense": "期间费用（本期）",
    "gross_margin": "毛利率（套表报数）",
    "expense_ratio": "期间费用率（套表报数）",
    "collection_rate_current": "本年账单收缴率",
    "collection_rate_total": "综合收缴率（含清欠）",
    "revenue_py_full": "上年全年营业收入",
    "revenue_ttm": "近12个月营业收入",
    "ar_end": "应收账款期末",
    "ar_begin": "应收账款年初",
    "contract_assets_end": "合同资产期末",
    "contract_assets_begin": "合同资产年初",
    "impairment": "减值损失（本期）",
    "cash_from_sales": "销售商品、提供劳务收到的现金",
    "ar_gross": "应收账款账面余额",
    "provision": "坏账准备",
    "ar_over_1y": "账龄1年以上余额",
    "related_ar": "关联方应收余额",
    "related_provision": "关联方坏账准备",
    "ar_collected": "本期收回",
    "ar_gross_begin": "应收账款年初余额",
    "ar_new": "本期新增应收",
}
"""Every input a metric may read. A name ending in _py is the same input for the prior-year period."""

COUNT_INPUTS = frozenset({"months_elapsed", "headcount"})
AREA_INPUTS = frozenset({"area_begin", "area_end", "area_exit", "area_nonrenewal"})
"""Counts carry no money unit. months_elapsed has no prior-year form; a prior headcount is still a headcount."""
RATE_INPUTS = frozenset({"collection_rate_current", "collection_rate_total", "gross_margin", "expense_ratio"})

LEVEL_LABELS = {"red": "红", "orange": "橙", "yellow": "黄", "green": "绿", "unknown": "无法判断"}

COLUMNS = [
    "entity",
    "metric_key",
    "metric_label",
    "scenario",
    {"name": "value", "type": "decimal"},
    "unit",
    "display_value",
    "level",
    "level_label",
    "estimate",
    "formula",
    "note",
]


def _dec(value: Any, field: str) -> Decimal:
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        number = value if isinstance(value, Decimal) else Decimal(str(value))
        if not number.is_finite():
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError) as exc:
        raise FoundryError(f"{field} must be a finite decimal") from exc


def resolve_params(raw: Any) -> dict[str, Decimal]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise FoundryError("collection_health params must be an object")
    unknown = sorted(set(raw) - set(DEFAULT_PARAMS))
    if unknown:
        raise FoundryError(f"unknown collection_health params: {', '.join(unknown)}")
    params = {
        key: _dec(raw.get(key, default), f"params.{key}")
        for key, default in DEFAULT_PARAMS.items()
    }
    if params["vat_factor"] <= 0 or params["days_per_year"] <= 0:
        raise FoundryError("params.vat_factor and params.days_per_year must be positive")
    for key in ("matrix_margin_step", "matrix_collection_step"):
        if params[key] <= 0:
            raise FoundryError(f"params.{key} must be positive")
    return params


# ---------------------------------------------------------------- cell resolution


def _rate_limit(key: str) -> Decimal | None:
    """Above this a bare number is taken for a percentage written without its sign.

    A margin or expense ratio is below one as a fraction, so 1.2 is 1.2%; a collection
    rate can pass 100% when arrears come in, so only a figure past 150% is refused.
    """
    base = key.removesuffix("_py")
    if base in {"gross_margin", "expense_ratio"}:
        return Decimal("1")
    if base in RATE_INPUTS:
        return Decimal("1.5")
    return None


def _parse_cell(value: Any, *, limit: Decimal | None, scale: str | None, where: str) -> Decimal:
    if value is None or (isinstance(value, str) and value.strip() in {"", "-", "—", "--"}):
        raise FoundryError(f"{where} is empty")
    percent = False
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("，", "")
        if text.endswith(("%", "％")):
            percent, text = True, text[:-1].strip()
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        value = text
    number = _dec(value, where)
    if scale not in (None, "percent", "fraction"):
        raise FoundryError(f"{where} scale must be percent or fraction")
    if percent or scale == "percent":
        return number / 100
    if limit is not None and scale is None and abs(number) > limit:
        raise FoundryError(
            f"{where} reads {number}, which looks like a percentage; "
            "set scale to percent (87.32 means 87.32%) or fraction"
        )
    return number


def _input_name(name: Any) -> str:
    if not isinstance(name, str):
        raise FoundryError("collection_health input names must be text")
    base = name[:-3] if name.endswith("_py") else name
    if base not in INPUT_LABELS:
        raise FoundryError(f"unknown collection_health input: {name}")
    if name.endswith("_py") and base == "months_elapsed":
        raise FoundryError(f"{name}: {base} has no prior-year counterpart")
    return name


def resolve_entities(
    inputs: dict,
    rows_by_alias: dict[str, list[dict]],
    units_by_alias: dict[str, Any] | None = None,
) -> list[dict]:
    """Read each entity's named values from the bound snapshots.

    A value is a cell reference {alias, match: {column: text} | source_row, column,
    scale?, unit?} that must find exactly one row, or a bare number or text, which is
    kept as a manual input and said to be one on every metric that reads it.
    """

    units_by_alias = units_by_alias or {}
    raw_entities = inputs.get("entities") or []
    if not isinstance(raw_entities, list):
        raise FoundryError("collection_health entities must be a list")
    raw_entities = [*raw_entities, *_table_entities(inputs.get("entity_tables"), rows_by_alias)]
    if not raw_entities:
        raise FoundryError("collection_health inputs require entities or entity_tables")
    entities = []
    seen = set()
    for index, raw in enumerate(raw_entities):
        if not isinstance(raw, dict):
            raise FoundryError("each collection_health entity must be an object")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise FoundryError(f"collection_health entity {index + 1} requires a name")
        if name in seen:
            raise FoundryError(f"collection_health entity {name} is listed twice")
        seen.add(name)
        refs = raw.get("values")
        if not isinstance(refs, dict) or not refs:
            raise FoundryError(f"collection_health entity {name} requires values")
        values: dict[str, Decimal] = {}
        sources: dict[str, dict] = {}
        manual: set[str] = set()
        units: dict[str, str] = {}
        area_units: dict[str, str | None] = {}
        for key, ref in refs.items():
            key = _input_name(key)
            rate = key.removesuffix("_py") in RATE_INPUTS
            limit = _rate_limit(key)
            where = f"{name}.{key}"
            if not isinstance(ref, dict):
                values[key] = _parse_cell(ref, limit=limit, scale=None, where=where)
                manual.add(key)
                continue
            alias = ref.get("alias")
            if alias not in rows_by_alias:
                raise FoundryError(f"{where} alias {alias} is not bound")
            column = ref.get("column")
            if not isinstance(column, str) or not column:
                raise FoundryError(f"{where} requires a column")
            candidates = rows_by_alias[alias]
            if "sum_where" in ref:
                if "match" in ref or "source_row" in ref:
                    raise FoundryError(f"{where}: sum_where reads many rows; it cannot sit beside match, "
                                       "source_row or an entity_tables column")
                if rate or key.removesuffix("_py") == "months_elapsed":
                    raise FoundryError(f"{where}: only an amount or a headcount is summed over rows")
                total, cells, row_units = _sum_rows(candidates, ref, column, where)
                values[key] = total
                sources[key] = cells
                stated = _unit(ref.get("unit"))
                if len(row_units) > 1 and not stated:
                    raise FoundryError(f"{where} sums rows in {', '.join(sorted(row_units))}; one unit at a time")
                row_unit = stated or (next(iter(row_units)) if row_units else None)
                if key.removesuffix("_py") in AREA_INPUTS:
                    area_units[key] = row_unit
                elif key.removesuffix("_py") not in COUNT_INPUTS:
                    units[key] = row_unit or _unit(units_by_alias.get(alias))
                continue
            if "source_row" in ref:
                if "match" in ref:
                    raise FoundryError(f"{where} gives both match and source_row; give one")
                try:
                    source_row = int(ref["source_row"])
                except (TypeError, ValueError) as exc:
                    raise FoundryError(f"{where} source_row must be a row number") from exc
                candidates = [r for r in candidates if r["source"].get("source_row") == source_row]
                wanted = f"source_row {source_row}"
            else:
                match = ref.get("match")
                if not isinstance(match, dict) or not match:
                    raise FoundryError(f"{where} requires match or source_row")
                candidates = [
                    r
                    for r in candidates
                    if all(str(r.get(col) if r.get(col) is not None else "").strip() == str(text).strip()
                           for col, text in match.items())
                ]
                wanted = ", ".join(f"{col}={text}" for col, text in match.items())
            if len(candidates) != 1:
                raise FoundryError(
                    f"{where} must match exactly one row of {alias} ({wanted}); found {len(candidates)}"
                )
            row = candidates[0]
            if column not in row:
                raise FoundryError(f"{where} column {column} is not in {alias}")
            values[key] = _parse_cell(row[column], limit=limit, scale=ref.get("scale"), where=where)
            sources[key] = [{**row["source"], "column": column}]
            if key.removesuffix("_py") in AREA_INPUTS:
                area_units[key] = _unit(ref.get("unit") or row.get("unit"))
            elif not rate and key.removesuffix("_py") not in COUNT_INPUTS:
                unit = ref.get("unit") or row.get("unit") or units_by_alias.get(alias)
                units[key] = _unit(unit)
        for count in ("headcount", "headcount_py"):
            if count in values and values[count] <= 0:
                raise FoundryError(f"{name}.{count} must be positive")
        months = values.get("months_elapsed")
        if months is not None and not (1 <= months <= 12 and months == months.to_integral_value()):
            raise FoundryError(f"{name}.months_elapsed must be a whole number of months from 1 to 12")
        distinct = sorted({unit for unit in units.values() if unit})
        if len(distinct) > 1:
            raise FoundryError(
                f"{name} mixes amount units {', '.join(distinct)}; ratios across units are wrong"
            )
        areas = sorted({unit for unit in area_units.values() if unit})
        if len(areas) > 1:
            raise FoundryError(f"{name} mixes area units {', '.join(areas)}")
        if areas and any(not unit for unit in area_units.values()):
            raise FoundryError(f"{name} reads an area without a unit beside areas in {areas[0]}")
        unknown = sorted(key for key, unit in units.items() if not unit)
        if distinct and unknown:
            raise FoundryError(
                f"{name} reads {', '.join(unknown)} without a unit beside amounts in {distinct[0]}; "
                "state the unit on the cell reference or in the table scope"
            )
        entities.append(
            {
                "name": name,
                "values": values,
                "sources": sources,
                "manual": manual,
                "unit": distinct[0] if distinct else None,
                "area_unit": areas[0] if areas else None,
                # A row of a detail table, or a unit named on its own (often the group total over those rows).
                "origin": raw.get("origin") or "declared",
                "sensitivity": bool(raw.get("sensitivity")),
            }
        )
    return entities


UNIT_ALIASES = {"万": "万元", "亿": "亿元", "千": "千元"}


def _unit(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return UNIT_ALIASES.get(text, text)


def _same_text(cell: Any, wanted: set[str]) -> bool:
    """A filter cell matches a listed text as written, or as the same number (1.0 is 1)."""
    text = str(cell if cell is not None else "").strip()
    if text in wanted:
        return True
    try:
        number = Decimal(text)
    except InvalidOperation:
        return False
    for item in wanted:
        try:
            if number.is_finite() and Decimal(item) == number:
                return True
        except InvalidOperation:
            continue
    return False


def _sum_rows(rows: list[dict], ref: dict, column: str, where: str) -> tuple[Decimal, list[dict], set[str]]:
    """Σ column over the rows whose columns hold one of the listed texts (a contract ledger filtered by status).

    require_columns skips rows where any of those columns is blank, so a numerator and denominator summed apart
    read the same rows.
    """
    conditions = ref["sum_where"]
    if not isinstance(conditions, dict) or not conditions:
        raise FoundryError(f"{where} sum_where must name at least one column {{column: text or [texts]}}")
    wanted = {col: {str(item).strip() for item in (texts if isinstance(texts, list) else [texts])}
              for col, texts in conditions.items()}
    if any(not texts for texts in wanted.values()):
        raise FoundryError(f"{where} sum_where lists no text for a column")
    required = list(ref.get("require_columns") or [])
    present = {name for row in rows for name in row}
    for name in [column, *wanted, *required]:
        if name not in present:
            raise FoundryError(f"{where} column {name} is not in the table")
    total, cells, units, matched, blank = Decimal(0), [], set(), 0, 0
    for row in rows:
        if not all(_same_text(row.get(col), texts) for col, texts in wanted.items()):
            continue
        matched += 1
        # A collection rate sums 实收 and 账单 apart: both sides must skip the rows where either is blank.
        if _blank(row.get(column)) or any(_blank(row.get(other)) for other in required):
            blank += 1
            continue
        total += _parse_cell(row[column], limit=None, scale=ref.get("scale"), where=where)
        cells.append({**row["source"], "column": column})
        if _unit(row.get("unit")):
            units.add(_unit(row.get("unit")))
    if not cells:
        raise FoundryError(f"{where} found no figure: {matched} rows matched {conditions}, {blank} of them blank")
    return total, cells, units


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() in {"", "-", "—", "--"})


def _table_entities(tables: Any, rows_by_alias: dict[str, list[dict]]) -> list[dict]:
    """One entity per row of a detail table (a city-company sheet), named by one of its columns.

    Rows with no name are section headings and are passed over; a blank cell leaves that
    input out, so only the metrics that need it are skipped.
    """
    if tables is None:
        return []
    if not isinstance(tables, list):
        raise FoundryError("collection_health entity_tables must be a list")
    out = []
    for table in tables:
        if not isinstance(table, dict):
            raise FoundryError("each collection_health entity table must be an object")
        alias, name_column, columns = table.get("alias"), table.get("name_column"), table.get("columns")
        if alias not in rows_by_alias:
            raise FoundryError(f"entity table alias {alias} is not bound")
        if not isinstance(name_column, str) or not isinstance(columns, dict) or not columns:
            raise FoundryError("an entity table requires name_column and columns {input: column}")
        exclude = {str(name).strip() for name in table.get("exclude") or []}
        prefix = str(table.get("name_prefix") or "")
        rows = rows_by_alias[alias]
        present = {column for row in rows for column in row}
        specs = {key: column if isinstance(column, dict) else {"column": column} for key, column in columns.items()}
        for key, spec in [("name_column", {"column": name_column}), *specs.items()]:
            if spec.get("column") not in present:
                raise FoundryError(f"entity table {alias}: column {spec.get('column')} for {key} is not in the table")
        for key, spec in specs.items():
            # A percentage column written without its sign is caught on any row, not only past the limit.
            limit = _rate_limit(_input_name(key))
            if limit is None or spec.get("scale") is not None:
                continue
            for row in rows:
                cell = row.get(spec["column"])
                if not _blank(cell) and not (isinstance(cell, str) and cell.strip().endswith(("%", "％"))):
                    try:
                        number = Decimal(str(cell).replace(",", ""))
                    except InvalidOperation:
                        continue
                    if number.is_finite() and abs(number) > limit:
                        raise FoundryError(
                            f"entity table {alias}: {spec['column']} reads {number} on a row, which looks "
                            "like a percentage; set scale to percent or fraction for the column"
                        )
        for row in rows:
            name = row.get(name_column)
            if _blank(name) or str(name).strip() in exclude:
                continue
            values = {}
            for key, spec in specs.items():
                if _blank(row.get(spec.get("column"))):
                    continue
                values[key] = {**spec, "alias": alias, "source_row": row["source"]["source_row"]}
            if values:
                out.append({"name": prefix + str(name).strip(), "values": values, "origin": "table"})
    return out


# ---------------------------------------------------------------- metric definitions


def _gross_profit(v: dict) -> tuple[Decimal, list[str]] | None:
    if "gross_profit" in v:
        return v["gross_profit"], ["gross_profit"]
    if "revenue" in v and "cost" in v:
        return v["revenue"] - v["cost"], ["revenue", "cost"]
    return None


def _need(v: dict, *names: str) -> bool:
    return all(name in v for name in names)


def _div(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return None if denominator == 0 else numerator / denominator


Computed = tuple[Decimal, list[str], bool] | None
"""(value, inputs read, estimate) or None when an input is missing."""


def _m_gross_margin(v, p) -> Computed:
    # A pack that reports the ratio itself (a KPI dashboard) is read as reported.
    if "gross_margin" in v:
        return v["gross_margin"], ["gross_margin"], False
    gp = _gross_profit(v)
    if gp is None or "revenue" not in v:
        return None
    value = _div(gp[0], v["revenue"])
    return None if value is None else (value, sorted({*gp[1], "revenue"}), False)


def _m_expense_ratio(v, p) -> Computed:
    if "expense_ratio" in v:
        return v["expense_ratio"], ["expense_ratio"], False
    if not _need(v, "period_expense", "revenue"):
        return None
    value = _div(v["period_expense"], v["revenue"])
    return None if value is None else (value, ["period_expense", "revenue"], False)


def _m_break_even(v, p) -> Computed:
    gm, er = _m_gross_margin(v, p), _m_expense_ratio(v, p)
    if gm is None or er is None:
        return None
    return 1 - gm[0] + er[0], sorted({*gm[1], *er[1]}), False


def _with_rate(rate_key: str) -> Callable[[dict, dict], Computed]:
    def compute(v, p) -> Computed:
        be = _m_break_even(v, p)
        if be is None or rate_key not in v:
            return None
        return v[rate_key] - be[0], sorted({*be[1], rate_key}), False

    return compute


def _m_ttm_revenue(v, p) -> Computed:
    if "revenue_ttm" in v:
        return v["revenue_ttm"], ["revenue_ttm"], False
    if not _need(v, "revenue_py_full", "revenue_py", "revenue"):
        return None
    return (
        v["revenue_py_full"] - v["revenue_py"] + v["revenue"],
        ["revenue_py_full", "revenue_py", "revenue"],
        True,
    )


def _receivables(v: dict, when: str) -> tuple[Decimal, list[str]] | None:
    ar = f"ar_{when}"
    if ar not in v:
        return None
    ca = f"contract_assets_{when}"
    if _with_contract_assets(v) and ca in v:
        return v[ar] + v[ca], [ar, ca]
    return v[ar], [ar]


def _with_contract_assets(v: dict) -> bool:
    """Contract assets count only when both ends have them, or there is no year start to compare with.

    Adding them at year end but not at year start would count the whole contract-asset
    balance as a year's increase in receivables.
    """
    return "contract_assets_end" in v and ("contract_assets_begin" in v or "ar_begin" not in v)


def _m_dso(v, p) -> Computed:
    ar, ttm = _receivables(v, "end"), _m_ttm_revenue(v, p)
    if ar is None or ttm is None:
        return None
    value = _div(ar[0] * p["days_per_year"], ttm[0])
    return None if value is None else (value, sorted({*ar[1], *ttm[1]}), ttm[2])


def _m_dso_begin(v, p) -> Computed:
    ar = _receivables(v, "begin")
    if ar is None or "revenue_py_full" not in v:
        return None
    value = _div(ar[0] * p["days_per_year"], v["revenue_py_full"])
    return None if value is None else (value, sorted({*ar[1], "revenue_py_full"}), False)


def _ar_change(v: dict) -> tuple[Decimal, list[str]] | None:
    end, begin = _receivables(v, "end"), _receivables(v, "begin")
    if end is None or begin is None:
        return None
    return end[0] - begin[0], sorted({*end[1], *begin[1]})


def _m_buildup(v, p) -> Computed:
    change = _ar_change(v)
    if change is None or "revenue" not in v:
        return None
    value = _div(change[0], v["revenue"])
    return None if value is None else (value, sorted({*change[1], "revenue"}), False)


def _m_implied_collection(v, p) -> Computed:
    change = _ar_change(v)
    if change is None or not _need(v, "impairment", "revenue"):
        return None
    value = _div(change[0] + abs(v["impairment"]), v["revenue"] * p["vat_factor"])
    if value is None:
        return None
    return 1 - value, sorted({*change[1], "impairment", "revenue"}), True


def _m_implied_vs_reported(v, p) -> Computed:
    implied = _m_implied_collection(v, p)
    if implied is None or "collection_rate_total" not in v:
        return None
    return implied[0] - v["collection_rate_total"], sorted({*implied[1], "collection_rate_total"}), True


def _m_rollforward_collection(v, p) -> Computed:
    if not _need(v, "ar_collected", "ar_gross_begin", "ar_new"):
        return None
    value = _div(v["ar_collected"], v["ar_gross_begin"] + v["ar_new"])
    return None if value is None else (value, ["ar_collected", "ar_gross_begin", "ar_new"], False)


def _m_cash_collection(v, p) -> Computed:
    if not _need(v, "cash_from_sales", "revenue"):
        return None
    value = _div(v["cash_from_sales"], v["revenue"] * p["vat_factor"])
    return None if value is None else (value, ["cash_from_sales", "revenue"], False)


def _m_impairment_to_gp(v, p) -> Computed:
    gp = _gross_profit(v)
    if gp is None or "impairment" not in v:
        return None
    value = _div(abs(v["impairment"]), gp[0])
    return None if value is None else (value, sorted({*gp[1], "impairment"}), False)


def _share(numerator: str, denominator: str) -> Callable[[dict, dict], Computed]:
    def compute(v, p) -> Computed:
        if not _need(v, numerator, denominator):
            return None
        value = _div(v[numerator], v[denominator])
        return None if value is None else (value, [numerator, denominator], False)

    return compute


def _seasonal(base: str) -> Callable[[dict, dict], Computed]:
    """Year to date divided by the share of last year's full year booked by the same point."""
    def compute(v, p) -> Computed:
        names = (base, f"{base}_py", f"{base}_py_full")
        if not _need(v, *names) or v[f"{base}_py_full"] == 0:
            return None
        share = v[f"{base}_py"] / v[f"{base}_py_full"]
        value = _div(v[base], share)
        return None if value is None else (value, list(names), True)

    return compute


def _linear(base: str) -> Callable[[dict, dict], Computed]:
    def compute(v, p) -> Computed:
        if not _need(v, base, "months_elapsed"):
            return None
        return v[base] * 12 / v["months_elapsed"], [base, "months_elapsed"], True

    return compute


def _le_gap(base: str) -> Callable[[dict, dict], Computed]:
    def compute(v, p) -> Computed:
        seasonal = _seasonal(base)(v, p)
        if seasonal is None or f"{base}_le" not in v or seasonal[0] == 0:
            return None
        return (v[f"{base}_le"] - seasonal[0]) / abs(seasonal[0]), sorted({*seasonal[1], f"{base}_le"}), True

    return compute


def _m_impairment_progress(v, p) -> Computed:
    if not _need(v, "impairment_py", "impairment_py_full") or v["impairment_py_full"] == 0:
        return None
    return abs(v["impairment_py"]) / abs(v["impairment_py_full"]), ["impairment_py", "impairment_py_full"], False


def _m_area_growth(v, p) -> Computed:
    if not _need(v, "area_begin", "area_end"):
        return None
    value = _div(v["area_end"] - v["area_begin"], v["area_begin"])
    return None if value is None else (value, ["area_begin", "area_end"], False)


def _m_area_exit(v, p) -> Computed:
    parts = [name for name in ("area_exit", "area_nonrenewal") if name in v]
    if not parts or "area_begin" not in v:
        return None
    value = _div(sum((v[name] for name in parts), Decimal(0)), v["area_begin"])
    return None if value is None else (value, sorted({*parts, "area_begin"}), False)


def _m_exiting_gap(v, p) -> Computed:
    names = ("collected_exiting", "billed_exiting", "collected_staying", "billed_staying")
    if not _need(v, *names) or v["billed_exiting"] == 0 or v["billed_staying"] == 0:
        return None
    return (v["collected_exiting"] / v["billed_exiting"] - v["collected_staying"] / v["billed_staying"],
            list(names), False)


METRICS: list[dict[str, Any]] = [
    {"key": "gross_margin", "label": "毛利率", "kind": "ratio", "fn": _m_gross_margin,
     "formula": "毛利 ÷ 营业收入"},
    {"key": "expense_ratio", "label": "期间费用率", "kind": "ratio", "fn": _m_expense_ratio,
     "formula": "期间费用 ÷ 营业收入"},
    {"key": "break_even_collection", "label": "生死线收缴率", "kind": "ratio", "fn": _m_break_even,
     "formula": "1 − 毛利率 + 期间费用率"},
    {"key": "collection_gap", "label": "距生死线（本年账单收缴率）", "kind": "pp",
     "fn": _with_rate("collection_rate_current"),
     "formula": "本年账单收缴率 − 生死线收缴率，等于现金经营利润率"},
    {"key": "collection_gap_total", "label": "距生死线（综合收缴率，含清欠）", "kind": "pp",
     "fn": _with_rate("collection_rate_total"),
     "formula": "综合收缴率 − 生死线收缴率"},
    {"key": "ttm_revenue", "label": "近12个月营业收入", "kind": "amount", "fn": _m_ttm_revenue,
     "formula": "上年全年 − 上年同期累计 + 本年累计"},
    {"key": "dso", "label": "应收天数", "kind": "days", "fn": _m_dso, "compare": "begin",
     "formula": "（应收账款 + 合同资产）÷ 近12个月营业收入 × 365"},
    {"key": "ar_buildup", "label": "应收蓄水率", "kind": "ratio", "fn": _m_buildup,
     "formula": "（期末应收 − 年初应收）÷ 本期营业收入，应收含合同资产"},
    {"key": "implied_collection", "label": "反推回款率", "kind": "ratio", "fn": _m_implied_collection,
     "formula": "1 − （应收增加额 + 本期减值）÷（本期营业收入 × 税率因子），减值按绝对值计"},
    {"key": "implied_vs_reported", "label": "反推回款率与综合收缴率之差", "kind": "pp",
     "fn": _m_implied_vs_reported, "formula": "反推回款率 − 综合收缴率"},
    {"key": "rollforward_collection", "label": "滚动回款率", "kind": "ratio", "fn": _m_rollforward_collection,
     "formula": "本期收回 ÷（年初余额 + 本期新增）"},
    {"key": "cash_collection_ratio", "label": "现金回收比", "kind": "ratio", "fn": _m_cash_collection,
     "formula": "销售商品、提供劳务收到的现金 ÷（营业收入 × 税率因子）"},
    {"key": "impairment_to_gross_profit", "label": "减值占毛利", "kind": "ratio", "fn": _m_impairment_to_gp,
     "formula": "减值损失（绝对值）÷ 毛利"},
    {"key": "provision_ratio", "label": "应收拨备率", "kind": "ratio", "fn": _share("provision", "ar_gross"),
     "formula": "坏账准备 ÷ 应收账款账面余额"},
    {"key": "aging_over_1y_share", "label": "账龄1年以上占比", "kind": "ratio",
     "fn": _share("ar_over_1y", "ar_gross"), "formula": "账龄1年以上余额 ÷ 应收账款账面余额"},
    {"key": "related_party_share", "label": "关联方应收占比", "kind": "ratio",
     "fn": _share("related_ar", "ar_gross"), "formula": "关联方应收余额 ÷ 应收账款账面余额"},
    {"key": "related_party_provision_ratio", "label": "关联方拨备率", "kind": "ratio",
     "fn": _share("related_provision", "related_ar"), "formula": "关联方坏账准备 ÷ 关联方应收余额"},
    {"key": "revenue_full_year_seasonal", "label": "全年营业收入（按去年节奏）", "kind": "amount",
     "fn": _seasonal("revenue"), "formula": "本年累计 ÷（上年同期累计 ÷ 上年全年）"},
    {"key": "revenue_full_year_linear", "label": "全年营业收入（线性外推，仅对照）", "kind": "amount",
     "fn": _linear("revenue"), "formula": "本年累计 × 12 ÷ 已过月数"},
    {"key": "revenue_le_gap", "label": "收入 LE 与按去年节奏之差", "kind": "ratio", "fn": _le_gap("revenue"),
     "formula": "（LE − 按去年节奏的全年数）÷ 按去年节奏的全年数"},
    {"key": "net_profit_full_year_seasonal", "label": "全年净利润（按去年节奏）", "kind": "amount",
     "fn": _seasonal("net_profit"), "formula": "本年累计 ÷（上年同期累计 ÷ 上年全年）"},
    {"key": "net_profit_full_year_linear", "label": "全年净利润（线性外推，仅对照）", "kind": "amount",
     "fn": _linear("net_profit"), "formula": "本年累计 × 12 ÷ 已过月数"},
    {"key": "net_profit_le_gap", "label": "净利润 LE 与按去年节奏之差", "kind": "ratio", "fn": _le_gap("net_profit"),
     "formula": "（LE − 按去年节奏的全年数）÷ 按去年节奏的全年数"},
    {"key": "impairment_progress_py", "label": "去年同期减值占全年比重", "kind": "ratio",
     "fn": _m_impairment_progress, "formula": "上年同期减值 ÷ 上年全年减值（均按绝对值）"},
    {"key": "area_net_growth", "label": "在管面积净增率", "kind": "ratio", "fn": _m_area_growth,
     "formula": "（期末 − 年初）÷ 年初"},
    {"key": "area_exit_share", "label": "退场与未续约面积占年初", "kind": "ratio", "fn": _m_area_exit,
     "formula": "（低效退场 + 到期未续约）÷ 年初面积"},
    {"key": "renewal_exposure", "label": "续约风险敞口", "kind": "ratio", "fn": _share("revenue_at_risk", "contract_revenue"),
     "formula": "12个月内到期及拟退场合同的确认收入 ÷ 合同确认收入合计"},
    {"key": "exiting_collection_rate", "label": "拟退场合同收缴率", "kind": "ratio",
     "fn": _share("collected_exiting", "billed_exiting"), "formula": "拟退场合同实收 ÷ 账单"},
    {"key": "staying_collection_rate", "label": "在约合同收缴率", "kind": "ratio",
     "fn": _share("collected_staying", "billed_staying"), "formula": "在约合同实收 ÷ 账单"},
    {"key": "exiting_collection_gap", "label": "拟退场比在约合同收缴率", "kind": "pp", "fn": _m_exiting_gap,
     "formula": "拟退场合同收缴率 − 在约合同收缴率"},
    {"key": "revenue_per_head", "label": "人均创收", "kind": "amount", "fn": _share("revenue", "headcount"),
     "formula": "营业收入 ÷ 在岗人数", "unit": lambda entity: f"{entity['unit']}/人" if entity.get("unit") else "/人"},
    {"key": "area_per_head", "label": "人均在管面积", "kind": "amount", "fn": _share("area_end", "headcount"),
     "formula": "期末在管面积 ÷ 在岗人数",
     "unit": lambda entity: f"{entity['area_unit']}/人" if entity.get("area_unit") else "/人"},
]
METRIC_KEYS = tuple(metric["key"] for metric in METRICS)

# Which inputs a metric could read, for saying why it was skipped.
_METRIC_INPUTS = {
    "gross_margin": ("gross_margin|revenue+cost|revenue+gross_profit",),
    "expense_ratio": ("expense_ratio|period_expense+revenue",),
    "break_even_collection": ("gross_margin|revenue+cost|revenue+gross_profit", "expense_ratio|period_expense+revenue"),
    "collection_gap": ("gross_margin|revenue+cost|revenue+gross_profit", "expense_ratio|period_expense+revenue",
                       "collection_rate_current"),
    "collection_gap_total": ("gross_margin|revenue+cost|revenue+gross_profit", "expense_ratio|period_expense+revenue",
                             "collection_rate_total"),
    "ttm_revenue": ("revenue_ttm|revenue_py_full+revenue_py+revenue",),
    "dso": ("ar_end", "revenue_ttm|revenue_py_full+revenue_py+revenue"),
    "ar_buildup": ("ar_end", "ar_begin", "revenue"),
    "implied_collection": ("ar_end", "ar_begin", "impairment", "revenue"),
    "implied_vs_reported": ("ar_end", "ar_begin", "impairment", "revenue", "collection_rate_total"),
    "rollforward_collection": ("ar_collected", "ar_gross_begin", "ar_new"),
    "cash_collection_ratio": ("cash_from_sales", "revenue"),
    "impairment_to_gross_profit": ("impairment", "gross_profit|revenue+cost"),
    "provision_ratio": ("provision", "ar_gross"),
    "aging_over_1y_share": ("ar_over_1y", "ar_gross"),
    "related_party_share": ("related_ar", "ar_gross"),
    "revenue_full_year_seasonal": ("revenue", "revenue_py", "revenue_py_full"),
    "revenue_full_year_linear": ("revenue", "months_elapsed"),
    "revenue_le_gap": ("revenue", "revenue_py", "revenue_py_full", "revenue_le"),
    "net_profit_full_year_seasonal": ("net_profit", "net_profit_py", "net_profit_py_full"),
    "net_profit_full_year_linear": ("net_profit", "months_elapsed"),
    "net_profit_le_gap": ("net_profit", "net_profit_py", "net_profit_py_full", "net_profit_le"),
    "impairment_progress_py": ("impairment_py", "impairment_py_full"),
    "area_net_growth": ("area_begin", "area_end"),
    "area_exit_share": ("area_begin", "area_exit|area_nonrenewal"),
    "renewal_exposure": ("revenue_at_risk", "contract_revenue"),
    "exiting_collection_rate": ("collected_exiting", "billed_exiting"),
    "staying_collection_rate": ("collected_staying", "billed_staying"),
    "exiting_collection_gap": ("collected_exiting", "billed_exiting", "collected_staying", "billed_staying"),
    "revenue_per_head": ("revenue", "headcount"),
    "area_per_head": ("area_end", "headcount"),
    "related_party_provision_ratio": ("related_provision", "related_ar"),
}


# ---------------------------------------------------------------- levels


def _bump(level: str | None) -> str | None:
    return {"green": "yellow", "yellow": "red"}.get(level or "", level)


def _level(key: str, value: Decimal, change: Decimal | None, p: dict) -> tuple[str | None, str]:
    """A screening light and the reason for it. None means the metric carries no threshold."""
    if key in {"revenue_le_gap", "net_profit_le_gap"}:
        if value > p["le_gap_flag"]:
            return "yellow", "LE 比按去年节奏的全年数高，偏乐观"
        if value < -p["le_gap_flag"]:
            return "yellow", "LE 比按去年节奏的全年数低，偏保守"
        return "green", ""
    if key == "impairment_progress_py":
        if value < p["impairment_progress_flag"]:
            return "yellow", "去年减值大半在后几个月确认，今年剩余月份还会有减值"
        return "green", ""
    if key == "renewal_exposure":
        if value > p["renewal_exposure_red"]:
            return "red", f"超过 {_pct(p['renewal_exposure_red'])} 的收入来自快到期或拟退场的合同"
        if value > p["renewal_exposure_yellow"]:
            return "yellow", ""
        return "green", ""
    if key == "exiting_collection_gap" and value < 0:
        return None, "拟退场合同收得比在约合同差，退场多因收缴不足"
    if key in {"revenue_full_year_linear", "net_profit_full_year_linear"}:
        return None, "线性外推只作对照，不进结论"
    if key in {"collection_gap", "collection_gap_total"}:
        if value < p["gap_severe_below"]:
            return "red", "严重低于生死线，每收100元倒贴现金"
        if value < 0:
            return "red", "低于生死线，每收100元倒贴现金"
        if value < p["gap_yellow_below"]:
            return "yellow", "贴近生死线"
        return "green", ""
    if key == "dso":
        level = "red" if value > p["dso_red_above"] else "yellow" if value > p["dso_yellow_above"] else "green"
        if change is not None and change >= p["dso_rise_days"]:
            return _bump(level), f"比年初多 {display_amount(change)} 天"
        return level, ""
    if key == "impairment_to_gross_profit":
        if value > p["impairment_red_above"]:
            return "red", "减值吃掉三成以上毛利"
        if value > p["impairment_yellow_above"]:
            return "yellow", ""
        return "green", ""
    if key == "implied_vs_reported":
        if abs(value) > p["implied_gap_flag"]:
            return "yellow", "收缴率与应收变动对不上，核对口径或收缴率统计"
        return "green", ""
    if key == "cash_collection_ratio" and change is not None:
        if change < -p["cash_ratio_drop_red"]:
            return "red", "现金回收比比上年同期明显下降"
        if change < -p["cash_ratio_drop_yellow"]:
            return "yellow", "现金回收比比上年同期下降"
        return "green", ""
    if key == "ar_buildup" and change is not None:
        if change > p["buildup_rise_red"]:
            return "red", "应收积压比上年同期明显加快"
        if change > p["buildup_rise_yellow"]:
            return "yellow", "应收积压比上年同期加快"
        return "green", ""
    return None, ""


# ---------------------------------------------------------------- evaluation


UNIT_BY_KIND = {"ratio": "%", "pp": "百分点", "days": "天"}
CHANGE_UNIT_BY_KIND = {"ratio": "百分点", "pp": "百分点", "days": "天"}


def _shown(kind: str, value: Decimal) -> Decimal:
    """The value as its row states it: a ratio in percent, a gap in percentage points."""
    return value * 100 if kind in {"ratio", "pp"} else value


def _display(unit: str | None, value: Decimal, *, signed: bool = False) -> str:
    text = display_amount(value)
    if signed and not text.startswith("-") and text != "0.00":
        text = "+" + text
    if unit == "%":
        return f"{text}%"
    if unit == "百分点":
        return f"{text} 个百分点"
    return f"{text} {unit}" if unit else text


def _prior(values: dict[str, Decimal]) -> dict[str, Decimal]:
    return {key[:-3]: value for key, value in values.items() if key.endswith("_py")}


def _judged_out(key: str, values: dict, computed: dict, params: dict) -> str | None:
    """Why a value is not judged although it was computed, or None."""
    if key.endswith("_full_year_seasonal") or key.endswith("_le_gap"):
        base = key.split("_full_year")[0].removesuffix("_le_gap")
        if values.get(f"{base}_py_full", Decimal(1)) <= 0 or values.get(f"{base}_py", Decimal(1)) <= 0:
            return "上年同期或全年不为正，去年节奏没有意义，不作判断"
        if values.get(base, Decimal(1)) <= 0:
            return "本年累计不为正，按去年节奏放大没有意义，不作判断"
        if f"{base}_py" in values and f"{base}_py_full" in values and \
                values[f"{base}_py"] / values[f"{base}_py_full"] < params["seasonal_share_min"]:
            return "上年同期只占全年很小一部分，按去年节奏放大没有意义，不作判断"
    if key == "impairment_progress_py" and values["impairment_py"] * values["impairment_py_full"] < 0:
        return "上年同期减值与全年方向相反（有转回），进度没有意义，不作判断"
    if key == "dso" and computed.get("ttm_revenue", Decimal(1)) <= 0:
        return "近12个月收入不为正，天数没有意义，不作判断"
    if key == "impairment_to_gross_profit":
        gp = _gross_profit(values)
        if gp is not None and gp[0] <= 0:
            return "毛利不为正，占比没有意义，不作判断"
    if key in {"implied_collection", "implied_vs_reported"} and "implied_collection" in computed:
        implied = computed["implied_collection"]
        if not params["implied_collection_min"] <= implied <= params["implied_collection_max"]:
            return "反推回款率超出合理区间，可能受收并购、处置或重分类影响，不作判断"
    return None


def evaluate_entity(entity: dict, params: dict[str, Decimal]) -> tuple[list[dict], list[dict]]:
    """Every metric the entity's inputs support, and a diagnostic per metric they do not.

    Rows are long-form: one row for the period, and when there is something to compare
    with, one for 年初 or 上年同期 and one for the change, each with its own value and unit.
    """
    values = entity["values"]
    prior = _prior(values)
    rows, skipped, computed = [], [], {}
    for metric in METRICS:
        key, kind = metric["key"], metric["kind"]
        result = metric["fn"](values, params)
        if result is None:
            skipped.append({"metric_key": key, "needs": list(_METRIC_INPUTS[key])})
            continue
        value, used, estimate = result
        computed[key] = value
        compare_label = compare = None
        compare_used: list[str] = []
        compare_estimate = False
        if metric.get("compare") == "begin":
            begin = _m_dso_begin(values, params)
            if begin is not None:
                compare_label, compare, compare_used = "年初", begin[0], begin[1]
        elif prior:
            previous = metric["fn"](prior, params)
            if previous is not None:
                compare_label, compare = "上年同期", previous[0]
                compare_used, compare_estimate = [f"{name}_py" for name in previous[1]], previous[2]
        change = None if compare is None else value - compare
        level, note = _level(key, value, change, params)
        notes = [note] if note else []
        reason = _judged_out(key, values, computed, params)
        if reason:
            level, notes = "unknown", [reason]
        if key == "dso" and "contract_assets_end" in values and not _with_contract_assets(values):
            notes.append("年初缺合同资产，两端都只算应收账款")
        elif key == "dso" and "contract_assets_end" not in values:
            notes.append("未取合同资产，应收天数只含应收账款")
        if key in {"implied_collection", "impairment_to_gross_profit"} and values.get("impairment", 0) < 0:
            notes.append("减值在报表中列为负数，按绝对值计")
        manual = sorted(name for name in {*used, *compare_used} if name in entity["manual"])
        if manual:
            notes.append("含手填数：" + "、".join(_input_label(name) for name in manual))
        if estimate:
            notes.append("估算")
        own = metric["unit"](entity) if "unit" in metric else entity.get("unit")
        unit = UNIT_BY_KIND.get(kind, own)
        change_unit = CHANGE_UNIT_BY_KIND.get(kind, own)

        def row(scenario, number, row_unit, read, is_estimate, *, signed=False, judged=False):
            shown = _shown(kind, number) if row_unit in {"%", "百分点"} else number
            return {
                "entity": entity["name"],
                "entity_origin": entity.get("origin", "declared"),
                "metric_key": key,
                "metric_label": metric["label"],
                "scenario": scenario,
                "value": format(shown, "f"),
                "unit": row_unit,
                "display_value": _display(row_unit, shown, signed=signed),
                "level": level if judged else None,
                "level_label": LEVEL_LABELS.get(level or "") if judged else None,
                "estimate": is_estimate,
                "formula": metric["formula"],
                "note": "；".join(notes) if judged else ("估算" if is_estimate else ""),
                "inputs": {name: format(values[name], "f") for name in read},
                "source_rows": [ref for name in read for ref in entity["sources"].get(name, [])],
            }

        rows.append(row("本期", value, unit, used, estimate, signed=kind == "pp", judged=True))
        if compare is not None:
            rows.append(row(compare_label, compare, unit, compare_used, compare_estimate, signed=kind == "pp"))
            both = sorted({*used, *compare_used})
            rows.append(row("变动", change, change_unit, both, estimate or compare_estimate, signed=True))
    _provision_follow_up(rows)
    risk = _risk_row(entity, values, computed, params)
    if risk:
        rows.append(risk)
    return rows, skipped


def _risk_signals(values: dict, computed: dict, p: dict) -> list[tuple[str, int, str]]:
    """(signal, points, hit | clear | unknown) for each screening signal of the risk radar."""
    out: list[tuple[str, int, str]] = []

    def add(label: str, points: int | None) -> None:
        out.append((label, points or 0, "unknown" if points is None else "hit" if points else "clear"))

    add("营业利润为负", None if "operating_profit" not in values else 2 if values["operating_profit"] < 0 else 0)
    share = computed.get("impairment_to_gross_profit")
    gp = _gross_profit(values)
    if share is None or (gp is not None and gp[0] <= 0):
        add("减值占毛利高", None)
    else:
        add("减值占毛利高", 2 if share > p["impairment_red_above"] else 1 if share > p["impairment_yellow_above"] else 0)
    dso = computed.get("dso")
    if dso is None or computed.get("ttm_revenue", Decimal(1)) <= 0:
        add("应收天数长", None)
    else:
        add("应收天数长", 2 if dso > p["dso_red_above"] else 1 if dso > p["dso_yellow_above"] else 0)
    gap = computed.get("collection_gap")
    add("收缴率低于生死线", None if gap is None else 2 if gap < p["gap_severe_below"] else 1 if gap < 0 else 0)
    if _need(values, "collection_rate_current", "collection_rate_current_py"):
        drop = values["collection_rate_current_py"] - values["collection_rate_current"]
        add("收缴率同比下降", 1 if drop > p["risk_collection_drop"] else 0)
    else:
        add("收缴率同比下降", None)
    if _need(values, "revenue", "revenue_py") and values["revenue_py"] > 0:
        add("收入同比下滑", 1 if (values["revenue"] - values["revenue_py"]) / values["revenue_py"] < -p["risk_revenue_decline"] else 0)
    else:
        add("收入同比下滑", None)
    share = None
    if _need(values, "revenue_py", "revenue_py_full") and values["revenue_py_full"] > 0 and values["revenue_py"] > 0:
        share = values["revenue_py"] / values["revenue_py_full"]  # last year's pace
    elif "months_elapsed" in values:
        share = values["months_elapsed"] / 12  # linear, when last year's pace is not given
    if _need(values, "revenue", "revenue_budget_full") and values["revenue_budget_full"] > 0 and share:
        pace = values["revenue"] / (values["revenue_budget_full"] * share)
        add("收入预算进度落后" if "revenue_py_full" in values else "收入预算进度落后（按月数线性）",
            1 if pace < 1 - p["risk_budget_lag"] else 0)
    else:
        add("收入预算进度落后", None)
    return out


RISK_INPUTS = ("operating_profit", "impairment", "revenue", "cost", "gross_profit", "ar_end", "contract_assets_end",
               "revenue_ttm", "revenue_py_full", "revenue_py", "period_expense", "gross_margin", "expense_ratio",
               "collection_rate_current", "collection_rate_current_py", "revenue_budget_full", "months_elapsed")


def _pct(value: Decimal) -> str:
    return f"{display_amount(value * 100).removesuffix('.00')}%"


def _points(value: Decimal) -> str:
    return f"{display_amount(abs(value) * 100).removesuffix('.00')} 个百分点"


def _days(value: Decimal) -> str:
    return f"{display_amount(value).removesuffix('.00')} 天"


def _risk_formula(p: dict) -> str:
    """The scoring rule as the parameters of this run set it."""
    def n(value: Decimal) -> str:
        return display_amount(value).removesuffix(".00")

    return (
        f"七项信号加总：营业利润为负 2 分；减值占毛利超过 {_pct(p['impairment_red_above'])} 2 分、"
        f"超过 {_pct(p['impairment_yellow_above'])} 1 分；应收天数超过 {_days(p['dso_red_above'])} 2 分、"
        f"超过 {_days(p['dso_yellow_above'])} 1 分；收缴率低于生死线超过 {_points(p['gap_severe_below'])} 2 分、"
        f"低于 1 分；收缴率同比降超过 {_points(p['risk_collection_drop'])} 1 分；收入同比降超过 "
        f"{_pct(p['risk_revenue_decline'])} 1 分；收入预算进度落后超过 {_points(p['risk_budget_lag'])} 1 分"
        f"（按去年节奏，没有去年数时按月数线性）。不低于 {n(p['risk_red_at'])} 分红，不低于 "
        f"{n(p['risk_orange_at'])} 分橙，不低于 {n(p['risk_yellow_at'])} 分黄，其余绿"
    )


def _risk_row(entity: dict, values: dict, computed: dict, p: dict) -> dict | None:
    """A screening score from the signals the entity's inputs allow. Not a rating, and never counted in the close."""
    signals = _risk_signals(values, computed, p)
    known = [signal for signal in signals if signal[2] != "unknown"]
    if len(known) < 2:
        return None
    score = sum(points for _, points, status in signals if status == "hit")
    level = ("red" if score >= p["risk_red_at"] else "orange" if score >= p["risk_orange_at"]
             else "yellow" if score >= p["risk_yellow_at"] else "green")
    hits = [f"{label}（{points}分）" for label, points, status in signals if status == "hit"]
    unknown = [label for label, _, status in signals if status == "unknown"]
    notes = [("触发：" + "、".join(hits)) if hits else "未触发信号"]
    if unknown:
        notes.append("无法判断：" + "、".join(unknown))
    read = [name for name in RISK_INPUTS if name in values]
    estimate = "dso" in computed and "revenue_ttm" not in values and any(
        label == "应收天数长" and status != "unknown" for label, _, status in signals)
    manual = sorted(name for name in read if name in entity["manual"])
    if manual:
        notes.append("含手填数：" + "、".join(_input_label(name) for name in manual))
    if estimate:
        notes.append("应收天数用估算的近12个月收入")
    notes.append("筛查提示，不是评级，不计入月结")
    return {
        "entity": entity["name"],
        "entity_origin": entity.get("origin", "declared"),
        "metric_key": "risk_score",
        "metric_label": "风险雷达得分",
        "scenario": "本期",
        "value": str(score),
        "unit": "分",
        "display_value": f"{score} 分",
        "level": level,
        "level_label": LEVEL_LABELS[level],
        "estimate": estimate,
        "formula": _risk_formula(p),
        "note": "；".join(notes),
        "inputs": {name: format(values[name], "f") for name in read},
        "source_rows": [ref for name in read for ref in entity["sources"].get(name, [])],
    }


def _provision_follow_up(rows: list[dict]) -> None:
    """Older receivables with a falling provision rate: the provision has not kept up."""
    changes = {row["metric_key"]: Decimal(row["value"]) for row in rows if row["scenario"] == "变动"}
    provision = next((row for row in rows if row["metric_key"] == "provision_ratio" and row["scenario"] == "本期"), None)
    if provision is None or "aging_over_1y_share" not in changes or "provision_ratio" not in changes:
        return
    if changes["aging_over_1y_share"] > 0 and changes["provision_ratio"] < 0:
        provision["level"], provision["level_label"] = "yellow", LEVEL_LABELS["yellow"]
        provision["note"] = "；".join(filter(None, ["账龄变老而拨备率下降，拨备没跟上", provision["note"]]))


def _input_label(name: str) -> str:
    if name.endswith("_py"):
        return INPUT_LABELS[name[:-3]] + "（上年同期）"
    return INPUT_LABELS[name]


def _frange(start: Decimal, stop: Decimal, step: Decimal) -> list[Decimal]:
    out, value = [], start
    while value <= stop + step / 1000 and len(out) < 200:
        out.append(value)
        value += step
    return out


def break_even_matrix(entity: dict, params: dict[str, Decimal]) -> dict | None:
    """Cash operating margin over a grid of gross margins and collection rates, at the entity's expense ratio."""
    values = entity["values"]
    er = _m_expense_ratio(values, params)
    if er is None:
        return None
    gm = _m_gross_margin(values, params)
    margins = _frange(params["matrix_margin_from"], params["matrix_margin_to"], params["matrix_margin_step"])
    rates = _frange(
        params["matrix_collection_from"], params["matrix_collection_to"], params["matrix_collection_step"]
    )
    return {
        "entity": entity["name"],
        "expense_ratio": format(er[0], "f"),
        "gross_margins": [format(m, "f") for m in margins],
        "collection_rates": [format(c, "f") for c in rates],
        "cells": [[format(c - (1 - m) - er[0], "f") for c in rates] for m in margins],
        # Cells at or above zero but below this sit close to the line (the gap's yellow threshold).
        "edge_below": format(params["gap_yellow_below"], "f"),
        "current": {
            "gross_margin": None if gm is None else format(gm[0], "f"),
            "collection_rate": None
            if "collection_rate_current" not in values
            else format(values["collection_rate_current"], "f"),
        },
        "formula": "现金经营利润率 = 收缴率 − （1 − 毛利率）− 期间费用率",
    }


def evaluate_collection_health(entities: list[dict], params: dict[str, Decimal]) -> dict:
    rows, diagnostics, matrices = [], [], []
    for entity in entities:
        entity_rows, skipped = evaluate_entity(entity, params)
        rows.extend(entity_rows)
        if skipped:
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "collection_metric_skipped",
                    "message": f"{entity['name']} 有 {len(skipped)} 项指标缺输入，未计算",
                    "entity": entity["name"],
                    "skipped": skipped,
                }
            )
        if entity["sensitivity"]:
            matrix = break_even_matrix(entity, params)
            if matrix is None:
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "collection_matrix_skipped",
                        "message": f"{entity['name']} 缺期间费用率，生死线矩阵未计算",
                        "entity": entity["name"],
                    }
                )
            else:
                matrices.append(matrix)
    if not rows:
        diagnostics.append(
            {
                "severity": "error",
                "code": "empty_result",
                "message": "collection_health produced no metric; every metric lacked an input",
            }
        )
    return {
        "domain": DOMAIN,
        # Stamped here, not on every scenario result: older runs of other kinds keep their output hash.
        "scenario_kind": "collection_health",
        "columns": COLUMNS,
        "rows": rows,
        "diagnostics": diagnostics,
        "sensitivity": matrices,
        "params": {key: format(value, "f") for key, value in params.items()},
        "assumptions": [
            {
                "label": "税率因子",
                "value": format(params["vat_factor"], "f"),
                "detail": "收到的现金含销项税，营业收入不含，现金回收比和反推回款率按此换算",
            }
        ],
    }
