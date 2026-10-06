"""A session reads every run as it would have saved it from the files it may read.

A run another reader saved is pinned to the requirements version current when it started, its rows declared against
that version, and its reproducibility decided by the earlier runs of its fingerprint that reader could read. A session
reads it as saved where the versions and runs outside its snapshot ceiling were never saved: pinned to the version
current then among those it, and a session that saved the run, may read, not one saved while the run ran, with that
version's fingerprint and rows, and reproducible by the runs it may read. So does every saved analysis, draft,
completion receipt and export built on such a run, and so does what the session saves from it: a draft another session
saved, which read its runs otherwise, reads judged as the session's own save would have judged it. No run a session
reads carries the stored record's integrity hash. The manager (no session) reads every run as stored.

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
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from foundry.analysis import AnalysisStore, _hash, _new
from foundry.finance_completion import completion_chain_key
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
    return SimpleNamespace(var=var, task=task, analysis=analysis, a=a, h=h, manager=manager, visible=visible,
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


def _pins(versions: dict[str, dict], runs: list[dict]) -> list[tuple]:
    """Each run's pin and fingerprint, and its row declaration's, by the names of ``versions``: a fingerprint by every
    version saved with it, so that two worlds read alike where they pin alike."""
    ids = {row["id"]: name for name, row in versions.items()}
    prints: dict[str, list[str]] = {}
    for name, row in versions.items():
        prints.setdefault(row["semantic_fingerprint"], []).append(name)
    names = {**ids, **{fingerprint: "=".join(shared) for fingerprint, shared in prints.items()}}
    return [tuple(names.get(value, value) for value in (
        run["requirements_id"], run["requirements_semantic_fingerprint"],
        *((run["row_declarations"]["requirements_id"], run["row_declarations"]["requirements_fingerprint"])
          if run.get("row_declarations") else ()))) for run in runs]


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


def test_a_session_runs_an_analysis_naming_a_version_it_may_not_read_as_it_reads_it(tmp_path, capsys, fake_runner):
    """A saved SQL analysis or script naming Hv reads to the session as naming V, and runs so: pinned to V, its rows
    declared against V, as where the manager named V outright."""
    ran = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys)
        pin = (world.hidden or world.visible)["id"]
        as_manager = {"session": None, "task": world.task.id}
        code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}, "requirements_id": pin}), **as_manager)
        assert code == 0, saved
        code, script = _cli(capsys, world.var, "analysis-script", "--spec", json.dumps(
            {"code": "print(1)", "bindings": {"gl": world.a}, "result_file": "result.json", "requirements_id": pin}),
            **as_manager)
        assert code == 0, script
        runs = {}
        for way, analysis_id in (("sql", saved["id"]), ("script", script["analysis_id"])):
            code, runs[way] = _cli(capsys, world.var, "analysis-run", "--analysis", analysis_id)
            assert code == 0, runs[way]
        assert [run["requirements_id"] for run in runs.values()] == [world.visible["id"]] * 2
        assert runs["script"]["row_declarations"]["rows"][0]["estimate"] is False
        assert _shows(runs, world.secrets) == []
        ran.append(_named(world, {way: {key: run.get(key) for key in PINNED} for way, run in runs.items()}))
    assert ran[0] == ran[1]


def test_a_session_reads_a_run_of_an_analysis_naming_a_version_it_may_not_read_by_the_version_current_when_it_ran(
        tmp_path, capsys, fake_runner):
    """The manager runs SQL saved naming Hv (V where Hv was never saved) while V3, which asks otherwise, is current; V4
    then asks what V asked. The session reads the run as captured under V3, not V: not bound to V4, its own draft's
    receipt included."""
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys)
        as_manager = {"session": None, "task": world.task.id}
        code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a},
             "requirements_id": (world.hidden or world.visible)["id"]}), **as_manager)
        assert code == 0, saved
        spec = {"scope": {"period": "2026-08"}, "bindings": {"gl": world.a}, "items": ITEMS, "change_reason": "复核"}
        then = world.manager.analysis_requirements_save(
            {**spec, "question": "收入（复核）", "parent_id": world.current["id"]})
        code, run = _cli(capsys, world.var, "analysis-run", "--analysis", saved["id"], **as_manager)
        assert code == 0, run
        again = world.manager.analysis_requirements_save({**spec, "question": "收入", "parent_id": then["id"]})
        assert again["semantic_fingerprint"] == world.visible["semantic_fingerprint"] != then["semantic_fingerprint"]
        code, state = _cli(capsys, world.var, "analysis-state")
        assert code == 0
        [listed] = [row for row in state["runs"] if row["id"] == run["id"]]
        assert (listed["requirements_id"], listed["requirements_semantic_fingerprint"]) == (
            world.visible["id"], then["semantic_fingerprint"])
        receipt = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess").save_explanation_draft(
            {"body": "会话稿：Falcon 收入 100。", "run_ids": [run["id"]]})["completion"]
        assert _shows([state, receipt], world.secrets) == []
        read.append(_verdict(receipt))
    assert read[0] == read[1] and read[0][4] == 0 and "requirements_run_outdated" in read[0][5]


def test_a_session_reads_a_run_of_an_analysis_naming_a_first_version_it_may_not_read_as_its_own_run_of_it(
        tmp_path, capsys, fake_runner):
    """Hv, on H, is the first version, and V2 on A its child. The manager saves SQL and a script naming Hv (where Hv
    was never saved, naming none) and runs them while V2 is current. No version the session may read is older than Hv:
    it reads the runs, as its own run of the SQL, pinned to V2, which they ran under, the script's rows declared
    against V2, and files its receipt on them so."""
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        root = tmp_path / name
        var = root / "var"
        task = TaskStore(var).create(title="首个要求版本")
        analysis = AnalysisStore(task)
        a = analysis.add_dataset(_csv(root / "a.csv", [("revenue", "2026-08", "Falcon", "100", "CNY", "元")]), name="总账")["id"]
        task.record_session("sess", role="analysis")
        h = analysis.add_dataset(_csv(root / "h.csv", [("revenue", "2026-07", "Falcon", "100", "CNY", "元")]), name="薪酬")["id"]
        manager = FinanceStore(task)
        first = manager.analysis_requirements_save({
            "question": "Falcon 项目", "scope": {"period": "2026-07"}, "bindings": {"payroll": h},
            "items": HIDDEN_ITEMS}) if hidden else None
        current = manager.analysis_requirements_save({"question": "收入", "scope": {"period": "2026-08"},
                                                      "bindings": {"gl": a}, "items": ITEMS,
                                                      **({"parent_id": first["id"]} if first else {})})
        named = {"requirements_id": first["id"]} if first else {}
        as_manager = {"session": None, "task": task.id}
        code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": a}, **named}), **as_manager)
        assert code == 0, saved
        runs = [_cli(capsys, var, "analysis-run", "--analysis", saved["id"], **as_manager)[1],
                _cli(capsys, var, "analysis-script", "--spec", json.dumps(
                    {"code": "print(1)", "bindings": {"gl": a}, "result_file": "result.json", **named}),
                    **as_manager)[1]]
        assert [run["requirements_id"] for run in runs] == [(first or current)["id"]] * 2
        code, own = _cli(capsys, var, "analysis-run", "--analysis", saved["id"])
        assert code == 0, own
        code, state = _cli(capsys, var, "analysis-state")
        assert code == 0
        listed = {run["id"]: run for run in state["runs"]}
        receipt = FinanceStore(task, snapshot_ids=[a], session_id="sess").save_explanation_draft(
            {"body": "会话稿：Falcon 收入 100。", "run_ids": [run["id"] for run in runs]})["completion"]
        assert _shows([state, receipt], [h, *([first["id"], first["semantic_fingerprint"]] if first else [])]) == []
        read.append((_pins({"V2": current}, [listed[run["id"]] for run in [*runs, own]]), _verdict(receipt)))
    assert read[0] == read[1]
    assert read[0][0] == [("V2", "V2"), ("V2", "V2", "V2", "V2"), ("V2", "V2")]
    assert "requirements_run_outdated" not in read[0][1][5]


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


def test_a_replay_of_another_reader_s_save_is_answered_with_the_receipt_already_filed(tmp_path, capsys, fake_runner):
    """A save is replayed by its request and the current version, whoever sends it: the manager replays a session's
    save, and a session the manager's. Where Hv held an item more, the session reads V2 with another fingerprint than
    the stored one, so the two chain the same draft and check otherwise. Each is still handed the receipt already filed
    and files none, as on main; the session reads it as where Hv was never saved."""
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys, extra_item=True)
        session = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess")
        replays = []
        for first, then, body in ((session, world.manager, "会话稿：Falcon 收入 100。"),
                                  (world.manager, session, "经理稿：Falcon 收入 100。")):
            saved = first.save_explanation_draft({**world.draft, "body": body})
            stored = world.analysis._list("completions")
            replayed = then.save_explanation_draft({**world.draft, "body": body})
            assert world.analysis._list("completions") == stored
            assert (replayed["replayed"], replayed["id"], replayed["completion"]["id"]) == (
                True, saved["id"], saved["completion"]["id"])
            replays.append(replayed)
        assert _shows(replays[1], world.secrets) == []
        read.append(_verdict(replays[1]["completion"]))
    assert read[0] == read[1] == ("needs_review", 1, "no_progress", False, 3, ISSUES)


# --- a completion chain on such runs ----------------------------------------------------------------------------------


@pytest.mark.parametrize("extra_item", [False, True])
def test_a_session_reads_a_completion_chain_on_such_runs_as_where_the_version_was_never_saved(
        tmp_path, capsys, fake_runner, extra_item):
    """Each receipt is judged a stall against the one before it: as the session reads that one, not as stored. Where
    Hv held an item more, V2's stored fingerprint covers it, and the manager's receipts are filed under it: the session
    reads them, their key and their chain under V2's fingerprint as it reads it, and files its own receipt there."""
    from foundry.evidence_labels import EVIDENCE_FIELDS

    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys, extra_item=extra_item)
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
        drafts = {row["id"]: row for row in state["drafts"]}
        for receipt in [*receipts.values(), own["completion"]]:
            draft = drafts.get(receipt["draft_id"]) or own
            shown = {key: value for key, value in draft["explanation_check"].items() if key not in EVIDENCE_FIELDS}
            assert receipt["requirements_semantic_fingerprint"] == world.visible["semantic_fingerprint"]
            assert receipt["chain_key"] == _hash(
                {"requirements_semantic_fingerprint": world.visible["semantic_fingerprint"]})
            assert receipt["input_key"] == _hash({
                "chain_key": receipt["chain_key"], "draft_id": draft["id"], "draft_content_hash": draft["content_hash"],
                "quality": shown, "completion_policy_version": receipt["completion_policy_version"]})
        # The session files its own receipt as it reads it.
        stored = world.analysis._get("completions", own["completion"]["id"])
        assert {key: stored[key] for key in ("requirements_semantic_fingerprint", "chain_key")} == {
            key: own["completion"][key] for key in ("requirements_semantic_fingerprint", "chain_key")}
        if hidden:
            assert [_verdict(draft["completion"])[4] for draft in managed] == [0, 0, 0]
            assert {draft["completion"]["requirements_semantic_fingerprint"] for draft in managed} == {
                world.current["semantic_fingerprint"]}
    assert read[0] == read[1]
    assert read[0] == ([("repair_available", 0, None, True, 3, ISSUES), ("needs_review", 1, "no_progress", False, 3, ISSUES),
                        ("needs_review", 2, "no_progress", False, 3, ISSUES)],
                       ("needs_review", 2, "no_progress", False, 3, ISSUES))


