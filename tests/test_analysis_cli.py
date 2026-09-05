import json
from pathlib import Path

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.task import TaskStore


def test_cli_operator_flow_and_unknown_session_no_writes(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="分析")
    data = tmp_path / "data.csv"
    data.write_text("region,revenue\nNorth,70\nSouth,30\n")
    args = ["--var", str(root), "--task", task.id]
    assert main([*args, "dataset-add", "--path", str(data), "--name", "实际"]) == 0
    dataset = json.loads(capsys.readouterr().out)
    spec = {
        "question": "North占比",
        "sql": "SELECT SUM(CASE WHEN region='North' THEN revenue ELSE 0 END)/SUM(revenue)*100 AS share FROM actual",
        "bindings": {"actual": dataset["id"]},
    }
    assert main([*args, "analysis-save", "--spec", json.dumps(spec)]) == 0
    analysis = json.loads(capsys.readouterr().out)
    assert main([*args, "analysis-run", "--analysis", analysis["id"]]) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["result"]["rows"][0]["share"] == "70.0"
    before = list(root.rglob("*"))
    assert main([*args, "--session", "unknown", "analysis-state"]) == 3
    assert list(root.rglob("*")) == before


def test_session_upload_binding_refresh_and_state_resource_scope(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="分析")
    store = AnalysisStore(task)
    task.record_session("parent", role="analysis")
    args = ["--var", str(root), "--session", "parent"]
    outside = tmp_path / "outside.csv"
    outside.write_text("value\n12\n")
    assert (
        main([*args, "dataset-add", "--path", str(outside), "--name", "outside"]) == 3
    )
    capsys.readouterr()
    upload = task.root / "analysis" / ".dsh-uploads" / "parent" / "inside.csv"
    upload.parent.mkdir(parents=True)
    upload.write_text("value\n30\n")
    assert main([*args, "dataset-add", "--path", str(upload), "--name", "inside"]) == 0
    dataset = json.loads(capsys.readouterr().out)
    task.record_session("child", role="analysis", parent_session_id="parent")
    later = store.add_dataset(outside, name="later")
    assert main([*args, "analysis-state"]) == 0
    state = json.loads(capsys.readouterr().out)
    assert [d["id"] for d in state["datasets"]] == [dataset["id"]]
    assert main([*args, "dataset-read", "--dataset", later["id"]]) == 3
    capsys.readouterr()
    assert main(["--var", str(root), "--session", "child", "analysis-refresh"]) == 0
    refreshed = json.loads(capsys.readouterr().out)
    assert later["id"] not in refreshed["snapshot_ids"]
    assert main([*args, "analysis-refresh"]) == 0
    refreshed = json.loads(capsys.readouterr().out)
    assert later["id"] in refreshed["snapshot_ids"]


def test_cli_decimal_timeout_and_script(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="分析")
    store = AnalysisStore(task)
    source = tmp_path / "data.json"
    source.write_text('[{"amount":30}]')
    data = store.add_dataset(source, name="actual")
    args = ["--var", str(root), "--task", task.id]
    spec = {
        "question": "金额",
        "sql": "SELECT SUM(amount) FROM actual",
        "bindings": {"actual": data["id"]},
        "timeout_seconds": 0.1,
    }
    assert main([*args, "analysis-save", "--spec", json.dumps(spec)]) == 0
    revision = json.loads(capsys.readouterr().out)
    assert main([*args, "analysis-run", "--analysis", revision["id"]]) == 0
    assert json.loads(capsys.readouterr().out)["execution_status"] == "succeeded"


def test_child_dataset_add_refusal_does_not_create_canonical_snapshot(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="分析")
    service = AnalysisStore(task)
    task.record_session("parent", role="analysis")
    task.record_session("child", role="analysis", parent_session_id="parent")
    path = task.root / "analysis" / "uploads" / "new.csv"
    path.parent.mkdir(parents=True)
    path.write_text("amount\n30\n")
    before = service.state()["datasets"]
    assert (
        main(
            [
                "--var",
                str(root),
                "--session",
                "child",
                "dataset-add",
                "--path",
                str(path),
                "--name",
                "new",
            ]
        )
        == 3
    )
    assert service.state()["datasets"] == before
    capsys.readouterr()
    dataset = service.add_dataset(path, name="parent-added")
    task.update_session_context("parent", snapshot_ids=[dataset["id"]])
    assert main(["--var", str(root), "--session", "child", "analysis-refresh"]) == 0
    assert json.loads(capsys.readouterr().out)["snapshot_ids"] == []


def test_output_cli_only_resolves_actual_manifest_names(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="脚本")
    service = AnalysisStore(task)
    run = service.run_script(
        {
            "code": "from pathlib import Path\nPath('report.txt').write_text('saved')",
            "bindings": {},
        }
    )
    if run.get("runner_status") == "unavailable":
        import pytest

        pytest.skip("OS-isolated runner unavailable")
    args = [
        "--var",
        str(root),
        "--task",
        task.id,
        "analysis-output",
        "--run",
        run["id"],
    ]
    assert main([*args, "--output", "report.txt"]) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert Path(resolved["path"]).read_text() == "saved"
    assert main([*args, "--output", "../../task.json"]) == 3
