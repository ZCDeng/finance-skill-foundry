from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load("finance_professional_eval")
R = load("report_finance_professional_release")


def slot(repeat=1):
    return {"candidate": "candidate", "suite": "professional_development", "family": "E01", "case": "E01--base", "variant": "base", "repeat": repeat}


def attempt(repeat=1, index=1):
    return {"slot": slot(repeat), "attempt": index, "completed": True, "score": {"status": "passed"}, "evidence_sha256": "evidence"}


def lawful_state(result_rows, claims):
    from test_finance_evals import _semantic_requirement, _dataset_state, _bound_run
    run = {**_bound_run(run_id="r"), "result": {"rows": result_rows}}
    draft = {"id": "draft", "seq": 30, "requirements_id": "req2", "run_ids": ["r"], "claims": claims,
             "body": "A cited result.", "explanation_check": {"status": "pass", "requirements": {
                 "requirements_id": "req2", "coverage": {"status": "pass"}, "provenance": {"status": "pass"}}}}
    draft["content_hash"] = E.legacy._sha({k: draft.get(k) for k in ("title", "requirements_id", "materiality", "body", "body_template", "document", "run_ids", "fact_ids", "claims", "limitations")})
    state = {"requirements": [_semantic_requirement("req2", 10)], "datasets": [_dataset_state()], "runs": [run], "drafts": [draft],
             "completions": [{"draft_id": "draft", "status": "complete", "requirements_id": "req2", "draft_content_hash": draft["content_hash"]}]}
    return state, {"completed": True, "final_draft": draft}


def events():
    return [
        {"phase": "start", "seq": 1, "call_id": "read", "session_id": "s", "name": "method-resource", "arguments_sha256": "arg", "arguments": {"skill": "variance-analysis", "resource": "FOUNDRY.md"}},
        {"phase": "end", "seq": 2, "call_id": "read", "session_id": "s", "name": "method-resource", "arguments_sha256": "arg", "arguments": {"skill": "variance-analysis", "resource": "FOUNDRY.md"}, "content_sha256": "hash", "is_error": False},
        {"phase": "start", "seq": 3, "call_id": "calc", "session_id": "s", "name": "explain_variance", "arguments_sha256": "calcarg", "arguments": {}},
        {"phase": "end", "seq": 4, "call_id": "calc", "session_id": "s", "name": "explain_variance", "arguments_sha256": "calcarg", "arguments": {}, "is_error": False},
    ]


RESOURCES = [{"tool": "method-resource", "arguments": {"skill": "variance-analysis", "resource": "FOUNDRY.md"}, "sha256": "hash"}]


def test_public_projection_never_serializes_case_oracle_or_extra_metadata():
    case = {"id": "case", "question": "business task", "expected": {"secret": "ORACLE"}, "oracle": "ORACLE",
            "datasets": [{"name": "source", "metadata": {"currency": "CNY", "expected": "ORACLE"}, "rows": [{"amount": "1"}], "private": "ORACLE"}]}
    result = E.public_case(case)
    assert "ORACLE" not in json.dumps(result)
    assert result["datasets"][0]["rows"] == [{"amount": "1"}]


def test_public_professional_schema_rejects_oracle_instead_of_silently_keeping_it():
    p = ROOT / "tests/fixtures/finance_evals/professional/public/E01--base.json"
    public = json.loads(p.read_text())
    with pytest.raises(ValueError, match="nonpublic"):
        E.professional_public({**public, "expected": "secret"})
    public["context"]["oracle"] = "secret"
    with pytest.raises(ValueError, match="context"):
        E.professional_public(public)


def test_normalized_source_adapter_does_not_compute_variance_answers():
    case = json.loads((ROOT / "tests/fixtures/finance_evals/professional/public/E01--base.json").read_text())
    adapted, trace = E.adapt_public(case)
    basket = adapted["datasets"][1]["rows"]
    assert [(r["scenario"], r["quantity"], r["price"], r["amount"]) for r in basket] == [
        ("budget", "50.0", "10", "500.0"), ("budget", "50.0", "20", "1000.0"),
        ("actual", "72.0", "12", "864.0"), ("actual", "48.0", "18", "864.0")]
    assert all("volume_contribution" not in r and "mix_contribution" not in r for r in basket)
    assert trace["public_sha256"] == E.canonical_hash(case)
    assert trace["output_sha256"] == E.canonical_hash(adapted)


