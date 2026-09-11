"""Read-only readiness projection over already authorized finance datasets."""

from __future__ import annotations

import re
from typing import Any

from foundry.analysis import _hash_bytes
from foundry.analysis_data import parse_source
from foundry.errors import FoundryError
from foundry.finance_model import (
    DEFAULT_FIELD_MAP,
    _diag,
    _field_map,
    _read,
)

PNL_ACCOUNTS = frozenset({"revenue", "cost", "expense"})
SCOPE_KEYS = ("ledger", "organization", "period", "currency", "unit")
CAPABILITY_ORDER = (
    "management_pnl",
    "control_totals",
    "reconciliation",
    "receivables_aging",
    "cash_13_weeks",
)
ERP_HEADER_MARKERS = frozenset(
    {"科目名称", "科目编码", "借方", "贷方", "凭证字", "凭证号", "会计科目", "对方科目"}
)
ERP_TITLE_MARKERS = ("金蝶", "用友", "KIS", "U8")
_PERIOD_IN_TITLE = re.compile(r"(20\d{2})[-./年](\d{1,2})")
_CURRENCY_IN_TITLE = re.compile(r"(?:币种|原币)[:：\s]*([A-Za-z]{3}|人民币)")
_PATH_RE = re.compile(r"(?i)(/Users/|/home/|[A-Z]:\\|\\\\|file://|\.xlsx|\.csv)")
_URL_RE = re.compile(r"(?i)https?://|wss?://")
_HOST_RE = re.compile(r"(?i)\b(?:localhost|\d{1,3}(?:\.\d{1,3}){3}|[a-z0-9-]+(?:\.[a-z0-9-]+)+)\b")
_FORBIDDEN_SCOPE = frozenset({"本月", "CNY"})
AMOUNT_EXTRA = ("借方", "贷方")


def build_readiness_report(store, spec: dict | None = None) -> dict[str, Any]:
    del spec
    datasets = _authorized_tables(store)
    if not datasets:
        return _sanitize(
            {
                "proposed_scope": {key: "" for key in SCOPE_KEYS},
                "can_run": [],
                "blocked": [
                    {
                        "capability": "management_pnl",
                        "missing_fields": ["dataset"],
                        "reason": "no_dataset",
                    }
                ],
                "file_identity_policy": "snapshot_only",
                "diagnostics": [
                    _diag("error", "no_dataset", "no authorized finance dataset")
                ],
                "erp_connected": False,
                "sheet_candidates": [],
                "merged_sheets": False,
            }
        )

    probes: list[dict[str, Any]] = []
    sheet_candidates: list[dict[str, Any]] = []
    diagnostics: list[dict] = []
    for dataset in datasets:
        probes.extend(_probes_for_dataset(store, dataset, sheet_candidates, diagnostics))

    proposed_scope = _proposed_scope(probes)
    mapped_accounts = _management_accounts(store, probes)
    period = proposed_scope.get("period") or ""
    currency = proposed_scope.get("currency") or ""
    identity_failed = any(
        probe.get("identity_attempted") and not probe.get("identity_ok") for probe in probes
    )
    mapping_complete = PNL_ACCOUNTS <= mapped_accounts
    has_amount = any(_has_amount(probe) for probe in probes)
    has_rows = any(probe.get("rows") for probe in probes)

    can_run: list[str] = []
    blocked: list[dict[str, Any]] = []

    missing_scope = [key for key in ("period", "currency") if not proposed_scope.get(key)]
    pnl_missing = list(missing_scope)
    if not mapping_complete:
        pnl_missing.append("management_account")

    if identity_failed:
        blocked.append(
            {
                "capability": "management_pnl",
                "missing_fields": missing_scope or ["period", "currency"],
                "reason": "identity_failed",
            }
        )
        diagnostics.append(
            _diag("error", "identity_failed", "header identity did not declare period and currency")
        )
    elif missing_scope:
        blocked.append(
            {
                "capability": "management_pnl",
                "missing_fields": missing_scope,
                "reason": "missing_scope",
            }
        )
        diagnostics.append(_diag("error", "missing_scope", "period or currency is not declared"))
    elif any(_pnl_sheet_ready(store, probe) for probe in probes):
        can_run.append("management_pnl")
    elif not mapping_complete:
        blocked.append(
            {
                "capability": "management_pnl",
                "missing_fields": ["management_account"],
                "reason": "mapping_incomplete",
            }
        )
        diagnostics.append(
            _diag("error", "mapping_incomplete", "management accounts are not fully mapped")
        )
    else:
        blocked.append(
            {
                "capability": "management_pnl",
                "missing_fields": ["management_account"],
                "reason": "mapping_incomplete",
            }
        )
        diagnostics.append(
            _diag("error", "mapping_incomplete", "management accounts are not fully mapped on one sheet")
        )

    if missing_scope:
        blocked.append(
            {
                "capability": "control_totals",
                "missing_fields": missing_scope,
                "reason": "missing_scope",
            }
        )
    elif has_amount and has_rows:
        can_run.append("control_totals")

    if _aging_ready(probes) and not missing_scope:
        can_run.append("receivables_aging")

    policy = (
        "business_key"
        if probes and all(_has_business_keys(probe) for probe in probes if probe.get("rows"))
        else "snapshot_only"
    )
    report = {
        "proposed_scope": proposed_scope,
        "can_run": [name for name in CAPABILITY_ORDER if name in can_run],
        "blocked": blocked,
        "file_identity_policy": policy,
        "diagnostics": diagnostics,
        "erp_connected": False,
        "sheet_candidates": sheet_candidates,
        "merged_sheets": False,
    }
    del pnl_missing
    return _sanitize(report)