def test_a_session_reads_a_receipt_judging_again_only_the_one_before_it(tmp_path, capsys, fake_runner, monkeypatch):
    """A stall is judged on the receipt before alone: each receipt of a chain on such runs reads assessing it and the
    one before it again, however many came before them."""
    import foundry.finance_completion as completion

    world = _pinned_world(tmp_path, True, capsys)
    receipts = [_session_draft(world, f"会话稿{index}：Falcon 收入 100。")["completion"] for index in "甲乙丙丁戊"]
    calls = []
    assess = completion.assess_completion
    monkeypatch.setattr(completion, "assess_completion",
                        lambda *args, **kwargs: calls.append(args[1]["id"]) or assess(*args, **kwargs))
    session = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess")
    read = []
    for receipt in receipts:
        calls.clear()
        shown = session._readable_receipt(world.analysis._get("completions", receipt["id"]))
        read.append((len(calls), _verdict(shown)[:4]))
    assert read == [(1, ("repair_available", 0, None, True)), (2, ("needs_review", 1, "no_progress", False)),
                    *[(2, ("needs_review", 2, "no_progress", False))] * 3]


def test_a_session_judging_receipts_again_reads_a_version_s_support_once_a_read(
        tmp_path, capsys, fake_runner, monkeypatch):
    """Every receipt on such runs reads judged again, each on the support of V2, its version: which paths V2's files,
    contexts and runs leave open (with_input_gaps). None of them changes within one read, so a listing assesses that
    support, and lists the runs for it, once however many receipts it judges again."""
    import foundry.finance_completion as completion
    import foundry.finance_requirement_support as support

    world = _pinned_world(tmp_path, True, capsys)
    for index in "甲乙丙丁":
        _session_draft(world, f"会话稿{index}：Falcon 收入 100。")
    assessed, supported, listed = [], [], []
    assess, list_kind, assess_support = (completion.assess_completion, AnalysisStore._list,
                                         support.assess_requirement_support)
    monkeypatch.setattr(completion, "assess_completion",
                        lambda *args, **kwargs: assessed.append(args[1]["id"]) or assess(*args, **kwargs))
    monkeypatch.setattr(support, "assess_requirement_support",
                        lambda analysis, spec: supported.append(spec["id"]) or assess_support(analysis, spec))
    monkeypatch.setattr(AnalysisStore, "_list", lambda self, kind: listed.append(kind) or list_kind(self, kind))
    code, state = _cli(capsys, world.var, "analysis-state")
    assert code == 0 and len(state["completions"]) == 4
    assert len(assessed) == 4 and supported == [world.current["id"]]
    # Once for the read, once for the support.
    assert listed.count("runs") == 2


def _legacy_chain(root: Path, hidden: bool, cites: tuple[str, str], capsys, monkeypatch) -> list[tuple]:
    """The manager asks for control totals on D1, inside the session, runs an account total on it, then saves the same
    version again and runs it once more (``stored``). Under policy 12 it saves two drafts citing one of the runs each,
    the control totals left unanswered. With ``hidden``, Hv on H was current when the first run started (``pinned``),
    and the manager ran control totals on D1 and D2 before Hv and again, scoped otherwise, between the drafts: each
    draft's check names the ones then filed. What the session reads of each receipt."""
    from foundry import finance_completion, finance_requirements

    var = root / "var"
    task = TaskStore(var).create(title="控制合计")
    analysis = AnalysisStore(task)
    manager = FinanceStore(task)
    row = {"account_code": "6001", "management_account": "revenue", "amount": 100, "period": "2026-09",
           "organization": "O1", "currency": "CNY"}
    d1 = analysis.add_dataset(_ledger(root / "gl.json", [row]), name="gl")["id"]
    task.record_session("sess", role="analysis")
    spec = {"question": "九月控制合计", "scope": {"period": "2026-09", "organization": "O1", "currency": "CNY"},
            "bindings": {"gl": d1}, "items": [{"id": "ct", "metric": "control_totals"}]}
    head = manager.analysis_requirements_save(spec)
    context = manager.save_context({"bindings": {"gl": d1}, "scopes": {"gl": spec["scope"]}})
    secrets: list[str] = []
    if hidden:
        d2 = analysis.add_dataset(_ledger(root / "deal.json", [
            {**row, "account_code": "9999", "management_account": "acquisition_payout", "amount": 7777777,
             "period": "2026-07", "organization": "SECRET-SUBSIDIARY", "currency": "USD"}]), name="并购")["id"]
        h = analysis.add_dataset(_ledger(root / "h.json", [{**row, "management_account": "expense", "amount": 999}]),
                                 name="薪酬")["id"]

        def control_totals(organization: str) -> str:
            wider = manager.save_context({"bindings": {"gl": d1, "hidden": d2}, "scopes": {
                "gl": spec["scope"], "hidden": {"organization": organization, "currency": "USD", "period": "2026-07"}}})
            return manager.run_metric({"context_id": wider["id"], "metric": {"kind": "control_totals"}})["id"]

        secrets += [d2, h, control_totals("SECRET-SUBSIDIARY"), "SECRET-SUBSIDIARY", "SECRET-OTHER", "7777777"]
        head = manager.analysis_requirements_save({**spec, "question": "薪酬控制合计", "bindings": {"payroll": h},
                                                   "parent_id": head["id"], "change_reason": "换薪酬"})
    account_total = {"context_id": context["id"], "metric": {"kind": "account_total", "accounts": ["revenue"]}}
    runs = {"pinned": manager.run_metric(account_total)["id"]}
    manager.analysis_requirements_save({**spec, "parent_id": head["id"], "change_reason": "回到总账"})
    runs["stored"] = manager.run_metric(account_total)["id"]
    drafts = []
    with monkeypatch.context() as old:
        old.setattr(finance_requirements, "_within_files", lambda files, bindings: True)
        old.setattr(finance_completion, "COMPLETION_POLICY_VERSION", 12)
        for body, way in zip(("控制合计待核。", "控制合计待核。。"), cites):
            if drafts and hidden:
                secrets.append(control_totals("SECRET-OTHER"))
            drafts.append(manager.save_explanation_draft({"body": body, "run_ids": [runs[way]]}))
    code, state = _cli(capsys, var, "analysis-state")
    assert code == 0, state
    assert _shows(state, secrets) == []
    receipts = {row["draft_id"]: row for row in state["completions"]}
    return [_verdict(receipts[draft["id"]])[:4] for draft in drafts]


@pytest.mark.parametrize("cites", [("pinned", "pinned"), ("stored", "pinned"), ("pinned", "stored"),
                                   ("stored", "stored")])
def test_a_session_judges_a_stall_on_checks_before_policy_13_without_runs_it_may_not_read(
        tmp_path, capsys, monkeypatch, cites):
    """Each receipt reads judged over its draft's check as the session reads it, its issues naming none of the runs it
    may not read, whether or not the session reads its cited run as stored: the second stalls on the first, as where
    neither those runs nor Hv were saved. The manager stored it otherwise, the second run's scope in its issues."""
    read = [_legacy_chain(tmp_path / str(hidden), hidden, cites, capsys, monkeypatch) for hidden in (False, True)]
    assert read[0] == read[1] == [("repair_available", 0, None, True), ("needs_review", 1, "no_progress", False)]


def test_a_session_verifies_the_runs_a_check_before_policy_13_names_once_a_read(tmp_path, capsys, monkeypatch):
    """A check before policy 13 named engine runs on files the session may not read, and the session reads it without
    them (finance_requirements.requirements_in_view) on every draft and receipt it reads it on: it reads each such run,
    its outputs verified, once a read (verified_run)."""
    _legacy_chain(tmp_path, True, ("pinned", "pinned"), capsys, monkeypatch)
    calls = []
    get_run = AnalysisStore.get_run
    monkeypatch.setattr(AnalysisStore, "get_run", lambda self, run_id: calls.append(run_id) or get_run(self, run_id))
    code, state = _cli(capsys, tmp_path / "var", "analysis-state")
    assert code == 0 and len(state["drafts"]) == len(state["completions"]) == 2
    # The control totals the manager ran on the hidden files, which neither draft cites.
    hidden = set(calls) - {run["id"] for run in state["runs"]}
    assert len(hidden) == 2 and [calls.count(run_id) for run_id in hidden] == [1, 1]


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


def test_a_session_s_receipt_reuses_runs_pinned_where_a_version_it_may_not_read_held_an_item_more(
        tmp_path, capsys, fake_runner):
    """V2's stored fingerprint covers the item it removed that only Hv held; the session reads V2 with the fingerprint
    over what it reads V2 removed, V's, so the runs it reads pinned to V bind to it."""
    filed = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys, extra_item=True)
        filed.append(_verdict(_session_draft(world, "会话稿：Falcon 收入 100。")["completion"]))
    assert filed[0] == filed[1] and filed[0][4] == 3


