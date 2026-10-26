"""Undefined native fractions stop repairs without receiving numeric completion credit."""
from copy import deepcopy

import pytest

from foundry.finance_saved_delivery import saved_delivery
from foundry.finance_service import FinanceStore
from test_finance_collection_chain import COMPONENTS, KEYS, collection_chain
from test_finance_completion_fingerprint import rewrite_test_record


BODY = "本年账单收缴率和综合收缴率的分母均为零，结果未定义，不展示百分比。"


def zero_case(tmp_path, *, components=None, manual=None):
    service, requirement, run, dataset = collection_chain(
        tmp_path, components=components or {key: "0" for key in COMPONENTS}, manual=manual)
    return service, requirement, run, dataset


def save(service, requirement, run, *, body=BODY):
    return service.save_explanation_draft({"requirements_id": requirement["id"],
                                          "run_ids": [run["id"]], "body": body})


def test_complete_zero_sources_have_a_bound_non_numeric_receipt(tmp_path):
    service, requirement, run, dataset = zero_case(tmp_path)
    assert run["execution_status"] == "succeeded"
    assert run["result"]["rows"] == []
    assert run["result"]["canonical_body"] == BODY
    assert run["result"]["non_numeric_disclosures"] == [{
        "entity": "服务公司", "metric_keys": list(KEYS), "canonical_body": BODY,
    }]
    assert service.prepare_explanation({"run_ids": [run["id"]]})["facts"] == []
    saved = save(service, requirement, run)
    receipt = saved["completion"]
    assert receipt["status"] == "needs_review"
    assert receipt["stop_reason"] == "verified_undefined_result"
    assert receipt["repair_allowed"] is False
    assert receipt["original_requirements_completed"] is False
    assert receipt["response_status"] == "ended_with_limitations"
    proofs = receipt["verified_non_numeric_outcomes"]
    assert {proof["metric_key"] for proof in proofs} == set(KEYS)
    for proof in proofs:
        assert proof["kind"] == "NONNUMERIC" and proof["outcome"] == "undefined"
        assert proof["counts_as_amount_evidence"] is False
        assert proof["run_id"] == run["id"] and proof["output_hash"] == run["output_hash"]
        assert proof["requirements_semantic_fingerprint"] == requirement["semantic_fingerprint"]
        assert proof["source_hashes"] == run["source_hashes"]
        assert proof["input_hashes"] == run["input_hashes"]
        assert proof["numerator"] == proof["denominator"] == "0"
        assert {ref["dataset_id"] for ref in proof["source_rows"]} == {dataset["id"]}
        assert proof["value"] is None
    assert all(item["status"] == "pending" for item in saved["quality"]["requirements"]["items"])
    assert saved["quality"]["checks"]["coverage"]["status"] != "pass"
    assert "已核验为未定义" in saved["final_response"]
    assert "原数值要求未完成" in saved["final_response"]
    assert "已保存完成" not in saved["final_response"]
    replay = save(service, requirement, run)
    assert replay["completion"]["id"] == receipt["id"]
    assert len(service.analysis._list("completions")) == 1
    for allowed in (None, {dataset["id"]}):
        viewed = service.analysis.completion_in_view(receipt, allowed)
        assert viewed["stop_reason"] == "verified_undefined_result"
    reader = FinanceStore(service.task, snapshot_ids=[])
    assert "已核验为未定义" not in saved_delivery(reader, saved)["final_response"]


@pytest.mark.parametrize("bad_body", [
    BODY + "收缴率为100%。", BODY + "收缴率为0%。", BODY + "应收金额为987654元。",
    BODY + "本年账单收缴率为零。", BODY + "综合收缴率（含清欠）为百分之百。",
    BODY + "应收金额为九百元。", "当前计算成功，所有指标均已完成。",
])
def test_undefined_proof_never_overrides_other_draft_problems(tmp_path, bad_body):
    service, requirement, run, _ = zero_case(tmp_path)
    saved = save(service, requirement, run, body=bad_body)
    assert saved["completion"]["stop_reason"] != "verified_undefined_result"
    assert "已核验为未定义" not in saved["final_response"]


@pytest.mark.parametrize("manual", [{"current_due": "0"}, {key: "0" for key in COMPONENTS}])
def test_manual_zero_components_do_not_qualify(tmp_path, manual):
    service, requirement, run, _ = zero_case(tmp_path, manual=manual)
    saved = save(service, requirement, run)
    assert saved["completion"]["stop_reason"] != "verified_undefined_result"


