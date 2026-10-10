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

from foundry.analysis import PARENT_UNAVAILABLE, AnalysisStore, _hash
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
    """Two worlds draw different ids and clocks: number the ids by first appearance and blank the clocks. Keys stay
    in the order they were read."""
    text = re.sub(r'"_integrity_hash": "[0-9a-f]{64}"', '"_integrity_hash": "<hash>"',
                  json.dumps(value, ensure_ascii=False))
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
    stored = revision.analysis.get_draft(revision.child["id"])
    # It wrote its own text, so it rests on its own files only; the record of that is no part of what anyone reads.
    assert stored["inherited_fields"] == []
    assert managed == {key: value for key, value in stored.items() if key != "inherited_fields"}
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


def test_a_context_grant_answers_a_hidden_parent_as_an_unknown_one(revision):
    from foundry.finance_mcp import FinanceMcpServer, McpRefused

    service = FinanceStore(revision.task, snapshot_ids=[revision.a["id"]], session_id="sess")
    granted = "0" * 32
    grant = {"snapshot_ids": [revision.a["id"]], "context_ids": [granted]}
    FinanceMcpServer._authorize_context(None, grant, service, "validate_explanation", {"context_id": granted})
    # A parent outside the grant with no run says nothing a parent with runs or no parent at all would not.
    runless = revision.analysis.save_draft({"title": "无运行", "body": "薪酬说明。", "claims": [
        {"basis": "source_fact", "dataset_id": revision.h["id"], "text": "薪酬"}]})
    for tool in ("validate_explanation", "save_explanation_draft"):
        errors = []
        for parent_id in (revision.parent["id"], runless["id"], "f" * 32):
            with pytest.raises(FoundryError) as refused:
                FinanceMcpServer._authorize_context(None, grant, service, tool, {"context_id": granted, "parent_id": parent_id})
            assert not isinstance(refused.value, McpRefused)
            errors.append(str(refused.value))
        assert set(errors) == {PARENT_UNAVAILABLE}
        # A parent the grant may read is held to the grant's contexts: its run is in none of them.
        with pytest.raises(McpRefused):
            FinanceMcpServer._authorize_context(None, grant, service, tool,
                                                {"context_id": granted, "parent_id": revision.child["id"]})


def _hidden_metric_run(revision, manager):
    """A finance run on two ledgers outside the session, whose generated appendix shows 987,654."""
    hidden = {}
    for scenario, amounts in (("actual", [987654, 70, 20]), ("budget", [100, 60, 15])):
        hidden[scenario] = revision.analysis.add_dataset(_ledger(revision.var.parent / f"{scenario}.json", [
            {"account_code": code, "management_account": account, "amount": amount}
            for code, account, amount in zip(("6001", "6401", "6601"), ("revenue", "cost", "expense"), amounts)]),
            name=scenario)["id"]
    context = manager.save_context({"bindings": hidden, "scopes": {alias: {
        "ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元", "scenario": alias}
        for alias in hidden}})
    return manager.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})


