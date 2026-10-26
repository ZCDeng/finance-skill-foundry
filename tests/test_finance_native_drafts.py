"""Native draft aids reduce transcription without changing finance acceptance."""
from copy import deepcopy
import hashlib
import json

import pytest

from foundry.finance_explanations import FACT_TOKEN
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


SCOPE = {"ledger": "L", "organization": "O", "currency": "CNY", "unit": "元"}


def native_case(tmp_path, *, method="quantity_then_price", dimensions=None, drilldown=False,
                aging=False, numeric_buckets=False, extra_item=False, context_scope=None,
                legacy_numeric_unbounded=False):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="Native draft evidence"))
    scope = dict(SCOPE if context_scope is None else context_scope)
    if aging:
        rows = [{**scope, "id": key, "issue_date": "2026-08-01", "due_date": due, "amount": amount}
                for key, due, amount in [("a", "2026-08-31", "40"), ("b", "2026-08-30", "60")]]
    elif method == "volume_mix_price":
        rows = [{**scope, "product": p, "scenario": s, "quantity": q, "price": v, "quantity_unit": "件"}
                for p, s, q, v in [("A", "budget", "50", "10"), ("B", "budget", "50", "20"),
                                    ("A", "actual", "72", "12"), ("B", "actual", "48", "18")]]
    else:
        pairs = [("budget", "12", "10"), ("actual", "15", "9")] if method == "base_weights_with_interaction" else [
            ("budget", "16", "10"), ("actual", "10", "11")]
        rows = [{**scope, "product": "商品", "scenario": s, "quantity": q, "price": p}
                for s, q, p in pairs]
    source = tmp_path / "native.json"
    source.write_text(json.dumps(rows), encoding="utf-8")
    dataset = service.analysis.add_dataset(source, name="native input")
    alias = "invoices" if aging else "source"
    context = service.save_context({"bindings": {alias: dataset["id"]}, "scopes": {alias: scope}})
    dimensions = dimensions if dimensions is not None else ({"bucket": "late"} if aging else {"method": method})
    items = [{"id": "native", "metric": "open_amount" if aging else "price_quantity",
              "dimensions": dimensions, "requires_drilldown": drilldown}]
    if extra_item:
        items.append({"id": "other-obligation", "metric": "unanswered_amount", "requires_drilldown": False})
    requirements = service.analysis_requirements_save({"context_id": context["id"], "question": "保留完整原要求",
        "items": items})
    if aging:
        buckets = [{"name": "0-30天" if numeric_buckets else "recent", "min": 0, "max": 30},
                   {"name": "31-60天" if numeric_buckets else "late", "min": 31,
                    "max": 60 if numeric_buckets and not legacy_numeric_unbounded else None}]
        scenario = service.save_scenario({"context_id": context["id"], "kind": "receivables_aging", "inputs": {
            "as_of": "2026-09-30", "scope": scope, "buckets": buckets}})
        run = service.run_scenario({"scenario_id": scenario["id"]})
    else:
        run = service.explain_variance({"context_id": context["id"], "kind": "price_quantity", "method": method,
            "actual_scenario": "actual", "baseline_scenario": "budget"})
    assert run["execution_status"] == "succeeded", run.get("error")
    prepared = service.prepare_explanation({"run_ids": [run["id"]], "fact_view": "inspection"})
    return service, context, requirements, run, prepared


def native_result(case, *, allowed=None, run=None, prepared=None):
    from foundry.finance_native_drafts import prepare_native_draft
    service, _, _, saved_run, saved_prepared = case
    return prepare_native_draft(service.analysis, [saved_run if run is None else run],
                                saved_prepared if prepared is None else prepared, allowed=allowed)


