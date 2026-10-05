"""A session reads every run as it would have saved it from the files it may read.

A run another reader saved is pinned to the requirements version current when it started, its rows declared against
that version, and its reproducibility decided by the earlier runs of its fingerprint that reader could read. A
session reads it as saved where the versions and runs outside its snapshot ceiling were never saved: pinned to the
version current then among those it may read, with that version's fingerprint and rows, and reproducible by the runs
it may read. So does every saved analysis, draft, completion receipt and export built on such a run, and so does
what the session saves from it. No run a session reads carries the stored record's integrity hash. The manager (no
session) reads every run as stored.

So do the records a session's writes left before it saved only from the files it may read (main before #76), where
what it read can still be told from what was stored. A source refresh it filed against a batch it may not read reads
as filed against the nearest one back it may read, as does a refresh the manager filed past such batches, and so do
the files it replaced and the drafts citing them. A manager recovery that settled its completion operation on a draft
it may not read reads as never filed. Neither record is rewritten, and the manager reads both as stored. The rows a
business_key refresh carried over from the hidden batch are the session's own snapshot's, and stay there.
"""

from __future__ import annotations

import copy
import json
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from foundry.analysis import AnalysisStore, _hash, _new
from foundry.finance_service import FinanceStore
from foundry.source_refresh import SourceRefreshService, SourceScope
from foundry.task import TaskStore

from test_session_views import SECRET, SQL, _chain, _cli, _csv, _ledger, _normalized, _shows
from test_session_writes import ITEMS, PROFIT, SCOPE, SOURCE_SCOPE, _entry, _normalized_operation, _snapshots
from test_session_writes import fake_runner  # noqa: F401 (fixture)

# --- a run pinned to a requirements version outside the session -----------------------------------------------------

# A version on a file outside the session that declares the session's Falcon revenue an estimate.
HIDDEN_ITEMS = [{"id": "rev", "metric": "revenue", "label": "Falcon 收入", "organizations": ["Falcon"],
                 "grain_basis": [{"basis": "estimate", "method": "按人数分摊", "organizations": ["Falcon"]}]}]
PINNED = ("requirements_id", "requirements_semantic_fingerprint", "row_declarations")
# What a draft citing the runs leaves open, whoever saves it: a result fact of each SQL run, and the requirement.
ISSUES = ["missing_required_fact", "missing_required_fact", "requirement_unanswered"]
# A run reuses a version's binding only on the very bindings the version names (run_has_equivalent_requirements).
PINNED_SQL = "select metric_key, period, organization, amount, currency, unit from gl"


def _pinned_world(root: Path, hidden: bool, capsys, *, extra_item: bool = False):
    """The manager runs SQL, a script and the finance engine on A, a file inside the session, and SQL saved naming V,
    while with ``hidden`` a version Hv on H, outside it, is the head (with ``extra_item`` it holds an item more). The
    manager then saves V's items again on A (V2), the current version, which the session may read. Without ``hidden``
    every run is pinned to V."""
    var = root / "var"
    task = TaskStore(var).create(title="运行的要求版本")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(root / "a.csv", [("revenue", "2026-08", "Falcon", "100", "CNY", "元")]), name="总账")["id"]
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_csv(root / "h.csv", [("revenue", "2026-07", "Falcon", "100", "CNY", "元")]), name="薪酬")["id"]
    manager = FinanceStore(task)
    visible = manager.analysis_requirements_save({"question": "收入", "scope": {"period": "2026-08"},
                                                  "bindings": {"gl": a}, "items": ITEMS})
    head = visible
    if hidden:
        head = manager.analysis_requirements_save({
            "question": "Falcon 项目", "scope": {"period": "2026-07"}, "bindings": {"payroll": h},
            "parent_id": visible["id"], "change_reason": "换项目",
            "items": [*HIDDEN_ITEMS, *([{"id": "falcon_payroll", "metric": "expense", "label": "Falcon 薪酬"}]
                                       if extra_item else [])]})
    as_manager = {"session": None, "task": task.id}

    def sql(**spec):
        code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": a}, **spec}), **as_manager)
        assert code == 0, saved
        return _cli(capsys, var, "analysis-run", "--analysis", saved["id"], **as_manager)[1]

    runs = {"sql": sql(), "explicit": sql(requirements_id=visible["id"]),
            "script": _cli(capsys, var, "analysis-script", "--spec", json.dumps(
                {"code": "print(1)", "bindings": {"gl": a}, "result_file": "result.json"}), **as_manager)[1]}
    context = manager.save_context({"bindings": {"ledger": a}, "scopes": {}})
    runs["finance"] = manager.run_metric({"context_id": context["id"],
                                          "metric": {"kind": "account_total", "accounts": ["revenue"]}})
    assert [run["requirements_id"] for run in runs.values()] == [head["id"], visible["id"], head["id"], head["id"]]
    current = manager.analysis_requirements_save({"question": "收入", "scope": {"period": "2026-08"},
                                                  "bindings": {"gl": a}, "items": ITEMS, "parent_id": head["id"],
                                                  "change_reason": "回到总账"})
    cited = [runs[way]["id"] for way in ("script", "sql", "explicit")]
    draft = {"body": "Falcon 收入 100。", "run_ids": cited,
             "claims": [{"basis": "calculation", "run_id": cited[0], "row": 0, "column": "value", "value": "100"}]}
    return SimpleNamespace(var=var, task=task, analysis=analysis, a=a, manager=manager, visible=visible,
                           hidden=head if hidden else None, current=current, runs=runs, draft=draft,
                           secrets=[h, *([head["id"], head["semantic_fingerprint"], "Falcon 项目", "按人数分摊"]
                                         if hidden else [])])


def _named(world, value) -> str:
    """``value`` with each world's ids numbered: V's fingerprint (V2's is the same) is drawn from its file ids."""
    return _normalized(json.loads(json.dumps(value, ensure_ascii=False).replace(
        world.visible["semantic_fingerprint"], "<fingerprint>")))


def _labels_of(check: dict, run_id: str) -> list:
    return [(entry["key"].get("kind"), entry["label"], [reason["code"] for reason in entry["reasons"]])
            for entry in check.get("evidence_labels") or [] if entry["key"].get("run_id") == run_id]


def _verdict(receipt: dict) -> tuple:
    return (receipt["status"], receipt["repair_attempts"], receipt["stop_reason"], receipt["repair_allowed"],
            len(receipt.get("reused_run_ids") or []), [action["code"] for action in receipt.get("actions") or []])


def _session_draft(world, body: str) -> dict:
    return FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess").save_explanation_draft(
        {**world.draft, "body": body})