def _document(text: str) -> dict:
    return {"schema_version": 1, "template_version": "annual-v1",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def _unread(revision, capsys, draft_id: str) -> None:
    """The session neither lists the draft nor reads it, and nothing it lists shows the parent's secrets."""
    code, state = _cli(capsys, revision.var, "analysis-state")
    assert code == 0 and draft_id not in [draft["id"] for draft in state["drafts"]]
    assert _shows(state, ["987,654", SECRET]) == []
    assert _cli(capsys, revision.var, "report-draft-read", "--draft", draft_id)[0] != 0


def test_a_revision_that_took_its_parent_s_text_rests_on_the_parent(revision, capsys):
    manager = FinanceStore(revision.task)
    run = _hidden_metric_run(revision, manager)
    parent = manager.save_explanation_draft({"title": f"薪酬 {SECRET} 专项", "body": "控制合计见计算依据。",
                                             "run_ids": [run["id"]]})
    assert "987,654" in parent["evidence_appendix"] and parent["evidence_appendix_meta"]

    def cli_revision(**fields):
        spec = {"parent_id": parent["id"], "title": "C", "body": "收入说明（修订）。", "run_ids": [revision.ra["id"]],
                "claims": [], **fields}
        code, child = _cli(capsys, revision.var, "analysis-draft", "--spec", json.dumps(spec, ensure_ascii=False),
                           session=None, task=revision.task.id)
        assert code == 0
        return child

    # Edited in the desktop with a new body and runs: the generated appendix stays the parent's.
    kept = cli_revision()
    assert kept["evidence_appendix"] == parent["evidence_appendix"]
    _unread(revision, capsys, kept["id"])
    # An emptied appendix whose digest stays the parent's.
    meta = cli_revision(evidence_appendix="")
    assert meta["evidence_appendix_meta"] == parent["evidence_appendix_meta"]
    _unread(revision, capsys, meta["id"])
    # Saved through the finance tools: the parent's title, or its prose (as text or as a document), taken over.
    titled = manager.save_explanation_draft({"parent_id": parent["id"], "body": "收入说明（修订）。",
                                             "run_ids": [revision.ra["id"]], "claims": []})
    assert titled["title"] == parent["title"]
    _unread(revision, capsys, titled["id"])
    prose = manager.save_explanation_draft({"parent_id": parent["id"], "title": "收入", "run_ids": [revision.ra["id"]],
                                            "claims": []})
    assert prose["body"].startswith("控制合计见计算依据。") and prose["evidence_appendix"] != parent["evidence_appendix"]
    _unread(revision, capsys, prose["id"])
    documented = manager.save_explanation_draft({"title": "薪酬", "document": _document(f"薪酬 {SECRET}。"),
                                                 "run_ids": [run["id"]]})
    from_document = manager.save_explanation_draft({"parent_id": documented["id"], "title": "收入",
                                                    "run_ids": [revision.ra["id"]], "claims": []})
    assert SECRET in from_document["body"]
    _unread(revision, capsys, from_document["id"])
    code, cli_document = _cli(capsys, revision.var, "analysis-draft", "--spec", json.dumps(
        {"parent_id": documented["id"], "title": "收入", "run_ids": [revision.ra["id"]], "claims": [],
         "evidence_appendix": "", "evidence_appendix_meta": {}, "source_read_failures": []}, ensure_ascii=False),
        session=None, task=revision.task.id)
    assert code == 0 and SECRET in cli_document["body"]
    _unread(revision, capsys, cli_document["id"])
    # Revisions with text of their own read with no parent, whichever way they were saved; a default title is one a
    # draft saved with no parent carries too.
    own = cli_revision(evidence_appendix="", evidence_appendix_meta={})
    rewritten = manager.save_explanation_draft({"parent_id": parent["id"], "title": "收入", "body": "收入说明（修订）。",
                                                "run_ids": [revision.ra["id"]], "claims": []})
    untitled = manager.save_explanation_draft({"body": "控制合计见计算依据。", "run_ids": [run["id"]]})
    retitled = manager.save_explanation_draft({"parent_id": untitled["id"], "body": "收入说明（修订）。",
                                               "run_ids": [revision.ra["id"]], "claims": []})
    assert retitled["title"] == untitled["title"] == "分析报告"
    for draft in (own, rewritten, retitled):
        assert revision.analysis.get_draft(draft["id"])["inherited_fields"] == []
        code, read = _cli(capsys, revision.var, "report-draft-read", "--draft", draft["id"])
        assert code == 0 and read["parent_id"] is None and _shows(read, ["987,654", SECRET]) == []
        assert "inherited_fields" not in read


def _workbook(path: Path) -> Path:
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "差异"
    book.active["A1"], book.active["A2"] = 100, "收入均已入账。"
    book.save(path)
    book.close()
    return path


@pytest.mark.parametrize("taken", ["materiality", "fact_ids", "evidence_recipes", "consistency"])
def test_a_revision_that_took_its_parent_s_settings_rests_on_the_parent(revision, capsys, taken):
    """Recipes, consistency rules and sources, materiality and facts are written by the parent's author as well."""
    book = revision.analysis.add_dataset(_workbook(revision.var.parent / "w.xlsx"), name="差异",
                                         metadata={"mode": "workbook"})
    revision.task.update_session_context("sess", snapshot_ids=[book["id"]])
    source = {"dataset_id": book["id"], "source_hash": book["source_hash"], "sheet": "差异"}
    fields = {
        "materiality": {"materiality": {"absolute": SECRET}},
        "fact_ids": {"fact_ids": [{"note": f"薪酬 {SECRET}"}]},
        "evidence_recipes": {"evidence_recipes": [{
            "id": "direct", "kind": "direct", **source, "range": "A1", "label": f"薪酬 {SECRET}",
            "claim": {"run_id": revision.ra["id"], "row": 0, "column": "amount"}}]},
        "consistency": {
            "consistency_sources": {"n": {"kind": "number", **source, "range": "A1", "label": f"源 {SECRET}"},
                                    "t": {"kind": "text", **source, "range": "A2"}},
            "consistency_rules": [{"id": "r", "kind": "all_absolute_exceed", "label": f"规则 {SECRET}", "threshold": "10",
                                   "asserted_result": True, "assertion_source_id": "t",
                                   "values": [{"id": "n", "source_id": "n"}]}]},
    }[taken]
    parent = revision.analysis.save_draft({"title": "P", "body": "薪酬。", "run_ids": [revision.rh["id"]], **fields})
    own = {"title": "C", "body": "收入说明（修订）。", "run_ids": [revision.ra["id"]], "claims": [], "limitations": [],
           "evidence_appendix": "", "evidence_appendix_meta": {}, "source_read_failures": [], "materiality": {},
           "fact_ids": [], "evidence_recipes": [], "consistency_rules": [], "consistency_sources": {}}

    def revise(spec):
        code, child = _cli(capsys, revision.var, "analysis-draft", "--spec", json.dumps(
            {"parent_id": parent["id"], **spec}, ensure_ascii=False), session=None, task=revision.task.id)
        assert code == 0
        return child

    took = revise({key: value for key, value in own.items() if key not in fields})
    assert SECRET in json.dumps(took, ensure_ascii=False)
    _unread(revision, capsys, took["id"])
    alone = revise(own)
    code, read = _cli(capsys, revision.var, "report-draft-read", "--draft", alone["id"])
    assert code == 0 and read["parent_id"] is None and SECRET not in json.dumps(read, ensure_ascii=False)


def test_a_revision_whose_appendix_matches_its_parent_s_by_its_own_runs_reads_alone(revision, capsys):
    """An appendix composed again from the revision's own runs is its own, even when it reads as the parent's did."""
    manager = FinanceStore(revision.task)
    parent = manager.save_explanation_draft({"title": "收入", "body": "收入说明。", "run_ids": [revision.ra["id"]],
                                             "claims": [{"basis": "source_fact", "dataset_id": revision.h["id"]}]})
    child = manager.save_explanation_draft({"parent_id": parent["id"], "title": "收入（修订）", "body": "收入说明（修订）。",
                                            "run_ids": [revision.ra["id"]], "claims": []})
    assert child["evidence_appendix"] == parent["evidence_appendix"]
    code, state = _cli(capsys, revision.var, "analysis-state")
    listed = [draft["id"] for draft in state["drafts"]]
    assert code == 0 and child["id"] in listed and parent["id"] not in listed
    code, read = _cli(capsys, revision.var, "report-draft-read", "--draft", child["id"])
    assert code == 0 and read["parent_id"] is None


def test_a_finance_revision_that_composed_its_own_claims_and_prose_reads_alone(revision, capsys):
    manager = FinanceStore(revision.task)
    ledger = revision.analysis.add_dataset(_ledger(revision.var.parent / "ledger.json", [
        {"account_code": code, "management_account": account, "amount": amount}
        for code, account, amount in (("6001", "revenue", 120), ("6401", "cost", 70))]), name="总账二")["id"]
    revision.task.update_session_context("sess", snapshot_ids=[ledger])
    context = manager.save_context({"bindings": {"actual": ledger}, "scopes": {"actual": {
        "ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元", "scenario": "actual"}}})
    run = manager.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})
    # The parent's claims are its run's generated ones, which the revision generates again.
    parent = manager.save_explanation_draft({"title": "P", "body": "说明。", "run_ids": [run["id"], revision.rh["id"]]})
    assert parent["claims"] and {claim["run_id"] for claim in parent["claims"]} == {run["id"]}
    claimed = manager.save_explanation_draft({"parent_id": parent["id"], "title": "C", "body": "说明（修订）。",
                                              "run_ids": [run["id"]]})
    # The parent's body was only its generated appendix: the revision keeps none of it.
    bare = manager.save_explanation_draft({"title": "P2", "body": "", "run_ids": [revision.rh["id"]]})
    unwritten = manager.save_explanation_draft({"parent_id": bare["id"], "title": "C2", "run_ids": [revision.ra["id"]],
                                                "claims": []})
    for draft in (claimed, unwritten):
        assert revision.analysis.get_draft(draft["id"])["inherited_fields"] == []
        code, read = _cli(capsys, revision.var, "report-draft-read", "--draft", draft["id"])
        assert code == 0 and read["parent_id"] is None and _shows(read, revision.hidden) == []


