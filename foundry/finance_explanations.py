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
    evidence_groups: list[dict] = []
    for run in runs:
        if run.get("execution_status") != "succeeded":
            raise FoundryError("explanation facts require a referenced successful run")
        diagnostics.extend(_run_diagnostics(run))
        run_facts = _facts_for_run(run, materiality)
        facts.extend(run_facts)
        evidence_groups.extend(_evidence_groups_for_run(run, run_facts))
    required = _required_fact_ids(facts)
    return {
        "schema_version": 1,
        "task_id": analysis.task.id,
        "facts": facts,
        "evidence_groups": evidence_groups,
        "required_fact_ids": required,
        "diagnostics": diagnostics,
        "business_contexts": backgrounds or [],
        "materiality": materiality,
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


def render_evidence_appendix(prepared: dict) -> dict:
    """Render readable calculation evidence without changing manager prose."""
    if not isinstance(prepared, dict):
        raise FoundryError("prepared explanation payload must be an object")
    groups = prepared.get("evidence_groups", [])
    if not isinstance(groups, list):
        raise FoundryError("prepared evidence_groups must be an array")
    lines = ["## 计算依据"]
    fact_ids: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        title = group.get("label") or group.get("group_type") or group.get("id")
        lines.append(f"\n### {title}")
        members = group.get("members", [])
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            state = member.get("state", "missing")
            label = member.get("label") or member.get("semantic_role") or member.get("column")
            value = member.get("display_value")
            suffix = f"：{value}" if value not in (None, "") else ""
            if member.get("fact_id"):
                fact_ids.append(member["fact_id"])
            source_count = member.get("source_row_count")
            source = (
                "；有来源行"
                if isinstance(source_count, int) and source_count > 0
                else ""
            )
            lines.append(f"- {label}{suffix}（{_state_label(state)}{source}）")
        closure = group.get("closure")
        if isinstance(closure, dict) and closure.get("status") != "unsupported":
            lines.append(f"- 闭合核对：{_closure_label(closure)}")
    return {
        "schema_version": 1,
        "body": "\n".join(lines).strip() if len(lines) > 1 else "",
        "fact_ids": list(dict.fromkeys(fact_ids)),
        "claims": claims_for_facts(
            prepared.get("facts", []), list(dict.fromkeys(fact_ids))
        ),
    }


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
    prepared = prepare_explanation(
        analysis,
        [r for r in runs if r.get("execution_status") == "succeeded"],
        materiality=spec.get("materiality", draft.get("materiality", {})),
    )
    facts = prepared["facts"]
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
    required = set(_required_fact_ids(facts))
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
    for group in prepared.get("evidence_groups", []):
        if not isinstance(group, dict):
            continue
        closure = group.get("closure", {})
        if isinstance(closure, dict) and closure.get("status") in {
            "closure_mismatch",
            "scope_mismatch",
            "unit_mismatch",
        }:
            issues.append(
                {
                    "code": "evidence_group_not_closed",
                    "severity": "warning",
                    "message": "计算依据组未通过同范围同单位闭合核对。",
                    "group_id": group.get("id"),
                    "closure_status": closure.get("status"),
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
            "fact_states": _fact_state_counts(facts),
            "evidence_group_statuses": _evidence_group_statuses(
                prepared.get("evidence_groups", [])
            ),
        },
        "facts": facts,
        "evidence_groups": prepared.get("evidence_groups", []),
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
    cleaned = {"absolute": str(materiality.get("absolute", "0"))}
    try:
        Decimal(cleaned["absolute"])
    except InvalidOperation as exc:
        raise FoundryError("materiality.absolute must be a decimal string") from exc
    relative = materiality.get("relative")
    if relative is None:
        return cleaned
    if isinstance(relative, dict):
        threshold = relative.get("threshold", relative.get("value"))
        denominator = relative.get("denominator", "baseline_abs")
        negative_policy = relative.get("negative_policy", "absolute")
    else:
        threshold = relative
        denominator = "baseline_abs"
        negative_policy = "absolute"
    try:
        threshold_text = str(threshold)
        threshold_value = Decimal(threshold_text)
    except (InvalidOperation, TypeError) as exc:
        raise FoundryError("materiality.relative threshold must be a decimal string") from exc
    if threshold_value < 0:
        raise FoundryError("materiality.relative threshold cannot be negative")
    if denominator not in {"baseline_abs", "actual_abs", "max_abs"}:
        raise FoundryError("materiality.relative denominator is unsupported")
    if negative_policy not in {"absolute", "signed"}:
        raise FoundryError("materiality.relative negative_policy is unsupported")
    return {
        **cleaned,
        "relative": {
            "threshold": threshold_text,
            "denominator": denominator,
            "negative_policy": negative_policy,
        },
    }


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
        "state": _fact_state(value),
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
        signed_value = Decimal(exact.rstrip("%"))
        magnitude = abs(signed_value)
    except InvalidOperation:
        signed_value = Decimal(0)
        magnitude = Decimal(0)
    threshold = materiality.get("absolute", "0") if isinstance(materiality, dict) else "0"
    try:
        absolute_material = magnitude >= Decimal(str(threshold))
    except InvalidOperation:
        absolute_material = magnitude != 0
    relative = _relative_materiality(row, column, signed_value, magnitude, materiality)
    material = absolute_material or relative["is_material"]
    return {
        "role": role,
        "metric": row.get("metric") or column,
        "direction": "positive" if not exact.startswith("-") else "negative",
        "state": "observed_zero" if magnitude == 0 else "nonzero",
        "materiality": {
            "absolute": {
                "threshold": str(threshold),
                "is_material": absolute_material,
            },
            "relative": relative,
        },
        "required_for_explanation": (
            column not in {"actual", "baseline"}
            and material
            and magnitude != 0
            and role in {"amount", "ratio", "profit_impact", "value"}
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


def _relative_materiality(
    row: dict, column: str, signed_value: Decimal, magnitude: Decimal, materiality: dict
) -> dict:
    configured = materiality.get("relative") if isinstance(materiality, dict) else None
    if not configured:
        return {"enabled": False, "is_material": False, "status": "not_configured"}
    denominator = configured["denominator"]
    denominator_value = _relative_denominator(row, column, denominator)
    threshold = Decimal(configured["threshold"])
    payload = {
        "enabled": True,
        "threshold": configured["threshold"],
        "denominator": denominator,
        "negative_policy": configured["negative_policy"],
        "denominator_value": None,
        "ratio": None,
        "absolute_ratio": None,
        "is_material": False,
        "status": "not_applicable",
    }
    if denominator_value is None:
        return payload
    if denominator_value == 0:
        payload["denominator_value"] = "0"
        payload["status"] = "denominator_zero"
        return payload
    signed_denominator = denominator_value
    display_denominator = abs(denominator_value) if configured["negative_policy"] == "absolute" else denominator_value
    signed_ratio = signed_value / signed_denominator
    absolute_ratio = abs(magnitude) / abs(signed_denominator)
    ratio = absolute_ratio if configured["negative_policy"] == "absolute" else signed_ratio
    payload["denominator_value"] = format(display_denominator, "f")
    payload["ratio"] = format(ratio.normalize(), "f")
    payload["absolute_ratio"] = format(absolute_ratio.normalize(), "f")
    payload["is_material"] = absolute_ratio >= threshold
    payload["status"] = (
        "negative_denominator"
        if configured["negative_policy"] == "signed" and signed_denominator < 0
        else "complete"
    )
    return payload


def _relative_denominator(row: dict, column: str, denominator: str) -> Decimal | None:
    candidates: list[Decimal] = []
    for key in ("baseline", "actual"):
        value = row.get(key)
        if value is None:
            candidates.append(None)  # type: ignore[arg-type]
            continue
        try:
            candidates.append(Decimal(str(value)))
        except InvalidOperation:
            candidates.append(None)  # type: ignore[arg-type]
    baseline, actual = candidates if len(candidates) == 2 else (None, None)
    if denominator == "baseline_abs":
        return baseline
    if denominator == "actual_abs":
        return actual
    if denominator == "max_abs":
        values = [abs(v) for v in (baseline, actual) if v is not None]
        return max(values) if values else None
    return None


def _evidence_groups_for_run(run: dict, facts: list[dict]) -> list[dict]:
    result = run.get("result", {})
    rows = result.get("rows", [])
    columns = [
        c["name"] if isinstance(c, dict) else str(c)
        for c in result.get("columns", [])
    ]
    if not isinstance(rows, list):
        return []
    by_cell = {(fact["row"], fact["column"]): fact for fact in facts}
    method = result.get("method")
    if method == "revenue_minus_cost_minus_expense" or (
        {"contribution", "profit_impact"} & set(columns)
        and any(isinstance(row, dict) and row.get("metric") for row in rows)
    ):
        return _profit_bridge_groups(run, rows, columns, by_cell)
    if method in {"quantity_then_price", "base_weights_with_interaction"}:
        return [
            _row_evidence_group(
                run,
                index,
                row,
                columns,
                by_cell,
                group_type="price_quantity_bridge",
                member_columns=[
                    "total_variance",
                    "quantity_contribution",
                    "price_contribution",
                    "interaction",
                    "residual",
                    "actual",
                    "baseline",
                ],
            )
            for index, row in enumerate(rows)
            if isinstance(row, dict)
        ]
    return [
        _row_evidence_group(
            run,
            index,
            row,
            columns,
            by_cell,
            group_type="calculation_row",
            member_columns=[
                column
                for column in columns
                if column not in META_COLUMNS and column in row
            ],
        )
        for index, row in enumerate(rows)
        if isinstance(row, dict)
    ]


def _profit_bridge_groups(
    run: dict, rows: list[dict], columns: list[str], by_cell: dict
) -> list[dict]:
    grouped: dict[tuple, list[tuple[int, dict]]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        grouped.setdefault(_bridge_scope_key(row), []).append((index, row))
    groups = []
    for key, items in grouped.items():
        members = []
        for index, row in items:
            metric = row.get("metric", f"row_{index}")
            for column in (
                "contribution",
                "profit_impact",
                "amount_change",
                "actual",
                "baseline",
            ):
                members.append(
                    _evidence_member(
                        index,
                        row,
                        column,
                        columns,
                        by_cell,
                        semantic_role=f"{metric}.{column}",
                    )
                )
        label = "利润桥闭合依据"
        if key:
            label = f"{label} / " + " / ".join(f"{k}={v}" for k, v in key)
        groups.append(
            _group_payload(
                run,
                group_type="profit_bridge",
                label=label,
                members=members,
                row=None,
            )
        )
    return groups


def _row_evidence_group(
    run: dict,
    index: int,
    row: dict,
    columns: list[str],
    by_cell: dict,
    *,
    group_type: str,
    member_columns: list[str],
) -> dict:
    label = row.get("metric") or row.get("product") or f"结果行 {index + 1}"
    return _group_payload(
        run,
        group_type=group_type,
        label=str(label),
        members=[
            _evidence_member(index, row, column, columns, by_cell)
            for column in member_columns
        ],
        row=index,
    )


def _group_payload(
    run: dict, *, group_type: str, label: str, members: list[dict], row: int | None
) -> dict:
    factual = [m for m in members if m.get("fact_id")]
    missing = [m for m in members if m.get("state") == "missing"]
    closure = _closure_check(group_type, members)
    status = closure["status"] if closure["status"] != "passed" else "complete"
    if missing:
        status = "missing_data"
    return {
        "id": _hash(
            {
                "kind": "finance-evidence-group-v1",
                "run_id": run["id"],
                "output_hash": run.get("output_hash"),
                "group_type": group_type,
                "row": row,
                "label": label,
            }
        ),
        "run_id": run["id"],
        "group_type": group_type,
        "label": label,
        "row": row,
        "status": status,
        "closure": closure,
        "members": members,
        "fact_ids": [m["fact_id"] for m in factual],
    }


def _evidence_member(
    row_index: int,
    row: dict,
    column: str,
    columns: list[str],
    by_cell: dict,
    *,
    semantic_role: str | None = None,
) -> dict:
    fact = by_cell.get((row_index, column))
    state = _cell_state(row, column, columns)
    payload = {
        "row": row_index,
        "column": column,
        "semantic_role": semantic_role or column,
        "label": _label(row, column),
        "state": state,
        "fact_id": fact["id"] if fact else None,
        "value": fact["value"] if fact else None,
        "display_value": fact["display_value"] if fact else None,
        "unit": fact.get("unit") if fact else row.get("unit"),
        "scope": _row_scope(row),
        "source_row_count": (
            fact.get("source_trace", {}).get("source_row_count") if fact else 0
        ),
    }
    if state in {"missing", "not_applicable"}:
        payload["reason"] = (
            "结果列存在但本行未产生可核验数值"
            if state == "missing"
            else "当前计算方法未定义该分项"
        )
    return payload


def _cell_state(row: dict, column: str, columns: list[str]) -> str:
    if column not in columns:
        return "not_applicable"
    value = row.get(column)
    if value is None:
        return "missing"
    return _fact_state(value)


def _fact_state(value: Any) -> str:
    try:
        return "observed_zero" if Decimal(str(value)) == 0 else "nonzero"
    except InvalidOperation:
        return "missing"


def _state_label(state: str) -> str:
    return {
        "observed_zero": "已计算为零",
        "nonzero": "已计算",
        "missing": "缺少数据",
        "not_applicable": "不适用",
    }.get(state, str(state))


def _fact_state_counts(facts: list[dict]) -> dict:
    counts = {"nonzero": 0, "observed_zero": 0}
    for fact in facts:
        state = fact.get("state", fact.get("semantics", {}).get("state", "nonzero"))
        counts[state] = counts.get(state, 0) + 1
    return counts


def _evidence_group_statuses(groups: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        status = str(group.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _closure_check(group_type: str, members: list[dict]) -> dict:
    if group_type == "profit_bridge":
        return _profit_bridge_closure(members)
    if group_type == "price_quantity_bridge":
        return _price_quantity_closure(members)
    return {"status": "unsupported", "equation": None, "message": "未声明可复算闭合规则"}


def _profit_bridge_closure(members: list[dict]) -> dict:
    contribution = {
        str(member.get("semantic_role", "")).split(".", 1)[0]: member
        for member in members
        if member.get("column") == "contribution"
    }
    required = ("revenue", "cost", "expense", "profit")
    missing = [
        metric
        for metric in required
        if contribution.get(metric, {}).get("value") is None
    ]
    if missing:
        return {
            "status": "missing_data",
            "equation": "profit = revenue + cost + expense",
            "missing": missing,
        }
    consistency = _member_consistency([contribution[metric] for metric in required])
    if consistency:
        return consistency
    values = {metric: Decimal(str(contribution[metric]["value"])) for metric in required}
    expected = values["revenue"] + values["cost"] + values["expense"]
    difference = values["profit"] - expected
    return {
        "status": "passed" if difference == 0 else "closure_mismatch",
        "equation": "profit = revenue + cost + expense",
        "expected": format(expected, "f"),
        "actual": format(values["profit"], "f"),
        "difference": format(difference, "f"),
        "inputs": {metric: format(value, "f") for metric, value in values.items()},
    }


def _price_quantity_closure(members: list[dict]) -> dict:
    by_column = {member.get("column"): member for member in members}
    required = ("quantity_contribution", "price_contribution", "interaction", "residual", "total_variance")
    missing = [
        column for column in required if by_column.get(column, {}).get("value") is None
    ]
    if missing:
        return {
            "status": "missing_data",
            "equation": "total_variance = quantity_contribution + price_contribution + interaction + residual",
            "missing": missing,
        }
    consistency = _member_consistency([by_column[column] for column in required])
    if consistency:
        return consistency
    values = {column: Decimal(str(by_column[column]["value"])) for column in required}
    expected = (
        values["quantity_contribution"]
        + values["price_contribution"]
        + values["interaction"]
        + values["residual"]
    )
    difference = values["total_variance"] - expected
    return {
        "status": "passed" if difference == 0 else "closure_mismatch",
        "equation": "total_variance = quantity_contribution + price_contribution + interaction + residual",
        "expected": format(expected, "f"),
        "actual": format(values["total_variance"], "f"),
        "difference": format(difference, "f"),
        "inputs": {column: format(value, "f") for column, value in values.items()},
    }


def _member_consistency(members: list[dict]) -> dict | None:
    units = {member.get("unit") for member in members if member.get("unit")}
    if len(units) > 1:
        return {
            "status": "unit_mismatch",
            "equation": None,
            "units": sorted(str(unit) for unit in units),
        }
    scopes = {
        tuple(sorted((member.get("scope") or {}).items()))
        for member in members
        if member.get("scope")
    }
    if len(scopes) > 1:
        return {
            "status": "scope_mismatch",
            "equation": None,
            "scopes": [dict(scope) for scope in sorted(scopes, key=repr)],
        }
    return None


def _bridge_scope_key(row: dict) -> tuple:
    skip = (
        MONEY_COLUMNS
        | RATIO_COLUMNS
        | META_COLUMNS
        | {
            "profit_impact",
            "quantity_contribution",
            "price_contribution",
            "amount_change",
            "amount_change_display",
            "profit_impact_display",
            "total_variance",
            "interaction",
            "residual",
            "display_value",
            "evidence",
            "source_rows",
            "semantics",
            "actual_scope",
            "baseline_scope",
        }
    )
    return tuple(
        sorted(
            (key, str(value))
            for key, value in row.items()
            if key not in skip and value not in (None, "")
        )
    )


def _row_scope(row: dict) -> dict:
    scope = {}
    for key in ("ledger", "organization", "period", "currency"):
        if row.get(key) not in (None, ""):
            scope[key] = str(row[key])
    for side in ("actual_scope", "baseline_scope"):
        if isinstance(row.get(side), dict):
            for key in ("ledger", "organization", "period", "currency"):
                value = row[side].get(key)
                if value not in (None, ""):
                    scope[f"{side}.{key}"] = str(value)
    return scope


def _closure_label(closure: dict) -> str:
    status = closure.get("status")
    if status == "passed":
        return (
            f"通过，{closure.get('equation')}，"
            f"实际 {closure.get('actual')}，复算 {closure.get('expected')}，差额为零"
        )
    return {
        "closure_mismatch": (
            f"不匹配，{closure.get('equation')}，实际 {closure.get('actual')}，"
            f"复算 {closure.get('expected')}，差额 {closure.get('difference')}"
        ),
        "scope_mismatch": "范围不一致",
        "unit_mismatch": "单位不一致",
        "missing_data": "缺少闭合所需数据",
    }.get(str(status), str(status))


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