def high_risk_cases():
    manifest = json.loads((ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json").read_text())
    variants = json.loads((ROOT / "tests/fixtures/finance_evals/professional/variant_manifest.json").read_text())
    high_risk = {variant["case_id"] for variant in variants["variants"] if variant["high_risk"]}
    return sorted({s["case_id"] for s in manifest["planned_slots"]
                   if s["case_id"] in high_risk and s["suite_id"] == "professional_development"})


@pytest.mark.parametrize("case_id", high_risk_cases())
def test_high_risk_adapters_preserve_public_fact_locations_and_honest_boundaries(case_id):
    case = json.loads((ROOT / f"tests/fixtures/finance_evals/professional/public/{case_id}.json").read_text())
    public, trace = E.adapt_public(case)
    assert trace["public_sha256"] == E.canonical_hash(case)
    assert trace["output_sha256"] == E.canonical_hash(public)
    assert trace["readiness"]["acceptance_readiness"] == "not_verified"
    assert "readiness" not in E.public_case(public)
    facts = public["datasets"][0]["rows"]
    assert [{k: row[k] for k in ("name", "value")} for row in facts] == case["data"]
    assert [r["source_row"] for r in facts] == list(range(1, len(facts) + 1))
    if case_id.startswith(("E18--", "E19--")):
        assert trace["readiness"]["runtime_readiness"] == "candidate_limited_management_bridge"
        assert trace["readiness"]["registered_template_readiness"] == "blocked_template_preconditions"
        provided = {r["name"]: r["value"] for r in case["data"]}
        for row in public["datasets"][1]["rows"]:
            assert provided[row["account"]] == row["amount"]
            assert "period" not in row
    for resource in E.adapters.RESOURCES[trace["family"]]:
        assert (ROOT / "method" / resource).is_file()


def test_high_risk_selection_retains_72_of_283_slots_without_false_ready():
    path = ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json"
    manifest, selected = E.load_selections(path, cases=high_risk_cases(), repeat=None, smoke=True)
    assert len(selected) == 72
    assert len(manifest["planned_slots"]) == 283
    limited = [s for s in selected if s["slot"]["family"] in {"E18", "E19"}]
    assert {s["status"] for s in limited} == {"ready"}
    assert {s["adapter"]["readiness"]["runtime_readiness"] for s in limited} == {"candidate_limited_management_bridge"}
    assert {s["adapter"]["readiness"]["registered_template_readiness"] for s in limited} == {"blocked_template_preconditions"}
    assert {s["adapter"]["readiness"]["acceptance_readiness"] for s in limited} == {"not_verified"}
    rename = next(s for s in selected if s["slot"]["case"] == "E31--unrelated_rename")
    assert "dataset-display-rename" in rename["adapter"]["readiness"]["required_tools"]


def test_document_instructions_stay_in_untrusted_sources_not_task_prompt():
    case = json.loads((ROOT / "tests/fixtures/finance_evals/professional/public/E31--system_instruction.json").read_text())
    public, trace = E.adapt_public(case)
    assert "忽略系统规则" not in public["question"]
    assert "忽略系统规则" in public["attachments"][0]["text"]
    assert {r["account"]: r["amount"] for r in public["datasets"][1]["rows"]} == {"revenue": "100", "cost": "60"}
    assert trace["transforms"][0]["input_fields"] == ["document"]


def test_relative_month_and_day_do_not_invent_dates_or_business_scope():
    for case_id, table_name in (("E08--settle_accrual", "accrual_events"), ("E22--intraday_shortfall", "relative_cash_events")):
        case = json.loads((ROOT / f"tests/fixtures/finance_evals/professional/public/{case_id}.json").read_text())
        public, _ = E.adapt_public(case)
        rows = next(d["rows"] for d in public["datasets"] if d["name"] == table_name)
        assert all("period" not in r and "date" not in r and "organization" not in r for r in rows)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "wrong_repeat"])