def test_a_session_reads_a_run_pinned_to_a_version_it_may_not_read_as_pinned_where_that_version_was_never_saved(
        tmp_path, capsys, fake_runner):
    from foundry.excel_bridge import BridgeTokenAuthority, ExcelBridgeApp

    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys)
        code, state = _cli(capsys, world.var, "analysis-state")
        assert code == 0
        assert _shows(state, world.secrets) == []
        listed = {run["id"]: run for run in state["runs"]}
        shown = {way: {key: listed[run["id"]].get(key) for key in PINNED} for way, run in world.runs.items()}
        assert {way: (run["requirements_id"], run["requirements_semantic_fingerprint"]) for way, run in shown.items()} \
            == dict.fromkeys(world.runs, (world.visible["id"], world.visible["semantic_fingerprint"]))
        assert shown["script"]["row_declarations"]["rows"][0]["estimate"] is False
        # The analysis a run was saved from names what the run reads as pinned to, or nothing.
        analyses = {row["id"]: row for row in state["analyses"]}
        assert [analyses[run["analysis_id"]].get("requirements_id") for way, run in world.runs.items()
                if way != "finance"] == [None, world.visible["id"], None]
        # A view need not be the stored record, and its absence must not tell the two apart.
        assert not any("_integrity_hash" in row for row in [*state["runs"], *state["analyses"]])
        # The Excel add-in lists the session's finance runs as the session reads them.
        authority = BridgeTokenAuthority(b"local-test-secret-local-test-secret")
        token = authority.issue(task_id=world.task.id, session_id="sess", ttl_seconds=60)
        status, _, body = ExcelBridgeApp(var_root=world.var, token_authority=authority).handle(
            "GET", "/api/context", {"Authorization": f"Bearer {token}"}, b"{}")
        assert status == 200
        excel = json.loads(body)["finance"]["runs"]
        assert [(run["requirements_id"], run["requirements_semantic_fingerprint"]) for run in excel] == [
            (world.visible["id"], world.visible["semantic_fingerprint"])]
        assert _shows(excel, world.secrets) == [] and "_integrity_hash" not in excel[0]
        read.append(_named(world, shown))
    # A world where the manager also saved a version outside the session reads, to it, as one where it never did.
    assert read[0] == read[1]
    # The manager reads every run as stored: pinned to Hv, the row Hv's estimate, the run naming V by Hv's fingerprint.
    code, managed = _cli(capsys, world.var, "analysis-state", session=None, task=world.task.id)
    runs = {run["id"]: run for run in managed["runs"]}
    script, explicit = runs[world.runs["script"]["id"]], runs[world.runs["explicit"]["id"]]
    assert script["requirements_id"] == world.hidden["id"] and script["_integrity_hash"]
    assert script["row_declarations"]["rows"][0]["estimate_sources"] == [
        {"source": "declared", "requirements_id": world.hidden["id"], "item_id": "rev"}]
    assert explicit["requirements_semantic_fingerprint"] == world.hidden["semantic_fingerprint"]


def test_a_session_reads_an_analysis_naming_a_version_it_may_not_read_as_its_runs_read(tmp_path, capsys, fake_runner):
    world = _pinned_world(tmp_path, True, capsys)
    code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
        {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}, "requirements_id": world.hidden["id"]}),
        session=None, task=world.task.id)
    assert code == 0
    code, run = _cli(capsys, world.var, "analysis-run", "--analysis", saved["id"], session=None, task=world.task.id)
    assert code == 0 and run["requirements_id"] == world.hidden["id"]
    code, state = _cli(capsys, world.var, "analysis-state")
    assert code == 0
    [listed] = [row for row in state["runs"] if row["id"] == run["id"]]
    [analysis] = [row for row in state["analyses"] if row["id"] == saved["id"]]
    # Pinned, as its run, to the version current before Hv among those the session may read.
    assert analysis["requirements_id"] == listed["requirements_id"] == world.visible["id"]
    assert _shows(state, world.secrets) == []
    code, managed = _cli(capsys, world.var, "analysis-state", session=None, task=world.task.id)
    assert [row["requirements_id"] for row in managed["analyses"] if row["id"] == saved["id"]] == [world.hidden["id"]]


def test_a_session_reads_a_draft_and_receipt_citing_such_a_run_as_it_would_have_saved_them(tmp_path, capsys, fake_runner):
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys)
        saved = world.manager.save_explanation_draft(world.draft)
        script = world.runs["script"]["id"]
        code, state = _cli(capsys, world.var, "analysis-state")
        assert code == 0
        [draft] = [row for row in state["drafts"] if row["id"] == saved["id"]]
        [receipt] = [row for row in state["completions"] if row["draft_id"] == saved["id"]]
        code, report = _cli(capsys, world.var, "report-draft-read", "--draft", saved["id"])
        assert code == 0
        code, exported = _cli(capsys, world.var, "analysis-export", "--draft", saved["id"], "--format", "md",
                              "--mode", "audit")
        assert code == 0
        text = Path(exported["path"]).read_text(encoding="utf-8")
        assert "row_declared_estimate" not in text and _shows([text, draft, report, receipt], world.secrets) == []
        assert _labels_of(draft["explanation_check"], script) == _labels_of(report["explanation_check"], script)
        # A receipt read anew reads back as one stored, its keys in order.
        read.append((_labels_of(draft["explanation_check"], script), _verdict(receipt), list(receipt)))
        if hidden:
            # The manager reads its draft and receipt as stored: the row an estimate, the runs not bound.
            assert _labels_of(saved["explanation_check"], script)[0][1:] == ("estimate", ["row_declared_estimate"])
            assert "requirements_run_outdated" in [action["code"] for action in saved["completion"]["actions"]]
    assert read[0] == read[1]
    assert read[0][0][0][1:] == ("unknown", ["run_script"])
    assert read[0][1][4:] == (3, ISSUES)


def test_a_session_s_draft_citing_a_run_pinned_to_a_version_it_may_not_read_is_saved_as_where_it_never_was(
        tmp_path, capsys, fake_runner):
    """A session draft citing such a run keeps its row declarations and its binding to the current requirements as the
    version the session reads the run pinned to decides them, and nothing of the hidden one."""
    saved = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys)
        session = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess")
        preview = session.validate_explanation(world.draft)
        draft = session.save_explanation_draft(world.draft)
        stored = world.analysis.get_draft(draft["id"])
        receipt = world.analysis._get("completions", draft["completion"]["id"])
        assert _shows([preview, draft, stored, receipt], world.secrets) == []
        script = world.runs["script"]["id"]
        assert _labels_of(preview, script) == _labels_of(stored["explanation_check"], script)
        names = {run["id"]: way for way, run in world.runs.items()}
        saved.append((_labels_of(stored["explanation_check"], script), stored["evidence_basis"]["row_estimates"],
                      _verdict(receipt), sorted(names[run_id] for run_id in receipt["reused_run_ids"])))
    assert saved[0] == saved[1]
    assert saved[0][1] == [] and saved[0][3] == ["explicit", "script", "sql"]


@pytest.mark.parametrize("way", ["save_explanation_draft", "save_completion_draft"])
def test_a_session_s_retry_files_the_receipt_its_save_would_have(tmp_path, capsys, fake_runner, monkeypatch, way):
    """The draft was saved and its receipt was not: the retry files the receipt as the session reads the runs."""
    import foundry.finance_completion as completion
    from foundry.finance_completion_operations import CompletionOperationStore

    filed = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys)
        session = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess")
        if way == "save_explanation_draft":
            def save():
                return session.save_explanation_draft(world.draft)
        else:
            operation = CompletionOperationStore(world.task, "sess", session.allowed).begin(
                "request-1", policy={"max_repairs": 2})

            def save():
                return session.save_completion_draft(operation["id"], "call-1", world.draft)
        original = completion.record_completion

        def interrupted(*args, **kwargs):
            raise RuntimeError("interrupted before receipt")

        monkeypatch.setattr(completion, "record_completion", interrupted)
        with pytest.raises(RuntimeError):
            save()
        monkeypatch.setattr(completion, "record_completion", original)
        retried = save()
        assert retried["replayed"] is True
        receipt = world.analysis._get("completions", retried["completion"]["id"])
        assert _shows(receipt, world.secrets) == []
        filed.append(_verdict(receipt))
    assert filed[0] == filed[1] and filed[0][4] == 3


