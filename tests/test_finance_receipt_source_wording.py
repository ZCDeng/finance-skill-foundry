"""Optional forecast roles and receipt modifiers retain independent proof boundaries."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION
from foundry.finance_driver_templates import BOUNDARY_INPUTS, TEMPLATE_ID
from foundry.finance_explanations import _ar_wording_suggestions, _forecast_performance_sources
from foundry.finance_professional import BASE_FIELDS, STANDARD_FIELDS, TEMPLATE_METRICS
from test_finance_ar_wording import render_saved
from test_finance_professional_protocol import _profile_case


PUBLIC = Path(__file__).parent / "fixtures/finance_supplements/three_statement_v1/public"
E18 = "SUP-E18-01--management-closed"
OLD_AR = "SUP-E19-01--old-ar-collection"
CASH = "SUP-E19-02--fulfilled-cash-sale"
MODIFIER = "S-CUR-01 为对 2026-10 已履约服务的收款（形成未收余额）"
CLARIFIED = "S-CUR-01 的服务在本预测期已履约；该合同尚未收到的价款形成未收余额。"
ADVICE = "receipt_balance_modifier_ambiguous"


def source_case(tmp_path, case_id, mutate=None):
    """Register each original public case, never substitute another case's facts."""
    service, seed = _profile_case(tmp_path)
    directory = PUBLIC / case_id
    record = json.loads((directory / "transaction_allocation.json").read_text())
    scope = deepcopy(record["scope"])
    if mutate:
        mutate(record)
    bindings, source_bindings = {}, {}
    for alias, key in (("template_inputs", "input_name"), ("model_boundary", "boundary_name")):
        rows = json.loads((directory / f"{alias}.json").read_text())["rows"]
        path = tmp_path / f"{alias}.json"
        path.write_text(json.dumps(rows))
        bindings[alias] = service.analysis.add_dataset(path, name=alias)["id"]
        for row in rows:
            name = row[key] if alias == "template_inputs" else f"boundary.{row[key]}"
            source_bindings[name] = {
                "alias": alias, "column": "amount", "selector": {key: row[key]},
                "aggregation": "single", "period": row["period"],
                "scope": {"organization": row["organization"]},
                "unit": row["unit"], "currency": row["currency"],
            }
    allocation = tmp_path / "allocation.json"
    allocation.write_text(json.dumps([{
        "record_type": "transaction_allocation", "public_record_json": json.dumps(record),
    }]))
    bindings["transaction_allocation"] = service.analysis.add_dataset(
        allocation, name="source transaction allocations")["id"]
    context = service.save_context({
        "bindings": bindings, "scopes": {key: scope for key in bindings},
        "reporting_profile": {**seed["reporting_profile"], "entity_scope": scope["organization"]},
    })
    service.finance_profile_confirm({"context_id": context["id"], "confirmed_fields": sorted(BASE_FIELDS | STANDARD_FIELDS)})
    scenario = service.save_scenario({
        "context_id": context["id"], "kind": "driver_model", "label": "source-bound forecast",
        "inputs": {"template_id": TEMPLATE_ID, "period": "2026-10", "scope": scope,
                   "source_bindings": source_bindings},
    })
    service.finance_profile_confirm({
        "context_id": context["id"], "scenario_id": scenario["id"],
        "confirmed_model_boundaries": list(BOUNDARY_INPUTS),
    })
    requirement = service.analysis_requirements_save({
        "context_id": context["id"], "question": "管理预测三表与来源内履约状态",
        "items": [{"id": key, "metric": key, "requires_drilldown": False,
                   "dimensions": {"template_id": TEMPLATE_ID, "scenario_id": scenario["id"]}}
                  for key in sorted(TEMPLATE_METRICS)],
    })
    run = service.run_scenario({"scenario_id": scenario["id"]})
    assert run["execution_status"] == "succeeded"
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    return service, record, context, requirement, run, prepared


def save_note(service, prepared, note, short, *, parent_id=None):
    spec = ({**prepared["save_template_spec"], "qualitative_note": note} if short else
            {**prepared["draft_template"], "body": prepared["draft_template"]["body"] + "\n\n" + note})
    if parent_id:
        spec["parent_id"] = parent_id
    return service.save_explanation_draft(spec)