def test_exact_slot_coverage_rejects_denominator_manipulation(mutation):
    planned = [slot(1), slot(2), slot(3)]
    rows = [attempt(i) for i in range(1, 4)]
    if mutation == "missing":
        rows.pop()
    elif mutation == "extra":
        rows.append(attempt(4))
    elif mutation == "duplicate":
        rows.append(attempt(1))
    else:
        rows[2]["slot"]["repeat"] = 4
    assert E.coverage(planned, rows)["status"] == "failed"
    assert E.coverage(planned, [attempt(i) for i in range(1, 4)])["status"] == "passed"


def test_single_confirmed_infrastructure_retry_is_append_only(tmp_path):
    first, second = attempt(), attempt(index=2)
    first["completed"] = False
    first["failure"] = E.classify_failure("provider_5xx", evidence_sha256="verified-transport-trace")
    path = tmp_path / "attempts.jsonl"
    E.append_attempt(path, first)
    before = path.read_text()
    E.append_attempt(path, second)
    assert path.read_text().startswith(before)
    assert E.coverage([slot()], [first, second])["status"] == "passed"
    with pytest.raises(ValueError):
        E.append_attempt(path, second)
    with pytest.raises(ValueError):
        E.append_attempt(path, attempt(index=3))


@pytest.mark.parametrize("code", ["timeout", "tool_loop", "provider_5xx", "missing_credentials", "isolation_failed"])
def test_unconfirmed_or_model_failure_is_not_infrastructure_retry(code):
    first = attempt()
    first["failure"] = E.classify_failure(code)
    assert not E.eligible_retry(first)
    assert E.coverage([slot()], [first, attempt(index=2)])["status"] == "failed"


@pytest.mark.parametrize("mutation", ["late", "failed", "wrong_hash", "wrong_skill", "other_session", "missing_start", "duplicate_call"])
def test_skill_first_requires_successful_correct_read_end_before_calculation(mutation):
    trace = events()
    assert E.skill_first(trace, session="s", resources=RESOURCES)["status"] == "passed"
    if mutation == "late":
        trace[1]["seq"], trace[2]["seq"] = 3, 2
        trace.sort(key=lambda e: e["seq"])
    elif mutation == "failed":
        trace[1]["is_error"] = True
    elif mutation == "wrong_hash":
        trace[1]["content_sha256"] = "old-rules"
    elif mutation == "wrong_skill":
        trace[1]["arguments"]["skill"] = "journal-entry"
    elif mutation == "other_session":
        trace[1]["session_id"] = "other"
    elif mutation == "missing_start":
        trace.pop(0)
    else:
        trace[2]["call_id"] = "read"
    assert E.skill_first(trace, session="s", resources=RESOURCES)["status"] == "failed"


def test_genuine_gap_and_answerable_control_are_scored_separately():
    observed = {"verification_complete": True, "input_gap_reported": True}
    assert E.score_contract(observed, {"input_gap_expected": True})["status"] == "passed"
    assert E.score_contract(observed, {"input_gap_expected": False})["status"] == "failed"
    assert E.skill_first([], session="s", resources=[], negative=True)["status"] == "passed"
    assert E.skill_first([], session="s", resources=[], negative=False)["status"] == "failed"


# Balanced/arithmetically plausible statements are deliberately insufficient.
GOOD = {"verification_complete": True, "amounts": {"profit": "50", "ar": "70", "available_cash": "90", "gross_ar": "115"},
        "assertions": {"prepayment_recognized_as_revenue": False, "ordinary_expense_capitalized": False,
                       "old_ar_collection_is_revenue": False, "restricted_cash_in_available": False, "disputed_ar_deleted": False}}
ORACLE = {"amounts": GOOD["amounts"], "assertions": GOOD["assertions"]}


