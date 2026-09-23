"""Deterministic financial consistency checks for declared draft assertions.

This module compares caller-declared rule results against evidence-backed numeric
values. It does not parse arbitrary prose and it does not read workbooks; callers
must pass source snippets and/or recipe results that were already authorized by
the finance evidence layer.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from foundry.errors import FoundryError

SUPPORTED_RULES = {"all_absolute_exceed"}


def evaluate_consistency_rules(
    rules: list[Any] | None,
    *,
    recipe_report: dict[str, Any] | None = None,
    source_auth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate declared consistency rules against authorized evidence.

    `source_auth` is a caller-provided authorization seam, keyed by stable source
    ids, containing archived text/reference payloads selected by the integration
    layer. Rules may reference those ids, but may not inline original text or
    source references themselves.
    """

    clean_rules = _rules(rules)
    auth = _source_auth(source_auth)
    recipe_results = _recipe_results(recipe_report)
    results = [_evaluate_rule(rule, auth, recipe_results) for rule in clean_rules]
    issues = [result["issue"] for result in results if result.get("issue")]
    return {
        "schema_version": 1,
        "summary": {
            "status": "needs_attention" if issues else "pass",
            "rule_count": len(clean_rules),
            "issue_count": len(issues),
        },
        "results": results,
        "issues": issues,
    }


def consistency_quality_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    return list(report.get("issues") or [])


def _rules(rules: list[Any] | None) -> list[dict[str, Any]]:
    if rules in (None, []):
        return []
    if not isinstance(rules, list):
        raise FoundryError("consistency_rules must be an array")
    return [_rule(rule, index) for index, rule in enumerate(rules, start=1)]


def _rule(rule: Any, index: int) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise FoundryError("consistency rule must be an object")
    forbidden = {"original_text", "source_ref", "source_reference", "location"}
    if forbidden.intersection(rule):
        raise FoundryError("consistency rule source text must reference source_auth")
    kind = rule.get("kind")
    if kind not in SUPPORTED_RULES:
        raise FoundryError("consistency rule kind must be all_absolute_exceed")
    operands = rule.get("values") or rule.get("declared_values")
    if not isinstance(operands, list) or not operands:
        raise FoundryError("consistency rule values must be a non-empty array")
    asserted_result = rule.get("asserted_result", rule.get("claim_result"))
    if not isinstance(asserted_result, bool):
        raise FoundryError("consistency rule asserted_result must be boolean")
    cleaned = {
        "id": _text(rule.get("id") or f"rule-{index}", "consistency rule id"),
        "label": _text(rule.get("label") or rule.get("id") or f"rule-{index}", "consistency rule label"),
        "kind": kind,
        "threshold": _decimal(rule.get("threshold"), "consistency rule threshold"),
        "asserted_result": asserted_result,
        "assertion_source_id": _text(rule.get("assertion_source_id"), "consistency assertion_source_id"),
        "values": [_operand(operand, offset) for offset, operand in enumerate(operands, start=1)],
    }
    if cleaned["threshold"] < 0:
        raise FoundryError("consistency rule threshold cannot be negative")
    return cleaned


def _operand(operand: Any, index: int) -> dict[str, Any]:
    if not isinstance(operand, dict):
        raise FoundryError("consistency rule value must be an object")
    forbidden = {"original_text", "source_ref", "source_reference", "location"}
    if forbidden.intersection(operand):
        raise FoundryError("consistency value source text must reference source_auth")
    recipe_result_id = _optional_text(operand.get("recipe_result_id"), "consistency recipe_result_id")
    value_present = "value" in operand or "declared_value" in operand
    if recipe_result_id and value_present:
        raise FoundryError("consistency value must use either recipe_result_id or value")
    if not recipe_result_id and not value_present:
        raise FoundryError("consistency value requires recipe_result_id or value")
    cleaned = {
        "id": _text(operand.get("id") or recipe_result_id or f"value-{index}", "consistency value id"),
        "label": _text(operand.get("label") or operand.get("id") or recipe_result_id or f"value-{index}", "consistency value label"),
        "source_id": _optional_text(operand.get("source_id"), "consistency source_id"),
    }
    if recipe_result_id:
        cleaned["recipe_result_id"] = recipe_result_id
    else:
        if not cleaned["source_id"]:
            raise FoundryError("consistency declared value requires source_id")
        cleaned["value"] = _decimal(operand.get("value", operand.get("declared_value")), "consistency value")
    return cleaned


