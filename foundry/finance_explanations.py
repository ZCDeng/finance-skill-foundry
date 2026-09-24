"""Deterministic explanation facts and draft checks for finance analysis."""

from __future__ import annotations

import re
import hashlib
from datetime import date, datetime, timezone
from calendar import monthrange
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any

from foundry.analysis import BASIS, _hash, _safe_text
from foundry.analysis_data import json_value
from foundry.errors import FoundryError

FACT_TOKEN = re.compile(r"\{\{fact:([0-9a-f]{64})\}\}")
NUMBER = re.compile(r"(?<![A-Za-z0-9_.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![A-Za-z0-9_.])")
CLOSURE_EXPR = re.compile(r"(?P<expr>[-+]?\d+(?:\.\d+)?(?:\s*[+\-−]\s*\d+(?:\.\d+)?)+\s*=\s*[-+]?\d+(?:\.\d+)?)")
DATE_SPAN = re.compile(r"\b\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2})?")
FACT_ID = re.compile(r"^[0-9a-f]{64}$")
PERIOD_OR_DATE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
EVIDENCE_APPENDIX_RENDER_VERSION = 1
WRITING_GUIDANCE = {
    "schema_version": 1,
    "summary": (
        "管理层财务文稿应先给短结论，再用比较表或条列承接驱动；"
        "完整公式独立成段，来源定位用章节末附注。"
    ),
    "rules": [
        "每段只写一个主题，开头用一到两个短段说明结论和重大财务影响。",
        "把 {{fact:FACT_ID}} 保留在对应数字、公式或表格位置；它是数值占位符，不是引用编号。",
        "多个驱动、条件或不确定性使用条列或比较表，条件贴近相关判断。",
        "完整公式、桥接计算和口径说明独立成段或小表，不塞进长句。",
        "来源定位使用章节末附注 [^n]；不得补造原因、行动、空值或未授权来源。",
    ],
}

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
RATIO_COLUMNS = {"ratio", "ratio_exact", "cost_rate_pct", "gross_margin_pct"}
MONEY_UNIT_SEGMENTS = {"万元", "元", "亿元", "千元", "百万元"}
MONEY_TOKENS = {
    "amount", "revenue", "cost", "expense", "profit", "cash",
    "budget", "actual", "variance", "sales", "income",
}
EXACT_VALUE_COLUMNS = {"numerator_exact", "denominator_exact", "ratio_exact"}
COUNT_COLUMNS = {"row_count"}
QUANTITY_COLUMNS = {"quantity", "actual_quantity", "baseline_quantity", "quantity_change"}
UNIT_PRICE_COLUMNS = {"price", "unit_price", "actual_price", "baseline_price", "price_change"}
META_COLUMNS = {
    "ledger",
    "organization",
    "period",
    "account_id",
    "account_code",
    "management_account",
    "scenario",
    "currency",
    "unit",
    "metric",
    "basis",
    "favorability",
    "comparison_status",
    "ratio_status",
    "display_value",
    "ratio_display",
    "numerator_display",
    "denominator_display",
    "quantity_unit",
    "price_unit",
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
        "writing_guidance": WRITING_GUIDANCE,
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
        display = fact["display_value"]
        unit = str(fact.get("unit") or "")
        # The manager writes 「期间费用 {{fact:…}} 元」 because that is how the
        # sentence reads, and the fact already carries 元. Appending it again
        # printed 「53,262,500 元 元」. Where the prose says the unit, the prose
        # keeps it.
        if unit and display.endswith(f" {unit}") and _unit_follows(body, match.end(), unit):
            return display[: -len(unit)].rstrip()
        return display

    return FACT_TOKEN.sub(replace, body), used


def _unit_follows(body: str, position: int, unit: str) -> bool:
    """Whether the prose right after the token writes this unit as a word.

    「元」 is a prefix of 「元币」 and 「元旦」, so the unit only counts when what
    follows it is not more of a word.
    """
    return re.match(rf"\s*{re.escape(unit)}(?![\w\u4e00-\u9fff])", body[position:]) is not None


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
    facts_by_id = {
        fact["id"]: fact
        for fact in prepared.get("facts", [])
        if isinstance(fact, dict)
        and isinstance(fact.get("id"), str)
        and FACT_ID.fullmatch(fact["id"])
    }
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
            fact = _appendix_member_fact(group, member, facts_by_id)
            state = fact.get("state") if fact else member.get("state", "missing")
            label = member.get("label") or member.get("semantic_role") or member.get("column")
            value = fact.get("display_value") if fact else None
            suffix = f"：{value}" if value not in (None, "") else ""
            if fact:
                fact_ids.append(fact["id"])
            source_count = (
                fact.get("source_trace", {}).get("source_row_count")
                if fact
                else member.get("source_row_count")
            )
            source = (
                "；有来源行"
                if fact and isinstance(source_count, int) and source_count > 0
                else ""
            )
            lines.append(f"- {label}{suffix}（{_appendix_member_label(state, fact)}{source}）")
        closure = group.get("closure")
        if isinstance(closure, dict) and closure.get("status") != "unsupported":
            lines.append(f"- 闭合核对：{_closure_label(closure)}")
    unique_fact_ids = list(dict.fromkeys(fact_ids))
    return {
        "schema_version": EVIDENCE_APPENDIX_RENDER_VERSION,
        "body": "\n".join(lines).strip() if len(lines) > 1 else "",
        "fact_ids": unique_fact_ids,
        "claims": claims_for_facts(
            prepared.get("facts", []), unique_fact_ids
        ),
    }


def evidence_appendix_metadata(body: str, *, base_body: str | None = None) -> dict:
    if not isinstance(body, str):
        raise FoundryError("evidence appendix body must be text")
    base = body if base_body is None else base_body
    if not isinstance(base, str):
        raise FoundryError("evidence appendix base body must be text")
    return {
        "schema_version": 1,
        "render_version": EVIDENCE_APPENDIX_RENDER_VERSION,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "base_body_sha256": hashlib.sha256(base.encode("utf-8")).hexdigest(),
        "body_chars": len(body),
    }


def _appendix_member_fact(group: dict, member: dict, facts_by_id: dict[str, dict]) -> dict | None:
    fact_id = member.get("fact_id")
    if not isinstance(fact_id, str):
        return None
    fact = facts_by_id.get(fact_id)
    if not fact:
        return None
    if group.get("run_id") is not None and fact.get("run_id") != group.get("run_id"):
        return None
    for key in ("row", "column"):
        if member.get(key) is not None and member.get(key) != fact.get(key):
            return None
    if member.get("value") is not None and not _decimal_equal(member.get("value"), fact.get("value")):
        return None
    if member.get("unit") is not None and member.get("unit") != fact.get("unit"):
        return None
    if member.get("state") is not None and member.get("state") != fact.get("state"):
        return None
    if not _appendix_scope_matches(member.get("scope"), fact.get("scope")):
        return None
    if (
        member.get("display_value") is not None
        and member.get("display_value") != fact.get("display_value")
    ):
        return None
    return fact


def _appendix_scope_matches(member_scope: Any, fact_scope: Any) -> bool:
    if not isinstance(member_scope, dict) or not member_scope:
        return True
    if not isinstance(fact_scope, dict) or not fact_scope:
        return False
    for key, value in member_scope.items():
        if value in (None, ""):
            continue
        if _appendix_scope_value(fact_scope, key) != value:
            return False
    return True


def _appendix_scope_value(fact_scope: dict, key: str) -> Any:
    if key in fact_scope:
        return fact_scope.get(key)
    if key.startswith("actual_scope."):
        return _appendix_nested_scope_value(
            fact_scope, ("actual",), key.removeprefix("actual_scope.")
        )
    if key.startswith("baseline_scope."):
        return _appendix_nested_scope_value(
            fact_scope, ("baseline", "budget"), key.removeprefix("baseline_scope.")
        )
    nested_values = [
        scope.get(key)
        for scope in fact_scope.values()
        if isinstance(scope, dict) and key in scope
    ]
    if nested_values and all(value == nested_values[0] for value in nested_values):
        return nested_values[0]
    return None


def _appendix_nested_scope_value(fact_scope: dict, aliases: tuple[str, ...], key: str) -> Any:
    for alias in aliases:
        scope = fact_scope.get(alias)
        if isinstance(scope, dict) and key in scope:
            return scope.get(key)
    return None


def _appendix_member_label(state: str, fact: dict | None) -> str:
    if fact:
        return _state_label(state)
    if state in {"missing", "not_applicable"}:
        return _state_label(state)
    return "非可引用：未生成可核验事实"


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
    generated_regions = _trusted_generated_appendix_regions(
        analysis, body, {**draft, **spec}, prepared
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
        _fact_context_issues(
            body,
            [by_id[f] for f in referenced if f in by_id],
            prepared.get("evidence_groups", []),
        )
    )
    presentation = _presentation_allowed_numbers_and_issues(claims, by_id)
    issues.extend(presentation["issues"])
    base_allowed_numbers = _allowed_numbers(
        [by_id[fact_id] for fact_id in referenced if fact_id in by_id]
    )
    ignored_number_spans = _generated_appendix_heading_number_spans(body, prepared)
    for token in _body_numbers(body, ignored_spans=ignored_number_spans):
        normalized = _normalize_number(token["text"])
        if normalized in base_allowed_numbers:
            continue
        if normalized in presentation["numbers"] and _presentation_token_unit_matches(body, token, presentation["numbers"][normalized]):
            continue
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
    merged = {**draft, **spec, "run_ids": run_ids}
    evidence_recipes = merged.get("evidence_recipes", [])
    consistency_rules = merged.get("consistency_rules", [])
    consistency_sources = merged.get("consistency_sources", {})
    from foundry.analysis import _quality_status_dimensions, _revision_quality_issues
    from foundry.finance_revision import compare_draft_runs
    from foundry.financial_consistency import consistency_quality_issues, evaluate_consistency_rules
    from foundry.financial_evidence import evaluate_evidence_recipes, prepare_consistency_inputs

    parent = analysis.get_draft(merged["parent_id"]) if merged.get("parent_id") else {}
    revision_comparison = compare_draft_runs(analysis, parent, {"run_ids": run_ids})
    evidence_report = evaluate_evidence_recipes(analysis, evidence_recipes)
    resolved_rules, consistency_source_auth = prepare_consistency_inputs(
        analysis, consistency_rules, consistency_sources
    )
    consistency_report = evaluate_consistency_rules(
        resolved_rules,
        recipe_report=evidence_report,
        source_auth=consistency_source_auth,
    )
    issues.extend(_revision_quality_issues(revision_comparison))
    issues.extend(evidence_report.get("issues", []))
    issues.extend(consistency_quality_issues(consistency_report))
    execution_status = (
        "succeeded"
        if runs and all(run.get("execution_status") == "succeeded" for run in runs)
        else "failed"
        if runs
        else "not_run"
    )
    stored_review = draft.get("review_status", "unreviewed") if draft else "unreviewed"
    effective_review = stored_review if draft and body == draft.get("body") and claims == draft.get("claims", []) else "unreviewed"
    status_dimensions = _quality_status_dimensions(
        execution_status=execution_status,
        review_status=effective_review,
        quality_issues=issues,
        evidence_report=evidence_report,
        consistency_report=consistency_report,
        numeric_configured=bool(run_ids or claims or fact_ids),
    )
    status = "pass" if not issues else "needs_attention"
    issues = _locate_issues(issues, generated_regions)
    readability = _readability_suggestions(body, generated_regions)
    return {
        "schema_version": 1,
        "status": status,
        "issues": [issue for issue in issues if issue],
        "status_dimensions": status_dimensions,
        "evidence_report": evidence_report,
        "consistency_report": consistency_report,
        "revision_comparison": revision_comparison,
        "readability": readability,
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
    column_defs = _column_defs(result)
    columns = list(column_defs)
    facts: list[dict] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        for column in columns:
            if not _include_fact_column(row, column, column_defs):
                continue
            value = row.get(column)
            if not _is_fact_value(value, column):
                continue
            fact = _make_fact(run, row_index, row, column, value, materiality, column_defs)
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



def _locator_trace(refs) -> dict:
    if not isinstance(refs, list):
        return {"preview_available": False}
    for ref in refs:
        if isinstance(ref, dict) and isinstance(ref.get("source_locator"), dict):
            locator = {
                key: value
                for key, value in ref["source_locator"].items()
                if key not in {"path", "url", "file"}
                and not (isinstance(value, str) and ("/" in value or "\\" in value or "file://" in value))
            }
            return {
                "source_locator": locator,
                "preview_available": bool(locator.get("preview_available")),
            }
    return {"preview_available": False}


def _make_fact(
    run: dict,
    row_index: int,
    row: dict,
    column: str,
    value: Any,
    materiality: dict,
    column_defs: dict[str, dict],
) -> dict:
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
    unit = _fact_unit(row, column, column_defs, run)
    display = _display_value(exact, column, unit)
    semantics = _semantics(row, column, exact, materiality)
    refs = row.get("evidence", {}).get(column, row.get("source_rows", []))
    scope = run.get("finance_scope", {})
    if run.get("engine") == "structured_aggregate":
        dimensions = [*run.get("aggregate_plan", {}).get("group_by", []), "currency", "unit"]
        scope = {**scope, **{key: row[key] for key in dimensions if key in row}}
    return {
        "id": fact_id,
        "run_id": run["id"],
        "analysis_id": run.get("analysis_id"),
        "row": row_index,
        "column": column,
        "value": exact,
        "display_value": display,
        "label": _label(row, column),
        "unit": unit,
        "scope": scope,
        "semantics": semantics,
        "state": _fact_state(value),
        "source_trace": {
            "output_hash": run.get("output_hash"),
            "input_hashes": run.get("input_hashes", {}),
            "source_hashes": run.get("source_hashes", {}),
            "source_rows": refs,
            "source_row_count": len(refs) if isinstance(refs, list) else 0,
            **_locator_trace(refs),
            "provenance_status": (
                run.get("result", {}).get("provenance", {}).get("status", "unverified")
                if run.get("engine") == "structured_aggregate" else
                "available_for_verification" if run.get("engine") == "finance" else "unverified"
            ),
        },
    }


def _semantics(row: dict, column: str, exact: str, materiality: dict) -> dict:
    role = _fact_role(column)
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
        "metric": _row_metric(row, column),
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
            and role in {
                "amount",
                "ratio",
                "profit_impact",
                "count",
                "quantity",
                "unit_price",
                "value",
            }
        ) or (magnitude == 0 and column in {
            "contribution",
            "profit_impact",
            "total_variance",
            "interaction",
            "residual",
        }),
    }