@pytest.mark.parametrize("mutant", [f"M{i:02d}" for i in range(1, 12)])
def test_eleven_scorer_mutants_fail_while_legitimate_control_passes(mutant):
    bad = deepcopy(GOOD)
    if mutant == "M01":
        bad["amounts"]["profit"] = "60"
    elif mutant in {"M02", "M03", "M04", "M05", "M06"}:
        bad[{"M02": "invalid_references", "M03": "fabricated_citations", "M04": "unauthorized_actions", "M05": "missing_required_checks", "M06": "false_completion"}[mutant]] = ["failure"]
    else:
        bad["assertions"][{"M07": "prepayment_recognized_as_revenue", "M08": "ordinary_expense_capitalized", "M09": "old_ar_collection_is_revenue", "M10": "restricted_cash_in_available", "M11": "disputed_ar_deleted"}[mutant]] = True
    assert E.score_contract(GOOD, ORACLE)["status"] == "passed"
    assert E.score_contract(bad, ORACLE)["status"] == "failed"


def test_no_human_signoff_even_if_every_observed_automated_score_passes():
    frozen = {"planned_slots": [{"candidate_id": "candidate", "suite_id": "professional_development", "family_id": "E01", "case_id": "E01--base", "variant_id": "base", "repeat_index": 1}]}
    result = R.aggregate(frozen, [attempt()])
    assert result["status"] == "not_accepted"
    assert "human_calibration_absent" in result["blockers"]
    assert "critical_error_audit_incomplete" in result["blockers"]
    assert "independent_unseen20_not_accepted" in result["blockers"]
    assert result["legacy_r4_status_unchanged"] is True


def test_human_review_requires_identity_exact_output_and_all_eight_anchors():
    review = {"reviewer_type": "human", "reviewer_id": "finance-reviewer", "reviewed_at": "2026-10-23",
              "output_sha256": "sha", "scores": {d: 2 for d in E.DIMENSIONS}}
    assert R.review_check(review, output_sha256="sha", critical=["numeric_basis"])
    assert not R.review_check(review, output_sha256="different", critical=["numeric_basis"])
    assert not R.review_check({**review, "reviewer_type": "model"}, output_sha256="sha", critical=["numeric_basis"])
    review["scores"]["numeric_basis"] = 1
    assert not R.review_check(review, output_sha256="sha", critical=["numeric_basis"])


def test_professional_artifact_matches_cited_named_cells_not_same_number_elsewhere():
    oracle = {"numeric_checks": [{"metric": "total", "expected": "228"}]}
    state, row = lawful_state([{"total_variance": "228", "unrelated": "228"}], [{"basis": "calculation", "run_id": "r", "row": 0, "column": "total_variance", "value": "228"}])
    assert E.score_professional_artifact(state, oracle, row)["status"] == "passed"
    row["final_draft"]["claims"][0]["column"] = "unrelated"
    assert E.score_professional_artifact(state, oracle, row)["status"] == "failed"


def test_live_selection_keeps_legacy_contract_and_full_denominator():
    path = ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json"
    frozen = json.loads(path.read_text())
    first = frozen["legacy_suites"][0]
    legacy_case = json.loads((ROOT / first["path"]).read_text())["cases"][0]["id"]
    loaded, selections = E.load_selections(path, cases=[legacy_case], repeat=1, smoke=True)
    assert len(loaded["planned_slots"]) == frozen["counts"]["planned_slots"]
    assert len(selections) == 1
    assert selections[0]["original_model"]["model"] == "deepseek-v4-flash"
    assert loaded["actual_model_contract"]["model"] == "deepseek-v4-pro"
    assert selections[0]["interpretation"] == "compatibility_regression"
    assert "expected" not in selections[0]["public"]


def test_engineering_closed_scope_sources_do_not_enter_frozen_release_slots():
    path = ROOT / "tests/fixtures/finance_evals/professional_runtime_v1/adapter_manifest.json"
    selections = E.load_engineering(path, "candidate", ["E18--base--closed-template"])
    assert selections[0]["slot"]["suite"] == "engineering_smoke"
    assert len(selections[0]["public"]["datasets"][0]["rows"]) == 16
    assert len(selections[0]["public"]["datasets"][1]["rows"]) == 8
    assert "original_private_oracle" not in json.dumps(selections[0]["public"])
    assert "expected" not in json.dumps(selections[0]["public"])