@pytest.mark.parametrize("method,values", [
    ("quantity_then_price", {"quantity_contribution": "-60", "price_contribution": "10", "interaction": "0", "residual": "0"}),
    ("base_weights_with_interaction", {"quantity_contribution": "30", "price_contribution": "-12", "interaction": "-3", "residual": "0"}),
    ("volume_mix_price", {"volume_contribution": "300", "mix_contribution": "-120", "price_contribution": "48", "residual": "0"}),
])
def test_native_bridge_template_uses_exact_current_outputs_and_existing_save_checks(tmp_path, method, values):
    case = native_case(tmp_path, method=method)
    service, _, requirements, run, prepared = case
    result = native_result(case)
    template = result["draft_template"]
    assert template is not None, result
    assert template["requirements_id"] == requirements["id"]
    assert template["run_ids"] == [run["id"]]
    assert template["claims"] == [] and template["fact_ids"] == []
    tokens = FACT_TOKEN.findall(template["body"])
    selected = [fact for fact in prepared["facts"] if fact["id"] in tokens]
    assert len(tokens) == len(set(tokens)) == len(selected) == 7
    assert {f["column"]: f["value"] for f in selected if f["column"] in values} == values
    assert all(f["evidence_eligibility"]["counts_as_amount_evidence"] for f in selected)
    assert len(template["body"]) < 1600
    assert "算术贡献不证明业务因果" in template["body"]
    draft = service.save_explanation_draft(template)
    assert draft["quality"]["status"] == "pass", draft["quality"]["issues"]
    assert draft["completion"]["status"] == "complete", draft["completion"]
    assert len(draft["claims"]) == 7


def test_aging_template_preserves_cutoff_and_does_not_invent_source_period(tmp_path):
    case = native_case(tmp_path, aging=True)
    service, _, _, run, _ = case
    result = native_result(case)
    assert result["draft_template"] is not None, result
    body = result["draft_template"]["body"]
    assert "边界及发票明细见附录" in body
    assert all("period" not in row for row in run["result"]["rows"])
    draft = service.save_explanation_draft(result["draft_template"])
    assert draft["quality"]["status"] == "pass", draft["quality"]["issues"]
    assert draft["completion"]["status"] == "complete", draft["completion"]
    assert "2026-09-30" in draft["body"] and "late" in draft["body"]


def test_numeric_aging_boundaries_are_explicitly_unsupported_without_legal_citations(tmp_path):
    case = native_case(tmp_path, aging=True, numeric_buckets=True, dimensions={"bucket": "31-60天"})
    before = deepcopy(case[2])
    unproved = deepcopy(case[4])
    unproved.pop("aging_audit_metadata", None)
    result = native_result(case, prepared=unproved)
    assert result["draft_template"] is None
    assert any(d["code"] == "native_aging_boundary_citation_unsupported" for d in result["diagnostics"])
    assert case[0].analysis._get("requirements", before["id"]) == before
    assert case[0].analysis._list("drafts") == []


@pytest.mark.parametrize("mutation", ["ineligible", "missing_fact", "duplicate_fact", "value", "token", "identity", "closure"])
def test_prepared_metadata_cannot_qualify_or_relabel_the_source(tmp_path, mutation):
    case = native_case(tmp_path)
    changed = deepcopy(case[4])
    fact = next(f for f in changed["facts"] if f["column"] == "interaction")
    if mutation == "ineligible":
        fact["evidence_eligibility"]["counts_as_amount_evidence"] = False
    elif mutation == "missing_fact":
        changed["facts"].remove(fact)
    elif mutation == "duplicate_fact":
        changed["facts"].append(deepcopy(fact))
    elif mutation == "value":
        fact["value"] = "123"
    elif mutation == "token":
        fact["reference_template"]["body_token"] = "0"
    elif mutation == "identity":
        fact["metric_identity"]["currency"] = "USD"
    else:
        next(g for g in changed["evidence_groups"] if g["group_type"] == "price_quantity_bridge")["closure"]["status"] = "failed"
    before = deepcopy(changed)
    result = native_result(case, prepared=changed)
    assert result["draft_template"] is None, result
    assert changed == before


