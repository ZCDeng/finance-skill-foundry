"""A session saves and files every record as it would have from the files it may read.

A session's snapshot ceiling (context.snapshot_ids; FinanceStore.allowed; an MCP grant's snapshot_ids) decides what
it may build on, as it decides what it may read (test_session_views). A record that rests on a file outside it
neither shows nor changes what the session saves: not a source batch a refresh compares with, an upload of the
same bytes, a requirements version, an earlier run of the same fingerprint, a draft named by id or a draft a
recovery files for it. A record the session may not read is refused exactly as one that does not
exist. The manager (no session) saves and is answered as before.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from foundry.analysis import AnalysisStore, _new
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.source_refresh import SourcePage, SourceRefreshService, SourceScope
from foundry.task import TaskStore

from test_session_views import SECRET, SQL, _chain, _cli, _csv, _ledger, _normalized, _shows
from test_source_refresh import FakeTransport

SCOPE = {"ledger": "L1", "organization": "O1", "period": "2026-08", "currency": "CNY", "unit": "万元", "scenario": "actual"}


def _entry(path: Path, account: str, amount: str) -> Path:
    """A ledger of one row in SCOPE."""
    return _ledger(path, [{**SCOPE, "management_account": account, "amount": amount, "source_row": 1}])


def _snapshots(task, session: str = "sess") -> list[str]:
    return next(row for row in task.sessions() if row["session_id"] == session)["snapshot_ids"]


# --- source refresh -------------------------------------------------------------------------------------------------


SOURCE_SCOPE = {"source_id": "erp", "tenant_id": "T1", "ledger_id": "L1", "organization_id": "O1",
                "period": "2026-09", "currency": "CNY", "cutoff_at": "2026-09-06"}


def _source_world(root: Path, *, manager_rows: list[str] | None, policy: str, mode: str, capsys):
    """A session refreshes the ERP source from uploaded files; the manager first publishes ``manager_rows``."""
    var = root / "var"
    task = TaskStore(var).create(title="刷新")
    task.record_session("sess", role="analysis")
    uploads = task.root / "analysis" / "uploads"
    uploads.mkdir(parents=True)

    def refresh(file: str, body: str, label: str, session: str | None):
        (uploads / file).write_text("document_id,line_id,management_account,amount\n" + body)
        spec = {"path": str(uploads / file), "scope": {**SOURCE_SCOPE, "mode": mode}, "file_identity_policy": policy,
                "name": label}
        code, result = _cli(capsys, var, "finance-source-refresh", "--spec", json.dumps(spec),
                            session=session, task=None if session else task.id)
        assert code == 0, result
        return result

    hidden = refresh("payroll.csv", "".join(manager_rows), "薪酬", None) if manager_rows else None
    return var, task, refresh, hidden


@pytest.mark.parametrize(("policy", "mode"), [("business_key", "incremental"), ("business_key", "full_period"),
                                              ("snapshot_only", "full_period")])
def test_a_session_refreshes_a_source_as_if_batches_it_may_not_read_were_never_published(tmp_path, capsys, policy, mode):
    from foundry.finance_controls import refreshed_snapshots, superseded_snapshots

    var, task, refresh, hidden = _source_world(tmp_path / "with", manager_rows=[f"H1,1,revenue,{SECRET}\n"],
                                               policy=policy, mode=mode, capsys=capsys)
    mine = refresh("ledger.csv", "S1,1,revenue,100\n", "总账", "sess")
    twin_var, _, twin_refresh, _ = _source_world(tmp_path / "without", manager_rows=None, policy=policy, mode=mode,
                                                 capsys=capsys)
    alone = twin_refresh("ledger.csv", "S1,1,revenue,100\n", "总账", "sess")
    # The batch it files is the one it files where the manager's was never published (seq counts every record).
    drop = lambda row: {key: value for key, value in row.items() if key != "seq"}
    assert _normalized(drop(mine)) == _normalized(drop(alone))
    assert mine["prior_snapshot_id"] is None and mine["duplicate_of"] is None
    assert _snapshots(task) == [mine["dataset_id"]]
    code, read = _cli(capsys, var, "dataset-read", "--dataset", mine["dataset_id"])
    assert code == 0
    assert read["rows"] == _cli(capsys, twin_var, "dataset-read", "--dataset", alone["dataset_id"])[1]["rows"]
    assert read["metadata"]["source_refresh"]["prior_snapshot_id"] is None
    code, listing = _cli(capsys, var, "finance-source-list")
    assert code == 0
    for shown in (mine, read, listing):
        assert _shows(shown, [SECRET, hidden["id"], hidden["dataset_id"]]) == []
    if mode == "incremental":
        code, context = _cli(capsys, var, "finance-context-save", "--spec", json.dumps({
            "bindings": {"actual": mine["dataset_id"]}, "scopes": {"actual": {
                "ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元",
                "scenario": "actual"}}}))
        code, run = _cli(capsys, var, "run-metric", "--spec", json.dumps({"context_id": context["id"]}))
        assert code == 0
        assert run["result"]["rows"][0]["revenue"] == "100"  # its own row, not it on top of the hidden one (987754.321)
    # The manager's batch is not replaced by a refresh that never saw it.
    assert hidden["dataset_id"] not in refreshed_snapshots(task)
    assert hidden["dataset_id"] not in superseded_snapshots(task)
    code, ready = _cli(capsys, var, "finance-readiness", session=None, task=task.id)
    payroll = next(row for row in ready["datasets"] if row["name"] == "薪酬")
    assert "superseded" not in [reason["code"] for reason in payroll["freshness"]["reasons"]]


def test_a_session_refreshing_bytes_only_a_hidden_batch_holds_files_its_own(tmp_path, capsys):
    var, task, refresh, _ = _source_world(tmp_path, manager_rows=["H0,1,payroll,555000\n"],
                                          policy="business_key", mode="incremental", capsys=capsys)
    hidden = refresh("h1.csv", "H1,1,revenue,10\n", "薪酬", None)  # H = H0 + H1 for the manager
    mine = refresh("h1.csv", "H1,1,revenue,10\n", "总账", "sess")  # the same bytes as H's file
    assert mine["duplicate_of"] is None
    assert mine["dataset_id"] not in (None, hidden["dataset_id"])
    assert mine["effective_dataset_id"] == mine["dataset_id"]
    assert hidden["dataset_id"] not in _snapshots(task)
    code, read = _cli(capsys, var, "dataset-read", "--dataset", mine["dataset_id"])
    assert code == 0 and [row["document_id"] for row in read["rows"]] == ["H1"]
    # The manager's batch is refused exactly as an id the task never filed.
    refused = _cli(capsys, var, "dataset-read", "--dataset", hidden["dataset_id"])
    assert refused == _cli(capsys, var, "dataset-read", "--dataset", "0" * 32) and refused[0] == 3
    # The manager still dedupes against every batch, as before.
    assert refresh("h1.csv", "H1,1,revenue,10\n", "薪酬", None)["duplicate_of"] == mine["id"]


def test_a_session_refresh_diffs_against_the_latest_batch_it_may_read(tmp_path):
    from foundry.finance_controls import superseded_snapshots

    task = TaskStore(tmp_path / "var").create(title="刷新")
    uploads = task.root / "analysis" / "uploads"
    uploads.mkdir(parents=True)
    scope = SourceScope(**SOURCE_SCOPE, mode="incremental")

    def upload(name, body):
        (uploads / name).write_text("document_id,line_id,management_account,amount\n" + body)
        return uploads / name

    seen = SourceRefreshService(task).refresh_file(upload("a.csv", "A1,1,revenue,1\n"), scope=scope, name="a")
    hidden = SourceRefreshService(task).refresh_file(upload("h.csv", f"H1,1,revenue,{SECRET}\n"), scope=scope, name="h")
    mine = SourceRefreshService(task, allowed={seen["dataset_id"]}).refresh_file(upload("s.csv", "S1,1,revenue,2\n"),
                                                                                 scope=scope, name="s")
    assert mine["prior_snapshot_id"] == seen["dataset_id"]
    rows = AnalysisStore(task).read_dataset(mine["dataset_id"])["rows"]
    assert sorted(row["document_id"] for row in rows) == ["A1", "S1"]
    assert hidden["dataset_id"] not in superseded_snapshots(task)
    # The manager's prior is the latest batch of all.
    manager = SourceRefreshService(task).refresh_file(upload("m.csv", "M1,1,revenue,3\n"), scope=scope, name="m")
    assert manager["prior_snapshot_id"] == mine["dataset_id"]


def test_a_refresh_a_reader_may_not_read_leaves_the_replacements_it_may_read_standing(tmp_path, capsys):
    from foundry.finance_controls import superseded_snapshots

    freshness = {}
    for name, forked in (("forked", True), ("alone", False)):
        var = tmp_path / name / "var"
        task = TaskStore(var).create(title="刷新")
        uploads = task.root / "analysis" / "uploads"
        uploads.mkdir(parents=True)
        scope = SourceScope(**SOURCE_SCOPE, mode="full_period")

        def upload(file, body):
            (uploads / file).write_text("document_id,line_id,management_account,amount\n" + body)
            return uploads / file

        first = SourceRefreshService(task).refresh_file(upload("p.csv", "P1,1,revenue,1\n"), scope=scope, name="P")
        newer = SourceRefreshService(task).refresh_file(upload("m.csv", "M1,1,revenue,2\n"), scope=scope, name="M")
        task.record_session("reader", role="analysis")
        task.update_session_context("reader", snapshot_ids=[first["dataset_id"], newer["dataset_id"]])
        if forked:
            # A session that may read only P refreshes against P: two batches now name P as their prior.
            fork = SourceRefreshService(task, allowed={first["dataset_id"]}).refresh_file(
                upload("s.csv", "S1,1,revenue,3\n"), scope=scope, name="S")
            assert fork["prior_snapshot_id"] == first["dataset_id"] == newer["prior_snapshot_id"]
        reads = {first["dataset_id"], newer["dataset_id"]}
        assert set(_snapshots(task, "reader")) == reads
        assert first["dataset_id"] in superseded_snapshots(task, allowed=reads)
        assert first["dataset_id"] in superseded_snapshots(task)
        code, ready = _cli(capsys, var, "finance-readiness", session="reader")
        assert code == 0
        freshness[name] = next(row for row in ready["datasets"] if row["name"] == "P")["freshness"]
    # The reader of P and M reads P as replaced by M whether or not a batch it may not read also replaced P.
    assert freshness["forked"] == freshness["alone"]
    assert "superseded" in [reason["code"] for reason in freshness["forked"]["reasons"]]


class _Resuming(FakeTransport):
    """Notes the checkpoint each pull resumes from."""

    def __init__(self, pages):
        super().__init__(pages)
        self.resumed = []

    def pull_page(self, scope, *, cursor, checkpoint):
        self.resumed.append(checkpoint)
        return super().pull_page(scope, cursor=cursor, checkpoint=checkpoint)


def test_a_session_pulling_a_source_resumes_and_dedupes_only_from_batches_it_may_read(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="拉取")
    scope = SourceScope(**SOURCE_SCOPE, mode="full_period")
    pages = [SourcePage(sequence=1, rows=[{"document_id": "H1", "line_id": "1", "management_account": "revenue",
                                           "amount": SECRET}], checkpoint={"cursor": "H1"}, is_last=True)]
    hidden = SourceRefreshService(task).refresh_transport(_Resuming(pages), scope, name="薪酬")
    pulled = _Resuming(pages)
    mine = SourceRefreshService(task, allowed=set()).refresh_transport(pulled, scope, name="总账")
    assert pulled.resumed == [None]
    assert (mine["duplicate_of"], mine["prior_snapshot_id"]) == (None, None)
    assert mine["dataset_id"] not in (None, hidden["dataset_id"])
    # The manager resumes from, and is answered with, the latest batch of all.
    again = _Resuming(pages)
    assert SourceRefreshService(task).refresh_transport(again, scope)["duplicate_of"] == mine["id"]
    assert again.resumed == [{"cursor": "H1"}]


# --- an upload of bytes already filed -------------------------------------------------------------------------------


@pytest.fixture
def upload(tmp_path):
    """The manager files H after the session began; the session holds the same bytes among its uploads."""
    var = tmp_path / "var"
    task = TaskStore(var).create(title="去重")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(tmp_path / "a.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")]), name="总账")
    task.record_session("sess", role="analysis")
    h_path = _csv(tmp_path / "h.csv", [("revenue", "2026-08", "集团", SECRET, "CNY", "元")])
    h = analysis.add_dataset(h_path, name="薪酬", metadata={"owner": "HR-only"})
    uploads = task.root / "analysis" / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "mine.csv").write_bytes(h_path.read_bytes())
    return SimpleNamespace(var=var, task=task, analysis=analysis, a=a, h=h, h_path=h_path,
                           hidden=[h["id"], "薪酬", "HR-only", "h.csv"])


def test_a_session_uploading_bytes_it_may_not_read_files_its_own_copy(upload, capsys):
    code, added = _cli(capsys, upload.var, "dataset-add", "--path", "uploads/mine.csv", "--name", "我的收入",
                       "--meta", json.dumps({"period": "2026-09"}))
    assert code == 0
    assert "duplicate_of" not in added and added["id"] != upload.h["id"]
    assert (added["name"], added["metadata"], added["source_name"]) == ("我的收入", {"period": "2026-09"}, "mine.csv")
    assert added["context_revision"] == 2 and "structure_proposal" in added
    assert _shows(added, upload.hidden) == []
    assert _snapshots(upload.task) == [upload.a["id"], added["id"]]
    code, read = _cli(capsys, upload.var, "dataset-read", "--dataset", added["id"])
    assert code == 0 and read["rows"][0]["amount"] == SECRET
    # Its own copy answers its next upload of the same bytes, never the older hidden one.
    code, again = _cli(capsys, upload.var, "dataset-add", "--path", "uploads/mine.csv", "--name", "再来")
    assert code == 0
    assert again["duplicate_of"] == again["id"] == added["id"]
    assert _shows(again, upload.hidden) == []
    # The manager is answered from every upload, oldest first, as before.
    code, managed = _cli(capsys, upload.var, "dataset-add", "--path", str(upload.h_path), "--name", "再传",
                         session=None, task=upload.task.id)
    assert code == 0
    assert managed["duplicate_of"] == managed["id"] == upload.h["id"]
    assert {key: value for key, value in managed.items() if key != "duplicate_of"} == upload.analysis.published_datasets()[1]


def test_a_session_holding_a_copy_is_answered_with_it_not_the_hidden_original(upload, capsys):
    code, own = _cli(capsys, upload.var, "dataset-add", "--path", "uploads/mine.csv", "--name", "我的", "--allow-duplicate")
    assert code == 0 and own["id"] != upload.h["id"]
    code, again = _cli(capsys, upload.var, "dataset-add", "--path", "uploads/mine.csv", "--name", "再来")
    assert code == 0
    assert again["duplicate_of"] == own["id"]
    assert _shows(again, upload.hidden) == []


def test_the_store_answers_a_same_bytes_upload_only_from_the_uploads_allowed(upload):
    session = upload.analysis.add_dataset(upload.h_path, name="会话", allowed={upload.a["id"]})
    assert "duplicate_of" not in session and session["id"] != upload.h["id"]
    assert upload.analysis.add_dataset(upload.h_path, name="经理")["duplicate_of"] == upload.h["id"]


def test_an_excel_import_is_not_answered_with_another_session_s_snapshot(tmp_path):
    from foundry.excel_bridge import BridgeTokenAuthority, ExcelBridgeApp

    var = tmp_path / "var"
    task = TaskStore(var).create(title="Excel")
    task.record_session("s1", role="analysis")
    task.record_session("s2", role="analysis")
    authority = BridgeTokenAuthority(b"local-test-secret-local-test-secret")
    app = ExcelBridgeApp(var_root=var, token_authority=authority)
    names = ["management_account", "amount", "organization", "period", "currency", "unit", "scenario"]
    binding = {"id": "actual", "name": "actual", "role": "input", "worksheet": "Model", "address": "Model!A1:G2",
               "binding_type": "matrix", "headers": names, "header": True,
               "fields": [{"name": name, "policy": "text"} for name in names]}
    values = [names, ["revenue", SECRET, "HQ", "2026-08", "CNY", "yuan", "actual"]]

    def imported(session, name):
        headers = {"Authorization": f"Bearer {authority.issue(task_id=task.id, session_id=session, ttl_seconds=60)}"}
        app.handle("POST", "/api/register-workbook", headers, json.dumps(
            {"workbook_id": f"wb_{session}", "name": "m.xlsx", "host": {"excelApi11": True}}).encode())
        status, _, out = app.handle("POST", "/api/import-binding", headers, json.dumps(
            {"workbook_id": f"wb_{session}", "binding": binding, "values": values, "name": name, "alias": "actual",
             "scope": {}, "policy": {}}).encode())
        assert status == 200
        return json.loads(out)

    first = imported("s1", "S1 私有导入")
    second = imported("s2", "S2 导入")
    assert second["dataset"]["id"] != first["dataset"]["id"]
    assert "duplicate_of" not in second["dataset"] and second["dataset"]["name"] == "S2 导入"
    assert _snapshots(task, "s2") == [second["dataset"]["id"]]
    assert second["finance_context"]["bindings"] == {"actual": second["dataset"]["id"]}
    # The same session importing the same values again is answered with its own snapshot.
    assert imported("s2", "S2 再导入")["dataset"]["duplicate_of"] == second["dataset"]["id"]


# --- the requirements version a session runs and saves against ---------------------------------------------------


ITEMS = [{"id": "rev", "metric": "revenue", "label": "收入"}]
SCRIPT_ROWS = [{"metric_key": "revenue", "organization": "Falcon", "value": "100"}]


@pytest.fixture
def fake_runner(monkeypatch):
    import foundry.runner as runner

    def run(workspace, code, **options):
        data = json.dumps(SCRIPT_ROWS).encode()
        (Path(workspace) / "result.json").write_bytes(data)
        return {"status": "succeeded", "stdout": "", "stderr": "", "exit_code": 0, "workspace": str(workspace),
                "outputs": [{"path": "result.json", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}],
                "environment": {"mocked": True}}

    monkeypatch.setattr(runner, "run_script", run)


def _version_world(root: Path, hidden: bool):
    """V on A, inside the session; with ``hidden``, a newer version on a file outside it that declares the Falcon
    revenue an estimate for July."""
    var = root / "var"
    task = TaskStore(var).create(title="要求版本")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(root / "a.csv", [("revenue", "2026-08", "Falcon", "100", "CNY", "元")]), name="总账")["id"]
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_csv(root / "h.csv", [("revenue", "2026-07", "Falcon", "100", "CNY", "元")]), name="薪酬")["id"]
    manager = FinanceStore(task)
    visible = manager.analysis_requirements_save({"question": "收入", "scope": {"period": "2026-08"},
                                                  "bindings": {"gl": a}, "items": ITEMS})
    newer = None
    if hidden:
        newer = manager.analysis_requirements_save({
            "question": "Falcon 项目", "scope": {"period": "2026-07"}, "bindings": {"payroll": h},
            "parent_id": visible["id"], "change_reason": "换项目",
            "items": [{"id": "falcon", "metric": "revenue", "label": "Falcon 收入", "organizations": ["Falcon"],
                       "grain_basis": [{"basis": "estimate", "method": "按人数分摊", "organizations": ["Falcon"]}]}]})
    return SimpleNamespace(var=var, task=task, a=a, h=h, visible=visible, newer=newer)


def _session_runs(world, capsys, monkeypatch) -> dict[str, dict]:
    """Every way a session runs something, each as it saves the run."""
    from foundry.analysis_jobs import JobStore, _worker
    from foundry.context import resolve_context

    var, a = world.var, world.a
    code, saved = _cli(capsys, var, "analysis-save", "--spec", json.dumps({"question": "收入", "sql": SQL, "bindings": {"t": a}}))
    assert code == 0
    script_spec = {"code": "print(1)", "bindings": {"t": a}, "result_file": "result.json"}
    runs = {"sql": _cli(capsys, var, "analysis-run", "--analysis", saved["id"]),
            "script": _cli(capsys, var, "analysis-script", "--spec", json.dumps(script_spec))}
    runs["script again"] = _cli(capsys, var, "analysis-run", "--analysis", runs["script"][1]["analysis_id"])
    jobs = JobStore(world.task)
    monkeypatch.setattr(jobs, "_launch", lambda record: None)
    job = jobs.create(resolve_context(var, session_id="sess"), "script", script_spec)
    _worker(var, world.task.id, job["id"])
    runs["job"] = (0, AnalysisStore(world.task).get_run(jobs.get(job["id"])["result"]["run_id"]))
    context = FinanceStore(world.task).save_context({"bindings": {"ledger": a}, "scopes": {}})
    finance = FinanceStore(world.task, snapshot_ids=[a], session_id="sess").run_metric(
        {"context_id": context["id"], "metric": {"kind": "account_total", "accounts": ["revenue"]}})
    runs["finance"] = (0, finance)
    runs["finance again"] = _cli(capsys, var, "analysis-run", "--analysis", finance["analysis_id"])
    assert [code for code, _ in runs.values()] == [0] * len(runs), runs
    return {name: run for name, (_, run) in runs.items()}


def test_a_session_s_runs_capture_the_newest_requirements_version_it_may_read(tmp_path, capsys, fake_runner, monkeypatch):
    captured = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _version_world(tmp_path / name, hidden)
        secrets = [world.h, *([world.newer["id"], "falcon", "Falcon 项目"] if hidden else [])]
        runs = _session_runs(world, capsys, monkeypatch)
        for run in runs.values():
            assert (run["requirements_id"], run["requirements_semantic_fingerprint"]) == (
                world.visible["id"], world.visible["semantic_fingerprint"])
            assert _shows(run, secrets) == []
        for script in ("script", "script again", "job"):
            declaration = runs[script]["row_declarations"]
            assert declaration["requirements_id"] == world.visible["id"]
            assert declaration["rows"][0]["estimate"] is False
        # Each world's version hashes its own file ids: name it, as the ids are named.
        captured.append(_normalized(json.loads(json.dumps({way: {key: run.get(key) for key in (
            "requirements_id", "requirements_semantic_fingerprint", "row_declarations")} for way, run in runs.items()},
            ensure_ascii=False).replace(world.visible["semantic_fingerprint"], "<fingerprint>"))))
    # A world with a newer version outside the session captures what one without it captures.
    assert captured[0] == captured[1]
    # The manager captures the task's latest, as before.
    code, managed = _cli(capsys, world.var, "analysis-run", "--analysis", runs["sql"]["analysis_id"],
                         session=None, task=world.task.id)
    assert code == 0 and managed["requirements_id"] == world.newer["id"]


def test_a_session_s_readiness_reads_the_period_of_the_newest_requirements_version_it_may_read(tmp_path, capsys):
    read = []
    for name, hidden in (("plain", False), ("hidden", True)):
        world = _version_world(tmp_path / name, hidden)
        code, report = _cli(capsys, world.var, "finance-readiness")
        assert code == 0
        [row] = [row for row in report["datasets"] if row["dataset_id"] == world.a]
        read.append(row["freshness"])
        assert "2026-07" not in json.dumps(report, ensure_ascii=False)
    assert read == [{"state": "current", "reasons": []}] * 2
    code, managed = _cli(capsys, world.var, "finance-readiness", session=None, task=world.task.id)
    [row] = [row for row in managed["datasets"] if row["dataset_id"] == world.a]
    assert row["freshness"]["reasons"][0]["text"] == "资料期间 2026-08 与分析期间 2026-07 不同"


def _legacy_world(root: Path, hidden: bool):
    """The current version V rests on A; with ``hidden``, its parent is a version saved before phase 1 on a file
    outside the session, whose scope and item hold a drilldown level."""
    task = TaskStore(root / "var").create(title="要求修订")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_entry(root / "a.json", "revenue", "100"), name="A")["id"]
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_entry(root / "h.json", "revenue", "999"), name="H")["id"]
    parent = None
    if hidden:
        legacy = _new(task, question="Falcon 项目", scope={"period": "2026-08", "drilldown": "Falcon"},
                      bindings={"payroll": h}, context_id=None, parent_id=None, removed_item_ids=[], change_reason="",
                      selection=None, items=[{**ITEMS[0], "dimensions": {"drilldown": "Falcon"}, "requires_drilldown": False}])
        parent = analysis._write(analysis._object_path("requirements", legacy["id"]), legacy)["id"]
    visible = FinanceStore(task).analysis_requirements_save({
        "question": "收入", "scope": {"period": "2026-08"}, "bindings": {"gl": a}, "items": ITEMS,
        **({"parent_id": parent} if parent else {})})
    return task, a, parent, visible


def test_a_requirements_version_outside_a_session_neither_shows_nor_decides_what_its_save_keeps(tmp_path):
    specs = {"scope": {"scope": {"period": "2026-08", "drilldown": "Falcon"}, "items": ITEMS},
             "item": {"scope": {"period": "2026-08"}, "items": [{**ITEMS[0], "dimensions": {"drilldown": "Falcon"}}]}}
    refusals = {kind: [] for kind in specs}
    for name, hidden in (("plain", False), ("hidden", True)):
        task, a, parent, visible = _legacy_world(tmp_path / name, hidden)
        session = FinanceStore(task, snapshot_ids=[a], session_id="sess")
        for kind, spec in specs.items():
            for parent_id in [visible["id"], *([parent, "e" * 32] if parent else [])]:
                with pytest.raises(FoundryError) as refused:
                    session.analysis_requirements_save({"question": "收入", **spec, "bindings": {"gl": a},
                                                        "parent_id": parent_id})
                refusals[kind].append((str(refused.value).replace(parent_id, "<id>"),
                                       getattr(refused.value, "details", None)))
                assert parent is None or parent not in str(refused.value)
    # The same refusal in a world without the hidden version, and for a hidden parent as for a missing one.
    for kind, code in (("scope", "requirement_scope_not_row_filter"), ("item", "requirement_dimension_not_row_filter")):
        assert len({json.dumps(refusal, ensure_ascii=False, sort_keys=True) for refusal in refusals[kind]}) == 1
        assert refusals[kind][0][1]["code"] == code
    # The manager still drops the level the legacy ancestor held.
    saved = FinanceStore(task).analysis_requirements_save({"question": "收入", **specs["scope"], "bindings": {"gl": a},
                                                           "parent_id": visible["id"]})
    assert saved["scope"] == {"period": "2026-08"}
    assert [warning["code"] for warning in saved["authoring_warnings"]] == ["hierarchy_scope_dropped"]


def test_a_session_s_draft_check_holds_no_level_only_a_hidden_earlier_version_held(tmp_path):
    checked = {}
    for name, hidden in (("plain", False), ("hidden", True)):
        task, a, parent, visible = _legacy_world(tmp_path / name, hidden)
        session = FinanceStore(task, snapshot_ids=[a], session_id="sess")
        saved = session.save_explanation_draft({"body": "收入待核。"})
        validated = session.validate_explanation({"body": "收入待核。"})
        assert _shows([saved, validated], ["Falcon"]) == []
        checked[name] = [check["requirements"]["items"][0].get("dropped_hierarchy")
                         for check in (saved["explanation_check"], validated)]
    assert checked["hidden"] == checked["plain"] == [None, None]
    # The manager's check still names the level the requirement asked for once.
    managed = FinanceStore(task).save_explanation_draft({"body": "经理稿：收入待核。"})
    assert managed["explanation_check"]["requirements"]["items"][0]["dropped_hierarchy"] == {"drilldown": "Falcon"}


@pytest.mark.parametrize("periods", [[], ["2026-07"]])
def test_circle_select_refuses_a_hidden_current_version_before_reading_or_writing_anything(tmp_path, periods):
    task = TaskStore(tmp_path / "var").create(title="圈选")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_entry(tmp_path / "a.json", "revenue", "100"), name="A")["id"]
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_entry(tmp_path / "h.json", "revenue", "999"), name="H")["id"]
    manager = FinanceStore(task)
    context = manager.save_context({"bindings": {"ledger": a}, "scopes": {"ledger": SCOPE}})
    first = manager.analysis_requirements_save({"context_id": context["id"], "question": "收入", "items": ITEMS})
    # Checked against the version the session may read, so the draft is one it may read.
    draft = analysis.save_draft({"title": "简报", "document": _table("tbl")})
    hidden_context = manager.save_context({"bindings": {"ledger": h}, "scopes": {"ledger": {
        key: value for key, value in SCOPE.items() if key != "period"}}})
    manager.analysis_requirements_save({"context_id": hidden_context["id"], "question": "Falcon 项目", "parent_id": first["id"],
                                        "change_reason": "换项目", "items": [{**ITEMS[0], "periods": periods}]})
    contexts = sorted((analysis.root / "finance" / "contexts").glob("*.json"))
    versions = len(analysis._list("requirements"))
    session = FinanceStore(task, snapshot_ids=[a], session_id="sess")
    with pytest.raises(FoundryError) as saved:
        session.analysis_requirements_save({"context_id": context["id"], "question": "收入", "parent_id": first["id"],
                                            "items": ITEMS})
    with pytest.raises(FoundryError) as refused:
        session.analysis_circle_select({"kind": "draft_table", "range": "A1", "context_id": context["id"],
                                        "draft_id": draft["id"], "block_id": "tbl", "instruction": "按区域拆开"})
    # Refused as its requirements save is refused, before anything is taken from that version or written.
    assert str(refused.value) == str(saved.value)
    assert "outside this session context" in str(refused.value)
    assert _shows(str(refused.value), ["Falcon", "2026-07"]) == []
    assert sorted((analysis.root / "finance" / "contexts").glob("*.json")) == contexts
    assert len(analysis._list("requirements")) == versions


def test_mcp_refuses_a_hidden_requirements_parent_as_a_missing_one(tmp_path):
    from foundry.finance_mcp import FinanceMcpServer, McpRefused, create_stdio_grant

    task = TaskStore(tmp_path / "var").create(title="授权")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_entry(tmp_path / "a.json", "revenue", "100"), name="A")["id"]
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_entry(tmp_path / "h.json", "revenue", "999"), name="H")["id"]
    manager = FinanceStore(task)
    context = manager.save_context({"bindings": {"ledger": a}, "scopes": {"ledger": SCOPE}})
    hidden = manager.analysis_requirements_save({"question": "Falcon", "bindings": {"payroll": h}, "items": ITEMS})
    grant = create_stdio_grant(task.store.var_root, task_id=task.id, session_id="sess", snapshot_ids=[a],
                               context_ids=[context["id"]])
    server = FinanceMcpServer(var_root=task.store.var_root, grant_id=grant["grant_id"], token=grant["token"])
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    refused = []
    for parent_id in (hidden["id"], "e" * 32):
        with pytest.raises(McpRefused) as error:
            server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "analysis_requirements_save",
                "arguments": {"context_id": context["id"], "question": "收入", "items": ITEMS, "parent_id": parent_id}}})
        refused.append(str(error.value))
    assert refused[0] == refused[1]


# --- reproducibility ------------------------------------------------------------------------------------------------


PLAN = {"dataset_alias": "t", "group_by": ["organization"], "filters": [],
        "measures": [{"name": "amount", "field": "amount", "aggregation": "sum"}], "dedupe": {"policy": "none"}}


@pytest.fixture
def twin(tmp_path):
    """The session may read B; A, filed after it began, holds the same rows under another snapshot."""
    var = tmp_path / "var"
    task = TaskStore(var).create(title="复现")
    analysis = AnalysisStore(task)
    path = _csv(tmp_path / "b.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")])
    b = analysis.add_dataset(path, name="总账")
    task.record_session("sess", role="analysis")
    a = analysis.add_dataset(path, name="薪酬", allow_duplicate=True)
    assert a["id"] != b["id"] and a["data_hash"] == b["data_hash"]
    return SimpleNamespace(var=var, task=task, analysis=analysis, a=a, b=b)


def _analysis_spec(engine: str, dataset: dict) -> dict:
    if engine == "sql":
        return {"question": "收入", "sql": SQL, "bindings": {"t": dataset["id"]}}
    return {"question": "收入", "engine": "structured_aggregate", "bindings": {"t": dataset["id"]}, "aggregate_plan": PLAN}


@pytest.mark.parametrize("engine", ["sql", "structured_aggregate"])
def test_a_session_s_run_is_compared_only_with_runs_it_may_read(twin, capsys, engine):
    hidden = twin.analysis.run_analysis(twin.analysis.save_analysis(_analysis_spec(engine, twin.a))["id"])
    code, saved = _cli(capsys, twin.var, "analysis-save", "--spec", json.dumps(_analysis_spec(engine, twin.b)))
    assert code == 0
    code, first = _cli(capsys, twin.var, "analysis-run", "--analysis", saved["id"])
    assert code == 0
    # The same fingerprint (the inputs are keyed by their rows), yet nothing earlier the session may read.
    assert first["fingerprint"] == hidden["fingerprint"]
    assert first["reproducibility_status"] == "unverified"
    code, state = _cli(capsys, twin.var, "analysis-state")
    assert [(run["id"], run["reproducibility_status"]) for run in state["runs"]] == [(first["id"], "unverified")]
    code, second = _cli(capsys, twin.var, "analysis-run", "--analysis", saved["id"])
    assert second["reproducibility_status"] == "reproducible"
    claim = {"run_id": first["id"], "row": 0, "column": "amount", "value": first["result"]["rows"][0]["amount"],
             "basis": "calculation"}
    code, draft = _cli(capsys, twin.var, "analysis-draft", "--spec", json.dumps(
        {"title": "收入", "body": "收入 100。", "run_ids": [first["id"]], "claims": [claim]}))
    assert code == 0, draft
    assert draft["reproducibility_status"] == "unverified"
    code, managed = _cli(capsys, twin.var, "analysis-run", "--analysis", saved["id"], session=None, task=twin.task.id)
    assert managed["reproducibility_status"] == ("reproducible" if engine == "sql" else "non_reproducible")


def test_the_manager_s_run_is_compared_with_runs_on_any_snapshot_as_before(twin, capsys):
    twin.analysis.run_analysis(twin.analysis.save_analysis(_analysis_spec("sql", twin.a))["id"])
    code, saved = _cli(capsys, twin.var, "analysis-save", "--spec", json.dumps(_analysis_spec("sql", twin.b)),
                       session=None, task=twin.task.id)
    code, run = _cli(capsys, twin.var, "analysis-run", "--analysis", saved["id"], session=None, task=twin.task.id)
    assert run["reproducibility_status"] == "reproducible"


# --- drafts named by id ---------------------------------------------------------------------------------------------


CAPTION = "Falcon薪酬表"


def _table(caption: str) -> dict:
    cell = {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "费用"}]}]}
    return {"schema_version": 1, "template_version": "annual-v1",
            "content": [{"type": "table", "attrs": {"caption": caption},
                         "content": [{"type": "tableRow", "content": [cell]}]}]}


@pytest.fixture
def circled(tmp_path):
    """The manager drafts a table on a file outside the session (H) and one on no file; requirements rest on A."""
    var = tmp_path / "var"
    task = TaskStore(var).create(title="圈选")
    analysis = AnalysisStore(task)
    manager = FinanceStore(task)
    a = analysis.add_dataset(_entry(tmp_path / "a.json", "expense", "20"), name="总账")
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_entry(tmp_path / "h.json", "expense", "987654"), name="薪酬")
    context = manager.save_context({"bindings": {"actual": a["id"]}, "scopes": {"actual": SCOPE}})
    hidden_context = manager.save_context({"bindings": {"payroll": h["id"]}, "scopes": {"payroll": SCOPE}})
    requirements = manager.analysis_requirements_save({"context_id": context["id"], "question": "解释费用",
                                                       "items": [{"id": "expense", "metric": "expense"}]})
    hidden = analysis.save_draft({"title": "薪酬简报", "document": _table(CAPTION),
                                  "claims": [{"basis": "source_fact", "dataset_id": h["id"], "text": "薪酬"}]})
    shown = analysis.save_draft({"title": "简报", "document": _table("tbl-expense")})
    return SimpleNamespace(var=var, task=task, analysis=analysis, manager=manager, a=a, h=h, context=context,
                           hidden_context=hidden_context, requirements=requirements, hidden=hidden, shown=shown,
                           session=FinanceStore(task, snapshot_ids=[a["id"]], session_id="sess"))


def _written(world) -> tuple[int, int]:
    """Requirements versions and finance contexts on file."""
    return (len(world.analysis._list("requirements")),
            len(list((world.analysis.root / "finance" / "contexts").glob("*.json"))))


def test_a_session_circles_a_table_only_in_a_draft_it_may_read(circled, capsys):
    from foundry.analysis import DRAFT_UNAVAILABLE

    base = {"kind": "draft_table", "range": "A:A", "instruction": "改成开票口径", "context_id": circled.context["id"]}
    before = _written(circled)
    errors = []
    for draft_id in (circled.hidden["id"], "f" * 32):
        for block_id in ("nope", CAPTION):
            with pytest.raises(FoundryError) as refused:
                circled.session.analysis_circle_select({**base, "draft_id": draft_id, "block_id": block_id})
            errors.append(str(refused.value))
        code, error = _cli(capsys, circled.var, "analysis-circle-select", "--spec",
                           json.dumps({**base, "draft_id": draft_id, "block_id": CAPTION}, ensure_ascii=False))
        assert code != 0
        errors.append(error.strip())
    assert set(errors) == {DRAFT_UNAVAILABLE}
    assert _written(circled) == before
    # A draft the session may read is circled as before.
    revised = circled.session.analysis_circle_select({**base, "draft_id": circled.shown["id"], "block_id": "tbl-expense"})
    assert revised["requirements"]["selection"]["draft_id"] == circled.shown["id"]
    # The manager circles any draft, and is told what it holds, as before.
    with pytest.raises(FoundryError, match=f"no table in this draft is called nope; it has {CAPTION}"):
        circled.manager.analysis_circle_select({**base, "draft_id": circled.hidden["id"], "block_id": "nope"})
    code, managed = _cli(capsys, circled.var, "analysis-circle-select", "--spec",
                         json.dumps({**base, "draft_id": circled.hidden["id"], "block_id": CAPTION}, ensure_ascii=False),
                         session=None, task=circled.task.id)
    assert code == 0 and managed["requirements"]["selection"]["block_id"] == CAPTION


def test_a_session_names_a_hidden_or_unknown_draft_alike(circled):
    from foundry.analysis import DRAFT_UNAVAILABLE
    from foundry.finance_mcp import FinanceMcpServer, McpRefused

    run = circled.manager.run_metric({"context_id": circled.hidden_context["id"], "metric": {"kind": "control_totals"}})
    with_run = circled.analysis.save_draft({"title": "薪酬", "document": _table(CAPTION), "run_ids": [run["id"]]})
    grant = {"snapshot_ids": [circled.a["id"]], "context_ids": [circled.context["id"]]}
    errors = []
    for draft_id in (circled.hidden["id"], with_run["id"], "f" * 32):
        for call in (lambda: circled.session.validate_explanation({"draft_id": draft_id}),
                     lambda: circled.session.validate_explanation({"draft_id": draft_id, "claims": []}),
                     lambda: circled.session.report_review({"draft_id": draft_id}),
                     lambda: FinanceMcpServer._authorize_context(None, grant, circled.session, "validate_explanation",
                                                                 {"context_id": circled.context["id"], "draft_id": draft_id})):
            with pytest.raises(FoundryError) as refused:
                call()
            assert not isinstance(refused.value, McpRefused)
            errors.append(str(refused.value))
    assert set(errors) == {DRAFT_UNAVAILABLE}
    # The manager reads every draft, and is refused an unknown one, as before.
    assert circled.manager.validate_explanation({"draft_id": circled.hidden["id"]})
    with pytest.raises(FoundryError) as unknown:
        circled.analysis.get_draft("f" * 32)
    for call in (lambda: circled.manager.validate_explanation({"draft_id": "f" * 32}),
                 lambda: circled.manager.report_review({"draft_id": "f" * 32}),
                 lambda: circled.manager.analysis_circle_select({
                     "kind": "draft_table", "range": "A:A", "instruction": "改成开票口径",
                     "context_id": circled.context["id"], "draft_id": "f" * 32, "block_id": CAPTION})):
        with pytest.raises(FoundryError) as refused:
            call()
        assert str(refused.value) == str(unknown.value)


def test_a_session_reads_or_exports_a_hidden_draft_by_id_as_an_unknown_one(circled, capsys):
    from foundry.analysis import DRAFT_UNAVAILABLE

    commands = [("analysis-export",), ("report-draft-read",), ("report-projection-read", "--mode", "audit")]
    errors = []
    for draft_id in (circled.hidden["id"], "f" * 32, "zz"):
        for command in commands:
            code, error = _cli(capsys, circled.var, command[0], "--draft", draft_id, *command[1:])
            assert code != 0
            errors.append(error.strip())
    assert set(errors) == {DRAFT_UNAVAILABLE}
    for command in commands:
        assert _cli(capsys, circled.var, command[0], "--draft", circled.shown["id"], *command[1:])[0] == 0
        # The manager reads the draft, and is told an unknown id is unavailable, as before.
        manager = {"session": None, "task": circled.task.id}
        assert _cli(capsys, circled.var, command[0], "--draft", circled.hidden["id"], *command[1:], **manager)[0] == 0
        code, error = _cli(capsys, circled.var, command[0], "--draft", "f" * 32, *command[1:], **manager)
        assert code != 0 and "analysis object is unavailable" in error


def test_a_session_circle_select_on_a_current_version_it_may_not_read_writes_nothing(circled):
    circled.manager.analysis_requirements_save({
        "context_id": circled.hidden_context["id"], "question": "Falcon 项目薪酬", "parent_id": circled.requirements["id"],
        "change_reason": "换项目", "items": [{"id": "falcon", "metric": "expense", "label": "Falcon 薪酬"}]})
    spec = {"kind": "draft_table", "range": "A:A", "instruction": "改成开票口径", "context_id": circled.context["id"],
            "draft_id": circled.shown["id"], "block_id": "tbl-expense"}
    before = _written(circled)
    with pytest.raises(FoundryError) as saved:
        circled.session.analysis_requirements_save({"context_id": circled.context["id"], "question": "q",
                                                    "parent_id": circled.requirements["id"],
                                                    "items": [{"id": "expense", "metric": "expense"}]})
    for named in ({}, {"parent_id": circled.requirements["id"]}):
        with pytest.raises(FoundryError) as refused:
            circled.session.analysis_circle_select({**spec, **named})
        # Refused as the requirements save refuses it, naming nothing of that version, and before any child context.
        assert str(refused.value) == str(saved.value)
        assert "Falcon" not in str(refused.value)
    assert _written(circled) == before
    # The manager revises the current version as before.
    assert circled.manager.analysis_circle_select(spec)["requirements"]["question"] == "Falcon 项目薪酬"


def test_a_session_circles_no_table_a_revision_took_from_a_parent_it_may_not_read(circled):
    from foundry.analysis import DRAFT_UNAVAILABLE

    # The revision's document is its parent's, written from the hidden file.
    child = circled.analysis.save_draft({"title": "C", "parent_id": circled.hidden["id"], "claims": []})
    assert child["document"]["content"][0]["attrs"]["caption"] == CAPTION
    with pytest.raises(FoundryError) as refused:
        circled.session.analysis_circle_select({"kind": "draft_table", "range": "A:A", "instruction": "改成开票口径",
                                                "context_id": circled.context["id"], "draft_id": child["id"],
                                                "block_id": "nope"})
    assert str(refused.value) == DRAFT_UNAVAILABLE


# --- recovering a session's completion operation --------------------------------------------------------------------


def _normalized_operation(value) -> str:
    """_normalized, with a draft's content hash blanked too: the two worlds' drafts hash different ids."""
    text = re.sub(r'"draft_content_hash": "[0-9a-f]{64}"', '"draft_content_hash": "<hash>"',
                  json.dumps(value, ensure_ascii=False))
    return _normalized(json.loads(text))


@pytest.mark.parametrize("live", [False, True])
def test_a_recovery_on_a_draft_its_session_may_not_read_leaves_the_session_s_operation_as_it_was(tmp_path, capsys, live):
    from foundry.finance_completion_operations import CompletionOperationStore, list_completion_recoveries

    reads = {}
    for recover in (True, False):
        root = tmp_path / ("recovered" if recover else "left")
        root.mkdir()
        sess, _wide, run = _chain(root, 2)
        var = root / "var2"
        code, operation = _cli(capsys, var, "finance-completion-begin",
                               "--spec", json.dumps({"request_key": "request-1", "policy": {"max_repairs": 2}}))
        assert code == 0
        operations = CompletionOperationStore(sess.task, "sess", sess.allowed)
        operations.reserve(operation["id"], payload={"body": "会话稿。"}, call_id="call-1")
        if live:  # rejected with a repair left: the recovered verdict would decide the session's status
            operations.reject_attempt(operation["id"], 1, {"code": "claim_value_mismatch", "message": "bad"})
        else:     # timed out: only the revision and its event would change
            operations.stop(operation["id"], "timeout")
        hidden = []
        if recover:
            manager = FinanceStore(sess.task)
            spec = {"operation_id": operation["id"], "revision": 1,
                    "draft": {"body": "宽口径恢复稿。", "run_ids": [run["id"]]}}
            recovered = manager.recover_completion_draft(spec)
            hidden = [recovered["id"], recovered["completion"]["id"], recovered["content_hash"]]
            # The manager's draft and receipt are as before; a replay returns them, another payload is refused.
            assert recovered["completion"] == manager.analysis._get("completions", recovered["completion"]["id"])
            assert (recovered["completion_operation_id"], recovered["completion_operation_revision"]) == (operation["id"], 1)
            assert manager.recover_completion_draft(spec)["id"] == recovered["id"]
            with pytest.raises(FoundryError, match="different payload"):
                manager.recover_completion_draft({**spec, "draft": {"body": "另一稿。"}})
            assert list_completion_recoveries(sess.task) == {"recoveries": []}
            # The session may not read the draft at all.
            assert _cli(capsys, var, "report-draft-read", "--draft", recovered["id"])[0] != 0
        code, status = _cli(capsys, var, "finance-completion-status", "--spec", json.dumps({"operation_id": operation["id"]}))
        assert code == 0
        code, begun = _cli(capsys, var, "finance-completion-begin", "--spec", json.dumps({"request_key": "request-1"}))
        assert code == 0
        direct = CompletionOperationStore(sess.task, "sess", sess.allowed).get(operation["id"])
        assert _shows([status, begun, direct], hidden) == []
        try:
            saved = sess.save_completion_draft(operation["id"], "call-2", {"body": "会话修订稿。"})
            after = ("saved", saved["completion_operation"])
            assert saved["completion_operation"]["revisions"][-1]["draft_content_hash"] == saved["content_hash"]
        except FoundryError as exc:
            after = ("refused", str(exc))
        assert _shows(after, hidden) == []
        reads[recover] = [_normalized_operation(read) for read in (status, begun, direct, after)]
    # Nothing of the hidden draft shows through or changes what the session reads or saves.
    assert reads[True] == reads[False]


def test_a_recovery_left_unsettled_is_not_settled_later_behind_a_newer_revision(tmp_path, capsys):
    from foundry.finance_completion_operations import CompletionOperationStore

    sess, _wide, run = _chain(tmp_path, 2)
    var = tmp_path / "var2"
    code, operation = _cli(capsys, var, "finance-completion-begin",
                           "--spec", json.dumps({"request_key": "request-1", "policy": {"max_repairs": 2}}))
    assert code == 0
    operations = CompletionOperationStore(sess.task, "sess", sess.allowed)
    operations.reserve(operation["id"], payload={"body": "会话稿。"}, call_id="call-1")
    operations.reject_attempt(operation["id"], 1, {"code": "claim_value_mismatch", "message": "bad"})
    manager = FinanceStore(sess.task)
    spec = {"operation_id": operation["id"], "revision": 1, "draft": {"body": "宽口径恢复稿。", "run_ids": [run["id"]]}}
    manager.recover_completion_draft(spec)
    saved = sess.save_completion_draft(operation["id"], "call-2", {"body": "会话修订稿。"})
    assert saved["completion_operation"]["current_revision"] == 2
    # The session may now read the recovered draft; the manager's replay of the recovery settles nothing behind
    # revision 2, whose verdict the operation goes on by.
    sess.task.update_session_context("sess", snapshot_ids=[*sess.allowed, *run["bindings"].values()])
    before = operations.get(operation["id"])
    replayed = manager.recover_completion_draft(spec)
    assert replayed["replayed"] is True
    assert replayed["completion_operation"] == before == operations.get(operation["id"])
    assert [row.get("completion_id") is not None for row in before["revisions"]] == [False, True]


def test_an_interrupted_recovery_of_a_draft_its_session_may_read_settles_late_as_before(tmp_path, capsys, monkeypatch):
    from foundry.finance_completion_operations import CompletionOperationStore

    sess, _wide, _run = _chain(tmp_path, 2)
    var = tmp_path / "var2"
    code, operation = _cli(capsys, var, "finance-completion-begin",
                           "--spec", json.dumps({"request_key": "request-1", "policy": {"max_repairs": 2}}))
    assert code == 0
    operations = CompletionOperationStore(sess.task, "sess", sess.allowed)
    operations.reserve(operation["id"], payload={"body": "会话稿。"}, call_id="call-1")
    operations.reject_attempt(operation["id"], 1, {"code": "claim_value_mismatch", "message": "bad"})
    manager = FinanceStore(sess.task)
    spec = {"operation_id": operation["id"], "revision": 1, "draft": {"body": "经理恢复稿。"}}
    settle = CompletionOperationStore.settle

    def interrupted(*args, **kwargs):
        monkeypatch.setattr(CompletionOperationStore, "settle", settle)
        raise OSError("interrupted")

    monkeypatch.setattr(CompletionOperationStore, "settle", interrupted)
    with pytest.raises(OSError):
        manager.recover_completion_draft(spec)
    sess.save_completion_draft(operation["id"], "call-2", {"body": "会话修订稿。"})
    # The session may read this receipt, so nothing held it back: the replay settles revision 1, late, as on main.
    replayed = manager.recover_completion_draft(spec)
    assert replayed["replayed"] is True
    settled = operations.get(operation["id"])
    assert settled["revisions"][0]["completion_id"] == replayed["completion"]["id"]
    assert [event["revision"] for event in settled["events"] if event["type"] == "revision_settled"] == [2, 1]
