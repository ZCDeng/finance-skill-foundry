"""A session saves and files every record as it would have from the files it may read.

A session's snapshot ceiling (context.snapshot_ids; FinanceStore.allowed; an MCP grant's snapshot_ids) decides what
it may build on, as it decides what it may read (test_session_views). A record that rests on a file outside it
neither shows nor changes what the session saves: not a source batch a refresh compares with, an upload of the
same bytes, a requirements version, an earlier run of the same fingerprint, a draft named by id or a draft a
recovery files for it. The Excel bridge's record of a workbook is the session's own: what another session bound,
imported, previewed or logged in the same file is no part of it. A record the session may not read is refused
exactly as one that does not exist: a draft, requirements version, run or saved analysis it names by id is answered
as an id never saved or no id at all. The manager (no session) saves and is answered as before.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from foundry.analysis import AnalysisStore, _hash, _new
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


# --- a workbook another session opened ------------------------------------------------------------------------------


BRIDGE_FIELDS = ["management_account", "amount", "organization", "period", "currency", "unit", "scenario"]
BRIDGE_OUTPUT = {"id": "out", "name": "out", "role": "output", "writable": True, "dedicated_area": True,
                 "worksheet": "Model", "address": "Model!J1:J2", "headers": ["amount"], "header": True,
                 "fields": [{"name": "amount", "policy": "amount"}]}
BLANK_J2 = {"J2": {"address": "J2", "value": ""}}
NOT_REGISTERED = (400, {"error": {"code": "refused", "message": "workbook is not registered"}})


def _bridge(root: Path, sessions=("s1", "s2")):
    """A task whose sessions, recorded before anything is imported, call the Excel bridge; ``call(session, path,
    payload)`` answers (status, body)."""
    from foundry.excel_bridge import BridgeTokenAuthority, ExcelBridgeApp

    task = TaskStore(root / "var").create(title="Excel")
    for session in sessions:
        task.record_session(session, role="analysis")
    authority = BridgeTokenAuthority(b"local-test-secret-local-test-secret")
    app = ExcelBridgeApp(var_root=root / "var", token_authority=authority)

    def call(session, path, payload=None):
        headers = {"Authorization": f"Bearer {authority.issue(task_id=task.id, session_id=session, ttl_seconds=60)}"}
        status, _, body = app.handle("GET" if path == "/api/context" else "POST", path, headers,
                                     json.dumps(payload or {}).encode())
        return status, json.loads(body)

    return task, call


def _bridge_import(call, session, binding_id, amount, workbook="wb_shared"):
    """``session`` imports one revenue row of ``amount`` through input binding ``binding_id`` of ``workbook``."""
    binding = {"id": binding_id, "name": binding_id, "role": "input", "worksheet": "Model",
               "address": {"actual": "Model!A1:G2", "budget": "Model!L1:R2"}.get(binding_id, "Model!T1:Z2"),
               "headers": BRIDGE_FIELDS,
               "fields": [{"name": name, "policy": "amount" if name == "amount" else "text"} for name in BRIDGE_FIELDS]}
    status, out = call(session, "/api/import-binding", {
        "workbook_id": workbook, "binding": binding, "alias": binding_id,
        "values": [BRIDGE_FIELDS, ["revenue", amount, "HQ", "2026-08", "CNY", "yuan", binding_id]]})
    assert status == 200, out
    return out


def _bridge_preview(call, session, workbook="wb_shared") -> dict:
    """``session`` binds the output area of ``workbook`` and previews SECRET onto it."""
    status, out = call(session, "/api/register-bindings", {"workbook_id": workbook, "bindings": [BRIDGE_OUTPUT]})
    assert status == 200, out
    status, out = call(session, "/api/preview-output", {
        "workbook_id": workbook, "binding_id": "out", "current_cells": BLANK_J2,
        "writes": [{"address": "J2", "field": "amount", "value": SECRET}]})
    assert status == 200, out
    return out["preview"]


def _s1_works_in_the_shared_workbook(call):
    """s1 imports SECRET into wb_shared from its Mac, previews it onto an output area and logs the import."""
    call("s1", "/api/register-workbook", {"workbook_id": "wb_shared", "name": "m.xlsx",
                                          "url": "https://files.test/s1/m.xlsx", "host": {"platform": "Mac"}})
    first = _bridge_import(call, "s1", "actual", SECRET)
    preview = _bridge_preview(call, "s1")
    call("s1", "/api/telemetry", {"workbook_id": "wb_shared", "event": "input_imported",
                                  "details": {"dataset_id": first["dataset"]["id"]}})
    return first, preview


def _bridge_state(task) -> dict:
    return json.loads((task.root / "analysis" / "excel_bridge" / "state.json").read_text(encoding="utf8"))


def _records_of(task, workbook_id: str) -> list[dict]:
    """The bridge's records of ``workbook_id``, whichever session keeps them."""
    return [book for key, book in _bridge_state(task)["workbooks"].items() if key.rpartition("/")[2] == workbook_id]


