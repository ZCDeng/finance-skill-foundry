import hashlib
import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from foundry.analysis import AnalysisStore
from foundry.finance_professional import cell_evidence_eligibility
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

STALE = "adjustment_approval_superseded"
UNAVAILABLE = "adjustment_dependency_unavailable"


@pytest.fixture
def case(tmp_path):
    source = tmp_path / "management.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Management"
    sheet.append(["account_code", "management_account", "amount", "management_old", "management_new",
                  "ledger", "organization", "period", "scenario", "currency", "unit"])
    for values in [("6001", "revenue", 200, 200, 200, "book"),
                   ("6401", "cost", 60, -60, -60, "book"),
                   ("6601", "expense", 10, -10, -10, "book"),
                   ("ADJ", "other_income", 100, 100, 120, "adjustment-support")]:
        sheet.append([*values, "O1", "2026-08", "actual", "CNY", "元"])
    book.save(source)
    book.close()
    task = TaskStore(tmp_path / "var").create(title="当前批准调整引用")
    analysis = AnalysisStore(task)
    dataset = analysis.add_dataset(source, name="管理损益组成项")
    store = FinanceStore(task)
    context = store.save_context({"bindings": {"actual": dataset["id"]}, "scopes": {"actual": {
        "ledger": "book", "organization": "O1", "period": "2026-08", "scenario": "actual", "currency": "CNY", "unit": "元"}}})
    requirement = store.analysis_requirements_save({"question": "报告当期经批准调整后的管理利润",
        "bindings": context["bindings"], "scope": {"organization": "O1", "period": "2026-08", "currency": "CNY", "unit": "元"},
        "items": [{"id": "pnl", "metric": "management_pnl", "requires_drilldown": True}]})
    return SimpleNamespace(store=store, analysis=analysis, dataset=dataset, context=context,
                           requirement=requirement, aggregates={}, tmp_path=tmp_path)


def approve(case, amount="100", *, parent=None, confirm=True, context=None, period="2026-08", accounts=None):
    context = context or case.context
    spec = {"context_id": context["id"], "label": "管理利润调整", "amount": amount, "profit_impact": amount,
            "effective_period": period, "accounts": accounts or ["management-adjustment"],
            "basis": "professional_judgment", "bindings": context["bindings"]}
    if parent:
        spec["parent_id"] = parent["id"]
    pending = case.store.finance_adjustment_save(spec)
    return case.store.finance_adjustment_confirm({"id": pending["id"]}) if confirm else pending


def native(case, adjustment=None):
    return case.store.run_metric({"context_id": case.context["id"], "metric": {"kind": "management_pnl"},
                                  "adjustment_ids": [adjustment["id"]] if adjustment else []})


def eligibility(case, run, column="adjusted_total", row=0):
    return cell_evidence_eligibility(run, run["result"]["rows"][row], column, analysis=case.analysis)


def draft_spec(case, run, *, field="management_old", direct=True, recipe=True, column="adjusted_total"):
    if field not in case.aggregates:
        definition = case.analysis.save_analysis({"question": "从同源组成项复算管理利润", "engine": "structured_aggregate",
            "bindings": case.context["bindings"], "aggregate_plan": {"dataset_alias": "actual",
                "group_by": ["organization", "period"], "scope": {"currency": "CNY", "unit": "元"},
                "measures": [{"name": "management_pnl", "field": field, "aggregation": "sum"}], "dedupe": {"policy": "none"}}})
        case.aggregates[field] = case.analysis.run_analysis(definition["id"])
    aggregate = case.aggregates[field]
    case.store.drilldown_fact({"run_id": aggregate["id"], "row": 0, "column": "management_pnl"})
    run_ids = [run["id"], aggregate["id"]] if direct else [aggregate["id"]]
    facts = case.store.prepare_explanation({"run_ids": run_ids, "fact_view": "inspection"})["facts"]
    selected = [f for f in facts if f["column"] in {column, "management_pnl"}]
    recipes = [{"id": "native-total", "kind": "sum", "dataset_id": case.dataset["id"],
                "source_hash": case.dataset["source_hash"], "sheet": "Management",
                "range": "D2:D5" if field == "management_old" else "E2:E5", "unit": "元",
                "claim": {"run_id": run["id"], "row": 0, "column": "adjusted_total"}}] if recipe else []
    return {"requirements_id": case.requirement["id"], "run_ids": run_ids,
            "body": "当前最新已批准口径的本期结论：\n" + "\n".join(f["column"] + " {{fact:" + f["id"] + "}}。" for f in selected),
            "fact_ids": [f["id"] for f in selected], "evidence_recipes": recipes}


