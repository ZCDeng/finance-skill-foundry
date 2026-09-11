"""Pure finance-domain normalization for analysis snapshots."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from foundry.errors import FoundryError

CANONICAL_SCOPE = ("ledger", "organization", "period", "currency", "unit", "scenario")
TRACE_FIELDS = ("source_system", "tenant", "doc_id", "line_id", "source_status")
DOMAIN = {
    "input": "foundry.finance.dataset.v1",
    "output": "foundry.finance.normalized.v1",
    "capabilities": ["analysis"],
    "excluded_capabilities": ["posting", "payment_execution"],
}
UNIT_FACTORS = {"元": Decimal("1"), "万元": Decimal("10000")}
INACTIVE_SOURCE_STATUS = {"duplicate_pull", "deleted", "void", "voided"}
PARENT_STATUS = INACTIVE_SOURCE_STATUS


DEFAULT_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "ledger": ("ledger", "ledger_id", "账套"),
    "organization": ("organization", "organization_id", "org", "组织"),
    "period": ("period", "会计期间", "期间"),
    "currency": ("currency", "原币", "币种"),
    "unit": ("unit", "金额单位", "单位"),
    "scenario": ("scenario", "version", "口径"),
    "account_code": ("account_code", "科目编码"),
    "account_name": ("account_name", "科目名称"),
    "account_direction": ("account_direction", "余额方向"),
    "management_account": ("management_account", "管理科目"),
    "amount": ("amount", "金额"),
    "dc_flag": ("dc_flag", "借贷"),
    "line_type": ("line_type", "行类型"),
    "posting_status": ("posting_status", "过账状态"),
    "source_row": ("source_row", "source_row_number", "source_row_index", "来源行"),
    "doc_id": ("doc_id", "document_id", "voucher_id", "单据ID", "凭证号"),
    "line_id": ("line_id", "document_line_id", "voucher_line_id", "行ID"),
    "source_status": ("source_status", "_source_row_state", "status"),
    "aux_customer": ("aux_customer", "customer", "客户"),
    "aux_department": ("aux_department", "department", "部门"),
}


def normalize_finance_dataset(
    dataset: dict,
    scope: dict,
    account_map: dict | list[dict] | None = None,
    policy: dict | None = None,
) -> dict:
    """Return normalized finance facts plus diagnostics and control totals.

    The function is intentionally side-effect free.  Parent services own source
    loading, mapping-version persistence, and manager approval flows.
    """

    policy = policy or {}
    field_map = _field_map(policy)
    diagnostics: list[dict] = []
    rows = dataset.get("rows") or []
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return _result(
            dataset,
            scope,
            [],
            diagnostics
            + [
                _diag(
                    "error", "invalid_dataset", "dataset rows must be a list of objects"
                )
            ],
        )

    mapping, mapping_version = _compile_account_map(account_map, policy, diagnostics)
    target_unit = str(policy.get("target_unit") or scope.get("unit") or "").strip()
    amount_sign = str(policy.get("amount_sign") or "natural").strip()
    normalized: list[dict] = []

    for index, raw in enumerate(rows, start=1):
        canonical = {name: _read(raw, field_map, name) for name in field_map}
        canonical = _with_scalar_scope_defaults(canonical, scope)
        if not _in_scope(canonical, scope):
            continue
        source_status = _source_status(raw, canonical)
        source_row = _physical_source_row(dataset, canonical.get("source_row"), index)
        locator = _row_locator(dataset, source_row)
        source_ref = {
            "dataset_id": str(dataset.get("id") or dataset.get("dataset_id") or ""),
            "row_index": index,
            "source_row": source_row,
            **({"source_locator": locator} if locator else {}),
        }
        if _inactive_source_status(source_status):
            diagnostics.append(
                _diag(
                    "info",
                    "inactive_source_row",
                    "inactive source row is preserved in normalized output but excluded from totals and metrics",
                    row_ref=source_ref,
                )
            )
        for amount, measure_account in _expanded_amounts(
            raw, canonical, diagnostics, index
        ):
            source_unit = str(canonical.get("unit") or scope.get("unit") or "").strip()
            output_unit = target_unit or source_unit
            converted = _convert_unit(
                amount, source_unit, output_unit, diagnostics, index
            )
            if converted is None:
                continue

            account_code = _text(canonical.get("account_code"))
            account_direction = _norm_direction(canonical.get("account_direction"))
            dc_flag = _norm_direction(canonical.get("dc_flag"))
            management = measure_account or _management_account(
                account_code,
                _text(canonical.get("management_account")),
                mapping,
                diagnostics,
                index,
            )
            posting_status = _text(canonical.get("posting_status")) or "posted"
            debit_positive = (
                converted
                if amount_sign == "debit_positive"
                else _debit_positive(converted, dc_flag, account_direction)
            )
            aux = _auxiliaries(raw, canonical)
            for aux_name, aux_values in aux.items():
                if len(aux_values) > 1:
                    diagnostics.append(
                        _diag(
                            "info",
                            "multi_valued_auxiliary",
                            f"auxiliary {aux_name} has multiple values",
                            row_ref={
                                "dataset_id": str(
                                    dataset.get("id") or dataset.get("dataset_id") or ""
                                ),
                                "row_index": index,
                                "source_row": source_row,
                            },
                        )
                    )
            row = {
                "domain": "finance.fact.v1",
                "dataset_id": str(dataset.get("id") or dataset.get("dataset_id") or ""),
                "source_row": source_row,
                "source": source_ref,
                **({"source_locator": locator} if locator else {}),
                "ledger": _text(canonical.get("ledger")),
                "organization": _text(canonical.get("organization")),
                "period": _text(canonical.get("period")),
                "currency": _text(canonical.get("currency")),
                "unit": output_unit,
                "scenario": _text(canonical.get("scenario"))
                or _text(scope.get("scenario")),
                "account_code": account_code,
                "account_name": _text(canonical.get("account_name")),
                "account_direction": account_direction,
                "management_account": management,
                "line_type": _text(canonical.get("line_type")) or "fact",
                "amount": _money(converted),
                "original_amount": _money(amount),
                "original_unit": source_unit,
                "debit_credit": dc_flag,
                "signed_amount": _money(debit_positive),
                "posting_status": posting_status,
                "source_status": source_status or "active",
                "auxiliaries": aux,
                "drilldown_available": bool(
                    _text(canonical.get("doc_id")) and _text(canonical.get("line_id"))
                ),
                "trace": {
                    name: _text(
                        canonical.get(name) if name in canonical else raw.get(name)
                    )
                    for name in TRACE_FIELDS
                    if (canonical.get(name) if name in canonical else raw.get(name))
                    not in (None, "")
                },
                "policies": {
                    "amount_sign": amount_sign,
                    "unit_conversion": f"{source_unit or '(blank)'}->{output_unit or '(blank)'}",
                    "account_map_version": mapping_version,
                },
            }
            if not row["drilldown_available"]:
                diagnostics.append(
                    _diag(
                        "info",
                        "voucher_detail_unavailable",
                        "row is usable for balance-level analysis but has no voucher drilldown key",
                        row_ref=row["source"],
                    )
                )
            normalized.append(row)

    _scope_currency_unit_diagnostics(normalized, scope, policy, diagnostics)
    _special_row_diagnostics(normalized, policy, diagnostics)
    movement_checks = _movement_checks(normalized, policy, diagnostics)
    control_totals = _control_totals(normalized)
    return _result(
        dataset,
        scope,
        normalized,
        diagnostics,
        control_totals=control_totals,
        movement_checks=movement_checks,
        mapping_version=mapping_version,
    )


def scoped_source_rows(
    dataset: dict, scope: dict, policy: dict | None = None
) -> list[dict]:
    """Return raw rows that share finance scope semantics without amount expansion.

    This is for services that need source-shaped fields such as price, quantity,
    date, and original identifiers. It adds canonical aliases and stable source
    references, filters inactive source-refresh rows, and refuses unit relabeling
    because this helper does not perform amount conversion.
    """

    policy = policy or {}
    field_map = _field_map(policy)
    rows = dataset.get("rows") or []
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise FoundryError("dataset rows must be a list of objects")

    dataset_id = str(dataset.get("id") or dataset.get("dataset_id") or "")
    scoped: list[dict] = []
    for index, raw in enumerate(rows, start=1):
        canonical = {name: _read(raw, field_map, name) for name in field_map}
        canonical = _with_scalar_scope_defaults(canonical, scope)
        if not _in_scope(canonical, scope):
            continue
        _refuse_unit_relabel(canonical, scope)
        source_status = _source_status(raw, canonical)
        if _inactive_source_status(source_status):
            continue
        source_row = _source_row(canonical.get("source_row"), index)
        row = dict(raw)
        for name, value in canonical.items():
            if value not in (None, ""):
                row[name] = value
        row["source_status"] = source_status or "active"
        row["source"] = {
            "dataset_id": dataset_id,
            "row_index": index,
            "source_row": source_row,
        }
        scoped.append(row)
    return scoped


def _result(
    dataset: dict,
    scope: dict,
    rows: list[dict],
    diagnostics: list[dict],
    *,
    control_totals: list[dict] | None = None,
    movement_checks: list[dict] | None = None,
    mapping_version: str | None = None,
) -> dict:
    return {
        "domain": DOMAIN,
        "dataset_id": str(dataset.get("id") or dataset.get("dataset_id") or ""),
        "scope": {
            name: scope.get(name)
            for name in CANONICAL_SCOPE
            if scope.get(name) not in (None, "")
        },
        "provenance": {
            "source_dataset_id": str(
                dataset.get("id") or dataset.get("dataset_id") or ""
            ),
            "source_name": dataset.get("source_name") or dataset.get("name"),
            "source_hash": dataset.get("source_hash"),
            "data_hash": dataset.get("data_hash"),
            "metadata": dataset.get("metadata") or {},
            "account_map_version": mapping_version,
        },
        "rows": rows,
        "diagnostics": _bounded_diagnostics(diagnostics),
        "control_totals": control_totals or [],
        "movement_checks": movement_checks or [],
    }


def _field_map(policy: dict) -> dict[str, tuple[str, ...]]:
    overrides = policy.get("field_map") or policy.get("source_mappings") or {}
    merged: dict[str, tuple[str, ...]] = dict(DEFAULT_FIELD_MAP)
    if isinstance(overrides, dict):
        for canonical, names in overrides.items():
            if isinstance(names, str):
                merged[str(canonical)] = (names, *merged.get(str(canonical), ()))
            elif isinstance(names, (list, tuple)):
                merged[str(canonical)] = tuple(
                    str(name) for name in names
                ) + merged.get(str(canonical), ())
    return merged


def _read(row: dict, field_map: dict[str, tuple[str, ...]], name: str) -> Any:
    for candidate in field_map.get(name, (name,)):
        if candidate in row:
            return row.get(candidate)
    return None


def _with_scalar_scope_defaults(canonical: dict, scope: dict) -> dict:
    merged = dict(canonical)
    for key in CANONICAL_SCOPE:
        expected = scope.get(key)
        if isinstance(expected, (list, tuple, set, frozenset)):
            continue
        if expected in (None, ""):
            continue
        if merged.get(key) in (None, ""):
            merged[key] = expected
    return merged


def _source_status(raw: dict, canonical: dict) -> str:
    if raw.get("deleted") is True:
        return "deleted"
    if raw.get("void") is True or raw.get("voided") is True:
        return "voided"
    return _text(
        canonical.get("source_status")
        or raw.get("source_status")
        or raw.get("_source_row_state")
        or raw.get("status")
    ).casefold()


def _inactive_source_status(status: Any) -> bool:
    return _text(status).casefold() in INACTIVE_SOURCE_STATUS


def _refuse_unit_relabel(canonical: dict, scope: dict) -> None:
    expected = scope.get("unit")
    if isinstance(expected, (list, tuple, set, frozenset)) or expected in (None, ""):
        return
    actual = _text(canonical.get("unit"))
    if actual and actual != str(expected):
        raise FoundryError(
            "scoped_source_rows requires explicit conversion before changing unit labels"
        )


def _in_scope(row: dict, scope: dict) -> bool:
    for key in CANONICAL_SCOPE:
        expected = scope.get(key)
        if expected in (None, "", [], ()):
            continue
        actual = _text(row.get(key))
        if key == "unit" and actual != str(expected):
            if actual in UNIT_FACTORS and str(expected) in UNIT_FACTORS:
                continue
        if isinstance(expected, (list, tuple, set, frozenset)):
            if actual not in {str(item) for item in expected}:
                return False
        elif actual and actual != str(expected):
            return False
    return True


def _bounded_diagnostics(diagnostics: list[dict], sample_limit: int = 5) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    passthrough: list[dict] = []
    for diagnostic in diagnostics:
        if "row_ref" not in diagnostic:
            passthrough.append(diagnostic)
            continue
        key = (
            str(diagnostic.get("severity") or ""),
            str(diagnostic.get("code") or ""),
            str(diagnostic.get("message") or ""),
        )
        grouped[key].append(diagnostic)

    compacted: list[dict] = list(passthrough)
    for (severity, code, message), items in grouped.items():
        if len(items) <= sample_limit:
            compacted.extend(items)
            continue
        compacted.append(
            {
                "severity": severity,
                "code": code,
                "message": message,
                "count": len(items),
                "sample_row_refs": [
                    item["row_ref"]
                    for item in items[:sample_limit]
                    if "row_ref" in item
                ],
            }
        )
    return compacted


def _compile_account_map(
    account_map: dict | list[dict] | None, policy: dict, diagnostics: list[dict]
) -> tuple[dict[str, str], str | None]:
    version = None
    rows: list[dict] = []
    if isinstance(account_map, dict):
        version = _text(account_map.get("version") or account_map.get("id"))
        if isinstance(account_map.get("rows"), list):
            rows = [row for row in account_map["rows"] if isinstance(row, dict)]
        else:
            rows = [
                {"account_code": key, "management_account": value}
                for key, value in account_map.items()
                if key not in {"version", "id", "rows"}
            ]
    elif isinstance(account_map, list):
        rows = [row for row in account_map if isinstance(row, dict)]
    manager = policy.get("manager_mappings") or {}
    if not isinstance(manager, dict):
        manager = {}
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        code = _text(row.get("account_code") or row.get("source_account_code"))
        target = _text(row.get("management_account") or row.get("analysis_node_id"))
        if code and target and target not in grouped[code]:
            grouped[code].append(target)
    mapping: dict[str, str] = {}
    for code, targets in grouped.items():
        selected = _text(manager.get(code))
        if len(targets) > 1:
            diagnostics.append(
                _diag(
                    "warning",
                    "duplicate_mapping",
                    f"account {code} maps to {', '.join(targets)}",
                )
            )
        if selected:
            mapping[code] = selected
            continue
        if len(targets) == 1:
            mapping[code] = targets[0]
        else:
            continue
    codes = sorted(grouped, key=len)
    for index, parent in enumerate(codes):
        for child in codes[index + 1 :]:
            if child.startswith(parent) and child != parent:
                diagnostics.append(
                    _diag(
                        "warning",
                        "parent_child_overlap",
                        f"account map contains parent {parent} and child {child}",
                    )
                )
    return mapping, version


def _management_account(
    account_code: str,
    source_management: str,
    mapping: dict[str, str],
    diagnostics: list[dict],
    index: int,
) -> str:
    if account_code and account_code in mapping:
        return mapping[account_code]
    if source_management:
        return source_management
    if account_code:
        diagnostics.append(
            _diag(
                "warning",
                "unmapped_account",
                f"account {account_code} is not mapped",
                row_index=index,
            )
        )
    return "__unmapped__"


def _decimal(value: Any, diagnostics: list[dict], index: int) -> Decimal | None:
    try:
        if isinstance(value, bool) or value in (None, ""):
            raise InvalidOperation
        return value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        diagnostics.append(
            _diag(
                "error",
                "invalid_amount",
                "amount is not a finite decimal",
                row_index=index,
            )
        )
        return None


def _expanded_amounts(
    raw: dict, canonical: dict, diagnostics: list[dict], index: int
) -> list[tuple[Decimal, str]]:
    amount = _decimal(canonical.get("amount"), diagnostics, index)
    if amount is not None:
        return [(amount, "")]
    if canonical.get("amount") not in (None, ""):
        return []
    diagnostics[:] = [
        diag
        for diag in diagnostics
        if not (diag.get("code") == "invalid_amount" and diag.get("row_index") == index)
    ]
    expanded: list[tuple[Decimal, str]] = []
    for account in ("revenue", "cost", "expense"):
        if raw.get(account) in (None, ""):
            continue
        value = _decimal(raw.get(account), diagnostics, index)
        if value is not None:
            expanded.append((value, account))
    if not expanded:
        diagnostics.append(
            _diag(
                "error",
                "missing_amount",
                "row has no amount or supported wide finance measure",
                row_index=index,
            )
        )
    return expanded


def _convert_unit(
    amount: Decimal,
    source_unit: str,
    target_unit: str,
    diagnostics: list[dict],
    index: int,
) -> Decimal | None:
    if not target_unit or not source_unit or source_unit == target_unit:
        return amount
    if source_unit not in UNIT_FACTORS or target_unit not in UNIT_FACTORS:
        diagnostics.append(
            _diag(
                "error",
                "unsupported_unit_conversion",
                f"cannot convert {source_unit} to {target_unit}",
                row_index=index,
            )
        )
        return None
    return amount * UNIT_FACTORS[source_unit] / UNIT_FACTORS[target_unit]


def _debit_positive(amount: Decimal, dc_flag: str, account_direction: str) -> Decimal:
    direction = dc_flag or account_direction
    return -amount if direction == "credit" else amount



def _physical_source_row(dataset: dict, declared: Any, index: int) -> int:
    if declared not in (None, ""):
        return _source_row(declared, index)
    numbers = (dataset.get("transformation") or {}).get("source_row_numbers")
    if isinstance(numbers, list) and 0 <= index - 1 < len(numbers):
        return _source_row(numbers[index - 1], index)
    return _source_row(declared, index)


def _row_locator(dataset: dict, source_row: int) -> dict:
    from foundry.finance_locators import build_source_locator

    return build_source_locator(dataset, source_row)


def _source_row(value: Any, index: int) -> int:
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return index


def _scope_currency_unit_diagnostics(
    rows: list[dict], scope: dict, policy: dict, diagnostics: list[dict]
) -> None:
    currencies = {row["currency"] for row in rows if row["currency"]}
    units = {row["unit"] for row in rows if row["unit"]}
    if (
        len(currencies) > 1
        and not scope.get("currency")
        and not policy.get("allow_mixed_currencies")
    ):
        diagnostics.append(
            _diag(
                "error",
                "mixed_currency",
                f"scope contains multiple currencies: {', '.join(sorted(currencies))}",
            )
        )
    if len(units) > 1 and not scope.get("unit") and not policy.get("allow_mixed_units"):
        diagnostics.append(
            _diag(
                "error",
                "mixed_unit",
                f"scope contains multiple units: {', '.join(sorted(units))}",
            )
        )


def _special_row_diagnostics(
    rows: list[dict], policy: dict, diagnostics: list[dict]
) -> None:
    declared = policy.get("movement_policies") or {}
    for row in rows:
        line_type = row["line_type"]
        if line_type in {"red_letter", "closing_transfer", "adjustment_period"}:
            diagnostics.append(
                _diag(
                    "info",
                    f"{line_type}_policy",
                    f"{line_type} row follows declared policy: {declared.get(line_type, 'preserve')}",
                    row_ref=row["source"],
                )
            )
        if row["posting_status"] != "posted":
            diagnostics.append(
                _diag(
                    "warning",
                    "unposted_row",
                    "unposted row excluded from complete movement checks by default",
                    row_ref=row["source"],
                )
            )


def _movement_checks(
    rows: list[dict], policy: dict, diagnostics: list[dict]
) -> list[dict]:
    include_unposted = bool(policy.get("include_unposted"))
    checks: list[dict] = []
    groups: dict[tuple[str, str, str, str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if _inactive_source_status(row["source_status"]):
            continue
        groups[
            (
                row["ledger"],
                row["organization"],
                row["period"],
                row["currency"],
                row["unit"],
                row["account_code"],
            )
        ].append(row)
    for key, group in groups.items():
        relevant = [
            row
            for row in group
            if include_unposted or row["posting_status"] == "posted"
        ]
        by_type: dict[str, list[dict]] = defaultdict(list)
        for row in relevant:
            by_type[row["line_type"]].append(row)
        if not {"opening", "ending", "period_activity"} <= set(by_type):
            if any(
                row["line_type"] in {"opening", "ending", "period_activity"}
                for row in group
            ):
                diagnostics.append(
                    _diag(
                        "info",
                        "movement_check_incomplete",
                        f"movement check incomplete for account {key[-1]}",
                    )
                )
            continue
        opening = sum(
            (_as_decimal(row["signed_amount"]) for row in by_type["opening"]),
            Decimal("0"),
        )
        activity = sum(
            (_as_decimal(row["signed_amount"]) for row in by_type["period_activity"]),
            Decimal("0"),
        )
        ending = sum(
            (_as_decimal(row["signed_amount"]) for row in by_type["ending"]),
            Decimal("0"),
        )
        status = "passed" if opening + activity == ending else "failed"
        check = {
            "ledger": key[0],
            "organization": key[1],
            "period": key[2],
            "currency": key[3],
            "unit": key[4],
            "account_code": key[5],
            "opening": _money(opening),
            "activity": _money(activity),
            "expected_ending": _money(opening + activity),
            "ending": _money(ending),
            "status": status,
            "source_rows": [row["source"] for row in relevant],
        }
        checks.append(check)
        if status == "failed":
            diagnostics.append(
                _diag(
                    "warning",
                    "movement_check_failed",
                    f"movement check failed for account {key[-1]}",
                )
            )
    return checks


def _control_totals(rows: list[dict]) -> list[dict]:
    totals: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        if _inactive_source_status(row["source_status"]):
            continue
        key = tuple(
            str(row.get(name) or "")
            for name in (*CANONICAL_SCOPE, "management_account")
        )
        item = totals.setdefault(
            key,
            {
                **{name: row.get(name) for name in CANONICAL_SCOPE},
                "management_account": row.get("management_account"),
                "amount": Decimal("0"),
                "signed_amount": Decimal("0"),
                "row_count": 0,
                "source_rows": [],
            },
        )
        item["amount"] += _as_decimal(row["amount"])
        item["signed_amount"] += _as_decimal(row["signed_amount"])
        item["row_count"] += 1
        item["source_rows"].append(row["source"])
    return [
        {
            **{k: v for k, v in item.items() if k not in {"amount", "signed_amount"}},
            "amount": _money(item["amount"]),
            "signed_amount": _money(item["signed_amount"]),
        }
        for item in sorted(
            totals.values(),
            key=lambda value: tuple(
                str(value.get(name) or "")
                for name in (*CANONICAL_SCOPE, "management_account")
            ),
        )
    ]


def _auxiliaries(raw: dict, canonical: dict) -> dict[str, list[str]]:
    aux: dict[str, list[str]] = {}
    for key, value in {**raw, **canonical}.items():
        if not str(key).startswith("aux_") or value in (None, ""):
            continue
        values = [
            part.strip()
            for part in str(value).replace("；", ";").replace("|", ";").split(";")
            if part.strip()
        ]
        aux[str(key)[4:]] = values
    return aux


def _norm_direction(value: Any) -> str:
    text = _text(value).casefold()
    if text in {"credit", "贷", "cr", "c"}:
        return "credit"
    if text in {"debit", "借", "dr", "d"}:
        return "debit"
    return text


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _money(value: Decimal) -> str:
    return format(value, "f")


def _diag(severity: str, code: str, message: str, **extra: Any) -> dict:
    return {"severity": severity, "code": code, "message": message, **extra}
