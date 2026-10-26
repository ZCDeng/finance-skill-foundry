"""Nonblocking AR wording advice preserves text, accounting gates and public delivery."""
from copy import deepcopy
import json
import subprocess

import pytest

from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION
from foundry.finance_explanations import _readability_suggestions
from test_finance_runtime_payload import ROOT, restore, restore_table
from test_finance_statement_draft_template import statement as _statement_fixture

statement = _statement_fixture
CODES = {"receipt_recognition_pairing_ambiguous", "receipt_offset_object_ambiguous"}
PAIR = "本期履约收入与其对应收款分别按履约确认与债权形成追踪"
OBJECT = "本期履约收款冲抵本期已履约服务 S-CUR-01 的收款，与本期收入确认分别对应"
CLEAR = "收入按履约假设确认；对已识别债权的收款属于清偿，清偿对象按来源核对；来源追踪单独说明。"
CASES = [('B01', '本期履约收入与其对应收款分别按履约确认与债权形成追踪', True),
 ('B02', '本期履约收款冲抵本期已履约服务 S-CUR-01 的收款，与本期收入确认分别对应', True),
 ('B03', '本期收入和对应收款分别按履约确认和债权形成追踪。', True),
 ('B04', '本期履约收款冲抵本期已履约服务的收款。', True),
 ('B05', '本期收款冲抵对应服务的收款。', True),
 ('B06', '旧应收回款不确认新收入；本期履约收入与其对应收款分别按履约确认与债权形成追踪。', True),
 ('B07', '“本期履约收入与其对应收款分别按履约确认与债权形成追踪”这一表述正确。', True),
 ('B08', '已经核对来源；本期履约收款冲抵本期已履约服务 S-CUR-01 的收款，与本期收入确认分别对应。', True),
 ('E01', '收款本身形成新增应收。', False),
 ('E02', '客户付款直接增加应收账款。', False),
 ('E03', '收入依履约确认，但收款本身形成新的应收。', False),
 ('E04', '旧债权没有新增收入；收款因此形成新增应收。', False),
 ('P01', '收入按履约假设确认；已确认的赊销形成债权；对应收款清偿已识别债权。', False),
 ('P02', '收入与收款分别按履约确认和已识别债权清偿说明。', False),
 ('P03', '收款按对应债权形成时的合同信息追踪来源。', False),
 ('P04', '追踪收款对应的债权形成来源，不将收款本身视为形成债权。', False),
 ('P05', '本期收入按履约确认；本期收款按债权来源追踪，并核对其清偿的已识别债权。', False),
 ('P06', '赊销形成应收，之后收款冲抵该应收。', False),
 ('P07', '已履约现金销售按履约假设确认当期收入并收现；不能仅为解释现金流而假定先形成期初应收。', False),
 ('P08', '未履约的预收款依已确认政策作为合同负债；本句不把收款本身作为履约证据。', False),
 ('P09', '收款冲抵本期服务形成的应收款。', False),
 ('P10', '收款冲抵对应的应收账款。', False),
 ('P11', '已收款服务与未收款服务分别追踪；未收款赊销形成债权。', False),
 ('P12', '收入与收款分别按履约确认与债权形成时的来源记录追踪。', False),
 ('P13', '不能写成“本期履约收入与其对应收款分别按履约确认与债权形成追踪”。', False),
 ('P14', '“本期履约收入与其对应收款分别按履约确认与债权形成追踪”的说法并不成立。', False),
 ('P15', '“本期履约收款冲抵本期已履约服务 S-CUR-01 的收款，与本期收入确认分别对应”并不正确。', False),
 ('P16', '是否可以说“本期履约收入与其对应收款分别按履约确认与债权形成追踪”？', False),
 ('P17', '若出现“本期履约收款冲抵本期已履约服务 S-CUR-01 的收款，与本期收入确认分别对应”，应改成清偿对应的已识别债权。', False),
 ('P18', '不要将收款写成冲抵收款，应按来源核对被清偿的债权。', False),
 ('P19', '该收款追溯至先前赊销形成的债权；回款后该债权已结清。', False),
 ('P20', '本期服务按履约假设确认收入；来源未说明现金履约与赊销的先后分解，不从汇总数补写。', False),
 ('P21', '收款并不形成新增应收，新增债权来自符合确认条件的赊销。', False),
 ('P22', '收入及对应收款须分别核对；追踪债权形成来源属于证据归属，并非说收款创造债权。', False),
 ('P23', '原文“本期履约收入与其对应收款分别按履约确认与债权形成追踪”有歧义，改为履约确认收入、收款清偿已识别债权。', False),
 ('P24', '收款形成新增应收的说法并不正确。', False),
 ('old_target_pairing', '本期履约收入与其对应收款分别按履约确认与债权形成追踪。', True),
 ('old_original_object', '本期履约收款冲抵本期已履约服务 S-CUR-01 的收款，与本期收入确认分别对应。', True),
 ('parallel_income_receipt', '收入按履约条件确认，收款按对应债权清偿追踪。', False),
 ('prior_credit_origin', '收款追溯至收入确认时形成的债权，收款本身属于清偿。', False),
 ('source_lineage', '按债权形成记录追踪收款来源。', False),
 ('received_by_origin', '本期收款对应此前履约形成的应收账款。', False),
 ('clear_parallel_pair', '收入与收款分别按履约确认与债权清偿追踪。', False),
 ('clear_settlement', '本期履约收款冲抵本期已识别的应收账款。', False),
 ('correct_reporting', '“收款冲抵收款”的表述不清，应写明所清偿的债权。', False),
 ('question', '这里的收款冲抵收款，具体核销对象是什么？', False),
 ('denial', '不能把本期收款描述为新增应收的形成原因。', False),
 ('cross_sentence', '已追踪债权形成记录。本期收款清偿同一债权。', False),
 ('contradiction', '收款本身形成新增应收账款。', False),
 ('negated_contradiction', '收款本身形成新增应收账款这一说法不成立。', False),
 ('mixed_correct_then_incorrect', '收款清偿既有债权；但收款本身形成新增应收账款。', False),
 ('source_labels_not_accounting_actions', '系统将两笔待匹配记录都命名为“收款”，应先核对其业务身份。', False),
 ('different_clearing_object', '收款冲抵收款方确认的应收账款。', False),
 ('correct_formation_and_settlement', '本期履约确认收入并形成债权；收款清偿相应债权。', False)]