def _evaluate_rule(rule: dict[str, Any], source_auth: dict[str, dict[str, Any]], recipe_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    assertion = _authorized_assertion_source(source_auth, rule.get("assertion_source_id"))
    values = [_resolve_value(operand, source_auth, recipe_results) for operand in rule["values"]]
    unreadable = [value for value in values if value.get("status") != "pass"]
    if unreadable:
        issue = _issue(rule, assertion, values, None, "financial_consistency_unreadable", "一致性规则引用的证据结果不可用。")
        return {"rule_id": rule["id"], "status": "error", "values": values, "issue": issue}
    computed = all(abs(value["decimal"]) > rule["threshold"] for value in values)
    public_values = [_public_value(value) for value in values]
    base = {
        "rule_id": rule["id"],
        "label": rule["label"],
        "status": "pass" if computed == rule["asserted_result"] else "mismatch",
        "kind": rule["kind"],
        "threshold": _format_decimal(rule["threshold"]),
        "asserted_result": rule["asserted_result"],
        "computed_result": computed,
        "values": public_values,
    }
    if assertion:
        base["assertion_source"] = assertion
    if computed == rule["asserted_result"]:
        return base
    issue = _issue(rule, assertion, values, computed, "financial_consistency_mismatch", None)
    return {**base, "issue": issue}


def _resolve_value(operand: dict[str, Any], source_auth: dict[str, dict[str, Any]], recipe_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source = _authorized_source(source_auth, operand.get("source_id"))
    if operand.get("recipe_result_id"):
        result = recipe_results.get(operand["recipe_result_id"])
        if not result:
            return {"id": operand["id"], "label": operand["label"], "status": "error", "message": "recipe result not found", **({"source": source} if source else {})}
        if result.get("status") not in {"pass", "mismatch"} or result.get("actual") is None:
            return {"id": operand["id"], "label": operand["label"], "status": "error", "message": str(result.get("status") or "recipe result unavailable"), **({"source": source} if source else {})}
        value = _decimal(result.get("actual"), "recipe result actual")
        return {
            "id": operand["id"],
            "label": operand["label"],
            "status": "pass",
            "decimal": value,
            "value": _format_decimal(value),
            "recipe_result_id": operand["recipe_result_id"],
            **({"source": source} if source else {}),
        }
    value = operand["value"]
    return {
        "id": operand["id"],
        "label": operand["label"],
        "status": "pass",
        "decimal": value,
        "value": _format_decimal(value),
        **({"source": source} if source else {}),
    }


def _issue(
    rule: dict[str, Any],
    assertion: dict[str, Any] | None,
    values: list[dict[str, Any]],
    computed: bool | None,
    code: str,
    message: str | None,
) -> dict[str, Any]:
    issue = {
        "code": code,
        "severity": "error",
        "rule_id": rule["id"],
        "label": rule["label"],
        "kind": rule["kind"],
        "threshold": _format_decimal(rule["threshold"]),
        "asserted_result": rule["asserted_result"],
        "values": [_public_value(value) for value in values],
        "message": message or _mismatch_message(rule, values, computed),
    }
    if computed is not None:
        issue["computed_result"] = computed
    if assertion:
        issue["assertion_source"] = assertion
        if assertion.get("text"):
            issue["original_text"] = assertion["text"]
    return issue


def _mismatch_message(rule: dict[str, Any], values: list[dict[str, Any]], computed: bool | None) -> str:
    rendered = "、".join(f"{value['label']}={value.get('value', '不可用')}" for value in values)
    verdict = "全部超过" if computed else "并非全部超过"
    return f"声明结果为 {rule['asserted_result']}，但按绝对值阈值 {_format_decimal(rule['threshold'])} 计算为 {computed}：{rendered} {verdict}阈值。"


def _public_value(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "decimal"}


def _recipe_results(recipe_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if recipe_report in (None, {}):
        return {}
    if not isinstance(recipe_report, dict):
        raise FoundryError("recipe_report must be an object")
    results = recipe_report.get("results", [])
    if not isinstance(results, list):
        raise FoundryError("recipe_report results must be an array")
    mapped: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        recipe_id = result.get("recipe_id")
        if isinstance(recipe_id, str) and recipe_id.strip():
            mapped[recipe_id.strip()] = result
    return mapped


def _source_auth(source_auth: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if source_auth in (None, {}):
        return {}
    if not isinstance(source_auth, dict):
        raise FoundryError("source_auth must be an object")
    clean: dict[str, dict[str, Any]] = {}
    for source_id, source in source_auth.items():
        if not isinstance(source_id, str) or not source_id.strip() or not isinstance(source, dict):
            raise FoundryError("source_auth entries must be keyed objects")
        text = source.get("text")
        reference = source.get("reference", {})
        kind = source.get("kind")
        if kind in (None, ""):
            kind = "text" if text is not None else "number"
        if kind not in {"text", "number"}:
            raise FoundryError("source_auth kind must be text or number")
        if text is not None and not isinstance(text, str):
            raise FoundryError("source_auth text must be text")
        if kind == "text" and text is None:
            raise FoundryError("source_auth text source requires text")
        if kind == "number" and text is not None:
            raise FoundryError("source_auth number source cannot contain text")
        if reference is not None and not isinstance(reference, dict):
            raise FoundryError("source_auth reference must be an object")
        clean[source_id.strip()] = {
            "source_id": source_id.strip(),
            "kind": kind,
            **({"text": text} if text is not None else {}),
            **({"reference": dict(reference)} if reference else {}),
        }
    return clean


def _authorized_assertion_source(source_auth: dict[str, dict[str, Any]], source_id: str | None) -> dict[str, Any] | None:
    source = _authorized_source(source_auth, source_id)
    if source and source.get("kind") != "text":
        raise FoundryError("consistency assertion_source_id must reference an authorized text source")
    return source


def _authorized_source(source_auth: dict[str, dict[str, Any]], source_id: str | None) -> dict[str, Any] | None:
    if not source_id:
        return None
    if source_id not in source_auth:
        raise FoundryError("consistency source_id is not authorized")
    return source_auth[source_id]


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise FoundryError(f"{label} must be text")
    text = value.strip()
    if not text:
        raise FoundryError(f"{label} is required")
    return text


def _optional_text(value: Any, label: str) -> str | None:
    if value in (None, ""):
        return None
    return _text(value, label)


def _decimal(value: Any, label: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FoundryError(f"{label} must be decimal text") from exc
    if not decimal.is_finite():
        raise FoundryError(f"{label} must be finite")
    return decimal


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")