def _rewrite(analysis: AnalysisStore, kind: str, record_id: str, change) -> None:
    """Change a stored record as an older version of the app would have written it."""
    path = analysis._object_path(kind, record_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("_integrity_hash")
    change(record)
    record["_integrity_hash"] = _hash(record)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def test_a_revision_saved_before_revisions_recorded_their_parent_s_text_rests_on_the_parent(revision, capsys):
    assert _cli(capsys, revision.var, "report-draft-read", "--draft", revision.child["id"])[0] == 0
    _rewrite(revision.analysis, "drafts", revision.child["id"], lambda record: record.pop("inherited_fields"))
    # It cannot tell what it took from its parent, so a session that may not read the parent does not read it.
    code, state = _cli(capsys, revision.var, "analysis-state")
    assert code == 0 and state["drafts"] == []
    assert _cli(capsys, revision.var, "report-draft-read", "--draft", revision.child["id"])[0] != 0
    code, managed = _cli(capsys, revision.var, "report-draft-read", "--draft", revision.child["id"],
                         session=None, task=revision.task.id)
    assert code == 0 and managed == revision.analysis.get_draft(revision.child["id"])


def test_a_long_revision_chain_is_read_once_per_listing(revision, capsys, monkeypatch):
    analysis = revision.analysis
    draft = analysis.save_draft({"title": "收入", "body": "收入说明。", "run_ids": [revision.ra["id"]], "limitations": ["未经审计"]})
    for index in range(30):
        draft = analysis.save_draft({"parent_id": draft["id"], "body": f"收入说明（第 {index + 1} 版）。"})
    assert draft["inherited_fields"] == ["limitations", "title"]
    reads = []
    original = AnalysisStore.get_draft
    monkeypatch.setattr(AnalysisStore, "get_draft", lambda self, draft_id: reads.append(draft_id) or original(self, draft_id))
    code, state = _cli(capsys, revision.var, "analysis-state")
    assert code == 0 and len(state["drafts"]) == 32
    assert len(reads) <= 31
    # However deep the chain, it is walked, never recursed into.
    monkeypatch.setattr(AnalysisStore, "get_draft", original)
    from foundry.analysis import _new

    for _ in range(1500):
        record = _new(analysis.task, run_ids=[revision.ra["id"]], parent_id=draft["id"], inherited_fields=["body"])
        draft = analysis._write(analysis._object_path("drafts", record["id"]), record)
    assert analysis.draft_snapshots(draft) == {revision.a["id"]}
    assert analysis.draft_readable(draft, {revision.a["id"]})


def test_a_session_never_reads_a_revision_as_more_reviewed_than_it_was_saved(tmp_path, capsys):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="复核状态")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(tmp_path / "a.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")]), name="A")
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_csv(tmp_path / "h.csv", [("revenue", "2026-08", "集团", SECRET, "CNY", "元")]), name="H")

    def run_twice(dataset):
        analysis_id = analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": dataset["id"]}})["id"]
        analysis.run_analysis(analysis_id)
        return analysis.run_analysis(analysis_id)

    ra, rh = run_twice(a), run_twice(h)
    assert ra["reproducibility_status"] == "reproducible"

    def claim(run):
        return {"basis": "calculation", "run_id": run["id"], "row": 0, "column": "amount", "value": run["result"]["rows"][0]["amount"]}

    parent = analysis.save_draft({"title": "P", "body": f"收入 {SECRET} 元。", "run_ids": [rh["id"]], "claims": [claim(rh)],
                                  "review_status": "accepted"})
    # The editor sends the review it showed; the changed body was never reviewed, so the save resets it.
    child = analysis.save_draft({"title": "C", "parent_id": parent["id"], "body": "收入 100 元。", "run_ids": [ra["id"]],
                                 "claims": [claim(ra)], "review_status": "accepted"})
    assert (child["review_status"], child["reproducibility_status"]) == ("unreviewed", "unverified")
    code, shown = _cli(capsys, var, "report-draft-read", "--draft", child["id"])
    assert code == 0 and shown["parent_id"] is None
    assert _shows(shown, [parent["id"], rh["id"], h["id"], SECRET]) == []
    assert shown["review_status"] == child["review_status"]
    # Its reproducibility it reads as it would have saved it with no parent: by its one cited run, which reads reproducible.
    assert shown["reproducibility_status"] == "reproducible"
    for key in ("explanation_check", "quality"):
        assert shown[key]["status_dimensions"]["professional_review"]["status"] == "unreviewed"
    # A management projection, which an export is rendered from, reads the same review for the session as for the manager,
    # and the reproducibility each would have saved.
    command = ("report-projection-read", "--draft", child["id"], "--mode", "management")
    projections = [_cli(capsys, var, *command)[1], _cli(capsys, var, *command, session=None, task=task.id)[1]]
    assert projections[0]["review_status"] == projections[1]["review_status"] == "unreviewed"
    assert (projections[0]["reproducibility_status"], projections[1]["reproducibility_status"]) == ("reproducible", "unverified")