def _rewrite_bridge_state(task, **fields) -> None:
    """Store ``fields`` in the bridge's state as an older bridge left them, under a valid integrity hash."""
    state = {key: value for key, value in _bridge_state(task).items() if key != "_integrity_hash"}
    state.update(fields)
    (task.root / "analysis" / "excel_bridge" / "state.json").write_text(
        json.dumps({**state, "_integrity_hash": _hash(state)}), encoding="utf8")


def test_a_session_opening_another_session_s_workbook_works_in_it_as_if_alone(tmp_path):
    """The workbook id lives in the workbook's document settings, so a second session opening the same file sends
    s1's id. s2 neither takes up s1's imports nor sees or uses s1's bindings, previews or events, and s1's record of
    the file stays as s1 left it."""
    answers = {}
    for name in ("alone", "shared"):
        task, call = _bridge(tmp_path / name)
        first, preview = _s1_works_in_the_shared_workbook(call) if name == "shared" else (None, None)
        registered = call("s2", "/api/register-workbook", {"workbook_id": "wb_shared", "name": "m.xlsx",
                                                           "host": {"platform": "Win"}})
        second = _bridge_import(call, "s2", "budget", "100")
        bound = call("s2", "/api/register-bindings", {"workbook_id": "wb_shared", "bindings": [BRIDGE_OUTPUT]})
        context = call("s2", "/api/context")
        assert _snapshots(task, "s2") == [second["dataset"]["id"]]
        assert second["finance_context"]["bindings"] == {"budget": second["dataset"]["id"]}
        ran = call("s2", "/api/run-metric", {"workbook_id": "wb_shared", "spec": {"metric": {
            "kind": "account_total", "dimensions": ["organization", "period"], "accounts": ["revenue"]}}})
        assert ran[0] == 200 and ran[1]["run"]["bindings"] == {"budget": second["dataset"]["id"]}
        answers[name] = [registered, {key: second[key] for key in ("finance_context", "workbook")}, bound, context]
        if name == "shared":
            assert _shows([answers[name], ran], [SECRET, first["dataset"]["id"], preview["id"]]) == []
            # s1's preview is refused to s2 as one that never existed, to apply and to acknowledge.
            for path, payload in (("/api/apply-output", {"current_cells": BLANK_J2}),
                                  ("/api/ack-output", {"cells": []})):
                refusals = [call("s2", path, {"workbook_id": "wb_shared", "preview_id": preview_id, **payload})
                            for preview_id in (preview["id"], "f" * 32)]
                assert refusals[0] == refusals[1] == (400, {"error": {"code": "refused",
                                                                      "message": "preview is unavailable"}})
            # s1's record keeps its own host, bindings and preview; its next import takes up nothing s2 imported.
            books = call("s1", "/api/context")[1]["workbooks"]
            assert [(book["host"], sorted(book["bindings"]), list(book["previews"])) for book in books] == [
                ({"platform": "Mac"}, ["actual", "out"], [preview["id"]])]
            third = _bridge_import(call, "s1", "plan", "5")
            assert third["finance_context"]["bindings"] == {"actual": first["dataset"]["id"],
                                                            "plan": third["dataset"]["id"]}
            assert _snapshots(task, "s1") == [first["dataset"]["id"], third["dataset"]["id"]]
    # Equal to the answers where s1 never worked in the file (seq counts every record of the task; an upload's
    # name carries a digest of its import time).
    same = [re.sub(r'"seq": \d+|\b[0-9a-f]{16}\b', "<n>", _normalized(answers[name])) for name in ("shared", "alone")]
    assert same[0] == same[1]