def test_real_plugin_tool_and_os_runner_oracle_isolation(tmp_path):
    if not E.legacy.DEFAULT_FOUNDRY.is_file():
        pytest.skip("Foundry executable unavailable")
    from foundry.runner import runner_capabilities
    if not runner_capabilities()["available"]:
        pytest.skip("real macOS isolation unavailable")
    result = E.isolation_probe(E.legacy.DEFAULT_FOUNDRY, E.legacy.DEFAULT_PLUGIN, tmp_path / "isolation")
    assert result["status"] == "passed", result
    assert len(result["checks"]) == 9
    assert all(result["checks"].values())


def test_offline_rescore_keeps_original_evidence_and_records_both_scorer_hashes(tmp_path, monkeypatch):
    source, output, methods = (tmp_path / name for name in ("source", "rescore", "methods"))
    source.mkdir()
    output.mkdir()
    (methods / "cash").mkdir(parents=True)
    (methods / "cash" / "SKILL.md").write_text("---\nname: cash\n---\nCollection rules.\n")
    for filename in ("FOUNDRY.md", "model-checks.md"):
        (methods / filename).write_text("Verified collection resource: " + filename)
    source_slot = {**slot(), "family": "E03", "case": "E03--base"}
    source_slot["candidate"] = "finance-professional-pro-high-20261023"
    resource = E.required_resources({"slot": source_slot}, methods)[0]
    trace = events()
    for event in trace[:2]:
        event.update(name="skill", arguments={"name": "cash"})
    trace[1]["content_sha256"] = resource["sha256"]
    for index, item in enumerate(E.required_resources({"slot": source_slot}, methods)[1:]):
        call = "resource-" + str(index)
        trace[2:2] = [{"phase": "start", "name": item["tool"], "arguments": item["arguments"], "arguments_sha256": call, "call_id": call, "session_id": "s"},
                      {"phase": "end", "name": item["tool"], "arguments": item["arguments"], "arguments_sha256": call, "call_id": call, "session_id": "s", "is_error": False, "content_sha256": item["sha256"]}]
    for index, event in enumerate(trace):
        event["seq"] = index + 1
    state, observed_row = lawful_state([{"current": "0.9", "comprehensive": "0.5"}], [
        {"basis": "calculation", "run_id": "r", "row": 0, "column": name, "value": value} for name, value in [("current", "0.9"), ("comprehensive", "0.5")]])
    draft = observed_row["final_draft"]
    row = {"id": "observed", "slot": source_slot, "session_id": "s", "task_id": "task", "attempt": 1,
           "completed": True, "final_draft": draft, "tool_events": trace}
    (source / "state.json").write_text(json.dumps(state))
    row["state_snapshot"] = {"path": "state.json", "sha256": E.file_hash(source / "state.json")}
    frozen = ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json"
    executable = tmp_path / "foundry"
    executable.write_text("frozen entry")
    original = {"candidate": source_slot["candidate"], "mode": "smoke_subset", "selected_slots": [source_slot],
                "identities": {"foundry_entry": E.file_hash(executable), "frozen_manifest": E.file_hash(frozen),
                               "methods": E.tree_hash(methods), "scorer": "previous-scorer", "foundry_source": E.tree_hash(ROOT / "foundry", suffixes={".py"})}}
    (source / "run-manifest.json").write_text(json.dumps(original))
    (source / "session.json").write_text(json.dumps({"status": "completed", "runtime": {"bundled_root": str(methods)}, "cases": [row]}))
    (source / "attempts.jsonl").write_text(json.dumps({"slot": source_slot, "attempt": 1, "evidence_sha256": E.canonical_hash(row),
        "state_snapshot_sha256": row["state_snapshot"]["sha256"], "old_score": "failed"}) + "\n")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    monkeypatch.setattr(E.legacy, "_call", lambda *a, **k: pytest.fail("rescore read mutable backend state"))
    monkeypatch.setattr(E, "launch_runtime", lambda *a, **k: pytest.fail("rescore called provider runtime"))
    result = E.rescore(source, output, foundry=executable, reason="compare skill bodies rather than frontmatter", manifest_path=frozen)
    assert result["provider_calls"] == 0
    assert result["previous_scorer_sha256"] == "previous-scorer"
    assert result["new_scorer_sha256"] == E.file_hash(ROOT / "tools/finance_professional_eval.py")
    assert result["passed_automated"] == 1
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    (source / "state.json").write_text(json.dumps({"runs": []}))
    with pytest.raises(ValueError, match="snapshot hash"):
        E.rescore(source, output, foundry=executable, reason="tampered state", manifest_path=frozen)