def test_a_session_reads_runs_captured_under_such_a_version_with_the_fingerprint_it_reads(
        tmp_path, capsys, fake_runner):
    """With V2 current, the manager runs a script and SQL, and the session runs its own; V3 then repeats V2. The
    session saves and reads every run, the scripts' declarations, the current version beside them and the receipts on
    them as where Hv was never saved: by V's fingerprint, which is V2's and V3's as it reads them, and its receipt
    counts the manager's earlier ones of that chain. So does a script the manager runs under a later version on H,
    which reads pinned to V3. The manager reads hers as stored, and the session's as the session saved them."""
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys, extra_item=True)
        as_manager = {"session": None, "task": world.task.id}
        script = {"code": "print(1)", "bindings": {"gl": world.a}, "result_file": "result.json"}
        sql = {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}}
        runs = {"script": _cli(capsys, world.var, "analysis-script", "--spec", json.dumps(script), **as_manager)[1]}
        code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(sql), **as_manager)
        runs["sql"] = _cli(capsys, world.var, "analysis-run", "--analysis", saved["id"], **as_manager)[1]
        code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(sql))
        runs["own"] = _cli(capsys, world.var, "analysis-run", "--analysis", saved["id"])[1]
        runs["own script"] = _cli(capsys, world.var, "analysis-script", "--spec", json.dumps(script))[1]
        assert [run["requirements_id"] for run in runs.values()] == [world.current["id"]] * 4
        returned = {way: {key: runs[way].get(key) for key in PINNED} for way in ("own", "own script")}
        world.manager.analysis_requirements_save({"question": "收入", "scope": {"period": "2026-08"},
                                                  "bindings": {"gl": world.a}, "items": ITEMS,
                                                  "parent_id": world.current["id"]})
        managed = world.manager.save_explanation_draft({"body": "经理稿：Falcon 收入 100。", "run_ids": [runs["own"]["id"]]})
        for index in "甲乙":
            world.manager.save_explanation_draft({"body": f"经理稿{index}：收入 100。", "run_ids": [runs["sql"]["id"]]})
        own = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess").save_explanation_draft(
            {"body": "会话稿：收入 100。", "run_ids": [runs["sql"]["id"]]})
        if hidden:
            world.manager.analysis_requirements_save({
                "question": "Falcon 项目", "scope": {"period": "2026-07"}, "bindings": {"payroll": world.h},
                "parent_id": world.manager.analysis_requirements_list({})["current"]["id"], "items": HIDDEN_ITEMS})
        runs["later"] = _cli(capsys, world.var, "analysis-script", "--spec", json.dumps(script), **as_manager)[1]
        code, state = _cli(capsys, world.var, "analysis-state")
        assert code == 0
        listed = {run["id"]: run for run in state["runs"]}
        receipts = {row["draft_id"]: row for row in state["completions"]}
        assert _shows(state, world.secrets) == []
        assert {row["semantic_fingerprint"] for row in state["requirements"]} == {world.visible["semantic_fingerprint"]}
        read.append(_named(world, {
            "runs": {way: {key: listed[run["id"]].get(key) for key in PINNED} for way, run in runs.items()},
            "returned": returned, "receipt": _verdict(receipts[managed["id"]]),
            "own": [_verdict(own["completion"]), _verdict(receipts[own["id"]])]}))
        if hidden:
            # The manager reads her runs and V2 as stored, and the session's run as it was saved.
            stored = world.current["semantic_fingerprint"]
            assert stored != world.visible["semantic_fingerprint"]
            code, managed_state = _cli(capsys, world.var, "analysis-state", session=None, task=world.task.id)
            stored_runs = {run["id"]: run for run in managed_state["runs"]}
            assert [stored_runs[run["id"]]["requirements_semantic_fingerprint"] for run in runs.values()][:4] == [
                stored, stored, *[world.visible["semantic_fingerprint"]] * 2]
            assert [stored_runs[runs[way]["id"]]["row_declarations"]["requirements_fingerprint"]
                    for way in ("script", "own script")] == [stored, world.visible["semantic_fingerprint"]]
    assert read[0] == read[1]
    shown = json.loads(read[0])
    pins = [*shown["runs"].values(), *shown["returned"].values()]
    declarations = [pin["row_declarations"] for pin in pins if pin["row_declarations"]]
    fingerprints = {pin["requirements_semantic_fingerprint"] for pin in pins}
    fingerprints |= {declaration["requirements_fingerprint"] for declaration in declarations}
    fingerprints |= {declaration["current_requirements"]["fingerprint"] for declaration in declarations
                     if "current_requirements" in declaration}
    assert len(declarations) == 4 and fingerprints == {"<fingerprint>"}
    # The manager's receipt on the session's run reads as the session's own save would have filed it: bound to V3.
    assert shown["receipt"][4] == 1 and "requirements_run_outdated" not in shown["receipt"][5]
    assert shown["own"][0] == shown["own"][1] and shown["own"][0][1:5] == [2, "repair_budget_exhausted", False, 1]


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
    # Each cited run once for whether the session may read each draft, and once in the read for whether it may read the
    # receipts whole.
    assert len(calls) == (4 + 1) * len(world.draft["run_ids"])
    # The versions and runs are listed once for the whole read, and each record's pin is read once, by the listing:
    # no draft or receipt lists or reads them again.
    assert listed.count("requirements") == listed.count("runs") == 1 and len(pins) == len(set(pins))


def test_a_session_save_with_no_version_hidden_assesses_its_draft_once(tmp_path, capsys, fake_runner, monkeypatch):
    """A save assesses its draft once, to file the receipt, and returns that receipt and the one before it as filed:
    with every version readable, neither is judged again, whichever copy of the version the assessment read first."""
    import foundry.finance_completion as completion
    from foundry.finance_completion_operations import CompletionOperationStore

    world = _pinned_world(tmp_path, False, capsys)
    session = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess")
    operation = CompletionOperationStore(world.task, "sess", session.allowed).begin(
        "request-1", policy={"max_repairs": 2})
    assessed = []
    assess = completion.assess_completion
    monkeypatch.setattr(completion, "assess_completion",
                        lambda *args, **kwargs: assessed.append(args[1]["id"]) or assess(*args, **kwargs))
    saves = [lambda index=index: _session_draft(world, f"会话稿{index}：Falcon 收入 100。") for index in "甲乙丙"]
    saves.append(lambda: session.save_completion_draft(operation["id"], "call-1", world.draft))
    counts = []
    for save in saves:
        assessed.clear()
        assert save()["completion"]
        counts.append(len(assessed))
    assert counts == [1] * 4


def test_a_session_declares_a_run_pinned_to_a_version_it_may_not_read_again_once_a_read(
        tmp_path, capsys, fake_runner, monkeypatch):
    """The script run, pinned to Hv, reads to the session with its rows declared again from its archived result
    against V. That result is read once for a listing however many drafts and receipts cite the run, once for a save
    or its retry and the draft and receipt it returns, and not at all for the Excel add-in, which lists only finance
    runs."""
    import foundry.result_semantics as result_semantics
    from foundry.excel_bridge import BridgeTokenAuthority, ExcelBridgeApp
    from foundry.finance_completion_operations import CompletionOperationStore

    world = _pinned_world(tmp_path, True, capsys)
    for index in "甲乙丙":
        _session_draft(world, f"会话稿{index}：Falcon 收入 100。")
    session = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess")
    operation = CompletionOperationStore(world.task, "sess", session.allowed).begin(
        "request-1", policy={"max_repairs": 2})
    parsed = []
    archived = result_semantics._archived_result
    monkeypatch.setattr(result_semantics, "_archived_result",
                        lambda analysis, run: parsed.append(run["id"]) or archived(analysis, run))
    authority = BridgeTokenAuthority(b"local-test-secret-local-test-secret")
    token = authority.issue(task_id=world.task.id, session_id="sess", ttl_seconds=60)
    app = ExcelBridgeApp(var_root=world.var, token_authority=authority)
    requests = {
        "state": lambda: _cli(capsys, world.var, "analysis-state")[0] == 0,
        "save": lambda: bool(_session_draft(world, "会话稿丁：Falcon 收入 100。")["completion"]),
        "retry": lambda: _session_draft(world, "会话稿丁：Falcon 收入 100。")["replayed"],
        "operation": lambda: "replayed" not in session.save_completion_draft(operation["id"], "call-1", world.draft),
        "operation retry": lambda: session.save_completion_draft(operation["id"], "call-1", world.draft)["replayed"],
        "excel": lambda: app.handle("GET", "/api/context", {"Authorization": f"Bearer {token}"}, b"{}")[0] == 200,
    }
    read = {}
    for name, request in requests.items():
        parsed.clear()
        assert request()
        read[name] = list(parsed)
    script = world.runs["script"]["id"]
    assert read == {**dict.fromkeys(requests, [script]), "excel": []}


def test_a_session_judges_no_draft_again_whose_runs_every_reader_of_it_reads_as_stored(
        tmp_path, capsys, fake_runner, monkeypatch):
    """Hv is hidden from the session, not from W, which may read every file. A draft citing a run pinned to V2 rests
    on A alone, and whoever may read A reads that run as stored: neither session assesses its receipt again, whoever
    saved it."""
    import foundry.evidence_labels as evidence_labels
    import foundry.finance_completion as completion

    world = _pinned_world(tmp_path, True, capsys)
    as_manager = {"session": None, "task": world.task.id}
    code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
        {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}}), **as_manager)
    run = _cli(capsys, world.var, "analysis-run", "--analysis", saved["id"], **as_manager)[1]
    assert run["requirements_id"] == world.current["id"]
    world.task.record_session("wide", role="analysis")
    world.manager.save_explanation_draft({"body": "经理稿：收入 100。", "run_ids": [run["id"]]})
    FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess").save_explanation_draft(
        {"body": "会话稿：收入 100。", "run_ids": [run["id"]]})
    for name in ("assess_completion", "declared_row_estimates"):
        module = completion if name == "assess_completion" else evidence_labels
        monkeypatch.setattr(module, name, lambda *args, name=name, **kwargs: pytest.fail(f"{name} read again"),
                            raising=False)
    for session in ("sess", "wide"):
        code, state = _cli(capsys, world.var, "analysis-state", session=session)
        assert code == 0 and len(state["drafts"]) == len(state["completions"]) == 2


# --- the version a run started under, among those the session that ran it may read ---------------------------------


def _meanwhile(monkeypatch) -> list:
    """The saves to make while the next SQL query or script runs: after its run captured its version, before it
    commits. Each runs once."""
    import foundry.analysis as module
    import foundry.runner as runner

    pending: list = []

    def saving(execute):
        def run(*args, **kwargs):
            while pending:
                pending.pop(0)()
            return execute(*args, **kwargs)
        return run

    monkeypatch.setattr(module, "execute_sql", saving(module.execute_sql))
    monkeypatch.setattr(runner, "run_script", saving(runner.run_script))
    return pending


