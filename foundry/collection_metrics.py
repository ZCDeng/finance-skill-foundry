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

RATE_INPUTS = frozenset({"collection_rate_current", "collection_rate_total", "gross_margin", "expense_ratio"})

LEVEL_LABELS = {"red": "红", "yellow": "黄", "green": "绿", "unknown": "无法判断"}

COLUMNS = [
    "entity",
    "metric_key",
    "metric_label",
    "value_kind",
    "value",
    "display_value",
    "compare_label",
    "compare_value",
    "change",
    "change_display",
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


def _parse_cell(value: Any, *, rate: bool, scale: str | None, where: str) -> Decimal:
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
    if rate and scale is None and abs(number) > Decimal("1.5"):
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
        for key, ref in refs.items():
            key = _input_name(key)
            rate = key.removesuffix("_py") in RATE_INPUTS
            where = f"{name}.{key}"
            if not isinstance(ref, dict):
                values[key] = _parse_cell(ref, rate=rate, scale=None, where=where)
                manual.add(key)
                continue
            alias = ref.get("alias")
            if alias not in rows_by_alias:
                raise FoundryError(f"{where} alias {alias} is not bound")
            column = ref.get("column")
            if not isinstance(column, str) or not column:
                raise FoundryError(f"{where} requires a column")
            candidates = rows_by_alias[alias]
            if "source_row" in ref:
                candidates = [r for r in candidates if r["source"].get("source_row") == ref["source_row"]]
                wanted = f"source_row {ref['source_row']}"
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
            values[key] = _parse_cell(row[column], rate=rate, scale=ref.get("scale"), where=where)
            sources[key] = {**row["source"], "column": column}
            unit = ref.get("unit") or row.get("unit") or units_by_alias.get(alias)
            if unit and not rate:
                units[key] = str(unit)
        distinct = sorted(set(units.values()))
        if len(distinct) > 1:
            raise FoundryError(
                f"{name} mixes amount units {', '.join(distinct)}; ratios across units are wrong"
            )
        entities.append(
            {
                "name": name,
                "values": values,
                "sources": sources,
                "manual": manual,
                "sensitivity": bool(raw.get("sensitivity")),
            }
        )
    return entities


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
        for row in rows_by_alias[alias]:
            name = row.get(name_column)
            if _blank(name) or str(name).strip() in exclude:
                continue
            values = {}
            for key, column in columns.items():
                spec = column if isinstance(column, dict) else {"column": column}
                if _blank(row.get(spec.get("column"))):
                    continue
                values[key] = {**spec, "alias": alias, "source_row": row["source"]["source_row"]}
            if values:
                out.append({"name": prefix + str(name).strip(), "values": values})
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
    if ca in v:
        return v[ar] + v[ca], [ar, ca]
    return v[ar], [ar]


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
    value = _div(change[0] + v["impairment"], v["revenue"] * p["vat_factor"])
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
    value = _div(v["impairment"], gp[0])
    return None if value is None else (value, sorted({*gp[1], "impairment"}), False)


def _share(numerator: str, denominator: str) -> Callable[[dict, dict], Computed]:
    def compute(v, p) -> Computed:
        if not _need(v, numerator, denominator):
            return None
        value = _div(v[numerator], v[denominator])
        return None if value is None else (value, [numerator, denominator], False)

    return compute


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
     "formula": "1 − （应收增加额 + 本期减值）÷（本期营业收入 × 税率因子）"},
    {"key": "implied_vs_reported", "label": "反推回款率与综合收缴率之差", "kind": "pp",
     "fn": _m_implied_vs_reported, "formula": "反推回款率 − 综合收缴率"},
    {"key": "rollforward_collection", "label": "滚动回款率", "kind": "ratio", "fn": _m_rollforward_collection,
     "formula": "本期收回 ÷（年初余额 + 本期新增）"},
    {"key": "cash_collection_ratio", "label": "现金回收比", "kind": "ratio", "fn": _m_cash_collection,
     "formula": "销售商品、提供劳务收到的现金 ÷（营业收入 × 税率因子）"},
    {"key": "impairment_to_gross_profit", "label": "减值占毛利", "kind": "ratio", "fn": _m_impairment_to_gp,
     "formula": "减值损失 ÷ 毛利"},
    {"key": "provision_ratio", "label": "应收拨备率", "kind": "ratio", "fn": _share("provision", "ar_gross"),
     "formula": "坏账准备 ÷ 应收账款账面余额"},
    {"key": "aging_over_1y_share", "label": "账龄1年以上占比", "kind": "ratio",
     "fn": _share("ar_over_1y", "ar_gross"), "formula": "账龄1年以上余额 ÷ 应收账款账面余额"},
    {"key": "related_party_share", "label": "关联方应收占比", "kind": "ratio",
     "fn": _share("related_ar", "ar_gross"), "formula": "关联方应收余额 ÷ 应收账款账面余额"},
    {"key": "related_party_provision_ratio", "label": "关联方拨备率", "kind": "ratio",
     "fn": _share("related_provision", "related_ar"), "formula": "关联方坏账准备 ÷ 关联方应收余额"},
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
    "related_party_provision_ratio": ("related_provision", "related_ar"),
}


