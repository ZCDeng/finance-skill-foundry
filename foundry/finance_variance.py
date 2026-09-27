"""Arithmetic variance bridges with source evidence, independent of persistence."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext

from foundry.errors import FoundryError
from foundry.finance_metrics import evaluate_metric


def _decimal(value):
    try:
        result = Decimal(str(value))
        if isinstance(value, bool) or not result.is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError) as exc:
        raise FoundryError("variance amounts must be finite decimal values") from exc


def _text(value):
    return format(value, "f")


def variance_ratio(actual, baseline, *, negative_policy="absolute_baseline"):
    """Signed change / declared denominator; zero has no percentage."""
    actual, baseline = _decimal(actual), _decimal(baseline)
    if negative_policy not in {"absolute_baseline", "signed_baseline"}:
        raise FoundryError("negative budget policy must be explicit and supported")
    if baseline == 0:
        return {"ratio": None, "ratio_status": "baseline_zero"}
    denominator = abs(baseline) if negative_policy == "absolute_baseline" else baseline
    with localcontext() as ctx:
        ctx.prec = 50
        return {
            "ratio": _text((actual - baseline) / denominator),
            "ratio_status": negative_policy,
        }


def explain_variance(normalized: dict, spec: dict) -> dict:
    """Preaggregate facts independently before comparing budget/actual groups.

    Period comparisons require explicit side filters. Missing groups remain
    incomplete unless the manager selects missing_groups_as_zero. Inside a
    group both sides have, an account with source rows on one side only is
    partial (缺项), and so is the profit line built on it; the count-as-zero
    choice covers whole groups, not these.
    """
    spec = _require_spec(spec, "variance spec")
    actual_label = spec.get("actual_scenario", "actual")
    baseline_label = spec.get("baseline_scenario", "budget")
    dimensions = _dimensions(spec, default=[])
    invalid = set(dimensions) & {"management_account", "account_code", "metric"}
    if invalid:
        raise FoundryError("profit bridge already groups accounts as metric rows; remove management_account/account_code/metric from dimensions and use organization, period or business dimensions")
    if not _explicit_period_comparison(spec):
        dimensions = list(dict.fromkeys([*dimensions, "period"]))
    if "scenario" in dimensions:
        dimensions.remove("scenario")
    sides = []
    diagnostics = list(normalized.get("diagnostics", []))
    for label, filters in (
        (actual_label, _filters(spec, "actual_filters")),
        (baseline_label, _filters(spec, "baseline_filters")),
    ):
        selected = [
            r
            for r in normalized.get("rows", [])
            if r.get("scenario") == label and _matches_filters(r, filters)
        ]
        selected_scopes = {}
        for row in selected:
            key = tuple(row.get(dim) for dim in dimensions)
            selected_scopes.setdefault(key, []).append(row)
        metric = evaluate_metric(
            {"rows": selected, "diagnostics": []},
            {
                "kind": "management_pnl",
                "dimensions": dimensions,
                "scenario_bindings": {"actual": actual_label, "budget": baseline_label},
                **(
                    {"account_signs": spec["account_signs"]}
                    if "account_signs" in spec
                    else {}
                ),
            },
        )
        # A period comparison may have several periods on one side. Aggregate
        # these already-computed flow metrics, retaining all contributing rows.
        groups = {}
        for row in metric["rows"]:
            key = tuple(row.get(dim) for dim in dimensions)
            if key not in groups:
                groups[key] = {
                    "revenue": Decimal(0),
                    "cost": Decimal(0),
                    "expense": Decimal(0),
                    "profit": Decimal(0),
                    "scope": _side_scope(
                        selected_scopes.get(key, []), label=label, filters=filters
                    ),
                    "evidence": defaultdict(list),
                }
            group = groups[key]
            for account in ("revenue", "cost", "expense", "profit"):
                group[account] += _decimal(row[account])
                group["evidence"][account].extend(
                    row.get("evidence", {}).get(account, [])
                )
        sides.append(groups)
    actuals, baselines = sides
    rows = []
    for key in sorted(actuals.keys() | baselines.keys(), key=repr):
        a, b = actuals.get(key), baselines.get(key)
        missing = a is None or b is None
        context = dict(zip(dimensions, key))
        if missing:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "comparison_group_missing",
                    "group": context,
                    "missing_side": "actual" if a is None else "baseline",
                    "actual_filters": spec.get("actual_filters", {}),
                    "baseline_filters": spec.get("baseline_filters", {}),
                    "suggested_actions": [
                        "检查实际和基准 scenario、期间、组织、账套过滤条件",
                        "补充缺失资料后重跑，或由经理明确 missing_groups_as_zero=true",
                    ],
                    "message": "比较口径缺少实际或基准组；未自动把缺失资料视为零。",
                }
            )
        # Which side has source rows for each account. Both sides empty is a
        # line neither books (0 against 0), which is a complete comparison.
        one_sided = (
            {}
            if missing
            else {
                account: "actual" if not a["evidence"].get(account) else "baseline"
                for account in ("revenue", "cost", "expense")
                if bool(a["evidence"].get(account)) != bool(b["evidence"].get(account))
            }
        )
        for account, missing_side in one_sided.items():
            side_word = "实际" if missing_side == "actual" else "基准"
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "comparison_account_missing",
                    "group": context,
                    "metric": account,
                    "missing_side": missing_side,
                    "suggested_actions": [
                        f"检查{side_word}资料是否漏了这个科目，或科目映射是否一致",
                        "补齐后重跑；补齐前这一行和利润行都不算完整比较",
                    ],
                    "message": f"{_ACCOUNT_LABELS[account]}在{side_word}一侧没有来源行，这一行和利润行标为缺项。",
                }
            )
        zero = {
            "revenue": Decimal(0),
            "cost": Decimal(0),
            "expense": Decimal(0),
            "profit": Decimal(0),
            "evidence": {},
        }
        for account, sign in (
            ("revenue", Decimal(1)),
            ("cost", Decimal(-1)),
            ("expense", Decimal(-1)),
            ("profit", Decimal(1)),
        ):
            av, bv = (a or zero)[account], (b or zero)[account]
            calculable = not missing or spec.get("missing_groups_as_zero") is True
            amount_change = av - bv if calculable else None
            profit_impact = amount_change * sign if amount_change is not None else None
            refs = [
                *(a or zero)["evidence"].get(account, []),
                *(b or zero)["evidence"].get(account, []),
            ]
            rows.append(
                {
                    **context,
                    "metric": account,
                    "actual": _text(av) if a or calculable else None,
                    "baseline": _text(bv) if b or calculable else None,
                    "actual_scope": (a or {}).get(
                        "scope", _declared_scope(actual_label, spec.get("actual_filters", {}))
                    ),
                    "baseline_scope": (b or {}).get(
                        "scope", _declared_scope(baseline_label, spec.get("baseline_filters", {}))
                    ),
                    "amount_change": None
                    if amount_change is None
                    else _text(amount_change),
                    "profit_impact": None
                    if profit_impact is None
                    else _text(profit_impact),
                    "contribution": None
                    if profit_impact is None
                    else _text(profit_impact),
                    "amount_change_display": _display_amount_change(
                        account, amount_change, context.get("unit")
                    ),
                    "profit_impact_display": _display_profit_impact(
                        profit_impact, context.get("unit")
                    ),
                    "display_value": _display_profit_impact(
                        profit_impact, context.get("unit")
                    ),
                    "favorability": "unknown"
                    if profit_impact is None
                    else "favorable"
                    if profit_impact > 0
                    else "unfavorable"
                    if profit_impact < 0
                    else "neutral",
                    "comparison_status": "assumed_zero"
                    if missing and calculable
                    else "incomplete"
                    if missing
                    else "partial"
                    if account in one_sided or (account == "profit" and one_sided)
                    else "complete",
                    "basis": "calculation",
                    "semantics": {
                        "metric_kind": "profit_bridge",
                        "amount_change_direction": _direction(amount_change),
                        "profit_impact_direction": _direction(profit_impact),
                        "profit_impact_sign_policy": "revenue - cost - expense",
                        "contribution_alias": "profit_impact",
                    },
                    "source_rows": refs,
                    **(
                        variance_ratio(
                            av,
                            bv,
                            negative_policy=spec.get(
                                "negative_budget_policy", "absolute_baseline"
                            ),
                        )
                        if calculable
                        else {"ratio": None, "ratio_status": "missing_input"}
                    ),
                }
            )
    return {
        "domain": "foundry.finance.variance.v1",
        "columns": [
            *dimensions,
            "metric",
            "actual",
            "baseline",
            "amount_change",
            "profit_impact",
            "contribution",
            "ratio",
            "ratio_status",
            "favorability",
            "comparison_status",
        ],
        "rows": rows,
        "diagnostics": diagnostics,
        "method": "revenue_minus_cost_minus_expense",
        "interpretation": "分量表示算术贡献。业务原因需经理判断或独立证据。",
        "comparison": {
            "actual_scenario": actual_label,
            "baseline_scenario": baseline_label,
            "actual_filters": spec.get("actual_filters", {}),
            "baseline_filters": spec.get("baseline_filters", {}),
        },
    }


def _declared_scope(label, filters):
    return {"scenario": label, "filters": filters or {}}


def _side_scope(rows, *, label, filters):
    scope = _declared_scope(label, filters)
    for key in ("ledger", "organization", "period", "currency", "unit"):
        values = sorted({str(row.get(key)) for row in rows if row.get(key) not in (None, "")})
        if len(values) == 1:
            scope[key] = values[0]
        elif len(values) > 1:
            scope[key] = values
    return scope


def _direction(value):
    if value is None:
        return "unknown"
    if value > 0:
        return "increase"
    if value < 0:
        return "decrease"
    return "neutral"


def _display_profit_impact(value, unit):
    if value is None:
        return None
    text = _text(value)
    return f"利润影响 {text} {unit}" if unit else f"利润影响 {text}"


_ACCOUNT_LABELS = {"revenue": "收入", "cost": "成本", "expense": "费用", "profit": "利润"}


def _display_amount_change(account, value, unit):
    if value is None:
        return None
    word = "增加" if value > 0 else "减少" if value < 0 else "持平"
    amount = abs(value)
    text = _text(amount)
    suffix = f" {unit}" if unit else ""
    return f"{_ACCOUNT_LABELS.get(account, account)}{word} {text}{suffix}"


def _declared_amount(row: dict, field: str) -> Decimal | None:
    """The amount the row states for itself, if it states one at all."""
    value = row.get(field)
    if value in (None, ""):
        return None
    try:
        return _decimal(value)
    except (ArithmeticError, ValueError, TypeError):
        return None


def price_quantity_bridge(rows: list[dict], spec: dict) -> dict:
    """Compare explicitly paired product observations; never invent drivers."""
    spec = _require_spec(spec, "price/quantity variance spec")
    method = spec.get("method", "quantity_then_price")
    if method not in {"quantity_then_price", "base_weights_with_interaction"}:
        raise FoundryError("unknown price/quantity decomposition method")
    field_map = spec.get("field_map", {})
    if not isinstance(field_map, dict):
        raise FoundryError("price/quantity field_map must be an object")
    fields = {
        "quantity": "quantity",
        "price": "price",
        "scenario": "scenario",
        "amount": "amount",
        **field_map,
    }
    dimensions = _dimensions(spec, default=["product"])
    if not _explicit_period_comparison(spec):
        dimensions = list(dict.fromkeys([*dimensions, "period"]))
    dimensions = [dim for dim in dimensions if dim != "scenario"]
    groups = defaultdict(dict)
    actual, baseline = (
        spec.get("actual_scenario", "actual"),
        spec.get("baseline_scenario", "budget"),
    )
    for side, label in (("actual", actual), ("baseline", baseline)):
        filters = _filters(spec, f"{side}_filters")
        for row in rows:
            if row.get(fields["scenario"]) != label or not _matches_filters(
                row, filters
            ):
                continue
            key = tuple(row.get(dim) for dim in dimensions)
            if side in groups[key]:
                raise FoundryError(
                    "multiple product observations: declare and preaggregate quantity and weighted price before comparison"
                )
            groups[key][side] = row
    result, diagnostics = [], []
    with localcontext() as ctx:
        ctx.prec = 80
        for key, pair in sorted(groups.items(), key=lambda item: repr(item[0])):
            if (
                "actual" not in pair
                or "baseline" not in pair
                or any(
                    pair[s].get(fields[f]) in (None, "")
                    for s in ("actual", "baseline")
                    for f in ("price", "quantity")
                )
            ):
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "price_quantity_missing",
                        "group": dict(zip(dimensions, key)),
                        "message": "缺少对应数量和价格，不能分解量价贡献。",
                    }
                )
                continue
            a, b = pair["actual"], pair["baseline"]
            qa, qb, pa, pb = (
                _decimal(v)
                for v in (
                    a[fields["quantity"]],
                    b[fields["quantity"]],
                    a[fields["price"]],
                    b[fields["price"]],
                )
            )
            quantity = (qa - qb) * pb
            price = (pa - pb) * (qa if method == "quantity_then_price" else qb)
            interaction = (
                Decimal(0) if method == "quantity_then_price" else (qa - qb) * (pa - pb)
            )
            total = qa * pa - qb * pb
            # A row that also states its amount is stating a fact about the
            # books. Where q×p disagrees with it the decomposition is describing
            # something the ledger does not say, and the manager has to be the
            # one who decides which is wrong -- silently preferring q×p reported
            # 34,221 against a booked 409,500 with nothing to notice.
            for side, row, computed in (("actual", a, qa * pa), ("baseline", b, qb * pb)):
                declared = _declared_amount(row, fields["amount"])
                if declared is not None and declared != computed:
                    diagnostics.append(
                        {
                            "severity": "warning",
                            "code": "price_quantity_amount_mismatch",
                            "group": dict(zip(dimensions, key)),
                            "side": side,
                            "declared": _text(declared),
                            "computed": _text(computed),
                            "message": (
                                f"{side} 行声明金额 {_text(declared)}，数量乘单价得 "
                                f"{_text(computed)}；分解用的是数量乘单价。"
                            ),
                        }
                    )
            result.append(
                {
                    **dict(zip(dimensions, key)),
                    "actual": _text(qa * pa),
                    "baseline": _text(qb * pb),
                    "quantity_contribution": _text(quantity),
                    "price_contribution": _text(price),
                    "interaction": _text(interaction),
                    "total_variance": _text(total),
                    "residual": _text(total - quantity - price - interaction),
                    "source_rows": [r["source"] for r in (a, b) if r.get("source")],
                }
            )
    return {
        "domain": "foundry.finance.variance.v1",
        "method": method,
        "columns": [
            *dimensions,
            "actual",
            "baseline",
            "quantity_contribution",
            "price_contribution",
            "interaction",
            "total_variance",
            "residual",
        ],
        "rows": result,
        "diagnostics": diagnostics,
        "comparison": {
            "actual_scenario": actual,
            "baseline_scenario": baseline,
            "actual_filters": spec.get("actual_filters", {}),
            "baseline_filters": spec.get("baseline_filters", {}),
        },
        "interpretation": "数量与价格按声明顺序分解；算术贡献不证明业务因果。",
    }


def _explicit_period_comparison(spec):
    return all(
        isinstance(spec.get(key), dict) and spec[key].get("period") not in (None, "")
        for key in ("actual_filters", "baseline_filters")
    )


def _require_spec(spec, label):
    if not isinstance(spec, dict):
        raise FoundryError(f"{label} must be an object")
    return spec


def _filters(spec, key):
    filters = spec.get(key, {})
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise FoundryError("comparison filters must be objects")
    return filters


def _dimensions(spec, *, default):
    requested = spec.get("dimensions", default)
    if isinstance(requested, str) or not isinstance(requested, (list, tuple)):
        raise FoundryError("variance dimensions must be a list")
    return list(
        dict.fromkeys(["ledger", "organization", "currency", "unit", *requested])
    )


def _matches_filters(row, filters):
    for key, value in filters.items():
        actual = row.get(key)
        if isinstance(value, (list, tuple, set, frozenset)):
            if actual not in value:
                return False
        elif actual != value:
            return False
    return True