def test_a_child_session_sees_and_uses_none_of_its_parent_s_workbooks(tmp_path):
    """A child begins with what its parent could read then. The workbook its parent goes on to import into, preview
    from and log is the parent's record: the child neither sees it nor applies the parent's preview."""
    task, call = _bridge(tmp_path, sessions=("s1",))
    task.record_session("child", role="analysis", parent_session_id="s1")
    first, preview = _s1_works_in_the_shared_workbook(call)
    status, context = call("child", "/api/context")
    assert status == 200 and (context["snapshot_ids"], context["workbooks"], context["telemetry"]) == ([], [], [])
    assert _shows(context, [SECRET, first["dataset"]["id"], preview["id"]]) == []
    refusals = [call("child", "/api/apply-output", {"workbook_id": workbook, "preview_id": preview["id"],
                                                    "current_cells": BLANK_J2}) for workbook in ("wb_shared", "wb_new")]
    assert refusals[0] == refusals[1] == NOT_REGISTERED


def test_another_session_s_host_events_never_push_a_session_s_own_out(tmp_path, monkeypatch):
    """Each session reads and keeps its own latest host events. Events logged before they named their session stay
    in the file for the operator's tools and show to no session."""
    import foundry.excel_bridge

    monkeypatch.setattr(foundry.excel_bridge, "MAX_TELEMETRY", 3)
    task, call = _bridge(tmp_path)

    def logged(session, event):
        status, out = call(session, "/api/telemetry", {"workbook_id": "wb_shared", "event": event})
        assert status == 200, out
        return out["telemetry"]

    mine = logged("s1", "input_imported")
    old = {"id": "0" * 32, "at": "2026-08-01T00:00:00Z", "event": "ready", "workbook_id": "wb_shared", "host": {},
           "details": {}}
    _rewrite_bridge_state(task, telemetry=[old, *_bridge_state(task)["telemetry"]])
    for number in range(4):
        logged("s2", f"metric_run_{number}")
    assert call("s1", "/api/context")[1]["telemetry"] == [mine]
    assert [event["event"] for event in call("s2", "/api/context")[1]["telemetry"]] == [
        "metric_run_1", "metric_run_2", "metric_run_3"]
    assert [event["event"] for event in _bridge_state(task)["telemetry"]] == [
        "ready", "input_imported", "metric_run_1", "metric_run_2", "metric_run_3"]


def test_a_workbook_saved_before_per_session_records_goes_only_to_the_session_that_filed_its_imports(tmp_path):
    """A record stored under the bare workbook id names no owner. The session that filed an import there takes up
    that import with its input binding, while the output area, the preview and what the last session to open the
    file registered stay behind. A session that filed nothing there finds no such workbook, even one whose context
    holds the import."""
    task, call = _bridge(tmp_path, sessions=("excel", "other"))
    call("excel", "/api/register-workbook", {"workbook_id": "wb_shared", "name": "m.xlsx", "host": {}})
    first = _bridge_import(call, "excel", "actual", SECRET)
    _bridge_preview(call, "excel")
    task.record_session("late", role="analysis")  # a root session begins with every dataset of the task
    assert _snapshots(task, "late") == [first["dataset"]["id"]]
    [record] = _records_of(task, "wb_shared")
    # 'other' opened the file last, and the shared record took its name, address and host.
    record = {**record, "name": "other.xlsx", "url_hash": "a" * 64, "host": {"platform": "Win"}}
    _rewrite_bridge_state(task, workbooks={"wb_shared": record})

    status, context = call("excel", "/api/context")
    assert status == 200 and [book["id"] for book in context["workbooks"]] == ["wb_shared"]
    book = context["workbooks"][0]
    assert (sorted(book["bindings"]), book["input_snapshots"]["actual"]["dataset_id"]) == (["actual"],
                                                                                          first["dataset"]["id"])
    assert (book["preauthorized_areas"], book["previews"]) == ({}, {})
    assert (book["name"], book["url_hash"], book["host"]) == ("", "", {})
    budget = _bridge_import(call, "excel", "budget", "100")
    assert budget["finance_context"]["bindings"] == {"actual": first["dataset"]["id"],
                                                     "budget": budget["dataset"]["id"]}
    for session, amount, held in (("other", "200", []), ("late", "300", [first["dataset"]["id"]])):
        status, context = call(session, "/api/context")
        assert status == 200 and context["workbooks"] == []
        refusals = [call(session, "/api/preview-output", {"workbook_id": workbook, "binding_id": "out", "writes": [],
                                                          "current_cells": {}}) for workbook in ("wb_shared", "wb_new")]
        assert refusals[0] == refusals[1] == NOT_REGISTERED
        own = _bridge_import(call, session, "budget", amount)
        assert own["finance_context"]["bindings"] == {"budget": own["dataset"]["id"]}
        assert _snapshots(task, session) == [*held, own["dataset"]["id"]]
    assert _shows(call("other", "/api/context")[1], [SECRET, first["dataset"]["id"]]) == []
    # Each session's share is written under its own key; the bare record stays as it was stored.
    assert _bridge_state(task)["workbooks"]["wb_shared"] == record