def _authorized_tables(store) -> list[dict]:
    state = store.analysis.state()
    records = [
        row
        for row in state["datasets"]
        if store.allowed is None or row["id"] in store.allowed
    ]
    tables = []
    for record in records:
        dataset = store.analysis.read_dataset(record["id"])
        if dataset.get("kind") == "background":
            continue
        tables.append(dataset)
    return tables


def _probes_for_dataset(
    store,
    dataset: dict,
    sheet_candidates: list[dict[str, Any]],
    diagnostics: list[dict],
) -> list[dict[str, Any]]:
    if _is_workbook_shell(dataset):
        return _workbook_probes(store, dataset, sheet_candidates, diagnostics)
    rows = list(dataset.get("rows") or [])
    headers = _headers_of(dataset, rows)
    return [_probe(headers, rows, sheet=str(dataset.get("transformation", {}).get("sheet") or ""))]


def _is_workbook_shell(dataset: dict) -> bool:
    if dataset.get("source_file") != "source.xlsx":
        return False
    if dataset.get("kind") == "workbook":
        return True
    return not dataset.get("rows") and bool((dataset.get("workbook") or {}).get("sheets"))


def _workbook_probes(
    store,
    dataset: dict,
    sheet_candidates: list[dict[str, Any]],
    diagnostics: list[dict],
) -> list[dict[str, Any]]:
    try:
        data = _source_bytes(store, dataset)
        directory = parse_source(data, ".xlsx", {"mode": "workbook"})
    except FoundryError:
        diagnostics.append(_diag("error", "parse_failed", "workbook could not be inspected"))
        return [_probe([], [], sheet="")]

    names = [str(item.get("name") or "") for item in (directory.get("workbook") or {}).get("sheets") or []]
    probes: list[dict[str, Any]] = []
    for name in names:
        try:
            parsed = parse_source(data, ".xlsx", {"sheet": name, "mode": "table"})
        except FoundryError:
            sheet_candidates.append({"sheet": name, "mappable": False})
            diagnostics.append(_diag("warning", "parse_failed", "worksheet could not be parsed"))
            continue
        rows = list(parsed.get("rows") or [])
        headers = _headers_of(parsed, rows)
        probe = _probe(headers, rows, sheet=name)
        probes.append(probe)
        sheet_candidates.append({"sheet": name, "mappable": _pnl_sheet_ready(store, probe)})
    if not probes:
        probes.append(_probe([], [], sheet=""))
    return probes


def _source_bytes(store, dataset: dict) -> bytes:
    folder = store.analysis._inside(store.analysis.root / "datasets" / dataset["id"])
    data = (folder / dataset["source_file"]).read_bytes()
    if _hash_bytes(data) != dataset["source_hash"]:
        raise FoundryError("dataset integrity check failed")
    return data


def _headers_of(dataset: dict, rows: list[dict]) -> list[str]:
    schema = dataset.get("schema") or []
    names = []
    for column in schema:
        if isinstance(column, dict) and column.get("name"):
            names.append(str(column["name"]))
        elif isinstance(column, str) and column:
            names.append(column)
    if names:
        return names
    if rows:
        return [str(key) for key in rows[0].keys()]
    return []


def _probe(headers: list[str], rows: list[dict], *, sheet: str) -> dict[str, Any]:
    fmap = _field_map({})
    period_values = _declared_values(rows, fmap, "period")
    currency_values = _declared_values(rows, fmap, "currency")
    title = _title_blob(headers, rows)
    extracted_period = _period_from_title(title)
    extracted_currency = _currency_from_title(title)
    attempted = _identity_attempted(headers, title)
    period = _first(period_values) or extracted_period
    currency = _first(currency_values) or extracted_currency
    identity_ok = bool(period and currency)
    return {
        "sheet": sheet,
        "headers": headers,
        "rows": rows,
        "period": period if period not in _FORBIDDEN_SCOPE else period,
        "currency": currency,
        "ledger": _first(_declared_values(rows, fmap, "ledger")),
        "organization": _first(_declared_values(rows, fmap, "organization")),
        "unit": _first(_declared_values(rows, fmap, "unit")),
        "identity_attempted": attempted,
        "identity_ok": identity_ok if attempted else True,
        "doc_id": bool(_declared_values(rows, fmap, "doc_id")),
        "line_id": bool(_declared_values(rows, fmap, "line_id")),
        "due_date": any(str(row.get("due_date") or "").strip() for row in rows),
        "management_accounts": {
            value for value in _declared_values(rows, fmap, "management_account") if value
        },
        "account_codes": {
            value for value in _declared_values(rows, fmap, "account_code") if value
        },
        "has_amount": _headers_include(headers, "amount")
        or any(name in headers for name in AMOUNT_EXTRA),
    }