def wording(body, regions=None):
    return [issue for issue in _readability_suggestions(body, regions or [])["issues"] if issue["code"] in CODES]


@pytest.mark.parametrize("case_id,body,expected", CASES, ids=[c[0] for c in CASES])
def test_independent_wording_controls(case_id, body, expected):
    issues = wording(body)
    assert bool(issues) is expected, (case_id, issues)
    for issue in issues:
        assert issue["severity"] == "suggestion"
        assert body[issue["position"]:issue["position"] + len(issue["text"])] == issue["text"]


@pytest.mark.parametrize("wrapper", ["{}", "- {}", "> {}", "## {}", "| 处理 | {} |"])
@pytest.mark.parametrize("phrase", [PAIR, OBJECT])
def test_assertion_layout_does_not_hide_wording_advice(wrapper, phrase):
    assert len(wording(wrapper.format(phrase))) == 1


@pytest.mark.parametrize("body", [f"```text\n{PAIR}\n```", f"~~~\n{OBJECT}\n~~~", f"示例：`{PAIR}`"])
def test_code_examples_are_outside_wording_scan(body):
    assert not wording(body)


def test_trusted_appendix_only_exempts_its_exact_range():
    body = PAIR + "\n" + OBJECT
    issues = wording(body, [{"start": 0, "end": len(PAIR), "section": "generated_appendix"}])
    assert [i["code"] for i in issues] == ["receipt_offset_object_ambiguous"]


def render_saved(saved):
    result = subprocess.run(["node", "--input-type=module", "-e", """
      import fs from 'node:fs';
      import {definitions} from './dsh-plugin/analysis.js';
      const tool = definitions().find(t => t.name === 'save_explanation_draft');
      const out = tool.output.render({}, {stdout:fs.readFileSync(0,'utf8')});
      if(out.length !== 1 || out[0].type !== 'text') throw Error('unexpected render');
      process.stdout.write(out[0].text);
    """], cwd=ROOT, input=json.dumps(saved), text=True, capture_output=True, check=True)
    packet = json.loads(result.stdout)
    return restore_table(packet) if "_model_projection" in packet else restore(packet, packet)