@pytest.mark.parametrize("engine", ["sql", "script"])
def test_a_session_reads_a_run_by_the_version_it_started_under_not_one_saved_while_it_ran(
        tmp_path, capsys, fake_runner, monkeypatch, engine):
    """A run captures the version current when it starts, and takes its place among the versions when it commits. The
    manager saves a version on A while each of three runs: hers naming V, started while Hv on H was the head, hers
    naming none, started under Hv2 on H, and the session's, started under V5, while V6 and then Hv3 on H follow. The
    session reads each, and files its receipt on each, as where no version on H was ever saved: started under V, V3
    and V5, bound to a later version that asks the same."""
    pending = _meanwhile(monkeypatch)
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        root = tmp_path / name
        var = root / "var"
        task = TaskStore(var).create(title="运行时保存的版本")
        analysis = AnalysisStore(task)
        a = analysis.add_dataset(_csv(root / "a.csv", [("revenue", "2026-08", "Falcon", "100", "CNY", "元")]), name="总账")["id"]
        task.record_session("sess", role="analysis")
        h = analysis.add_dataset(_csv(root / "h.csv", [("revenue", "2026-07", "Falcon", "100", "CNY", "元")]), name="薪酬")["id"]
        manager = FinanceStore(task)
        versions: dict[str, dict] = {}

        def save(label: str, question: str, *, on_h: bool = False) -> None:
            parent = {"parent_id": list(versions.values())[-1]["id"], "change_reason": "复核"} if versions else {}
            versions[label] = manager.analysis_requirements_save({
                "question": question, "scope": {"period": "2026-08"}, **parent,
                "bindings": {"payroll": h} if on_h else {"gl": a}, "items": HIDDEN_ITEMS if on_h else ITEMS})

        def run(session: str | None, **named) -> dict:
            who = {"session": session, "task": None if session else task.id}
            if engine == "script":
                code, ran = _cli(capsys, var, "analysis-script", "--spec", json.dumps(
                    {"code": "print(1)", "bindings": {"gl": a}, "result_file": "result.json", **named}), **who)
            else:
                code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps(
                    {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": a}, **named}), **who)
                assert code == 0, saved
                code, ran = _cli(capsys, var, "analysis-run", "--analysis", saved["id"], **who)
            assert code == 0, ran
            return ran

        save("V", "收入")
        if hidden:
            save("Hv", "Falcon 项目", on_h=True)
        pending.append(lambda: save("V3", "收入（复核）"))
        runs = [run(None, requirements_id=versions["V"]["id"])]
        if hidden:
            save("Hv2", "Falcon 薪酬", on_h=True)
        pending.append(lambda: save("V5", "收入（再复核）"))
        runs.append(run(None))
        pending.extend([lambda: save("V6", "收入（三复核）"), *([lambda: save("Hv3", "Falcon 奖金", on_h=True)]
                                                            if hidden else [])])
        runs.append(run("sess"))
        assert not pending and [run["requirements_id"] for run in runs] == [
            versions[label]["id"] for label in (("V", "Hv2", "V5") if hidden else ("V", "V3", "V5"))]
        code, state = _cli(capsys, var, "analysis-state")
        assert code == 0
        listed = {row["id"]: row for row in state["runs"]}
        receipts = []
        for index, (ran, question) in enumerate(zip(runs, ("收入", "收入（复核）", "收入（再复核）"))):
            save(f"again{index}", question)
            receipts.append(_verdict(FinanceStore(task, snapshot_ids=[a], session_id="sess").save_explanation_draft(
                {"body": f"会话稿{index}：Falcon 收入 100。", "run_ids": [ran["id"]]})["completion"]))
        secrets = [value for label, row in versions.items() if label.startswith("Hv")
                   for value in (row["id"], row["semantic_fingerprint"])]
        assert _shows(state, [h, *secrets]) == []
        read.append((_pins({label: row for label, row in versions.items() if not label.startswith("Hv")},
                           [listed[ran["id"]] for ran in runs]), receipts))
    assert read[0] == read[1]
    pins, receipts = read[0]
    started = [("V", "V=again0"), ("V3", "V3=again1"), ("V5", "V5=again2")]
    assert [pin[:2] for pin in pins] == started
    if engine == "script":
        assert [pin[2:] for pin in pins] == started
    assert [receipt[4] for receipt in receipts] == [1] * 3
    assert not any("requirements_run_outdated" in receipt[5] for receipt in receipts)


@pytest.mark.parametrize("saved_after", [None, "before", "check", "basis"])
@pytest.mark.parametrize("saver", ["manager", "session"])
def test_a_session_reads_a_draft_by_the_version_it_was_checked_against_not_one_saved_while_it_was_saved(
        tmp_path, capsys, fake_runner, monkeypatch, saver, saved_after):
    """A draft save checks the draft against the current version, reads its basis, then takes its seq, and no
    requirements save waits on it. The manager saves W on A, a child of V2 that declares the Falcon revenue an estimate,
    before the manager or the session saves a draft citing the runs, or while it does: after the check, or after the
    basis was read. The session reads the draft as where Hv was never saved, by the version it was checked against: W,
    which declares the script row an estimate, where W came first, and V2 either other way."""
    import foundry.evidence_labels as evidence_labels

    basis = evidence_labels.draft_evidence_basis
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys)
        meanwhile: list[dict] = []

        def save_w() -> None:
            spec = {"question": "收入", "scope": {"period": "2026-08"}, "bindings": {"gl": world.a}, "items": [
                {"id": "rev", "metric": "revenue", "label": "收入", "organizations": ["Falcon"],
                 "grain_basis": [{"basis": "estimate", "method": "按收入分摊", "organizations": ["Falcon"]}]}],
                "parent_id": world.current["id"], "change_reason": "估计"}
            # Another writer: the draft save holds completion.lock, which a requirements save never takes.
            thread = threading.Thread(target=lambda: meanwhile.append(
                FinanceStore(world.task).analysis_requirements_save(spec)))
            thread.start()
            thread.join(timeout=30)

        def reading(*args, **kwargs):
            if saved_after == "check" and not meanwhile:
                save_w()
            fields = basis(*args, **kwargs)
            if saved_after == "basis" and not meanwhile:
                save_w()
            return fields

        if saved_after == "before":
            save_w()
        monkeypatch.setattr(evidence_labels, "draft_evidence_basis", reading)
        saved = (world.manager.save_explanation_draft(world.draft) if saver == "manager"
                 else _session_draft(world, world.draft["body"]))
        monkeypatch.setattr(evidence_labels, "draft_evidence_basis", basis)
        assert saved["explanation_check"]["requirements"]["requirements_id"] == (
            meanwhile[0]["id"] if saved_after == "before" else world.current["id"])
        assert [row["seq"] < saved["seq"] for row in meanwhile] == ([True] if saved_after else [])
        script = world.runs["script"]["id"]
        code, state = _cli(capsys, world.var, "analysis-state")
        assert code == 0, state
        [draft] = [row for row in state["drafts"] if row["id"] == saved["id"]]
        code, report = _cli(capsys, world.var, "report-draft-read", "--draft", saved["id"])
        assert code == 0, report
        read.append((_labels_of(draft["explanation_check"], script), _labels_of(report["explanation_check"], script),
                     draft["explanation_check"]["evidence_posture"]))
    assert read[0] == read[1]
    assert read[0][0] == read[0][1] and read[0][0][0][1:] == (
        ("estimate", ["row_declared_estimate"]) if saved_after == "before" else ("unknown", ["run_script"]))


def _apart_world(root: Path):
    """S1 may read A and H1, S2 A and H2: neither may read the other's file. S2 came to read H2 by a context
    revision."""
    var = root / "var"
    task = TaskStore(var).create(title="互不包含的会话")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(root / "a.csv", [("revenue", "2026-08", "Falcon", "100", "CNY", "元")]), name="总账")["id"]
    task.record_session("s2", role="analysis")
    h1 = analysis.add_dataset(_csv(root / "h1.csv", [("revenue", "2026-07", "Falcon", "100", "CNY", "元")]), name="项目")["id"]
    task.record_session("s1", role="analysis")
    h2 = analysis.add_dataset(_csv(root / "h2.csv", [("revenue", "2026-06", "Falcon", "100", "CNY", "元")]), name="薪酬")["id"]
    task.update_session_context("s2", snapshot_ids=[h2])
    assert {row["session_id"]: set(row["snapshot_ids"]) for row in task.sessions()} == {"s1": {a, h1}, "s2": {a, h2}}
    return SimpleNamespace(var=var, task=task, a=a, h1=h1, h2=h2, manager=FinanceStore(task), versions={})


def _save_on(world, label: str, question: str, binding: dict, items: list) -> dict:
    """The manager saves the next requirements version, on ``binding``."""
    parent = {"parent_id": list(world.versions.values())[-1]["id"], "change_reason": "换"} if world.versions else {}
    world.versions[label] = world.manager.analysis_requirements_save(
        {"question": question, "scope": {"period": "2026-08"}, "bindings": binding, "items": items, **parent})
    return world.versions[label]


def _apart_reads(world, capsys, runs: list[dict]) -> tuple:
    """S2 may read H1 too by now. What S1 reads of S2's runs, by the names of the versions on A, and its receipt."""
    world.task.update_session_context("s2", snapshot_ids=[world.h1])
    code, state = _cli(capsys, world.var, "analysis-state", session="s1")
    assert code == 0, state
    listed = {row["id"]: row for row in state["runs"]}
    s1 = next(row for row in world.task.sessions() if row["session_id"] == "s1")["snapshot_ids"]
    receipt = FinanceStore(world.task, snapshot_ids=s1, session_id="s1").save_explanation_draft(
        {"body": "S1 稿：Falcon 收入 100。", "run_ids": [run["id"] for run in runs]})["completion"]
    hidden = [value for label, row in world.versions.items() if label == "Hv2"
              for value in (row["id"], row["semantic_fingerprint"])]
    assert _shows([state, receipt], [world.h2, *hidden]) == []
    return (_pins({label: row for label, row in world.versions.items() if label != "Hv2"},
                  [listed[run["id"]] for run in runs]), _verdict(receipt))


@pytest.mark.parametrize("named", [False, True])
def test_a_session_reads_another_session_s_run_by_the_versions_that_session_may_read(
        tmp_path, capsys, fake_runner, named):
    """The manager saves P on A, then Hv1 on H1 and, but where S1 reads, Hv2 on H2. S2 runs SQL and a script on A,
    naming P with ``named``, and later comes to read H1 too. Where Hv2 was never saved, S2's runs started under P, the
    newest version S2 could read: S1 reads them so, never pinned to or by Hv1, which S2 could not read when they ran,
    and its receipt reuses them under C, which asks what P asked."""
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _apart_world(tmp_path / name)
        _save_on(world, "P", "收入", {"gl": world.a}, ITEMS)
        _save_on(world, "Hv1", "Falcon 项目", {"project": world.h1}, HIDDEN_ITEMS)
        if hidden:
            _save_on(world, "Hv2", "Falcon 薪酬", {"payroll": world.h2}, ITEMS)
        pin = {"requirements_id": world.versions["P"]["id"]} if named else {}
        code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}, **pin}), session="s2")
        assert code == 0, saved
        runs = [_cli(capsys, world.var, "analysis-run", "--analysis", saved["id"], session="s2")[1],
                _cli(capsys, world.var, "analysis-script", "--spec", json.dumps(
                    {"code": "print(1)", "bindings": {"gl": world.a}, "result_file": "result.json", **pin}),
                    session="s2")[1]]
        started = world.versions["P" if named or not hidden else "Hv2"]
        assert [run["requirements_id"] for run in runs] == [started["id"]] * 2
        _save_on(world, "C", "收入", {"gl": world.a}, ITEMS)
        read.append(_apart_reads(world, capsys, runs))
    assert read[0] == read[1]
    assert read[0][0] == [("P", "P=C"), ("P", "P=C", "P", "P=C")]
    assert read[0][1][4] == 2 and "requirements_run_outdated" not in read[0][1][5]


def test_a_session_reads_another_session_s_run_of_an_analysis_naming_a_version_neither_may_read_alike(
        tmp_path, capsys, fake_runner, monkeypatch):
    """Hv1 on H1 is the first version, then, but where S1 reads, Hv2 on H2, then P on A. The manager saves SQL and a
    script naming Hv2, which S1 reads as naming Hv1 (and where Hv2 was never saved, they name Hv1). S2 runs them while
    P is current, and the manager saves P2 and then P3 on A while they run. S2 could read no version older than Hv2:
    S1 reads its runs as S2 ran them where Hv2 was never saved, naming none, so pinned to the version each started
    under, P and P2."""
    pending = _meanwhile(monkeypatch)
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _apart_world(tmp_path / name)
        _save_on(world, "Hv1", "Falcon 项目", {"project": world.h1}, HIDDEN_ITEMS)
        if hidden:
            _save_on(world, "Hv2", "Falcon 薪酬", {"payroll": world.h2}, ITEMS)
        _save_on(world, "P", "收入", {"gl": world.a}, ITEMS)
        pin = {"requirements_id": world.versions["Hv2" if hidden else "Hv1"]["id"]}
        as_manager = {"session": None, "task": world.task.id}
        code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}, **pin}), **as_manager)
        assert code == 0, saved
        code, script = _cli(capsys, world.var, "analysis-script", "--spec", json.dumps(
            {"code": "print(1)", "bindings": {"gl": world.a}, "result_file": "result.json", **pin}), **as_manager)
        assert code == 0, script
        code, state = _cli(capsys, world.var, "analysis-state", session="s1")
        named = {row["id"]: row["requirements_id"] for row in state["analyses"]}
        assert named[saved["id"]] == named[script["analysis_id"]] == world.versions["Hv1"]["id"]
        runs = []
        for analysis_id, label, question in ((saved["id"], "P2", "收入（复核）"),
                                             (script["analysis_id"], "P3", "收入（再复核）")):
            pending.append(lambda label=label, question=question: _save_on(
                world, label, question, {"gl": world.a}, ITEMS))
            code, run = _cli(capsys, world.var, "analysis-run", "--analysis", analysis_id, session="s2")
            assert code == 0, run
            runs.append(run)
        assert [run["requirements_id"] for run in runs] == (
            [world.versions["Hv2"]["id"]] * 2 if hidden else [world.versions["P"]["id"], world.versions["P2"]["id"]])
        read.append(_apart_reads(world, capsys, runs))
    assert read[0] == read[1]
    assert read[0][0] == [("P", "P"), ("P2", "P2", "P2", "P2")]