def _identity_attempted(headers: list[str], title: str) -> bool:
    if any(header in ERP_HEADER_MARKERS for header in headers):
        return True
    return any(marker in title for marker in ERP_TITLE_MARKERS)


def _title_blob(headers: list[str], rows: list[dict]) -> str:
    parts = list(headers)
    if rows:
        parts.extend(str(value) for value in rows[0].values() if value is not None)
    return " ".join(parts)


def _period_from_title(title: str) -> str:
    match = _PERIOD_IN_TITLE.search(title)
    if not match:
        return ""
    return f"{match.group(1)}-{int(match.group(2)):02d}"


def _currency_from_title(title: str) -> str:
    match = _CURRENCY_IN_TITLE.search(title)
    if match:
        return match.group(1)
    if "人民币" in title:
        return "人民币"
    return ""


def _declared_values(rows: list[dict], fmap: dict, canonical: str) -> list[str]:
    values: list[str] = []
    for row in rows:
        raw = _read(row, fmap, canonical)
        text = str(raw).strip() if raw is not None else ""
        if text and text not in values:
            if canonical in {"period", "currency"} and text in _FORBIDDEN_SCOPE and canonical == "period":
                continue
            values.append(text)
    return values


def _first(values: list[str]) -> str:
    return values[0] if values else ""


def _headers_include(headers: list[str], canonical: str) -> bool:
    aliases = {name.casefold() for name in DEFAULT_FIELD_MAP.get(canonical, (canonical,))}
    return any(header.casefold() in aliases for header in headers)


def _proposed_scope(probes: list[dict[str, Any]]) -> dict[str, str]:
    scope = {key: "" for key in SCOPE_KEYS}
    for key in SCOPE_KEYS:
        found: list[str] = []
        for probe in probes:
            value = str(probe.get(key) or "").strip()
            if key == "period" and value == "本月":
                continue
            if not value or value in found:
                continue
            found.append(value)
        scope[key] = ",".join(found)
    return scope


def _management_accounts(store, probes: list[dict[str, Any]]) -> set[str]:
    accounts: set[str] = set()
    codes: set[str] = set()
    for probe in probes:
        accounts.update(probe.get("management_accounts") or ())
        codes.update(probe.get("account_codes") or ())
    for record in store._list("account_maps"):
        for item in record.get("rows") or []:
            code = str(item.get("account_code") or "").strip()
            account = str(item.get("management_account") or "").strip()
            if code in codes and account:
                accounts.add(account)
    return accounts


def _accounts_for_probe(store, probe: dict[str, Any]) -> set[str]:
    accounts = {value for value in (probe.get("management_accounts") or ()) if value}
    codes = {value for value in (probe.get("account_codes") or ()) if value}
    for record in store._list("account_maps"):
        for item in record.get("rows") or []:
            code = str(item.get("account_code") or "").strip()
            account = str(item.get("management_account") or "").strip()
            if code in codes and account:
                accounts.add(account)
    return accounts


def _pnl_sheet_ready(store, probe: dict[str, Any]) -> bool:
    if not probe.get("rows"):
        return False
    return bool(
        probe.get("period")
        and probe.get("currency")
        and PNL_ACCOUNTS <= _accounts_for_probe(store, probe)
    )


def _sheet_mappable(probe: dict[str, Any]) -> bool:
    return bool(
        probe.get("period")
        and probe.get("currency")
        and PNL_ACCOUNTS <= set(probe.get("management_accounts") or ())
    )


def _has_amount(probe: dict[str, Any]) -> bool:
    return bool(probe.get("has_amount"))


def _has_business_keys(probe: dict[str, Any]) -> bool:
    return bool(probe.get("doc_id") and probe.get("line_id"))


def _aging_ready(probes: list[dict[str, Any]]) -> bool:
    return any(
        probe.get("due_date") and (probe.get("has_amount") or "accounts_receivable" in (probe.get("management_accounts") or ()))
        for probe in probes
    )


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        if _URL_RE.search(value) or (_PATH_RE.search(value) and "/" in value):
            return "[redacted]"
        if _HOST_RE.search(value) and "." in value and " " not in value:
            return "[redacted]"
        for marker in ERP_TITLE_MARKERS:
            if marker in value:
                value = value.replace(marker, "")
        return value
    return value
