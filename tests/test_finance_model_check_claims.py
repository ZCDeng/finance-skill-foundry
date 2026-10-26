"""Passing a lower-bound check does not assert a zero numerical difference."""
from copy import deepcopy

import pytest

from foundry.analysis import _hash
from foundry.finance_claim_semantics import check_claim_semantics
from test_finance_professional_protocol import _template_case


BAD_LIVE_PROSE = "十二项模型联动检查全部通过（实际与期望差异为零）"
CODE = "model_check_difference_claim_mismatch"


@pytest.fixture
def native_statement(tmp_path):
    service, _, requirement, run = _template_case(tmp_path)
    checks = run["result"]["model_checks"]
    assert len(checks) == 12 and all(item["status"] == "pass" for item in checks)
    assert all(item["source_rows"] for item in checks)
    assert [item["id"] for item in checks if item["difference"] != "0"] == [
        "nonnegative_operating_balances", "restricted_cash_bounds", "cash_sufficiency"]
    return service, requirement, run


@pytest.mark.parametrize("body", [
    BAD_LIVE_PROSE,
    "所有模型检查的差异均为零。",
    "模型检查的实际与期望差异全部为零。",
    "12 项 model_checks 全部通过，实际与期望差异均为 0。",
    "全部 model_checks 的 difference 均为 0。",
    "All model checks passed (all differences are zero).",
    "Model checks all passed; all differences are zero.",
    "不能误报检查结果，但所有模型检查差异均为零。",
    "期末模型检查全部通过，差异均为 0.00。",
    "合同已确认；所有模型检查的差异均为零。",
    "预算保持不变，所有模型检查的差异均为零。",
    "不能忽略边界；所有模型检查的差异均为零。",
    "所有模型检查，包括 cash_sufficiency，差异均为零。",
])
def test_universal_zero_difference_claim_conflicts_with_native_passed_bounds(native_statement, body):
    _, _, run = native_statement
    before = deepcopy(run)
    issue, = check_claim_semantics(body, [], runs=[run])
    assert issue["code"] == CODE and issue["severity"] == "error"
    assert issue["run_id"] == run["id"] and issue["output_hash"] == run["output_hash"]
    assert issue["all_checks_passed"] is True
    assert [item["id"] for item in issue["nonzero_checks"]] == [
        "nonnegative_operating_balances", "restricted_cash_bounds", "cash_sufficiency"]
    assert all(item["status"] == "pass" for item in issue["nonzero_checks"])
    assert run == before


@pytest.mark.parametrize("body", [
    "十二项模型联动检查全部通过。",
    "模型检查通过不等于差异为零。",
    "所有模型检查通过不意味着差异均为零。",
    "所有模型检查差异均为零吗？",
    "所有模型检查差异均为零？",
    "全部模型检查的差异并非为零。",
    "并非所有模型检查差异为零。",
    "不能说所有模型检查差异为零。",
    "如果所有模型检查差异为零，才可如此表述。",
    "如果忽略限制，所有模型检查差异均为零。",
    "假设所有模型检查的差异均为零。",
    "“所有模型检查差异为零”这一说法错误。",
    "所有模型检查差异为零的说法不正确。",
    "模型检查全部通过，其中等式核查的差异均为零。",
    "所有等式模型检查的差异为零。",
    "模型检查全部通过，其中 closing_balance_sheet 的差异为零。",
    "模型检查全部通过；期末资产负债表平衡检查差异为零。",
    "模型检查全部通过；期初平衡差异为零。",
    "模型检查全部通过；现金流勾稽差异为零。",
    "模型检查全部通过，预算与实际差异为零。",
    "模型检查全部通过，合同核对差异均为零。",
    "本期收入差异均为零，模型检查全部通过。",
    "Model checks all passed. Other differences are zero.",
    "Model checks all passed; equality checks have zero differences.",
    "Not all model checks have differences of zero.",
    "If all model checks have zero differences, the statement is valid.",
    "The claim 'all model checks have differences of zero' is wrong.",
])
def test_scoped_or_nonaffirmative_statements_are_not_universal_claims(native_statement, body):
    _, _, run = native_statement
    assert check_claim_semantics(body, [], runs=[run]) == []


@pytest.mark.parametrize("mutation", ["other_engine", "other_template", "failed_run", "bad_hash", "multiple_runs"])
def test_check_claims_never_borrow_unbound_or_ambiguous_run_authority(native_statement, mutation):
    _, _, original = native_statement
    run = deepcopy(original)
    runs = [run]
    if mutation == "other_engine":
        run["engine"] = "sql"
    elif mutation == "other_template":
        run["result"]["template_id"] = "other_model"
        run["output_hash"] = _hash(run["result"])
    elif mutation == "failed_run":
        run["execution_status"] = "failed"
    elif mutation == "bad_hash":
        run["result"]["model_checks"][0]["difference"] = "17"
    else:
        runs.append({**deepcopy(run), "id": "another-run"})
    assert check_claim_semantics(BAD_LIVE_PROSE, [], runs=runs) == []


def test_zero_differences_are_allowed_when_recorded_checks_really_are_zero(native_statement):
    _, _, original = native_statement
    run = deepcopy(original)
    run["result"]["model_checks"] = [item for item in run["result"]["model_checks"] if item["difference"] == "0"]
    run["output_hash"] = _hash(run["result"])
    assert check_claim_semantics("所有模型检查差异均为零。", [], runs=[run]) == []


@pytest.mark.parametrize("short", [False, True])
def test_ordinary_and_short_saves_block_false_zero_without_failing_native_checks(native_statement, short):
    service, requirement, run = native_statement
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    spec = ({**prepared["save_template_spec"], "qualitative_note": BAD_LIVE_PROSE} if short else
            {**prepared["draft_template"], "body": prepared["draft_template"]["body"] + "\n" + BAD_LIVE_PROSE})
    draft = service.save_explanation_draft(spec)
    assert draft["quality"]["status"] == "needs_attention"
    assert draft["completion"]["status"] != "complete"
    assert any(issue["code"] == CODE for issue in draft["quality"]["issues"])
    assert all(item["status"] == "pass" for item in service.analysis.get_run(run["id"])["result"]["model_checks"])
    repaired = service.save_explanation_draft({**prepared["save_template_spec"], "parent_id": draft["id"],
        "qualitative_note": "模型检查全部通过；等式勾稽与阈值判断遵循各自核查规则。"})
    assert repaired["completion"]["status"] == "complete"
    assert repaired["quality"]["requirements"]["requirements_id"] == requirement["id"]
    assert service.analysis.get_draft(draft["id"])["quality"]["status"] == "needs_attention"


def test_previous_semantic_verdict_is_rechecked_without_mutating_draft_or_run(native_statement):
    from foundry.finance_explanations import saved_claim_semantic_issues
    service, _, run = native_statement
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    legacy = service.save_explanation_draft(prepared["save_template_spec"])
    legacy["body"] += "\n" + BAD_LIVE_PROSE
    legacy["body_template"] += "\n" + BAD_LIVE_PROSE
    for key in ("quality", "explanation_check"):
        if key in legacy:
            legacy[key]["claim_semantics_version"] = 8
    before = deepcopy(legacy)
    run_before = service.analysis.get_run(run["id"])
    assert any(issue["code"] == CODE for issue in saved_claim_semantic_issues(service.analysis, legacy))
    assert legacy == before
    assert service.analysis.get_run(run["id"]) == run_before