@pytest.mark.parametrize("mutation", ["result", "bindings", "fingerprint", "failed", "foreign_task"])
def test_run_argument_cannot_replace_current_persisted_identity(tmp_path, mutation):
    case = native_case(tmp_path)
    run = deepcopy(case[3])
    if mutation == "result":
        run["result"]["rows"][0]["interaction"] = "1"
    elif mutation == "bindings":
        run["bindings"] = {}
    elif mutation == "fingerprint":
        run["requirements_semantic_fingerprint"] = "wrong"
    elif mutation == "failed":
        run["execution_status"] = "failed"
    else:
        run["task_id"] = "other-task"
    assert native_result(case, run=run)["draft_template"] is None


def test_authorization_and_requirement_versions_remain_mandatory(tmp_path):
    case = native_case(tmp_path)
    assert native_result(case, allowed=set())["draft_template"] is None
    service, context, requirement, _, _ = case
    service.analysis_requirements_save({"context_id": context["id"], "parent_id": requirement["id"],
        "question": "新的原问题", "items": requirement["items"]})
    assert native_result(case)["draft_template"] is None


def test_unanswered_original_obligation_cannot_be_completed_by_a_template(tmp_path):
    result = native_result(native_case(tmp_path, extra_item=True))
    assert result["draft_template"] is None
    assert any(d["code"] == "native_requirements_pending" for d in result["diagnostics"])


def test_requested_downstream_source_checks_are_not_erased(tmp_path):
    case = native_case(tmp_path, drilldown=True)
    assert native_result(case)["draft_template"] is None
    service, _, _, run, prepared = case
    for fact in prepared["facts"]:
        if fact["column"] in {"total_variance", "quantity_contribution", "price_contribution", "interaction"}:
            service.drilldown_fact({"run_id": run["id"], "row": fact["row"], "column": fact["column"]})
    assert native_result(case)["draft_template"] is not None


def test_edited_native_template_remains_subject_to_uncited_number_gate(tmp_path):
    case = native_case(tmp_path)
    result = native_result(case)
    template = deepcopy(result["draft_template"])
    template["body"] += "\n未核验金额 999999 元。"
    draft = case[0].save_explanation_draft(template)
    assert draft["completion"]["status"] != "complete"
    assert any(i["code"] == "uncited_number" for i in draft["quality"]["issues"])


def test_non_native_or_multiple_runs_do_not_offer_partial_templates(tmp_path):
    from foundry.finance_native_drafts import prepare_native_draft
    case = native_case(tmp_path)
    service, _, _, run, prepared = case
    assert prepare_native_draft(service.analysis, [run, run], prepared)["draft_template"] is None
    assert prepare_native_draft(service.analysis, [], prepared)["draft_template"] is None


def test_numeric_aging_boundaries_are_complete_in_source_bound_v4_appendix(tmp_path):
    case = native_case(tmp_path, aging=True, numeric_buckets=True, dimensions={"bucket": "31-60天"})
    service, _, _, run, prepared = case
    assert prepared["save_template_spec"]["use_prepared_template"] is True
    draft = service.save_explanation_draft(prepared["save_template_spec"])
    assert draft["quality"]["status"] == "pass", draft["quality"]["issues"]
    assert draft["completion"]["status"] == "complete", draft["completion"]
    assert draft["evidence_appendix_meta"]["render_version"] == 4
    assert "边界及发票明细见附录" in draft["body"]
    appendix = draft["evidence_appendix"]
    assert "| 0-30天 | 0 | 30 |" in appendix
    assert "| 31-60天 | 31 | 60 |" in appendix
    assert "| a | 2026-08-31 | 30 | 0-30天 | 40 | CNY | 元 |" in appendix
    assert "| b | 2026-08-30 | 31 | 31-60天 | 60 | CNY | 元 |" in appendix
    assert "非金额元数据" in appendix and "不替代可引用汇总事实" in appendix
    assert len(draft["claims"]) == len(run["result"]["rows"])
    assert all(c["column"] == "open_amount" for c in draft["claims"])
    assert service.validate_explanation({"draft_id": draft["id"]})["status"] == "pass"


