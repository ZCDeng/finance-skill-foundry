"""A session reads every record as it would have saved it from the files it may read.

A session's snapshot ceiling (context.snapshot_ids; FinanceStore.allowed) decides what it may read. A record
that rests on a file outside it, or a part of one that does, neither shows nor changes what the session reads:
not a draft's parent, a requirements version, a run another reader made, a completion receipt, a newer upload or
a control result. The manager (no session) reads every record as stored.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from foundry.analysis import PARENT_UNAVAILABLE, AnalysisStore
from foundry.cli import main
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

from test_finance_controls import _ar_pack, _side

SQL = "select metric_key, period, organization, amount, currency, unit from t"
SECRET = "987654.321"


def _cli(capsys, var: Path, *args: str, session: str | None = "sess", task: str | None = None):
    code = main(["--var", str(var), *(["--session", session] if session else ["--task", task]), *args])
    out = capsys.readouterr()
    return code, (json.loads(out.out) if code == 0 else out.err)


def _csv(path: Path, rows: list[tuple[str, ...]]) -> Path:
    path.write_text("metric_key,period,organization,amount,currency,unit\n"
                    + "".join(",".join(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _ledger(path: Path, rows: list[dict]) -> Path:
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return path


def _shows(value, tokens) -> list[str]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return [token for token in tokens if token in text]


def _codes(check: dict) -> list[str]:
    return [issue.get("code") for issue in check.get("issues") or []]


def _normalized(value) -> str:
    """Two worlds draw different ids and clocks: number the ids by first appearance and blank the clocks."""
    text = re.sub(r'"_integrity_hash": "[0-9a-f]{64}"', '"_integrity_hash": "<hash>"',
                  json.dumps(value, ensure_ascii=False, sort_keys=True))
    seen: dict[str, str] = {}
    text = re.sub(r"\b[0-9a-f]{32}\b", lambda match: seen.setdefault(match.group(0), f"<id{len(seen)}>"), text)
    return re.sub(r"\d{4}-\d{2}-\d{2}T[0-9:.]+(?:Z|[+-]\d{2}:\d{2})?", "<ts>", text)


# --- a revision whose parent rests on a file outside the session -------------------------------------------------


@pytest.fixture
def revision(tmp_path):
    """The manager drafts P on a file outside the session, then revises it into C on a file inside it."""
    var = tmp_path / "var"
    task = TaskStore(var).create(title="修订")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(tmp_path / "a.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")]), name="总账")
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_csv(tmp_path / "h.csv", [("revenue", "2026-08", "集团", SECRET, "CNY", "元")]), name="薪酬")

    def run(dataset):
        return analysis.run_analysis(analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": dataset["id"]}})["id"])

    ra, rh = run(a), run(h)
    parent = analysis.save_draft({"title": "P", "body": "收入说明。", "run_ids": [rh["id"]]})
    child = analysis.save_draft({"title": "C", "parent_id": parent["id"], "body": "收入说明（修订）。", "run_ids": [ra["id"]]})
    assert child["revision_comparison"]["summary"]["status"] == "needs_attention"
    hidden = [h["id"], rh["id"], parent["id"], SECRET, *rh["input_hashes"].values()]
    return SimpleNamespace(var=var, task=task, analysis=analysis, a=a, h=h, ra=ra, rh=rh, parent=parent,
                           child=child, hidden=hidden)


def test_a_session_reads_a_revision_without_a_parent_it_may_not_read(revision, capsys):
    code, state = _cli(capsys, revision.var, "analysis-state")
    assert code == 0
    assert [draft["id"] for draft in state["drafts"]] == [revision.child["id"]]
    code, read = _cli(capsys, revision.var, "report-draft-read", "--draft", revision.child["id"])
    assert code == 0
    code, audit = _cli(capsys, revision.var, "report-projection-read", "--draft", revision.child["id"], "--mode", "audit")
    assert code == 0
    for shown in (state, read, audit):
        assert _shows(shown, revision.hidden) == []
    assert read == state["drafts"][0]
    assert read["parent_id"] is None
    assert read["revision_comparison"] == {"schema_version": 1, "issues": [], "summary": {"status": "no_parent"}}
    for key in ("explanation_check", "quality"):
        check = read[key]
        assert not [code for code in _codes(check) if code.startswith("revision_")]
        numeric = check["status_dimensions"]["numeric_citation"]
        assert not [issue for issue in numeric["issues"] if issue["code"].startswith("revision_")]
        assert not [label for label in check["evidence_labels"] if label["key"]["kind"] == "revision"]
    # The draft as the session would have saved it: the same spec with no parent.
    alone = revision.analysis.save_draft({"title": "C", "body": "收入说明（修订）。", "run_ids": [revision.ra["id"]]})
    expected = revision.analysis.draft_in_view(alone, {revision.a["id"]})
    for key in ("explanation_check", "quality"):
        assert read[key] == expected[key]
    # The manager reads the comparison as saved.
    code, managed = _cli(capsys, revision.var, "report-draft-read", "--draft", revision.child["id"],
                         session=None, task=revision.task.id)
    assert code == 0
    assert managed == revision.analysis.get_draft(revision.child["id"])
    assert managed["parent_id"] == revision.parent["id"]


def test_a_session_that_may_read_the_parent_reads_the_comparison_as_saved(revision, capsys):
    assert _cli(capsys, revision.var, "analysis-refresh")[0] == 0
    code, read = _cli(capsys, revision.var, "report-draft-read", "--draft", revision.child["id"])
    assert code == 0
    stored = revision.analysis.get_draft(revision.child["id"])
    assert read["parent_id"] == revision.parent["id"]
    assert read["revision_comparison"] == stored["revision_comparison"]
    assert read["explanation_check"]["issues"] == stored["explanation_check"]["issues"]


def test_validating_a_revision_compares_only_with_a_parent_the_session_may_read(revision):
    session = FinanceStore(revision.task, snapshot_ids=[revision.a["id"]], session_id="sess")
    checked = session.validate_explanation({"draft_id": revision.child["id"]})
    assert checked["revision_comparison"]["summary"]["status"] == "no_parent"
    assert not [code for code in _codes(checked) if code.startswith("revision_")]
    assert _shows(checked, revision.hidden) == []
    spec = {"body": "收入说明。", "run_ids": [revision.ra["id"]]}
    with pytest.raises(FoundryError) as hidden:
        session.validate_explanation({**spec, "parent_id": revision.parent["id"]})
    with pytest.raises(FoundryError) as unknown:
        session.validate_explanation({**spec, "parent_id": "f" * 32})
    assert str(hidden.value) == str(unknown.value) == PARENT_UNAVAILABLE
    manager = FinanceStore(revision.task).validate_explanation({"draft_id": revision.child["id"]})
    assert [code for code in _codes(manager) if code.startswith("revision_")]


def test_saving_a_revision_of_a_hidden_or_unknown_parent_fails_alike(revision, capsys):
    errors = []
    for parent_id in (revision.parent["id"], "f" * 32):
        spec = {"parent_id": parent_id, "body": "收入说明。", "run_ids": [revision.ra["id"]]}
        code, error = _cli(capsys, revision.var, "analysis-draft", "--spec", json.dumps(spec, ensure_ascii=False))
        assert code != 0
        errors.append(error)
        with pytest.raises(FoundryError) as refused:
            FinanceStore(revision.task, snapshot_ids=[revision.a["id"]], session_id="sess").save_explanation_draft(spec)
        errors.append(str(refused.value) + "\n")
    assert len(set(errors)) == 1 and PARENT_UNAVAILABLE in errors[0]


def test_a_retried_save_is_refused_to_a_session_that_may_not_read_the_parent(revision):
    spec = {"parent_id": revision.parent["id"], "body": "收入说明（修订）。", "run_ids": [revision.ra["id"]]}
    saved = FinanceStore(revision.task).save_explanation_draft(spec)
    assert FinanceStore(revision.task).save_explanation_draft(spec)["id"] == saved["id"]
    with pytest.raises(FoundryError, match=re.escape(PARENT_UNAVAILABLE)):
        FinanceStore(revision.task, snapshot_ids=[revision.a["id"]], session_id="sess").save_explanation_draft(spec)


def test_a_context_grant_refuses_to_validate_against_a_parent_outside_it(revision):
    from foundry.finance_mcp import FinanceMcpServer, McpRefused

    service = FinanceStore(revision.task, snapshot_ids=[revision.a["id"]])
    granted = "0" * 32
    grant = {"snapshot_ids": [revision.a["id"]], "context_ids": [granted]}
    FinanceMcpServer._authorize_context(None, grant, service, "validate_explanation", {"context_id": granted})
    # The parent's runs are in no context the grant holds, as for a revision saved under the grant.
    for tool in ("validate_explanation", "save_explanation_draft"):
        with pytest.raises(McpRefused):
            FinanceMcpServer._authorize_context(None, grant, service, tool,
                                                {"context_id": granted, "parent_id": revision.parent["id"]})


# --- completion receipts -------------------------------------------------------------------------------------------


def test_a_session_lists_the_receipts_of_the_drafts_it_may_read_and_nothing_else(revision, capsys):
    manager = FinanceStore(revision.task)
    hidden = manager.save_explanation_draft({"body": "薪酬说明。", "run_ids": [revision.rh["id"]]})
    shown = manager.save_explanation_draft({"body": "收入说明。", "run_ids": [revision.ra["id"]]})
    code, state = _cli(capsys, revision.var, "analysis-state")
    assert code == 0
    assert [receipt["draft_id"] for receipt in state["completions"]] == [shown["id"]]
    assert _shows(state["completions"], [hidden["id"], hidden["completion"]["id"], *revision.hidden]) == []
    stored = revision.analysis._get("completions", shown["completion"]["id"])
    assert state["completions"][0] == {key: value for key, value in stored.items() if key != "_integrity_hash"}
    # A receipt of the revision whose parent the session may not read: the draft reads with no parent, the receipt
    # was judged with one, so it is not the session's to read.
    revised = manager.save_explanation_draft({"parent_id": revision.parent["id"], "body": "收入说明（再修订）。",
                                              "run_ids": [revision.ra["id"]]})
    code, state = _cli(capsys, revision.var, "analysis-state")
    assert revised["id"] in [draft["id"] for draft in state["drafts"]]
    assert revised["id"] not in [receipt["draft_id"] for receipt in state["completions"]]
    # The manager lists every receipt as stored.
    code, everything = _cli(capsys, revision.var, "analysis-state", session=None, task=revision.task.id)
    assert everything["completions"] == revision.analysis._list("completions")


def _chain(tmp_path, hidden_saves: int):
    task = TaskStore(tmp_path / f"var{hidden_saves}").create(title="修补次数")
    analysis = AnalysisStore(task)
    scope = {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元", "scenario": "actual"}

    def rows(amounts):
        return [{**scope, "management_account": account, "amount": amount, "source_row": index}
                for index, (account, amount) in enumerate(amounts, 1)]

    a = analysis.add_dataset(_ledger(tmp_path / f"a{hidden_saves}.json", rows([("revenue", "120"), ("cost", "70")])), name="A")["id"]
    task.record_session("sess", role="analysis")
    x = analysis.add_dataset(_ledger(tmp_path / f"x{hidden_saves}.json", rows([("revenue", "777")])), name="X")["id"]
    task.record_session("wide", role="analysis")
    sess = FinanceStore(task, snapshot_ids=[a], session_id="sess")
    wide = FinanceStore(task, snapshot_ids=[a, x], session_id="wide")
    sess.analysis_requirements_save({"question": "A 表控制数", "scope": {k: v for k, v in scope.items() if k != "scenario"},
                                     "bindings": {"ledger": a},
                                     "items": [{"id": "controls", "metric": "control_totals", "label": "控制数"}]})
    context = wide.save_context({"bindings": {"ledger": a, "extra": x}, "scopes": {"ledger": scope, "extra": scope}})
    run = wide.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})
    for index in range(hidden_saves):
        wide.save_explanation_draft({"body": f"第{index}稿，请查看计算依据。", "run_ids": [run["id"]]})
    return sess, wide, run


def test_drafts_a_session_may_not_read_spend_none_of_its_repairs(tmp_path):
    receipts = [_chain(tmp_path, hidden)[0].save_explanation_draft({"body": "请查看计算依据。"})["completion"]
                for hidden in (0, 2)]
    assert [(receipt["repair_attempts"], receipt["status"], receipt["repair_allowed"]) for receipt in receipts] == [
        (0, "repair_available", True), (0, "repair_available", True)]
    sess, wide, _run = _chain(tmp_path / "own", 0)
    attempts = [sess.save_explanation_draft({"body": f"第{index}稿。"})["completion"] for index in range(3)]
    assert [receipt["repair_attempts"] for receipt in attempts] == [0, 1, 2]
    assert attempts[-1]["stop_reason"] in {"no_progress", "repair_budget_exhausted"}
    # The wider session reads every draft it may read, the narrower one's included.
    assert wide.save_explanation_draft({"body": "宽口径。"})["completion"]["repair_attempts"] == 2


def test_a_session_lists_only_the_requirements_and_evidence_checks_it_may_read(tmp_path, capsys):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="清单")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(tmp_path / "a.csv", [("revenue", "2026-09", "O1", "1", "CNY", "元")]), name="A")["id"]
    task.record_session("sess", role="analysis")
    scope = {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元", "scenario": "actual"}
    x = analysis.add_dataset(_ledger(tmp_path / "x.json", [{**scope, "management_account": "revenue", "amount": "777",
                                                             "source_row": 1}]), name="X")["id"]
    manager = FinanceStore(task)
    context = manager.save_context({"bindings": {"ledger": x}, "scopes": {"ledger": scope}})
    manager.analysis_requirements_save({"question": "机密问题", "bindings": {"ledger": x},
                                        "items": [{"id": "rev", "metric": "revenue", "label": "机密收入"}]})
    run = manager.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})
    manager.drilldown_fact({"run_id": run["id"], "row": 0, "column": "amount"})
    code, state = _cli(capsys, var, "analysis-state")
    assert code == 0
    assert state["requirements"] == [] and state["evidence_checks"] == []
    assert _shows(state, [x, run["id"], "机密"]) == []
    code, everything = _cli(capsys, var, "analysis-state", session=None, task=task.id)
    assert len(everything["requirements"]) == 1 and len(everything["evidence_checks"]) == 1


# --- the requirements check ----------------------------------------------------------------------------------------


def _requirement_world(tmp_path):
    """R1 binds D1, inside the session; the manager runs control totals on D1 and a file D2 outside it."""
    var = tmp_path / "var"
    task = TaskStore(var).create(title="要求")
    analysis = AnalysisStore(task)
    manager = FinanceStore(task)
    d1 = analysis.add_dataset(_ledger(tmp_path / "gl.json", [
        {"account_code": "6001", "management_account": "revenue", "amount": 100, "period": "2026-09",
         "organization": "O1", "currency": "CNY"}]), name="gl")["id"]
    requirement = manager.analysis_requirements_save({
        "question": "九月控制合计", "scope": {"period": "2026-09", "organization": "O1", "currency": "CNY"},
        "bindings": {"gl": d1}, "items": [{"id": "ct", "metric": "control_totals", "requires_drilldown": True}]})
    task.record_session("sess", role="analysis")
    d2 = analysis.add_dataset(_ledger(tmp_path / "deal.json", [
        {"account_code": "9999", "management_account": "acquisition_payout", "amount": 7777777, "period": "2026-07",
         "organization": "SECRET-SUBSIDIARY", "currency": "USD"}]), name="并购")["id"]
    context = manager.save_context({"bindings": {"gl": d1, "hidden": d2}, "scopes": {
        "gl": {"organization": "O1", "currency": "CNY", "period": "2026-09"},
        "hidden": {"organization": "SECRET-SUBSIDIARY", "currency": "USD", "period": "2026-07"}}})
    hidden = manager.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})
    session = FinanceStore(task, snapshot_ids=[d1], session_id="sess")
    return SimpleNamespace(var=var, task=task, analysis=analysis, manager=manager, session=session, d1=d1, d2=d2,
                           requirement=requirement, run=hidden, hidden=[hidden["id"], d2, "SECRET-SUBSIDIARY"])


def test_a_run_on_files_beyond_the_requirement_is_never_named(tmp_path):
    world = _requirement_world(tmp_path)
    for store in (world.session, world.manager):
        saved = store.save_explanation_draft({"body": "控制合计待核。"})
        assert _shows(saved, world.hidden) == []
        assert "engine_runs" not in saved["explanation_check"]["requirements"]["items"][0]
        assert _shows(store.validate_explanation({"body": "控制合计待核。"}), world.hidden) == []


@pytest.mark.parametrize("with_hidden_run", [False, True])
def test_a_run_on_files_beyond_the_requirement_sets_no_bar_for_a_result_set(tmp_path, with_hidden_run):
    task = TaskStore(tmp_path / "var").create(title="门槛")
    analysis = AnalysisStore(task)
    manager = FinanceStore(task)
    row = {"account_code": "6001", "management_account": "revenue", "amount": 100, "period": "2026-09",
           "organization": "O1", "currency": "CNY"}
    d1 = analysis.add_dataset(_ledger(tmp_path / "gl.json", [row]), name="gl")["id"]
    manager.analysis_requirements_save({"question": "九月控制合计", "scope": {"period": "2026-09", "organization": "O1",
                                                                         "currency": "CNY"},
                                        "bindings": {"gl": d1}, "items": [{"id": "ct", "metric": "control_totals"}]})
    task.record_session("sess", role="analysis")
    d2 = analysis.add_dataset(_ledger(tmp_path / "x.json", [{**row, "account_code": "6601", "management_account": "expense",
                                                              "amount": 50}]), name="X")["id"]
    if with_hidden_run:
        context = manager.save_context({"bindings": {"gl": d1, "hidden": d2}})
        manager.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})
    session = FinanceStore(task, snapshot_ids=[d1], session_id="sess")
    own = session.save_context({"bindings": {"gl": d1}})
    run = session.run_metric({"context_id": own["id"], "metric": {"kind": "control_totals"}})
    rows = run["result"]["rows"]
    for index in range(len(rows)):
        session.drilldown_fact({"run_id": run["id"], "row": index, "column": "amount"})
    facts = session.prepare_explanation({"run_ids": [run["id"]]})["facts"]
    saved = session.save_explanation_draft({
        "body": "控制合计见附表。", "run_ids": [run["id"]], "fact_ids": [fact["id"] for fact in facts],
        "claims": [{"basis": "calculation", "run_id": run["id"], "row": index, "column": "amount", "value": item["amount"]}
                   for index, item in enumerate(rows)]})
    item = saved["explanation_check"]["requirements"]["items"][0]
    assert (item["status"], saved["explanation_check"]["requirements"]["coverage"]["status"]) == ("answered", "pass")


def test_a_session_cannot_check_a_draft_against_requirements_it_may_not_read(tmp_path, capsys):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="当前要求")
    analysis = AnalysisStore(task)
    d1 = analysis.add_dataset(_csv(tmp_path / "a.csv", [("revenue", "2026-08", "O1", "100", "CNY", "元")]), name="总账")["id"]
    task.record_session("sess", role="analysis")
    d2 = analysis.add_dataset(_csv(tmp_path / "h.csv", [("falcon", "2026-08", "O1", "999", "CNY", "元")]), name="薪酬")["id"]
    requirement = FinanceStore(task).analysis_requirements_save({
        "question": "Falcon 项目", "scope": {"period": "2026-08"}, "bindings": {"payroll": d2},
        "items": [{"id": "falcon", "metric": "revenue", "label": "Falcon 收入"}]})
    before = len(analysis._list("drafts"))
    spec = {"title": "说明", "body": "收入 100。", "claims": [{"basis": "source_fact", "dataset_id": d1, "text": "收入 100"}]}
    code, error = _cli(capsys, var, "analysis-draft", "--spec", json.dumps(spec, ensure_ascii=False))
    assert code != 0 and _shows(error, [d2, requirement["id"], "Falcon"]) == []
    session = FinanceStore(task, snapshot_ids=[d1], session_id="sess")
    with pytest.raises(FoundryError):
        session.report_template_apply({"template_id": "management-brief-v1"})
    assert len(analysis._list("drafts")) == before
    with pytest.raises(FoundryError):
        session.validate_explanation({"body": "收入 100。", "requirements_id": requirement["id"]})


def test_a_session_neither_lists_nor_reads_a_draft_checked_against_requirements_it_may_not_read(tmp_path, capsys):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="修订后的要求")
    analysis = AnalysisStore(task)
    manager = FinanceStore(task)
    d1 = analysis.add_dataset(_csv(tmp_path / "a.csv", [("revenue", "2026-08", "O1", "100", "CNY", "元")]), name="总账")["id"]
    manager.analysis_requirements_save({"question": "收入", "scope": {"period": "2026-08"}, "bindings": {"gl": d1},
                                        "items": [{"id": "rev", "metric": "revenue", "label": "收入"}]})
    task.record_session("sess", role="analysis")
    first = analysis.save_draft({"title": "收入", "body": "收入 100。"})
    d2 = analysis.add_dataset(_csv(tmp_path / "h.csv", [("falcon", "2026-08", "O1", "999", "CNY", "元")]), name="薪酬")["id"]
    hidden = manager.analysis_requirements_save({"question": "Falcon 项目", "scope": {"period": "2026-08"},
                                                 "parent_id": first["requirements_id"], "change_reason": "换项目",
                                                 "bindings": {"payroll": d2},
                                                 "items": [{"id": "falcon", "metric": "revenue", "label": "Falcon 收入"}]})
    revised = analysis.save_draft({"parent_id": first["id"], "body": "收入 100（修订）。"})
    assert revised["requirements_id"] == first["requirements_id"] != hidden["id"]
    assert revised["explanation_check"]["requirements"]["requirements_id"] == hidden["id"]
    code, state = _cli(capsys, var, "analysis-state")
    assert [draft["id"] for draft in state["drafts"]] == [first["id"]]
    assert _shows(state, [d2, hidden["id"], "Falcon"]) == []
    for command in (("report-draft-read", "--draft", revised["id"]),
                    ("report-projection-read", "--draft", revised["id"], "--mode", "audit")):
        assert _cli(capsys, var, *command)[0] != 0
    assert _cli(capsys, var, "report-draft-read", "--draft", revised["id"], session=None, task=task.id)[0] == 0


def test_a_session_reads_a_draft_checked_before_policy_13_without_runs_it_may_not_read(tmp_path, monkeypatch, capsys):
    from foundry import finance_completion, finance_requirements

    world = _requirement_world(tmp_path)
    # What policy 12 stored: a requirement read every run on its files, one on other files too.
    with monkeypatch.context() as old:
        old.setattr(finance_requirements, "_within_files", lambda files, bindings: True)
        old.setattr(finance_completion, "COMPLETION_POLICY_VERSION", 12)
        saved = world.manager.save_explanation_draft({"body": "控制合计待核。"})
    assert saved["check_policy_version"] == 12
    stored = world.analysis.get_draft(saved["id"])
    assert world.run["id"] in json.dumps(stored["explanation_check"]["requirements"])
    code, state = _cli(capsys, world.var, "analysis-state")
    assert code == 0
    [draft] = [draft for draft in state["drafts"] if draft["id"] == saved["id"]]
    assert _shows(draft, world.hidden) == []
    for key in ("explanation_check", "quality"):
        item = draft[key]["requirements"]["items"][0]
        assert item["status"] == stored[key]["requirements"]["items"][0]["status"]
        assert "engine_runs" not in item
        unanswered = [issue for issue in draft[key]["issues"] if issue["code"] == "requirement_unanswered"]
        assert unanswered and not [fixup for issue in unanswered for fixup in issue.get("fixups") or []
                                   if fixup["code"] == "engine_run_does_not_cover_requirement"]
    # Its receipt names the run: the session reads only the verdict.
    [receipt] = [receipt for receipt in state["completions"] if receipt["draft_id"] == saved["id"]]
    assert _shows(receipt, world.hidden) == []
    assert receipt["status"] == saved["completion"]["status"]
    assert not any("message" in action or "fixups" in action for action in receipt["actions"])
    assert "input_key" not in receipt and "issue_fingerprint" not in receipt
    code, managed = _cli(capsys, world.var, "report-draft-read", "--draft", saved["id"], session=None, task=world.task.id)
    assert world.run["id"] in json.dumps(managed["explanation_check"]["requirements"])


# --- month close and controls ---------------------------------------------------------------------------------------


BROKEN = [3525, 5355, 6930, 7020, 5400, 5550]


def _close_world(root: Path, hidden: str | None, _packs: dict[str, Path]):
    task = TaskStore(root / "var").create(title="月结")
    analysis = AnalysisStore(task)
    manager = FinanceStore(task)
    scope = {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元"}

    def pnl(name, amounts):
        return _ledger(root / name, [{"account_code": code, "management_account": account, "amount": amount, "period": "2026-09"}
                                     for code, account, amount in zip(("6001", "6401", "6601"), ("revenue", "cost", "expense"), amounts)])

    bindings = {alias: analysis.add_dataset(pnl(f"{alias}.json", amounts), name=alias)["id"]
                for alias, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15]))}
    context = manager.save_context({"bindings": bindings, "scopes": {alias: {**scope, "scenario": alias} for alias in bindings}})
    manager.analysis_requirements_save({"context_id": context["id"], "question": "解释利润",
                                        "items": [{"id": "profit", "metric": "profit", "requires_drilldown": True}]})
    task.record_session("sess", role="analysis")
    task.update_session_context("sess", snapshot_ids=sorted(bindings.values()))
    session = FinanceStore(task, snapshot_ids=sorted(bindings.values()), session_id="sess")
    run = session.explain_variance({"context_id": context["id"]})
    session.save_explanation_draft({"body": "请查看计算依据。", "run_ids": [run["id"]]})
    if hidden == "newer_draft":
        other = analysis.add_dataset(pnl("other.json", [1, 2, 3]), name="other")
        analysis.save_draft({"title": "其他公司", "body": "收入 1。",
                             "claims": [{"basis": "source_fact", "dataset_id": other["id"], "text": "收入 1"}]})
    elif hidden == "replacement_upload":
        analysis.add_dataset(pnl("actual-v2.json", [121, 70, 20]), name="actual")
    return task, root / "var"


def _packs(root: Path) -> dict[str, Path]:
    """The workbooks every world adds, written once: a workbook's bytes carry the time it was written."""
    root.mkdir(parents=True, exist_ok=True)
    return {"ar": _ar_pack(root / "ar.xlsx", provisions=BROKEN, total=22125),
            "other": _ar_pack(root / "other.xlsx", provisions=BROKEN, total=22000),
            "v2": _ar_pack(root / "ar-v2.xlsx", provisions=BROKEN, total=33780)}