@pytest.mark.parametrize("lineage", ["middle", "first"])
def test_a_session_reads_an_analysis_another_session_saved_naming_a_version_it_may_not_read_as_that_session_named(
        tmp_path, capsys, fake_runner, monkeypatch, lineage):
    """Hv1 on H1 follows P on A (``middle``) or comes first (``first``), and then, but where S1 reads, Hv2 on H2. S2
    saves SQL and a script on A naming Hv2, and S2 and the manager run the SQL. Where Hv2 was never saved, S2, which
    could read neither H1 nor Hv1, named the newest older version it could read: P, or none. S1 reads the analyses and
    their runs so, never naming or pinned to Hv1, though S2 has since come to read H1 too, and runs, declares and
    files its receipt on them so. The manager also runs SQL S2 saved naming none: that run is pinned to the head it
    captured, not to a version S2 named, so S1 reads it as the manager's capture where Hv2 was never saved, Hv1 or P."""
    get_analysis = AnalysisStore.get_analysis
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _apart_world(tmp_path / name)
        if lineage == "middle":
            _save_on(world, "P", "收入", {"gl": world.a}, ITEMS)
        _save_on(world, "Hv1", "Falcon 项目", {"project": world.h1}, HIDDEN_ITEMS)
        if hidden:
            _save_on(world, "Hv2", "Falcon 薪酬", {"payroll": world.h2}, ITEMS)
        if lineage == "first":
            _save_on(world, "P", "收入", {"gl": world.a}, ITEMS)
        naming = "Hv2" if hidden else "P" if lineage == "middle" else None
        pin = {"requirements_id": world.versions[naming]["id"]} if naming else {}
        code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}, **pin}), session="s2")
        assert code == 0, saved
        code, script = _cli(capsys, world.var, "analysis-script", "--spec", json.dumps(
            {"code": "print(1)", "bindings": {"gl": world.a}, "result_file": "result.json", **pin}), session="s2")
        assert code == 0, script
        analyses = [saved["id"], script["analysis_id"]]
        code, unnamed = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}}), session="s2")
        assert code == 0, unnamed
        manager = {"session": None, "task": world.task.id}
        others = [_cli(capsys, world.var, "analysis-run", "--analysis", analysis_id, **who)[1] for analysis_id, who in (
            (saved["id"], {"session": "s2"}), (saved["id"], manager), (unnamed["id"], manager))]
        _save_on(world, "C", "收入", {"gl": world.a}, ITEMS)
        world.task.update_session_context("s2", snapshot_ids=[world.h1])
        loaded = []
        monkeypatch.setattr(AnalysisStore, "get_analysis",
                            lambda self, analysis_id: loaded.append(analysis_id) or get_analysis(self, analysis_id))
        code, state = _cli(capsys, world.var, "analysis-state", session="s1")
        assert code == 0, state
        # Each analysis is read once, in the listing, whichever runs of it read by what it names.
        assert loaded == []
        listed = {row["id"]: row for row in [*state["analyses"], *state["runs"]]}
        own = []
        for analysis_id in analyses:
            code, run = _cli(capsys, world.var, "analysis-run", "--analysis", analysis_id, session="s1")
            assert code == 0, run
            own.append(run)
        s1 = next(row for row in world.task.sessions() if row["session_id"] == "s1")["snapshot_ids"]
        receipt = FinanceStore(world.task, snapshot_ids=s1, session_id="s1").save_explanation_draft(
            {"body": "S1 稿：Falcon 收入 100。", "run_ids": [run["id"] for run in own]})["completion"]
        hidden_values = [value for label, row in world.versions.items() if label == "Hv2"
                         for value in (row["id"], row["semantic_fingerprint"])]
        assert _shows([state, own, receipt], [world.h2, *hidden_values]) == []
        versions = {label: row for label, row in world.versions.items() if label != "Hv2"}
        ids = {row["id"]: label for label, row in versions.items()}
        # Who saved each analysis shows as it does on a run, alike in both worlds.
        read.append(([(ids.get(listed[analysis_id].get("requirements_id")), listed[analysis_id]["session_id"],
                       listed[analysis_id]["context_revision"]) for analysis_id in analyses],
                     _pins(versions, [*(listed[run["id"]] for run in others), *own]), _verdict(receipt)))
    assert read[0] == read[1]
    named, pins, verdict = read[0]
    if lineage == "middle":
        assert named == [("P", "s2", 2)] * 2
        assert pins == [("P", "P=C"), ("P", "Hv1"), ("Hv1", "Hv1"), ("P", "P=C"), ("P", "P=C", "P", "P=C")]
    else:
        assert named == [(None, "s2", 2)] * 2
        assert pins == [("P", "P=C"), ("P", "P=C"), ("P", "P=C"), ("C", "P=C"), ("C", "P=C", "C", "P=C")]
    assert verdict[4] == (2 if lineage == "middle" else 0) and "requirements_run_outdated" not in verdict[5]


def test_a_session_reads_a_run_of_another_session_s_analysis_by_a_version_its_runner_may_read_too(
        tmp_path, capsys, fake_runner):
    """S1 may read A and H1, S2 A and H2, and S3 all three. Hv1 on H1 follows P on A and then, but where S1 reads, Hv2
    on H2. S3 saves SQL on A naming Hv2 and S2 runs it. Where Hv2 was never saved, S3 named Hv1, as S1 reads its
    analysis, and S2, which may not read Hv1, ran it as naming P. S1 reads S2's run so, pinned to P and not to Hv1,
    which S3 may read but S2 never could, and files its receipt on it so."""
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _apart_world(tmp_path / name)
        world.task.record_session("s3", role="analysis")
        assert set(next(row for row in world.task.sessions() if row["session_id"] == "s3")["snapshot_ids"]) == {
            world.a, world.h1, world.h2}
        _save_on(world, "P", "收入", {"gl": world.a}, ITEMS)
        _save_on(world, "Hv1", "Falcon 项目", {"project": world.h1}, HIDDEN_ITEMS)
        if hidden:
            _save_on(world, "Hv2", "Falcon 薪酬", {"payroll": world.h2}, ITEMS)
        code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a},
             "requirements_id": world.versions["Hv2" if hidden else "Hv1"]["id"]}), session="s3")
        assert code == 0, saved
        code, run = _cli(capsys, world.var, "analysis-run", "--analysis", saved["id"], session="s2")
        assert code == 0, run
        assert run["requirements_id"] == world.versions["Hv2" if hidden else "P"]["id"]
        _save_on(world, "C", "收入", {"gl": world.a}, ITEMS)
        code, state = _cli(capsys, world.var, "analysis-state", session="s1")
        assert code == 0, state
        listed = {row["id"]: row for row in [*state["analyses"], *state["runs"]]}
        s1 = next(row for row in world.task.sessions() if row["session_id"] == "s1")["snapshot_ids"]
        receipt = FinanceStore(world.task, snapshot_ids=s1, session_id="s1").save_explanation_draft(
            {"body": "S1 稿：Falcon 收入 100。", "run_ids": [run["id"]]})["completion"]
        hidden_values = [value for label, row in world.versions.items() if label == "Hv2"
                         for value in (row["id"], row["semantic_fingerprint"])]
        assert _shows([state, receipt], [world.h2, *hidden_values]) == []
        versions = {label: row for label, row in world.versions.items() if label != "Hv2"}
        ids = {row["id"]: label for label, row in versions.items()}
        read.append((ids.get(listed[saved["id"]].get("requirements_id")), _pins(versions, [listed[run["id"]]]),
                     _verdict(receipt)))
    assert read[0] == read[1]
    named, pins, verdict = read[0]
    assert named == "Hv1" and pins == [("P", "P=C")]
    assert verdict[4] == 1 and "requirements_run_outdated" not in verdict[5]


@pytest.mark.parametrize("engine", ["sql", "script"])
def test_a_session_reads_another_session_s_run_started_under_a_version_that_session_read_otherwise(
        tmp_path, capsys, fake_runner, monkeypatch, engine):
    """Hv1 on H1 holds an item more than P on A, and Hv2 on H2, saved but where S1 reads, drops it: S2, which may not
    read Hv1, reads Hv2 with a fingerprint of its own, and its run started under Hv2 captured that one. The manager
    saves P2 on A while the run runs. S1 reads the run as started under P, which S2 read as current where Hv2 was
    never saved, not under P2."""
    pending = _meanwhile(monkeypatch)
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _apart_world(tmp_path / name)
        _save_on(world, "P", "收入", {"gl": world.a}, ITEMS)
        _save_on(world, "Hv1", "Falcon 项目", {"project": world.h1},
                 [*HIDDEN_ITEMS, {"id": "falcon_payroll", "metric": "expense", "label": "Falcon 薪酬"}])
        if hidden:
            dropped = _save_on(world, "Hv2", "Falcon 薪酬", {"payroll": world.h2}, ITEMS)
            # S2 reads Hv2 by a fingerprint no version is stored with.
            assert AnalysisStore(world.task).fingerprint_in_view(dropped, {world.a, world.h2}) not in {
                row["semantic_fingerprint"] for row in world.versions.values()}
        pending.append(lambda: _save_on(world, "P2", "收入（复核）", {"gl": world.a}, ITEMS))
        if engine == "script":
            code, run = _cli(capsys, world.var, "analysis-script", "--spec", json.dumps(
                {"code": "print(1)", "bindings": {"gl": world.a}, "result_file": "result.json"}), session="s2")
        else:
            code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
                {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}}), session="s2")
            assert code == 0, saved
            code, run = _cli(capsys, world.var, "analysis-run", "--analysis", saved["id"], session="s2")
        assert code == 0, run
        assert run["requirements_id"] == world.versions["Hv2" if hidden else "P"]["id"]
        read.append(_apart_reads(world, capsys, [run]))
    assert read[0] == read[1]
    assert read[0][0] == [("P", "P", "P", "P") if engine == "script" else ("P", "P")]


# An item a version on H1 holds more than P, and one only a version on H2 holds.
H1_ITEM = {"id": "project_cost", "metric": "expense", "label": "项目费用"}
H2_ITEM = {"id": "falcon_bonus", "metric": "expense", "label": "Falcon 奖金"}


