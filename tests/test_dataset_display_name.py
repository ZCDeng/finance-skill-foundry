"""A title edit cannot replace a source or widen a session's snapshot ceiling."""

import json

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.task import TaskStore


def test_display_title_cli_keeps_source_run_and_history(tmp_path, capsys):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="title metadata")
    store = AnalysisStore(task)
    source = tmp_path / "notes.json"
    source.write_text('[{"amount":"70"}]')
    dataset = store.add_dataset(source, name="notes")
    run = store.run_analysis(store.save_analysis({
        "question": "amount", "sql": "SELECT amount FROM notes",
        "bindings": {"notes": dataset["id"]},
    })["id"])
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    args = ["--var", str(var), "--task", task.id]
    for name in ["meeting-notes", "meeting-notes-final"]:
        assert main([*args, "dataset-display-rename", "--dataset", dataset["id"], "--name", name]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["display_name"] == name
        for key in ("name", "source_name", "source_hash", "data_hash", "id"):
            assert result[key] == dataset[key]
    assert all(p.read_bytes() == data for p, data in before.items() if p.name != "sequence.json")
    records = store._list("dataset_display_names")
    assert len(records) == 2 and records[1]["parent_id"] == records[0]["id"]
    state = store.state()
    assert not state["superseded_datasets"]
    assert state["datasets"][0]["display_name"] == "meeting-notes-final"
    assert state["runs"][0]["input_hashes"] == run["input_hashes"]


def test_display_title_cannot_escape_session_or_accept_empty_name(tmp_path, capsys):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="scope")
    store = AnalysisStore(task)
    source = tmp_path / "notes.txt"
    source.write_text("meeting")
    visible = store.add_dataset(source, name="notes")
    task.record_session("reader", role="analysis")
    source.write_text("secret")
    hidden = store.add_dataset(source, name="hidden")
    args = ["--var", str(var), "--session", "reader", "dataset-display-rename"]
    for dataset, name in [(hidden, "attempt"), (visible, " "), (visible, "x" * 201)]:
        assert main([*args, "--dataset", dataset["id"], "--name", name]) == 3
        capsys.readouterr()
    assert store._list("dataset_display_names") == []
    assert main([*args, "--dataset", visible["id"], "--name", "meeting-notes"]) == 0
    assert json.loads(capsys.readouterr().out)["display_name"] == "meeting-notes"
