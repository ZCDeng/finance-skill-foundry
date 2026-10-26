"""Observer integrity and real CLI probes; no model or scorer-labelled fixtures."""

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_finance_mutation_pipeline", ROOT / "tools/verify_finance_mutation_pipeline.py"
)
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


@pytest.mark.parametrize(
    "control,mutant,case,expected",
    [
        ({"accepted": True}, {"accepted": True}, "M05", "escaped"),
        ({"accepted": False}, {"accepted": False, "rejection_reasons": ["blocked"]}, "M05", "control_not_accepted"),
        ({"accepted": True}, {"accepted": False, "rejection_reasons": []}, "M05", "unresolved"),
        ({"accepted": True}, {"accepted": False, "rejection_reasons": [{"code": "missing_required_fact"}]}, "M05", "detected"),
        ({"accepted": True}, {"accepted": False, "rejection_reasons": [{"stage": "save", "message": "Traceback: process crashed"}]}, "M03", "unresolved"),
        ({"accepted": True}, {"accepted": False, "rejection_reasons": [{"code": "requirement_unanswered"}]}, "M10", "unresolved"),
        ({"accepted": True}, {"accepted": False, "historical_draft_id": "old", "current_draft": {"quality": {"status": "pass"}}, "current_completion": {"status": "complete"}, "rejection_reasons": [{"code": "fact_metric_semantics_mismatch"}]}, "M10", "escaped_current_receipt"),
        ({"accepted": True}, {"accepted": False, "current_draft": {"quality": {"status": "needs_attention"}}, "current_completion": {"status": "complete"}, "rejection_reasons": [{"code": "fact_metric_semantics_mismatch"}]}, "M10", "escaped_current_receipt"),
        ({"accepted": True}, {"accepted": False, "current_draft": {"quality": {"status": "needs_attention"}}, "current_completion": {"status": "blocked"}, "rejection_reasons": [{"code": "fact_metric_semantics_mismatch"}]}, "M10", "detected"),
        ({"accepted": True}, {"accepted": False, "save": {"returncode": 0, "value": {"id": "fresh"}}, "current_draft": None, "current_completion": None, "rejection_reasons": [{"code": "fact_metric_semantics_mismatch"}]}, "M10", "unresolved"),
    ],
)
def test_no_all_reject_or_label_only_success(control, mutant, case, expected):
    assert pipeline.classify(control, mutant, case) == expected


def test_candidate_manifest_binds_actual_launcher_and_detects_changed_runtime(tmp_path):
    runtime = tmp_path / "foundry"
    runtime.mkdir()
    source = runtime / "cli.py"
    source.write_text("def main(): return 0\n")
    launcher = tmp_path / "foundry-cli"
    launcher.write_text(f"#!/usr/bin/python3\nimport sys\nsys.path.insert(0, {str(tmp_path)!r})\n")
    manifest = tmp_path / "candidate-source.json"
    pipeline.write_json(manifest, {"files": {"foundry/cli.py": pipeline.file_hash(source)}})
    identity = pipeline.candidate_identity(launcher, manifest)
    assert identity["manifest_verified"] is True
    assert identity["package_root"] == str(tmp_path)
    source.write_text("def main(): return 1\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        pipeline.candidate_identity(launcher, manifest)


def test_candidate_manifest_rejects_omitted_runtime_resource(tmp_path):
    runtime = tmp_path / "foundry"
    runtime.mkdir()
    source = runtime / "cli.py"
    source.write_text("def main(): return 0\n")
    (runtime / "rules.json").write_text("{}")
    launcher = tmp_path / "foundry-cli"
    launcher.write_text(f"#!/usr/bin/python3\nimport sys\nsys.path.insert(0, {str(tmp_path)!r})\n")
    manifest = tmp_path / "candidate-source.json"
    pipeline.write_json(manifest, {"files": {"foundry/cli.py": pipeline.file_hash(source)}})
    with pytest.raises(ValueError, match="runtime file omitted"):
        pipeline.candidate_identity(launcher, manifest)


def test_existing_evidence_is_never_overwritten(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "report.json"
    sentinel.write_text("preserved")
    with pytest.raises(FileExistsError):
        pipeline.run_suite(ROOT / ".venv/bin/foundry", output, ["M02"])
    assert sentinel.read_text() == "preserved"


@pytest.mark.parametrize("case", ["M02", "M05", "M06"])
def test_real_cli_preserves_control_and_rejects_mutation(tmp_path, case):
    result = pipeline.execute_case(ROOT / ".venv/bin/foundry", tmp_path / case, case)
    assert result["status"] == "detected", result["control"].get("rejection_reasons")
    assert result["control"]["current_completion"]["status"] == "complete"
    assert result["mutant"]["rejection_reasons"]
    assert result["provider_calls"] == 0
    calls = [json.loads(path.read_text()) for path in (tmp_path / case / "calls").glob("*.json")]
    commands = {call["command"] for call in calls}
    assert {"dataset-add", "save-explanation-draft", "validate-explanation", "analysis-state"} <= commands
    assert all(call["argv"][0] == str((ROOT / ".venv/bin/foundry").resolve()) for call in calls)
    assert result["control"]["request_sha256"] != result["mutant"]["request_sha256"]