def issue_codes(draft):
    return {issue["code"] for issue in draft["quality"]["issues"]}


def archive_hashes(case):
    folders = ["runs", "revisions", "drafts", "completions", "requirements", "datasets", "finance/adjustments"]
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for folder in folders
            for path in (case.analysis.root / folder).rglob("*") if path.is_file()}


def test_complete_current_reuse_rejects_replaced_approval_and_new_250_recovers(case):
    old_adjustment = approve(case)
    old_run = native(case, old_adjustment)
    spec = draft_spec(case, old_run)
    old = case.store.save_explanation_draft(spec)
    assert old["completion"]["status"] == "complete"
    assert old_run["result"]["rows"][0]["adjusted_total"] == "230"
    archives = archive_hashes(case)
    replacement = approve(case, "120", parent=old_adjustment)
    new_run = native(case, replacement)
    assert new_run["result"]["rows"][0]["adjusted_total"] == "250"
    current = case.analysis.completion_in_view(old["completion"], None)
    assert current["status"] != "complete"
    assert current["historical_status"] == "complete"
    assert current["original_requirements_completed"] is False
    replay = case.store.save_explanation_draft(spec)
    assert replay["completion"]["status"] != "complete"
    fresh = case.store.save_explanation_draft({**spec, "body": "本次当前结论。\n" + spec["body"]})
    assert fresh["id"] != old["id"]
    assert STALE in issue_codes(fresh)
    assert fresh["completion"]["status"] != "complete"
    assert STALE in {i["code"] for i in case.store.validate_explanation({"draft_id": old["id"]})["issues"]}
    new = case.store.save_explanation_draft(draft_spec(case, new_run, field="management_new"))
    assert new["completion"]["status"] == "complete"
    assert not issue_codes(new)
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in archives} == archives


def test_recipe_only_dependency_cannot_hide_old_native_adjusted_total(case):
    adjustment = approve(case)
    run = native(case, adjustment)
    spec = draft_spec(case, run, direct=False)
    assert run["id"] not in spec["run_ids"]
    before = case.store.save_explanation_draft(spec)
    assert before["completion"]["status"] == "complete"
    approve(case, "120", parent=adjustment)
    after = case.store.save_explanation_draft({**spec, "body": "本次更新。\n" + spec["body"]})
    assert STALE in issue_codes(after)
    assert after["completion"]["status"] != "complete"


@pytest.mark.parametrize("amount", ["120", "0", "-100", "100"])
def test_only_adjusted_cell_loses_eligibility_for_any_new_approved_identity(case, amount):
    adjustment = approve(case)
    run = native(case, adjustment)
    assert eligibility(case, run)["counts_as_amount_evidence"]
    approve(case, amount, parent=adjustment)
    assert eligibility(case, run)["reason_codes"] == [STALE]
    for column in ("source_total", "profit", "revenue", "cost", "expense"):
        assert eligibility(case, run, column)["counts_as_amount_evidence"], column
    fresh = case.store.save_explanation_draft(draft_spec(case, run, recipe=False, column="profit"))
    assert fresh["completion"]["status"] == "complete"
    assert STALE not in issue_codes(fresh)
    assert all(claim.get("column") != "adjusted_total" for claim in fresh["claims"])
    adjusted_line = next(line for line in fresh["evidence_appendix"].splitlines() if "adjusted_total" in line)
    assert "230" not in adjusted_line
    assert "当前批准" in fresh["evidence_appendix"]


@pytest.mark.parametrize("change", ["pending", "unrelated", "context", "period", "accounts"])
def test_changes_outside_applied_approval_scope_do_not_invalidate(case, change):
    adjustment = approve(case)
    run = native(case, adjustment)
    options = {"parent": adjustment}
    if change == "pending":
        options["confirm"] = False
    if change == "unrelated":
        options.update(parent=None, accounts=["another-adjustment"])
    if change == "context":
        options["context"] = case.store.save_context({"bindings": case.context["bindings"], "scopes": case.context["scopes"]})
    if change == "period":
        options["period"] = "2026-09"
    if change == "accounts":
        options["accounts"] = ["another-adjustment"]
    approve(case, "120", **options)
    assert eligibility(case, run)["counts_as_amount_evidence"]


def test_unapplied_adjustment_keeps_book_evidence(case):
    pending = approve(case, confirm=False)
    run = native(case, pending)
    assert "adjusted_total" not in run["result"]["rows"][0]
    assert eligibility(case, run, "profit")["counts_as_amount_evidence"]