@pytest.mark.parametrize("scenario", ["swapped", "kept", "named"])
def test_a_session_reads_the_fingerprint_another_session_filed_for_a_version_as_its_own(
        tmp_path, capsys, fake_runner, scenario):
    """The manager saves P on A, Hv1 on H1 with an item more, and, but where S1 reads, Hv2 on H2, which swaps that item
    for one of its own (``swapped``, ``named``) or keeps it (``kept``), then C on A, which drops them. Each session
    reads C as dropping only what the versions it may read held, so S2 reads it with a fingerprint other than S1's
    but where Hv2 kept the item. S2 runs SQL and a script on A, naming P with ``named``, and files a receipt on them,
    each with the fingerprint it read C with. S1 reads every one of those as its own fingerprint of C in both worlds:
    nothing S2 read of Hv2 shows, or decides S1's receipt on the runs."""
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _apart_world(tmp_path / name)
        _save_on(world, "P", "收入", {"gl": world.a}, ITEMS)
        _save_on(world, "Hv1", "Falcon 项目", {"project": world.h1}, [*ITEMS, H1_ITEM])
        if hidden:
            _save_on(world, "Hv2", "Falcon 薪酬", {"payroll": world.h2},
                     [*ITEMS, H1_ITEM if scenario == "kept" else H2_ITEM])
        current = _save_on(world, "C", "收入", {"gl": world.a}, ITEMS)
        ceilings = {row["session_id"]: set(row["snapshot_ids"]) for row in world.task.sessions()}
        pin = {"requirements_id": world.versions["P"]["id"]} if scenario == "named" else {}
        code, saved = _cli(capsys, world.var, "analysis-save", "--spec", json.dumps(
            {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": world.a}, **pin}), session="s2")
        assert code == 0, saved
        runs = [_cli(capsys, world.var, "analysis-run", "--analysis", saved["id"], session="s2")[1],
                _cli(capsys, world.var, "analysis-script", "--spec", json.dumps(
                    {"code": "print(1)", "bindings": {"gl": world.a}, "result_file": "result.json", **pin}),
                    session="s2")[1]]
        filed = FinanceStore(world.task, snapshot_ids=ceilings["s2"], session_id="s2").save_explanation_draft(
            {"body": "S2 稿：Falcon 收入 100。", "run_ids": [run["id"] for run in runs]})["completion"]
        analysis = AnalysisStore(world.task)
        s2_reads = analysis.fingerprint_in_view(current, ceilings["s2"])
        assert [run["requirements_semantic_fingerprint"] for run in runs] == [s2_reads] * 2
        assert filed["requirements_semantic_fingerprint"] == s2_reads
        code, state = _cli(capsys, world.var, "analysis-state", session="s1")
        assert code == 0, state
        receipt = FinanceStore(world.task, snapshot_ids=ceilings["s1"], session_id="s1").save_explanation_draft(
            {"body": "S1 稿：Falcon 收入 100。", "run_ids": [run["id"] for run in runs]})["completion"]
        # Each fingerprint by the versions S1 reads with it.
        versions = {label: {**row, "semantic_fingerprint": analysis.fingerprint_in_view(row, ceilings["s1"])}
                    for label, row in world.versions.items() if label != "Hv2"}
        listed = {row["id"]: row for row in state["runs"]}
        shown = next(row for row in state["completions"] if row["id"] == filed["id"])
        if hidden:
            unread = {current["semantic_fingerprint"], s2_reads} - {versions["C"]["semantic_fingerprint"]}
            assert _shows([state, receipt], [world.h2, H2_ITEM["id"], *unread, *(
                world.versions["Hv2"][key] for key in ("id", "semantic_fingerprint"))]) == []
        read.append((_pins(versions, [*(listed[run["id"]] for run in runs), shown, receipt]),
                     [row["chain_key"] == completion_chain_key(row["requirements_semantic_fingerprint"],
                                                               row["requirements_id"], row["run_hashes"])
                      for row in (shown, receipt)], _verdict(receipt)))
    assert read[0] == read[1]
    pins, chained, verdict = read[0]
    named = "P" if scenario == "named" else "C"
    assert pins == [(named, "C"), (named, "C", named, named), ("C", "C"), ("C", "C")]
    assert chained == [True, True]
    # S2's receipt was the first on C's chain as S1 reads it.
    assert verdict[1] == 1
    assert ("requirements_run_outdated" in verdict[5]) == (scenario == "named")


def test_a_session_reads_a_receipt_on_a_run_another_session_captured_otherwise_as_its_own_save_would_file_it(
        tmp_path, capsys, fake_runner):
    """The manager saves P on A, Hv1 on B with an item more, and C on A, which drops it. N, which may read A alone,
    reads C as dropping nothing, and runs SQL on A under it; W, which may read A and B, reads C as stored. The manager
    saves a draft citing N's run and hers on B, and files its receipt on N's run as captured: not bound to C. Every
    version rests on the draft's files, and, but where W reads, so does none saved since on X. W reads the receipt as
    its own save of the draft would have filed it, in both worlds: N's run bound to C, as W reads it."""
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        root = tmp_path / name
        var = root / "var"
        task = TaskStore(var).create(title="另一会话的捕获")
        analysis = AnalysisStore(task)
        files = {}
        # Each session may read the files added before it.
        for label, organization, session in (("A", "Falcon", "n"), ("B", "Hawk", "w"), ("X", "Owl", None)):
            files[label] = analysis.add_dataset(_csv(root / f"{label}.csv", [
                ("revenue", "2026-08", organization, "100", "CNY", "元")]), name=label)["id"]
            if session:
                task.record_session(session, role="analysis")
        ceilings = {row["session_id"]: set(row["snapshot_ids"]) for row in task.sessions()}
        assert ceilings == {"n": {files["A"]}, "w": {files["A"], files["B"]}}
        manager = FinanceStore(task)
        versions: dict[str, dict] = {}
        for label, binding, items in (("P", "A", ITEMS), ("Hv1", "B", [*ITEMS, H1_ITEM]), ("C", "A", ITEMS)):
            parent = {"parent_id": versions[list(versions)[-1]]["id"], "change_reason": "换"} if versions else {}
            versions[label] = manager.analysis_requirements_save({
                "question": "收入", "scope": {"period": "2026-08"}, "bindings": {"gl": files[binding]}, "items": items,
                **parent})
        runs = []
        for session, binding in (("n", "A"), (None, "B")):
            who = {"session": session, "task": None if session else task.id}
            code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps(
                {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": files[binding]}}), **who)
            assert code == 0, saved
            runs.append(_cli(capsys, var, "analysis-run", "--analysis", saved["id"], **who)[1])
        assert runs[0]["requirements_semantic_fingerprint"] != versions["C"]["semantic_fingerprint"]
        draft = {"body": "收入 100。", "run_ids": [run["id"] for run in runs]}
        filed = manager.save_explanation_draft({**draft, "body": "经理稿：收入 100。"})["completion"]
        if hidden:
            manager.analysis_requirements_save({
                "question": "收入", "scope": {"period": "2026-08"}, "bindings": {"gl": files["X"]}, "items": ITEMS,
                "parent_id": versions["C"]["id"], "change_reason": "换"})
        w = FinanceStore(task, snapshot_ids=ceilings["w"], session_id="w")
        shown = w._readable_receipt(analysis._get("completions", filed["id"]))
        assert manager._readable_receipt(analysis._get("completions", filed["id"])) == filed
        read.append(_verdict(shown))
        if not hidden:
            own = _verdict(w.save_explanation_draft({**draft, "body": "W 稿：收入 100。"})["completion"])
    assert read[0] == read[1]
    assert "requirements_run_outdated" in _verdict(filed)[5] and "requirements_run_outdated" not in read[0][5]
    # W's own save is the next on the chain.
    assert own[4:] == read[0][4:]


def test_a_run_a_session_filed_before_sessions_had_a_ceiling_reads_as_the_manager_s(tmp_path, capsys):
    """A session recorded before sessions had a snapshot ceiling ran as the manager does: its run reads to a session
    as the manager's run of the same analysis does, pinned where the version on H it ran under was never saved."""
    var = tmp_path / "var"
    task = TaskStore(var).create(title="没有上限的会话")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(tmp_path / "a.csv", [("revenue", "2026-08", "Falcon", "100", "CNY", "元")]), name="总账")["id"]
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_csv(tmp_path / "h.csv", [("revenue", "2026-07", "Falcon", "100", "CNY", "元")]), name="薪酬")["id"]
    task.record_session("old", role="analysis")
    rows = [{key: value for key, value in row.items() if not (row["session_id"] == "old" and key == "snapshot_ids")}
            for row in task.sessions()]
    task._write_sessions(rows)
    manager = FinanceStore(task)
    visible = manager.analysis_requirements_save({"question": "收入", "scope": {"period": "2026-08"},
                                                  "bindings": {"gl": a}, "items": ITEMS})
    head = manager.analysis_requirements_save({"question": "Falcon 项目", "scope": {"period": "2026-07"},
                                               "bindings": {"payroll": h}, "items": HIDDEN_ITEMS,
                                               "parent_id": visible["id"], "change_reason": "换项目"})
    saved = analysis.save_analysis({"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": a}})["id"]
    runs = [analysis.run_analysis(saved, session_id="old", context_revision=1), analysis.run_analysis(saved)]
    assert [run["requirements_id"] for run in runs] == [head["id"]] * 2
    code, state = _cli(capsys, var, "analysis-state")
    assert code == 0
    listed = {row["id"]: row for row in state["runs"]}
    assert _pins({"V": visible}, [listed[run["id"]] for run in runs]) == [("V", "V")] * 2


# --- a draft another session saved on such runs --------------------------------------------------------------------


def _ceilings_world(root: Path, capsys, *, nested: bool, with_g: bool):
    """W, the wider session, imports H. N, the narrower, may read A, and G where G was added before N (``with_g`` and
    not ``nested``): either way W may not read G. The manager saves V on A, Gv on G (with ``with_g``) and Hv on H,
    runs a script and SQL on A while Hv is the head, then saves V's items again (V2). N and W each save a draft citing
    both runs: W reads them pinned to Hv, N pinned to Gv where it may read G, else to V."""
    var = root / "var"
    task = TaskStore(var).create(title="两个会话")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(root / "a.csv", [("revenue", "2026-08", "Falcon", "100", "CNY", "元")]), name="总账")["id"]
    task.record_session("wide", role="analysis")
    if nested:
        task.record_session("narrow", role="analysis")
    g = analysis.add_dataset(_csv(root / "g.csv", [("revenue", "2026-07", "Falcon", "100", "CNY", "元")]),
                             name="项目")["id"] if with_g else None
    if not nested:
        task.record_session("narrow", role="analysis")
    workspace = Path(next(row for row in task.sessions() if row["session_id"] == "wide")["workspace_path"])
    (workspace / "uploads").mkdir(parents=True, exist_ok=True)
    path = _csv(workspace / "uploads" / "h.csv", [("revenue", "2026-06", "Falcon", "100", "CNY", "元")])
    code, h = _cli(capsys, var, "dataset-add", "--path", str(path), "--name", "薪酬", session="wide")
    assert code == 0, h
    manager = FinanceStore(task)
    spec = {"question": "收入", "scope": {"period": "2026-08"}, "bindings": {"gl": a}, "items": ITEMS}
    head = manager.analysis_requirements_save(spec)
    gv = None
    if with_g:
        head = gv = manager.analysis_requirements_save({
            "question": "Falcon 项目", "scope": {"period": "2026-07"}, "bindings": {"project": g},
            "items": HIDDEN_ITEMS, "parent_id": head["id"], "change_reason": "换项目"})
    head = manager.analysis_requirements_save({"question": "薪酬", "scope": {"period": "2026-06"},
                                               "bindings": {"payroll": h["id"]}, "items": ITEMS,
                                               "parent_id": head["id"], "change_reason": "换薪酬"})
    as_manager = {"session": None, "task": task.id}
    code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps(
        {"question": "收入", "sql": PINNED_SQL, "bindings": {"gl": a}}), **as_manager)
    assert code == 0, saved
    sql = _cli(capsys, var, "analysis-run", "--analysis", saved["id"], **as_manager)[1]
    script = _cli(capsys, var, "analysis-script", "--spec", json.dumps(
        {"code": "print(1)", "bindings": {"gl": a}, "result_file": "result.json"}), **as_manager)[1]
    assert sql["requirements_id"] == script["requirements_id"] == head["id"]
    manager.analysis_requirements_save({**spec, "parent_id": head["id"], "change_reason": "回到总账"})
    ceilings = {row["session_id"]: row["snapshot_ids"] for row in task.sessions()}
    assert (g in ceilings["narrow"]) == (with_g and not nested) and g not in ceilings["wide"]
    assert h["id"] in ceilings["wide"] and h["id"] not in ceilings["narrow"]
    draft = {"run_ids": [script["id"], sql["id"]],
             "claims": [{"basis": "calculation", "run_id": script["id"], "row": 0, "column": "value", "value": "100"}]}
    saved = {who: FinanceStore(task, snapshot_ids=ceilings[who], session_id=who).save_explanation_draft(
        {**draft, "body": f"{who} 稿：Falcon 收入 100。"}) for who in ("narrow", "wide")}
    secrets = [g, gv["id"], gv["semantic_fingerprint"], "Falcon 项目", "按人数分摊"] if with_g else []
    return SimpleNamespace(var=var, script=script, saved=saved, secrets=secrets)