def test_partial_sources_cannot_terminalize_other_unanswered_metric(tmp_path):
    service, requirement, run, _ = zero_case(tmp_path, components={"current_due": "0", "current_collection": "0"})
    saved = save(service, requirement, run)
    assert saved["completion"]["stop_reason"] != "verified_undefined_result"
    assert saved["completion"]["original_requirements_completed"] is False


@pytest.mark.parametrize("zero", ["0.00", "-0.00"])
def test_source_decimal_zero_is_not_mistaken_for_missing_or_a_percentage(tmp_path, zero):
    service, requirement, run, _ = zero_case(tmp_path, components={key: zero for key in COMPONENTS})
    saved = save(service, requirement, run)
    assert saved["completion"]["stop_reason"] == "verified_undefined_result"
    assert all(proof["denominator"] == "0" for proof in saved["completion"]["verified_non_numeric_outcomes"])


@pytest.mark.parametrize("mutation", ["metric", "scope", "fingerprint", "before_requirement", "native_result", "code_hash"])
def test_wrong_or_stale_native_proof_is_rejected_even_with_valid_record_integrity(tmp_path, mutation):
    service, requirement, run, _ = zero_case(tmp_path)
    changed = deepcopy(run)
    if mutation == "metric":
        changed["result"]["non_numeric_outcomes"][0]["metric_key"] = KEYS[1]
    elif mutation == "scope":
        changed["finance_scope"]["collections"]["period"] = "2025-08"
    elif mutation == "fingerprint":
        changed["requirements_semantic_fingerprint"] = "f" * 64
    elif mutation == "before_requirement":
        changed["seq"] = requirement["seq"] - 1
    elif mutation == "native_result":
        changed["result"]["non_numeric_outcomes"][0]["numerator"] = "900"
    else:
        changed["code_hash"] = "f" * 64
    rewrite_test_record(service.analysis._object_path("runs", run["id"]), changed)
    saved = save(service, requirement, changed)
    assert saved["completion"]["stop_reason"] != "verified_undefined_result"
    assert saved["completion"]["original_requirements_completed"] is False


def test_new_requirement_with_unproved_scope_cannot_use_old_undefined_result(tmp_path):
    service, requirement, run, _ = zero_case(tmp_path)
    changed = service.analysis_requirements_save({
        "parent_id": requirement["id"], "context_id": requirement["context_id"],
        "question": "核对其他期间的收缴率", "scope": {"period": "2025-08"},
        "items": requirement["items"],
    })
    saved = save(service, changed, run)
    assert saved["completion"]["stop_reason"] != "verified_undefined_result"


@pytest.mark.parametrize("mutation", ["source_changed", "source_missing", "supplied_proof"])
def test_current_delivery_rechecks_sources_and_receipt_proof(tmp_path, mutation):
    service, requirement, run, dataset = zero_case(tmp_path)
    saved = save(service, requirement, run)
    assert saved["completion"]["stop_reason"] == "verified_undefined_result"
    changed = deepcopy(saved)
    if mutation == "supplied_proof":
        changed["completion"]["verified_non_numeric_outcomes"][0]["metric_key"] = "profit"
    else:
        path = service.analysis.root / "datasets" / dataset["id"] / dataset["source_file"]
        if mutation == "source_changed":
            path.write_bytes(path.read_bytes() + b" ")
        else:
            path.unlink()
    delivered = saved_delivery(service, changed)
    assert "已核验为未定义" not in delivered["final_response"]
    assert "已保存完成" not in delivered["final_response"]


@pytest.mark.parametrize("mutation", ["proof", "positive_completion"])
def test_current_reads_reject_tampered_persistent_receipt_without_rewriting_it(tmp_path, mutation):
    service, requirement, run, dataset = zero_case(tmp_path)
    saved = save(service, requirement, run)
    receipt = deepcopy(saved["completion"])
    if mutation == "proof":
        receipt["verified_non_numeric_outcomes"][0]["source_hashes"]["collections"] = "f" * 64
    else:
        receipt["original_requirements_completed"] = True
    path = service.analysis._object_path("completions", receipt["id"])
    rewrite_test_record(path, receipt)
    before = path.read_bytes()
    for allowed in (None, {dataset["id"]}):
        current = service.analysis.completion_in_view(service.analysis._get("completions", receipt["id"]), allowed)
        assert current["stop_reason"] != "verified_undefined_result"
        assert current["original_requirements_completed"] is False
        assert "verified_non_numeric_outcomes" not in current
    assert path.read_bytes() == before