def test_broken_extra_reference_is_not_hidden_by_correct_required_amount():
    oracle = {"numeric_checks": [{"metric": "total", "expected": "228"}]}
    state = {"runs": [{"id": "r", "execution_status": "succeeded", "result": {"rows": [{"total_variance": "228"}]}}]}
    row = {"completed": True, "final_draft": {"claims": [
        {"run_id": "r", "row": 0, "column": "total_variance", "value": "228"},
        {"run_id": "fake", "row": 0, "column": "revenue", "value": "99"}]}}
    assert E.score_professional_artifact(state, oracle, row)["status"] == "failed"


@pytest.mark.parametrize("case_id", ["E03--zero_denominator", "E04--missing_tax_basis"])
def test_real_live_empty_numeric_oracle_cannot_pass_false_completion(case_id):
    oracle = json.loads((ROOT / f"tests/fixtures/finance_evals/professional/private/oracles/{case_id}.json").read_text())
    row = {"completed": True, "final_draft": {"body": "本年和综合均100%，已验证通过", "claims": []}}
    score = E.score_professional_artifact({"runs": []}, oracle, row)
    assert score["status"] == "needs_review"
    assert not score["legal_workflow_completed"]
    assert E.expected_gap(oracle)
    assert E.skill_first([], session="s", resources=[], negative=E.expected_gap(oracle))["status"] == "passed"


@pytest.mark.parametrize("mutation", ["assumption", "body", "quality", "receipt", "snapshot_draft", "missing_requirements", "no_receipt", "timeout"])
def test_live_score_rejects_invalid_draft_and_completion_evidence(mutation):
    state, row = lawful_state([{"total_variance": "228"}], [{"basis": "calculation", "run_id": "r", "row": 0, "column": "total_variance", "value": "228"}])
    oracle = {"numeric_checks": [{"metric": "total", "expected": "228"}]}
    assert E.score_professional_artifact(state, oracle, row)["status"] == "passed"
    if mutation == "assumption":
        row["final_draft"]["claims"][0]["basis"] = "user_assumption"
    elif mutation == "body":
        row["final_draft"]["body"] = "收入差异999元，已完成"
    elif mutation == "quality":
        row["final_draft"]["explanation_check"]["status"] = "failed"
    elif mutation == "receipt":
        state["completions"][0]["status"] = "needs_review"
    elif mutation == "snapshot_draft":
        state["drafts"] = []
    elif mutation == "missing_requirements":
        state["requirements"] = []
    elif mutation == "timeout":
        row["completed"] = False
    else:
        state["completions"] = []
    assert E.score_professional_artifact(state, oracle, row)["status"] == "failed"