def test_a_workbook_two_sessions_shared_before_per_session_records_splits_by_who_imported(tmp_path):
    """The pre-fix bug case itself: s1 and s2 both imported into one bare record, and s2's context took in s1's
    import. Each takes up only the imports it filed; neither binds or names the other's again."""
    task, call = _bridge(tmp_path)
    first = _bridge_import(call, "s1", "actual", SECRET)
    second = _bridge_import(call, "s2", "budget", "100")
    task.update_session_context("s2", snapshot_ids=[first["dataset"]["id"]])  # what the shared record did to s2
    records = _records_of(task, "wb_shared")
    _rewrite_bridge_state(task, workbooks={"wb_shared": {
        **records[0], **{key: {name: row for record in records for name, row in record[key].items()}
                         for key in ("bindings", "input_snapshots")}}})

    for session, own in (("s1", first), ("s2", second)):
        books = call(session, "/api/context")[1]["workbooks"]
        assert [(sorted(book["bindings"]), [row["dataset_id"] for row in book["input_snapshots"].values()])
                for book in books] == [([own["binding"]["id"]], [own["dataset"]["id"]])]
    s1 = _bridge_import(call, "s1", "plan", "5")
    assert s1["finance_context"]["bindings"] == {"actual": first["dataset"]["id"], "plan": s1["dataset"]["id"]}
    s2 = _bridge_import(call, "s2", "plan", "6")
    assert s2["finance_context"]["bindings"] == {"budget": second["dataset"]["id"], "plan": s2["dataset"]["id"]}
    assert _shows(call("s2", "/api/context")[1]["workbooks"], [first["dataset"]["id"]]) == []


def test_a_workbook_saved_before_per_session_records_with_no_import_is_no_session_s(tmp_path):
    """A bare record holding only an output area and its preview names no owner: no session takes it up, not the one
    that made it, another, or a child that may read nothing."""
    task, call = _bridge(tmp_path)
    task.record_session("child", role="analysis", parent_session_id="s1")
    call("s1", "/api/register-workbook", {"workbook_id": "wb_noimp", "name": "m.xlsx", "host": {}})
    preview = _bridge_preview(call, "s1", workbook="wb_noimp")
    [record] = _records_of(task, "wb_noimp")
    _rewrite_bridge_state(task, workbooks={"wb_noimp": record})
    for session in ("s1", "s2", "child"):
        status, context = call(session, "/api/context")
        assert status == 200 and context["workbooks"] == []
        assert call(session, "/api/preview-output", {
            "workbook_id": "wb_noimp", "binding_id": "out", "current_cells": BLANK_J2,
            "writes": [{"address": "J2", "field": "amount", "value": SECRET}]}) == NOT_REGISTERED
        assert call(session, "/api/apply-output", {"workbook_id": "wb_noimp", "preview_id": preview["id"],
                                                   "current_cells": BLANK_J2}) == NOT_REGISTERED


def test_a_session_takes_up_no_import_its_context_does_not_hold(tmp_path):
    """Filing an import there is not enough: a session takes up only what it may read. No call narrows a context;
    this stands in for a sessions file that holds one without the session's own import."""
    task, call = _bridge(tmp_path, sessions=("s1",))
    _bridge_import(call, "s1", "actual", SECRET)
    [record] = _records_of(task, "wb_shared")
    _rewrite_bridge_state(task, workbooks={"wb_shared": record})
    task._write_sessions([{**row, "snapshot_ids": []} for row in task.sessions()])
    status, context = call("s1", "/api/context")
    assert status == 200 and context["workbooks"] == []
    plan = _bridge_import(call, "s1", "plan", "5")
    assert plan["finance_context"]["bindings"] == {"plan": plan["dataset"]["id"]}
    assert _snapshots(task, "s1") == [plan["dataset"]["id"]]


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
    for parent_id in (hidden["id"], "e" * 32, "zz"):
        with pytest.raises(McpRefused) as error:
            server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "analysis_requirements_save",
                "arguments": {"context_id": context["id"], "question": "收入", "items": ITEMS, "parent_id": parent_id}}})
        refused.append(str(error.value))
    assert len(set(refused)) == 1


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