def record_observation(tmp_path, **observations):
    (tmp_path / "observed-public-result.json").write_text(
        json.dumps(observations, ensure_ascii=False, indent=2) + "\n")


@pytest.mark.parametrize("case_id,expected", [(E18, 1), (OLD_AR, 1), (CASH, 2)])
def test_original_public_cases_keep_own_performance_facts(tmp_path, case_id, expected):
    service, record, context, requirement, run, prepared = source_case(tmp_path, case_id)
    proof = prepared["forecast_performance"]
    record_observation(tmp_path, case_id=case_id, source_record=record,
                       run_id=run["id"], prepared=prepared)
    assert proof["status"] == "verified", proof
    assert len(proof["facts"]) == expected
    assert proof["counts_as_amount_evidence"] is False
    expected_contracts = {record[role]["contract_id"] for role in ("base_current_service", "additional_sale")
                          if isinstance(record[role], dict)}
    assert {fact["contract_id"] for fact in proof["facts"]} == expected_contracts
    for fact in proof["facts"]:
        assert fact["state"] == "performed" and fact["status"] == "verified"
        assert fact["period"] == "2026-10"
        assert fact["authority"] == "source_defined_forecast_assumption"
        assert fact["counts_as_amount_evidence"] is False
        assert fact["run_id"] == run["id"] and fact["output_hash"] == run["output_hash"]
        assert fact["context_id"] == context["id"] and fact["requirements_id"] == requirement["id"]
        source = service.analysis.read_dataset(fact["source"]["dataset_id"])
        assert fact["source"]["source_hash"] == source["source_hash"]
        assert fact["source"]["data_hash"] == source["data_hash"]
        assert fact["source"]["json_pointer"] == f"/{fact['role']}/performed_in_forecast"


@pytest.mark.parametrize("case_id", [E18, OLD_AR])
@pytest.mark.parametrize("short", [False, True], ids=["ordinary", "compact"])
def test_optional_null_does_not_disable_existing_same_contract_save_guard(tmp_path, case_id, short):
    service, record, _, _, run, prepared = source_case(tmp_path, case_id)
    note = "S-CUR-01 在本预测期仍待履约。"
    wrong = save_note(service, prepared, note, short)
    path = service.analysis._object_path("drafts", wrong["id"])
    previous = path.read_bytes()
    fixed = save_note(service, prepared, "S-CUR-01 在本预测期已履约。", short,
                      parent_id=wrong["id"])
    record_observation(tmp_path, case_id=case_id, source_record=record,
                       proof=prepared["forecast_performance"], wrong=wrong, fixed=fixed)
    assert note in wrong["body"] and path.read_bytes() == previous
    assert fixed["parent_id"] == wrong["id"] and fixed["completion"]["status"] == "complete"
    assert fixed["claims"] == wrong["claims"] and fixed["run_ids"] == [run["id"]]
    assert wrong["quality"]["claim_semantics_version"] == CLAIM_SEMANTICS_VERSION
    assert {issue["code"] for issue in wrong["quality"]["issues"]} == {"forecast_performance_status_mismatch"}
    assert wrong["completion"]["status"] != "complete"


