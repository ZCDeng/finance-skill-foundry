"""Authorization and projection mode checks at the actual CLI boundary."""
import json

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.task import TaskStore


def test_projection_and_export_do_not_escape_session_sources(tmp_path, capsys):
    root = tmp_path / "var"
    task = TaskStore(root).create(title="scope")
    task.record_session("limited", role="analysis")
    store = AnalysisStore(task)
    source = tmp_path / "data.csv"
    source.write_text("amount\n30\n")
    dataset = store.add_dataset(source, name="source")
    analysis = store.save_analysis({"question": "total", "sql": "select sum(amount) as total from actual", "bindings": {"actual": dataset["id"]}})
    run = store.run_analysis(analysis["id"])
    draft = store.save_draft({"title": "report", "body": "Working draft", "run_ids": [run["id"]], "claims": [], "limitations": ["pending"]})
    args = ["--var", str(root), "--session", "limited"]
    for command in ("report-projection-read", "report-draft-read", "analysis-export"):
        assert main([*args, command, "--draft", draft["id"]]) == 3
        capsys.readouterr()
    operator = ["--var", str(root), "--task", task.id]
    assert main([*operator, "report-projection-read", "--draft", draft["id"], "--mode", "management"]) == 0
    projected = json.loads(capsys.readouterr().out)
    assert projected["content_mode"] == "management"
    assert projected["draft_id"] == draft["id"]
    assert projected["marker"] == "分析草稿·待复核"


def test_bounded_preview_cli_uses_archived_workbook(tmp_path, capsys):
    from openpyxl import Workbook
    root = tmp_path / "var"
    task = TaskStore(root).create(title="preview")
    source = tmp_path / "data.xlsx"
    book = Workbook()
    book.active.title = "预算"
    book.active["B2"] = 3185
    book.save(source)
    dataset = AnalysisStore(task).add_dataset(source, name="budget", metadata={"mode": "workbook"})
    args = ["--var", str(root), "--task", task.id, "workbook-range-preview", "--spec"]
    assert main([*args, json.dumps({"dataset_id": dataset["id"], "sheet": "预算", "range": "B2:B2"})]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["cells"][0]["exact"] == "3185"
    assert main([*args, json.dumps({"dataset_id": dataset["id"], "sheet": "预算", "range": "B:B"})]) == 3


def test_recipe_and_consistency_sources_cannot_widen_session_scope(tmp_path, capsys):
    from openpyxl import Workbook
    root = tmp_path / "var"
    task = TaskStore(root).create(title="evidence scope")
    store = AnalysisStore(task)
    csv = tmp_path / "allowed.csv"
    csv.write_text("amount\n30\n")
    allowed = store.add_dataset(csv, name="allowed")
    task.record_session("limited", role="analysis")
    task.update_session_context("limited", snapshot_ids=[allowed["id"]])
    definition = store.save_analysis({"question": "total", "sql": "select amount as actual from actual", "bindings": {"actual": allowed["id"]}})
    run = store.run_analysis(definition["id"])
    book = Workbook()
    book.active.title = "later"
    book.active["A1"] = 30
    xlsx = tmp_path / "later.xlsx"
    book.save(xlsx)
    later = store.add_dataset(xlsx, name="later", metadata={"mode": "workbook"})
    source = {"dataset_id": later["id"], "source_hash": later["source_hash"], "sheet": "later", "range": "A1"}
    recipe = {"id": "check", "kind": "direct", **source, "claim": {"run_id": run["id"], "row": 0, "column": "actual"}}
    spec = {"title": "evidence", "body": "pending", "run_ids": [run["id"]], "claims": [], "evidence_recipes": [recipe]}
    args = ["--var", str(root), "--session", "limited"]
    assert main([*args, "analysis-draft", "--spec", json.dumps({"title": "self-review", "body": "pending", "review_status": "accepted"})]) == 3
    assert "professional review" in capsys.readouterr().err
    assert main([*args, "analysis-draft", "--spec", json.dumps(spec)]) == 3
    assert "outside this session" in capsys.readouterr().err
    # A source in the second operand cannot bypass the same boundary.
    spec["evidence_recipes"] = [{**recipe, "kind": "ratio", "left": source, "right": source}]
    assert main([*args, "analysis-draft", "--spec", json.dumps(spec)]) == 3
    capsys.readouterr()
    spec["evidence_recipes"] = []
    spec["consistency_sources"] = [{"id": "late", "kind": "number", **source}]
    assert main([*args, "analysis-draft", "--spec", json.dumps(spec)]) == 3
    capsys.readouterr()
    # Manager-authored evidence remains invisible to an older session.
    spec["consistency_sources"] = []
    spec["evidence_recipes"] = [recipe]
    draft = store.save_draft(spec)
    assert main([*args, "report-projection-read", "--draft", draft["id"]]) == 3
    capsys.readouterr()
    assert main([*args, "analysis-state"]) == 0
    assert draft["id"] not in {row["id"] for row in json.loads(capsys.readouterr().out)["drafts"]}