# --- requirements versions, runs and saved analyses named by id -----------------------------------------------------


@pytest.fixture
def named(tmp_path):
    """The manager saved a requirements version, a finance run and an analysis on files outside the session (H, LH).
    The current requirements version rests on A, so a session is refused for the id it names, not by #75's rule."""
    from foundry.finance_mcp import FinanceMcpServer, create_stdio_grant

    var = tmp_path / "var"
    task = TaskStore(var).create(title="按编号")
    analysis = AnalysisStore(task)
    a = analysis.add_dataset(_csv(tmp_path / "a.csv", [("revenue", "2026-08", "集团", "100", "CNY", "元")]), name="A")["id"]
    ledger = analysis.add_dataset(_entry(tmp_path / "l.json", "revenue", "100"), name="L")["id"]
    task.record_session("sess", role="analysis")
    h = analysis.add_dataset(_csv(tmp_path / "h.csv", [("revenue", "2026-08", "集团", SECRET, "CNY", "元")]), name="H")["id"]
    hidden_ledger = analysis.add_dataset(_entry(tmp_path / "lh.json", "revenue", SECRET), name="LH")["id"]
    manager = FinanceStore(task)
    context = manager.save_context({"bindings": {"ledger": ledger}, "scopes": {"ledger": SCOPE}})
    hidden_context = manager.save_context({"bindings": {"ledger": hidden_ledger}, "scopes": {"ledger": SCOPE}})
    requirements = manager.analysis_requirements_save({"question": "Falcon", "bindings": {"payroll": h}, "items": ITEMS})
    manager.analysis_requirements_save({"question": "收入", "bindings": {"gl": a}, "items": ITEMS,
                                        "parent_id": requirements["id"]})
    session = FinanceStore(task, snapshot_ids=_snapshots(task), session_id="sess")
    total = {"kind": "account_total", "accounts": ["revenue"]}

    def server(context_ids):
        grant = create_stdio_grant(var, task_id=task.id, session_id="sess", snapshot_ids=_snapshots(task),
                                   context_ids=context_ids)
        served = FinanceMcpServer(var_root=var, grant_id=grant["grant_id"], token=grant["token"])
        served.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        served.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return served

    return SimpleNamespace(
        var=var, task=task, analysis=analysis, a=a, manager=manager, session=session,
        run=session.run_metric({"context_id": context["id"], "metric": total})["id"], hidden_requirements=requirements["id"],
        hidden_run=manager.run_metric({"context_id": hidden_context["id"], "metric": total})["id"],
        hidden_analysis=analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": h}})["id"],
        # A grant on snapshots alone leaves every id to the service; a grant on a context checks a run's first.
        grants={"snapshot grant": server(None), "context grant": server([context["id"]])})


def _mcp(server, tool: str, spec: dict) -> str:
    """What a session reads of a refused tool call: the tool's error, or the grant's refusal."""
    from foundry.finance_mcp import McpRefused

    try:
        response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": tool, "arguments": spec}})
    except McpRefused as refused:
        return f"grant refused: {refused}"
    assert response["result"]["isError"], response
    return json.loads(response["result"]["content"][0]["text"])["message"]


def _refusal(call) -> str:
    with pytest.raises(FoundryError) as refused:
        call()
    return str(refused.value)


def _stored(world) -> dict[str, int]:
    """Every record a refused call could have written."""
    from foundry.analysis_jobs import JobStore

    return {**{kind: len(world.analysis._list(kind))
               for kind in ("revisions", "runs", "drafts", "requirements", "methods", "completions")},
            "jobs": len(JobStore(world.task).list())}