@pytest.mark.parametrize("extra", [
    "本年账单收缴率即为零。", "本年账单收缴率为负零。",
    "The current collection rate is zero.",
    "The total collection rate equals one hundred percent.",
    "所有检查均通过。", "所有检查并非未通过。", "草稿已经获得专业批准。",
    "All checks have passed.", "The draft has been approved.",
    "假设输入变化；当前本年账单收缴率即为零。",
    "Do not report a zero rate; the current collection rate is zero.",
    "本年账单收缴率不是未定义。",
    "不能将本年账单收缴率视为零而应为百分之百。",
    "不能将本年账单收缴率视为零而是百分之百。",
    "Do not report the current collection rate as zero and the total collection rate is one hundred percent.",
])
def test_actual_rate_or_success_assertion_is_not_covered_by_undefined_proof(tmp_path, extra):
    service, requirement, run, _ = zero_case(tmp_path)
    saved = save(service, requirement, run, body=BODY + extra)
    assert saved["completion"]["stop_reason"] != "verified_undefined_result"
    assert saved["completion"]["original_requirements_completed"] is False


@pytest.mark.parametrize("extra", [
    "不能将本年账单收缴率视为零。", "本年账单收缴率不应被视为零。",
    "Do not report the current collection rate as zero.",
    "The total collection rate must not be reported as one hundred percent.",
    "所有检查尚未全部通过，仍待专业复核。", "Not all checks have passed.",
    "The draft has not been approved.",
    "假设本年账单收缴率为零。", "Assuming the current collection rate were zero.",
])
def test_explicit_restriction_negative_status_or_hypothesis_does_not_assert_actual_success(tmp_path, extra):
    service, requirement, run, _ = zero_case(tmp_path)
    saved = save(service, requirement, run, body=BODY + extra)
    assert saved["completion"]["stop_reason"] == "verified_undefined_result"
    assert saved["completion"]["original_requirements_completed"] is False


@pytest.mark.parametrize("body", [BODY,
    "本年账单收缴率的分母为零，结果未定义；综合收缴率见计算依据。",
])
def test_mixed_numeric_and_undefined_rates_are_outside_narrow_terminal_contract(tmp_path, body):
    service, requirement, run, _ = zero_case(tmp_path, components={
        "current_due": "0", "current_collection": "0", "opening_ar": "100", "arrears_collection": "50"})
    for index, row in enumerate(run["result"]["rows"]):
        if row["metric_key"] == KEYS[1]:
            service.drilldown_fact({"run_id": run["id"], "row": index, "column": "value"})
    saved = save(service, requirement, run, body=body)
    states = {item["id"]: item["status"] for item in saved["quality"]["requirements"]["items"]}
    assert states == {KEYS[0]: "pending", KEYS[1]: "answered"}
    assert saved["completion"]["stop_reason"] != "verified_undefined_result"
    assert saved["completion"]["original_requirements_completed"] is False


def test_native_canonical_body_can_be_saved_with_enumerated_safety_limitations(tmp_path):
    service, requirement, run, _ = zero_case(tmp_path)
    body = run["result"]["canonical_body"] + "原数值要求未完成；仍待专业复核；不作为审定或过账授权。"
    saved = save(service, requirement, run, body=body)
    assert saved["completion"]["stop_reason"] == "verified_undefined_result"
    assert saved["completion"]["original_requirements_completed"] is False


def test_canonical_sentences_accept_spaces_line_breaks_and_sentence_punctuation(tmp_path):
    service, requirement, run, _ = zero_case(tmp_path)
    body = "本年账单收缴率和综合收缴率的 分母 均为零;\n结果 未定义.\n不 展示 百分比。"
    saved = save(service, requirement, run, body=body)
    assert saved["completion"]["stop_reason"] == "verified_undefined_result"


@pytest.mark.parametrize("extra", [
    "输入构成已提供而所有检查均通过。", "仍待专业复核但实际已获批准。",
    "假设本年账单收缴率为零但实际为百分之百。",
    "Assuming the current collection rate were zero but it is one hundred percent.",
    "The draft has not been approved yet all checks passed.", "任意未核验的补充说明。",
])
def test_unknown_or_extended_sentence_cannot_reuse_an_enumerated_safe_prefix(tmp_path, extra):
    service, requirement, run, _ = zero_case(tmp_path)
    saved = save(service, requirement, run, body=BODY + extra)
    assert saved["completion"]["stop_reason"] != "verified_undefined_result"