@pytest.mark.parametrize("nested", [False, True])
def test_a_session_reads_a_draft_another_session_saved_as_its_own_save_would_have_filed_it(
        tmp_path, capsys, fake_runner, nested):
    """W reads N's draft and receipt judged on the runs as W reads them, as its own save would have filed them, not
    as N read them. Where N may read G it read them pinned to Gv, the revenue an estimate; W reads as where G was
    never added, so as where N's ceiling lies inside its own and N read them pinned to V: there too it reads N's draft
    as its own, and saves on it so."""
    read = []
    for with_g in (False, True):
        world = _ceilings_world(tmp_path / str(with_g), capsys, nested=nested, with_g=with_g)
        code, state = _cli(capsys, world.var, "analysis-state", session="wide")
        assert code == 0, state
        assert _shows([state, world.saved["wide"]], world.secrets) == []
        drafts = {row["id"]: row for row in state["drafts"]}
        receipts = {row["draft_id"]: row for row in state["completions"]}
        shown = {who: (_labels_of(drafts[draft["id"]]["explanation_check"], world.script["id"]),
                       _verdict(receipts[draft["id"]])[4:]) for who, draft in world.saved.items()}
        read.append((shown, _verdict(world.saved["wide"]["completion"])))
    assert read[0] == read[1]
    issues = ["missing_required_fact", "requirement_unanswered", "requirements_run_outdated"]
    shown, saved = read[0]
    labels = [("claim", "unknown", ["run_script"]), ("fact", "unknown", ["run_script"])]
    assert shown["narrow"] == shown["wide"] == (labels, (0, issues))
    assert saved == ("needs_review", 1, "no_progress", False, 0, issues)


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
    """The session compares its run with the earlier runs of its fingerprint and commits it under one task lock: a run
    the manager commits meanwhile comes after it, so the session reads its run as it saved it."""
    import foundry.analysis as module

    var = tmp_path / "var"
    task = TaskStore(var).create(title="复现")
    analysis = AnalysisStore(task)
    b = analysis.add_dataset(_csv(tmp_path / "b.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")]), name="总账")
    task.record_session("sess", role="analysis")
    managed = analysis.save_analysis({"question": "q", "sql": SQL, "bindings": {"t": b["id"]}})["id"]
    code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps({"question": "q", "sql": SQL,
                                                                          "bindings": {"t": b["id"]}}))
    compared = module._snapshot_reproducibility
    meanwhile: dict = {}

    def comparing(*args):
        if not meanwhile:
            # The manager runs once the session has compared its run with the earlier runs, before the session
            # commits it; it waits for the session's commit.
            meanwhile["thread"] = threading.Thread(target=lambda: meanwhile.update(run=analysis.run_analysis(managed)))
            meanwhile["thread"].start()
            meanwhile["thread"].join(timeout=2)
        return compared(*args)

    monkeypatch.setattr(module, "_snapshot_reproducibility", comparing)
    run = AnalysisStore(task).run_analysis(saved["id"], session_id="sess", allowed={b["id"]})
    meanwhile["thread"].join()
    monkeypatch.setattr(module, "_snapshot_reproducibility", compared)
    assert meanwhile["run"]["seq"] > run["seq"]
    code, state = _cli(capsys, var, "analysis-state")
    assert [row["reproducibility_status"] for row in state["runs"] if row["id"] == run["id"]] == [
        run["reproducibility_status"]] == ["unverified"]


def test_a_run_reads_the_earlier_runs_before_it_takes_the_task_lock(tmp_path, monkeypatch):
    """A task's runs can be many, each holding its result rows: a run reads and checks the earlier ones before it takes
    the task lock, so no other writer on the task waits on them, and under the lock only a run committed since, which
    it still compares with."""
    import contextlib

    import foundry.analysis as module

    task = TaskStore(tmp_path / "var").create(title="复现")
    analysis = AnalysisStore(task)
    b = analysis.add_dataset(_csv(tmp_path / "b.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")]), name="总账")
    managed = analysis.save_analysis({"question": "q", "sql": SQL, "bindings": {"t": b["id"]}})["id"]
    earlier = [analysis.run_analysis(managed) for _ in range(3)]
    lock, read = module.exclusive, AnalysisStore._read
    held, meanwhile, reads = [], [], []

    @contextlib.contextmanager
    def exclusive(path, **kwargs):
        if not meanwhile:
            # Once the run has read the earlier runs and before it takes the lock, a run of its fingerprint that gave
            # another output is committed.
            meanwhile.append(None)
            fields = {key: value for key, value in earlier[0].items()
                      if key not in ("id", "task_id", "schema_version", "created_at", "seq", "_integrity_hash")}
            record = _new(task, **{**fields, "output_hash": "0" * 64})
            meanwhile[0] = analysis._write(analysis._object_path("runs", record["id"]), record)
        with lock(path, **kwargs):
            held.append(path)
            try:
                yield
            finally:
                held.pop()

    def reading(self, path):
        if path.parent.name == "runs":
            reads.append((bool(held), path.stem))
        return read(self, path)

    monkeypatch.setattr(module, "exclusive", exclusive)
    monkeypatch.setattr(AnalysisStore, "_read", reading)
    run = analysis.run_analysis(managed)
    assert sorted(stem for locked, stem in reads if not locked) == sorted(row["id"] for row in earlier)
    assert [stem for locked, stem in reads if locked] == [meanwhile[0]["id"]]
    assert run["seq"] > meanwhile[0]["seq"] and run["reproducibility_status"] == "non_reproducible"


def test_a_session_lists_the_task_s_runs_once_a_request_to_read_a_run_s_reproducibility(tmp_path, capsys, monkeypatch):
    """A session reads a SQL run's reproducibility by the earlier runs of its fingerprint it may read, from a listing
    of the task's runs. An export (its draft, projection and run lines) and a save or its retry (the draft, its
    receipt and what it returns) are each one read, and list them once; a close status reads its draft with the runs
    its listing read, so it lists them no more often than the manager's."""
    var = tmp_path / "var"
    task = TaskStore(var).create(title="复现")
    analysis = AnalysisStore(task)
    b = analysis.add_dataset(_csv(tmp_path / "b.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")]), name="总账")
    task.record_session("sess", role="analysis")
    revision = analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": b["id"]}})["id"]
    run = [analysis.run_analysis(revision) for _ in range(2)][-1]
    spec = {"title": "收入", "body": "收入 100。", "run_ids": [run["id"]], "claims": [_claim(run)]}
    code, saved = _cli(capsys, var, "analysis-draft", "--spec", json.dumps(spec))
    assert code == 0, saved
    session = FinanceStore(task, snapshot_ids=[b["id"]], session_id="sess")
    finance = {"body": "收入 100。", "run_ids": [run["id"]], "claims": [_claim(run)]}
    listed = []
    list_kind = AnalysisStore._list
    monkeypatch.setattr(AnalysisStore, "_list",
                        lambda self, kind, **kwargs: listed.append(kind) or list_kind(self, kind, **kwargs))
    requests = {
        "export": lambda: _cli(capsys, var, "analysis-export", "--draft", saved["id"], "--format", "md",
                               "--mode", "audit")[0] == 0,
        "draft": lambda: _cli(capsys, var, "analysis-draft", "--spec", json.dumps({**spec, "body": "收入 100。。"}))[0] == 0,
        "save": lambda: "replayed" not in session.save_explanation_draft(finance),
        "retry": lambda: session.save_explanation_draft(finance)["replayed"],
        "close": lambda: bool(session.finance_close_status({})),
        "managed close": lambda: bool(FinanceStore(task).finance_close_status({})),
    }
    counts = {}
    for name, request in requests.items():
        listed.clear()
        assert request()
        counts[name] = listed.count("runs")
    managed = counts.pop("managed close")
    assert counts == {**dict.fromkeys(("export", "draft", "save", "retry"), 1), "close": managed}


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


def test_a_session_lists_the_refresh_batches_once_for_every_draft_it_reads(tmp_path, capsys, monkeypatch):
    """Each draft on P reads P by the refreshes filed before it, as the session reads them, and S's record names the
    prior its batch reads with: the batches are listed once for the read, however many drafts there are."""
    world = _refreshed_world(tmp_path, capsys, legacy=True, drafts=True)
    world.drafts.append(_draft_on(world.task, world.p["dataset_id"]))
    listed = []
    batches = SourceRefreshService.batches
    monkeypatch.setattr(SourceRefreshService, "batches", lambda self: listed.append(None) or batches(self))
    code, state = _cli(capsys, world.var, "analysis-state")
    assert code == 0 and len(listed) == 1
    drafts = {row["id"]: row for row in state["drafts"]}
    assert [(freshness["state"], [reason["code"] for reason in freshness["reasons"]]) for freshness in (
        drafts[saved["id"]]["explanation_check"]["dataset_freshness"][world.p["dataset_id"]]["freshness"]
        for saved in world.drafts)] == [("unknown", ["no_task_period"])] + [("source_stale", ["superseded"])] * 2
    assert [row["metadata"]["source_refresh"]["prior_snapshot_id"] for row in state["datasets"]
            if row["id"] == world.s["dataset_id"]] == [world.p["dataset_id"]]


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