def test_a_session_names_a_hidden_unknown_or_malformed_requirements_version_alike(named, capsys):
    from foundry.analysis import REQUIREMENTS_UNAVAILABLE

    def cli(*args):
        code, error = _cli(capsys, named.var, *args)
        assert code == 3
        return error.strip()

    pinned = named.analysis.save_analysis({"question": "收入", "sql": SQL, "bindings": {"t": named.a},
                                           "requirements_id": named.hidden_requirements})
    stored = _stored(named)
    answers = {}
    # A version on a file outside the session, one never saved, one that is no id and one that is no text.
    for requirements_id in (named.hidden_requirements, "e" * 32, "zz", 5):
        script = json.dumps({"code": "print(1)", "bindings": {"t": named.a}, "requirements_id": requirements_id})
        explanation = {"body": "收入。", "run_ids": [named.run], "requirements_id": requirements_id}
        answers[requirements_id] = {
            "analysis-save": cli("analysis-save", "--spec", json.dumps(
                {"question": "收入", "sql": SQL, "bindings": {"t": named.a}, "requirements_id": requirements_id})),
            "analysis-script": cli("analysis-script", "--spec", script),
            "analysis-script-start": cli("analysis-script-start", "--spec", script),
            "analysis-draft": cli("analysis-draft", "--spec", json.dumps(
                {"title": "T", "body": "收入。", "requirements_id": requirements_id})),
            "validate-explanation": cli("validate-explanation", "--spec", json.dumps(explanation)),
            "save-explanation-draft": cli("save-explanation-draft", "--spec", json.dumps(explanation)),
            "completion save": _refusal(lambda: named.session.save_completion_draft("op", "call", explanation)),
            **{f"{tool} ({grant})": _mcp(server, tool, explanation) for grant, server in named.grants.items()
               for tool in ("validate_explanation", "save_explanation_draft")},
        }
    assert {answer for row in answers.values() for answer in row.values()} == {REQUIREMENTS_UNAVAILABLE}
    # A saved analysis pinned to a version the session may not read runs as one pinned to an unknown version would.
    assert cli("analysis-run", "--analysis", pinned["id"]) == REQUIREMENTS_UNAVAILABLE
    assert _stored(named) == stored
    # A save the manager made of the very same request is no retry the session may replay: refused as a fresh save.
    same = {"body": "收入。", "run_ids": [named.run], "requirements_id": named.hidden_requirements}
    named.manager.save_explanation_draft(dict(same))
    assert _refusal(lambda: named.session.save_explanation_draft(dict(same))) == REQUIREMENTS_UNAVAILABLE
    # The manager is answered as before.
    for requirements_id, message in (("e" * 32, f"analysis object is unavailable: {'e' * 32}.json"),
                                     ("zz", "invalid analysis object id: zz")):
        for args in (("analysis-save", "--spec", json.dumps({"question": "收入", "sql": SQL, "bindings": {"t": named.a},
                                                               "requirements_id": requirements_id})),
                     ("validate-explanation", "--spec", json.dumps({"body": "收入。", "requirements_id": requirements_id}))):
            code, error = _cli(capsys, named.var, *args, session=None, task=named.task.id)
            assert (code, error.strip()) == (3, message)