# --- a completion chain on such runs ----------------------------------------------------------------------------------


def test_a_session_reads_a_completion_chain_on_such_runs_as_where_the_version_was_never_saved(
        tmp_path, capsys, fake_runner):
    """Each receipt is judged a stall against the one before it: as the session reads that one, not as stored."""
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys)
        managed = [world.manager.save_explanation_draft({**world.draft, "body": f"经理稿{index}：Falcon 收入 100。"})
                   for index in "甲乙丙"]
        code, state = _cli(capsys, world.var, "analysis-state")
        assert code == 0
        receipts = {row["draft_id"]: row for row in state["completions"]}
        chain = [_verdict(receipts[draft["id"]]) for draft in managed]
        # The manager files one more; the session then saves a draft with the same issues.
        world.manager.save_explanation_draft({**world.draft, "body": "经理稿丁：Falcon 收入 100。"})
        own = _session_draft(world, "会话稿：Falcon 收入 100。")
        assert _shows([state, own], world.secrets) == []
        read.append((chain, _verdict(own["completion"])))
        if hidden:
            assert [_verdict(draft["completion"])[4] for draft in managed] == [0, 0, 0]
    assert read[0] == read[1]
    assert read[0] == ([("repair_available", 0, None, True, 3, ISSUES), ("needs_review", 1, "no_progress", False, 3, ISSUES),
                        ("needs_review", 2, "no_progress", False, 3, ISSUES)],
                       ("needs_review", 2, "no_progress", False, 3, ISSUES))


def test_a_session_reads_its_operation_settled_before_it_read_such_runs_so_as_its_receipts(
        tmp_path, capsys, fake_runner, monkeypatch):
    """Saved as every reader then read runs, as stored: the operation settled on receipts judged on Hv. Read now, the
    receipts read as where Hv was never saved, and agree with the operation, which reads as it was settled."""
    from foundry.finance_completion_operations import CompletionOperationStore

    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys)
        session = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess")
        operations = CompletionOperationStore(world.task, "sess", session.allowed)
        operation = operations.begin("request-1", policy={"max_repairs": 2})
        with monkeypatch.context() as before:
            before.setattr(AnalysisStore, "run_in_view", lambda self, run, allowed, *, cache=None: run, raising=False)
            for call, body in (("call-1", "会话稿甲：Falcon 收入 100。"), ("call-2", "会话稿乙：Falcon 收入 100。")):
                session.save_completion_draft(operation["id"], call, {**world.draft, "body": body})
        settled = operations.get(operation["id"])
        receipts = [session._readable_receipt(world.analysis._get("completions", row["completion_id"]))
                    for row in settled["revisions"]]
        assert [(row["completion_status"], row.get("completion_stop_reason"), row["repair_allowed"])
                for row in settled["revisions"]] == [(row["status"], row["stop_reason"], row["repair_allowed"])
                                                     for row in receipts]
        assert _shows(receipts, world.secrets) == []
        read.append([_verdict(row) for row in receipts])
    assert read[0] == read[1] and [verdict[4] for verdict in read[0]] == [3, 3]


@pytest.mark.xfail(strict=True, reason="V2's stored semantic fingerprint holds the item only Hv held, so the runs the "
                                       "session reads pinned to V do not bind to it; the requirements lineage view "
                                       "does not read fingerprints")
def test_a_session_s_receipt_reuses_runs_pinned_where_a_version_it_may_not_read_held_an_item_more(
        tmp_path, capsys, fake_runner):
    filed = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys, extra_item=True)
        filed.append(_verdict(_session_draft(world, "会话稿：Falcon 收入 100。")["completion"]))
    assert filed[0] == filed[1]


def test_a_session_reads_a_receipt_on_such_a_run_by_the_lineage_it_reads(tmp_path, capsys):
    """A version saved before phase 1 on H held the level Falcon; V, on the session's files, dropped it. The manager's
    run was pinned to Hv, a later version on H, and V2 then repeated V. The session reads the receipt of a draft citing
    the run as one where neither version on H was saved: complete, the run reused, no level dropped."""
    seen = {}
    for hidden in (False, True):
        root = tmp_path / str(hidden)
        root.mkdir()
        task = TaskStore(root / "var").create(title="要求沿革")
        analysis = AnalysisStore(task)
        bindings = {}
        for scenario, amounts in (("actual", ("120", "70", "20")), ("budget", ("100", "60", "15"))):
            bindings[scenario] = analysis.add_dataset(_ledger(root / f"{scenario}.json", [
                {"account_code": code, "management_account": account, "amount": amount}
                for code, account, amount in zip(("001", "002", "003"), ("revenue", "cost", "expense"), amounts)]),
                name=scenario)["id"]
        task.record_session("sess", role="analysis")
        h = analysis.add_dataset(_entry(root / "h.json", "expense", "999"), name="H")["id"]
        manager = FinanceStore(task)
        context = manager.save_context({"bindings": bindings, "scopes": {
            scenario: {**SCOPE, "period": "2026-09", "scenario": scenario} for scenario in bindings}})

        def save(parent=None, *, on_h=False):
            return manager.analysis_requirements_save({
                "question": "Falcon 项目" if on_h else "利润", "items": [PROFIT], "change_reason": "改口径",
                **({"bindings": {"payroll": h}} if on_h else {"context_id": context["id"]}),
                **({"parent_id": parent} if parent else {})})["id"]

        parent = None
        if hidden:
            legacy = _new(task, question="Falcon 项目", scope={"period": "2026-09", "drilldown": "Falcon"},
                          bindings={"payroll": h}, context_id=None, parent_id=None, removed_item_ids=[],
                          change_reason="", selection=None, items=[{**PROFIT, "dimensions": {"drilldown": "Falcon"}}])
            parent = analysis._write(analysis._object_path("requirements", legacy["id"]), legacy)["id"]
        v = save(parent)
        head = save(v, on_h=True) if hidden else v
        run = manager.explain_variance({"context_id": context["id"]})
        save(head)
        managed = manager.save_explanation_draft({"body": "经理稿：请查看计算依据。", "run_ids": [run["id"]]})
        code, state = _cli(capsys, root / "var", "analysis-state")
        assert code == 0
        [receipt] = [row for row in state["completions"] if row["draft_id"] == managed["id"]]
        assert _shows(receipt, [h, head, "Falcon"] if hidden else []) == []
        seen[hidden] = (receipt["status"], receipt["original_requirements_completed"], len(receipt["reused_run_ids"]),
                        receipt["actions"])
        if hidden:
            # The manager reads it as stored: the run not bound, the level dropped.
            assert [action["code"] for action in managed["completion"]["actions"]] == [
                "requirements_run_outdated", "hierarchy_dimension_dropped"]
    assert seen[True] == seen[False] == ("complete", True, 1, [])