# ---------------------------------------------------------------- levels


def _bump(level: str | None) -> str | None:
    return {"green": "yellow", "yellow": "red"}.get(level or "", level)


def _level(key: str, value: Decimal, change: Decimal | None, p: dict) -> tuple[str | None, str]:
    """A screening light and the reason for it. None means the metric carries no threshold."""
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


def _display(kind: str, value: Decimal) -> str:
    if kind == "ratio":
        return display_percent(value)
    if kind == "pp":
        return f"{display_amount(value * 100)}pp"
    if kind == "days":
        return f"{display_amount(value)} 天"
    return display_amount(value)


def _change_display(kind: str, change: Decimal) -> str:
    sign = "+" if change > 0 else ""
    if kind in {"ratio", "pp"}:
        return f"{sign}{display_amount(change * 100)}pp"
    if kind == "days":
        return f"{sign}{display_amount(change)} 天"
    return f"{sign}{display_amount(change)}"


def _prior(values: dict[str, Decimal]) -> dict[str, Decimal]:
    return {key[:-3]: value for key, value in values.items() if key.endswith("_py")}


def evaluate_entity(entity: dict, params: dict[str, Decimal]) -> tuple[list[dict], list[dict]]:
    """Every metric the entity's inputs support, and a diagnostic per metric they do not."""
    values = entity["values"]
    prior = _prior(values)
    rows, skipped = [], []
    for metric in METRICS:
        key = metric["key"]
        computed = metric["fn"](values, params)
        if computed is None:
            skipped.append({"metric_key": key, "needs": list(_METRIC_INPUTS[key])})
            continue
        value, used, estimate = computed
        compare_label = compare_value = change = None
        if metric.get("compare") == "begin":
            begin = _m_dso_begin(values, params)
            if begin is not None:
                compare_label, compare_value = "年初", begin[0]
                used = sorted({*used, *begin[1]})
        else:
            previous = metric["fn"](prior, params) if prior else None
            if previous is not None:
                compare_label, compare_value = "上年同期", previous[0]
                used = sorted({*used, *(f"{name}_py" for name in previous[1])})
                estimate = estimate or previous[2]
        if compare_value is not None:
            change = value - compare_value
        level, note = _level(key, value, change, params)
        notes = [note] if note else []
        if key == "implied_collection" and not (
            params["implied_collection_min"] <= value <= params["implied_collection_max"]
        ):
            level = "unknown"
            notes.append("超出合理区间，可能受收并购、处置或重分类影响，不作判断")
        if key == "dso" and "contract_assets_end" not in values:
            notes.append("未取合同资产，应收天数只含应收账款")
        manual = sorted(name for name in used if name in entity["manual"])
        if manual:
            notes.append("含手填数：" + "、".join(_input_label(name) for name in manual))
        if estimate:
            notes.append("估算")
        rows.append(
            {
                "entity": entity["name"],
                "metric_key": key,
                "metric_label": metric["label"],
                "value_kind": metric["kind"],
                "value": format(value, "f"),
                "display_value": _display(metric["kind"], value),
                "compare_label": compare_label,
                "compare_value": None if compare_value is None else format(compare_value, "f"),
                "change": None if change is None else format(change, "f"),
                "change_display": None if change is None else _change_display(metric["kind"], change),
                "level": level,
                "level_label": LEVEL_LABELS.get(level or ""),
                "estimate": estimate,
                "formula": metric["formula"],
                "note": "；".join(notes),
                "inputs": {name: format(values[name], "f") for name in used},
                "source_rows": [entity["sources"][name] for name in used if name in entity["sources"]],
            }
        )
    _provision_follow_up(rows)
    return rows, skipped


def _provision_follow_up(rows: list[dict]) -> None:
    """Older receivables with a falling provision rate: the provision has not kept up."""
    by_key = {row["metric_key"]: row for row in rows}
    aging, provision = by_key.get("aging_over_1y_share"), by_key.get("provision_ratio")
    if not aging or not provision or aging["change"] is None or provision["change"] is None:
        return
    if Decimal(aging["change"]) > 0 and Decimal(provision["change"]) < 0:
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