@pytest.mark.parametrize("mutation", ["dict", "bucket", "detail", "authority", "amount_eligibility"])
def test_untrusted_or_edited_aging_proof_never_generates_trusted_appendix(tmp_path, mutation):
    from foundry.finance_explanations import render_evidence_appendix
    case = native_case(tmp_path, aging=True, numeric_buckets=True, dimensions={"bucket": "31-60天"})
    changed = deepcopy(case[4])
    proof = changed["aging_audit_metadata"]
    if mutation == "dict":
        changed["aging_audit_metadata"] = json.loads(json.dumps(proof))
    elif mutation == "bucket":
        proof["buckets"][0]["max"] = 31
    elif mutation == "detail":
        proof["detail_rows"][0]["overdue_days"] = 999
    elif mutation == "authority":
        proof["authority"] = "manager_approved"
    else:
        proof["counts_as_amount_evidence"] = True
    appendix = render_evidence_appendix(changed)
    assert appendix["schema_version"] == 3
    assert "账龄边界与逐发票审计明细" not in appendix["body"]
    assert native_result(case, prepared=changed)["draft_template"] is None


@pytest.mark.parametrize("mutation", ["body", "version", "hash"])
def test_v4_saved_proof_and_render_metadata_tampering_is_not_trusted(tmp_path, mutation):
    from foundry.finance_explanations import _trusted_generated_appendix_regions, evidence_appendix_metadata
    case = native_case(tmp_path, aging=True, numeric_buckets=True, dimensions={"bucket": "31-60天"})
    service, _, _, _, prepared = case
    draft = service.save_explanation_draft(prepared["save_template_spec"])
    assert len(_trusted_generated_appendix_regions(service.analysis, draft["body"], draft, prepared)) == 1
    forged = deepcopy(draft)
    if mutation == "body":
        forged["evidence_appendix"] = forged["evidence_appendix"].replace("2026-08-31 | 30", "2026-08-31 | 31")
        forged["body"] = forged["body"].replace("2026-08-31 | 30", "2026-08-31 | 31")
        forged["evidence_appendix_meta"] = evidence_appendix_metadata(forged["evidence_appendix"], render_version=4)
    elif mutation == "version":
        forged["evidence_appendix_meta"]["render_version"] = 3
    else:
        forged["evidence_appendix_meta"]["base_body_sha256"] = "0" * 64
    assert _trusted_generated_appendix_regions(service.analysis, forged["body"], forged, prepared) == []


def test_existing_v3_aging_appendix_bytes_and_saved_rebuild_remain_unchanged(tmp_path, monkeypatch):
    import foundry.finance_service as service_module
    from foundry.finance_explanations import _render_evidence_appendix, _trusted_generated_appendix_regions
    case = native_case(tmp_path, aging=True, numeric_buckets=True, dimensions={"bucket": "31-60天"},
                       legacy_numeric_unbounded=True)
    service, _, _, run, prepared = case
    legacy = _render_evidence_appendix(prepared, render_version=3)
    assert "账龄边界与逐发票审计明细" not in legacy["body"]
    assert hashlib.sha256(legacy["body"].encode()).hexdigest() == "b7f4855699f3db0e4744e4c215852b3d6b24a3f2f46d32664035e682defd1699"
    with monkeypatch.context() as old_renderer:
        old_renderer.setattr(service_module, "render_evidence_appendix",
                             lambda p: _render_evidence_appendix(p, render_version=3))
        draft = service.save_explanation_draft({"run_ids": [run["id"]],
            "requirements_id": case[2]["id"], "body": "保留旧附录以核验历史重建。"})
    assert draft["evidence_appendix_meta"]["render_version"] == 3
    assert len(_trusted_generated_appendix_regions(service.analysis, draft["body"], draft, prepared)) == 1