def test_a_session_reads_runs_drafts_and_receipts_with_no_version_hidden_at_no_more_cost(
        tmp_path, capsys, fake_runner, monkeypatch):
    """With every version readable, nothing is read again: no run is loaded with its outputs beyond what the listing
    reads, and no receipt or declaration is assessed anew."""
    import foundry.evidence_labels as evidence_labels
    import foundry.finance_completion as completion

    world = _pinned_world(tmp_path, False, capsys)
    for index in "甲乙丙丁":
        _session_draft(world, f"会话稿{index}：Falcon 收入 100。")
    calls, listed, pins = [], [], []
    get_run, list_kind, pin = AnalysisStore.get_run, AnalysisStore._list, getattr(AnalysisStore, "_pin_in_view", None)
    monkeypatch.setattr(AnalysisStore, "get_run", lambda self, run_id: calls.append(run_id) or get_run(self, run_id))
    monkeypatch.setattr(AnalysisStore, "_list", lambda self, kind: listed.append(kind) or list_kind(self, kind))
    monkeypatch.setattr(AnalysisStore, "_pin_in_view",
                        lambda self, record, *args: pins.append(record["id"]) or pin(self, record, *args), raising=False)
    for name in ("assess_completion", "declared_row_estimates"):
        module = completion if name == "assess_completion" else evidence_labels
        monkeypatch.setattr(module, name, lambda *args, name=name, **kwargs: pytest.fail(f"{name} read again"),
                            raising=False)
    code, state = _cli(capsys, world.var, "analysis-state")
    assert code == 0 and len(state["drafts"]) == len(state["completions"]) == 4
    # Each cited run once for whether the session may read the draft, once for whether it may read the receipt whole.
    assert len(calls) == 2 * 4 * len(world.draft["run_ids"])
    # The versions and runs are listed once for the whole read, and each record's pin is read once, by the listing:
    # no draft or receipt lists or reads them again.
    assert listed.count("requirements") == listed.count("runs") == 1 and len(pins) == len(set(pins))


# --- reproducibility of a run another reader saved -----------------------------------------------------------------


AGGREGATE = {"dataset_alias": "t", "group_by": ["organization"], "filters": [],
             "measures": [{"name": "amount", "field": "amount", "aggregation": "sum"}], "dedupe": {"policy": "none"}}


def _claim(run: dict) -> dict:
    return {"basis": "calculation", "run_id": run["id"], "row": 0, "column": "amount",
            "value": run["result"]["rows"][0]["amount"]}


def _twin_world(root: Path, capsys, *, hidden_runs: bool) -> dict:
    """The session may read B; A, filed after it began, holds the same rows. The manager runs SQL on B once and a
    structured aggregate on B twice, after running both on A when ``hidden_runs``. What the session reads."""
    var = root / "var"
    task = TaskStore(var).create(title="复现")
    analysis = AnalysisStore(task)
    path = _csv(root / "b.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")])
    b = analysis.add_dataset(path, name="总账")
    task.record_session("sess", role="analysis")
    a = analysis.add_dataset(path, name="薪酬", allow_duplicate=True)

    def revision(dataset, engine):
        spec = {"engine": "structured_aggregate", "aggregate_plan": AGGREGATE} if engine == "aggregate" else {"sql": SQL}
        return analysis.save_analysis({"question": "收入", "bindings": {"t": dataset["id"]}, **spec})["id"]

    if hidden_runs:
        analysis.run_analysis(revision(a, "sql"))
        analysis.run_analysis(revision(a, "aggregate"))
    sql = analysis.run_analysis(revision(b, "sql"))
    twice = revision(b, "aggregate")
    analysis.run_analysis(twice)
    aggregate = analysis.run_analysis(twice)
    drafts = [analysis.save_draft({"title": "收入", "body": "收入 100。", "run_ids": [run["id"]], "claims": [_claim(run)]})
              for run in (sql, aggregate)]
    kept = analysis.save_draft({"title": "收入", "parent_id": drafts[1]["id"], "body": "收入 100。",
                                "run_ids": [aggregate["id"]], "claims": [_claim(aggregate)]})
    plain = analysis.save_draft({"title": "收入", "body": "收入 100。", "run_ids": [sql["id"]]})
    analysis.export_draft(plain["id"], "md", mode="management")
    read = {"stored": [run["reproducibility_status"] for run in (sql, aggregate)]}
    code, state = _cli(capsys, var, "analysis-state")
    read["runs"] = [{key: run.get(key) for key in ("id", "reproducibility_status", "_integrity_hash")} for run in state["runs"]]
    read["drafts"] = [(draft["id"], draft["reproducibility_status"]) for draft in state["drafts"]]
    for draft in (*drafts, kept):
        code, shown = _cli(capsys, var, "report-draft-read", "--draft", draft["id"])
        read.setdefault("draft-read", []).append(shown["reproducibility_status"])
    for run in (sql, aggregate):
        code, saved = _cli(capsys, var, "analysis-draft", "--spec", json.dumps(
            {"title": "收入", "body": "收入 100。", "run_ids": [run["id"]], "claims": [_claim(run)]}))
        assert code == 0, saved
        read.setdefault("saved", []).append((saved["reproducibility_status"],
                                             analysis.get_draft(saved["id"])["reproducibility_status"]))
    session = FinanceStore(task, snapshot_ids=[b["id"]], session_id="sess")
    finance = session.save_explanation_draft({"body": "收入 100。", "run_ids": [sql["id"]], "claims": [_claim(sql)]})
    read["finance"] = (finance["reproducibility_status"], analysis.get_draft(finance["id"])["reproducibility_status"])
    for draft, mode in ((drafts[0], "audit"), (drafts[0], "management"), (plain, "management")):
        code, exported = _cli(capsys, var, "analysis-export", "--draft", draft["id"], "--format", "md", "--mode", mode)
        read.setdefault("md", []).append([line for line in Path(exported["path"]).read_text().splitlines()
                                          if "reproducibility:" in line or "可复现状态" in line])
    return read


def test_a_session_reads_a_run_another_reader_saved_by_the_runs_it_may_read(tmp_path, capsys):
    hidden = _twin_world(tmp_path / "hidden", capsys, hidden_runs=True)
    alone = _twin_world(tmp_path / "alone", capsys, hidden_runs=False)
    # The manager compared its runs on B with its runs on A, the same rows under another snapshot.
    assert hidden.pop("stored") == ["reproducible", "non_reproducible"]
    assert alone.pop("stored") == ["unverified", "reproducible"]
    assert _normalized(hidden) == _normalized(alone)
    assert [run["reproducibility_status"] for run in alone["runs"]] == ["unverified", "unverified", "reproducible"]
    # The stored record's hash would confirm the stored status, so a view never carries it.
    assert all(run["_integrity_hash"] is None for run in alone["runs"])
    assert alone["draft-read"] == ["unverified", "reproducible", "reproducible"]
    assert alone["saved"] == [("unverified", "unverified"), ("reproducible", "reproducible")]
    assert alone["finance"] == ("unverified", "unverified")
    # The manager exported the run-only draft first; the session's management export is its own.
    assert [lines[-1].endswith("reproducibility: unverified") for lines in alone["md"]] == [True] * 3


def test_the_manager_reads_runs_and_drafts_compared_with_a_hidden_twin_as_stored(tmp_path, capsys):
    _twin_world(tmp_path, capsys, hidden_runs=True)
    var = tmp_path / "var"
    task = TaskStore(var).list("all")[0]
    code, state = _cli(capsys, var, "analysis-state", session=None, task=task.id)
    assert [run["reproducibility_status"] for run in state["runs"]][2:] == ["reproducible", "non_reproducible",
                                                                             "non_reproducible"]
    assert all(run["_integrity_hash"] for run in state["runs"])
    stored = {draft["id"]: draft["reproducibility_status"] for draft in AnalysisStore(task)._list("drafts")}
    assert {draft["id"]: draft["reproducibility_status"] for draft in state["drafts"]} == stored