@pytest.mark.parametrize("short", [False, True], ids=["ordinary", "compact"])
def test_exact_receipt_parenthetical_is_public_nonblocking_advice(tmp_path, short):
    service, record, _, _, run, prepared = source_case(tmp_path, CASH)
    original_run = deepcopy(run)
    saved = save_note(service, prepared, MODIFIER, short)
    path = service.analysis._object_path("drafts", saved["id"])
    previous = path.read_bytes()
    public = render_saved(saved)
    fixed = save_note(service, prepared, CLARIFIED, short, parent_id=saved["id"])
    record_observation(tmp_path, case_id=CASH, source_record=record, prepared=prepared,
                       saved=saved, public=public, fixed=fixed)
    assert MODIFIER in saved["body"] and MODIFIER in saved["body_template"]
    assert saved["quality"]["status"] == "pass" and saved["quality"]["issues"] == []
    assert saved["completion"]["status"] == "complete"
    assert saved["quality"]["claim_semantics_version"] == CLAIM_SEMANTICS_VERSION
    assert public["quality"]["readability"] == saved["quality"]["readability"]
    assert public["explanation_check"]["readability"] == saved["quality"]["readability"]
    assert public["completion"]["status"] == "complete"
    assert public["final_response"] == saved["final_response"]
    assert fixed["completion"]["status"] == "complete" and fixed["parent_id"] == saved["id"]
    assert fixed["claims"] == saved["claims"] and fixed["run_ids"] == saved["run_ids"]
    assert not any(issue["code"] == ADVICE for issue in fixed["quality"]["readability"]["issues"])
    assert path.read_bytes() == previous and service.analysis.get_run(run["id"]) == original_run
    issues = [issue for issue in saved["quality"]["readability"]["issues"] if issue["code"] == ADVICE]
    assert len(issues) == 1, saved["quality"]["readability"]
    assert issues[0]["severity"] == "suggestion"
    issue = issues[0]
    assert saved["body"][issue["position"]:issue["position"] + len(issue["text"])] == issue["text"]


@pytest.mark.parametrize("mutation", ["optional_absent", "base_absent", "base_null", "base_string",
                                      "optional_string", "optional_list", "optional_no_identity",
                                      "state_absent", "different_period", "different_scope", "other_schema"])
def test_optional_absence_is_not_a_general_null_or_unknown_exemption(tmp_path, mutation):
    def mutate(record):
        if mutation == "optional_absent":
            record.pop("additional_sale")
        elif mutation == "base_absent":
            record.pop("base_current_service")
        elif mutation == "base_null":
            record["base_current_service"] = None
        elif mutation == "base_string":
            record["base_current_service"] = "performed"
        elif mutation == "optional_string":
            record["additional_sale"] = "none"
        elif mutation == "optional_list":
            record["additional_sale"] = []
        elif mutation == "optional_no_identity":
            record["additional_sale"] = {"performed_in_forecast": True}
        elif mutation == "state_absent":
            record["base_current_service"].pop("performed_in_forecast")
        elif mutation == "different_period":
            record["base_current_service"]["performance_period"] = "2026-11"
        elif mutation == "different_scope":
            record["scope"]["organization"] = "unrelated organization"
        else:
            record["schema_version"] = "unregistered-envelope"

    _, _, _, _, _, prepared = source_case(tmp_path, E18, mutate)
    proof = prepared["forecast_performance"]
    if mutation == "optional_absent":
        assert proof["status"] == "verified" and len(proof["facts"]) == 1
        assert proof["facts"][0]["role"] == "base_current_service"
    else:
        assert proof["status"] == "unverifiable"
        assert not any(fact["status"] == "verified" for fact in proof["facts"])
    assert proof["counts_as_amount_evidence"] is False


@pytest.mark.parametrize("state", [None, "true", "false", 0, 1, "partial", False])
def test_optional_null_preserves_strict_state_types_without_amount_inference(tmp_path, state):
    def mutate(record):
        base = record["base_current_service"]
        base["performed_in_forecast"] = state
        base.pop("revenue")
        base.pop("receipts")

    _, _, _, _, _, prepared = source_case(tmp_path, E18, mutate)
    proof = prepared["forecast_performance"]
    assert len(proof["facts"]) == 1
    fact = proof["facts"][0]
    if state is False:
        assert fact["state"] == "pending" and fact["status"] == "verified"
    else:
        assert fact["state"] == "unknown" and fact["status"] == "unverifiable"
    assert fact["counts_as_amount_evidence"] is False


