#!/usr/bin/env python3
"""Freeze or verify independent synthetic supplements without executing Foundry.

Freeze requires the prior stage gate and an independent review of the exact
candidate bytes. Existing frozen artifacts are never overwritten.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "tests/fixtures/finance_supplements/three_statement_v1"
ORIGINAL_SHA = "54f91a277c669e33329d2aaa48728a7db551ed80810e750bb5856f7c91d4ad4d"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def artifacts(root):
    return {
        str(path.relative_to(root)): sha(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {"manifest.json", "freeze.sha256"}
    }


def independent_values(x):
    """Direct Decimal movement equations, independent of product imports."""
    x = {key: Decimal(value) for key, value in x.items()}
    y = {
        "net_income": x["revenue"] - x["operating_expense"] - x["depreciation"],
        "cash_flow_operating": x["customer_receipts"] - x["supplier_payments"],
        "cash_flow_investing": -x["capex"],
        "cash_flow_financing": x["debt_drawdowns"] - x["debt_principal_repayments"] - x["dividends_paid"],
        "closing_receivables": x["opening_receivables"] + x["revenue"] - x["customer_receipts"],
        "closing_ppe": x["opening_ppe"] + x["capex"] - x["depreciation"],
        "closing_payables": x["opening_payables"] + x["operating_expense"] - x["supplier_payments"],
        "closing_debt": x["opening_debt"] + x["debt_drawdowns"] - x["debt_principal_repayments"],
    }
    y["closing_cash"] = x["opening_cash"] + sum(y[key] for key in ("cash_flow_operating", "cash_flow_investing", "cash_flow_financing"))
    y["closing_equity"] = x["opening_equity"] + y["net_income"] - x["dividends_paid"]
    y["total_assets"] = y["closing_cash"] + y["closing_receivables"] + y["closing_ppe"]
    y["total_liabilities_equity"] = y["closing_payables"] + y["closing_debt"] + y["closing_equity"]
    y["available_cash"] = y["closing_cash"] - x["closing_restricted_cash"]
    require(sum(x[key] for key in ("opening_cash", "opening_receivables", "opening_ppe")) == sum(x[key] for key in ("opening_payables", "opening_debt", "opening_equity")), "opening imbalance")
    require(y["total_assets"] == y["total_liabilities_equity"], "closing imbalance")
    require(y["cash_flow_operating"] == y["net_income"] + x["depreciation"] - (y["closing_receivables"] - x["opening_receivables"]) + (y["closing_payables"] - x["opening_payables"]), "indirect cash bridge mismatch")
    return y


def validate(root, index):
    contract = read(root / "contract.json")
    require(contract["suite_id"] == index["suite_id"] == "professional_supplement_v2", "suite identity mismatch")
    require(contract["template_id"] == "linked_three_statement_management_v1", "template mismatch")
    metrics = contract["required_metrics"]
    checks = contract["required_model_checks"]
    require(len(set(metrics)) == len(metrics) == 13, "expected thirteen unique metrics")
    require(len(set(checks)) == len(checks) == 12, "expected twelve unique model checks")
    require(contract["limits"] == {"timeout_seconds": 420, "max_tool_turns": 80}, "original runtime limits changed")
    require(contract["model_protocol"]["controller_attempt_retries"] == 0, "controller retry gate changed")
    require(contract["original_release"]["credit"] == 0, "supplements must not credit original release")
    require(len(contract["negative_cases"]) == 8, "negative case count changed")
    expected_slots = {(row["case_id"], repeat) for row in index["cases"] for repeat in (1, 2, 3)}
    actual_slots = [(slot["case_id"], slot["repeat_index"]) for slot in contract["planned_slots"]]
    require(len(index["cases"]) == 3 and len(actual_slots) == 9 and set(actual_slots) == expected_slots, "supplement slot mismatch")
    for case in index["cases"]:
        case_id = case["case_id"]
        prefix = f"public/{case_id}/"
        names = ("request.json", "template_inputs.json", "model_boundary.json", "transaction_allocation.json")
        require(set(case["public_files"]) == {prefix + name for name in names}, "public selection is not isolated")
        require(case["oracle_path"] == f"private/oracles/{case_id}.json", "oracle path mismatch")
        request = read(root / prefix / "request.json")
        inputs = read(root / prefix / "template_inputs.json")["rows"]
        boundaries = read(root / prefix / "model_boundary.json")["rows"]
        allocation = read(root / prefix / "transaction_allocation.json")
        oracle = read(root / case["oracle_path"])
        values = {row["input_name"]: row["amount"] for row in inputs}
        require(len(values) == len(inputs) == 16, "source input names must be unique")
        require(len(boundaries) == len({row["boundary_name"] for row in boundaries}) == 8, "boundary rows must be unique")
        require(set(case["source_bindings"]) == set(values), "input binding mismatch")
        require(set(case["boundary_bindings"]) == {"boundary." + row["boundary_name"] for row in boundaries}, "boundary binding mismatch")
        for row in inputs + boundaries:
            name = row.get("input_name", "boundary." + row.get("boundary_name", ""))
            required_period = "2026-09" if name.startswith("opening_") else "2026-10"
            require(row["period"] == required_period, "source row period mismatch")
            require(all(row[key] == value for key, value in contract["scope_identity"].items()), "source row identity mismatch")
        require(all(Decimal(row["amount"]) == 0 for row in boundaries), "nonzero positive-case boundary")
        require(request["reporting_profile"]["purpose"] == "forecast" and request["reporting_profile"]["fiscal_year_start"] == "2026-01-01", "public profile source incomplete")
        require(request["case_id"] == oracle["case_id"] == allocation["case_id"] == case_id, "case identity mismatch")
        require(set(oracle["expected_values"]) == set(metrics) and oracle["numeric_tolerance"] == "0", "oracle key or tolerance mismatch")
        calculated = independent_values(values)
        require(all(calculated[key] == Decimal(value) for key, value in oracle["expected_values"].items()), "independent numeric oracle mismatch")
        require(oracle["required_model_checks"] == dict.fromkeys(checks, "pass"), "oracle model check mismatch")
        require(sum(Decimal(row["amount"]) for row in allocation["cash_receipt_allocations"]) == Decimal(values["customer_receipts"]), "receipt allocation mismatch")
        old = allocation["cash_receipt_allocations"][0]
        require(old["receivable_id"] == allocation["opening_receivable"]["receivable_id"], "old receivable identity mismatch")
        require(Decimal(old["amount"]) <= Decimal(allocation["opening_receivable"]["opening_amount"]) == Decimal(values["opening_receivables"]), "old receivable allocation exceeds opening amount")
    observed = artifacts(root)
    require(len(observed) == 16 and observed == index["artifact_hashes"], "candidate bytes changed or omitted")
    original = ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json"
    require(sha(original) == ORIGINAL_SHA, "original frozen release manifest changed")
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-root", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--candidate-index", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--stage1-gate", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = args.suite_root.resolve()
    manifest_path, seal_path = root / "manifest.json", root / "freeze.sha256"
    if args.verify:
        manifest = read(manifest_path)
        require(manifest["status"] == "frozen", "suite is not frozen")
        require(seal_path.read_text() == f"{sha(manifest_path)}  manifest.json\n", "manifest seal mismatch")
        validate(root, manifest)
        result = {"status": "passed", "manifest_sha256": sha(manifest_path), "files": 16, "numeric_assertions": 39, "original_release_credit": 0}
    else:
        require(all((args.candidate_index, args.review, args.stage1_gate)), "freeze requires candidate index, independent review and stage1 gate")
        require(not manifest_path.exists() and not seal_path.exists(), "refuse overwriting frozen suite")
        index, review, gate = read(args.candidate_index), read(args.review), read(args.stage1_gate)
        require(gate["status"] == "passed" and gate["supplement_implementation_authorized"] is True, "stage1 gate is not passed")
        observed = validate(root, index)
        require(review["status"] == "passed", "independent pre-freeze review is not passed")
        require(review["reviewed_artifact_hashes"] == observed, "independent review does not bind exact candidate bytes")
        require(review["candidate_index_sha256"] == sha(args.candidate_index), "independent review candidate index differs")
        manifest = {**index, "status": "frozen", "frozen_at": datetime.now(timezone.utc).isoformat(), "scope": "independent synthetic management forecast; zero original release credit", "original_frozen_manifest_sha256": ORIGINAL_SHA, "stage1_gate_sha256": sha(args.stage1_gate), "pre_freeze_review_sha256": sha(args.review), "candidate_index_sha256": sha(args.candidate_index), "freeze_tool_sha256": sha(Path(__file__)), "validation": {"numeric_assertions": 39, "opening_balance_checks": 3, "closing_balance_checks": 3, "indirect_cash_bridges": 3, "product_runs": 0, "model_runs": 0, "professional_signatures": 0}}
        with manifest_path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        with seal_path.open("x", encoding="utf-8") as output:
            output.write(f"{sha(manifest_path)}  manifest.json\n")
        result = {"status": "frozen", "manifest_sha256": sha(manifest_path), "files": 16, "model_slots": 9, "original_release_credit": 0}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