def test_a_session_export_filed_before_it_read_runs_so_is_not_handed_back(tmp_path, capsys, monkeypatch):
    """The session exported a draft citing a run, when it read the run's reproducibility as stored. Exported again
    now, it reads the run by the runs it may read, under a file of its own."""
    import foundry.analysis as analysis_module

    lines = {}
    for hidden in (True, False):
        var = tmp_path / str(hidden) / "var"
        task = TaskStore(var).create(title="复现")
        analysis = AnalysisStore(task)
        path = _csv(tmp_path / f"b{hidden}.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")])
        b = analysis.add_dataset(path, name="总账")
        task.record_session("sess", role="analysis")
        a = analysis.add_dataset(path, name="薪酬", allow_duplicate=True)
        for dataset in ([a, b] if hidden else [b]):
            run = analysis.run_analysis(analysis.save_analysis({"question": "q", "sql": SQL,
                                                                "bindings": {"t": dataset["id"]}})["id"])
        draft = analysis.save_draft({"title": "收入", "body": "收入 100。", "run_ids": [run["id"]]})
        with monkeypatch.context() as before:
            before.setattr(AnalysisStore, "run_in_view", lambda self, run, allowed, *, cache=None: run, raising=False)
            before.setattr(analysis_module, "_export_reader", lambda mode, allowed, runs=(): (
                "" if allowed is None or mode != "audit" else analysis_module._registration_reader(allowed)))
            code, earlier = _cli(capsys, var, "analysis-export", "--draft", draft["id"], "--mode", "audit")
        assert code == 0
        code, again = _cli(capsys, var, "analysis-export", "--draft", draft["id"], "--mode", "audit")
        assert code == 0 and again["path"] != earlier["path"]
        lines[hidden] = [line.replace(run["id"], "<run>") for line in Path(again["path"]).read_text().splitlines()
                         if "reproducibility:" in line]
    assert lines[True] == lines[False] == ["Run: <run>; execution: succeeded; reproducibility: unverified"]


def test_a_wider_session_reads_a_narrower_session_s_run_by_the_runs_it_may_read(tmp_path, capsys):
    """S1 may read B, S2 B and C; A, C and B hold the same rows. The run S1 saved on B compared with nothing S1 may
    read; S2 reads it against the manager's run on C, whether or not a run on A, hidden from both, exists."""
    def world(root: Path, hidden_run: bool):
        var = root / "var"
        task = TaskStore(var).create(title="复现")
        analysis = AnalysisStore(task)
        path = _csv(root / "b.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")])
        b = analysis.add_dataset(path, name="总账")
        task.record_session("s1", role="analysis")
        c = analysis.add_dataset(path, name="预算", allow_duplicate=True)
        task.record_session("s2", role="analysis")
        a = analysis.add_dataset(path, name="薪酬", allow_duplicate=True)
        for dataset in ([a, c] if hidden_run else [c]):
            analysis.run_analysis(analysis.save_analysis({"question": "收入", "sql": SQL,
                                                          "bindings": {"t": dataset["id"]}})["id"])
        code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": SQL, "bindings": {"t": b["id"]}}), session="s1")
        code, run = _cli(capsys, var, "analysis-run", "--analysis", saved["id"], session="s1")
        return [run["reproducibility_status"], *[next(row for row in _cli(capsys, var, "analysis-state", session=s)[1]["runs"]
                                                     if row["id"] == run["id"])["reproducibility_status"]
                                                for s in ("s1", "s2")]]

    assert world(tmp_path / "hidden", True) == world(tmp_path / "alone", False) == ["unverified", "unverified",
                                                                                    "reproducible"]


def test_a_run_committed_while_a_session_runs_reads_after_the_session_s(tmp_path, capsys, monkeypatch):
    """The session lists the earlier runs of its fingerprint and commits its run under one task lock: a run the
    manager commits meanwhile comes after it, so the session reads its run as it saved it."""
    var = tmp_path / "var"
    task = TaskStore(var).create(title="复现")
    analysis = AnalysisStore(task)
    b = analysis.add_dataset(_csv(tmp_path / "b.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")]), name="总账")
    task.record_session("sess", role="analysis")
    managed = analysis.save_analysis({"question": "q", "sql": SQL, "bindings": {"t": b["id"]}})["id"]
    code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps({"question": "q", "sql": SQL,
                                                                          "bindings": {"t": b["id"]}}))
    listed = AnalysisStore._list
    meanwhile: dict = {}

    def listing(self, kind):
        rows = listed(self, kind)
        if kind == "runs" and not meanwhile:
            # The manager runs once the session has listed the earlier runs; it waits for the session's commit.
            meanwhile["thread"] = threading.Thread(target=lambda: meanwhile.update(run=analysis.run_analysis(managed)))
            meanwhile["thread"].start()
            meanwhile["thread"].join(timeout=2)
        return rows

    monkeypatch.setattr(AnalysisStore, "_list", listing)
    run = AnalysisStore(task).run_analysis(saved["id"], session_id="sess", allowed={b["id"]})
    meanwhile["thread"].join()
    monkeypatch.setattr(AnalysisStore, "_list", listed)
    assert meanwhile["run"]["seq"] > run["seq"]
    code, state = _cli(capsys, var, "analysis-state")
    assert [row["reproducibility_status"] for row in state["runs"] if row["id"] == run["id"]] == [
        run["reproducibility_status"]] == ["unverified"]


def test_a_session_reads_a_revision_of_a_marked_document_as_saved_with_nothing_hidden(tmp_path, capsys):
    """Nothing is hidden from the session. save_draft compares a revision of a document with an estimate notice before
    adding the notice, so a revision that takes its parent's document is stored unverified; the session reads it,
    and its own such revision, as stored."""
    from foundry.finance_requirements import save_requirements

    var = tmp_path / "var"
    task = TaskStore(var).create(title="估算")
    analysis = AnalysisStore(task)
    source = tmp_path / "b.csv"
    source.write_text("metric_key,organization,period,scenario,value,currency,unit\n"
                      "revenue,华东,2026-08,budget,100,CNY,万元\n", encoding="utf-8")
    b = analysis.add_dataset(source, name="预算")
    task.record_session("sess", role="analysis")
    save_requirements(analysis, {
        "question": "收入预算", "scope": {"ledger": "L1", "currency": "CNY", "unit": "万元"}, "bindings": {"t": b["id"]},
        "items": [{"id": "rev", "metric": "revenue", "label": "收入", "organizations": ["华东"], "periods": ["2026-08"],
                   "scenarios": ["budget"], "requires_drilldown": False,
                   "grain_basis": [{"organizations": ["华东"], "scenarios": ["budget"], "basis": "estimate",
                                    "method": "全年×进度"}]}]})
    revision = analysis.save_analysis({"question": "q", "bindings": {"t": b["id"]},
                                       "sql": "select metric_key, organization, period, scenario, value, currency, unit from t"})
    analysis.run_analysis(revision["id"])
    run = analysis.run_analysis(revision["id"])
    chart = FinanceStore(task).chart_deliverable_save({"run_id": run["id"], "label": "预算"})
    visual = {"version": 1, "kind": "bar", "title": "预算", "takeaway": "估算。", "chart_id": chart["id"],
              "category": "organization", "value_columns": ["value"], "unit": "万元", "series": {"columns": [], "rows": []},
              "run_id": "b" * 32, "snapshot_hash": "c" * 64, "source_label": "x"}
    draft = analysis.save_draft({"title": "预算", "document": {
        "schema_version": 1, "template_version": "annual-v1", "metadata": {},
        "content": [{"type": "reportVisual", "attrs": {"visual": visual}}]}})
    assert run["reproducibility_status"] == "reproducible"
    assert "estimate_notice" in draft["document"]["content"][0]["attrs"]["visual"]
    kept = [analysis.save_draft({"title": "预算", "parent_id": draft["id"]}),
            analysis.save_draft({"title": "预算", "parent_id": draft["id"], "document": copy.deepcopy(draft["document"])})]
    assert [row["reproducibility_status"] for row in kept] == ["unverified", "unverified"]
    assert [_cli(capsys, var, "report-draft-read", "--draft", row["id"])[1]["reproducibility_status"]
            for row in kept] == ["unverified", "unverified"]
    code, own = _cli(capsys, var, "analysis-draft", "--spec", json.dumps({"title": "预算", "parent_id": draft["id"]}))
    assert code == 0, own
    assert own["reproducibility_status"] == analysis.get_draft(own["id"])["reproducibility_status"] == "unverified"


