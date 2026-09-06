"""Deterministic explanation facts and draft checks for finance analysis."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from calendar import monthrange
from decimal import Decimal, InvalidOperation
from typing import Any

from foundry.analysis import BASIS, _hash, _safe_text
from foundry.analysis_data import json_value
from foundry.errors import FoundryError

FACT_TOKEN = re.compile(r"\{\{fact:([0-9a-f]{64})\}\}")
NUMBER = re.compile(r"(?<![A-Za-z0-9_.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![A-Za-z0-9_.])")
DATE_SPAN = re.compile(r"\b\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2})?")
FACT_ID = re.compile(r"^[0-9a-f]{64}$")
PERIOD_OR_DATE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")

MONEY_COLUMNS = {
    "amount",
    "signed_amount",
    "revenue",
    "cost",
    "expense",
    "profit",
    "actual",
    "baseline",
    "contribution",
    "numerator",
    "denominator",
    "quantity_contribution",
    "price_contribution",
    "interaction",
    "total_variance",
    "residual",
}
RATIO_COLUMNS = {"ratio", "cost_rate_pct", "gross_margin_pct"}
META_COLUMNS = {
    "scenario",
    "currency",
    "unit",
    "metric",
    "basis",
    "favorability",
    "comparison_status",
    "ratio_status",
}
METRIC_LABELS = {
    "revenue": "收入",
    "cost": "成本",
    "expense": "费用",
    "profit": "利润",
}
POSITIVE_WORDS = ("增加", "增长", "提升", "上升", "超", "高", "有利", "改善")
NEGATIVE_WORDS = ("减少", "下降", "降低", "少", "不利", "恶化")


def prepare_explanation(
    analysis,
    runs: list[dict],
    backgrounds: list[dict] | None = None,
    materiality: dict | None = None,
) -> dict:
    facts: list[dict] = []
    materiality = _materiality(materiality or {})
    diagnostics: list[dict] = []
    for run in runs:
        if run.get("execution_status") != "succeeded":
            raise FoundryError("explanation facts require a referenced successful run")
        diagnostics.extend(_run_diagnostics(run))
        facts.extend(_facts_for_run(run, materiality))
    required = _required_fact_ids(facts)
    return {
        "schema_version": 1,
        "task_id": analysis.task.id,
        "facts": facts,
        "required_fact_ids": required,
        "diagnostics": diagnostics,
        "business_contexts": backgrounds or [],
    }


def render_fact_template(body: str, facts: list[dict]) -> tuple[str, list[str]]:
    by_id = {fact["id"]: fact for fact in facts}
    used: list[str] = []

    def replace(match: re.Match) -> str:
        fact_id = match.group(1)
        fact = by_id.get(fact_id)
        if not fact:
            return match.group(0)
        used.append(fact_id)
        return fact["display_value"]

    return FACT_TOKEN.sub(replace, body), used


def claims_for_facts(facts: list[dict], fact_ids: list[str]) -> list[dict]:
    by_id = {fact["id"]: fact for fact in facts}
    claims = []
    for fact_id in dict.fromkeys(fact_ids):
        fact = by_id.get(fact_id)
        if not fact:
            continue
        claims.append(
            {
                "basis": "calculation",
                "fact_id": fact["id"],
                "run_id": fact["run_id"],
                "row": fact["row"],
                "column": fact["column"],
                "value": fact["value"],
                "display_value": fact["display_value"],
            }
        )
    return claims


def validate_explanation(analysis, spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise FoundryError("explanation spec must be an object")
    draft = analysis.get_draft(spec["draft_id"]) if spec.get("draft_id") else {}
    body = _safe_text(spec.get("body", draft.get("body", "")), "draft body")
    run_ids = spec.get("run_ids", draft.get("run_ids", []))
    fact_ids = spec.get("fact_ids", draft.get("fact_ids", []))
    claims = json_value(spec.get("claims", draft.get("claims", [])))
    if not isinstance(run_ids, list) or not isinstance(fact_ids, list):
        raise FoundryError("run_ids and fact_ids must be arrays")
    if not isinstance(claims, list):
        raise FoundryError("claims must be an array")
    runs = [analysis.get_run(run_id) for run_id in dict.fromkeys(run_ids)]
    facts = prepare_explanation(
        analysis, [r for r in runs if r.get("execution_status") == "succeeded"]
    )["facts"]
    by_id = {fact["id"]: fact for fact in facts}
    by_location = {(fact["run_id"], fact["row"], fact["column"]): fact for fact in facts}
    issues: list[dict] = []
    referenced = set()
    for fact_id in fact_ids:
        if (
            not isinstance(fact_id, str)
            or not FACT_ID.fullmatch(fact_id)
            or fact_id not in by_id
        ):
            issues.append(
                {
                    "code": "unknown_fact",
                    "severity": "error",
                    "message": "引用的事实不存在于当前成功运行结果。",
                    "fact_id": fact_id,
                }
            )
        else:
            referenced.add(fact_id)
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("basis") not in BASIS:
            issues.append(
                {
                    "code": "invalid_claim",
                    "severity": "error",
                    "message": "claim requires an explicit supported basis.",
                }
            )
            continue
        fact = by_id.get(claim.get("fact_id")) if claim.get("fact_id") else None
        if fact:
            referenced.add(fact["id"])
            if any(
                claim.get(key) != fact[key]
                for key in ("run_id", "row", "column", "value")
            ):
                issues.append(
                    {
                        "code": "fact_claim_mismatch",
                        "severity": "error",
                        "message": "事实引用与 claim 的 run/row/column/value 不一致。",
                        "fact_id": fact["id"],
                    }
                )
        elif claim.get("basis") == "calculation":
            issue = _validate_calculation_claim(analysis, claim, run_ids)
            if issue:
                issues.append(issue)
            else:
                bound_fact = by_location.get((claim.get("run_id"), claim.get("row"), claim.get("column")))
                if bound_fact:
                    referenced.add(bound_fact["id"])
                else:
                    issues.append({"code": "unknown_fact", "severity": "error", "message": "引用位置没有可核验的数值事实。"})
            if claim.get("fact_id"):
                issues.append({"code": "unknown_fact", "severity": "error", "message": "引用的事实不存在于当前成功运行结果。"})
    issues.extend(
        _fact_context_issues(body, [by_id[f] for f in referenced if f in by_id])
    )
    allowed_numbers = _allowed_numbers(
        [by_id[fact_id] for fact_id in referenced if fact_id in by_id]
    )
    for token in _body_numbers(body):
        if _normalize_number(token["text"]) not in allowed_numbers:
            issues.append(
                {
                    "code": "uncited_number",
                    "severity": "warning",
                    "message": "正文包含未绑定到当前事实或 claim 的数字。",
                    "text": token["text"],
                    "position": token["start"],
                }
            )
    required = (
        set(_required_fact_ids(facts))
        if spec.get("require_all_material_facts") is True
        else set()
    )
    missing_required = sorted(required - referenced)
    for fact_id in missing_required:
        issues.append(
            {
                "code": "missing_required_fact",
                "severity": "warning",
                "message": "重要结果事实尚未在说明中引用。",
                "fact_id": fact_id,
            }
        )
    status = "pass" if not issues else "needs_attention"
    return {
        "schema_version": 1,
        "status": status,
        "issues": [issue for issue in issues if issue],
        "coverage": {
            "referenced_fact_count": len(referenced),
            "available_fact_count": len(facts),
            "missing_required_fact_ids": missing_required,
        },
        "facts": facts,
    }


def normalize_background(
    spec: dict, *, parent: dict | None = None, dataset: dict | None = None
) -> dict:
    if not isinstance(spec, dict):
        raise FoundryError("finance background spec must be an object")
    parent = parent or {}
    basis = spec.get("basis", parent.get("basis", "professional_judgment"))
    if basis not in BASIS:
        raise FoundryError("background basis is unsupported")
    scope = spec.get("scope", parent.get("scope", {}))
    if (
        not isinstance(scope, dict)
        or not scope.get("ledger")
        or not scope.get("organization")
    ):
        raise FoundryError("background scope requires ledger and organization")
    effective_from = _date_key(
        spec.get("effective_from", parent.get("effective_from")), "effective_from"
    )
    effective_to = spec.get("effective_to", parent.get("effective_to"))
    if effective_to is not None:
        effective_to = _date_key(effective_to, "effective_to")
        if _date_end_key(effective_to) < effective_from:
            raise FoundryError("effective_to cannot be earlier than effective_from")
    paragraph = spec.get("paragraph", (parent.get("source") or {}).get("paragraph"))
    if paragraph is not None and (
        isinstance(paragraph, bool) or not isinstance(paragraph, int) or paragraph < 1
    ):
        raise FoundryError("background paragraph must be a positive integer")
    paragraph_text = None
    if dataset and paragraph:
        paragraph_record = next(
            (p for p in dataset.get("paragraphs", []) if p["paragraph"] == paragraph),
            None,
        )
        if not paragraph_record:
            raise FoundryError("background paragraph does not exist")
        paragraph_text = paragraph_record.get("text", "")
    if basis == "source_fact":
        if not dataset or not paragraph:
            raise FoundryError("source_fact background requires dataset_id and paragraph")
        text = _safe_text(spec.get("text", parent.get("text", "")), "background text", required=True)
        if text not in paragraph_text:
            raise FoundryError("background text must come from paragraph")
    external_reference = _external_reference(spec, parent, basis)
    source = None
    if dataset:
        source = {
            "dataset_id": dataset["id"],
            "source_hash": dataset["source_hash"],
            "paragraph": paragraph,
            "paragraph_text": paragraph_text,
        }
    return {
        "label": _safe_text(
            spec.get("label", parent.get("label", "业务背景")),
            "background label",
            required=True,
            maximum=200,
        ),
        "text": _safe_text(
            spec.get("text", parent.get("text", "")), "background text", required=True
        ),
        "basis": basis,
        "scope": json_value({k: v for k, v in scope.items() if k not in {"period", "scenario"}}),
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source": source,
        "external_reference": external_reference,
        "parent_id": parent.get("id"),
    }


def background_applies(record: dict, *, scope: dict, as_of: str | None = None) -> bool:
    candidate = record.get("scope", {})
    for key, value in candidate.items():
        if key == "scenario" or value in (None, ""):
            continue
        if scope.get(key) != value:
            return False
    as_of = _date_key(as_of, "as_of") if as_of else current_period()
    if as_of:
        if str(record.get("effective_from", "")) > _date_end_key(as_of):
            return False
        if record.get("effective_to") and _date_end_key(str(record["effective_to"])) < as_of:
            return False
    return True


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _date_key(value: Any, label: str) -> str:
    text = _safe_text(value, label, required=True, maximum=40)
    if not PERIOD_OR_DATE.fullmatch(text):
        raise FoundryError(f"{label} must be YYYY-MM or YYYY-MM-DD")
    try:
        date.fromisoformat(text + '-01' if len(text) == 7 else text)
    except ValueError as exc:
        raise FoundryError(f"{label} must be a valid YYYY-MM or YYYY-MM-DD date") from exc
    return text


def _date_end_key(value: str) -> str:
    return f"{value}-{monthrange(int(value[:4]), int(value[5:7]))[1]:02d}" if len(value) == 7 else value


def _external_reference(spec: dict, parent: dict, basis: str) -> dict | None:
    value = spec.get("external_reference", parent.get("external_reference"))
    if basis != "external_reference":
        return json_value(value) if isinstance(value, dict) else None
    if not isinstance(value, dict):
        raise FoundryError("external_reference requires reference metadata")
    title = value.get("title")
    url = value.get("url")
    if not (
        isinstance(title, str)
        and title.strip()
        or isinstance(url, str)
        and url.strip()
    ):
        raise FoundryError("external_reference requires title or url")
    source_date = value.get("source_date")
    retrieved_at = value.get("retrieved_at")
    if not source_date and not retrieved_at:
        raise FoundryError("external_reference requires source_date or retrieved_at")
    cleaned = dict(value)
    for key in ("source_date", "retrieved_at"):
        if cleaned.get(key):
            try:
                cleaned[key] = _date_key(cleaned[key], f"external_reference {key}")
            except FoundryError as exc:
                raise FoundryError("external_reference date must be YYYY-MM or YYYY-MM-DD") from exc
    return json_value(cleaned)


def _facts_for_run(run: dict, materiality: dict) -> list[dict]:
    result = run.get("result", {})
    rows = result.get("rows", [])
    columns = [
        c["name"] if isinstance(c, dict) else str(c)
        for c in result.get("columns", [])
    ]
    facts: list[dict] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        for column in columns:
            if column in META_COLUMNS or column not in row or row.get(column) is None:
                continue
            value = row.get(column)
            if not _is_fact_value(value, column):
                continue
            fact = _make_fact(run, row_index, row, column, value, materiality)
            facts.append(fact)
    return facts


def _materiality(materiality: dict) -> dict:
    if not isinstance(materiality, dict):
        raise FoundryError("materiality must be an object")
    if materiality.get("relative") is not None:
        raise FoundryError("materiality.relative is not supported yet")
    return materiality


def _run_diagnostics(run: dict) -> list[dict]:
    rows = []
    for item in [
        *run.get("warnings", []),
        *run.get("result", {}).get("diagnostics", []),
        *run.get("diagnostics", []),
    ]:
        if isinstance(item, dict):
            rows.append({**item, "run_id": run["id"]})
    return rows


def _required_fact_ids(facts: list[dict]) -> list[str]:
    selected = {}
    for fact in facts:
        if fact["semantics"].get("required_for_explanation") is not True:
            continue
        key = (
            fact["run_id"],
            fact["row"],
            fact["semantics"].get("metric"),
        )
        current = selected.get(key)
        if current is None or _fact_priority(fact) < _fact_priority(current):
            selected[key] = fact
    return [fact["id"] for fact in selected.values()]


def _fact_priority(fact: dict) -> int:
    column = fact.get("column")
    if column == "contribution":
        return 0
    if column == "profit_impact":
        return 1
    if column in RATIO_COLUMNS:
        return 1
    if column in {"actual", "baseline"}:
        return 2
    return 3


def _make_fact(run: dict, row_index: int, row: dict, column: str, value: Any, materiality: dict) -> dict:
    exact = _exact(value)
    fact_id = _hash(
        {
            "kind": "finance-explanation-fact-v1",
            "run_id": run["id"],
            "output_hash": run.get("output_hash"),
            "row": row_index,
            "column": column,
            "value": exact,
        }
    )
    unit = row.get("unit")
    display = _display_value(exact, column, unit)
    semantics = _semantics(row, column, exact, materiality)
    refs = row.get("evidence", {}).get(column, row.get("source_rows", []))
    return {
        "id": fact_id,
        "run_id": run["id"],
        "analysis_id": run.get("analysis_id"),
        "row": row_index,
        "column": column,
        "value": exact,
        "display_value": display,
        "label": _label(row, column),
        "unit": "%" if column in RATIO_COLUMNS else unit,
        "scope": run.get("finance_scope", {}),
        "semantics": semantics,
        "source_trace": {
            "output_hash": run.get("output_hash"),
            "input_hashes": run.get("input_hashes", {}),
            "source_hashes": run.get("source_hashes", {}),
            "source_rows": refs,
            "source_row_count": len(refs) if isinstance(refs, list) else 0,
        },
    }


def _semantics(row: dict, column: str, exact: str, materiality: dict) -> dict:
    role = "ratio" if column in RATIO_COLUMNS else "amount" if column in MONEY_COLUMNS else "value"
    if column in {"contribution", "profit_impact"}:
        role = "profit_impact"
    try:
        magnitude = abs(Decimal(exact.rstrip("%")))
    except InvalidOperation:
        magnitude = Decimal(0)
    threshold = materiality.get("absolute", "0") if isinstance(materiality, dict) else "0"
    try:
        material = magnitude >= Decimal(str(threshold))
    except InvalidOperation:
        material = magnitude != 0
    return {
        "role": role,
        "metric": row.get("metric") or column,
        "direction": "positive" if not exact.startswith("-") else "negative",
        "required_for_explanation": (
            material and magnitude != 0 and role in {"amount", "ratio", "profit_impact"}
        ) or (magnitude == 0 and column in {
            "contribution", "profit_impact", "total_variance", "interaction", "residual",
        }),
    }


def _display_value(exact: str, column: str, unit: Any) -> str:
    if column in RATIO_COLUMNS:
        try:
            percent = Decimal(exact) if column.endswith("_pct") else Decimal(exact) * Decimal(100)
            return f"{percent.quantize(Decimal('0.01'))}%"
        except InvalidOperation:
            return exact
    suffix = f" {unit}" if unit else ""
    return f"{exact}{suffix}"


def _label(row: dict, column: str) -> str:
    parts = [str(row.get("metric") or column)]
    if column != parts[0]:
        parts.append(column)
    for key in ("scenario", "period"):
        if row.get(key):
            parts.append(str(row[key]))
    return " / ".join(parts)


def _is_fact_value(value: Any, column: str) -> bool:
    if column in MONEY_COLUMNS or column in RATIO_COLUMNS:
        return True
    try:
        return not isinstance(value, bool) and Decimal(str(value)).is_finite()
    except InvalidOperation:
        return False


def _fact_context_issues(body: str, facts: list[dict]) -> list[dict]:
    """Match complete numeric tokens to a compatible fact within their clause.

    A shared number is not an identity: select by the nearest financial label,
    then validate its unit and change semantics. Never match 5 inside 15.
    """
    issues = []
    for token in _body_numbers(body):
        value = Decimal(_normalize_number(token["text"]))
        candidates = [f for f in facts if _token_matches_fact(token["text"], f)]
        if not candidates:
            continue
        start = token["start"]
        end = start + len(token["text"])
        prefix = re.split(r"[，,；;。\n|]", body[:start])[-1][-60:]
        metric_matches = [(prefix.rfind(label), key) for key, label in METRIC_LABELS.items() if label in prefix]
        metric = max(metric_matches)[1] if metric_matches else None
        # In '成本利润影响', profit denotes the effect, not a different line item.
        impact = bool(re.search(r"利润.{0,3}(?:影响|贡献)|profit.{0,3}(?:impact|effect)", prefix, re.I))
        if impact:
            non_profit = [(at, key) for at, key in metric_matches if key != 'profit']
            metric = max(non_profit)[1] if non_profit else None
        labelled = [f for f in candidates if not metric or f['semantics'].get('metric') == metric or f['semantics'].get('metric') not in METRIC_LABELS]
        if not labelled:
            issues.append({'code': 'fact_label_mismatch', 'severity': 'warning', 'message': '正文指标与同值引用事实不一致。', 'position': start})
            labelled = candidates
        alternatives = []
        for fact in labelled:
            found = []
            unit_match = re.match(r"\s*(亿元|万元|元|%)", body[end:])
            if unit_match and fact.get('unit') and unit_match[1] != fact['unit']:
                found.append({'code': 'fact_unit_mismatch', 'severity': 'warning', 'message': '正文单位与引用事实单位不一致。'})
            semantic = fact['semantics']
            if semantic.get('role') == 'profit_impact' or fact['column'] in {'amount_change', 'total_variance', 'quantity_contribution', 'price_contribution', 'interaction'}:
                exact = Decimal(str(fact['value']))
                if semantic.get('role') == 'profit_impact' and semantic.get('metric') in {'cost', 'expense'} and metric in {'cost', 'expense'} and not impact:
                    exact = -exact
                sign_words = [(prefix.rfind(w), -1) for w in NEGATIVE_WORDS if w in prefix] + [(prefix.rfind(w), 1) for w in POSITIVE_WORDS if w in prefix]
                direction = max(sign_words)[1] if sign_words else None
                stated = abs(value) * direction if direction else value
                if stated and exact and (stated > 0) != (exact > 0):
                    found.append({'code': 'fact_direction_mismatch', 'severity': 'warning', 'message': '正文增减方向与所引用财务影响不一致。'})
            alternatives.append([{**issue, 'fact_id': fact['id'], 'position': start} for issue in found])
        # Another fact with the same value and matching label may be the correct reference.
        issues.extend(min(alternatives, key=len) if alternatives else [])
    return issues


def _token_matches_fact(text: str, fact: dict) -> bool:
    value = Decimal(_normalize_number(text))
    options = _numbers_from_text(str(fact.get('display_value', ''))) | {_fact_number(fact)}
    if any(value == Decimal(option) for option in options):
        return True
    return fact['semantics'].get('role') == 'profit_impact' and any(abs(value) == abs(Decimal(option)) for option in options)


def _validate_calculation_claim(analysis, claim: dict, run_ids: list[str]) -> dict | None:
    try:
        run = analysis.get_run(claim.get("run_id"))
        if run["id"] not in run_ids or run.get("execution_status") != "succeeded":
            raise ValueError("claim requires a referenced successful run")
        row = claim["row"]
        if isinstance(row, bool) or not isinstance(row, int) or row < 0:
            raise ValueError("claim row must be a non-negative integer")
        actual = run["result"]["rows"][row][claim["column"]]
        matches = _decimal_equal(actual, claim.get("value"))
    except Exception:
        return {
            "code": "invalid_claim_location",
            "severity": "error",
            "message": "calculation claim has an invalid output location.",
        }
    if not matches:
        return {
            "code": "claim_value_mismatch",
            "severity": "error",
            "message": "claim value differs from execution result.",
        }
    return None


def _fact_number(fact: dict) -> str:
    value = Decimal(str(fact["value"]))
    if fact.get("column") in RATIO_COLUMNS and fact["column"].endswith("_pct"):
        value /= 100
    return _normalize_number(str(value))


def _allowed_numbers(facts: list[dict]) -> set[str]:
    allowed = set()
    for fact in facts:
        allowed.add(_fact_number(fact))
        if fact["semantics"].get("role") == "profit_impact":
            allowed.add(_normalize_number(str(abs(Decimal(fact["value"])))))
        allowed.update(_numbers_from_text(fact["display_value"]))
    return {item for item in allowed if item}


def _body_numbers(body: str) -> list[dict]:
    date_spans = [match.span() for match in DATE_SPAN.finditer(body)]
    values = []
    for match in NUMBER.finditer(body):
        if any(_overlaps(match.span(), span) for span in date_spans):
            continue
        before = body[match.start() - 1 : match.start()]
        after = body[match.end() : match.end() + 1]
        if (before and before in "-/年月日") or (after and after in "-/年月日"):
            continue
        values.append({"text": match.group(0), "start": match.start()})
    return values


def _numbers_from_text(text: str) -> set[str]:
    return {_normalize_number(match["text"]) for match in _body_numbers(text)}


def _normalize_number(text: str) -> str:
    text = str(text).strip().replace(",", "")
    if text.endswith("%"):
        try:
            return format(Decimal(text[:-1]) / Decimal(100), "f")
        except InvalidOperation:
            return text
    try:
        value = Decimal(text)
        return format(value.normalize(), "f")
    except InvalidOperation:
        return text


def _decimal_equal(left: Any, right: Any) -> bool:
    if left == right:
        return True
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except InvalidOperation:
        return False


def _exact(value: Any) -> str:
    return str(value)


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]
