"""Receipt recognition wording is a local advisory, never new financial authority."""
import json

import pytest

from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION
from foundry.finance_explanations import _ar_wording_asserted, _ar_wording_suggestions
from test_finance_ar_wording import render_saved
from test_finance_receipt_source_wording import OLD_AR, save_note, source_case


CODE = "receipt_recognition_pairing_ambiguous"
EXACT = "本期履约服务收款按履约假设确认，未收价款形成期末应收余额。"
FIXED = "本期履约服务收入按履约假设确认；收款按来源分别说明，未收价款形成期末应收余额。"


def advice(body, regions=None):
    return [issue for issue in _ar_wording_suggestions(body, regions or []) if issue["code"] == CODE]


@pytest.mark.parametrize("short", [False, True], ids=["ordinary", "compact"])
def test_exact_actual_sentence_is_public_advisory_and_revision_keeps_history(tmp_path, short):
    service, record, _, _, run, prepared = source_case(tmp_path, OLD_AR)
    assert prepared["forecast_performance"]["status"] == "verified"
    assert len(prepared["forecast_performance"]["facts"]) == 1
    run_path = service.analysis._object_path("runs", run["id"])
    run_before = run_path.read_bytes()
    saved = save_note(service, prepared, EXACT, short)
    parent_path = service.analysis._object_path("drafts", saved["id"])
    parent_before = parent_path.read_bytes()
    public = render_saved(saved)
    fixed = save_note(service, prepared, FIXED, short, parent_id=saved["id"])
    stored_receipts = service.analysis._list("completions")
    latest = max(stored_receipts, key=lambda receipt: receipt["seq"])
    current = service.analysis.completion_in_view(latest, None)
    observations = {
        "source_record": record, "prepared": prepared, "saved": saved, "public": public,
        "fixed": fixed, "stored_latest_receipt": latest, "current_receipt": current,
    }
    (tmp_path / "observed-public-results.json").write_text(
        json.dumps(observations, ensure_ascii=False, indent=2) + "\n")
    assert EXACT in saved["body"] and EXACT in saved["body_template"]
    assert saved["quality"]["status"] == "pass" and saved["quality"]["issues"] == []
    assert saved["completion"]["status"] == "complete"
    assert saved["quality"]["claim_semantics_version"] == CLAIM_SEMANTICS_VERSION
    assert public["quality"]["readability"] == saved["quality"]["readability"]
    assert public["explanation_check"]["readability"] == saved["quality"]["readability"]
    assert public["completion"]["status"] == "complete"
    assert public["final_response"] == saved["final_response"]
    assert fixed["parent_id"] == saved["id"] and fixed["completion"]["status"] == "complete"
    assert FIXED in fixed["body"] and not advice(fixed["body"])
    assert fixed["claims"] == saved["claims"] and fixed["run_ids"] == saved["run_ids"]
    assert fixed["requirements_id"] == saved["requirements_id"]
    assert current["status"] == "complete" and current["draft_id"] == fixed["id"]
    assert latest["id"] == fixed["completion"]["id"]
    assert parent_path.read_bytes() == parent_before and run_path.read_bytes() == run_before
    issues = advice(saved["body"])
    assert len(issues) == 1, saved["quality"]["readability"]
    located = [i for i in saved["quality"]["readability"]["issues"] if i["code"] == CODE]
    assert len(located) == 1
    assert {key: located[0][key] for key in issues[0]} == issues[0]
    assert located[0]["origin"] == "manager_body"
    assert located[0]["location"] == {"section": "manager_body", "position": issues[0]["position"]}
    assert issues[0]["severity"] == "suggestion"


@pytest.mark.parametrize("wrapper", ["{}", "## {}", "- {}", "> {}", "**{}**", "| 处理 | {} |"])
def test_exact_relation_is_advised_across_prose_layouts(wrapper):
    body = wrapper.format(EXACT)
    issues = advice(body)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["severity"] == "suggestion"
    assert body[issue["position"]:issue["position"] + len(issue["text"])] == issue["text"]


@pytest.mark.parametrize("body", [
    "收款按履约确认。", "当期服务收款依据履约条件确认。", "本月收款依履约假设确认。",
    "若干收款按履约确认。", "“收款按履约确认”这一表述正确。",
    "并非所有合同都赊销；收款按履约确认。",
])
def test_bounded_affirmative_receipt_recognition_relation(body):
    assert len(advice(body)) == 1


@pytest.mark.parametrize("body", [
    FIXED, "收入按履约确认。", "收款对应的收入按履约确认。",
    "收款按履约确认的债权记录追溯来源。", "收款按履约确认 的债权记录追溯来源。",
    "**收款按履约确认**的债权记录追溯来源。", "本期收款按已识别债权来源追踪。",
    "对已识别债权的收款属于清偿；收入按履约假设确认。",
    "已履约现销按履约假设确认收入并收到现金。",
    "应收款按履约假设确认。", "预收款按履约假设确认。", "未收款按履约假设确认。",
    "并非本期履约服务收款按履约假设确认。", "不能写成“收款按履约确认”。",
    "“收款按履约确认”这一说法不正确。", "是否可以说收款按履约确认？",
    "如果收款按履约确认，则需要核查这种表述。", "若收款按履约确认，则需要核查这种表述。",
    "收款入账。收入按履约假设确认。",
    "```text\n收款按履约确认。\n```", "示例：`收款按履约确认`",
])
def test_correct_subject_trace_or_unasserted_relation_gets_no_new_advice(body):
    assert not advice(body)


@pytest.mark.parametrize("body", [
    "如果收款按履约确认，则核查该表述；但本期收款按履约确认。",
    "“收款按履约确认”这一说法不正确；“收款按履约确认”这一表述正确。",
])
def test_later_independent_assertion_remains_local(body):
    issues = advice(body)
    assert len(issues) == 1
    assert issues[0]["position"] >= body.index("；")


def test_trusted_mask_exempts_only_its_exact_range():
    phrase = "收款按履约确认。"
    body = phrase + "\n" + phrase
    issues = advice(body, [{"start": 0, "end": len(phrase)}])
    assert len(issues) == 1 and issues[0]["position"] > len(phrase)


@pytest.mark.parametrize("body,expected", [
    ("如果收款按履约确认，则核查该表述。", False),
    ("若收款按履约确认，则核查该表述。", False),
    ("假如收款按履约确认，则核查该表述。", False),
    ("若干收款按履约确认。", True),
    ("如果来源已核实，收款按履约确认。", True),
    ("并非收款按履约确认。", False),
    ("不能写成“收款按履约确认”。", False),
    ("“收款按履约确认”这一说法不正确。", False),
    ("“收款按履约确认”这一表述正确。", True),
])
def test_existing_assertion_helper_must_distinguish_local_condition_from_assertion(body, expected):
    """Only the new receipt-subject branch opts into the bounded conditional handling."""
    relation = "收款按履约确认"
    start = body.index(relation)
    assert _ar_wording_asserted(
        body, start, start + len(relation), receipt_subject=True,
    ) is expected


@pytest.mark.parametrize("prefix", ["如果", "若"])
def test_existing_advisory_helper_default_does_not_inherit_receipt_subject_opt_in(prefix):
    """Preserve the legacy default contract while the new branch gains its local check."""
    relation = "收款按履约确认"
    body = prefix + relation + "，则核查该表述。"
    assert _ar_wording_asserted(body, len(prefix), len(prefix) + len(relation)) is True
