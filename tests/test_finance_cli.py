import json
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.workbook.defined_name import DefinedName

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.task import TaskStore


def test_source_refresh_cli_dedupes_and_preserves_old_run(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="月度刷新")
    task.record_session("manager", role="analysis")
    args = ["--var", str(root), "--session", "manager"]
    path = task.root / "analysis" / "uploads" / "actual.csv"
    path.parent.mkdir(parents=True)
    path.write_text("management_account,amount\nrevenue,120\ncost,70\nexpense,20\n")
    spec = {"path": str(path), "scope": {
        "source_id": "monthly-file", "tenant_id": "T1", "ledger_id": "L1",
        "organization_id": "O1", "period": "2026-09", "currency": "CNY", "cutoff_at": "2026-09-06",
    }}

    def call(command, spec=None):
        assert main([*args, command, *(["--spec", json.dumps(spec)] if spec is not None else [])]) == 0
        return json.loads(capsys.readouterr().out)

    batch = call("finance-source-refresh", spec)
    context = call("finance-context-save", {"bindings": {"actual": batch["dataset_id"]}, "scopes": {
        "actual": {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "元", "scenario": "actual"},
    }})
    run = call("run-metric", {"context_id": context["id"]})
    assert run["result"]["rows"][0]["profit"] == "30"
    repeat = call("finance-source-refresh", spec)
    assert repeat["effective_dataset_id"] == batch["dataset_id"]
    assert repeat["duplicate_of"] == batch["id"]
    path.write_text("management_account,amount\nrevenue,130\ncost,70\nexpense,20\n")
    newer = call("finance-source-refresh", {**spec, "scope": {**spec["scope"], "cutoff_at": "2026-09-07"}})
    assert newer["dataset_id"] != batch["dataset_id"]
    assert len(call("finance-source-list")["batches"]) == 3
    old_again = AnalysisStore(task).run_analysis(run["analysis_id"])
    assert old_again["output_hash"] == run["output_hash"]
    assert len(task.sessions()[0]["snapshot_ids"]) == 2


def test_source_refresh_cannot_escape_uploads_or_child_ceiling(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="隔离")
    task.record_session("manager", role="analysis")
    task.record_session("child", role="analysis", parent_session_id="manager")
    path = tmp_path / "outside.csv"
    path.write_text("amount\n1\n")
    spec = {"path": str(path), "scope": {
        "source_id": "file", "tenant_id": "T1", "ledger_id": "L1", "organization_id": "O1",
        "period": "2026-09", "currency": "CNY", "cutoff_at": "2026-09-06",
    }}
    for session in ("manager", "child", "unknown"):
        assert main(["--var", str(root), "--session", session, "finance-source-refresh", "--spec", json.dumps(spec)]) == 3
        capsys.readouterr()
    assert AnalysisStore(task).state()["datasets"] == []


def test_workbook_cli_writes_numeric_new_artifact_with_real_run(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="Excel")
    source = tmp_path / "source.xlsx"
    book = Workbook()
    book.active.title = "Input"
    book.active.append(["amount"])
    book.active.append([120.35])
    output = book.create_sheet("Output")
    output["A1"] = "金额"
    output["A2"] = 0
    book.defined_names.add(DefinedName("Result", attr_text="'Output'!$A$2"))
    book.save(source)
    store = AnalysisStore(task)
    dataset = store.add_dataset(source, name="原工作簿")
    run = store.run_analysis(store.save_analysis({"question": "合计", "bindings": {"input": dataset["id"]}, "sql": "SELECT SUM(amount) AS amount FROM input"})["id"])
    args = ["--var", str(root), "--task", task.id]

    def call(command, spec):
        assert main([*args, command, "--spec", json.dumps(spec)]) == 0
        return json.loads(capsys.readouterr().out)

    assert "Result" in call("workbook-inspect", {"dataset_id": dataset["id"]})["named_ranges"]
    binding = call("workbook-bind", {"dataset_id": dataset["id"], "source": {"kind": "named_range", "name": "Result"},
        "role": "output", "writable": True, "header": False, "fields": [{"name": "amount", "policy": "amount"}]})
    patch = call("workbook-preview", {"binding_id": binding["id"], "run_id": run["id"],
        "writes": [{"cell": "A2", "field": "amount", "value": "120.35", "result_row": 0, "result_column": "amount"}]})
    result = call("workbook-apply", {"patch_id": patch["id"]})
    assert Path(result["path"]).is_file()
    result_book = load_workbook(result["path"], data_only=True)
    original = load_workbook(source)
    assert result_book["Output"]["A2"].data_type == "n"
    assert result_book["Output"]["A2"].value == 120.35
    assert original["Output"]["A2"].value == 0
    result_book.close()
    original.close()