# --- records filed before a session saved only from the files it may read ------------------------------------------


def _refreshed_world(root: Path, capsys, *, legacy: bool, policy: str = "snapshot_only", mode: str = "full_period",
                     drafts: bool = False):
    """The session refreshes P, the manager publishes H (with ``legacy``), and the session refreshes S: with ``legacy``
    as main before #76 filed it, against the latest batch of all (H); without H, as it files it now. With ``drafts``,
    the session saves a draft on P before S and another after it."""
    var = root / "var"
    task = TaskStore(var).create(title="刷新")
    task.record_session("sess", role="analysis")
    uploads = task.root / "analysis" / "uploads"
    uploads.mkdir(parents=True)

    def upload(name: str, body: str) -> Path:
        (uploads / name).write_text("document_id,line_id,management_account,amount\n" + body)
        return uploads / name

    def refresh(name: str, body: str, label: str, session: str | None = "sess") -> dict:
        spec = {"path": str(upload(name, body)), "scope": {**SOURCE_SCOPE, "mode": mode},
                "file_identity_policy": policy, "name": label}
        code, result = _cli(capsys, var, "finance-source-refresh", "--spec", json.dumps(spec),
                            session=session, task=None if session else task.id)
        assert code == 0, result
        return result

    p = refresh("p.csv", "P1,1,revenue,100\n", "总账8月")
    h = refresh("h.csv", f"H1,1,revenue,{SECRET}\n", "薪酬", None) if legacy else None
    saved = [_draft_on(task, p["dataset_id"])] if drafts else []
    body = "P1,1,revenue,100\nS1,1,revenue,200\n"
    if legacy:
        # What main's finance-source-refresh filed for the session: the manager's comparison, then the widening.
        s = SourceRefreshService(task).refresh_file(upload("s.csv", body), scope=SourceScope(**SOURCE_SCOPE, mode=mode),
                                                    name="总账9月", file_identity_policy=policy)
        task.update_session_context("sess", snapshot_ids=[*_snapshots(task), s["dataset_id"]])
        assert s["prior_snapshot_id"] == h["dataset_id"]
    else:
        s = refresh("s.csv", body, "总账9月")
    if drafts:
        saved.append(_draft_on(task, p["dataset_id"]))
    return SimpleNamespace(var=var, task=task, p=p, h=h, s=s, refresh=refresh, drafts=saved)


def _draft_on(task, dataset_id: str) -> dict:
    """A finance draft the session saves on a run of ``dataset_id``."""
    sess = FinanceStore(task, snapshot_ids=_snapshots(task), session_id="sess")
    scope = {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元",
             "scenario": "actual"}
    context = sess.save_context({"bindings": {"ledger": dataset_id}, "scopes": {"ledger": scope}})
    run = sess.run_metric({"context_id": context["id"], "metric": {"kind": "account_total", "accounts": ["revenue"]}})
    return sess.save_explanation_draft({"body": "收入见计算。", "run_ids": [run["id"]]})


def _refresh_reads(world, capsys, session: str = "sess") -> dict:
    """What ``session`` reads of the refreshes: the batches it lists, S's recorded prior wherever it reads S's record,
    each file's freshness, the files it reads as replaced, and whether each batch and record it lists verifies under
    its integrity hash, as a stored one does."""
    from foundry.finance_controls import superseded_snapshots

    allowed = _snapshots(world.task, session)
    s = world.s["dataset_id"]
    code, listing = _cli(capsys, world.var, "finance-source-list", session=session)
    assert code == 0
    code, read = _cli(capsys, world.var, "dataset-read", "--dataset", s, session=session)
    assert code == 0
    code, ready = _cli(capsys, world.var, "finance-readiness", session=session)
    assert code == 0
    code, state = _cli(capsys, world.var, "analysis-state", session=session)
    assert code == 0
    context = FinanceStore(world.task, snapshot_ids=allowed, session_id=session).list_finance_context()
    listed = [*listing["batches"], *state["datasets"]]
    return {
        "batches": [{key: row.get(key) for key in ("prior_snapshot_id", "dataset_id")} for row in listing["batches"]],
        "priors": [record["metadata"]["source_refresh"]["prior_snapshot_id"] for record in
                   (read, *[row for row in (*state["datasets"], *context["datasets"]) if row["id"] == s])],
        "freshness": {row["name"]: row["freshness"] for row in ready["datasets"]},
        "superseded": sorted({world.p["dataset_id"]: "P", s: "S"}.get(snapshot, "another")
                             for snapshot in superseded_snapshots(world.task, allowed=set(allowed))),
        "verified": [_hash({key: value for key, value in row.items() if key != "_integrity_hash"})
                     == row["_integrity_hash"] for row in listed],
    }


@pytest.mark.parametrize(("policy", "mode"), [("snapshot_only", "full_period"), ("business_key", "incremental"),
                                              ("business_key", "full_period")])
def test_a_refresh_filed_against_a_batch_the_session_may_not_read_reads_as_filed_against_its_own(
        tmp_path, capsys, policy, mode):
    from foundry.finance_controls import refreshed_snapshots

    legacy = _refreshed_world(tmp_path / "legacy", capsys, legacy=True, policy=policy, mode=mode)
    twin = _refreshed_world(tmp_path / "twin", capsys, legacy=False, policy=policy, mode=mode)
    read = _refresh_reads(legacy, capsys)
    # The batch, its snapshot's record and every freshness the session reads name P as S's prior, as without H.
    assert _normalized(read) == _normalized(_refresh_reads(twin, capsys))
    p, h, s = (record["dataset_id"] for record in (legacy.p, legacy.h, legacy.s))
    assert read["priors"] == [p] * 3 and read["superseded"] == ["P"] and all(read["verified"])
    assert _shows(read, [legacy.h["id"], h]) == []
    # The manager reads every batch as stored: S was filed against H, which replaced P.
    assert refreshed_snapshots(legacy.task) == {p: {h}, h: {s}}
    code, managed = _cli(capsys, legacy.var, "finance-source-list", session=None, task=legacy.task.id)
    assert managed["batches"] == SourceRefreshService(legacy.task).batches()
    assert [row["prior_snapshot_id"] for row in managed["batches"]] == [None, p, h]
    if policy == "business_key":
        # Not read again: S merged its upload with H's rows (incremental) or wrote them off as deleted (full_period),
        # and the two are not kept apart; its counts and changes were taken against H though it reads filed against
        # P. The session's later refreshes compare with S and carry H's rows on.
        code, listing = _cli(capsys, legacy.var, "finance-source-list")
        assert ([{key: row[key] for key in ("change_counts", "changes")} for row in listing["batches"]]
                == [{key: row[key] for key in ("change_counts", "changes")} for row in managed["batches"]
                    if row["dataset_id"] != h])
        later = legacy.refresh("s2.csv", "P1,1,revenue,100\nS1,1,revenue,200\nS2,1,revenue,300\n", "总账10月")
        for snapshot in (s, later["dataset_id"]):
            code, rows = _cli(capsys, legacy.var, "dataset-read", "--dataset", snapshot)
            assert ["H1", SECRET, "active" if mode == "incremental" else "deleted"] in [
                [row["document_id"], row["amount"], row["_source_row_state"]] for row in rows["rows"]]