def test_a_session_names_a_hidden_unknown_or_malformed_run_alike(named, capsys):
    from foundry.analysis import RUN_UNAVAILABLE

    def cli(*args):
        code, error = _cli(capsys, named.var, *args)
        assert code == 3
        return error.strip()

    stored = _stored(named)
    answers = {}
    for run_id in (named.hidden_run, "e" * 32, "zz", 5):
        runs = {"body": "收入。", "run_ids": [run_id]}
        cited = {"body": "收入。", "claims": [{"basis": "source_fact", "run_id": run_id, "text": "收入"}]}
        calculated = {"body": "收入。", "claims": [{"basis": "calculation", "run_id": run_id, "row": 0, "column": "amount"}]}
        answers[run_id] = {
            "prepare-explanation": cli("prepare-explanation", "--spec", json.dumps({"run_ids": [run_id]})),
            "validate-explanation": cli("validate-explanation", "--spec", json.dumps(runs)),
            "save-explanation-draft": cli("save-explanation-draft", "--spec", json.dumps(runs)),
            "validate a claim": _refusal(lambda: named.session.validate_explanation(cited)),
            "save a claim": _refusal(lambda: named.session.save_explanation_draft(cited)),
            "save a calculation": _refusal(lambda: named.session.save_explanation_draft(calculated)),
            "completion run_ids": _refusal(lambda: named.session.save_completion_draft("op", "call", runs)),
            "completion claim": _refusal(lambda: named.session.save_completion_draft("op", "call", cited)),
            **{f"{tool} ({grant})": _mcp(server, tool, runs) for grant, server in named.grants.items()
               for tool in ("prepare_explanation", "validate_explanation", "save_explanation_draft")},
        }
        if isinstance(run_id, str):  # a recipe naming its run by anything but text is refused for its shape
            recipe = {"kind": "direct", "dataset_id": named.a, "source_hash": "0" * 64, "sheet": "S", "range": "A1",
                      "claim": {"run_id": run_id, "row": 0, "column": "amount"}}
            answers[run_id]["validate a recipe"] = _refusal(
                lambda: named.session.validate_explanation({"evidence_recipes": [recipe]}))
    # The service answers alike; a context grant refuses each run before the service reads it, alike too.
    refused = "grant refused: finance run is outside this grant"
    assert {entry: {row[entry] for row in answers.values() if entry in row} for entry in answers["e" * 32]} == {
        entry: {refused if "context grant" in entry else RUN_UNAVAILABLE} for entry in answers["e" * 32]}
    assert _stored(named) == stored
    # A save the manager made of the very same request is no retry the session may replay: refused as a fresh save.
    same = {"body": "收入。", "run_ids": [named.hidden_run]}
    named.manager.save_explanation_draft(dict(same))
    assert _refusal(lambda: named.session.save_explanation_draft(dict(same))) == RUN_UNAVAILABLE
    # A run the session may read is read as before.
    mine = {"body": "收入。", "run_ids": [named.run]}
    assert _cli(capsys, named.var, "validate-explanation", "--spec", json.dumps(mine))[0] == 0
    # The manager reads every run, and is answered as before for an unknown or malformed one.
    manager = {"session": None, "task": named.task.id}
    assert _cli(capsys, named.var, "validate-explanation", "--spec", json.dumps(same), **manager)[0] == 0
    for run_id, message in (("e" * 32, f"analysis object is unavailable: {'e' * 32}.json"),
                            ("zz", "invalid analysis object id: zz")):
        for command in ("prepare-explanation", "validate-explanation", "save-explanation-draft"):
            code, error = _cli(capsys, named.var, command, "--spec", json.dumps({"body": "收入。", "run_ids": [run_id]}),
                               **manager)
            assert (code, error.strip()) == (3, message)


def test_a_session_names_a_hidden_unknown_or_malformed_saved_analysis_alike(named, capsys):
    from foundry.analysis import ANALYSIS_UNAVAILABLE

    def revision(parent_id) -> str:
        return json.dumps({"question": "收入", "sql": SQL, "bindings": {"t": named.a}, "parent_id": parent_id})

    stored = _stored(named)
    answers = set()
    for analysis_id in (named.hidden_analysis, "e" * 32, "zz"):
        for args in (("analysis-run", "--analysis", analysis_id),
                     ("analysis-method-save", "--analysis", analysis_id, "--name", "收入"),
                     ("analysis-save", "--spec", revision(analysis_id))):
            code, error = _cli(capsys, named.var, *args)
            answers.add((code, str(error).strip()))
    code, error = _cli(capsys, named.var, "analysis-save", "--spec", revision(5))
    answers.add((code, str(error).strip()))
    # Neither run nor saved as a method, nor kept as a revision's parent.
    assert answers == {(3, ANALYSIS_UNAVAILABLE)}
    assert _stored(named) == stored
    # A parent the session may read is kept as before.
    code, mine = _cli(capsys, named.var, "analysis-save", "--spec", json.dumps(
        {"question": "收入", "sql": SQL, "bindings": {"t": named.a}}))
    code, revised = _cli(capsys, named.var, "analysis-save", "--spec", revision(mine["id"]))
    assert code == 0 and revised["parent_id"] == mine["id"]
    # The manager runs and revises any analysis, and is answered as before for an unknown or malformed one.
    manager = {"session": None, "task": named.task.id}
    assert _cli(capsys, named.var, "analysis-run", "--analysis", named.hidden_analysis, **manager)[0] == 0
    code, managed = _cli(capsys, named.var, "analysis-save", "--spec", revision(named.hidden_analysis), **manager)
    assert code == 0 and managed["parent_id"] == named.hidden_analysis
    for analysis_id, message in (("e" * 32, f"analysis object is unavailable: {'e' * 32}.json"),
                                 ("zz", "invalid analysis object id: zz")):
        for args in (("analysis-run", "--analysis", analysis_id), ("analysis-save", "--spec", revision(analysis_id))):
            code, error = _cli(capsys, named.var, *args, **manager)
            assert (code, error.strip()) == (3, message)


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