def _fact_role(column: str) -> str:
    if _is_ratio_column(column):
        return "ratio"
    if _is_count_column(column):
        return "count"
    if column in QUANTITY_COLUMNS:
        return "quantity"
    if column in UNIT_PRICE_COLUMNS:
        return "unit_price"
    if _is_amount_column(column):
        return "amount"
    return "value"


def _column_tokens(column: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", column.lower()) if token}


def _is_ratio_column(column: str) -> bool:
    lowered = column.lower()
    tokens = _column_tokens(column)
    return (
        column in RATIO_COLUMNS
        or lowered.endswith("_pct")
        or bool(tokens & {"ratio", "rate", "pct", "percent", "percentage"})
        or "比率" in column
        or "达成率" in column
        or "完成率" in column
        or column.endswith("率")
        # 汇率_影响_万元 names a 率 driver but holds money; the money word wins.
        or (
            any(segment.endswith("率") for segment in _column_segments(column))
            and not _names_money(column)
        )
    )


def _column_segments(column: str) -> list[str]:
    """营业利润_差异率_同口径 -> [营业利润, 差异率, 同口径]; the unit word can sit mid-name."""
    return [segment for segment in re.split(r"[_\-\s/]+", column) if segment]


def _names_money(column: str) -> bool:
    """A money unit segment (…_万元) or an English amount word (revenue_…) says the column is money."""
    return bool(_column_tokens(column) & MONEY_TOKENS) or any(
        segment in MONEY_UNIT_SEGMENTS for segment in _column_segments(column)
    )


def _is_day_column(column: str) -> bool:
    if _names_money(column):
        return False  # revenue_last_30_days, 应收_逾期_90_天_万元: money over a day window
    segments = _column_segments(column)
    return bool(_column_tokens(column) & {"days", "dso"}) or any(
        "天数" in segment or segment == "天" for segment in segments
    )


def _is_amount_column(column: str) -> bool:
    if column in MONEY_COLUMNS or column in {"numerator_exact", "denominator_exact"}:
        return True
    if _is_ratio_column(column) or _is_count_column(column) or _is_day_column(column):
        return False
    tokens = _column_tokens(column)
    if tokens & {"amount", "revenue", "cost", "expense", "profit", "cash", "budget", "actual", "variance"}:
        return True
    if any(segment in MONEY_UNIT_SEGMENTS for segment in _column_segments(column)):
        return True
    return any(
        token in column
        for token in (
            "收入",
            "成本",
            "费用",
            "利润",
            "毛利",
            "减值",
            "损益",
            "收益",
            "现金",
            "应收",
            "预算",
            "实际",
            "差异",
            "缺口",
        )
    )


def _row_unit(row: dict) -> Any:
    for key in ("unit", "单位"):
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _run_scope_unit(run: dict | None) -> Any:
    if not isinstance(run, dict):
        return None
    for scope_key in ("scope", "finance_scope"):
        scope = run.get(scope_key)
        if not isinstance(scope, dict):
            continue
        direct = scope.get("unit") or scope.get("单位")
        if direct not in (None, ""):
            return direct
        nested_units = [
            item.get("unit") or item.get("单位")
            for item in scope.values()
            if isinstance(item, dict) and (item.get("unit") or item.get("单位")) not in (None, "")
        ]
        if nested_units and all(unit == nested_units[0] for unit in nested_units):
            return nested_units[0]
    return None


def _named_money_unit(column: str) -> str | None:
    """单方物业费_元 in a 万元 run is still 元: a unit the column name states beats the row/scope unit."""
    named = [segment for segment in _column_segments(column) if segment in MONEY_UNIT_SEGMENTS]
    return named[-1] if named else None


def _amount_unit(row: dict, column: str, column_defs: dict[str, dict], run: dict | None) -> Any:
    return (
        row.get(f"{column}_unit")
        or _named_money_unit(column)
        or _row_unit(row)
        or column_defs.get(column, {}).get("unit")
        or _run_scope_unit(run)
    )


def _fact_unit(row: dict, column: str, column_defs: dict[str, dict], run: dict | None = None) -> Any:
    if _is_ratio_column(column):
        return "%"
    if _is_count_column(column):
        return row.get(f"{column}_unit") or "条"
    if _is_day_column(column):
        return row.get(f"{column}_unit") or "天"
    if column in QUANTITY_COLUMNS:
        return (
            row.get(f"{column}_unit")
            or row.get("quantity_unit")
            or column_defs.get(column, {}).get("unit")
        )
    if column in UNIT_PRICE_COLUMNS:
        return (
            row.get(f"{column}_unit")
            or row.get("price_unit")
            or column_defs.get(column, {}).get("unit")
        )
    if _is_amount_column(column):
        return _amount_unit(row, column, column_defs, run)
    if column == "value" and _row_unit(row) not in (None, ""):
        return _row_unit(row)
    return column_defs.get(column, {}).get("unit")


def _display_value(exact: str, column: str, unit: Any) -> str:
    if _is_ratio_column(column):
        try:
            percent = (
                Decimal(exact)
                if column.endswith("_pct")
                else Decimal(exact) * Decimal(100)
            )
            return f"{percent.quantize(Decimal('0.01'))}%"
        except InvalidOperation:
            return exact
    suffix = f" {unit}" if unit else ""
    return f"{_grouped(exact, column)}{suffix}"


def _grouped(exact: str, column: str) -> str:
    """Money with thousands separators. 53,262,500 is read; 53262500 is counted.

    The exact value is what every check compares against, so the separators are
    a display choice and nothing else reads this string as a number.
    """
    if not _is_amount_column(column):
        return exact
    try:
        value = Decimal(exact)
    except InvalidOperation:
        return exact
    whole, _, fraction = exact.partition(".")
    del whole
    grouped = f"{value:,f}" if fraction else f"{value:,}"
    return grouped


def _label(row: dict, column: str) -> str:
    parts = [str(_row_metric(row, column))]
    if column != parts[0]:
        parts.append(column)
    for key in ("scenario", "period"):
        if row.get(key):
            parts.append(str(row[key]))
    return " / ".join(parts)


def _row_metric(row: dict, column: str) -> str:
    metric = row.get("metric")
    if metric not in (None, ""):
        return str(metric)
    metric_key = row.get("metric_key")
    if metric_key not in (None, ""):
        return str(metric_key)
    return column


def _is_fact_value(value: Any, column: str) -> bool:
    if (
        column in MONEY_COLUMNS
        or column in RATIO_COLUMNS
        or column in EXACT_VALUE_COLUMNS
        or _is_count_column(column)
        or column in QUANTITY_COLUMNS
        or column in UNIT_PRICE_COLUMNS
    ):
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


def _column_defs(result: dict) -> dict[str, dict]:
    definitions = {}
    for item in result.get("columns", []):
        if isinstance(item, dict):
            name = str(item.get("name", ""))
            if name:
                definitions[name] = item
        else:
            definitions[str(item)] = {"name": str(item)}
    return definitions


def _column_type(column_defs: dict[str, dict], column: str) -> str:
    return str(column_defs.get(column, {}).get("type") or "").upper()


def _is_decimal_column_type(column_type: str) -> bool:
    normalized = column_type.split("(", 1)[0].strip().upper()
    first = normalized.split()[0] if normalized else ""
    return normalized == "DOUBLE PRECISION" or first in {
        "BIGINT",
        "DECIMAL",
        "DOUBLE",
        "FLOAT",
        "HUGEINT",
        "INT",
        "INTEGER",
        "NUMERIC",
        "REAL",
        "SMALLINT",
        "TINYINT",
        "UBIGINT",
        "UHUGEINT",
        "UINTEGER",
        "USMALLINT",
        "UTINYINT",
    }


def _is_count_column(column: str) -> bool:
    return column in COUNT_COLUMNS or column.endswith("_count")


def _include_generic_member(row: dict, column: str, column_defs: dict[str, dict]) -> bool:
    if column in META_COLUMNS or column not in row:
        return False
    column_type = _column_type(column_defs, column)
    if column_type:
        return _is_decimal_column_type(column_type) or _is_count_column(column)
    value = row.get(column)
    if value is None:
        return column in MONEY_COLUMNS or column in RATIO_COLUMNS or _is_count_column(column)
    return _is_fact_value(value, column)


def _include_fact_column(row: dict, column: str, column_defs: dict[str, dict]) -> bool:
    if column in META_COLUMNS or column not in row or row.get(column) is None:
        return False
    column_type = _column_type(column_defs, column)
    if not column_type:
        return _is_fact_value(row.get(column), column)
    if _is_decimal_column_type(column_type):
        return True
    return (
        column
        in (
            MONEY_COLUMNS
            | RATIO_COLUMNS
            | EXACT_VALUE_COLUMNS
            | QUANTITY_COLUMNS
            | UNIT_PRICE_COLUMNS
        )
        or _is_count_column(column)
    ) and _is_fact_value(row.get(column), column)


def _is_ratio_result(columns: list[str]) -> bool:
    return {"numerator", "denominator", "ratio"} <= set(columns)


def _evidence_groups_for_run(run: dict, facts: list[dict]) -> list[dict]:
    result = run.get("result", {})
    rows = result.get("rows", [])
    column_defs = _column_defs(result)
    columns = list(column_defs)
    if not isinstance(rows, list):
        return []
    by_cell = {(fact["row"], fact["column"]): fact for fact in facts}
    method = result.get("method")
    if method == "revenue_minus_cost_minus_expense" or (
        {"contribution", "profit_impact"} & set(columns)
        and any(isinstance(row, dict) and row.get("metric") for row in rows)
    ):
        return _profit_bridge_groups(run, rows, columns, by_cell)
    if _is_ratio_result(columns):
        return [
            _row_evidence_group(
                run,
                index,
                row,
                columns,
                by_cell,
                group_type="ratio",
                member_columns=["numerator", "denominator", "ratio"],
            )
            for index, row in enumerate(rows)
            if isinstance(row, dict)
        ]
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
                if _include_generic_member(row, column, column_defs)
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
        "semantic_role": semantic_role or (fact.get("semantics", {}).get("role") if fact else _fact_role(column)),
        "label": _label(row, column),
        "state": state,
        "fact_id": fact["id"] if fact else None,
        "value": fact["value"] if fact else None,
        "display_value": fact["display_value"] if fact else None,
        "unit": fact.get("unit") if fact else _row_unit(row),
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
        if column == "ratio" and row.get("numerator") is not None and _is_zero(row.get("denominator")):
            return "not_applicable"
        return "missing"
    return _fact_state(value)


def _is_zero(value: Any) -> bool:
    try:
        return Decimal(str(value)) == 0
    except InvalidOperation:
        return False


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
    if group_type == "ratio":
        return _ratio_closure(members)
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


def _ratio_closure(members: list[dict]) -> dict:
    by_column = {member.get("column"): member for member in members}
    numerator = by_column.get("numerator")
    denominator = by_column.get("denominator")
    ratio = by_column.get("ratio")
    missing = [
        column
        for column, member in (("numerator", numerator), ("denominator", denominator))
        if not member or member.get("value") is None
    ]
    if missing:
        return {
            "status": "missing_data",
            "equation": "ratio = numerator / denominator",
            "missing": missing,
        }
    amount_consistency = _member_consistency([numerator, denominator])
    if amount_consistency:
        return amount_consistency
    scope_consistency = _scope_consistency([m for m in (numerator, denominator, ratio) if m])
    if scope_consistency:
        return scope_consistency
    numerator_value = Decimal(str(numerator["value"]))
    denominator_value = Decimal(str(denominator["value"]))
    inputs = {
        "numerator": format(numerator_value, "f"),
        "denominator": format(denominator_value, "f"),
    }
    if denominator_value == 0:
        if ratio and ratio.get("value") is not None:
            return {
                "status": "closure_mismatch",
                "equation": "ratio = numerator / denominator",
                "expected": None,
                "actual": str(ratio.get("value")),
                "difference": None,
                "inputs": inputs,
                "denominator_status": "zero",
            }
        return {
            "status": "not_applicable",
            "equation": "ratio = numerator / denominator",
            "expected": None,
            "actual": None,
            "difference": None,
            "inputs": inputs,
            "denominator_status": "zero",
        }
    if not ratio or ratio.get("value") is None:
        return {
            "status": "missing_data",
            "equation": "ratio = numerator / denominator",
            "missing": ["ratio"],
            "inputs": inputs,
        }
    actual = Decimal(str(ratio["value"]))
    with localcontext() as context:
        context.prec = max(28, len(actual.as_tuple().digits))
        expected = numerator_value / denominator_value
        difference = actual - expected
    return {
        "status": "passed" if difference == 0 else "closure_mismatch",
        "equation": "ratio = numerator / denominator",
        "expected": format(expected, "f"),
        "actual": format(actual, "f"),
        "difference": format(difference, "f"),
        "inputs": inputs,
        "denominator_status": "negative" if denominator_value < 0 else "positive",
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
    return _scope_consistency(members)


def _scope_consistency(members: list[dict]) -> dict | None:
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


def _fact_context_issues(body: str, facts: list[dict], evidence_groups: list[dict] | None = None) -> list[dict]:
    """Match complete numeric tokens to a compatible fact within their clause.

    A shared number is not an identity: select by the nearest financial label,
    then validate its unit and change semantics. Never match 5 inside 15.
    """
    issues = []
    closure_check = _body_closure_check(body, facts, evidence_groups or [])
    issues.extend(closure_check["issues"])
    closure_token_positions = closure_check["token_positions"]
    for token in _body_numbers(body):
        if token["start"] in closure_token_positions:
            continue
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
            issues.append({
                'code': 'fact_label_mismatch',
                'severity': 'warning',
                'message': '正文指标与同值引用事实不一致。',
                'position': start,
                'text': token['text'],
                'body_excerpt': _body_excerpt(body, start),
                'expected_metric': metric,
                'matched_fact_labels': [str(f.get('label')) for f in candidates],
                'matched_semantic_roles': [str(f.get('semantics', {}).get('role')) for f in candidates],
                'matched_fact_metrics': [str(f.get('semantics', {}).get('metric')) for f in candidates],
            })
            labelled = candidates
        alternatives = []
        for fact in labelled:
            found = []
            unit_match = re.match(r"\s*(亿元|万元|元/件|元|%|条|件)", body[end:])
            if unit_match and unit_match[1] != fact.get('unit'):
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


def _body_closure_check(body: str, facts: list[dict], evidence_groups: list[dict]) -> dict:
    token_positions: set[int] = set()
    issues: list[dict] = []
    if not facts:
        return {"token_positions": token_positions, "issues": issues}
    for match in CLOSURE_EXPR.finditer(body):
        span_start, span_end = match.span("expr")
        context = body[max(0, span_start - 40): min(len(body), span_end + 30)]
        if not any(marker in context for marker in ("闭合", "合计", "等式", "一致")):
            continue
        if not _has_closure_expression_boundaries(body, span_start, span_end):
            continue
        target_group_types = _closure_target_group_types(body, span_start)
        if not target_group_types:
            continue
        parsed = _parse_signed_closure_expression(match.group("expr"))
        if not parsed:
            continue
        matching_group = (
            _matching_body_closure_group(parsed, facts, evidence_groups, target_group_types)
            if parsed["balanced"]
            else None
        )
        if matching_group:
            for token in _body_numbers(body[span_start:span_end]):
                token_positions.add(span_start + token["start"])
            continue
        issues.append({
            "code": "body_closure_mismatch",
            "severity": "warning",
            "message": "正文闭合算式未能匹配同一完整且已闭合的证据组。",
            "position": span_start,
            "text": match.group("expr"),
            "body_excerpt": _body_excerpt(body, span_start),
            "target_group_types": sorted(target_group_types),
        })
    return {"token_positions": token_positions, "issues": issues}


def _has_closure_expression_boundaries(body: str, start: int, end: int) -> bool:
    before = body[:start].rstrip()[-1:]
    after = body[end:].lstrip()[:1]
    valid_before = before in {"", "（", "(", "[", ":", "：", " ", "，", ",", "；", ";", "。", "\n"}
    valid_after = after in {"", "）", ")", "]", "，", ",", "；", ";", "。", "\n"}
    return valid_before and valid_after


def _closure_target_group_types(body: str, start: int) -> set[str]:
    prefix = re.split(r"[。；;\n]", body[max(0, start - 80):start])[-1]
    metric_matches = [
        (prefix.rfind(label), key)
        for key, label in METRIC_LABELS.items()
        if label in prefix
    ]
    metric = max(metric_matches)[1] if metric_matches else None
    if metric in {None, "revenue"} and re.search(r"量价|price[-_ ]?quantity", prefix, re.I):
        return {"price_quantity_bridge"}
    if metric == "profit":
        return {"profit_bridge"}
    return set()


def _parse_signed_closure_expression(expr: str) -> dict | None:
    normalized = expr.replace("−", "-").replace("－", "-")
    if re.search(r"[^0-9+\-=.\s]", normalized) or normalized.count("=") != 1:
        return None
    left, right = [part.strip() for part in normalized.split("=", 1)]
    if not left or not right:
        return None
    try:
        rhs = Decimal(right)
        terms = [
            Decimal(term.replace(" ", ""))
            for term in re.findall(r"[+-]?\s*\d+(?:\.\d+)?", left)
        ]
    except InvalidOperation:
        return None
    if len(terms) < 2:
        return None
    with localcontext() as context:
        # Preserve small fractional terms beside large integers during addition.
        values = [*terms, rhs]
        context.prec = max(28, max(v.adjusted() for v in values)
                           - min(v.as_tuple().exponent for v in values)
                           + len(str(len(terms))) + 2)
        balanced = sum(terms) == rhs
    return {"terms": terms, "rhs": rhs, "balanced": balanced}


def _matching_body_closure_group(
    parsed: dict, facts: list[dict], evidence_groups: list[dict], target_group_types: set[str]
) -> dict | None:
    if not target_group_types:
        return None
    referenced_ids = {fact.get("id") for fact in facts}
    for group in evidence_groups:
        if not isinstance(group, dict) or group.get("status") != "complete":
            continue
        if group.get("group_type") not in target_group_types:
            continue
        closure = group.get("closure") or {}
        if closure.get("status") != "passed":
            continue
        members = _ordered_closure_members(group)
        if not members or any(member.get("fact_id") not in referenced_ids for member in members):
            continue
        expected_len = 5 if group.get("group_type") == "price_quantity_bridge" else 4
        if len(members) != expected_len:
            continue
        values = [Decimal(str(member["value"])) for member in members]
        if values[:-1] != parsed["terms"] or values[-1] != parsed["rhs"]:
            continue
        return group
    return None


def _ordered_closure_members(group: dict) -> list[dict]:
    members = group.get("members") or []
    if group.get("group_type") == "profit_bridge":
        by_metric = {
            str(member.get("semantic_role", "")).split(".", 1)[0]: member
            for member in members
            if isinstance(member, dict) and member.get("column") == "contribution"
        }
        order = ("revenue", "cost", "expense", "profit")
        return [by_metric[key] for key in order if key in by_metric]
    if group.get("group_type") == "price_quantity_bridge":
        by_column = {
            member.get("column"): member
            for member in members
            if isinstance(member, dict)
        }
        order = ("quantity_contribution", "price_contribution", "interaction", "residual", "total_variance")
        return [by_column[key] for key in order if key in by_column]
    return []


def _body_excerpt(body: str, start: int, radius: int = 24) -> str:
    left = max(0, start - radius)
    right = min(len(body), start + radius)
    return body[left:right]


def _token_matches_fact(text: str, fact: dict) -> bool:
    value = Decimal(_normalize_number(text))
    options = _numbers_from_text(str(fact.get('display_value', ''))) | {_fact_number(fact)}
    if any(value == Decimal(option) for option in options):
        return True
    return fact['semantics'].get('role') == 'profit_impact' and any(abs(value) == abs(Decimal(option)) for option in options)


def _presentation_allowed_numbers_and_issues(claims: list[dict], by_id: dict[str, dict]) -> dict:
    numbers: dict[str, set[str]] = {}
    issues: list[dict] = []
    for claim in claims:
        if not isinstance(claim, dict) or "presentation" not in claim:
            continue
        fact_id = claim.get("fact_id")
        fact = by_id.get(fact_id) if isinstance(fact_id, str) else None
        result, issue = _presentation_number(claim, fact)
        if issue:
            issues.append(issue)
        elif result:
            numbers.setdefault(result["number"], set()).add(result["unit"])
    return {"numbers": numbers, "issues": issues}


def _presentation_number(claim: dict, fact: dict | None) -> tuple[dict | None, dict | None]:
    presentation = claim.get("presentation")
    base_issue = {
        "code": "invalid_presentation",
        "severity": "error",
        "message": "claim presentation must be derived from the bound calculation fact.",
        "fact_id": claim.get("fact_id"),
    }
    if claim.get("basis") != "calculation" or not fact:
        return None, {**base_issue, "reason": "presentation_requires_bound_fact"}
    if not _claim_matches_fact(claim, fact):
        return None, {**base_issue, "reason": "claim_does_not_match_fact"}
    if not isinstance(presentation, dict):
        return None, {**base_issue, "reason": "presentation_must_be_object"}
    if set(presentation) != {"decimal_places", "scale", "rounding"}:
        return None, {**base_issue, "reason": "unsupported_presentation_fields"}
    decimal_places = presentation.get("decimal_places")
    scale = presentation.get("scale")
    rounding = presentation.get("rounding")
    if isinstance(decimal_places, bool) or not isinstance(decimal_places, int) or not 0 <= decimal_places <= 6:
        return None, {**base_issue, "reason": "decimal_places_out_of_range"}
    if scale not in {"identity", "percent"} or rounding != "half_up":
        return None, {**base_issue, "reason": "unsupported_presentation_policy"}
    try:
        value = Decimal(str(fact["value"]))
    except (InvalidOperation, KeyError):
        return None, {**base_issue, "reason": "fact_value_not_decimal"}
    if not value.is_finite():
        return None, {**base_issue, "reason": "fact_value_not_finite"}
    if scale == "percent":
        if not _fact_is_ratio(fact):
            return None, {**base_issue, "reason": "percent_requires_ratio_fact"}
        value = _fact_percent_value(fact, value)
    quant = Decimal("1") if decimal_places == 0 else Decimal("1").scaleb(-decimal_places)
    try:
        with localcontext() as ctx:
            ctx.prec = max(28, len(value.as_tuple().digits) + decimal_places + 4)
            rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None, {**base_issue, "reason": "presentation_rounding_failed"}
    rendered = format(rounded, f".{decimal_places}f")
    unit = "%" if scale == "percent" else str(fact.get("unit") or "").strip()
    if scale == "percent":
        rendered += "%"
    return {"number": _normalize_number(rendered), "unit": unit}, None


def _claim_matches_fact(claim: dict, fact: dict) -> bool:
    return (
        claim.get("run_id") == fact.get("run_id")
        and claim.get("row") == fact.get("row")
        and claim.get("column") == fact.get("column")
        and _decimal_equal(claim.get("value"), fact.get("value"))
    )


def _fact_is_ratio(fact: dict) -> bool:
    unit = str(fact.get("unit") or "").strip().lower()
    semantics = fact.get("semantics") if isinstance(fact.get("semantics"), dict) else {}
    return unit in {"%", "比率", "ratio"} or semantics.get("role") == "ratio"


def _fact_percent_value(fact: dict, value: Decimal) -> Decimal:
    if str(fact.get("column") or "").endswith("_pct"):
        return value
    return value * Decimal(100)


EXPLICIT_PRESENTATION_UNITS = ("亿元", "万元", "千元", "元", "%", "比率")


def _presentation_token_unit_matches(body: str, token: dict, allowed_units: set[str]) -> bool:
    explicit = _explicit_unit_for_token(body, token)
    if explicit is None:
        return True
    return any(_units_compatible(explicit, unit) for unit in allowed_units)


def _explicit_unit_for_token(body: str, token: dict) -> str | None:
    text = str(token.get("text") or "")
    if text.endswith("%"):
        return "%"
    start = token.get("start")
    if not isinstance(start, int):
        return None
    end = token.get("end", start + len(text))
    suffix = body[end:]
    match = re.match(r"\s*(" + "|".join(map(re.escape, EXPLICIT_PRESENTATION_UNITS)) + r")", suffix)
    return match.group(1) if match else None


def _units_compatible(explicit: str, expected: str) -> bool:
    if explicit == expected:
        return True
    return explicit == "%" and expected in {"%", "比率", "ratio"}


def _validate_calculation_claim(analysis, claim: dict, run_ids: list[str]) -> dict | None:
    run_id = claim.get("run_id")
    row = claim.get("row")
    column = claim.get("column")
    expected = claim.get("value")
    try:
        run = analysis.get_run(run_id)
        if run["id"] not in run_ids or run.get("execution_status") != "succeeded":
            raise ValueError("claim requires a referenced successful run")
        if isinstance(row, bool) or not isinstance(row, int) or row < 0:
            raise ValueError("claim row must be a non-negative integer")
        actual = run["result"]["rows"][row][column]
        matches = _decimal_equal(actual, expected)
    except Exception:
        return {
            "code": "invalid_claim_location",
            "severity": "error",
            "message": "calculation claim has an invalid output location.",
            "run_id": run_id,
            "row": row,
            "column": column,
        }
    if not matches:
        return {
            "code": "claim_value_mismatch",
            "severity": "error",
            "message": (
                "claim value differs from execution result "
                f"(run_id={run['id']}, row={row}, column={column}, "
                f"expected={expected}, actual={actual})."
            ),
            "run_id": run["id"],
            "row": row,
            "column": column,
            "expected": str(expected),
            "actual": str(actual),
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


def _trusted_generated_appendix_regions(
    analysis, body: str, spec: dict, prepared: dict
) -> list[dict]:
    appendix = spec.get("evidence_appendix")
    meta = spec.get("evidence_appendix_meta")
    if not isinstance(appendix, str) or not appendix:
        return []
    if not isinstance(meta, dict):
        return []
    rebuilt_base = render_evidence_appendix(prepared).get("body", "")
    if not isinstance(rebuilt_base, str) or not rebuilt_base:
        return []
    rebuilt_gap = _rebuilt_input_gap_appendix(analysis, spec, prepared)
    if rebuilt_gap is None:
        return []
    rebuilt = rebuilt_base + rebuilt_gap
    expected = evidence_appendix_metadata(rebuilt, base_body=rebuilt_base)
    if any(meta.get(key) != expected[key] for key in ("body_sha256", "base_body_sha256")):
        return []
    if meta.get("schema_version") != 1 or meta.get("render_version") != EVIDENCE_APPENDIX_RENDER_VERSION:
        return []
    if appendix != rebuilt:
        return []
    rendered = rebuilt
    start = body.rfind(rendered)
    if start < 0:
        canonical = _canonical_report_markdown(rebuilt)
        if not canonical:
            return []
        rendered = canonical
        start = body.rfind(rendered)
        if start < 0:
            return []
    return [
        {
            "section": "generated_appendix",
            "start": start,
            "end": start + len(rendered),
        }
    ]


def _canonical_report_markdown(markdown: str) -> str | None:
    try:
        from foundry.report_documents import (
            report_document_from_markdown_body,
            report_document_markdown,
        )

        return report_document_markdown(report_document_from_markdown_body(markdown))
    except FoundryError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _rebuilt_input_gap_appendix(analysis, spec: dict, prepared: dict) -> str | None:
    requirements_id = spec.get("requirements_id")
    if not requirements_id:
        return ""
    try:
        requirements = analysis._get("requirements", requirements_id)
        from foundry.finance_requirement_support import (
            input_gap_appendix,
            with_input_gaps,
        )
        from foundry.finance_requirements import check_requirements

        checked = check_requirements(
            analysis,
            {
                "run_ids": spec.get("run_ids", []),
                "claims": claims_for_facts(prepared.get("facts", []), spec.get("fact_ids", [])),
                "requirements_id": requirements_id,
                "source_read_failures": spec.get("source_read_failures", []),
            },
            _requirements_record=requirements,
        )
        return input_gap_appendix(with_input_gaps(analysis, checked))
    except FoundryError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def _readability_suggestions(body: str, generated_regions: list[dict]) -> dict:
    issues: list[dict] = []
    for block in _manager_readability_blocks(body, generated_regions):
        text = block["text"]
        stripped = text.strip()
        if _is_dense_finance_paragraph(stripped):
            issues.append({
                "code": "dense_paragraph",
                "severity": "suggestion",
                "message": "这一段同时承载结论、多个数据或条件，建议拆成短结论、条列/比较表和独立附注。",
                "position": block["start"] + text.find(stripped),
            })
        if _has_inline_formula_stack(stripped):
            match = CLOSURE_EXPR.search(stripped)
            position = block["start"] + (
                match.start("expr") if match else text.find(stripped)
            )
            issues.append({
                "code": "inline_formula",
                "severity": "suggestion",
                "message": "完整公式与叙述挤在同一段，建议把公式独立成段或小表，并把条件贴近相关判断。",
                "position": position,
            })
    located = _locate_issues(issues, generated_regions)
    return {
        "status": "suggestions" if located else "clear",
        "issues": located,
    }


def _manager_readability_blocks(body: str, generated_regions: list[dict]) -> list[dict]:
    blocks: list[dict] = []
    in_code = False
    index = 0
    current: list[str] = []
    current_start: int | None = None
    for line in body.splitlines(keepends=True):
        raw = line.rstrip("\n")
        stripped = raw.strip()
        line_start = index
        line_end = index + len(line)
        index = line_end
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if current and current_start is not None:
                blocks.append({"text": "".join(current), "start": current_start})
                current = []
                current_start = None
            in_code = not in_code
            continue
        if in_code or _span_in_generated_region(
            (line_start, line_end), generated_regions
        ):
            if current and current_start is not None:
                blocks.append({"text": "".join(current), "start": current_start})
                current = []
                current_start = None
            continue
        if not stripped:
            if current and current_start is not None:
                blocks.append({"text": "".join(current), "start": current_start})
                current = []
                current_start = None
            continue
        if _is_readability_exempt_line(stripped):
            if current and current_start is not None:
                blocks.append({"text": "".join(current), "start": current_start})
                current = []
                current_start = None
            continue
        if current_start is None:
            current_start = line_start
        current.append(line)
    if current and current_start is not None:
        blocks.append({"text": "".join(current), "start": current_start})
    return blocks


def _span_in_generated_region(
    span: tuple[int, int], generated_regions: list[dict]
) -> bool:
    return any(
        _overlaps(span, (region["start"], region["end"]))
        for region in generated_regions
    )


def _is_readability_exempt_line(stripped: str) -> bool:
    return (
        stripped.startswith(("|", ">", "#", "[^"))
        or bool(re.match(r"^(?:[-*+] |\d+[.)] )", stripped))
    )


def _is_dense_finance_paragraph(text: str) -> bool:
    if len(text) < 160:
        return False
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    sentence_boundaries = len(re.findall(r"[。；;！!？?]", text))
    if sentence_boundaries < 2:
        return False
    number_count = len(_body_numbers(text))
    fact_count = len(FACT_TOKEN.findall(text))
    finance_markers = sum(
        1
        for marker in (
            "结论",
            "收入",
            "成本",
            "费用",
            "利润",
            "现金",
            "预算",
            "同比",
            "环比",
            "公式",
            "原因",
            "行动",
            "证据",
        )
        if marker in text
    )
    return (number_count + fact_count) >= 3 and finance_markers >= 3


def _has_inline_formula_stack(text: str) -> bool:
    match = CLOSURE_EXPR.search(text)
    if not match:
        return False
    before = text[:match.start("expr")].strip()
    after = text[match.end("expr"):].strip()
    prose_chars = len(re.findall(r"[\u4e00-\u9fffA-Za-z]", before + after))
    return len(text) >= 80 and prose_chars >= 24


def _locate_issues(issues: list[dict], generated_regions: list[dict]) -> list[dict]:
    return [
        _locate_issue(issue, generated_regions)
        for issue in issues
        if isinstance(issue, dict)
    ]


def _locate_issue(issue: dict, generated_regions: list[dict]) -> dict:
    located = dict(issue)
    position = located.get("position")
    if isinstance(position, int):
        origin = _origin_for_position(position, generated_regions)
        location = {"section": origin, "position": position}
        if origin == "generated_appendix":
            region = _region_for_position(position, generated_regions)
            if region:
                location["offset"] = position - region["start"]
    else:
        origin = _non_body_issue_origin(located)
        location = {"section": origin}
    located.setdefault("origin", origin)
    located.setdefault("location", location)
    return located


def _origin_for_position(position: int, generated_regions: list[dict]) -> str:
    return (
        "generated_appendix"
        if _region_for_position(position, generated_regions)
        else "manager_body"
    )


def _region_for_position(position: int, generated_regions: list[dict]) -> dict | None:
    for region in generated_regions:
        if region["start"] <= position < region["end"]:
            return region
    return None


def _non_body_issue_origin(issue: dict) -> str:
    if issue.get("code") in {
        "invalid_claim",
        "invalid_claim_location",
        "claim_value_mismatch",
        "fact_claim_mismatch",
        "unknown_fact",
        "missing_required_fact",
    }:
        return "claim_binding"
    return "manager_body"


def _generated_appendix_heading_number_spans(body: str, prepared: dict) -> list[tuple[int, int]]:
    appendix = render_evidence_appendix(prepared).get("body", "")
    if not appendix:
        return []
    rendered = appendix
    start = body.rfind(rendered)
    if start < 0:
        canonical = _canonical_report_markdown(appendix)
        if not canonical:
            return []
        rendered = canonical
        start = body.rfind(rendered)
        if start < 0:
            return []
    spans = []
    for match in re.finditer(r"(?m)^### 结果行 (?P<number>\d+)$", rendered):
        number_span = match.span("number")
        spans.append((start + number_span[0], start + number_span[1]))
    return spans


def _body_numbers(body: str, *, ignored_spans: list[tuple[int, int]] | None = None) -> list[dict]:
    ignored_spans = ignored_spans or []
    footnote_spans = [
        match.span() for match in re.finditer(r"\[\^\d+\]", body)
    ]
    footnote_definition_spans = [
        match.span("number")
        for match in re.finditer(r"(?m)^\[\^(?P<number>\d+)\]:", body)
    ]
    ignored_spans = ignored_spans + footnote_spans + footnote_definition_spans
    date_spans = [match.span() for match in DATE_SPAN.finditer(body)]
    values = []
    for match in NUMBER.finditer(body):
        if any(_overlaps(match.span(), span) for span in ignored_spans):
            continue
        if any(_overlaps(match.span(), span) for span in date_spans):
            continue
        before = body[match.start() - 1 : match.start()]
        after = body[match.end() : match.end() + 1]
        if (before and before in "-–—/年月日") or (after and after in "-–—/年月日"):
            continue
        # 中文排版常在数字与年/月/日之间加空格：「1–8 月」「2026 年 08 月」。
        spaced_before = body[: match.start()].rstrip(" \u00a0\u2009\u202f\u3000")[-1:]
        spaced_after = body[match.end() :].lstrip(" \u00a0\u2009\u202f\u3000")[:1]
        if (spaced_before and spaced_before in "年月日") or (spaced_after and spaced_after in "年月日"):
            continue
        if _is_spreadsheet_reference_number(body, match):
            continue
        values.append({"text": match.group(0), "start": match.start(), "end": match.end()})
    return values


def _is_spreadsheet_reference_number(body: str, match: re.Match[str]) -> bool:
    token = match.group(0)
    if not re.fullmatch(r"\d{1,3}", token):
        return False
    after = body[match.end() : match.end() + 1]
    tail = body[match.end() + 1 :]
    if after == "!":
        return bool(re.match(r"\$?[A-Za-z]{1,3}\$?[1-9]\d*\b", tail))
    if after == "·":
        return bool(re.match(r"[\u4e00-\u9fff]+", tail))
    return bool(re.match(r"[ \u00a0\u3000]?表", body[match.end() :]))


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