def _reproducible_world(root: Path, capsys, *, engine: str, parent: bool) -> dict:
    """The session may read A. The manager runs a calculation on A twice, so it reads reproducible, and saves C, with
    a body of its own, and S on it; with ``parent``, as revisions of P, which has S's body and cites a run on H, a file
    outside the session, too. What the session reads of C and S."""
    var = root / "var"
    task = TaskStore(var).create(title="复现")
    analysis = AnalysisStore(task)
    if engine == "sql":
        a = analysis.add_dataset(_csv(root / "a.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")]), name="A")
        analysis_id = analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": a["id"]}})["id"]
        run = [analysis.run_analysis(analysis_id) for _ in range(2)][-1]
    else:
        a = analysis.add_dataset(_ledger(root / "a.json", [{"account_code": "6001", "management_account": "revenue",
                                                             "amount": 100}]), name="A")
        manager = FinanceStore(task)
        context = manager.save_context({"bindings": {"actual": a["id"]}, "scopes": {"actual": {
            "ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元",
            "scenario": "actual"}}})
        run = [manager.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}}) for _ in range(2)][-1]
    task.record_session("sess", role="analysis")
    claims = [{"basis": "calculation", "run_id": run["id"], "row": 0, "column": "amount",
               "value": run["result"]["rows"][0]["amount"]}]
    spec = {"title": "收入", "run_ids": [run["id"]], "claims": claims}
    if parent:
        h = analysis.add_dataset(_csv(root / "h.csv", [("revenue", "2026-08", "集团", SECRET, "CNY", "元")]), name="H")
        rh = analysis.run_analysis(analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": h["id"]}})["id"])
        spec["parent_id"] = analysis.save_draft({**spec, "body": "收入 100 元。", "run_ids": [rh["id"], run["id"]]})["id"]
    drafts = [analysis.save_draft({**spec, "body": body}) for body in ("收入 100 元（修订）。", "收入 100 元。")]
    read = {"stored": [draft["reproducibility_status"] for draft in drafts]}
    keys = ("parent_id", "revision_comparison", "review_status", "reproducibility_status")
    code, state = _cli(capsys, var, "analysis-state")
    assert code == 0
    read["listed"] = [{key: draft[key] for key in keys} for draft in state["drafts"]]
    for draft in drafts:
        code, shown = _cli(capsys, var, "report-draft-read", "--draft", draft["id"])
        assert code == 0
        read.setdefault("read", []).append({key: shown[key] for key in keys})
        code, projection = _cli(capsys, var, "report-projection-read", "--draft", draft["id"], "--mode", "management")
        assert code == 0
        read.setdefault("projected", []).append(projection["reproducibility_status"])
    return read


@pytest.mark.parametrize("engine", ["sql", "finance"])
def test_a_session_reads_a_revision_s_reproducibility_as_saved_with_no_parent_it_may_not_read(tmp_path, capsys, engine):
    """C changed the body of a parent the session may not read and S kept it: the session reads both as it would have
    saved them with no parent, so that parent's body decides nothing. A finance run reads as stored to every reader."""
    hidden = _reproducible_world(tmp_path / "hidden", capsys, engine=engine, parent=True)
    alone = _reproducible_world(tmp_path / "alone", capsys, engine=engine, parent=False)
    # The manager saved C unverified only because it changed P's body.
    assert hidden.pop("stored") == ["unverified", "reproducible"]
    assert alone.pop("stored") == ["reproducible", "reproducible"]
    assert hidden == alone
    assert alone["projected"] == [row["reproducibility_status"] for row in alone["read"]] == ["reproducible"] * 2


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
    revised = manager.save_explanation_draft({"parent_id": revision.parent["id"], "title": "收入",
                                              "body": "收入说明（再修订）。", "run_ids": [revision.ra["id"]]})
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


def test_a_session_reads_a_repair_budget_spent_only_by_drafts_it_may_read(tmp_path, capsys):
    read = []
    for hidden in (0, 2):
        sess, wide, _run = _chain(tmp_path, hidden)
        shown = wide.save_explanation_draft({"body": "请查看计算依据。"})
        assert shown["completion"]["repair_attempts"] == hidden
        code, state = _cli(capsys, tmp_path / f"var{hidden}", "analysis-state")
        assert code == 0
        [listed] = [receipt for receipt in state["completions"] if receipt["draft_id"] == shown["id"]]
        # The same request again: the session is handed the receipt already filed, as it reads it.
        replayed = sess.save_explanation_draft({"body": "请查看计算依据。"})
        assert replayed["id"] == shown["id"]
        read.append([listed, replayed["completion"]])
    for receipts in read:
        assert [(receipt["repair_attempts"], receipt["status"], receipt["stop_reason"], receipt["repair_allowed"])
                for receipt in receipts] == [(0, "repair_available", None, True)] * 2


def test_a_session_s_completion_operation_goes_on_by_the_budget_its_own_drafts_spent(tmp_path, capsys):
    from foundry.finance_completion_operations import CompletionOperationStore

    settled = []
    for hidden in (0, 2):
        sess, wide, _run = _chain(tmp_path, hidden)
        operations = CompletionOperationStore(sess.task, "sess", sess.allowed)
        operation = operations.begin(f"request-{hidden}", policy={"max_repairs": 2})
        saved = sess.save_completion_draft(operation["id"], "call-1", {"body": "请查看计算依据。"})
        # Recovered by the manager after the session stopped: the operation settles on the session's reading too.
        stopped = operations.begin(f"stopped-{hidden}", policy={"max_repairs": 2})
        operations.reserve(stopped["id"], payload={"body": "恢复稿。"}, call_id="call-1")
        operations.stop(stopped["id"], "timeout")
        recovered = FinanceStore(sess.task).recover_completion_draft({"operation_id": stopped["id"], "revision": 1,
                                                                       "draft": {"body": "恢复稿。"}})
        for record in (saved["completion_operation"], operations.get(saved["completion_operation"]["id"]),
                       recovered["completion_operation"]):
            [revision] = record["revisions"]
            settled.append((hidden, revision["completion_status"], revision["completion_stop_reason"], revision["repair_allowed"]))
        # The receipt keeps what every earlier draft spent, as the manager and a reader of all of them read it.
        stored = sess.analysis._get("completions", saved["completion"]["id"])
        assert stored["repair_attempts"] == hidden
        code, state = _cli(capsys, tmp_path / f"var{hidden}", "analysis-state", session=None, task=sess.task.id)
        assert [receipt for receipt in state["completions"] if receipt["id"] == stored["id"]] == [stored]
        assert wide._readable_receipt(stored)["repair_attempts"] == hidden
        assert sess._readable_receipt(stored)["repair_attempts"] == 0
    assert [row[1:] for row in settled if row[0] == 2] == [row[1:] for row in settled if row[0] == 0]


def test_a_recovered_operation_settles_on_what_its_session_now_reads(tmp_path):
    from foundry.finance_completion_operations import CompletionOperationStore

    sess, wide, _run = _chain(tmp_path, 2)
    operations = CompletionOperationStore(sess.task, "sess", sess.allowed)
    stopped = operations.begin("stopped", policy={"max_repairs": 2})
    operations.reserve(stopped["id"], payload={"body": "恢复稿。"}, call_id="call-1")
    operations.stop(stopped["id"], "timeout")
    # The session was given the wider files after it began: it now reads the two drafts it could not.
    sess.task.update_session_context("sess", snapshot_ids=sorted(wide.allowed))
    recovered = FinanceStore(sess.task).recover_completion_draft({"operation_id": stopped["id"], "revision": 1,
                                                                   "draft": {"body": "恢复稿。"}})
    [revision] = recovered["completion_operation"]["revisions"]
    widened = FinanceStore(sess.task, snapshot_ids=sorted(wide.allowed), session_id="sess")
    read = widened._readable_receipt(sess.analysis._get("completions", revision["completion_id"]))
    assert (read["repair_attempts"], read["status"], read["stop_reason"], read["repair_allowed"]) == (
        2, "needs_review", "repair_budget_exhausted", False)
    assert (revision["completion_status"], revision["completion_stop_reason"], revision["repair_allowed"]) == (
        read["status"], read["stop_reason"], read["repair_allowed"])


@pytest.mark.parametrize("basis", ["source_fact", "professional_judgment"])
def test_a_session_cites_no_run_it_may_not_read_through_a_claim_of_any_basis(tmp_path, capsys, basis):
    from foundry.finance_completion_operations import CompletionOperationStore

    sess, _wide, run = _chain(tmp_path, 0)
    operations = CompletionOperationStore(sess.task, "sess", sess.allowed)
    stored = lambda: (len(sess.analysis._list("drafts")), len(sess.analysis._list("completions")))
    for run_id in (run["id"], "0" * 32):
        spec = {"body": "请查看计算依据。", "claims": [{"basis": basis, "run_id": run_id}]}
        before = stored()
        operation = operations.begin(f"request-{run_id}", policy={"max_repairs": 2})
        for call in (lambda: sess.save_completion_draft(operation["id"], "call-1", spec),
                     lambda: sess.save_explanation_draft(spec)):
            with pytest.raises(FoundryError) as refused:
                call()
            assert _shows(str(refused.value), ["777"]) == []
        assert _cli(capsys, tmp_path / "var0", "analysis-draft", "--spec", json.dumps(spec, ensure_ascii=False))[0] != 0
        assert stored() == before
        # Refused before anything was reserved: the operation goes on.
        saved = sess.save_completion_draft(operation["id"], "call-2", {"body": "请查看计算依据。"})
        [revision] = saved["completion_operation"]["revisions"]
        assert (revision["completion_id"], revision["completion_status"]) == (saved["completion"]["id"],
                                                                             saved["completion"]["status"])
        # The manager saves such a claim as before.
        assert FinanceStore(sess.task).save_explanation_draft(spec)["claims"]


@pytest.mark.parametrize("hidden", [0, 2])
def test_a_session_counts_its_repairs_over_the_drafts_it_may_read(tmp_path, capsys, hidden):
    sess, _wide, _run = _chain(tmp_path / "own", hidden)
    own = [sess.save_explanation_draft({"body": f"第{index}稿。"})["completion"] for index in range(3)]
    code, state = _cli(capsys, tmp_path / "own" / f"var{hidden}", "analysis-state")
    listed = {receipt["id"]: receipt for receipt in state["completions"]}
    expected = [(0, "repair_available", None, True), (1, "repair_available", None, True),
                (2, "needs_review", "repair_budget_exhausted", False)]
    for receipts in (own, [listed[receipt["id"]] for receipt in own]):
        assert [(receipt["repair_attempts"], receipt["status"], receipt["stop_reason"], receipt["repair_allowed"])
                for receipt in receipts] == expected
    # The same issues twice: the session stops for no progress, on its own receipts alone.
    sess, _wide, _run = _chain(tmp_path / "stall", hidden)
    stalled = [sess.save_explanation_draft({"body": body})["completion"] for body in ("收入说明甲。", "收入说明乙。")]
    assert [(receipt["repair_attempts"], receipt["status"], receipt["stop_reason"], receipt["repair_allowed"])
            for receipt in stalled] == [(0, "repair_available", None, True), (1, "needs_review", "no_progress", False)]


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


def _requirement_world(tmp_path, amount: str = "amount"):
    """R1 binds D1, inside the session; the manager runs control totals on D1 and a file D2 outside it."""
    var = tmp_path / "var"
    task = TaskStore(var).create(title="要求")
    analysis = AnalysisStore(task)
    manager = FinanceStore(task)
    d1 = analysis.add_dataset(_ledger(tmp_path / "gl.json", [
        {"account_code": "6001", "management_account": "revenue", amount: 100, "period": "2026-09",
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


@pytest.mark.parametrize("bound", [True, False])
def test_a_finance_context_on_more_files_opens_the_engine_path_as_before(tmp_path, bound):
    """Which evidence paths are open is read from every finance context on the requirement's files, one that binds
    more files too: a run on it answers the requirement once cited (check_requirements counts cited runs)."""
    task = TaskStore(tmp_path / "var").create(title="支撑")
    analysis, manager = AnalysisStore(task), FinanceStore(task)
    ids = {scenario: analysis.add_dataset(_ledger(tmp_path / f"{scenario}.json", [
        {"account_code": code, "management_account": account, "amount": amount}
        for code, account, amount in zip(("6001", "6401", "6601"), ("revenue", "cost", "expense"), amounts)]),
        name=scenario)["id"] for scenario, amounts in (("actual", [1000, 700, 200]), ("budget", [900, 600, 150]))}

    def save_requirements():
        return manager.analysis_requirements_save({
            "question": "九月收入利润", "scope": {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY"},
            "bindings": {"actual": ids["actual"]} if bound else {},
            "items": [{"id": "revenue", "metric": "revenue"}, {"id": "profit", "metric": "profit"}]})

    if not bound:
        save_requirements()  # as the desktop saves one before any finance context
    context = manager.save_context({"bindings": ids, "scopes": {alias: {
        "ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元", "scenario": alias}
        for alias in ids}})
    run = manager.explain_variance({"context_id": context["id"]})
    if bound:
        assert all(row["accepted_evidence"] == ["engine_closure"] for row in save_requirements()["support"]["items"])

    def items(spec):
        saved = manager.save_explanation_draft(spec)
        assert "finance_context_save" not in json.dumps(saved, ensure_ascii=False)
        return saved["explanation_check"]["requirements"]["items"]

    assert all([path["path"] for path in item["evidence_paths"]["accepted"]] == ["engine_closure"]
               for item in items({"body": "收入利润说明待补。"}))
    assert {item["status"] for item in items({"body": "收入利润见计算。", "run_ids": [run["id"]]})} == {"answered"}


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
    # Once the current version is one it may read, an older one it may not read is still refused by name.
    current = FinanceStore(task).analysis_requirements_save({
        "question": "收入", "scope": {"period": "2026-08"}, "bindings": {"gl": d1}, "parent_id": requirement["id"],
        "change_reason": "换回总账", "items": [{"id": "rev", "metric": "revenue", "label": "收入"}]})
    assert session.validate_explanation({"body": "收入 100。", "requirements_id": current["id"]})
    with pytest.raises(FoundryError) as refused:
        session.validate_explanation({"body": "收入 100。", "requirements_id": requirement["id"]})
    assert _shows(str(refused.value), [d2, requirement["id"], "Falcon"]) == []


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


def test_a_session_reads_the_verdict_of_a_receipt_whose_draft_checked_a_run_it_may_not_read(tmp_path, monkeypatch, capsys):
    from foundry import finance_completion, finance_requirements

    # The ledger's amount column is not mapped: the engine path is blocked, and only the item names the run.
    world = _requirement_world(tmp_path, amount="本期发生额")
    with monkeypatch.context() as old:
        old.setattr(finance_requirements, "_within_files", lambda files, bindings: True)
        old.setattr(finance_completion, "COMPLETION_POLICY_VERSION", 12)
        saved = world.manager.save_explanation_draft({"body": "控制合计待核。"})
    stored = world.analysis.get_draft(saved["id"])
    assert world.run["id"] in json.dumps(stored["explanation_check"]["requirements"])
    assert _shows(saved["completion"], world.hidden) == []
    code, state = _cli(capsys, world.var, "analysis-state")
    assert code == 0
    [receipt] = [receipt for receipt in state["completions"] if receipt["draft_id"] == saved["id"]]
    assert "input_key" not in receipt and "issue_fingerprint" not in receipt
    assert receipt["status"] == saved["completion"]["status"]


def test_a_session_cites_no_run_it_may_not_read_through_an_evidence_recipe(tmp_path, capsys):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="配方")
    analysis = AnalysisStore(task)
    pack = analysis.add_dataset(_ar_pack(tmp_path / "ar.xlsx", provisions=BROKEN, total=33780), name="月结")
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_csv(tmp_path / "h.csv", [("revenue", "2026-08", "集团", SECRET, "CNY", "元")]), name="薪酬")
    rh = analysis.run_analysis(analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": h["id"]}})["id"])
    recipe = {"id": "direct", "kind": "direct", "dataset_id": pack["id"], "source_hash": pack["source_hash"],
              "sheet": "08·AR", "range": "D11", "claim": {"run_id": rh["id"], "row": 0, "column": "amount"}}
    spec = {"body": "坏账合计。", "evidence_recipes": [recipe]}
    hidden = [h["id"], rh["id"], SECRET]
    # The recipe's result shows the cited run's value.
    assert SECRET in json.dumps(FinanceStore(task).validate_explanation(spec)["evidence_report"], ensure_ascii=False)
    session = FinanceStore(task, snapshot_ids=[pack["id"]], session_id="sess")
    from foundry.finance_completion_operations import CompletionOperationStore

    operations = CompletionOperationStore(task, "sess", session.allowed)
    operation = operations.begin("recipe", policy={"max_repairs": 0})
    before = len(analysis._list("drafts"))
    for call in (session.validate_explanation, session.save_explanation_draft,
                 lambda spec: session.prepare_explanation({**spec, "run_ids": [rh["id"]]}),
                 lambda spec: session.save_completion_draft(operation["id"], "call-1", spec)):
        with pytest.raises(FoundryError) as refused:
            call(spec)
        assert _shows(str(refused.value), hidden) == []
    # Refused before anything was reserved, so the operation has spent nothing.
    assert operations.get(operation["id"])["revisions"] == []
    code, error = _cli(capsys, var, "analysis-draft", "--spec", json.dumps(spec, ensure_ascii=False))
    assert code != 0 and _shows(error, hidden) == []
    assert len(analysis._list("drafts")) == before


def test_the_manager_reads_a_recipe_citing_a_run_that_does_not_read_as_an_issue(tmp_path, capsys):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="配方")
    pack = AnalysisStore(task).add_dataset(_ar_pack(tmp_path / "ar.xlsx", provisions=BROKEN, total=33780), name="月结")
    task.record_session("sess", role="analysis")
    recipe = {"id": "direct", "kind": "direct", "dataset_id": pack["id"], "source_hash": pack["source_hash"],
              "sheet": "08·AR", "range": "D11", "claim": {"run_id": "0" * 32, "row": 0, "column": "amount"}}
    spec = {"body": "坏账合计。", "evidence_recipes": [recipe], "limitations": ["坏账口径待确认"]}
    manager = FinanceStore(task)
    assert manager.validate_explanation(spec)["evidence_report"]["summary"]["status"] == "needs_attention"
    saved = manager.save_explanation_draft(spec)
    assert saved["evidence_report"]["summary"]["status"] == "needs_attention"
    # The manager still checks and revises that draft, keeping the recipe or dropping it.
    assert manager.validate_explanation({"draft_id": saved["id"]})["evidence_report"]["summary"]["status"] == "needs_attention"
    revisions = [manager.save_explanation_draft({"parent_id": saved["id"], "body": "坏账合计（修订）。",
                                                 "evidence_recipes": recipes}) for recipes in ([recipe], [])]
    assert [draft["parent_id"] for draft in revisions] == [saved["id"]] * 2
    # A revision that dropped the recipe and kept the notes reads to the manager as it always did, though its parent
    # cites a run that does not read.
    dropped = revisions[1]["id"]
    for args in (("report-draft-read",), ("report-projection-read", "--mode", "audit"), ("analysis-export",)):
        assert _cli(capsys, var, *args, "--draft", dropped, session=None, task=task.id)[0] == 0
    further = json.dumps({"parent_id": dropped, "body": "坏账合计（再修订）。"}, ensure_ascii=False)
    assert _cli(capsys, var, "analysis-draft", "--spec", further, session=None, task=task.id)[0] == 0
    # A session cites only a run it may read.
    with pytest.raises(FoundryError):
        FinanceStore(task, snapshot_ids=[pack["id"]], session_id="sess").validate_explanation(spec)


def test_the_manager_validates_and_reviews_a_draft_as_before(revision):
    """The checks that keep a session to its files read nothing more for the manager."""
    manager = FinanceStore(revision.task)
    # A requirements version named while there is none is not read, as before.
    assert manager.validate_explanation({"requirements_id": "e" * 32, "body": "收入。", "run_ids": [revision.ra["id"]]})
    # A draft whose run no longer reads is refused, as before.
    analysis = revision.analysis
    gone = analysis.run_analysis(analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": revision.a["id"]}})["id"])
    draft = analysis.save_draft({"title": "收入", "document": _document("收入。"), "run_ids": [gone["id"]]})
    analysis._object_path("runs", gone["id"]).unlink()
    for call in (lambda: manager.validate_explanation({"draft_id": draft["id"], "run_ids": [revision.ra["id"]]}),
                 lambda: manager.report_review({"draft_id": draft["id"]})):
        with pytest.raises(FoundryError, match="unavailable"):
            call()


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
    elif hidden == "newer_requirements":
        deal = analysis.add_dataset(_ledger(root / "deal.json", [
            {"account_code": "9999", "management_account": "revenue", "amount": 7, "period": "2026-07",
             "organization": "HIDDENCO", "currency": "USD"}]), name="并购")
        manager.analysis_requirements_save({
            "question": "并购", "scope": {"period": "2026-07", "organization": "HIDDENCO", "currency": "USD", "unit": "元"},
            "parent_id": analysis._list("requirements")[-1]["id"], "change_reason": "换范围",
            "bindings": {"deal": deal["id"]}, "items": [{"id": "rev", "metric": "revenue"}]})
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
    (_close_world, "newer_requirements"),
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


def test_task_state_names_the_snapshots_a_newer_file_replaced(tmp_path):
    """A result card reads 资料已更新，待重算 from this list: the rule the controls use, read for the reader."""
    task = TaskStore(tmp_path / "var").create(title="新版本")
    analysis = AnalysisStore(task)
    first = analysis.add_dataset(_csv(tmp_path / "v1.csv", [("revenue", "2026-08", "O1", "1", "CNY", "元")]), name="总账")
    assert analysis.state()["superseded_datasets"] == []
    second = analysis.add_dataset(_csv(tmp_path / "v2.csv", [("revenue", "2026-08", "O1", "2", "CNY", "元")]), name="总账")
    assert analysis.state()["superseded_datasets"] == [first["id"]]
    assert analysis.state(allowed={first["id"]})["superseded_datasets"] == []
    assert analysis.state(allowed={first["id"], second["id"]})["superseded_datasets"] == [first["id"]]


# --- export registration ----------------------------------------------------------------------------------------------


def test_only_the_desktop_registers_an_export_and_only_of_the_projection_it_read(revision, capsys):
    path = revision.var.parent / "report.html"
    path.write_text("<!doctype html><h1>收入</h1>", encoding="utf-8")
    projection = revision.analysis.projection_for_draft(revision.child["id"], "management")
    command = ("report-export-register", "--draft", revision.child["id"], "--format", "html", "--path", str(path),
               "--mode", "management", "--projection-hash", projection["projection_hash"])
    code, error = _cli(capsys, revision.var, *command)
    assert code != 0 and "does not take a session" in error
    # A session's receipt would name only the projection the server reads for it; the desktop's files as before.
    with pytest.raises(FoundryError, match="projection_hash"):
        revision.analysis.register_report_export(revision.child["id"], "html", path, content_mode="management",
                                                 projection_hash="0" * 64, allowed={revision.a["id"]})
    assert revision.analysis.register_report_export(revision.child["id"], "html", path, content_mode="management",
                                                    projection_hash="0" * 64)["projection_hash"] == "0" * 64
    code, receipt = _cli(capsys, revision.var, *command, session=None, task=revision.task.id)
    assert code == 0 and receipt["projection_hash"] == projection["projection_hash"]