def _control_world(root: Path, hidden: str | None, packs: dict[str, Path]):
    task = TaskStore(root / "var").create(title="勾稽")
    analysis = AnalysisStore(task)
    manager = FinanceStore(task, actor="manager")
    close = analysis.add_dataset(packs["ar"], name="月结")
    control = {"kind": "subtotal", "label": "坏账分项", "left": _side(close, "08·AR", "D5:D10"), "right": _side(close, "08·AR", "D11")}
    manager.finance_controls_save({"confirm": True, "control": control})
    task.record_session("sess", role="analysis")
    task.update_session_context("sess", snapshot_ids=[close["id"]])
    if hidden == "co_run":
        other = analysis.add_dataset(packs["other"], name="其他公司")
        manager.finance_controls_save({"confirm": True, "control": {
            **control, "label": "其他分项", "left": _side(other, "08·AR", "D5:D10"), "right": _side(other, "08·AR", "D11")}})
    if hidden == "upload_before_run":
        analysis.add_dataset(packs["v2"], name="月结")
    manager.finance_controls_run({})
    if hidden == "upload_after_run":
        analysis.add_dataset(packs["v2"], name="月结")
    return task, root / "var"


@pytest.mark.parametrize("build, hidden", [
    (_close_world, "newer_draft"),
    (_close_world, "replacement_upload"),
    (_control_world, "co_run"),
    (_control_world, "upload_before_run"),
    (_control_world, "upload_after_run"),
])
def test_records_outside_a_session_change_nothing_in_its_month_close(tmp_path, capsys, build, hidden):
    packs = _packs(tmp_path / "packs")
    worlds = [build(tmp_path / f"world{index}", which, packs) for index, which in enumerate((None, hidden))]
    for command in (("finance-close-status",), ("finance-controls-list", "--spec", "{}")):
        read = [_cli(capsys, var, *command) for _task, var in worlds]
        assert [code for code, _ in read] == [0, 0]
        assert _normalized(read[0][1]) == _normalized(read[1][1])
    # The manager reads the newer records.
    managed = [_cli(capsys, var, "finance-close-status", session=None, task=task.id)[1] for task, var in worlds]
    assert _normalized(managed[0]) != _normalized(managed[1])