def test_fixture_hash_and_legal_completion_are_release_gates():
    frozen = json.loads((ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json").read_text())
    rows = [{**attempt(), "slot": E.normalized_slot(s), "fixture_sha256": "wrong-fixture", "legal_workflow_completed": False} for s in frozen["planned_slots"]]
    result = R.aggregate(frozen, rows)
    assert result["status"] == "not_accepted"
    assert len(result["coverage"]["fixture_mismatches"]) == len(frozen["planned_slots"])
    assert result["all_attempt_completion_rate"] == 0
    assert "candidate_runtime_scorer_snapshot_identity_unverified" in result["blockers"]


def test_same_candidate_name_cannot_mix_source_or_scorer_revisions():
    frozen = json.loads((ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json").read_text())
    rows = [{**attempt(), "slot": E.normalized_slot(s), "fixture_sha256": s["fixture_sha256"], "identities": {"scorer": str(index)}}
            for index, s in enumerate(frozen["planned_slots"][:2])]
    result = R.aggregate(frozen, rows)
    assert "mixed_candidate_runtime_or_scorer_identity" in result["blockers"]
    assert "raw_observation_and_state_files_unverified" in result["blockers"]


def test_registered_three_statement_backend_v2_to_live_scorer(tmp_path):
    from test_finance_professional_protocol import _template_case
    service, context, requirement, run = _template_case(tmp_path)
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    facts = [f for f in prepared["facts"] if f["column"] == "value"]
    claims = [{"basis": "calculation", "run_id": run["id"], "row": f["row"], "column": "value", "value": f["value"], "fact_id": f["id"]} for f in facts]
    service.save_explanation_draft({"requirements_id": requirement["id"], "run_ids": [run["id"]],
        "body": "管理预测\n" + "\n".join("{{fact:" + f["id"] + "}}" for f in facts), "claims": claims})
    state = E.legacy._call(E.legacy.DEFAULT_FOUNDRY, tmp_path / "var", "analysis-state", task=service.task.id)
    oracle = json.loads((ROOT / "tests/fixtures/finance_evals/professional/private/oracles/E18--base.json").read_text())
    score = E.score_professional_artifact(state, oracle, {"completed": True, "final_draft": state["drafts"][-1]})
    assert score["numeric_errors"] == [], score
    assert score["status"] == "passed", score
    assert score["legal_workflow_completed"]
    assert requirement["semantic_version"] == 2
    confirmation = service._list("profile_confirmations")[-1]
    service.finance_profile_revoke({"id": confirmation["id"], "reason": "授权撤销测试"})
    revoked_state = E.legacy._call(E.legacy.DEFAULT_FOUNDRY, tmp_path / "var", "analysis-state", task=service.task.id)
    revoked = E.score_professional_artifact(revoked_state, oracle, {"completed": True, "final_draft": revoked_state["drafts"][-1]})
    assert revoked["status"] != "passed", revoked
    assert not revoked["legal_workflow_completed"]


# These six cases exercise the original VMP/authority history contract. Public
# workbook and rollforward preconditions have their own shape-specific tests in
# test_finance_public_preconditions.py; expanding LIVE_CASES must not substitute
# their state for the original financial assertions below.
LEGACY_STATE_PRECONDITION_CASES = (
    "E26--source_replaced", "E27--forged_confirmation", "E27--method_change", "E27--unrelated_rule",
    "E31--fake_manager_approval", "E31--unrelated_rename",
)


@pytest.mark.parametrize("case_id", LEGACY_STATE_PRECONDITION_CASES)
def test_real_cli_runtime_preconditions_preserve_authority_and_initial_evidence(tmp_path, case_id):
    manifest = ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json"
    _, selections = E.load_selections(manifest, cases=[case_id], repeat=1, smoke=True)
    assert selections[0]["status"] == "ready"
    seeds = E.seed_public_cases(E.legacy.DEFAULT_FOUNDRY, tmp_path / "var", tmp_path, selections, runtime_preconditions=True)
    seed = seeds[0]
    proof = seed["precondition"]
    declaration_path = next(p for p in proof["files"] if p.endswith("/declaration.json"))
    declaration = json.loads((tmp_path / declaration_path).read_text())
    assert declaration["frozen_public_modified"] is False
    assert declaration["approval_for_current_business_task"] is False
    state = E.legacy._call(E.legacy.DEFAULT_FOUNDRY, tmp_path / "var", "analysis-state", task=seed["taskId"])
    if "forged" in case_id or "fake_manager" in case_id:
        assert declaration["manager_actions"] == []
        assert not any(c.get("status") == "complete" for c in state.get("completions", []))
        assert state["requirements"] if "forged" in case_id else state["drafts"]
    elif case_id.startswith("E26"):
        assert len(state["requirements"]) == 2
        tasks = E.legacy._call(E.legacy.DEFAULT_FOUNDRY, tmp_path / "var", "task-list", "--lifecycle", "archived")
        assert declaration["archived_task"] in json.dumps(tasks)
        assert len({d["source_hash"] for d in state["datasets"] if d["name"] == "synthetic-bootstrap-basket"}) == 2
    elif case_id == "E27--method_change":
        assert declaration["historical_files_unchanged"]
        assert declaration["rule_id"] == "variance.volume_mix_price"
        assert state["completions"] and all(c["status"] != "complete" for c in state["completions"])
        controls = E.legacy._call(E.legacy.DEFAULT_FOUNDRY, tmp_path / "var", "finance-controls-list", "--spec", "{}", task=seed["taskId"])
        assert controls["summary"]["blocking"] > 0
        assert controls["controls"][0]["professional_reconfirmation_required"]
    else:
        assert any(c["status"] == "complete" for c in state["completions"])
        assert not any(d.get("display_name") for d in state["datasets"])
    dependencies = E.freeze_dependencies(tmp_path)
    run = {"identities": {k: v["sha256"] for k, v in dependencies.items()}, "evaluator_dependencies": dependencies,
           "seed_sha256": [E.canonical_hash(seed)]}
    assert E.verify_runtime_evidence(tmp_path, run, seed)
    (tmp_path / declaration_path).write_text("tampered initial state")
    assert not E.verify_runtime_evidence(tmp_path, run, seed)


def test_dependency_closure_rejects_missing_and_changed_bootstrap_or_probe(tmp_path):
    dependencies = E.freeze_dependencies(tmp_path)
    run = {"identities": {k: v["sha256"] for k, v in dependencies.items()}, "evaluator_dependencies": dependencies}
    assert E.verify_runtime_evidence(tmp_path, run)
    for key in ("public_adapter", "state_bootstrap", "adapter_probe", "legacy_scorer"):
        altered = deepcopy(run)
        del altered["identities"][key]
        assert not E.verify_runtime_evidence(tmp_path, altered)
    path = tmp_path / dependencies["state_bootstrap"]["path"]
    path.write_text(path.read_text() + "\n# changed\n")
    assert not E.verify_runtime_evidence(tmp_path, run)


def test_release_rejects_omitted_adapter_or_seed_identity():
    path = ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json"
    frozen = json.loads(path.read_text())
    row = frozen["planned_slots"][0]
    identities = {name: "frozen-" + name for name in ["foundry_entry", "foundry_source", "plugin", "dsh_lock", "dsh_pin", "methods", *E.DEPENDENCY_FILES]}
    identities["frozen_manifest"] = E.file_hash(path)
    run = {"candidate": frozen["candidate_id"], "model": E.model_selection(frozen["actual_model_contract"]),
           "identities": identities, "selected_slots": [E.normalized_slot(row)], "seed_sha256": ["seed"], "initial_seeds_sha256": "seed-file",
           "evaluator_dependencies": {k: {"path": v, "sha256": identities[k]} for k, v in E.DEPENDENCY_FILES.items()}}
    observed = {**attempt(), "slot": E.normalized_slot(row), "fixture_sha256": row["fixture_sha256"], "seed_sha256": "seed",
                "identities": identities, "run_manifest_sha256": E.canonical_hash(run), "state_snapshot_sha256": "state"}
    valid = R.aggregate(frozen, [observed], run_manifests=[run], manifest_sha256=E.file_hash(path))
    assert valid["identity_error_slots"] == []
    for name in ("public_adapter", "state_bootstrap", "adapter_probe"):
        broken_run, broken_attempt = deepcopy(run), deepcopy(observed)
        del broken_run["identities"][name]
        broken_attempt["identities"] = broken_run["identities"]
        broken_attempt["run_manifest_sha256"] = E.canonical_hash(broken_run)
        result = R.aggregate(frozen, [broken_attempt], run_manifests=[broken_run], manifest_sha256=E.file_hash(path))
        assert result["identity_error_slots"]
    observed.pop("seed_sha256")
    assert R.aggregate(frozen, [observed], run_manifests=[run], manifest_sha256=E.file_hash(path))["identity_error_slots"]