@pytest.mark.parametrize("short", [False, True])
@pytest.mark.parametrize("note", [PAIR, OBJECT, CLEAR])
def test_real_prepare_save_keeps_nonblocking_advice_in_public_result(statement, short, note):
    service, _, _, _, run, prepared = statement
    before_run = deepcopy(run)
    spec = ({**prepared["save_template_spec"], "qualitative_note": note} if short else
            {**prepared["draft_template"], "body": prepared["draft_template"]["body"] + "\n\n" + note})
    saved = service.save_explanation_draft(spec)
    path = service.analysis._object_path("drafts", saved["id"])
    before = path.read_bytes()
    assert note in saved["body"] and note in saved["body_template"]
    assert saved["quality"]["status"] == "pass", saved["quality"]["issues"]
    assert not saved["quality"]["issues"]
    assert saved["quality"]["claim_semantics_version"] == CLAIM_SEMANTICS_VERSION
    assert saved["completion"]["status"] == "complete"
    expected = note != CLEAR
    issues = [i for i in saved["quality"]["readability"]["issues"] if i["code"] in CODES]
    assert bool(issues) is expected
    checked = service.validate_explanation({"draft_id": saved["id"]})
    assert checked["status"] == "pass"
    assert checked["readability"] == saved["quality"]["readability"]
    public = render_saved(saved)
    assert public["quality"]["readability"] == saved["quality"]["readability"]
    assert public["explanation_check"]["readability"] == saved["quality"]["readability"]
    assert public["completion"]["status"] == "complete"
    assert public["final_response"] == saved["final_response"]
    if expected:
        fixed = service.save_explanation_draft({**prepared["save_template_spec"], "parent_id": saved["id"],
                                               "qualitative_note": CLEAR})
        assert fixed["id"] != saved["id"]
        assert fixed["completion"]["status"] == "complete"
        assert not wording(fixed["body"])
        assert fixed["claims"] == saved["claims"]
        assert fixed["run_ids"] == saved["run_ids"]
        assert fixed["requirements_id"] == saved["requirements_id"]
        assert fixed["quality"]["claim_semantics_version"] == saved["quality"]["claim_semantics_version"]
    assert path.read_bytes() == before
    assert run == before_run


@pytest.mark.parametrize("short", [False, True])
@pytest.mark.parametrize("note,code", [("收款本身形成新增应收。", "receipt_receivable_causation_mismatch"),
                                      ("期末现金余额为999999元。", "uncited_number")])
def test_wording_advice_does_not_override_existing_hard_errors(statement, short, note, code):
    service, _, _, _, _, prepared = statement
    note = PAIR + "；" + note
    spec = ({**prepared["save_template_spec"], "qualitative_note": note} if short else
            {**prepared["draft_template"], "body": prepared["draft_template"]["body"] + "\n" + note})
    bad = service.save_explanation_draft(spec)
    assert bad["quality"]["status"] == "needs_attention"
    assert code in {i["code"] for i in bad["quality"]["issues"]}
    assert bad["completion"]["status"] != "complete"
    path = service.analysis._object_path("drafts", bad["id"])
    old = path.read_bytes()
    fixed = service.save_explanation_draft({**prepared["save_template_spec"], "parent_id": bad["id"],
                                           "qualitative_note": CLEAR})
    assert fixed["completion"]["status"] == "complete"
    assert path.read_bytes() == old


def test_prepared_guidance_separates_recognition_settlement_and_source(statement):
    *_, prepared = statement
    rules = "".join(prepared["writing_guidance"]["rules"])
    assert "收入按履约" in rules
    assert "清偿对象" in rules and "来源追踪" in rules
    assert "不能假定所有收款" in rules
    assert "履约确认与债权形成分别说明" not in rules
    assert "readability" in rules and "建议不改变财务通过" in rules


@pytest.mark.parametrize("name", ["method/accounting-basis.md", "method/financial-statements/SKILL.md",
                                  "dsh-plugin/finance-tools.js"])
def test_wording_guidance_and_packaged_mirror_match(name):
    assert (ROOT / name).read_bytes() == (ROOT / "foundry/resources" / name).read_bytes()


LOCAL_DENIAL_CASES = [('X01', '并非本期履约收入与其对应收款分别按履约确认与债权形成追踪。', False),
 ('X02', '并非本期履约收款冲抵本期已履约服务 S-CUR-01 的收款，与本期收入确认分别对应。', False),
 ('X03', '“本期履约收入与其对应收款分别按履约确认与债权形成追踪”并非正确。', False),
 ('X04', '“本期履约收款冲抵本期已履约服务 S-CUR-01 的收款，与本期收入确认分别对应”并非正确。', False),
 ('X05', '本期履约收入与其对应收款分别按履约确认与债权形成追踪，这一说法不正确。', False),
 ('X06', '本期履约收款冲抵本期已履约服务 S-CUR-01 的收款，与本期收入确认分别对应，这一说法不正确。', False),
 ('quoted_inaccurate', '“收入与收款分别按履约确认与债权形成追踪”是不准确的说法，应区分收入确认与债权清偿。', False),
 ('quoted_comma_correction', '“收款冲抵对应服务的收款”，这一表述不清，应写明对应债权。', False),
 ('prefix_rejected', '不是“收入与收款分别按履约确认与债权形成追踪”，而是收入按履约确认、收款清偿既有债权。', False)]


