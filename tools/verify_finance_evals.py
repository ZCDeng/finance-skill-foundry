"""Run and score r2 finance evaluations against the configured local model.

Only synthetic fixture data is sent to the provider. The configured credential is
copied into an ephemeral 0600 file and removed with the temporary harness home.
The model owns the analysis turn; this verifier observes tool calls, persisted
Foundry state, and raw messages, then scores them against Decimal fixture truth.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Any

import yaml


REPO = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO / "tests/fixtures/finance_evals/cases.json"
DEFAULT_DSH_ROOT = REPO / "app/extra/dsh"
DEFAULT_FOUNDRY = REPO / ".venv/bin/foundry"
DEFAULT_PLUGIN = REPO / "dsh-plugin"
DEFAULT_CREDENTIALS_HOME = Path("/Users/zcdeng/Library/Application Support/FA Foundry/harness")
SCORING_CONTRACT_R3 = "r3-final-draft-text-bound-v3"
SCORING_CONTRACT_R4_V2 = "r4-requirements-evidence-completion-v2"
SCORING_CONTRACT_R4 = "r4-requirements-evidence-completion-v3"
CALC_TOOLS = {"run_metric", "explain_variance", "finance_scenario_run", "analysis-run"}
SEMANTIC_VERSION = 1
METRIC_ALIASES = {
    "variance_ratio": "ratio",
    "revenue=price×quantity": "revenue",
    "revenue=price*quantity": "revenue",
}
SUPPORTED_R4_INPUT_GAP_CODES = {"native_price_quantity_fields_unavailable"}
ALLOWED_R4_AWAITING_INPUT_ISSUES = {"requirement_unanswered", "requested_source_missing", "verified_input_gap"}
FORBIDDEN_CAUSAL = re.compile(
    r"(?:导致|归因于|原因是|主要因为|直接造成|caused by|because of|due to|driven by)",
    re.I,
)
JUDGMENT_LABEL = re.compile(
    r"(?:经理(?:专业)?判断|经理(?:明确)?(?:假设|口径)|管理层判断|专业判断|user_assumption|professional_judgment|manager judgment)",
    re.I,
)
FINANCIAL_NUMBER = re.compile(r"(?<![A-Za-z0-9_.-])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(\s*(?:万元|元|%))")
DATE_OR_CODE = re.compile(r"\d{4}-\d{1,2}(?:-\d{1,2})?|[A-Z]+-\d+", re.I)


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _dec(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
        if result.is_finite():
            return result
    except (InvalidOperation, ValueError):
        pass
    raise AssertionError(f"not a finite decimal: {value!r}")


def _equal(value: Any, expected: Any) -> bool:
    try:
        return _dec(value) == _dec(expected)
    except AssertionError:
        return False


def _ratio_equal(value: Any, expected: Any) -> bool:
    try:
        actual, truth = _dec(value), _dec(expected)
        with localcontext() as ctx:
            ctx.prec = max(100, len(actual.as_tuple().digits), len(truth.as_tuple().digits))
            return actual.quantize(Decimal(1).scaleb(truth.as_tuple().exponent)) == truth
    except (AssertionError, InvalidOperation):
        return False


def _load_fixture(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    ids = [case["id"] for case in fixture["cases"]]
    minimum_cases = 8 if fixture.get("suite") == "holdout" else 30
    if len(ids) < minimum_cases or len(set(ids)) != len(ids):
        raise AssertionError(f"fixture must contain at least {minimum_cases} unique cases")
    runnable = [case for case in fixture["cases"] if case.get("runnable")]
    stage5 = [case for case in fixture["cases"] if case.get("stage") == "stage5"]
    if len(runnable) < minimum_cases:
        raise AssertionError(f"fixture must contain at least {minimum_cases} runnable cases")
    if fixture.get("suite") != "holdout" and (len(stage5) < 10 or any(not case.get("runnable") for case in stage5)):
        raise AssertionError("stage5 aging/cash scenario cases must now be runnable")
    if fixture.get("suite") != "holdout":
        categories = {case["category"] for case in runnable[:20]}
        required = {
            "profit_bridge",
            "price_quantity",
            "dimension",
            "missing",
            "zero_budget",
            "negative_budget",
            "wrong_unit",
            "duplicates",
            "manager_judgment",
            "drilldown",
        }
        missing = sorted(required - categories)
        if missing:
            raise AssertionError(f"first 20 runnable cases do not cover: {', '.join(missing)}")
    for case in fixture["cases"]:
        for dataset in case.get("datasets", []):
            if not isinstance(dataset.get("metadata"), dict) or not isinstance(dataset.get("rows"), list):
                raise AssertionError(f"{case['id']}: dataset metadata and rows are required")
            for row in dataset["rows"]:
                if "amount" in row and not isinstance(row["amount"], str):
                    raise AssertionError(f"{case['id']}: amount values must be exact strings")
    return fixture


def _clean_env(extra: dict[str, str]) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DSH_", "FOUNDRY_"))
        and not any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
    }
    env.update(extra)
    return env


def _stop(child: subprocess.Popen | None) -> None:
    if child is not None and child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)


def _wait_report(child: subprocess.Popen, path: Path, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                observed = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                observed = None
            if observed and observed.get("status") != "running":
                if observed.get("status") != "completed":
                    raise RuntimeError(observed.get("error", "finance eval observation failed"))
                return observed
        if child.poll() is not None:
            raise RuntimeError(f"harness exited with code {child.returncode}; see runtime.log")
        time.sleep(0.25)
    raise TimeoutError("finance eval harness timed out")


def _call(foundry: Path, var: Path, command: str, *parts: Any, task: str | None = None, session: str | None = None, raw: bool = False) -> Any:
    result = subprocess.run(
        [
            str(foundry),
            "--var",
            str(var),
            *(["--task", task] if task else []),
            *(["--session", session] if session else []),
            command,
            *map(str, parts),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() if raw else json.loads(result.stdout)


def _seed_cases(foundry: Path, var: Path, output: Path, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seeded = []
    for case in cases:
        task = _call(foundry, var, "task-new", "--title", f"r2 finance eval {case['id']}", raw=True)
        workspace = var / "tasks" / task / "analysis"
        uploads = workspace / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        dataset_ids = {}
        for dataset in case["datasets"]:
            source = uploads / f"{dataset['name']}.json"
            source.write_text(json.dumps(dataset["rows"], ensure_ascii=False, sort_keys=True), encoding="utf-8")
            added = _call(
                foundry,
                var,
                "dataset-add",
                "--path",
                source,
                "--name",
                dataset["name"],
                "--meta",
                json.dumps(dataset["metadata"], ensure_ascii=False, sort_keys=True),
                task=task,
            )
            dataset_ids[dataset["name"]] = added["id"]
        input_record = {
            "case_id": case["id"],
            "question": case["question"],
            "datasets": case["datasets"],
            "expected": case["expected"],
        }
        input_sha = _sha(input_record)
        (output / f"{case['id']}-input.json").write_text(
            json.dumps({**input_record, "input_sha256": input_sha}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        seeded.append(
            {
                **case,
                "taskId": task,
                "sessionId": f"r2-finance-eval-{case['id']}-{task}",
                "workspace": str(workspace),
                "datasetIds": dataset_ids,
                "inputSha256": input_sha,
            }
        )
    return seeded


def _matching_rows(state: dict[str, Any], case: dict[str, Any]) -> list[tuple[dict[str, Any], int, dict[str, Any]]]:
    expected = case["expected"]
    matches = []
    for run in state.get("runs", []):
        if run.get("execution_status") != "succeeded":
            continue
        rows = run.get("result", {}).get("rows", [])
        for index, row in enumerate(rows):
            # A grouped SQL projection may omit an invariant input scope field.
            # Infer it only when every fixture source row has that same value;
            # mixed organizations/ledgers still require an explicit output key.
            inputs = [source_row for dataset in case.get("datasets", []) for source_row in dataset.get("rows", [])]
            if all(row.get(key) == value if key in row else bool(inputs) and all(source_row.get(key) == value for source_row in inputs)
                   for key, value in expected.get("identity", {}).items()):
                matches.append((run, index, row))
    return matches


def _find_expected_cells(state: dict[str, Any], case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cells = _find_expected_cells_inner(state, case)
    runs = {run["id"]: run for run in state.get("runs", [])}
    for cell in cells.values():
        row = runs[cell["run_id"]]["result"]["rows"][cell["row"]]
        if row.get("unit") in {"元", "万元"}:
            cell["unit"] = row["unit"]
    return cells


def _find_expected_cells_inner(state: dict[str, Any], case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    # Prefer the run actually cited by the canonical draft when equivalent
    # calculations were rerun. Earlier drafts never supply missing claims.
    draft = _latest_draft(state) or {}
    cited = {claim.get("run_id") for claim in draft.get("claims", [])}
    state = {**state, "runs": sorted(
        [run for run in state.get("runs", []) if run.get("execution_status") == "succeeded"],
        key=lambda run: run.get("id") in cited,
    )}
    expected = case["expected"]
    kind = expected["type"]
    if kind == "price_quantity_missing":
        diagnostics = [
            diag
            for run in state.get("runs", [])
            for diag in run.get("result", {}).get("diagnostics", [])
        ]
        if not any(diag.get("code") == expected["diagnostic_code"] for diag in diagnostics):
            raise AssertionError("missing expected price_quantity_missing diagnostic")
        return {}
    if kind == "control_totals":
        cells = {}
        for run in state.get("runs", []):
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                currency = row.get("currency")
                if currency in expected["currencies"] and _equal(row.get("amount"), expected["currencies"][currency]):
                    cells[f"amount_{currency}"] = {"run_id": run["id"], "row": index, "column": "amount", "value": row["amount"]}
        if set(cells) != {f"amount_{key}" for key in expected["currencies"]}:
            raise AssertionError("control totals did not keep expected currency amounts")
        return cells
    if kind == "account_total":
        cells = {}
        for run, index, row in _matching_rows(state, case):
            period = row.get("period")
            for column in ("amount", "closing_balance"):
                if period in expected["claims"] and _equal(row.get(column), expected["claims"][period]):
                    cells[f"amount_{period}"] = {"run_id": run["id"], "row": index, "column": column, "value": row[column]}
        if set(cells) != {f"amount_{key}" for key in expected["claims"]}:
            raise AssertionError("account total rows did not match expected period amounts")
        return cells
    if kind == "receivables_aging":
        cells = {}
        for run in state.get("runs", []):
            if run.get("execution_status") != "succeeded":
                continue
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                key = f"{row.get('currency')}_{row.get('bucket')}"
                if key in expected["claims"] and _equal(row.get("open_amount"), expected["claims"][key]):
                    cells[key] = {"run_id": run["id"], "row": index, "column": "open_amount", "value": row["open_amount"]}
        if set(cells) != set(expected["claims"]):
            raise AssertionError(f"missing expected aging cells: {sorted(set(expected['claims']) - set(cells))}")
        return cells
    if kind == "cash_13_weeks":
        cells = {}
        for run in state.get("runs", []):
            if run.get("execution_status") != "succeeded":
                continue
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                key = f"week_{row.get('week')}"
                if key in expected["claims"] and _equal(row.get("closing_cash"), expected["claims"][key]):
                    cells[key] = {"run_id": run["id"], "row": index, "column": "closing_cash", "value": row["closing_cash"]}
        if set(cells) != set(expected["claims"]):
            raise AssertionError(f"missing expected cash cells: {sorted(set(expected['claims']) - set(cells))}")
        return cells
    cells = {}
    for run, index, row in _matching_rows(state, case):
        if kind == "profit_bridge" and row.get("metric") in expected.get("claims", {}):
            metric = row["metric"]
            if _equal(row.get("contribution"), expected["claims"][metric]):
                cells[metric] = {"run_id": run["id"], "row": index, "column": "contribution", "value": row["contribution"]}
            if expected.get("ratio_status") and row.get("metric") in {"profit", "revenue"} and row.get("ratio_status") != expected["ratio_status"]:
                raise AssertionError("ratio_status did not match expected policy")
            if expected.get("comparison_status") and row.get("comparison_status") != expected["comparison_status"]:
                raise AssertionError("comparison_status did not match expected policy")
        elif kind == "price_quantity":
            for column, value in expected.get("claims", {}).items():
                if _equal(row.get(column), value):
                    cells[column] = {"run_id": run["id"], "row": index, "column": column, "value": row[column]}
        elif kind == "ratio":
            for column, value in expected.get("claims", {}).items():
                if (_ratio_equal if column == "ratio" else _equal)(row.get(column), value):
                    cells[column] = {"run_id": run["id"], "row": index, "column": column, "value": row[column]}
    if kind == "profit_bridge":
        for run in state.get("runs", []):
            if run.get("execution_status") != "succeeded":
                continue
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                metric = row.get("metric") or row.get("line") or row.get("account") or row.get("management_account")
                if metric in expected.get("claims", {}) and metric not in cells:
                    for column in ("contribution", "profit_impact", "impact", "variance", "amount"):
                        if column in row and _equal(row.get(column), expected["claims"][metric]):
                            cells[metric] = {"run_id": run["id"], "row": index, "column": column, "value": row[column]}
                            break
    elif kind == "ratio":
        aliases = {
            "numerator": ("numerator", "cost_amount", "cost", "actual_cost"),
            "denominator": ("denominator", "revenue_amount", "revenue", "actual_revenue"),
            "ratio": ("ratio", "cost_rate", "cost_rate_pct", "rate"),
        }
        for run in state.get("runs", []):
            if run.get("execution_status") != "succeeded":
                continue
            for index, row in enumerate(run.get("result", {}).get("rows", [])):
                for key, columns in aliases.items():
                    if key in cells:
                        continue
                    for column in columns:
                        if column not in row:
                            continue
                        value = row[column]
                        if column.endswith("_pct"):
                            try:
                                value = _dec(value) / Decimal("100")
                            except AssertionError:
                                pass
                        if (_ratio_equal if key == "ratio" else _equal)(value, expected.get("claims", {}).get(key)):
                            cells[key] = {"run_id": run["id"], "row": index, "column": column, "value": row[column]}
                            break
    expected_keys = set(expected.get("claims", {}))
    if set(cells) != expected_keys:
        raise AssertionError(f"missing expected cells: {sorted(expected_keys - set(cells))}")
    if kind == "profit_bridge" and expected_keys >= {"profit", "revenue", "cost", "expense"}:
        if _dec(cells["profit"]["value"]) != sum(_dec(cells[key]["value"]) for key in ("revenue", "cost", "expense")):
            raise AssertionError("profit bridge does not close")
    # The bridge exposes contribution and profit_impact as exact aliases.
    # Resolve to the current draft's real cited column, not an evaluator-only alias.
    if kind == "profit_bridge":
        for name, cell in cells.items():
            for claim in draft.get("claims", []):
                if (claim.get("basis") == "calculation" and claim.get("run_id") == cell["run_id"]
                        and claim.get("row") == cell["row"]
                        and claim.get("column") in {"contribution", "profit_impact", "amount_change"}
                        and _equal(claim.get("value"), cell["value"])):
                    row = next(run for run in state["runs"] if run["id"] == cell["run_id"])["result"]["rows"][cell["row"]]
                    if _equal(row.get(claim["column"]), cell["value"]):
                        cells[name] = {**cell, "column": claim["column"]}
                        break
    return cells


def _latest_draft(state: dict[str, Any]) -> dict[str, Any] | None:
    drafts = [draft for draft in state.get("drafts", []) if isinstance(draft, dict)]
    return drafts[-1] if drafts else None


def _verified_draft_cells(state: dict[str, Any], cells: dict[str, dict[str, Any]]) -> set[str]:
    verified = set()
    draft = _latest_draft(state)
    if not draft:
        return verified
    for name, cell in cells.items():
        if cell["run_id"] not in draft.get("run_ids", []):
            continue
        for claim in draft.get("claims", []):
            if (
                claim.get("basis") == "calculation"
                and claim.get("verification_status") == "matches_run"
                and claim.get("run_id") == cell["run_id"]
                and claim.get("row") == cell["row"]
                and claim.get("column") == cell["column"]
                and _equal(claim.get("value"), cell["value"])
            ):
                verified.add(name)
    return verified


def _assistant_texts(messages: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for part in message.get("content", []):
            if part.get("type") == "text":
                texts.append(str(part.get("text", "")))
    return texts


def _scan_forbidden(case: dict[str, Any], observed: dict[str, Any], state: dict[str, Any]) -> list[str]:
    draft = _latest_draft(state)
    blobs = [draft.get("body", "")] if draft else []
    final_answer = _final_answer_text(observed)
    if final_answer:
        blobs.append(final_answer)
    forbidden = []
    for text in blobs:
        for match in FORBIDDEN_CAUSAL.finditer(text):
            window = text[max(0, match.start() - 30) : min(len(text), match.end() + 30)]
            prefix = re.split(r"[。；;\n]", text[:match.start()])[-1][-45:]
            if (re.search(r"口径|过滤|参数|schema|查询", window)
                    and re.search(r"查不到|空行|无匹配|报错|失败", window)):
                continue
            # A warning against causal inference is not a causal assertion.
            if re.search(r"(?:不能|无法|不足以|不应|尚未|未能|不可).{0,22}$|(?:可能|假设|待验证|待确认).{0,12}$", prefix):
                continue
            if case["expected"].get("requires_judgment") and JUDGMENT_LABEL.search(window):
                continue
            forbidden.append(window[:500])
    return forbidden


def _final_answer_text(observed: dict[str, Any]) -> str:
    texts = _assistant_texts(observed.get("messages", []))
    return texts[-1] if texts else ""


def _display_values(value: Decimal, percent: bool = False) -> set[Decimal]:
    candidates = set() if percent else {value.normalize()}
    if percent:
        percent_value = value * Decimal("100")
        candidates.add(percent_value.normalize())
        candidates.add(percent_value.quantize(Decimal("0.01")).normalize())
    else:
        candidates.add(value.quantize(Decimal("0.01")).normalize())
    return candidates


def _context_amount_value(raw: Decimal, context: str) -> Decimal:
    lowered = context.lower()
    if raw.is_signed():
        return raw
    expense_word = any(word in context for word in ("成本", "费用", "付款", "支出")) or any(
        word in lowered for word in ("cost", "expense", "payment")
    )
    increase_word = any(word in context for word in ("增加", "上升", "超支", "超预算", "高于预算", "增加了")) or any(
        word in lowered for word in ("increase", "higher", "overrun", "over budget", "above budget")
    )
    decrease_word = any(word in context for word in ("下降", "减少", "节约", "降低")) or any(
        word in lowered for word in ("decrease", "lower", "saved")
    )
    if expense_word and increase_word and not decrease_word:
        return -raw
    return raw


def _verified_additional_cells(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    draft = _latest_draft(state) or {}
    runs = {run["id"]: run for run in state.get("runs", []) if run.get("execution_status") == "succeeded"}
    cells = {}
    for index, claim in enumerate(draft.get("claims", [])):
        run = runs.get(claim.get("run_id"))
        if not run or run["id"] not in draft.get("run_ids", []) or claim.get("basis") != "calculation":
            continue
        row_index, column = claim.get("row"), claim.get("column")
        rows = run.get("result", {}).get("rows", [])
        if not isinstance(row_index, int) or isinstance(row_index, bool) or not 0 <= row_index < len(rows):
            continue
        row = rows[row_index]
        if column in row and _equal(claim.get("value"), row[column]):
            cells[f"cited_{index}"] = {"run_id": run["id"], "row": row_index, "column": column,
                                      "value": row[column], "unit": row.get("unit")}
    return cells


def _verify_final_text_numbers(case: dict[str, Any], text: str, cells: dict[str, dict[str, Any]],
                               additional: dict[str, dict[str, Any]] | None = None) -> None:
    if not text.strip():
        raise AssertionError("final draft/answer text is empty")
    fixture_units = {row.get("unit", dataset.get("metadata", {}).get("unit"))
                     for dataset in case.get("datasets", []) for row in dataset.get("rows", [])}
    fixture_units.discard(None)
    cell_units = {cell.get("unit") for cell in cells.values() if cell.get("unit")}
    default_unit = next(iter(cell_units)) if len(cell_units) == 1 else (next(iter(fixture_units)) if len(fixture_units) == 1 else None)
    def is_ratio(name, cell):
        return bool(re.search(r"ratio|rate|pct|percent|率", f"{name} {cell.get('column', '')}", re.I))
    def candidates(name, cell):
        value = _dec(cell["value"])
        if is_ratio(name, cell):
            return _display_values(value / 100 if cell.get("column", "").endswith("_pct") else value, percent=True)
        scale = Decimal(10000) if (cell.get("unit") or default_unit) == "万元" else Decimal(1)
        return {amount * scale for amount in _display_values(value)}
    all_cells = {**(additional or {}), **cells}
    amount_values = {value for name, cell in all_cells.items() if not is_ratio(name, cell) for value in candidates(name, cell)}
    percent_values = {value for name, cell in all_cells.items() if is_ratio(name, cell) for value in candidates(name, cell)}
    # Unit declarations also cover numeric Markdown table cells. Do not use a
    # default fixture unit to silently repair a missing unit in the final text.
    expanded = []
    table_unit = None
    for line in text.splitlines():
        unit_match = re.search(r"单位[：:）)\s]*(万元|元)", line)
        if unit_match:
            table_unit = unit_match.group(1)
        if line.lstrip().startswith("|") and table_unit:
            parts = line.split("|")
            line = "|".join(part + " " + table_unit if re.fullmatch(r"\s*[+-]?[\d,]+(?:\.\d+)?\s*", part) else part for part in parts)
        expanded.append(line)
    text = "\n".join(expanded)
    unbacked = []
    seen_amounts: set[Decimal] = set()
    seen_percents: set[Decimal] = set()
    for match in FINANCIAL_NUMBER.finditer(text):
        value = _dec(match.group(1).replace(",", "")).normalize()
        unit = match.group(2).strip()
        semantic_window = re.split(r"[，,。；;：:\n|]", text[max(0, match.start() - 18):match.start()])[-1]
        if unit == "%":
            if value not in percent_values:
                unbacked.append(match.group(0).strip())
            else:
                seen_percents.add(value)
            continue
        scale = Decimal(10000) if unit == "万元" and default_unit else Decimal(1)
        normalized = _context_amount_value(value, semantic_window).normalize() * scale
        raw = value * scale
        matched = {raw, normalized} & amount_values
        clause = re.split(r"[。；;\n]", text[max(0, match.start() - 18):match.end() + 18])[0]
        if (not matched and case.get("expected", {}).get("type") == "cash_13_weeks"
                and value > 0 and re.search(r"缺口|额外回款|融资|仍超过", clause) and -raw in amount_values):
            matched.add(-raw)
        if not matched:
            unbacked.append(match.group(0).strip())
        else:
            seen_amounts.update(matched)
    if unbacked:
        raise AssertionError(f"unbacked or contradictory financial numbers in final text: {unbacked[:5]}")
    missing = [name for name, cell in cells.items()
               if not candidates(name, cell) & (seen_percents if is_ratio(name, cell) else seen_amounts)]
    if missing:
        raise AssertionError(f"missing expected financial numbers in final text: {missing}")


def _call_spec(call: dict[str, Any]) -> dict[str, Any]:
    arguments = call.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    if not isinstance(arguments, dict):
        return {}
    spec = arguments.get("spec", arguments)
    return spec if isinstance(spec, dict) else {}


def _cell_key(cell: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (cell["run_id"], cell["row"], cell["column"])


def _required_drilldown_names(case: dict[str, Any], cells: dict[str, dict[str, Any]]) -> set[str]:
    question = str(case.get("question", ""))
    required = set()
    if re.search(r"成本率|cost\s*rate", question, re.I) and "ratio" in cells:
        required.add("ratio")
    if re.search(r"利润(?:差异|来源|行)?|profit", question, re.I) and "profit" in cells:
        required.add("profit")
    if case.get("expected", {}).get("requires_voucher_drilldown") and "profit" in cells:
        required.add("profit")
    return required


def _verify_drilldowns_reference_cells(case: dict[str, Any], observed: dict[str, Any], cells: dict[str, dict[str, Any]]) -> None:
    expected = {_cell_key(cell) for cell in cells.values() if not cell.get("synthetic_zero")}
    if not expected:
        return
    seen = set()
    for call in observed.get("calls", []):
        if call.get("name") != "drilldown_fact" or call.get("isError"):
            continue
        spec = _call_spec(call)
        key = (spec.get("run_id"), spec.get("row", 0), spec.get("column"))
        if key[2] is None:
            seen.update(item for item in expected if item[:2] == key[:2])
        else:
            seen.add(key)
            if case.get("expected", {}).get("type") == "profit_bridge":
                for name, cell in cells.items():
                    if key[:2] == _cell_key(cell)[:2] and key[2] in {name, "metric", "management_account", "contribution", "profit_impact"}:
                        seen.add(_cell_key(cell))
    if not seen & expected:
        raise AssertionError("no drilldown_fact call referenced expected cells")
    required_names = _required_drilldown_names(case, cells)
    required = {_cell_key(cells[name]) for name in required_names}
    if required and not required <= seen:
        raise AssertionError(f"no drilldown_fact call referenced requested drilldown target: {sorted(required_names)}")


def _datasets_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        dataset["id"]: dataset
        for dataset in state.get("datasets", [])
        if isinstance(dataset, dict) and isinstance(dataset.get("id"), str)
    }


def _check_bound_sources(check: dict[str, Any], run: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> None:
    bound = set(run.get("bindings", {}).values())
    if not bound:
        raise AssertionError("r4 evidence_check cannot verify a run without bound snapshots")
    source_hashes = check.get("source_hashes")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise AssertionError("r4 evidence_check source_hashes must be a non-empty object")
    for dataset_id, source_hash in source_hashes.items():
        if dataset_id not in bound:
            raise AssertionError("r4 evidence_check source hash is outside the run bindings")
        if not isinstance(source_hash, str) or not source_hash:
            raise AssertionError("r4 evidence_check source hash must be non-empty")
        dataset = datasets.get(dataset_id)
        if not dataset:
            raise AssertionError("r4 evidence_check source hash references a missing bound snapshot")
        if dataset.get("source_hash") != source_hash:
            raise AssertionError("r4 evidence_check source hash does not match the bound snapshot")
    sources = check.get("sources")
    if not isinstance(sources, list) or not sources:
        raise AssertionError("r4 evidence_check sources must be a non-empty list")
    if not _has_paging_metadata(check):
        raise AssertionError("r4 evidence_check must include complete paging metadata")
    total = check.get("total")
    offset = check.get("offset")
    read_count = check.get("read_count")
    has_more = check.get("has_more")
    if (
        isinstance(total, bool)
        or isinstance(offset, bool)
        or isinstance(read_count, bool)
        or not isinstance(total, int)
        or not isinstance(offset, int)
        or not isinstance(read_count, int)
        or not isinstance(has_more, bool)
    ):
        raise AssertionError("r4 evidence_check paging metadata has invalid types")
    if total <= 0 or offset < 0 or read_count <= 0 or offset + read_count > total:
        raise AssertionError("r4 evidence_check paging metadata is out of bounds")
    if len(sources) != read_count:
        raise AssertionError("r4 evidence_check read_count must match sources length")
    for source in sources:
        if not isinstance(source, dict):
            raise AssertionError("r4 evidence_check sources must be objects")
        dataset_id = source.get("dataset_id")
        row_index = source.get("row_index")
        if dataset_id not in bound:
            raise AssertionError("r4 evidence_check source row is outside the run bindings")
        if dataset_id not in source_hashes:
            raise AssertionError("r4 evidence_check source row has no verified source hash")
        dataset = datasets.get(dataset_id)
        if not dataset:
            raise AssertionError("r4 evidence_check source row references a missing bound snapshot")
        row_count = dataset.get("row_count")
        if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count <= 0:
            raise AssertionError("r4 evidence_check bound snapshot row_count must be a positive integer")
        if isinstance(row_index, bool) or not isinstance(row_index, int) or not 1 <= row_index <= row_count:
            raise AssertionError("r4 evidence_check source row is outside the bound snapshot rows")


def _has_paging_metadata(check: dict[str, Any]) -> bool:
    return all(key in check for key in ("total", "offset", "read_count", "has_more"))


def _r4_evidence_verified_keys(state: dict[str, Any], cells: dict[str, dict[str, Any]]) -> set[tuple[Any, Any, Any]]:
    runs = {run["id"]: run for run in state.get("runs", []) if isinstance(run, dict) and run.get("execution_status") == "succeeded"}
    datasets = _datasets_by_id(state)
    expected = {_cell_key(cell) for cell in cells.values() if not cell.get("synthetic_zero")}
    matched: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {key: [] for key in expected}
    for check in state.get("evidence_checks", []):
        if not isinstance(check, dict) or check.get("status") != "verified":
            continue
        location = check.get("location")
        if not isinstance(location, dict):
            continue
        run = runs.get(location.get("run_id"))
        if not run or location.get("output_hash") != run.get("output_hash"):
            continue
        key = (location.get("run_id"), location.get("row"), location.get("column"))
        if key not in matched:
            continue
        _check_bound_sources(check, run, datasets)
        matched[key].append(check)
    verified = set()
    for key, checks in matched.items():
        if not checks:
            continue
        totals = {check.get("total") for check in checks if isinstance(check.get("total"), int) and not isinstance(check.get("total"), bool)}
        if len(totals) != 1:
            continue
        total = totals.pop()
        intervals = sorted(
            (check.get("offset"), check.get("offset") + check.get("read_count"))
            for check in checks
            if (
                isinstance(check.get("offset"), int)
                and isinstance(check.get("read_count"), int)
                and check.get("offset") >= 0
                and check.get("read_count") >= 0
            )
        )
        cursor = 0
        for start, end in intervals:
            if start > cursor:
                break
            cursor = max(cursor, end)
            if cursor >= total:
                break
        if cursor >= total and any(check.get("has_more") is False for check in checks):
            verified.add(key)
    return verified


def _verify_r4_traceability(case: dict[str, Any], observed: dict[str, Any], state: dict[str, Any], cells: dict[str, dict[str, Any]]) -> None:
    direct_error = None
    try:
        _verify_drilldowns_reference_cells(case, observed, cells)
        return
    except AssertionError as exc:
        direct_error = exc
    expected = {_cell_key(cell) for cell in cells.values() if not cell.get("synthetic_zero")}
    if not expected:
        return
    verified = _r4_evidence_verified_keys(state, cells)
    required_names = _required_drilldown_names(case, cells)
    required = {_cell_key(cells[name]) for name in required_names}
    if expected & verified and (not required or required <= verified):
        return
    raise AssertionError(f"r4 traceability missing direct drilldown or immutable evidence_checks: {direct_error}")


def _verify_r4_contract(
    state: dict[str, Any],
    draft: dict[str, Any] | None,
    cells: dict[str, dict[str, Any]],
    *,
    allow_missing_data: bool = False,
) -> None:
    if not draft:
        raise AssertionError("r4 requires a persisted final draft")
    requirements = [row for row in state.get("requirements", []) if isinstance(row, dict)]
    if not requirements:
        raise AssertionError("r4 requires persisted analysis requirements before scoring")
    current = requirements[-1]
    requirements_by_id = {row.get("id"): row for row in requirements if row.get("id")}
    if draft.get("requirements_id") != current.get("id"):
        raise AssertionError("r4 final draft is not bound to the latest requirements version")
    if not isinstance(current.get("seq"), int) or not isinstance(draft.get("seq"), int) or current["seq"] >= draft["seq"]:
        raise AssertionError("r4 requirements must be saved before the final draft")
    runs = {run["id"]: run for run in state.get("runs", []) if isinstance(run, dict) and run.get("id")}
    _verify_r4_semantic_bindings(state, current, requirements_by_id, runs, draft.get("run_ids", []))
    for run_id in draft.get("run_ids", []):
        run = runs.get(run_id)
        if not run:
            raise AssertionError("r4 final draft references a missing selected run")
        if (
            isinstance(run.get("seq"), int)
            and current["seq"] >= run["seq"]
            and not _r4_run_has_semantic_reuse_proof(current, requirements_by_id, run, state)
        ):
            raise AssertionError("r4 requirements must be saved before selected final runs unless semantic reuse is proven")
    quality = draft.get("explanation_check", draft.get("quality", {}))
    requirement_quality = quality.get("requirements", {}) if isinstance(quality, dict) else {}
    if requirement_quality.get("requirements_id") != current.get("id"):
        raise AssertionError("r4 quality check did not assess the latest requirements")
    if not allow_missing_data:
        if requirement_quality.get("coverage", {}).get("status") != "pass":
            raise AssertionError("r4 requirement coverage did not pass")
        if requirement_quality.get("provenance", {}).get("status") != "pass":
            raise AssertionError("r4 requirement provenance did not pass")
    completions = [row for row in state.get("completions", []) if isinstance(row, dict) and row.get("draft_id") == draft.get("id")]
    if not completions:
        raise AssertionError("r4 requires a persistent completion receipt")
    receipt = completions[-1]
    expected_status = "awaiting_input" if allow_missing_data else "complete"
    if receipt.get("status") != expected_status or receipt.get("requirements_id") != current.get("id"):
        raise AssertionError(f"r4 completion receipt is not {expected_status} for the latest requirements")
    if receipt.get("draft_content_hash") != draft.get("content_hash"):
        raise AssertionError("r4 completion receipt is not bound to the final draft content hash")
    if allow_missing_data:
        _verify_r4_awaiting_input_gap(state, current, draft, quality, requirement_quality, receipt)


def _verify_r4_semantic_bindings(
    state: dict[str, Any],
    current: dict[str, Any],
    requirements_by_id: dict[Any, dict[str, Any]],
    runs: dict[Any, dict[str, Any]],
    run_ids: list[Any],
) -> None:
    datasets = _datasets_by_id(state)
    current_fingerprint = current.get("semantic_fingerprint")
    if not isinstance(current_fingerprint, str) or not current_fingerprint:
        raise AssertionError("r4/v3 requires current requirements semantic_fingerprint")
    _verify_r4_requirement_semantics(current, "current requirements", datasets)
    if _r4_requirement_fingerprint(current, datasets) != current_fingerprint:
        raise AssertionError("r4/v3 current requirements semantic_fingerprint does not match semantic_basis")
    if not _r4_requirement_sources(current):
        raise AssertionError("r4/v3 requires current requirements semantic_basis")
    for run_id in run_ids:
        run = runs.get(run_id)
        if not run:
            raise AssertionError("r4 final draft references a missing selected run")
        if run.get("requirements_semantic_fingerprint") != current_fingerprint:
            raise AssertionError("r4 selected run semantic fingerprint does not match current requirements")
        bound_requirement = requirements_by_id.get(run.get("requirements_id"))
        if not bound_requirement:
            raise AssertionError("r4 selected run does not bind an existing requirements record")
        _verify_r4_requirement_semantics(bound_requirement, "selected run requirements binding", datasets)
        if bound_requirement.get("semantic_fingerprint") != current_fingerprint:
            raise AssertionError("r4 selected run requirements binding does not match current semantic fingerprint")
        if _r4_requirement_fingerprint(bound_requirement, datasets) != current_fingerprint:
            raise AssertionError("r4 selected run requirements binding semantic_basis does not match fingerprint")
        if isinstance(bound_requirement.get("seq"), int) and isinstance(run.get("seq"), int) and bound_requirement["seq"] >= run["seq"]:
            raise AssertionError("r4 selected run requirements binding was not saved before the run")
        if not _r4_run_inputs_match_requirement(run, bound_requirement):
            raise AssertionError("r4 selected run inputs do not match its bound requirements")


def _r4_run_has_semantic_reuse_proof(
    current: dict[str, Any], requirements_by_id: dict[Any, dict[str, Any]], run: dict[str, Any], state: dict[str, Any]
) -> bool:
    current_fingerprint = current.get("semantic_fingerprint")
    bound_requirement = requirements_by_id.get(run.get("requirements_id"))
    if not isinstance(bound_requirement, dict):
        return False
    datasets = _datasets_by_id(state)
    try:
        _verify_r4_requirement_semantics(current, "current requirements", datasets)
        _verify_r4_requirement_semantics(bound_requirement, "selected run requirements binding", datasets)
    except AssertionError:
        return False
    if not (
        isinstance(bound_requirement.get("seq"), int)
        and isinstance(run.get("seq"), int)
        and bound_requirement["seq"] < run["seq"]
    ):
        return False
    return (
        isinstance(current_fingerprint, str)
        and bool(current_fingerprint)
        and run.get("requirements_semantic_fingerprint") == current_fingerprint
        and bound_requirement.get("semantic_fingerprint") == current_fingerprint
        and _r4_requirement_fingerprint(current, datasets) == current_fingerprint
        and _r4_requirement_fingerprint(bound_requirement, datasets) == current_fingerprint
        and _r4_run_inputs_match_requirement(run, bound_requirement)
    )


def _verify_r4_requirement_semantics(record: dict[str, Any], label: str, datasets: dict[str, dict[str, Any]]) -> None:
    if record.get("semantic_version") != SEMANTIC_VERSION:
        raise AssertionError(f"r4/v3 {label} must use semantic_version 1")
    if not isinstance(record.get("semantic_basis"), dict) or not record["semantic_basis"]:
        raise AssertionError(f"r4/v3 {label} lacks semantic_basis")
    expected = _r4_canonical_requirement_basis(record, datasets)
    if record["semantic_basis"] != expected:
        raise AssertionError(f"r4/v3 {label} semantic_basis does not match persisted requirement fields")


def _r4_requirement_fingerprint(record: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> str | None:
    try:
        basis = _r4_canonical_requirement_basis(record, datasets)
    except AssertionError:
        return None
    return _sha(basis)


def _r4_canonical_requirement_basis(record: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    bindings = record.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise AssertionError("r4/v3 requirements must bind source snapshots")
    sources = {}
    for alias, dataset_id in bindings.items():
        if not isinstance(alias, str) or not isinstance(dataset_id, str):
            raise AssertionError("r4/v3 requirements bindings must map aliases to dataset ids")
        dataset = datasets.get(dataset_id)
        if not dataset:
            raise AssertionError("r4/v3 requirements source references a missing dataset snapshot")
        source_hash = dataset.get("source_hash")
        data_hash = dataset.get("data_hash")
        if not isinstance(source_hash, str) or not source_hash or not isinstance(data_hash, str) or not data_hash:
            raise AssertionError("r4/v3 requirements source hashes must match dataset metadata")
        sources[alias] = {"dataset_id": dataset_id, "source_hash": source_hash, "data_hash": data_hash}
    items = []
    for item in record.get("items", []):
        if not isinstance(item, dict):
            raise AssertionError("r4/v3 requirements items must be objects")
        periods = item.get("periods", [])
        if periods in (None, ""):
            periods = []
        if not isinstance(periods, list):
            raise AssertionError("r4/v3 requirements item periods must be arrays")
        items.append({
            "id": item["id"],
            "metric": METRIC_ALIASES.get(item["metric"], item["metric"]),
            "dimensions": item.get("dimensions", {}),
            "periods": sorted(set(periods)),
            "requires_drilldown": item.get("requires_drilldown", False),
        })
    return {
        "version": SEMANTIC_VERSION,
        "question": record.get("question"),
        "context_id": record.get("context_id"),
        "scope": record.get("scope", {}),
        "sources": sources,
        "removed_item_ids": sorted(record.get("removed_item_ids", [])),
        "items": sorted(items, key=lambda item: item["id"]),
    }


def _r4_requirement_sources(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    basis = record.get("semantic_basis")
    sources = basis.get("sources") if isinstance(basis, dict) else None
    return {
        alias: source
        for alias, source in (sources or {}).items()
        if isinstance(alias, str) and isinstance(source, dict)
    }


def _r4_run_inputs_match_requirement(run: dict[str, Any], requirement: dict[str, Any]) -> bool:
    sources = _r4_requirement_sources(requirement)
    bindings = run.get("bindings")
    input_hashes = run.get("input_hashes")
    source_hashes = run.get("source_hashes")
    requirement_bindings = requirement.get("bindings")
    if not sources or not isinstance(bindings, dict) or not isinstance(requirement_bindings, dict):
        return False
    if bindings != requirement_bindings:
        return False
    if not isinstance(input_hashes, dict) or not isinstance(source_hashes, dict):
        return False
    for alias, source in sources.items():
        if (
            bindings.get(alias) != source.get("dataset_id")
            or input_hashes.get(alias) != source.get("data_hash")
            or source_hashes.get(alias) != source.get("source_hash")
        ):
            return False
    return True


def _verify_r4_awaiting_input_gap(
    state: dict[str, Any],
    current: dict[str, Any],
    draft: dict[str, Any],
    quality: dict[str, Any],
    requirement_quality: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    if quality.get("checks", {}).get("numbers", {}).get("status") != "pass":
        raise AssertionError("r4 awaiting_input requires numeric checks to pass")
    quality_items = [item for item in requirement_quality.get("items", []) if isinstance(item, dict)]
    quality_item_ids = {item.get("id") for item in quality_items}
    current_item_ids = {item.get("id") for item in current.get("items", []) if isinstance(item, dict)}
    if not current_item_ids <= quality_item_ids:
        raise AssertionError("r4 awaiting_input requirement quality must cover all current items")
    remaining = [item for item in quality_items if item.get("status") != "answered"]
    if not remaining:
        raise AssertionError("r4 awaiting_input requires remaining unmet requirements")
    if any(item.get("status") != "missing_data" or not isinstance(item.get("input_gap"), dict) for item in remaining):
        raise AssertionError("r4 awaiting_input remaining requirements must be verified input gaps")
    remaining_ids = {item.get("id") for item in remaining}
    unresolved = [
        issue for issue in quality.get("issues", [])
        if isinstance(issue, dict)
        and (issue.get("code") not in ALLOWED_R4_AWAITING_INPUT_ISSUES or issue.get("requirement_item_id") not in remaining_ids)
    ]
    if unresolved:
        raise AssertionError("r4 awaiting_input has unresolved non-gap issues")
    support_items = {
        item.get("requirement_item_id"): item
        for item in current.get("support", {}).get("items", [])
        if isinstance(item, dict)
    }
    datasets = _datasets_by_id(state)
    for item in remaining:
        gap = item["input_gap"]
        support = support_items.get(item.get("id"))
        if not isinstance(support, dict) or support.get("status") != "requires_input":
            raise AssertionError("r4 awaiting_input gap must be verified by requirement support snapshot")
        _verify_r4_input_gap_snapshot(gap, support, datasets)
    action_ids = {
        action.get("requirement_item_id")
        for action in receipt.get("actions", [])
        if isinstance(action, dict) and action.get("code") == "verified_input_gap"
    }
    if not remaining_ids <= action_ids:
        raise AssertionError("r4 awaiting_input completion receipt must name every verified input gap")
    if receipt.get("response_status") != "ended_with_limitations":
        raise AssertionError("r4 awaiting_input must end with limitations")
    if receipt.get("repair_allowed") is not False or receipt.get("stop_reason") != "verified_input_gap":
        raise AssertionError("r4 awaiting_input must stop instead of requesting more blind repairs")
    if receipt.get("original_requirements_completed") is not False:
        raise AssertionError("r4 awaiting_input must preserve original requirements as incomplete")
    if not _draft_has_explicit_limitations(draft):
        raise AssertionError("r4 awaiting_input cases require explicit draft limitations")


def _verify_r4_input_gap_snapshot(
    gap: dict[str, Any], support: dict[str, Any], datasets: dict[str, dict[str, Any]]
) -> None:
    if gap.get("gap_code") != support.get("gap_code"):
        raise AssertionError("r4 awaiting_input gap code does not match support snapshot")
    if gap.get("gap_code") not in SUPPORTED_R4_INPUT_GAP_CODES:
        raise AssertionError("r4 awaiting_input gap code is not supported by the r4 contract")
    missing_inputs = gap.get("missing_inputs")
    if not isinstance(missing_inputs, list) or not missing_inputs:
        raise AssertionError("r4 awaiting_input gap must include missing input columns")
    support_missing = support.get("missing_inputs")
    if missing_inputs != support_missing:
        raise AssertionError("r4 awaiting_input gap missing_inputs changed after support snapshot")
    sources = gap.get("sources")
    if not isinstance(sources, list) or not sources:
        raise AssertionError("r4 awaiting_input gap must include source snapshot hashes")
    if sources != support.get("sources"):
        raise AssertionError("r4 awaiting_input gap sources changed after support snapshot")
    source_ids = set()
    for source in sources:
        if not isinstance(source, dict):
            raise AssertionError("r4 awaiting_input gap sources must be objects")
        dataset_id = source.get("dataset_id")
        source_ids.add(dataset_id)
        dataset = datasets.get(dataset_id)
        if (
            not dataset
            or dataset.get("source_hash") != source.get("source_hash")
            or dataset.get("data_hash") != source.get("data_hash")
        ):
            raise AssertionError("r4 awaiting_input gap source hash does not match bound snapshot")
        row_count = dataset.get("row_count")
        if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
            raise AssertionError("r4 awaiting_input gap source snapshot row_count is invalid")
        schema_names = _dataset_schema_names(dataset)
        if not schema_names:
            raise AssertionError("r4 awaiting_input gap source schema is missing")
        if source.get("columns") and set(source["columns"]) != schema_names:
            raise AssertionError("r4 awaiting_input gap source columns do not match dataset schema")
    for group in missing_inputs:
        if not isinstance(group, dict):
            raise AssertionError("r4 awaiting_input missing_inputs must be source column groups")
        dataset_id = group.get("dataset_id")
        if dataset_id not in source_ids:
            raise AssertionError("r4 awaiting_input missing input references an unverified source")
        columns = group.get("columns")
        if not isinstance(columns, list) or not columns or not all(isinstance(column, str) and column for column in columns):
            raise AssertionError("r4 awaiting_input missing input columns are invalid")
        schema_names = _dataset_schema_names(datasets[dataset_id])
        present = sorted(set(columns) & schema_names)
        if present:
            raise AssertionError(f"r4 awaiting_input missing input columns exist in dataset schema: {present}")


def _dataset_schema_names(dataset: dict[str, Any]) -> set[str]:
    names = set()
    for column in dataset.get("schema", []):
        if isinstance(column, dict) and isinstance(column.get("name"), str):
            names.add(column["name"])
        elif isinstance(column, str):
            names.add(column)
    return names


def _draft_has_explicit_limitations(draft: dict[str, Any]) -> bool:
    limitations = draft.get("limitations")
    if isinstance(limitations, list) and any(str(item).strip() for item in limitations):
        return True
    body = draft.get("body")
    return isinstance(body, str) and "待补资料" in body and ("缺" in body or "补" in body)


def _verify_canonical_final_text(case: dict[str, Any], observed: dict[str, Any], state: dict[str, Any], cells: dict[str, dict[str, Any]]) -> str:
    draft = _latest_draft(state)
    text = draft.get("body", "") if draft else _final_answer_text(observed)
    if cells:
        _verify_final_text_numbers(case, text, cells, _verified_additional_cells(state))
    return text




def _verify_method_loads(observed: dict[str, Any], manifest: dict[str, Any]) -> None:
    expected = {item["id"]: item for item in manifest.get("skills", [])}
    loaded = observed.get("explicit_loads", [])
    loaded_names = {item.get("name") for item in loaded}
    if loaded_names != set(expected):
        raise AssertionError(f"method skill explicit loads incomplete: {sorted(set(expected) - loaded_names)}")
    for item in loaded:
        name = item["name"]
        source = Path(expected[name]["file"])
        if Path(item.get("resourceBase", {}).get("path", "")).resolve() != source.parent.resolve():
            raise AssertionError(f"method skill {name} loaded from unexpected resource base")
        skill_text = source.read_text(encoding="utf-8")
        body = skill_text.split("---", 2)[2].strip() if skill_text.startswith("---") else skill_text.strip()
        if hashlib.sha256(body.encode()).hexdigest() != item.get("content_sha256"):
            raise AssertionError(f"method skill {name} content hash mismatch")
        resources = item.get("resources", [])
        if {resource.get("resource") for resource in resources} != {"FOUNDRY.md", "CONNECTORS.md"}:
            raise AssertionError(f"method skill {name} did not load both method resources")
        for resource in resources:
            original = Path(manifest["root"]) / resource["resource"]
            if hashlib.sha256(original.read_bytes()).hexdigest() != resource.get("sha256"):
                raise AssertionError(f"method resource hash mismatch for {name}/{resource.get('resource')}")


def _case_tool_errors(observed: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    for index, call in enumerate(observed.get("calls", [])):
        if call.get("isError"):
            errors.append({"index": index, "tool": call.get("name"), "error": call.get("error")})
    return errors


def _terminal_events(observed: dict[str, Any]) -> list[dict[str, Any]]:
    return [event for event in observed.get("events", []) if event.get("type") == "turn/end"]


def _case_hard_errors(observed: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    terminals = _terminal_events(observed)
    ended_normally = bool(terminals and terminals[-1].get("data", {}).get("reason", {}).get("kind") == "completed")
    observer_error = observed.get("error")
    # The v1 observer misclassified retryable stream failures as terminal errors.
    # Correct that classification only with an explicit completed turn/end event.
    if observer_error and not (observer_error == "agent turn ended with error" and ended_normally):
        errors.append({"source": "case", "error": observer_error})
    if observed.get("state_error"):
        errors.append({"source": "analysis-state", "error": observed.get("state_error")})
    if observed.get("events"):
        turn_errors = [event for event in observed["events"]
                       if (event.get("type") == "turn/end" and event.get("data", {}).get("reason", {}).get("kind") == "error")
                       or event.get("type") in {"turn.failed", "error"}]
    else:
        turn_errors = observed.get("turn_errors", [])
    errors.extend({"source": "turn", "error": error} for error in turn_errors)
    return errors


def _case_completed(observed: dict[str, Any]) -> bool:
    terminals = _terminal_events(observed)
    if terminals:
        return terminals[-1].get("data", {}).get("reason", {}).get("kind") == "completed" and not _case_hard_errors(observed)
    return bool(observed.get("completed")) and not _case_hard_errors(observed)


def _failure_record(case: dict[str, Any], observed: dict[str, Any] | None, error: str) -> dict[str, Any]:
    observed = observed or {}
    return {
        "id": case["id"],
        "task_id": case.get("taskId") or observed.get("task_id"),
        "session_id": case.get("sessionId") or observed.get("session_id"),
        "input_sha256": case.get("inputSha256") or observed.get("input_sha256"),
        "duration_ms": observed.get("duration_ms"),
        "completed": _case_completed(observed),
        "final_draft_id": (observed.get("final_draft") or {}).get("id"),
        "error": error,
        "hard_errors": _case_hard_errors(observed),
        "tool_errors": _case_tool_errors(observed),
        "raw_output_sha256": _sha(observed),
    }


def _verify_skill_first(observed: dict[str, Any]) -> None:
    method_loaded = False
    work_tools = {
        "finance_context_save",
        "finance_map_save",
        "run_metric",
        "explain_variance",
        "drilldown_fact",
        "save_explanation_draft",
        "analysis-save",
        "analysis-run",
        "analysis-draft",
        "finance_scenario_save",
        "finance_scenario_run",
    }
    for call in observed.get("calls", []):
        name = call.get("name")
        if name == "skill" and not call.get("isError"):
            method_loaded = True
        if name in work_tools:
            if not method_loaded:
                raise AssertionError(f"case used {name} before successfully loading a method skill")
            return
    raise AssertionError("case did not reach any finance work tool after loading a method skill")

def _has_voucher_detail(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("voucher_detail_available") is True:
            return True
        return any(_has_voucher_detail(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_voucher_detail(child) for child in value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return False
        return not isinstance(decoded, str) and _has_voucher_detail(decoded)
    return False


def _score_case(foundry: Path, var: Path, case: dict[str, Any], observed: dict[str, Any], *, r4: bool = False) -> dict[str, Any]:
    hard_errors = _case_hard_errors(observed)
    if hard_errors:
        raise AssertionError(f"case has hard turn/runtime errors: {hard_errors[:3]}")
    if not _case_completed(observed):
        raise AssertionError("case did not finish normally")
    tool_errors = _case_tool_errors(observed)
    fatal_errors = [err for err in tool_errors if err.get("tool") in {"skill", "method-resource", "list_finance_context"}]
    if fatal_errors:
        raise AssertionError(f"method/catalog tool errors observed: {fatal_errors[:3]}")
    catalog_names = {item.get("name") for item in observed.get("catalog", [])}
    missing_methods = {"financial-statements", "variance-analysis"} - catalog_names
    if missing_methods:
        raise AssertionError(f"case method catalog missing required skills: {sorted(missing_methods)}")
    state = _call(foundry, var, "analysis-state", task=case["taskId"])
    drilled_runs = {_call_spec(call).get("run_id") for call in observed.get("calls", [])
                    if call.get("name") == "drilldown_fact" and not call.get("isError")}
    state["runs"] = sorted(state.get("runs", []), key=lambda run: run.get("id") in drilled_runs)
    allow_missing_data = r4 and case["expected"].get("type") == "price_quantity_missing"
    missing_data_contract_verified = False
    try:
        cells = _find_expected_cells(state, case)
    except AssertionError:
        if not allow_missing_data:
            raise
        _verify_r4_contract(state, _latest_draft(state), {}, allow_missing_data=True)
        missing_data_contract_verified = True
        cells = {}
    calls = observed.get("calls", [])
    used = {call.get("name") for call in calls if not call.get("isError")}
    drilldowns = [call for call in calls if call.get("name") == "drilldown_fact" and not call.get("isError")]
    if case["expected"].get("requires_map_save") and "finance_map_save" not in used:
        raise AssertionError("case required finance_map_save but the model did not call it")
    forbidden = _scan_forbidden(case, observed, state)
    if forbidden:
        raise AssertionError("unsupported causal certainty found in raw output")
    if not used & CALC_TOOLS:
        if not allow_missing_data:
            raise AssertionError("no finance calculation tool was used")
        if not missing_data_contract_verified:
            _verify_r4_contract(state, _latest_draft(state), {}, allow_missing_data=True)
            missing_data_contract_verified = True
    if case["expected"]["type"] not in {"price_quantity_missing"}:
        if not drilldowns and not r4:
            raise AssertionError("no successful drilldown_fact call was observed")
        if r4:
            _verify_r4_traceability(case, observed, state, cells)
        else:
            _verify_drilldowns_reference_cells(case, observed, cells)
    draft_verified = _verified_draft_cells(state, cells)
    if cells and draft_verified != set(cells):
        raise AssertionError(f"draft did not verify all expected cells: {sorted(set(cells) - draft_verified)}")
    if r4 and not missing_data_contract_verified:
        _verify_r4_contract(
            state,
            _latest_draft(state),
            cells,
            allow_missing_data=allow_missing_data,
        )
    _verify_canonical_final_text(case, observed, state, cells)
    if case["expected"].get("requires_voucher_drilldown"):
        if not any(_has_voucher_detail(call.get("value")) for call in drilldowns):
            raise AssertionError("voucher drilldown case did not return voucher_detail_available")
    return {
        "id": case["id"],
        "task_id": case["taskId"],
        "session_id": case["sessionId"],
        "input_sha256": case["inputSha256"],
        "status": "passed",
        "completed": _case_completed(observed),
        "duration_ms": observed.get("duration_ms"),
        "final_draft_id": (observed.get("final_draft") or {}).get("id"),
        "tools_used": sorted(used),
        "run_ids": sorted({cell["run_id"] for cell in cells.values() if not cell.get("synthetic_zero")}),
        "verified_cells": cells,
        "draft_verified": sorted(draft_verified),
        "recoverable_tool_errors": tool_errors,
        "raw_output_sha256": _sha(observed),
    }


def compare_verifications(paths: list[Path]) -> dict[str, Any]:
    runs = []
    by_case: dict[str, list[dict[str, Any]]] = {}
    expected_contract = None
    expected_fixture = None
    expected_inputs = None
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        contract = payload.get("scoring_contract")
        fixture_version = payload.get("fixture_version")
        inputs = {
            case.get("id"): case.get("input_sha256")
            for case in [*payload.get("cases", []), *payload.get("failures", [])]
            if case.get("id")
        }
        if not contract or not fixture_version or not inputs or any(not value for value in inputs.values()):
            raise AssertionError("comparison requires nonempty fixture_version, input hashes, and scoring_contract")
        if expected_contract is None:
            expected_contract = contract
            expected_fixture = fixture_version
            expected_inputs = inputs
        elif contract != expected_contract or fixture_version != expected_fixture or inputs != expected_inputs:
            raise AssertionError("comparison requires the same fixture_version, input hashes, and scoring_contract")
        run = {
            "path": str(path),
            "status": payload.get("status"),
            "completed": payload.get("completed"),
            "passed": payload.get("passed"),
            "workflow_pass_rate": payload.get("workflow_pass_rate", payload.get("pass_rate")),
            "hard_error_count": payload.get("hard_error_count"),
            "model": payload.get("model"),
            "fixture_version": fixture_version,
            "scoring_contract": contract,
        }
        runs.append(run)
        passed_ids = {case.get("id") for case in payload.get("cases", [])}
        failed = {case.get("id"): case for case in payload.get("failures", [])}
        for case_id in passed_ids | set(failed):
            by_case.setdefault(case_id, []).append(
                {
                    "path": str(path),
                    "status": "passed" if case_id in passed_ids else "failed",
                    "error": failed.get(case_id, {}).get("error"),
                }
            )
    case_rows = []
    for case_id, attempts in sorted(by_case.items()):
        passed = sum(1 for attempt in attempts if attempt["status"] == "passed")
        case_rows.append(
            {
                "id": case_id,
                "attempts": len(attempts),
                "passed": passed,
                "first_status": attempts[0]["status"],
                "stable": passed in {0, len(attempts)},
                "errors": [attempt["error"] for attempt in attempts if attempt.get("error")],
            }
        )
    return {
        "status": "passed" if runs and all(run["status"] == "passed" for run in runs) else "failed",
        "runs": runs,
        "cases": case_rows,
        "summary": {
            "runs": len(runs),
            "case_ids": len(case_rows),
            "first_passed": sum(1 for row in case_rows if row["first_status"] == "passed"),
            "stable_cases": sum(1 for row in case_rows if row["stable"]),
        },
    }


def _selected_cases_from_observation(source: Path, fixture: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    summary_path = source / "fixture-summary.json"
    session_path = source / "session.json"
    if not summary_path.is_file() or not session_path.is_file():
        raise AssertionError("rescore source must contain fixture-summary.json and session.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    selected_ids = summary.get("selected_cases")
    if not isinstance(selected_ids, list) or not selected_ids:
        raise AssertionError("rescore source fixture-summary.json must contain selected_cases")
    by_id = {case["id"]: case for case in fixture["cases"] if case.get("runnable")}
    selected = []
    for case_id in selected_ids:
        if case_id not in by_id:
            raise AssertionError(f"rescore selected case is absent from fixture: {case_id}")
        input_path = source / f"{case_id}-input.json"
        if not input_path.is_file():
            raise AssertionError(f"rescore source is missing input record: {input_path.name}")
        input_record = json.loads(input_path.read_text(encoding="utf-8"))
        expected_hash = input_record.get("input_sha256")
        current_hash = _sha(
            {
                "case_id": by_id[case_id]["id"],
                "question": by_id[case_id]["question"],
                "datasets": by_id[case_id]["datasets"],
                "expected": by_id[case_id]["expected"],
            }
        )
        if expected_hash != current_hash:
            raise AssertionError(f"rescore input hash mismatch for {case_id}")
        selected.append({**by_id[case_id], "inputSha256": expected_hash})
    session = json.loads(session_path.read_text(encoding="utf-8"))
    observed_by_id = {row.get("id"): row for row in session.get("cases", [])}
    for case in selected:
        row = observed_by_id.get(case["id"])
        if not row:
            continue
        task_id = row.get("task_id") or row.get("taskId")
        session_id = row.get("session_id") or row.get("sessionId")
        if not task_id or not session_id:
            raise AssertionError(f"rescore source missing task/session id for {case['id']}")
        if row.get("input_sha256") and row.get("input_sha256") != case["inputSha256"]:
            raise AssertionError(f"rescore session input hash mismatch for {case['id']}")
        case["taskId"] = task_id
        case["sessionId"] = session_id
    return selected, session


def rescore_observation(foundry: Path, fixture: dict[str, Any], source: Path, output: Path, *, scoring_contract: str = SCORING_CONTRACT_R3) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    if source == output:
        raise AssertionError("rescore output must be a different directory")
    output.mkdir(parents=True, exist_ok=False)
    selected, observed = _selected_cases_from_observation(source, fixture)
    var = source / "var"
    if not var.is_dir():
        raise AssertionError("rescore source must contain the original var directory")
    source_verification_path = source / "verification.json"
    source_verification = (
        json.loads(source_verification_path.read_text(encoding="utf-8"))
        if source_verification_path.is_file()
        else {}
    )
    score = score_observation(foundry, var, selected, observed, scoring_contract=scoring_contract)
    result = {
        **score,
        "fixture_version": fixture["version"],
        "model": source_verification.get("model") or observed.get("model"),
        "scorer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_observation": str(source),
        "source_fixture_version": json.loads((source / "fixture-summary.json").read_text(encoding="utf-8")).get("fixture_version"),
        "source_scoring_contract": source_verification.get("scoring_contract", "legacy-or-unscored"),
        "source_status": source_verification.get("status"),
        "current_scoring_contract": score["scoring_contract"],
        "selected_cases": [case["id"] for case in selected],
        "source_session_sha256": hashlib.sha256((source / "session.json").read_bytes()).hexdigest(),
    }
    (output / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "rescore-source.json").write_text(
        json.dumps(
            {
                "source_observation": str(source),
                "source_verification": str(source_verification_path) if source_verification_path.is_file() else None,
                "source_scoring_contract": result["source_scoring_contract"],
                "current_scoring_contract": result["current_scoring_contract"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def score_observation(foundry: Path, var: Path, cases: list[dict[str, Any]], observed: dict[str, Any], *, scoring_contract: str = SCORING_CONTRACT_R3) -> dict[str, Any]:
    if scoring_contract not in {SCORING_CONTRACT_R3, SCORING_CONTRACT_R4}:
        raise AssertionError(f"unsupported scoring contract: {scoring_contract}")
    observed_by_id = {row["id"]: row for row in observed.get("cases", [])}
    results = []
    failures = []
    for case in cases:
        row = observed_by_id.get(case["id"])
        if not row:
            failures.append(_failure_record(case, None, "case was selected but no attempt record was observed"))
            continue
        try:
            results.append(_score_case(foundry, var, case, row, r4=scoring_contract == SCORING_CONTRACT_R4))
        except Exception as exc:  # retain failure detail for manual review
            failures.append(_failure_record(case, row, str(exc)))
    seen = len(observed.get("cases", []))
    attempted = len(cases)
    completed = sum(1 for row in observed.get("cases", []) if _case_completed(row))
    passed = len(results)
    rate = Decimal(passed) / Decimal(attempted or 1)
    hard_error_count = sum(len(_case_hard_errors(row)) for row in observed.get("cases", []))
    return {
        "scoring_contract": scoring_contract,
        "seen": seen,
        "attempted": attempted,
        "completed": completed,
        "passed": passed,
        "workflow_pass_rate": format(rate, "f"),
        "hard_error_count": hard_error_count,
        "provider_retry_count": sum(event.get("type") == "llm/retry" for row in observed.get("cases", []) for event in row.get("events", [])),
        "hard_errors_status": "passed" if hard_error_count == 0 else "failed",
        "workflow_status": "passed" if attempted and rate >= Decimal("0.90") else "failed",
        "status": "passed" if attempted and rate >= Decimal("0.90") and hard_error_count == 0 and not failures else "failed",
        "cases": results,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--dsh-root", type=Path, default=DEFAULT_DSH_ROOT)
    parser.add_argument("--foundry", type=Path, default=DEFAULT_FOUNDRY)
    parser.add_argument("--plugin", type=Path, default=DEFAULT_PLUGIN)
    parser.add_argument("--credentials-home", type=Path, default=DEFAULT_CREDENTIALS_HOME)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=[], help="run a specific fixture case; may be repeated")
    parser.add_argument("--cases-limit", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--live", action="store_true", help="invoke the configured model")
    parser.add_argument("--r4", action="store_true", help="score with the r4 requirements/evidence/completion contract")
    parser.add_argument("--validate-fixture-only", action="store_true")
    parser.add_argument("--compare-verification", action="append", type=Path, default=[], help="compare existing verification.json files without invoking a model")
    parser.add_argument("--rescore-observation", type=Path, help="rescore an existing verification directory without invoking a model or modifying it")
    args = parser.parse_args()

    if args.compare_verification:
        args.output = args.output.resolve()
        args.output.mkdir(parents=True, exist_ok=False)
        comparison = compare_verifications(args.compare_verification)
        (args.output / "comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": comparison["status"], "output": str(args.output / "comparison.json")}, ensure_ascii=False))
        return 0 if comparison["status"] == "passed" else 1

    fixture = _load_fixture(args.fixture)
    if args.rescore_observation:
        result = rescore_observation(args.foundry, fixture, args.rescore_observation, args.output,
                                     scoring_contract=SCORING_CONTRACT_R4 if args.r4 else SCORING_CONTRACT_R3)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "attempted": result.get("attempted"),
                    "passed": result.get("passed"),
                    "workflow_pass_rate": result.get("workflow_pass_rate"),
                    "hard_error_count": result.get("hard_error_count"),
                    "output": str(args.output.resolve()),
                },
                ensure_ascii=False,
            )
        )
        return 0 if result["status"] == "passed" else 1
    runnable_all = [case for case in fixture["cases"] if case.get("runnable")]
    if args.case_id:
        wanted = set(args.case_id)
        runnable = [case for case in runnable_all if case["id"] in wanted]
        missing = sorted(wanted - {case["id"] for case in runnable})
        if missing:
            raise AssertionError(f"unknown or non-runnable case id: {', '.join(missing)}")
    else:
        runnable = runnable_all[: args.cases_limit]
    pending = [case["id"] for case in fixture["cases"] if not case.get("runnable")]
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "fixture-summary.json").write_text(
        json.dumps(
            {
                "fixture_version": fixture["version"],
                "total_cases": len(fixture["cases"]),
                "runnable_cases": len(runnable_all),
                "selected_cases": [case["id"] for case in runnable],
                "pending_cases": pending,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if args.validate_fixture_only:
        print(json.dumps({"status": "fixture-valid", "output": str(args.output)}, ensure_ascii=False))
        return 0
    if not args.live:
        parser.error("--live is required unless --validate-fixture-only is used")

    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required for live DSH evals")
    dsh = args.dsh_root / "node_modules/@deepseek-ai/dsh/lib/bin.js"
    if not dsh.is_file():
        raise RuntimeError(f"DSH runtime is missing: {dsh}")
    if not args.foundry.is_file():
        raise RuntimeError(f"foundry CLI is missing: {args.foundry}")

    source_settings = yaml.safe_load((args.credentials_home / "settings.yaml").read_text(encoding="utf-8")) or {}
    selection = source_settings.get("agent-default-model")
    expected_model = fixture["model_contract"]
    if (
        not selection
        or selection.get("provider") != expected_model["provider"]
        or selection.get("model") != expected_model["model"]
        or selection.get("reasoningEffort") != expected_model["reasoning_effort"]
    ):
        raise RuntimeError("configured model does not match the r2 finance eval contract; no provider was changed")
    credentials = yaml.safe_load((args.credentials_home / ".credentials.yaml").read_text(encoding="utf-8")) or {}
    reference = source_settings.get("llm-deepseek", {}).get("apiKeyEnv", "DEEPSEEK_API_KEY")
    refs = credentials.get("refs", credentials)
    if not refs.get(reference):
        raise RuntimeError("configured provider credential is missing; no fallback credential was used")

    var = args.output / "var"
    seeded = _seed_cases(args.foundry, var, args.output, runnable)
    manifest = _call(args.foundry, var, "method-skills", "--json")
    if not manifest.get("exists") or manifest.get("missing"):
        raise RuntimeError("bundled method skills are not available for finance evals")
    config = {
        "dshRoot": str(args.dsh_root.resolve()),
        "report": str(args.output / "session.json"),
        "timeoutSeconds": args.timeout_seconds,
        "agentsHome": "",
        "ids": manifest["ids"],
        "methodRoot": manifest["root"],
        "cases": seeded,
    }
    final = {
        "status": "running",
        "scoring_contract": SCORING_CONTRACT_R4 if args.r4 else SCORING_CONTRACT_R3,
        "fixture_version": fixture["version"],
        "model": selection,
        "method_manifest": manifest,
        "selected_cases": [case["id"] for case in seeded],
        "pending_cases": pending,
    }
    child: subprocess.Popen | None = None
    with tempfile.TemporaryDirectory(prefix="foundry-finance-evals-") as scratch_text:
        scratch = Path(scratch_text)
        home = scratch / "harness"
        home.mkdir()
        config["agentsHome"] = str(scratch / "agents")
        credential_path = home / ".credentials.yaml"
        descriptor = os.open(credential_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as sink:
            yaml.safe_dump({"version": credentials.get("version", 1), "refs": {reference: refs[reference]}}, sink)
        settings = {"agent-default-model": selection, "agent-presets": {"default": "analysis"}}
        if "llm-deepseek" in source_settings:
            settings["llm-deepseek"] = source_settings["llm-deepseek"]
        (home / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
        env = _clean_env(
            {
                "DSH_HOME": str(home),
                "DSH_AGENTS_HOME": str(scratch / "agents"),
                "DSH_BUNDLED_SKILL_DIR": manifest["root"],
                "FOUNDRY_VAR": str(var),
                "FOUNDRY_BIN": str(args.foundry),
            }
        )
        try:
            _call(args.foundry, var, "install-presets", "--dsh-home", home, raw=True)
            subprocess.run([node, str(dsh), "--profile", "web", "--dump-config"], env=env, cwd=scratch, capture_output=True, check=True)
            probe = scratch / "probe"
            probe.mkdir()
            shutil.copyfile(REPO / "tools/verify_finance_evals.mjs", probe / "index.mjs")
            (probe / "config.json").write_text(json.dumps(config), encoding="utf-8")
            profile = home / "profiles/web"
            package_path = profile / "package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package.setdefault("dependencies", {})["finance-skill-foundry-dsh"] = f"link:{args.plugin.resolve()}"
            bundles = package.setdefault("dsh", {}).setdefault("profile", {}).setdefault("bundles", [])
            if "finance-skill-foundry-dsh" not in bundles:
                bundles.append("finance-skill-foundry-dsh")
            package_path.write_text(json.dumps(package), encoding="utf-8")
            modules = profile / "node_modules"
            modules.mkdir(exist_ok=True)
            link = modules / "finance-skill-foundry-dsh"
            if not link.exists():
                link.symlink_to(args.plugin.resolve(), target_is_directory=True)
            (profile / "cordis.patch.yml").write_text(
                yaml.safe_dump([{"insert": [{"id": "foundry-finance-evals-verifier", "name": str(probe / "index.mjs")}]}]),
                encoding="utf-8",
            )
            with (args.output / "runtime.log").open("w", encoding="utf-8") as sink:
                child = subprocess.Popen(
                    [node, str(dsh), "--profile", "web", "--no-open", "--port", "0"],
                    cwd=scratch,
                    env=env,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                observed = _wait_report(child, args.output / "session.json", args.timeout_seconds * max(1, len(seeded)) + 120)
            if observed["model"] != selection:
                raise AssertionError("actual session changed the configured model")
            _verify_method_loads(observed, manifest)
            score = score_observation(args.foundry, var, seeded, observed,
                                      scoring_contract=SCORING_CONTRACT_R4 if args.r4 else SCORING_CONTRACT_R3)
            final.update(score)
            final["session_evidence_sha256"] = hashlib.sha256((args.output / "session.json").read_bytes()).hexdigest()
            final["raw_session_path"] = str(args.output / "session.json")
        except Exception as exc:
            final.update(status="failed", error=str(exc))
        finally:
            _stop(child)
    (args.output / "verification.json").write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": final["status"], "passed": final.get("passed"), "completed": final.get("completed"), "output": str(args.output), "error": final.get("error")}, ensure_ascii=False))
    return 0 if final["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
