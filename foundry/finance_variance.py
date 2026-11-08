"""Arithmetic variance bridges with source evidence, independent of persistence."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext

from foundry.display_numbers import display_amount
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
                    "actual_scenario": actual_label,
                    "baseline_scenario": baseline_label,
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
            "actual_scenario",
            "baseline_scenario",
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


def _explicit_zero_actual_volume(observations):
    """Every actual quantity is an explicit zero and every baseline quantity is positive.

    Prices stay the ones supplied. This is not a missing price and not a licence
    to divide by the actual volume or to publish mix and price effects as zero.
    """
    actuals = observations.get("actual") or {}
    baselines = observations.get("baseline") or {}
    if not actuals or set(actuals) != set(baselines):
        return False
    if any(item is None for side in (actuals, baselines) for item in side.values()):
        return False
    if not all(item[0] == 0 and item[1] >= 0 for item in actuals.values()):
        return False
    return all(item[0] > 0 and item[1] >= 0 for item in baselines.values())


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
    text = display_amount(value)
    return f"利润影响 {text} {unit}" if unit else f"利润影响 {text}"


_ACCOUNT_LABELS = {"revenue": "收入", "cost": "成本", "expense": "费用", "profit": "利润"}


def _display_amount_change(account, value, unit):
    if value is None:
        return None
    word = "增加" if value > 0 else "减少" if value < 0 else "持平"
    amount = abs(value)
    text = display_amount(amount)
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
    if method == "volume_mix_price":
        return _volume_mix_price_bridge(rows, spec)
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


_VMP_AMOUNTS = (
    "actual", "baseline", "total_variance", "volume_contribution",
    "mix_contribution", "price_contribution", "residual",
    "actual_volume", "baseline_volume",
)


def _volume_mix_price_bridge(rows, spec):
    """Decompose a comparable basket in the fixed volume -> mix -> price order.

    A product observation must already be aggregated to quantity and weighted
    price. Missing products, returns and incompatible units need a different
    business model; none is manufactured by filling a missing observation.
    """
    field_map = spec.get("field_map", {})
    if not isinstance(field_map, dict):
        raise FoundryError("price/quantity field_map must be an object")
    fields = {
        "quantity": "quantity", "price": "price", "amount": "amount",
        "scenario": "scenario", "product": "product", **field_map,
    }
    quantity_unit_field = spec.get("quantity_unit_field", "quantity_unit")
    if any(not isinstance(value, str) or not value.strip() for value in fields.values()):
        raise FoundryError("price/quantity field_map values must be column names")
    if not isinstance(quantity_unit_field, str) or not quantity_unit_field.strip():
        raise FoundryError("quantity_unit_field must be a column name")
    dimensions = _dimensions(spec, default=["product"])
    if not _explicit_period_comparison(spec):
        dimensions = list(dict.fromkeys([*dimensions, "period"]))
    dimensions = [dim for dim in dimensions if dim not in {"scenario", "product", fields["product"]}]
    labels = {
        "actual": spec.get("actual_scenario", "actual"),
        "baseline": spec.get("baseline_scenario", "budget"),
    }
    filters = {side: _filters(spec, f"{side}_filters") for side in labels}
    groups = defaultdict(lambda: {"actual": [], "baseline": []})
    for side, label in labels.items():
        for row in rows:
            if row.get(fields["scenario"]) == label and _matches_filters(row, filters[side]):
                groups[tuple(row.get(dim) for dim in dimensions)][side].append(row)

    result, diagnostics = [], []
    if not groups:
        diagnostics.append({
            "severity": "warning", "code": "volume_mix_price_no_observations",
            "message": "筛选范围内没有可比商品观察，不能分解量价贡献。",
        })
    for key, sides in sorted(groups.items(), key=lambda item: repr(item[0])):
        context = dict(zip(dimensions, key))
        ordered = {
            side: sorted(observations, key=lambda row: (repr(row.get(fields["product"])), repr(row.get("source"))))
            for side, observations in sides.items()
        }
        sources = []
        for observations in ordered.values():
            for row in observations:
                source = row.get("source")
                if source and source not in sources:
                    sources.append(source)
        reasons = []

        def issue(code, message, **details):
            if code not in reasons:
                reasons.append(code)
            diagnostics.append({"severity": "warning", "code": code,
                                "group": context, "message": message, **details})

        if any(not isinstance(context.get(field), str) or not context[field].strip() for field in ("currency", "unit")):
            issue("volume_mix_price_monetary_basis_missing", "币种和金额单位必须明确，不能自动推定。")
        quantity_units = {
            row.get(quantity_unit_field)
            for observations in ordered.values() for row in observations
            if isinstance(row.get(quantity_unit_field), str) and row[quantity_unit_field].strip()
        }
        if any(not isinstance(row.get(quantity_unit_field), str) or not row[quantity_unit_field].strip()
               for observations in ordered.values() for row in observations):
            issue("volume_mix_price_quantity_unit_missing", "篮子中每个观察都必须声明数量单位。")
        if len(quantity_units) > 1:
            issue("volume_mix_price_quantity_unit_mismatch", "数量单位不同的商品不能直接汇总为总量或结构占比。")
        quantity_unit = next(iter(quantity_units)) if len(quantity_units) == 1 else None
        observations = {"actual": {}, "baseline": {}}
        declared_count = 0
        values = []
        for side, selected in ordered.items():
            if not selected:
                issue("volume_mix_price_side_missing", "篮子缺少实际或基准观察，不能分解。", side=side)
            for row in selected:
                product = row.get(fields["product"])
                if (not isinstance(product, (str, int)) or isinstance(product, bool)
                        or (isinstance(product, str) and not product.strip())):
                    issue("volume_mix_price_product_missing", "商品必须具有非空、稳定的标识。", side=side)
                    continue
                if product in observations[side]:
                    issue("volume_mix_price_duplicate_product", "同侧商品存在多条观察；请先明确汇总数量及加权价格。", side=side, product=product)
                    continue
                # Remember even invalid observations to distinguish missing
                # products from invalid numeric data without replacing either.
                observations[side][product] = None
                if any(row.get(fields[field]) in (None, "") for field in ("quantity", "price")):
                    issue("price_quantity_missing", "缺少对应数量和价格，不能分解量价贡献。", side=side, product=product)
                    continue
                try:
                    quantity = _decimal(row[fields["quantity"]])
                    price = _decimal(row[fields["price"]])
                    stated = row.get(fields["amount"])
                    declared = None if stated in (None, "") else _decimal(stated)
                except FoundryError:
                    issue("volume_mix_price_invalid_number", "数量、价格及声明金额必须是有限数值。", side=side, product=product)
                    continue
                if quantity < 0 or (quantity == 0 and side != "actual"):
                    # Explicit actual zeros stay on the row. A whole actual side of
                    # zeros is a limited total below; it is not a missing price and
                    # it is not an invented unit price. Baseline zero and negatives
                    # still cannot enter the comparable basket.
                    issue("volume_mix_price_nonpositive_quantity", "零量或负数量需单独处理，不能用于本可比篮子模型。", side=side, product=product)
                if price < 0:
                    issue("volume_mix_price_negative_price", "负价格需单独解释退货或调整，不能用于本可比篮子模型。", side=side, product=product)
                observations[side][product] = (quantity, price, declared)
                values.extend([quantity, price])
                if declared is not None:
                    declared_count += 1
                    values.append(declared)
        if set(observations["actual"]) != set(observations["baseline"]):
            issue("volume_mix_price_unmatched_products", "实际与基准的商品集合不一致；新旧商品不能按零数量配对。",
                  actual_only=sorted(set(observations["actual"]) - set(observations["baseline"]), key=repr),
                  baseline_only=sorted(set(observations["baseline"]) - set(observations["actual"]), key=repr))
        if not _explicit_zero_actual_volume(observations):
            for product, observation in observations["actual"].items():
                if observation is not None and observation[0] == 0:
                    issue("volume_mix_price_nonpositive_quantity", "零量或负数量需单独处理，不能用于本可比篮子模型。",
                          side="actual", product=product)

        output = {
            **context, **{name: None for name in _VMP_AMOUNTS},
            "quantity_unit": quantity_unit, "source_rows": sources,
            "actual_scope": _side_scope(ordered["actual"], label=labels["actual"], filters=filters["actual"]),
            "baseline_scope": _side_scope(ordered["baseline"], label=labels["baseline"], filters=filters["baseline"]),
            "comparison_status": "incomplete", "applicability": "not_comparable",
            "amount_basis": "reported_amount" if declared_count == sum(map(len, ordered.values())) else "quantity_times_price",
        }
        # Products and their sums must remain exact even for large monetary
        # magnitudes or small quantities; division alone may be nonterminating.
        span = (max((value.adjusted() for value in values), default=0)
                - min((value.as_tuple().exponent for value in values), default=0))
        with localcontext() as ctx:
            ctx.prec = max(80, 3 * max(span, 1) + 2 * len(str(len(values))) + 8)
            for side, products in observations.items():
                for product, observation in products.items():
                    if observation is None:
                        continue
                    quantity, price, declared = observation
                    if declared is not None and quantity * price != declared:
                        issue("price_quantity_amount_mismatch", "声明金额与数量乘单价不一致，不能作为可比金额桥。",
                              side=side, product=product, declared=_text(declared), computed=_text(quantity * price))
            blocking = [code for code in reasons if code != "volume_mix_price_quantity_unit_missing"]
            if _explicit_zero_actual_volume(observations) and not blocking:
                # Money total is q×p on both sides. Actual mix is 0/0, so volume,
                # mix and price attribution stay unset rather than becoming 0.
                issue("volume_mix_price_zero_actual_volume",
                      "实际销量为零，实际结构占比和价格归因未定义；保留金额总差异，不构造单价，也不把未定义结构当成零。")
                actuals, baselines = observations["actual"], observations["baseline"]
                actual_amount = sum((q * p for q, p, _ in actuals.values()), Decimal(0))
                baseline_amount = sum((q * p for q, p, _ in baselines.values()), Decimal(0))
                output.update({
                    "actual": _text(actual_amount),
                    "baseline": _text(baseline_amount),
                    "total_variance": _text(actual_amount - baseline_amount),
                    "actual_volume": _text(sum((item[0] for item in actuals.values()), Decimal(0))),
                    "baseline_volume": _text(sum((item[0] for item in baselines.values()), Decimal(0))),
                })
                output.update(comparison_status="limited", applicability="zero_actual_volume")
            elif not reasons:
                actuals, baselines = observations["actual"], observations["baseline"]
                va = sum((item[0] for item in actuals.values()), Decimal(0))
                vb = sum((item[0] for item in baselines.values()), Decimal(0))
                actual_amount = sum((q * p for q, p, _ in actuals.values()), Decimal(0))
                baseline_amount = sum((q * p for q, p, _ in baselines.values()), Decimal(0))
                at_actual_mix = sum((actuals[product][0] * baselines[product][1] for product in actuals), Decimal(0))
                at_actual_volume = va * baseline_amount / vb
                # Use the same rounded intermediate level in both adjacent
                # differences. Increased precision makes these subtractions
                # exact; no component is adjusted using a calculated residual.
                ctx.prec *= 2
                total = actual_amount - baseline_amount
                volume = at_actual_volume - baseline_amount
                mix = at_actual_mix - at_actual_volume
                price = actual_amount - at_actual_mix
                amounts = (actual_amount, baseline_amount, total, volume, mix, price,
                           total - volume - mix - price, va, vb)
                output.update({name: _text(value) for name, value in zip(_VMP_AMOUNTS, amounts)})
                output.update(comparison_status="complete", applicability="comparable")
        if reasons:
            output["reason_codes"] = reasons
        result.append(output)
    return {
        "domain": "foundry.finance.variance.v1", "method": "volume_mix_price",
        "columns": [*dimensions, *_VMP_AMOUNTS, "quantity_unit", "amount_basis", "comparison_status", "applicability"],
        "rows": result, "diagnostics": diagnostics,
        "comparison": {"actual_scenario": labels["actual"], "baseline_scenario": labels["baseline"],
                       "actual_filters": spec.get("actual_filters", {}), "baseline_filters": spec.get("baseline_filters", {})},
        "interpretation": "同质数量单位的可比商品篮子，固定按总量、结构、价格顺序分解；算术贡献不证明业务因果。",
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