@pytest.mark.parametrize("mutation", ["allowed", "source_hash", "new_requirements", "superseded", "revoked"])
def test_optional_null_never_bypasses_current_source_authority(tmp_path, mutation):
    service, _, context, requirement, run, prepared = source_case(tmp_path, E18)
    assert prepared["forecast_performance"]["status"] == "verified"
    allowed = None
    if mutation == "allowed":
        allowed = set(context["bindings"].values()) - {context["bindings"]["transaction_allocation"]}
    elif mutation == "source_hash":
        path = service.analysis.root / "datasets" / context["bindings"]["transaction_allocation"] / "source.json"
        path.write_text(path.read_text() + " ")
    elif mutation == "new_requirements":
        service.analysis_requirements_save({
            "context_id": context["id"], "parent_id": requirement["id"],
            "question": "new obligation", "items": deepcopy(requirement["items"]),
        })
    elif mutation == "superseded":
        path = tmp_path / "replacement.json"
        path.write_text('[{"amount":"1"}]')
        service.analysis.add_dataset(path, name="source transaction allocations")
    else:
        service.finance_profile_revoke({"id": service._list("profile_confirmations")[-1]["id"],
                                        "reason": "review needed"})
    proof = _forecast_performance_sources(service.analysis, [run], allowed=allowed)
    assert proof == {"status": "unverifiable", "facts": [], "counts_as_amount_evidence": False}


@pytest.mark.parametrize("body", [
    "收款（形成未收余额）", "收款(形成未收余额)", "收款 （产生未收余额）",
    "收款（形成了未收款余额）", "本期收款（产生了未收余额）",
    "“收款（形成未收余额）”这一表述正确。",
    "并非所有合同都会赊销；收款（形成未收余额）。",
])
@pytest.mark.parametrize("wrapper", ["{}", "## {}", "- {}", "> {}", "| 项目 | {} |"])
def test_receipt_parenthetical_advice_has_local_span_in_all_prose_layouts(body, wrapper):
    body = wrapper.format(body)
    issues = [i for i in _ar_wording_suggestions(body, []) if i["code"] == ADVICE]
    assert len(issues) == 1
    issue = issues[0]
    assert issue["severity"] == "suggestion"
    assert body[issue["position"]:issue["position"] + len(issue["text"])] == issue["text"]


@pytest.mark.parametrize("body", [
    "未收价款形成未收余额。", "收款后仍有未收余额。", "收款（仍有未收余额）。",
    "收款（未形成未收余额）。", "收款（未收价款形成未收余额）。",
    "对已识别债权的收款冲减该应收余额。", "已履约现金销售收现，未形成应收。",
    "应收款（形成未收余额）。", "预收款（形成未收余额）。", "未收款（形成未收余额）。",
    "并非收款（形成未收余额）。", "不能写成“收款（形成未收余额）”。",
    "“收款（形成未收余额）”这一表述不清。", "“收款（形成未收余额）”并非正确。",
    "是否可以写成“收款（形成未收余额）”？", "若出现收款（形成未收余额）这一说法，应核实。",
    "收款（形成未收余额）这一说法不正确。", "收款；未收价款形成未收余额。",
    "收款（形成未收余额)", "收款(形成未收余额）",
    "```text\n收款（形成未收余额）\n```", "示例：`收款（形成未收余额）`",
])
def test_correct_or_unasserted_parenthetical_is_not_advised(body):
    assert not any(i["code"] == ADVICE for i in _ar_wording_suggestions(body, []))


def test_trusted_region_and_later_independent_assertion_remain_local():
    phrase = "收款（形成未收余额）"
    body = phrase + "\n“" + phrase + "”这一表述不清；但" + phrase + "。"
    issues = [i for i in _ar_wording_suggestions(body, [{"start": 0, "end": len(phrase)}])
              if i["code"] == ADVICE]
    assert len(issues) == 1 and issues[0]["position"] == body.rindex(phrase)


@pytest.mark.parametrize("short", [False, True], ids=["ordinary", "compact"])
@pytest.mark.parametrize("note,code", [("收款本身形成新增应收。", "receipt_receivable_causation_mismatch"),
                                      ("期末现金余额为999999元。", "uncited_number")])
def test_parenthetical_advice_does_not_clear_existing_hard_error(tmp_path, short, note, code):
    service, _, _, _, _, prepared = source_case(tmp_path, CASH)
    saved = save_note(service, prepared, MODIFIER + "；" + note, short)
    assert any(i["code"] == ADVICE for i in saved["quality"]["readability"]["issues"])
    assert code in {i["code"] for i in saved["quality"]["issues"]}
    assert saved["quality"]["status"] == "needs_attention"
    assert saved["completion"]["status"] != "complete"