def test_a_session_runs_its_control_by_the_files_it_may_read(tmp_path):
    packs = _packs(tmp_path / "packs")
    task, _var = _control_world(tmp_path, None, packs)
    analysis = AnalysisStore(task)
    [held] = analysis.state()["datasets"]
    analysis.add_dataset(packs["v2"], name="月结")
    session = FinanceStore(task, snapshot_ids=[held["id"]], session_id="sess", actor="assistant")
    run = session.finance_controls_run({})
    assert [result["status"] for result in run["results"]] == ["break"]
    assert [row["result"]["status"] for row in FinanceStore(task).finance_controls_list({})["controls"]] == ["stale"]


def test_superseded_snapshots_counts_only_the_replacements_a_reader_may_read(tmp_path):
    from foundry.finance_controls import superseded_snapshots

    task = TaskStore(tmp_path / "var").create(title="新版本")
    analysis = AnalysisStore(task)
    first = analysis.add_dataset(_csv(tmp_path / "v1.csv", [("revenue", "2026-08", "O1", "1", "CNY", "元")]), name="总账")
    second = analysis.add_dataset(_csv(tmp_path / "v2.csv", [("revenue", "2026-08", "O1", "2", "CNY", "元")]), name="总账")
    third = analysis.add_dataset(_csv(tmp_path / "v3.csv", [("revenue", "2026-08", "O1", "3", "CNY", "元")]), name="总账")
    assert superseded_snapshots(task) == {first["id"], second["id"]}
    assert superseded_snapshots(task, allowed={first["id"], second["id"]}) == {first["id"]}
    assert superseded_snapshots(task, allowed={first["id"], third["id"]}) == {first["id"]}
    assert superseded_snapshots(task, allowed={first["id"]}) == set()


# --- export registration ----------------------------------------------------------------------------------------------


def test_only_the_desktop_registers_an_export_and_only_of_the_projection_it_read(revision, capsys):
    path = revision.var.parent / "report.html"
    path.write_text("<!doctype html><h1>收入</h1>", encoding="utf-8")
    projection = revision.analysis.projection_for_draft(revision.child["id"], "management")
    command = ("report-export-register", "--draft", revision.child["id"], "--format", "html", "--path", str(path),
               "--mode", "management", "--projection-hash", projection["projection_hash"])
    code, error = _cli(capsys, revision.var, *command)
    assert code != 0 and "does not take a session" in error
    with pytest.raises(FoundryError, match="projection_hash"):
        revision.analysis.register_report_export(revision.child["id"], "html", path, content_mode="management",
                                                 projection_hash="0" * 64)
    code, receipt = _cli(capsys, revision.var, *command, session=None, task=revision.task.id)
    assert code == 0 and receipt["projection_hash"] == projection["projection_hash"]
