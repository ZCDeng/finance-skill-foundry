"""Deterministic source evidence recipes for finance drafts.

Recipes are manager-visible source checks. They execute only against archived,
task-bound snapshots and produce issues; they never promote a model assertion into
source truth.
"""

from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries

from foundry.analysis import _hash_bytes
from foundry.analysis_data import read_exact_numerics
from foundry.errors import FoundryError

RECIPE_KINDS = {"direct", "sum", "diff", "ratio"}
MAX_RECIPE_CELLS = 8000
MAX_RECIPE_COUNT = 256
MAX_CONSISTENCY_SOURCE_COUNT = 256
MAX_CONSISTENCY_RULE_COUNT = 256
EXCEL_MAX_ROW = 1048576
EXCEL_MAX_COLUMN = 16384


def evaluate_evidence_recipes(analysis: Any, recipes: list[Any] | None) -> dict[str, Any]:
    clean = _clean_recipes(recipes)
    recipe_by_id = {recipe["id"]: recipe for recipe in clean}
    factor_cache: dict[str, Decimal] = {}
    results = [_evaluate_recipe(analysis, recipe, recipe_by_id, factor_cache) for recipe in clean]
    issues = [result["issue"] for result in results if result.get("issue")]
    status = "not_configured" if not clean else "needs_attention" if issues else "pass"
    return {
        "schema_version": 1,
        "summary": {
            "status": status,
            "recipe_count": len(clean),
            "issue_count": len(issues),
        },
        "results": results,
        "issues": issues,
    }


def recipe_dataset_ids(recipes: list[Any] | None) -> set[str]:
    ids: set[str] = set()
    for recipe in _clean_recipes(recipes):
        if recipe["kind"] in {"direct", "sum"}:
            ids.add(recipe["dataset_id"])
        else:
            ids.add(recipe["left"]["dataset_id"])
            ids.add(recipe["right"]["dataset_id"])
    return ids


def evidence_quality_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    return list(report.get("issues") or [])


def consistency_dataset_ids(sources: Any) -> set[str]:
    ids: set[str] = set()
    for source in _clean_consistency_sources(sources).values():
        ids.add(source["dataset_id"])
    return ids