def test_short_native_save_reprepares_and_does_not_allow_uncited_note_or_stale_requirement(tmp_path):
    from foundry.errors import FoundryError
    case = native_case(tmp_path)
    service, context, requirement, _, prepared = case
    spec = prepared["save_template_spec"]
    draft = service.save_explanation_draft({**spec, "qualitative_note": "未引用金额999999元。"})
    assert draft["completion"]["status"] != "complete"
    assert any(issue["code"] == "uncited_number" for issue in draft["quality"]["issues"])
    service.analysis_requirements_save({"parent_id": requirement["id"], "context_id": context["id"],
        "question": "新的需求版本", "items": requirement["items"]})
    with pytest.raises(FoundryError, match="prepared template"):
        service.save_explanation_draft(spec)


@pytest.mark.parametrize("mutation", ["scope", "snapshot", "invalid_buckets", "session"])
def test_aging_proof_resolver_rejects_old_scope_snapshot_invalid_buckets_and_other_session(tmp_path, mutation):
    from foundry.finance_native_drafts import prepare_aging_audit_metadata
    from foundry.analysis import _hash
    case = native_case(tmp_path, aging=True, numeric_buckets=True, dimensions={"bucket": "31-60天"})
    service, context, requirements, run, prepared = case
    allowed = None
    if mutation == "session":
        allowed = set()
    elif mutation == "snapshot":
        source = tmp_path / "native.json"
        source.write_text(source.read_text().replace('"40"', '"41"'))
        service.analysis.add_dataset(source, name="native input")
    elif mutation == "scope":
        service.analysis_requirements_save({"parent_id": requirements["id"], "context_id": context["id"],
            "question": requirements["question"], "scope": {**requirements["scope"], "currency": "USD"},
            "items": requirements["items"]})
    else:
        from foundry.errors import FoundryError
        scenario = service._read("scenarios", run["result"]["scenario_id"])
        scenario["inputs"]["buckets"][1]["min"] = 30
        with pytest.raises(FoundryError):
            service.save_scenario({"context_id": context["id"], "kind": "receivables_aging",
                                   "inputs": scenario["inputs"]})
        scenario["input_hash"] = _hash(scenario["inputs"])
        # An external file edit must also fail immutable-source verification.
        service._path("scenarios", scenario["id"]).write_text(json.dumps(scenario))
    assert prepare_aging_audit_metadata(service.analysis, [run], allowed=allowed) is None


def test_default_aging_buckets_rebuild_exact_native_boundaries(tmp_path):
    case = native_case(tmp_path, aging=True)
    service, context, requirements, _, _ = case
    revised = service.analysis_requirements_save({"parent_id": requirements["id"],
        "context_id": context["id"], "question": requirements["question"],
        "items": [{"id": "native", "metric": "open_amount", "dimensions": {"bucket": "31-60"},
                   "requires_drilldown": False}]})
    scenario = service.save_scenario({"context_id": context["id"], "kind": "receivables_aging",
                                     "inputs": {"as_of": "2026-09-30", "scope": SCOPE}})
    run = service.run_scenario({"scenario_id": scenario["id"]})
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    assert prepared["save_template_spec"]["requirements_id"] == revised["id"]
    draft = service.save_explanation_draft(prepared["save_template_spec"])
    assert draft["quality"]["status"] == "pass", draft["quality"]["issues"]
    assert draft["completion"]["status"] == "complete"
    for text in ("| 0-30 | 0 | 30 |", "| 31-60 | 31 | 60 |", "| 61-90 | 61 | 90 |",
                 "| 90+ | 91 | 无上限 |", "| a | 2026-08-31 | 30 | 0-30 | 40 |",
                 "| b | 2026-08-30 | 31 | 31-60 | 60 |"):
        assert text in draft["evidence_appendix"]


def test_other_run_audit_proof_cannot_supply_a_native_draft(tmp_path):
    (tmp_path / "own").mkdir()
    own = native_case(tmp_path / "own", aging=True)
    (tmp_path / "other").mkdir()
    other = native_case(tmp_path / "other", aging=True)
    prepared = deepcopy(own[4])
    prepared["aging_audit_metadata"] = other[4]["aging_audit_metadata"]
    assert native_result(own, prepared=prepared)["draft_template"] is None
