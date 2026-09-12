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
_UNIT_IN_TITLE = re.compile(r"(?:金额)?单位[:：\s]*([万亿]?元)")
# Diagnostics are fixed finance_model codes and text; this only guards against a
# path, URL, or host slipping into the message text. Business values in
# proposed_scope and sheet_candidates are never rewritten.
_LEAK_RE = re.compile(r"(?i)(/Users/|/home/|/tmp/|[A-Z]:\\|\\\\|file://|https?://|wss?://|localhost|\d{1,3}(?:\.\d{1,3}){3})")
SILENT_PERIOD = "本月"
AMOUNT_EXTRA = ("借方", "贷方")


def build_readiness_report(store, spec: dict | None = None) -> dict[str, Any]:
    del spec
    diagnostics: list[dict] = []
    datasets, structure_states, pending = _authorized_tables(store, diagnostics)
    if pending:
        # A file whose table structure nobody has confirmed cannot answer for a
        # number yet, and saying "missing currency" about it would be a guess.
        return _report(
            proposed_scope={key: "" for key in SCOPE_KEYS},
            can_run=[],
            blocked=[_blocked("management_pnl", ["table_structure"], "pending_structure")],
            policy="snapshot_only",
            diagnostics=[
                *diagnostics,
                _diag(
                    "error",
                    "pending_structure",
                    "table structure is waiting for the manager's confirmation",
                ),
            ],
            sheet_candidates=[],
            structure_states=structure_states,
        )
    if not datasets:
        return _report(
            proposed_scope={key: "" for key in SCOPE_KEYS},
            can_run=[],
            blocked=[_blocked("management_pnl", ["dataset"], "no_dataset")],
            policy="snapshot_only",
            diagnostics=[*diagnostics, _diag("error", "no_dataset", "no authorized finance dataset")],
            sheet_candidates=[],
            structure_states=structure_states,
        )

    code_map = _account_code_map(store)
    probes: list[dict[str, Any]] = []
    sheet_candidates: list[dict[str, Any]] = []
    for dataset in datasets:
        probes.extend(_probes_for_dataset(store, dataset, sheet_candidates, diagnostics, code_map))

    proposed_scope = _proposed_scope(probes)
    # Each file answers for itself. A pack whose AR sheet never declares a
    # currency says nothing about the ledger sheet that does, and a report that
    # blocked the whole task on the weakest file sent the manager looking for a
    # problem in the wrong place.
    per_dataset = [
        _dataset_readiness(group, code_map)
        for group in _by_dataset(probes)
    ]
    can_run = [
        name
        for name in CAPABILITY_ORDER
        if any(name in entry["can_run"] for entry in per_dataset)
    ]
    blocked: list[dict[str, Any]] = []
    for entry in per_dataset:
        for item in entry["blocked"]:
            if item["capability"] in can_run:
                continue
            blocked.append({**item, "dataset_id": entry["dataset_id"]})
    for code, message in _report_diagnostics(blocked):
        diagnostics.append(_diag("error", code, message))

    with_rows = [probe for probe in probes if probe["rows"]]
    policy = (
        "business_key"
        if with_rows and all(_has_business_keys(probe) for probe in with_rows)
        else "snapshot_only"
    )
    return _report(
        proposed_scope=proposed_scope,
        can_run=can_run,
        blocked=blocked,
        policy=policy,
        diagnostics=diagnostics,
        sheet_candidates=sheet_candidates,
        structure_states=structure_states,
        datasets=per_dataset,
    )