@pytest.mark.parametrize("case_id,body,expected", LOCAL_DENIAL_CASES, ids=[c[0] for c in LOCAL_DENIAL_CASES])
def test_independent_local_denial_regressions(case_id, body, expected):
    assert bool(wording(body)) is expected, case_id


@pytest.mark.parametrize("phrase", [PAIR, OBJECT])
@pytest.mark.parametrize("body", [
    "不是旧应收，但{phrase}。",
    "并非旧应收；{phrase}。",
    "并非旧应收而是{phrase}。",
    "“{phrase}”这一说法正确。",
    "{phrase}；这一说法不正确。",
    "{phrase}，另一说法不正确。",
])
def test_local_denial_does_not_exempt_a_separate_assertion(phrase, body):
    assert len(wording(body.format(phrase=phrase))) == 1


@pytest.mark.parametrize("short", [False, True])
def test_real_save_preserves_locally_denied_wording_without_advice(statement, short):
    service, _, _, _, _, prepared = statement
    note = "\n".join(body for _, body, _ in LOCAL_DENIAL_CASES)
    spec = ({**prepared["save_template_spec"], "qualitative_note": note} if short else
            {**prepared["draft_template"], "body": prepared["draft_template"]["body"] + "\n\n" + note})
    saved = service.save_explanation_draft(spec)
    assert note in saved["body"] and note in saved["body_template"]
    assert saved["quality"]["status"] == "pass", saved["quality"]["issues"]
    assert saved["completion"]["status"] == "complete"
    assert not any(i["code"] in CODES for i in saved["quality"]["readability"]["issues"])
    public = render_saved(saved)
    assert public["quality"]["readability"] == saved["quality"]["readability"]
    assert public["explanation_check"]["readability"] == saved["quality"]["readability"]


def test_prepare_does_not_turn_collection_into_full_settlement(statement):
    *_, prepared = statement
    guidance = "".join(prepared["writing_guidance"]["rules"])
    template = prepared["draft_template"]["body"]
    for text in (guidance, template):
        assert "足额" in text and "同一债权" in text
        assert "部分清偿" in text and "未结清" in text
    # Receipts may cover multiple transactions; even aggregate cash exceeding
    # opening AR is not evidence that a particular receivable is fully paid.
    assert "归属" in guidance


def test_causation_repair_guidance_preserves_partial_settlement(statement):
    from foundry.finance_claim_semantics import check_claim_semantics
    _, _, _, _, run, _ = statement
    issues = check_claim_semantics("收款本身形成新增应收。", [], runs=[run])
    assert [i["code"] for i in issues] == ["receipt_receivable_causation_mismatch"]
    message = issues[0]["message"]
    assert "收款用于结清" not in message
    assert "足额" in message and "同一债权" in message and "部分清偿" in message


@pytest.mark.parametrize("short", [False, True])
@pytest.mark.parametrize("note", [
    "对已识别期初债权的本期收款只是部分清偿，剩余债权仍未结清；该清偿不确认新收入。",
    "来源明确同一债权已获足额清偿且余额为零，该债权已结清。",
    "来源只有收款汇总，缺少逐债权归属，不能据此判断某项债权结清。",
    "新增服务在同月已履约并足额收现；未假定先形成赊销应收。",
])
def test_save_preserves_partial_full_unknown_and_fulfilled_cash_boundaries(statement, short, note):
    service, _, _, _, _, prepared = statement
    spec = ({**prepared["save_template_spec"], "qualitative_note": note} if short else
            {**prepared["draft_template"], "body": prepared["draft_template"]["body"] + "\n\n" + note})
    saved = service.save_explanation_draft(spec)
    assert note in saved["body"] and note in saved["body_template"]
    assert saved["quality"]["status"] == "pass", saved["quality"]["issues"]
    assert saved["completion"]["status"] == "complete"
    assert not any(i["code"] in CODES for i in saved["quality"]["readability"]["issues"])
    assert saved["quality"]["claim_semantics_version"] == CLAIM_SEMANTICS_VERSION
    # This verifies preservation and the existing gate, not the truth of an
    # allocation assertion. Source-bound settlement review remains separate.
    public = render_saved(saved)
    # The registered compact view omits supporting facts and evidence tables;
    # the actual verdict and diagnostics must remain exact.
    for key in ("status", "issues", "readability", "claim_semantics_version"):
        assert public["quality"][key] == saved["quality"][key]
    assert public["completion"]["status"] == "complete"