def prepare_consistency_inputs(analysis: Any, rules: list[Any] | None, sources: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clean_sources = _clean_consistency_sources(sources)
    values: dict[str, Decimal] = {}
    source_auth: dict[str, Any] = {}
    for source_id, source in clean_sources.items():
        dataset = _read_authorized_dataset(analysis, source)
        reference = {key: source[key] for key in ("dataset_id", "source_hash")}
        if source["kind"] == "number":
            reference.update({key: source[key] for key in ("sheet", "range")})
            values[source_id] = _source_value(analysis, source) * source["scale"]
            source_auth[source_id] = {"kind": "number", "reference": reference}
        elif source["kind"] == "text":
            paragraph = _archived_paragraph(dataset, source, analysis)
            source_auth[source_id] = {
                "kind": "text",
                "text": paragraph["text"],
                "reference": {**reference, **{key: paragraph[key] for key in paragraph if key != "text"}},
            }
        else:  # pragma: no cover - guarded by cleaner
            raise FoundryError("unsupported consistency source kind")
    return _resolve_consistency_rules(rules, values), source_auth


def _clean_recipes(recipes: list[Any] | None) -> list[dict[str, Any]]:
    if recipes in (None, []):
        return []
    if not isinstance(recipes, list):
        raise FoundryError("evidence_recipes must be an array")
    if len(recipes) > MAX_RECIPE_COUNT:
        raise FoundryError("evidence_recipes exceeds the recipe count limit")
    cleaned = [_clean_recipe(recipe, index) for index, recipe in enumerate(recipes, start=1)]
    ids = [recipe["id"] for recipe in cleaned]
    if len(ids) != len(set(ids)):
        raise FoundryError("evidence recipe ids must be unique")
    by_id = {recipe["id"]: recipe for recipe in cleaned}
    for recipe in cleaned:
        factor_id = recipe.get("factor_recipe_id")
        if not factor_id:
            continue
        factor = by_id.get(factor_id)
        if factor is None:
            raise FoundryError("factor_recipe_id must reference a same-batch evidence recipe")
        if factor["kind"] != "ratio":
            raise FoundryError("factor_recipe_id must reference a ratio evidence recipe")
        if factor["scale"] != Decimal(1):
            raise FoundryError("factor ratio recipe scale must be 1")
        if recipe["id"] == factor_id:
            raise FoundryError("factor_recipe_id cannot reference itself")
        _assert_matching_factor_business_key(recipe, factor)
    return cleaned


def _clean_recipe(recipe: Any, index: int) -> dict[str, Any]:
    if not isinstance(recipe, dict):
        raise FoundryError("evidence recipe must be an object")
    kind = recipe.get("kind")
    if kind not in RECIPE_KINDS:
        raise FoundryError("evidence recipe kind must be direct, sum, diff or ratio")
    recipe_id = _text(recipe.get("id") or f"recipe-{index}", "evidence recipe id")
    cleaned = {
        "schema_version": 1,
        "id": recipe_id,
        "label": _text(recipe.get("label") or recipe_id, "evidence recipe label"),
        "kind": kind,
        "unit": _text(recipe.get("unit", ""), "evidence recipe unit", required=False),
        "scale": _decimal(recipe.get("scale", "1"), "evidence recipe scale"),
        "claim": _claim(recipe.get("claim")),
        "business_key": recipe.get("business_key") if isinstance(recipe.get("business_key"), dict) else {},
    }
    if kind in {"direct", "sum"}:
        cleaned.update(_source(recipe))
        if recipe.get("factor_recipe_id") is not None:
            if "scale" in recipe:
                raise FoundryError("factor_recipe_id cannot be combined with explicit scale")
            cleaned["factor_recipe_id"] = _text(recipe.get("factor_recipe_id"), "evidence recipe factor_recipe_id")
    elif recipe.get("factor_recipe_id") is not None:
        raise FoundryError("factor_recipe_id is only supported on direct and sum evidence recipes")
    else:
        left = recipe.get("left")
        right = recipe.get("right")
        if not isinstance(left, dict) or not isinstance(right, dict):
            raise FoundryError("diff and ratio recipes require left and right sources")
        cleaned["left"] = _source(left)
        cleaned["right"] = _source(right)
    return cleaned


def _source(recipe: dict[str, Any]) -> dict[str, str]:
    dataset_id = _text(recipe.get("dataset_id"), "evidence recipe dataset_id")
    source_hash = _text(recipe.get("source_hash"), "evidence recipe source_hash")
    sheet = _text(recipe.get("sheet"), "evidence recipe sheet")
    range_ref = _text(recipe.get("range"), "evidence recipe range")
    try:
        min_col, min_row, max_col, max_row = range_boundaries(range_ref.replace("$", ""))
    except ValueError as exc:
        raise FoundryError("evidence recipe range must be a bounded A1 reference") from exc
    if None in {min_col, min_row, max_col, max_row}:
        raise FoundryError("evidence recipe range must be a bounded A1 reference")
    if min_row < 1 or min_col < 1 or max_row < min_row or max_col < min_col:
        raise FoundryError("evidence recipe range must be a bounded A1 reference")
    if max_row > EXCEL_MAX_ROW or max_col > EXCEL_MAX_COLUMN:
        raise FoundryError("evidence recipe range exceeds Excel worksheet bounds")
    height = max_row - min_row + 1
    width = max_col - min_col + 1
    if height > 200 or width > 40 or height * width > MAX_RECIPE_CELLS:
        raise FoundryError("evidence recipe range is too large")
    return {"dataset_id": dataset_id, "source_hash": source_hash, "sheet": sheet, "range": range_ref.replace("$", "")}


def _evaluate_recipe(
    analysis: Any,
    recipe: dict[str, Any],
    recipe_by_id: dict[str, dict[str, Any]] | None = None,
    factor_cache: dict[str, Decimal] | None = None,
) -> dict[str, Any]:
    factor_value: Decimal | None = None
    try:
        if recipe.get("factor_recipe_id"):
            _assert_claim_business_key(analysis, recipe)
        actual = _recipe_actual(analysis, recipe)
        if recipe.get("factor_recipe_id"):
            if recipe_by_id is None or factor_cache is None:  # pragma: no cover - compatibility guard
                raise FoundryError("factor recipe context is unavailable")
            factor_value = _factor_value(analysis, recipe, recipe_by_id, factor_cache)
            actual = actual * factor_value
        actual = actual * recipe["scale"]
        expected = _claim_expected(analysis, recipe["claim"])
    except FoundryError as exc:
        return {
            "recipe_id": recipe["id"],
            "status": "unreadable",
            "issue": _issue(recipe, "evidence_recipe_unreadable", str(exc), actual=None, expected=None),
        }
    if actual != expected:
        return {
            "recipe_id": recipe["id"],
            "status": "mismatch",
            "actual": _format_decimal(actual),
            "expected": _format_decimal(expected),
            **_factor_result_details(recipe, factor_value),
            "issue": _issue(recipe, "evidence_recipe_mismatch", None, actual=actual, expected=expected),
        }
    return {
        "recipe_id": recipe["id"],
        "status": "pass",
        "actual": _format_decimal(actual),
        "expected": _format_decimal(expected),
        **_factor_result_details(recipe, factor_value),
    }


def _recipe_actual(analysis: Any, recipe: dict[str, Any]) -> Decimal:
    if recipe["kind"] == "direct":
        return _single_value(analysis, recipe)
    if recipe["kind"] == "sum":
        return _range_sum(analysis, recipe)
    if recipe["kind"] == "diff":
        return _source_value(analysis, recipe["left"]) - _source_value(analysis, recipe["right"])
    if recipe["kind"] == "ratio":
        return _ratio_value(analysis, recipe)
    raise FoundryError("unsupported evidence recipe kind")  # pragma: no cover - guarded by clean step


def _ratio_value(analysis: Any, recipe: dict[str, Any]) -> Decimal:
    denominator = _source_value(analysis, recipe["right"])
    if denominator == 0:
        raise FoundryError("ratio evidence recipe denominator is zero")
    return _source_value(analysis, recipe["left"]) / denominator


def _factor_value(
    analysis: Any,
    dependent: dict[str, Any],
    recipe_by_id: dict[str, dict[str, Any]],
    factor_cache: dict[str, Decimal],
) -> Decimal:
    factor_id = dependent["factor_recipe_id"]
    if factor_id in factor_cache:
        return factor_cache[factor_id]
    factor = recipe_by_id.get(factor_id)
    if factor is None or factor["kind"] != "ratio":  # pragma: no cover - guarded by clean step
        raise FoundryError("factor_recipe_id must reference a ratio evidence recipe")
    _assert_claim_business_key(analysis, factor)
    actual = _ratio_value(analysis, factor)
    expected = _claim_expected(analysis, factor["claim"])
    if actual != expected:
        raise FoundryError("系数规则未通过归档来源的精确复算")
    factor_cache[factor_id] = actual
    return actual


def _factor_result_details(recipe: dict[str, Any], factor_value: Decimal | None) -> dict[str, str]:
    if not recipe.get("factor_recipe_id") or factor_value is None:
        return {}
    return {"factor_recipe_id": recipe["factor_recipe_id"], "factor_value": _format_decimal(factor_value)}


def _source_value(analysis: Any, source: dict[str, str]) -> Decimal:
    min_col, min_row, max_col, max_row = range_boundaries(source["range"])
    if min_col == max_col and min_row == max_row:
        return _single_value(analysis, source)
    return _range_sum(analysis, source)


def _single_value(analysis: Any, source: dict[str, str]) -> Decimal:
    min_col, min_row, max_col, max_row = range_boundaries(source["range"])
    if min_col != max_col or min_row != max_row:
        raise FoundryError("direct evidence recipe requires a single cell")
    values = _exact_values(analysis, source)
    from openpyxl.utils import get_column_letter

    coordinate = f"{get_column_letter(min_col)}{min_row}"
    if coordinate not in values:
        raise FoundryError(f"source cell {source['sheet']}!{coordinate} is not numeric")
    return values[coordinate]


def _range_sum(analysis: Any, source: dict[str, str]) -> Decimal:
    min_col, min_row, max_col, max_row = range_boundaries(source["range"])
    values = _exact_values(analysis, source)
    from openpyxl.utils import get_column_letter

    total = Decimal("0")
    seen = False
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            coordinate = f"{get_column_letter(col)}{row}"
            if coordinate not in values:
                raise FoundryError(f"source cell {source['sheet']}!{coordinate} is not numeric")
            total += values[coordinate]
            seen = True
    if not seen:
        raise FoundryError(f"source range {source['sheet']}!{source['range']} has no numeric cells")
    return total


def _exact_values(analysis: Any, source: dict[str, str]) -> dict[str, Decimal]:
    dataset = analysis.read_dataset(source["dataset_id"])
    if dataset.get("source_hash") != source["source_hash"]:
        raise FoundryError("evidence recipe source_hash does not match archived snapshot")
    data = _dataset_bytes(analysis, dataset, source)
    return read_exact_numerics(data, source["sheet"])


def _issue(recipe: dict[str, Any], code: str, message: str | None, *, actual: Decimal | None, expected: Decimal | None) -> dict[str, Any]:
    expected_text = _format_decimal(expected) if expected is not None else ""
    actual_text = _format_decimal(actual) if actual is not None else None
    location = _recipe_location(recipe)
    if recipe["kind"] in {"direct", "sum"}:
        source_label = f"{location['sheet']}!{location['range']}"
    else:
        operator = "÷" if recipe["kind"] == "ratio" else "−"
        source_label = (
            f"{location['left']['sheet']}!{location['left']['range']} "
            f"{operator} {location['right']['sheet']}!{location['right']['range']}"
        )
    return {
        "code": code,
        "severity": "error",
        "recipe_id": recipe["id"],
        "label": recipe["label"],
        "business_key": recipe.get("business_key", {}),
        "expected": expected_text,
        **({"actual": actual_text} if actual_text is not None else {}),
        "location": location,
        "claim": recipe.get("claim", {}),
        "message": message or f"来源区域 {source_label} 的独立计算为 {actual_text}，运行引用值为 {expected_text}。",
    }


def _claim(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FoundryError("evidence recipe requires a claim run_id, row, column binding")
    run_id = _text(value.get("run_id"), "evidence recipe claim run_id")
    row = value.get("row")
    if isinstance(row, bool) or not isinstance(row, int) or row < 0:
        raise FoundryError("evidence recipe claim row must be a non-negative integer")
    column = _text(value.get("column"), "evidence recipe claim column")
    return {"run_id": run_id, "row": row, "column": column}


def _claim_expected(analysis: Any, claim: dict[str, Any]) -> Decimal:
    try:
        value = _claim_row(analysis, claim)[claim["column"]]
        return _decimal(value, "evidence recipe claim value")
    except FoundryError:
        raise
    except Exception as exc:
        raise FoundryError("evidence recipe claim does not point to a numeric run value") from exc


def _claim_row(analysis: Any, claim: dict[str, Any]) -> dict[str, Any]:
    try:
        run = analysis.get_run(claim["run_id"])
        row = run["result"]["rows"][claim["row"]]
    except FoundryError:
        raise
    except Exception as exc:
        raise FoundryError("evidence recipe claim does not point to a run row") from exc
    if not isinstance(row, dict):
        raise FoundryError("evidence recipe claim does not point to a run row")
    return row


def _recipe_location(recipe: dict[str, Any]) -> dict[str, Any]:
    if recipe["kind"] in {"direct", "sum"}:
        location = {key: recipe[key] for key in ("dataset_id", "source_hash", "sheet", "range")}
        if recipe.get("factor_recipe_id"):
            location["factor_recipe_id"] = recipe["factor_recipe_id"]
        return location
    return {
        "left": {key: recipe["left"][key] for key in ("dataset_id", "source_hash", "sheet", "range")},
        "right": {key: recipe["right"][key] for key in ("dataset_id", "source_hash", "sheet", "range")},
    }


def _assert_matching_factor_business_key(dependent: dict[str, Any], factor: dict[str, Any]) -> None:
    dependent_key = dependent.get("business_key") or {}
    factor_key = factor.get("business_key") or {}
    if (
        not dependent_key.get("metric_key")
        or not dependent_key.get("period")
        or dependent_key.get("metric_key") != factor_key.get("metric_key")
        or dependent_key.get("period") != factor_key.get("period")
    ):
        raise FoundryError("factor_recipe_id requires matching business_key metric_key and period")


def _assert_claim_business_key(analysis: Any, recipe: dict[str, Any]) -> None:
    business_key = recipe.get("business_key") or {}
    metric_key = business_key.get("metric_key")
    period = business_key.get("period")
    if not metric_key or not period:
        raise FoundryError("factor_recipe_id requires business_key metric_key and period")
    row = _claim_row(analysis, recipe["claim"])
    if row.get("metric_key") != metric_key or row.get("period") != period:
        raise FoundryError("evidence recipe business_key metric_key and period must match claim row")


def _text(value: Any, label: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise FoundryError(f"{label} must be text")
    text = value.strip()
    if required and not text:
        raise FoundryError(f"{label} is required")
    return text


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


def _clean_consistency_sources(sources: Any) -> dict[str, dict[str, Any]]:
    if sources in (None, {}, []):
        return {}
    items: list[Any]
    if isinstance(sources, dict):
        items = [{**value, "id": key} if isinstance(value, dict) else value for key, value in sources.items()]
    elif isinstance(sources, list):
        items = sources
    else:
        raise FoundryError("consistency_sources must be an object or array")
    if len(items) > MAX_CONSISTENCY_SOURCE_COUNT:
        raise FoundryError("consistency_sources exceeds the source count limit")
    cleaned: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise FoundryError("consistency source must be an object")
        source_id = _text(item.get("id"), "consistency source id")
        kind = item.get("kind")
        if kind not in {"number", "text"}:
            raise FoundryError("consistency source kind must be number or text")
        source = {
            "id": source_id,
            "kind": kind,
            "dataset_id": _text(item.get("dataset_id"), "consistency source dataset_id"),
            "source_hash": _text(item.get("source_hash"), "consistency source source_hash"),
            "label": _text(item.get("label", source_id), "consistency source label", required=False),
        }
        if kind == "number":
            source.update(_source(item))
            source["kind"] = kind
            source["id"] = source_id
            source["label"] = _text(item.get("label", source_id), "consistency source label", required=False)
            source["scale"] = _decimal(item.get("scale", "1"), "consistency source scale")
        else:
            paragraph = item.get("paragraph")
            has_paragraph = paragraph is not None
            has_workbook_cell = any(item.get(key) is not None for key in ("sheet", "range"))
            if has_paragraph and has_workbook_cell:
                raise FoundryError("text consistency source must use either paragraph or workbook sheet/range")
            if has_paragraph:
                if isinstance(paragraph, bool) or not isinstance(paragraph, int) or paragraph < 1:
                    raise FoundryError("consistency source paragraph must be a positive integer")
                source["paragraph"] = paragraph
            elif has_workbook_cell:
                workbook_source = _source(item)
                min_col, min_row, max_col, max_row = range_boundaries(workbook_source["range"])
                if min_col != max_col or min_row != max_row:
                    raise FoundryError("text consistency workbook source range must be a single cell")
                source.update(workbook_source)
                source["kind"] = kind
                source["id"] = source_id
                source["label"] = _text(item.get("label", source_id), "consistency source label", required=False)
            else:
                raise FoundryError("text consistency source requires paragraph or workbook sheet/range")
        if source_id in cleaned:
            raise FoundryError("consistency source ids must be unique")
        cleaned[source_id] = source
    return cleaned


def _read_authorized_dataset(analysis: Any, source: dict[str, Any]) -> dict[str, Any]:
    dataset = analysis.read_dataset(source["dataset_id"])
    if dataset.get("source_hash") != source["source_hash"]:
        raise FoundryError("consistency source_hash does not match archived snapshot")
    return dataset


def _dataset_bytes(analysis: Any, dataset: dict[str, Any], source: dict[str, Any]) -> bytes:
    folder = analysis._inside(analysis.root / "datasets" / source["dataset_id"])
    path = analysis._inside(folder / dataset["source_file"])
    data = path.read_bytes()
    if _hash_bytes(data) != source["source_hash"]:
        raise FoundryError("archived source integrity check failed")
    return data


def _archived_paragraph(dataset: dict[str, Any], source: dict[str, Any], analysis: Any | None = None) -> dict[str, Any]:
    if source.get("sheet") or source.get("range"):
        if analysis is None:
            raise FoundryError("workbook text source requires archived workbook access")
        return _archived_workbook_text_cell(analysis, dataset, source)
    if dataset.get("kind") != "background":
        raise FoundryError("text consistency paragraph source requires an archived text dataset")
    paragraphs = dataset.get("paragraphs") or []
    if source.get("paragraph"):
        paragraph = next((item for item in paragraphs if item.get("paragraph") == source["paragraph"]), None)
        if not paragraph:
            raise FoundryError("consistency source paragraph was not found")
        return {"paragraph": paragraph.get("paragraph"), "line": paragraph.get("line"), "text": str(paragraph.get("text") or "")}
    text = str(dataset.get("text") or "")
    if not text.strip():
        raise FoundryError("consistency source text is empty")
    return {"text": text}


def _archived_workbook_text_cell(analysis: Any, dataset: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    data = _dataset_bytes(analysis, dataset, source)
    min_col, min_row, max_col, max_row = range_boundaries(source["range"])
    if min_col != max_col or min_row != max_row:
        raise FoundryError("text consistency workbook source range must be a single cell")
    book = load_workbook(filename=io.BytesIO(data), data_only=False, read_only=True)
    try:
        if source["sheet"] not in book.sheetnames:
            raise FoundryError(f"no worksheet: {source['sheet']}")
        sheet = book[source["sheet"]]
        coordinate = f"{get_column_letter(min_col)}{min_row}"
        value = sheet[coordinate].value
    finally:
        book.close()
    if value is None or (isinstance(value, str) and not value.strip()):
        raise FoundryError(f"text consistency source cell {source['sheet']}!{source['range']} is empty")
    if isinstance(value, str) and value.startswith("="):
        raise FoundryError("text consistency source cell formula text is not accepted")
    return {"sheet": source["sheet"], "range": source["range"], "text": str(value)}


def _resolve_consistency_rules(rules: list[Any] | None, source_values: dict[str, Decimal]) -> list[dict[str, Any]]:
    if rules in (None, []):
        return []
    if not isinstance(rules, list):
        raise FoundryError("consistency_rules must be an array")
    if len(rules) > MAX_CONSISTENCY_RULE_COUNT:
        raise FoundryError("consistency_rules exceeds the rule count limit")
    resolved: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise FoundryError("consistency rule must be an object")
        copy = dict(rule)
        operands = copy.get("values", copy.get("declared_values"))
        if isinstance(operands, list):
            new_operands = []
            for operand in operands:
                if not isinstance(operand, dict):
                    new_operands.append(operand)
                    continue
                item = dict(operand)
                if "value" in item or "declared_value" in item:
                    raise FoundryError("consistency direct values must be read from an authorized source")
                source_id = item.get("source_id")
                if source_id and not item.get("recipe_result_id"):
                    if source_id not in source_values:
                        raise FoundryError("consistency numeric source_id is not authorized")
                    item["value"] = _format_decimal(source_values[source_id])
                new_operands.append(item)
            if "values" in copy:
                copy["values"] = new_operands
            else:
                copy["declared_values"] = new_operands
        resolved.append(copy)
    return resolved