def test_real_unaffected_rows_keep_evidence_when_period_total_consumes_adjustment(case):
    rows = case.analysis.read_dataset(case.dataset["id"])["rows"]
    rows.append({"account_code": "6001", "management_account": "revenue", "amount": "50", "ledger": "book",
                 "organization": "O2", "period": "2026-08", "scenario": "actual", "currency": "CNY", "unit": "元"})
    source = case.tmp_path / "two-organizations.json"
    source.write_text(json.dumps(rows))
    dataset = case.analysis.add_dataset(source, name="two organizations")
    case.context = case.store.save_context({"bindings": {"actual": dataset["id"]}, "scopes": {
        "actual": {**case.context["scopes"]["actual"], "organization": ["O1", "O2"]}}})
    approved = approve(case)
    run = native(case, approved)
    approve(case, "120", parent=approved)
    unaffected = [row for row in run["result"]["rows"] if row.get("organization") in {"O1", "O2"}]
    assert len(unaffected) == 2
    assert run["result"]["applied_adjustment_ids"] == [approved["id"]]
    for row in unaffected:
        assert row["applied_adjustment_ids"] == []
        assert cell_evidence_eligibility(run, row, "adjusted_total", analysis=case.analysis)["counts_as_amount_evidence"]


def test_pending_descendant_preserves_actual_complete_receipt(case):
    approved = approve(case)
    run = native(case, approved)
    spec = draft_spec(case, run)
    old = case.store.save_explanation_draft(spec)
    assert old["completion"]["status"] == "complete"
    approve(case, "120", parent=approved, confirm=False)
    assert case.analysis.completion_in_view(old["completion"], None)["status"] == "complete"
    assert case.store.save_explanation_draft(spec)["completion"]["status"] == "complete"


def test_explicit_calculation_claim_without_fact_id_cannot_reuse_old_total(case):
    approved = approve(case)
    run = native(case, approved)
    spec = draft_spec(case, run, recipe=False)
    approve(case, "120", parent=approved)
    spec.update(body="当前调整后利润230元。", fact_ids=[], claims=[{
        "basis": "calculation", "run_id": run["id"], "row": 0, "column": "adjusted_total", "value": "230"}])
    after = case.store.save_explanation_draft(spec)
    assert STALE in issue_codes(after)


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_unreadable_applied_dependency_fails_closed_without_staling_book_values(case, damage):
    adjustment = approve(case)
    run = native(case, adjustment)
    path = case.store._path("adjustments", adjustment["id"])
    if damage == "missing":
        path.unlink()
    else:
        path.write_text('{}')
    assert UNAVAILABLE in eligibility(case, run)["reason_codes"]
    assert eligibility(case, run, "profit")["counts_as_amount_evidence"]


@pytest.mark.parametrize("damage", ["approved_record", "pending_link"])
def test_unreadable_relevant_descendant_chain_fails_closed(case, damage):
    approved = approve(case)
    run = native(case, approved)
    replacement = approve(case, "120", parent=approved)
    path = case.store._path("adjustments", replacement["id"] if damage == "approved_record" else replacement["parent_id"])
    if damage == "approved_record":
        record = json.loads(path.read_text())
        record["label"] = "damaged approval"
        path.write_text(json.dumps(record))
    else:
        path.unlink()
    assert UNAVAILABLE in eligibility(case, run)["reason_codes"]


def test_unrelated_damaged_record_is_not_a_global_invalidator(case):
    approved = approve(case)
    run = native(case, approved)
    other = approve(case, "120", accounts=["other-adjustment"])
    path = case.store._path("adjustments", other["id"])
    record = json.loads(path.read_text())
    record["label"] = "damaged unrelated approval"
    path.write_text(json.dumps(record))
    assert eligibility(case, run)["counts_as_amount_evidence"]


def test_restricted_reader_never_receives_other_snapshot_identifiers(case, tmp_path):
    adjustment = approve(case)
    run = native(case, adjustment)
    old = case.store.save_explanation_draft(draft_spec(case, run))
    hidden_source = tmp_path / "hidden.json"
    hidden_source.write_text(json.dumps([{"amount": "999"}]))
    hidden = case.analysis.add_dataset(hidden_source, name="hidden")
    hidden_context = case.store.save_context({"bindings": {"secret": hidden["id"]}})
    hidden_adjustment = approve(case, "120", parent=adjustment, context=hidden_context)
    restricted = FinanceStore(case.store.task, snapshot_ids={case.dataset["id"]})
    viewed = restricted.save_explanation_draft(draft_spec(case, run))
    assert viewed["completion"]["status"] == old["completion"]["status"] == "complete"
    encoded = json.dumps(viewed)
    assert hidden["id"] not in encoded and hidden_adjustment["id"] not in encoded