def _by_dataset(probes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for probe in probes:
        key = str(probe.get("dataset_id") or "")
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(probe)
    return [grouped[key] for key in order]


def _dataset_readiness(probes: list[dict[str, Any]], code_map: dict[str, str]) -> dict[str, Any]:
    """What this one file can answer for, and what it is still missing."""
    scope = _proposed_scope(probes)
    missing = [key for key in ("period", "currency") if not scope.get(key)]
    identity_failed = any(
        probe["identity_attempted"] and not probe["identity_ok"] for probe in probes
    )
    has_amount_rows = any(probe["has_amount"] and probe["rows"] for probe in probes)
    can_run: list[str] = []
    blocked: list[dict[str, Any]] = []

    if identity_failed:
        blocked.append(
            _blocked("management_pnl", missing or ["period", "currency"], "identity_failed")
        )
    elif missing:
        blocked.append(_blocked("management_pnl", missing, "missing_scope"))
    elif any(_pnl_sheet_ready(probe, code_map) for probe in probes):
        can_run.append("management_pnl")
    else:
        blocked.append(_blocked("management_pnl", ["management_account"], "mapping_incomplete"))

    if missing:
        blocked.append(_blocked("control_totals", missing, "missing_scope"))
    elif has_amount_rows:
        can_run.append("control_totals")

    if _aging_ready(probes) and not missing:
        can_run.append("receivables_aging")

    return {
        "dataset_id": str(probes[0].get("dataset_id") or "") if probes else "",
        "name": str(probes[0].get("dataset_name") or "") if probes else "",
        "scope": scope,
        "missing_fields": missing,
        "can_run": [name for name in CAPABILITY_ORDER if name in can_run],
        "blocked": blocked,
    }


REASON_MESSAGES = {
    "identity_failed": "header identity did not declare period and currency",
    "missing_scope": "period or currency is not declared",
    "mapping_incomplete": "management accounts are not fully mapped on one sheet",
}


def _report_diagnostics(blocked: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """One diagnostic per reason, not one per file that shares it."""
    seen: list[tuple[str, str]] = []
    for item in blocked:
        reason = str(item.get("reason") or "")
        message = REASON_MESSAGES.get(reason)
        if message and (reason, message) not in seen:
            seen.append((reason, message))
    return seen


def _report(
    *,
    proposed_scope,
    can_run,
    blocked,
    policy,
    diagnostics,
    sheet_candidates,
    structure_states=None,
    datasets=None,
) -> dict[str, Any]:
    return {
        "structure_states": structure_states or {},
        "proposed_scope": proposed_scope,
        # What each file answers for on its own. `proposed_scope` above is only
        # what they all agree on, so this is where a disagreement is legible.
        "datasets": datasets or [],
        "can_run": can_run,
        "blocked": blocked,
        "file_identity_policy": policy,
        "diagnostics": [_sanitize_diagnostic(item) for item in diagnostics],
        # No adapter is ever named on a file-first session; a live ledger link
        # must come from a session-scoped, authorized adapter, which does not exist yet.
        "erp_connected": False,
        "sheet_candidates": sheet_candidates,
        "merged_sheets": False,
    }


def _blocked(capability: str, missing_fields: list[str], reason: str) -> dict[str, Any]:
    return {"capability": capability, "missing_fields": list(missing_fields), "reason": reason}


def _authorized_tables(store, diagnostics: list[dict]):
    """Authorized datasets, what each one's table structure is waiting for, and
    whether anything is still waiting for the manager.

    A workbook whose structure has been confirmed is represented by the table it
    produced; probing the original again would report the mis-parse the
    confirmation exists to correct.
    """
    from foundry.structure_records import (
        NO_TABLE,
        NOT_APPLICABLE,
        PENDING_CONFIRMATION,
        WITHDRAWN,
    )

    state = store.analysis.state()
    records = [
        row
        for row in state["datasets"]
        if store.allowed is None or row["id"] in store.allowed
    ]
    tables = []
    states: dict[str, str] = {}
    pending = False
    for record in records:
        try:
            dataset = store.analysis.read_dataset(record["id"])
        except FoundryError:
            # A snapshot that fails its integrity check is reported by code only;
            # the exception text never reaches the report.
            diagnostics.append(_diag("error", "dataset_unreadable", "dataset snapshot could not be read"))
            continue
        if dataset.get("kind") == "background":
            continue
        structure = store.dataset_structure_state(record["id"])
        states[record["id"]] = structure
        if _is_workbook_shell(dataset) and structure != NOT_APPLICABLE:
            # Once a workbook has been read, the tables it produced answer for
            # it; probing the original again reports the mis-parse the
            # confirmation exists to correct.
            if structure in {PENDING_CONFIRMATION, NO_TABLE}:
                pending = True
            continue
        if structure == WITHDRAWN:
            continue
        tables.append(dataset)
    return tables, states, pending


def _account_code_map(store) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for record in store._list("account_maps"):
        for item in record.get("rows") or []:
            code = str(item.get("account_code") or "").strip()
            account = str(item.get("management_account") or "").strip()
            if code and account:
                mapping[code] = account
    return mapping


def _probes_for_dataset(
    store,
    dataset: dict,
    sheet_candidates: list[dict[str, Any]],
    diagnostics: list[dict],
    code_map: dict[str, str],
) -> list[dict[str, Any]]:
    if _is_workbook_shell(dataset):
        return _workbook_probes(store, dataset, sheet_candidates, diagnostics, code_map)
    rows = list(dataset.get("rows") or [])
    headers = _headers_of(dataset, rows)
    return [
        _probe(
            headers,
            rows,
            sheet=str(dataset.get("transformation", {}).get("sheet") or ""),
            dataset_id=str(dataset.get("id") or ""),
            dataset_name=str(dataset.get("name") or ""),
            hints=_declared_hints(dataset),
        )
    ]


def _declared_hints(dataset: dict) -> dict[str, str]:
    """Period, currency and unit as the manager confirmed them off the title area.

    A derived table starts at the header row, so the title line that carried
    「单位：元」 is not in its rows and cannot be read back out of them. The
    confirmation kept it; this is where it re-enters the report.
    """
    structure = (dataset.get("transformation") or {}).get("structure") or {}
    hints = (structure.get("declaration") or {}).get("scope_hints") or {}
    return {key: str(hints.get(key) or "") for key in ("period", "currency", "unit")}


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
    code_map: dict[str, str],
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
        probe = _probe(
            headers,
            rows,
            sheet=name,
            dataset_id=str(dataset.get("id") or ""),
            dataset_name=str(dataset.get("name") or ""),
        )
        probes.append(probe)
        sheet_candidates.append({"sheet": name, "mappable": _pnl_sheet_ready(probe, code_map)})
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


def _probe(
    headers: list[str],
    rows: list[dict],
    *,
    sheet: str,
    dataset_id: str = "",
    dataset_name: str = "",
    hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    fmap = _field_map({})
    title = _title_blob(headers, rows)
    attempted = _identity_attempted(headers, title)
    # What the manager confirmed about the title area outranks anything guessed
    # back out of the derived rows, which no longer contain the title at all.
    hints = {key: str(value or "").strip() for key, value in (hints or {}).items()}
    period = (
        _unanimous(_declared_values(rows, fmap, "period"))
        or hints.get("period", "")
        or _period_from_title(title)
    )
    currency = (
        _unanimous(_declared_values(rows, fmap, "currency"))
        or hints.get("currency", "")
        or _currency_from_title(title)
    )
    return {
        "sheet": sheet,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "headers": headers,
        "rows": rows,
        "period": period,
        "currency": currency,
        "ledger": _unanimous(_declared_values(rows, fmap, "ledger")),
        "organization": _unanimous(_declared_values(rows, fmap, "organization")),
        "unit": (
            _unanimous(_declared_values(rows, fmap, "unit"))
            or hints.get("unit", "")
            or _unit_from_title(title)
        ),
        "identity_attempted": attempted,
        "identity_ok": bool(period and currency) if attempted else True,
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


def _unit_from_title(title: str) -> str:
    match = _UNIT_IN_TITLE.search(title)
    return match.group(1) if match else ""


def _currency_from_title(title: str) -> str:
    match = _CURRENCY_IN_TITLE.search(title)
    if match:
        return match.group(1)
    if "人民币" in title:
        return "人民币"
    return ""


def _declared_values(rows: list[dict], fmap: dict, canonical: str) -> list[str]:
    """Distinct declared values in source order. A literal 本月 period is not a declaration."""
    values: list[str] = []
    for row in rows:
        raw = _read(row, fmap, canonical)
        text = str(raw).strip() if raw is not None else ""
        if not text or text in values:
            continue
        if canonical == "period" and text == SILENT_PERIOD:
            continue
        values.append(text)
    return values


def _unanimous(values: list[str]) -> str:
    """The one value a column declares, or blank where it declares several.

    A column holding 上海城市公司 on one row and 宁波城市公司 on the next is a
    dimension of the data, not the scope of the file. Taking the first row's
    value made the readiness report answer 组织 with whatever happened to sort
    first, and joining every value with a comma made 期间 read 2026-08,2026-01 —
    a string no scope can ever match.
    """
    return values[0] if len(values) == 1 else ""


def _headers_include(headers: list[str], canonical: str) -> bool:
    aliases = {name.casefold() for name in DEFAULT_FIELD_MAP.get(canonical, (canonical,))}
    return any(header.casefold() in aliases for header in headers)


def _proposed_scope(probes: list[dict[str, Any]]) -> dict[str, str]:
    """What every probe agrees on. Where they differ the answer is blank.

    Two files closing different months do not share a period, and a report that
    answered 2026-08,2026-01 offered a value that is not a period and cannot be
    bound. The disagreement belongs in the per-dataset breakdown, not folded
    into one string.
    """
    scope = {key: "" for key in SCOPE_KEYS}
    for key in SCOPE_KEYS:
        found: list[str] = []
        for probe in probes:
            value = str(probe.get(key) or "").strip()
            if not value or value in found:
                continue
            found.append(value)
        scope[key] = found[0] if len(found) == 1 else ""
    return scope


def _accounts_for_probe(probe: dict[str, Any], code_map: dict[str, str]) -> set[str]:
    accounts = set(probe["management_accounts"])
    for code in probe["account_codes"]:
        account = code_map.get(code)
        if account:
            accounts.add(account)
    return accounts


def _pnl_sheet_ready(probe: dict[str, Any], code_map: dict[str, str]) -> bool:
    """One sheet must close the P&L on its own: period, currency, and every P&L account."""
    if not probe["rows"]:
        return False
    return bool(
        probe["period"]
        and probe["currency"]
        and PNL_ACCOUNTS <= _accounts_for_probe(probe, code_map)
    )


def _has_business_keys(probe: dict[str, Any]) -> bool:
    return bool(probe["doc_id"] and probe["line_id"])


def _aging_ready(probes: list[dict[str, Any]]) -> bool:
    return any(
        probe["due_date"] and (probe["has_amount"] or "accounts_receivable" in probe["management_accounts"])
        for probe in probes
    )


def _sanitize_diagnostic(item: dict) -> dict:
    clean = dict(item)
    message = str(clean.get("message") or "")
    if _LEAK_RE.search(message):
        clean["message"] = "[redacted]"
    return clean