def test_a_narrower_session_reads_a_refresh_chain_past_batches_it_may_not_read_as_filed_without_them(tmp_path, capsys):
    """Since #76 too: the manager refreshes P, H1, H2 and S in turn, and a session may read only P and S. It reads S as
    filed against P, and P as replaced, as where H1 and H2 were never published; one that may read only S reads S as
    its source's first refresh."""
    def world(root: Path, hidden: int):
        var = root / "var"
        task = TaskStore(var).create(title="刷新")
        for session in ("sess", "only"):
            task.record_session(session, role="analysis")
        uploads = task.root / "analysis" / "uploads"
        uploads.mkdir(parents=True)

        def refresh(name: str, body: str, label: str) -> dict:
            (uploads / name).write_text("document_id,line_id,management_account,amount\n" + body)
            return SourceRefreshService(task).refresh_file(uploads / name, scope=SourceScope(**SOURCE_SCOPE),
                                                           name=label, file_identity_policy="snapshot_only")

        p = refresh("p.csv", "P1,1,revenue,100\n", "总账8月")
        h = [refresh(f"h{index}.csv", f"H{index},1,revenue,{SECRET}\n", "薪酬") for index in range(hidden)]
        s = refresh("s.csv", "P1,1,revenue,100\nS1,1,revenue,200\n", "总账9月")
        for session, snapshots in (("sess", [p, s]), ("only", [s])):
            task.update_session_context(session, snapshot_ids=[row["dataset_id"] for row in snapshots])
        return SimpleNamespace(var=var, task=task, p=p, h=h, s=s)

    chained, alone = world(tmp_path / "chained", 2), world(tmp_path / "alone", 0)
    assert chained.s["prior_snapshot_id"] == chained.h[-1]["dataset_id"]
    reads = {name: [_refresh_reads(built, capsys, session) for session in ("sess", "only")]
             for name, built in (("chained", chained), ("alone", alone))}
    assert _normalized(reads["chained"]) == _normalized(reads["alone"])
    p, s = chained.p["dataset_id"], chained.s["dataset_id"]
    narrow, only = reads["chained"]
    assert narrow["batches"] == [{"prior_snapshot_id": None, "dataset_id": p},
                                 {"prior_snapshot_id": p, "dataset_id": s}]
    assert narrow["superseded"] == ["P"] and "superseded" in [reason["code"] for reason in
                                                              narrow["freshness"]["总账8月"]["reasons"]]
    assert only["batches"] == [{"prior_snapshot_id": None, "dataset_id": s}] and only["priors"] == [None] * 3
    assert _shows(reads["chained"], [token for row in chained.h for token in (row["id"], row["dataset_id"])]) == []


def test_a_draft_on_a_file_a_hidden_batch_replaced_reads_as_saved_without_it(tmp_path, capsys):
    """A session's draft on P saved after its refresh S reads P as replaced, though S was filed against H, as where H
    was never published; one saved before S reads P as it read when saved, S filed since replacing nothing."""
    read = {}
    for legacy in (True, False):
        world = _refreshed_world(tmp_path / str(legacy), capsys, legacy=legacy, drafts=True)
        read[legacy] = []
        for saved in world.drafts:
            code, shown = _cli(capsys, world.var, "report-draft-read", "--draft", saved["id"])
            assert code == 0
            read[legacy] += [(freshness["state"], [reason["code"] for reason in freshness["reasons"]])
                             for freshness in (record["explanation_check"]["dataset_freshness"][world.p["dataset_id"]]
                                               ["freshness"] for record in (saved, shown))]
    assert read[True] == read[False] == [("unknown", ["no_task_period"])] * 2 + [("source_stale", ["superseded"])] * 2


def _operations(reads: list) -> list[dict]:
    """The completion operations among ``reads``, however each was returned."""
    found = []
    for value in reads:
        if isinstance(value, dict) and "events" in value:
            found.append(value)
        elif isinstance(value, (list, tuple)):
            found += _operations(list(value))
    return found


def _settled_operation(root: Path, capsys, *, live: bool, legacy: bool, spent: int = 2):
    """A session's revision 1, rejected (``live``) or timed out; with ``legacy``, settled as main before #76 settled a
    manager recovery on a draft the session may not read, after ``spent`` drafts it may not read (2: the recovery's
    verdict exhausts the repairs; 0: it leaves one)."""
    from foundry.finance_completion_operations import CompletionOperationStore

    root.mkdir()
    sess, _wide, run = _chain(root, spent)
    var = root / f"var{spent}"
    code, operation = _cli(capsys, var, "finance-completion-begin",
                           "--spec", json.dumps({"request_key": "request-1", "policy": {"max_repairs": 2}}))
    assert code == 0
    operations = CompletionOperationStore(sess.task, "sess", sess.allowed)
    operations.reserve(operation["id"], payload={"body": "会话稿。"}, call_id="call-1")
    if live:
        operations.reject_attempt(operation["id"], 1, {"code": "claim_value_mismatch", "message": "bad"})
    else:
        operations.stop(operation["id"], "timeout")
    hidden = []
    if legacy:
        manager = FinanceStore(sess.task)
        recovered = manager.recover_completion_draft({"operation_id": operation["id"], "revision": 1,
                                                      "draft": {"body": "宽口径恢复稿。", "run_ids": [run["id"]]}})
        receipt = manager.analysis._get("completions", recovered["completion"]["id"])
        # What main's recovery settled: the session's revision, on the receipt as the manager reads it.
        CompletionOperationStore(sess.task, "sess").settle(operation["id"], 1, recovered, receipt)
        hidden = [recovered["id"], receipt["id"], recovered["content_hash"]]
    return SimpleNamespace(sess=sess, var=var, operation=operation["id"], hidden=hidden)


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("late", [False, True])
def test_a_settlement_on_a_draft_the_session_may_not_read_reads_as_never_filed(tmp_path, capsys, monkeypatch, live,
                                                                              late):
    import foundry.finance_completion_operations as module
    from foundry.errors import FoundryError
    from foundry.finance_completion_operations import CompletionOperationStore

    worlds = {legacy: _settled_operation(tmp_path / str(legacy), capsys, live=live, legacy=legacy)
              for legacy in (True, False)}
    stored = CompletionOperationStore(worlds[True].sess.task, "sess").get(worlds[True].operation)
    if late:  # read after every deadline, as every operation filed before #76 is by now
        clock = module._utc_now
        monkeypatch.setattr(module, "_utc_now", lambda value=None: clock(value) + timedelta(hours=2))
    reads = {}
    for legacy, world in worlds.items():
        spec = json.dumps({"operation_id": world.operation})
        # Read twice: a first read past the deadline files the expiry, as the stored record then reads back.
        statuses = [_cli(capsys, world.var, "finance-completion-status", "--spec", spec) for _ in range(2)]
        code, begun = _cli(capsys, world.var, "finance-completion-begin", "--spec",
                           json.dumps({"request_key": "request-1"}))
        assert code == 0 and all(code == 0 for code, _ in statuses)
        operations = CompletionOperationStore(world.sess.task, "sess", world.sess.allowed)
        read = [statuses[-1][1], begun, operations.get(world.operation)]
        try:  # revision 1 again, by number
            read.append(operations.reserve(world.operation, 1, payload={"body": "会话稿。"}))
        except FoundryError as exc:
            read.append(["refused", str(exc)])
        # The session's revision 1 again, then revision 2 and a stop. Before its deadline the session's next save
        # and stop still go by the stored verdict (needs_review): every operation filed before #76 is past it.
        for call, body in (("call-1", "会话稿。"), *([("call-2", "会话修订稿。")] if late or not live else [])):
            try:
                read.append(["saved", world.sess.save_completion_draft(world.operation, call, {"body": body})])
            except FoundryError as exc:
                read.append(["refused", str(exc)])
        if late or not live:
            read.append(_cli(capsys, world.var, "finance-completion-stop", "--spec", json.dumps(
                {"operation_id": world.operation, "reason": "用户取消"})))
        assert _shows(read, world.hidden) == []
        # Last updated by its last event, as every stored operation is: no later moment of the settlement shows.
        assert all(row["updated_at"] == row["events"][-1]["at"] for row in _operations(read))
        reads[legacy] = _normalized_operation(read)
    assert reads[True] == reads[False]
    # The manager reads the settlement as stored.
    assert stored["revisions"][0]["completion_id"] == worlds[True].hidden[1]
    assert CompletionOperationStore(worlds[True].sess.task, "sess").get(worlds[True].operation)["revisions"][0][
        "completion_id"] == worlds[True].hidden[1]