def test_a_session_reads_the_receipts_its_operation_settled_on_before_it_takes_the_task_lock(tmp_path, capsys,
                                                                                             monkeypatch):
    """Which revisions the session reads as settled rests on their receipts, drafts and runs (_in_view): each is read
    before the operation takes the task lock, so a save, a status poll or a begun-again request holds it no longer
    than the manager's. Each call is a store of its own, as each CLI call is, reading none of them before."""
    import foundry.finance_completion_operations as module
    from foundry.finance_completion_operations import CompletionOperationStore

    world = _settled_operation(tmp_path / "legacy", capsys, live=True, legacy=True, spent=0)

    def store():
        return CompletionOperationStore(world.sess.task, "sess", world.sess.allowed)

    def cli(command, **spec):
        code, shown = _cli(capsys, world.var, command, "--spec", json.dumps(spec))
        assert code == 0, shown
        return shown

    locking, load = module.exclusive, AnalysisStore._read
    held, reads = [False], {False: [], True: []}

    @contextmanager
    def holding(path, **kwargs):
        with locking(path, **kwargs):
            held[0] = True
            try:
                yield
            finally:
                held[0] = False

    def reading(self, path):
        if path.parent.name in {"completions", "drafts", "runs", "requirements"}:
            reads[held[0]].append(path.parent.name)
        return load(self, path)

    monkeypatch.setattr(module, "exclusive", holding)
    monkeypatch.setattr(AnalysisStore, "_read", reading)
    # Revision 2 settled, then settled again as a replay; revision 3 reserved and rejected; then a stop.
    read = [world.sess.save_completion_draft(world.operation, "call-2", {"body": "会话修订稿。"})["completion_operation"]
            for _ in range(2)]
    read += [store().reserve(world.operation, payload={"body": "会话第三稿。"}, call_id="call-3"),
             store().reject_attempt(world.operation, 3, {"code": "claim_value_mismatch", "message": "bad"}),
             cli("finance-completion-begin", request_key="request-1"),
             cli("finance-completion-status", operation_id=world.operation),
             cli("finance-completion-stop", operation_id=world.operation, reason="用户取消")]
    assert reads[True] == [] and {"completions", "drafts", "runs"} <= set(reads[False])
    assert [operation.get("replayed", False) for operation in read] == [False, True, False, False, True, False, False]
    assert [[row["status"] for row in operation["revisions"]] for operation in read] == [
        ["rejected_validation", "settled"]] * 2 + [["rejected_validation", "settled", "reserved"]] + [
        ["rejected_validation", "settled", "rejected_validation"]] * 4
    assert _shows(read, world.hidden) == []


@pytest.mark.parametrize("interrupted", [False, True])
def test_a_session_s_completion_save_reads_its_receipts_before_it_takes_completion_lock(tmp_path, capsys,
                                                                                        monkeypatch, interrupted):
    """The manager's saves wait on completion.lock, which a session's completion save holds while its operation reserves
    and settles: whether the session may read each receipt the operation is settled on, and the one the save settles
    it on, is read before the save takes that lock, so the operation reads no run under it, on a save or a replay.
    With ``interrupted`` the first save stopped after its draft was saved and before its receipt was filed, so the
    replay files the receipt under the lock: the save tells the operation the session reads it (_settled_receipt)."""
    import traceback

    import foundry.finance_completion as completion
    import foundry.locking as locking
    from foundry.finance_completion_operations import CompletionOperationStore

    world = _settled_operation(tmp_path / "legacy", capsys, live=True, legacy=True, spent=0)
    [a] = world.sess.allowed
    context = world.sess.save_context({"bindings": {"ledger": a}, "scopes": {}})
    run = world.sess.run_metric({"context_id": context["id"], "metric": {"kind": "control_totals"}})
    exclusive, get_run = locking.exclusive, AnalysisStore.get_run
    held, read, reads = [False], [], []

    @contextmanager
    def holding(path, **kwargs):
        with exclusive(path, **kwargs):
            before, held[0] = held[0], held[0] or Path(path).name == "completion.lock"
            try:
                yield
            finally:
                held[0] = before

    def reading(self, run_id):
        if held[0]:  # by the operation, or by the rest of the save, as on main
            reads[-1].append(any(frame.filename.endswith("finance_completion_operations.py")
                                 for frame in traceback.extract_stack()))
        return get_run(self, run_id)

    monkeypatch.setattr(locking, "exclusive", holding)
    monkeypatch.setattr(AnalysisStore, "get_run", reading)
    spec = {"body": "会话修订稿。", "run_ids": [run["id"]]}
    if interrupted:
        original = completion.record_completion

        def failing(*args, **kwargs):
            raise RuntimeError("interrupted before receipt")

        monkeypatch.setattr(completion, "record_completion", failing)
        reads.append([])
        with pytest.raises(RuntimeError):
            world.sess.save_completion_draft(world.operation, "call-2", spec)
        monkeypatch.setattr(completion, "record_completion", original)
        reads.clear()
        # Revision 2 is left reserved, on no receipt the operation could read before the replay's lock.
        assert [row["status"] for row in CompletionOperationStore(world.sess.task, "sess", world.sess.allowed).get(
            world.operation)["revisions"]] == ["rejected_validation", "reserved"]
    # Revision 2 settled on a draft citing the session's run, then settled again as a replay (interrupted: the replay
    # alone, settling it).
    for _ in range(1 if interrupted else 2):
        reads.append([])
        read.append(world.sess.save_completion_draft(world.operation, "call-2", spec))
    assert [(False in by_save, True in by_save) for by_save in reads] == [(True, False)] * len(read)
    assert [shown.get("replayed", False) for shown in read] == ([True] if interrupted else [False, True])
    assert [[row["status"] for row in shown["completion_operation"]["revisions"]] for shown in read] == [
        ["rejected_validation", "settled"]] * len(read)
    assert _shows(read, world.hidden) == []


def test_a_session_s_completion_save_verifies_its_runs_under_completion_lock_as_where_no_version_was_hidden(
        tmp_path, capsys, fake_runner, monkeypatch):
    """The manager's saves wait on completion.lock, which a session's completion save holds while it saves, files and
    reads its receipt. Where Hv held an item more, the session reads its draft and receipts again as its twin would,
    but verifies each cited run's outputs (get_run) under the lock no more often than where Hv was never saved: on a
    save, a revision and a replay."""
    import foundry.locking as locking
    from foundry.finance_completion_operations import CompletionOperationStore

    exclusive, get_run = locking.exclusive, AnalysisStore.get_run
    held, counts, verdicts = [False], [], []

    @contextmanager
    def holding(path, **kwargs):
        with exclusive(path, **kwargs):
            before, held[0] = held[0], held[0] or Path(path).name == "completion.lock"
            try:
                yield
            finally:
                held[0] = before

    def reading(self, run_id):
        if held[0]:
            counts[-1][-1] += 1
        return get_run(self, run_id)

    monkeypatch.setattr(locking, "exclusive", holding)
    monkeypatch.setattr(AnalysisStore, "get_run", reading)
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys, extra_item=True)
        session = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess")
        operation = CompletionOperationStore(world.task, "sess", session.allowed).begin(
            "request-1", policy={"max_repairs": 2})
        counts.append([])
        shown = []
        for call, body in (("call-1", "会话稿甲：Falcon 收入 100。"), ("call-2", "会话稿乙：Falcon 收入 100。"),
                           ("call-2", "会话稿乙：Falcon 收入 100。")):
            counts[-1].append(0)
            shown.append(session.save_completion_draft(operation["id"], call, {**world.draft, "body": body}))
        verdicts.append([(_verdict(row["completion"]), row.get("replayed", False)) for row in shown])
    assert verdicts[0] == verdicts[1] and [replayed for _, replayed in verdicts[0]] == [False, False, True]
    assert counts[1] == counts[0], counts


def test_a_session_s_completion_save_reads_each_lineage_from_its_listed_versions_under_completion_lock(
        tmp_path, capsys, fake_runner, monkeypatch):
    """A session reads its draft's check and each receipt by their version's lineage as its own check would have read
    it (finance_requirements.check_lineage_in_view), and its completion save does so under completion.lock, which the
    manager's saves wait on. Each walk takes the versions from those the save has listed
    (AnalysisStore._requirements_by_id), so it reads none again under the lock: on a save, a revision and a replay,
    with Hv or without."""
    import foundry.finance_requirements as finance_requirements
    import foundry.locking as locking
    from foundry.finance_completion_operations import CompletionOperationStore

    exclusive, get, walk = locking.exclusive, AnalysisStore._get, finance_requirements.check_lineage_in_view
    held, walking, counts = [False], [False], []

    @contextmanager
    def holding(path, **kwargs):
        with exclusive(path, **kwargs):
            before, held[0] = held[0], held[0] or Path(path).name == "completion.lock"
            try:
                yield
            finally:
                held[0] = before

    def walked(*args, **kwargs):
        if held[0]:
            counts[-1][-1][0] += 1
        walking[0] = True
        try:
            return walk(*args, **kwargs)
        finally:
            walking[0] = False

    def reading(self, kind, record_id):
        if held[0] and walking[0] and kind == "requirements":
            counts[-1][-1][1] += 1
        return get(self, kind, record_id)

    monkeypatch.setattr(locking, "exclusive", holding)
    monkeypatch.setattr(finance_requirements, "check_lineage_in_view", walked)
    monkeypatch.setattr(AnalysisStore, "_get", reading)
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _pinned_world(tmp_path / name, hidden, capsys, extra_item=True)
        session = FinanceStore(world.task, snapshot_ids=[world.a], session_id="sess")
        operation = CompletionOperationStore(world.task, "sess", session.allowed).begin(
            "request-1", policy={"max_repairs": 2})
        counts.append([])
        for call, body in (("call-1", "会话稿甲：Falcon 收入 100。"), ("call-2", "会话稿乙：Falcon 收入 100。"),
                           ("call-2", "会话稿乙：Falcon 收入 100。")):
            counts[-1].append([0, 0])
            session.save_completion_draft(operation["id"], call, {**world.draft, "body": body})
    # Every save walks the lineage under the lock, and reads no version to do so.
    assert all(walks and not reads for by_world in counts for walks, reads in by_world), counts


def test_a_session_s_operation_answers_by_the_record_it_reads_under_the_task_lock(tmp_path, capsys, monkeypatch):
    """What the operation reads before it takes the task lock (_prime) decides nothing: a revision the session settles
    in between reads as settled, as it does after, and a settlement refused under the lock is refused as before."""
    from foundry.errors import FoundryError
    from foundry.finance_completion_operations import CompletionOperationStore

    world = _settled_operation(tmp_path / "live", capsys, live=True, legacy=False, spent=0)
    spec = {"body": "会话修订稿。"}

    def store():
        return CompletionOperationStore(world.sess.task, "sess", world.sess.allowed)

    store().reserve(world.operation, payload=spec, call_id="call-2")
    prime, saved = CompletionOperationStore._prime, []

    def meanwhile(self, *args, **kwargs):
        prime(self, *args, **kwargs)
        monkeypatch.setattr(CompletionOperationStore, "_prime", prime)
        saved.append(world.sess.save_completion_draft(world.operation, "call-2", spec))

    monkeypatch.setattr(CompletionOperationStore, "_prime", meanwhile)
    raced = store().reserve(world.operation, payload=spec, call_id="call-2")
    assert raced == store().reserve(world.operation, payload=spec, call_id="call-2")
    receipt = saved[0]["completion"]
    assert (raced["attempt"]["status"], raced["attempt"]["completion_id"]) == ("settled", receipt["id"])
    with pytest.raises(FoundryError, match="completion id must be"):
        store().settle(world.operation, 2, saved[0], {**receipt, "id": [receipt["id"]]})


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
