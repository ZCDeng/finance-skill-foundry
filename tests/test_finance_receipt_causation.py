"""Cash collection alone does not originate a new receivable."""
from copy import deepcopy

import pytest

from foundry.analysis import _hash
from foundry.finance_claim_semantics import check_claim_semantics
from test_finance_professional_protocol import _template_case


BAD = "本期履约收款对应本期已履约服务并形成新应收。"
CODE = "receipt_receivable_causation_mismatch"


@pytest.fixture
def statement(tmp_path):
    service, _, _, run = _template_case(tmp_path)
    return service, run


@pytest.mark.parametrize("body", [
    BAD,
    "本期收款形成新增应收。",
    "收款导致应收账款增加。",
    "本期收入按履约确认；收款形成新应收。",
    "不能忽略收入确认，但本期收款产生新增应收。",
    "本期收款形成了新增应收。",
    "本期收款增加应收账款。",
    "客户付款形成新增应收。",
    "本期收款不是旧债权清偿而是本期履约价款并形成新应收。",
    "本期收款对应本期已履约服务，并形成新应收。",
    "本期若干客户收款形成新增应收。",
])
def test_explicit_receipt_origin_claim_is_rejected(statement, body):
    _, run = statement
    before = deepcopy(run)
    issues = check_claim_semantics(body, [], runs=[run])
    assert [issue["code"] for issue in issues] == [CODE]
    assert issues[0]["run_id"] == run["id"]
    assert issues[0]["output_hash"] == run["output_hash"]
    assert run == before


@pytest.mark.parametrize("body", [
    "收入确认依履约假设；收款用于结清已识别债权。",
    "本期已履约赊销形成新应收，后续收款冲减应收。",
    "本期收款后仍有未结清应收。",
    "本期收款形成新的现金流入。",
    "不能说本期收款形成新应收。",
    "收款不形成新应收。",
    "收款形成新应收的说法错误。",
    "“收款形成新应收”这一说法不正确。",
    "收款形成新应收吗？",
    "如果将收款视为形成新增应收，必须重新审查。",
    "若存在尚未结清的履约价款，应收增加；收款用于冲减债权。",
    "本期已履约并形成新应收的服务收款用于结清债权。",
    "本期收款对应前期已履约并形成新应收的服务。",
    "尚未收款的本期已履约赊销形成新增应收。",
    "本期收款清偿既有债权且本期赊销形成新应收。",
    "“收款形成新应收”只是假设，并非本期处理。",
    "收款形成新应收的说法并不成立。",
    "收款形成新应收并不正确。",
])
def test_denials_questions_conditions_and_credit_sales_are_preserved(statement, body):
    _, run = statement
    assert check_claim_semantics(body, [], runs=[run]) == []


@pytest.mark.parametrize("mutation", ["hash", "failed", "other_template", "multiple"])
def test_causation_guard_does_not_borrow_unbound_run_authority(statement, mutation):
    _, original = statement
    run = deepcopy(original)
    runs = [run]
    if mutation == "hash":
        run["output_hash"] = "not-current"
    elif mutation == "failed":
        run["execution_status"] = "failed"
    elif mutation == "other_template":
        run["result"]["template_id"] = "unregistered"
        run["output_hash"] = _hash(run["result"])
    else:
        runs.append({**deepcopy(run), "id": "another-run"})
    assert check_claim_semantics(BAD, [], runs=runs) == []


@pytest.mark.parametrize("short", [False, True])
def test_save_blocks_bad_causation_and_keeps_failed_version(statement, short):
    service, run = statement
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    spec = ({**prepared["save_template_spec"], "qualitative_note": BAD} if short else
            {**prepared["draft_template"], "body": prepared["draft_template"]["body"] + "\n" + BAD})
    failed = service.save_explanation_draft(spec)
    assert failed["completion"]["status"] != "complete"
    assert any(issue["code"] == CODE for issue in failed["quality"]["issues"])
    repaired = service.save_explanation_draft({**prepared["save_template_spec"], "parent_id": failed["id"]})
    assert repaired["completion"]["status"] == "complete"
    assert service.analysis.get_draft(failed["id"])["quality"]["status"] == "needs_attention"


def test_saved_old_verdict_is_rechecked_read_only(statement):
    from foundry.finance_explanations import saved_claim_semantic_issues

    service, run = statement
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    draft = service.save_explanation_draft(prepared["save_template_spec"])
    draft["body"] += "\n" + BAD
    draft["body_template"] += "\n" + BAD
    for key in ("quality", "explanation_check"):
        if key in draft:
            draft[key]["claim_semantics_version"] = 9
    before = deepcopy(draft)
    assert any(issue["code"] == CODE for issue in saved_claim_semantic_issues(service.analysis, draft))
    assert draft == before