def test_a_session_goes_on_past_a_settlement_on_a_draft_it_may_not_read_as_past_its_own_rejection(tmp_path, capsys):
    """The recovery's verdict left a repair, so the operation goes on: the session reserves revision 2, has it
    rejected, and saves revision 3, each again as a replay, reading revision 1 throughout as it rejected it."""
    from foundry.finance_completion_operations import CompletionOperationStore

    reads = {}
    for legacy in (True, False):
        world = _settled_operation(tmp_path / str(legacy), capsys, live=True, legacy=legacy, spent=0)
        operations = CompletionOperationStore(world.sess.task, "sess", world.sess.allowed)
        reserved = operations.reserve(world.operation, payload={"body": "会话修订稿。"}, call_id="call-2")
        rejected = [operations.reject_attempt(world.operation, 2, {"code": "claim_value_mismatch", "message": "bad"})
                    for _ in range(2)]
        saved = [world.sess.save_completion_draft(world.operation, "call-3", {"body": "会话第三稿。"})
                 ["completion_operation"] for _ in range(2)]
        read = [reserved, *rejected, *saved, operations.get(world.operation)]
        assert _shows(read, world.hidden) == []
        assert all(row["updated_at"] == row["events"][-1]["at"] for row in _operations(read))
        reads[legacy] = _normalized_operation(read)
    assert reads[True] == reads[False]
    assert [row["status"] for row in json.loads(reads[True])[-1]["revisions"]] == [
        "rejected_validation", "rejected_validation", "settled"]


def test_a_run_a_session_filed_on_a_hidden_run_and_version_reads_as_its_run_without_them(tmp_path, capsys, monkeypatch):
    """Main before #76 compared a session's run with every earlier run of its fingerprint and pinned it to the head
    requirements version of all, and the session's draft read the run's reproducibility as stored. A, B's rows filed
    again outside the session, had a run of the same SQL, and Hv on A was the head: the session reads its run, and the
    draft citing it, as where neither was ever saved (AnalysisStore.run_in_view)."""
    def world(root: Path, legacy: bool) -> dict:
        var = root / "var"
        task = TaskStore(var).create(title="复现")
        analysis = AnalysisStore(task)
        path = _csv(root / "b.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")])
        b = analysis.add_dataset(path, name="总账")["id"]
        task.record_session("sess", role="analysis")
        manager = FinanceStore(task)
        visible = manager.analysis_requirements_save({"question": "收入", "scope": {"period": "2026-08"},
                                                      "bindings": {"t": b}, "items": ITEMS})
        head = visible
        if legacy:
            a = analysis.add_dataset(path, name="薪酬", allow_duplicate=True)["id"]
            head = manager.analysis_requirements_save({
                "question": "Falcon 项目", "scope": {"period": "2026-07"}, "bindings": {"payroll": a},
                "parent_id": visible["id"], "change_reason": "换项目", "items": HIDDEN_ITEMS})
            analysis.run_analysis(analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": a}})["id"])
        code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": SQL, "bindings": {"t": b}}))
        assert code == 0, saved
        if legacy:  # what main's analysis-run filed for the session
            revision = next(row for row in task.sessions() if row["session_id"] == "sess")["context_revision"]
            run = analysis.run_analysis(saved["id"], session_id="sess", context_revision=revision)
        else:
            code, run = _cli(capsys, var, "analysis-run", "--analysis", saved["id"])
            assert code == 0, run
        manager.analysis_requirements_save({"question": "收入", "scope": {"period": "2026-08"}, "bindings": {"t": b},
                                            "items": ITEMS, "parent_id": head["id"], "change_reason": "回到总账"})
        with monkeypatch.context() as main:
            if legacy:  # main's draft save read the run as stored
                main.setattr(AnalysisStore, "run_in_view", lambda self, run, allowed, *, cache=None: run,
                             raising=False)
            code, draft = _cli(capsys, var, "analysis-draft", "--spec", json.dumps(
                {"title": "收入", "body": "收入 100。", "run_ids": [run["id"]], "claims": [_claim(run)]}))
        assert code == 0, draft
        stored = [run["reproducibility_status"], run["requirements_id"] == head["id"],
                  analysis.get_draft(draft["id"])["reproducibility_status"]]
        code, state = _cli(capsys, var, "analysis-state")
        code, shown = _cli(capsys, var, "report-draft-read", "--draft", draft["id"])
        listed = next(row for row in state["runs"] if row["id"] == run["id"])
        read = {"run": {key: listed.get(key) for key in ("reproducibility_status", "requirements_id",
                                                         "requirements_semantic_fingerprint")},
                "drafts": [next(row for row in state["drafts"] if row["id"] == draft["id"])["reproducibility_status"],
                           shown["reproducibility_status"]]}
        assert _shows([state, shown], [head["id"], head["semantic_fingerprint"]] if legacy else []) == []
        return {"stored": stored, "read": _normalized(json.loads(json.dumps(read).replace(
            visible["semantic_fingerprint"], "<fingerprint>")))}

    legacy, alone = world(tmp_path / "legacy", True), world(tmp_path / "alone", False)
    assert legacy["stored"] == ["reproducible", True, "reproducible"]
    assert alone["stored"] == ["unverified", True, "unverified"]
    assert legacy["read"] == alone["read"]
    assert json.loads(alone["read"]) == {"run": {"reproducibility_status": "unverified", "requirements_id": "<id0>",
                                                 "requirements_semantic_fingerprint": "<fingerprint>"},
                                         "drafts": ["unverified", "unverified"]}
