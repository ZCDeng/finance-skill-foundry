"""Supplementary M05 diagnostics never change the frozen original mutation gate."""
from pathlib import Path

import pytest

from tools import verify_finance_m05_adapter as adapter

ROOT = Path(__file__).resolve().parents[1]
original = adapter.load_original()


def test_m05_saved_effectiveness_never_promotes_auto_repair_to_detection():
    residual = "a" * 64
    request = {"body": "other components", "claims": [], "fact_ids": []}
    repaired = {"body": "residual: 0 元", "claims": [{"column": "residual", "fact_id": residual}],
                "fact_ids": [residual], "evidence_appendix_meta": {"render_version": 3}}
    diagnostic = adapter.m05_saved_effectiveness({"request": request, "current_draft": repaired}, [residual])
    assert diagnostic["status"] == "not_effective"
    assert diagnostic["full_flow_coverage"] == "adapter_gap"
    assert diagnostic["detection_credit"] is False
    assert original.classify({"accepted": True}, {"accepted": True}, "M05") == "escaped"
    missing = adapter.m05_saved_effectiveness({"request": request, "current_draft": {"body": "other components"}}, [residual])
    assert missing["status"] == "effective"
    assert missing["detection_credit"] is False
    text_only = adapter.m05_saved_effectiveness({"request": request, "current_draft": {"body": "residual: 0 元"}}, [residual])
    assert text_only["status"] == "not_effective"
    assert text_only["saved_residual_text_marker"] is True
    assert adapter.m05_saved_effectiveness({"request": request}, [residual])["status"] == "not_effective"
    assert adapter.m05_saved_effectiveness({"request": request, "current_draft": {"body": "other"}}, [])["status"] == "not_effective"
    assert original.classify({"accepted": True}, {
        "current_draft": {"quality": {"status": "needs_attention"}},
        "current_completion": None,
        "rejection_reasons": [{"code": "missing_required_fact"}],
    }, "M05") == "unresolved"


def test_m05_public_saved_omission_completion_does_not_substitute_for_original_case(tmp_path):
    cli = original.CLI(ROOT / ".venv/bin/foundry", tmp_path / "M05-boundaries")
    cli.start("M05 supplementary public authoring boundary")
    control, automatic, setup = adapter.observe_vmp_case(cli)
    assert control["accepted"] is True
    assert automatic["accepted"] is False
    assert automatic["current_completion"]["status"] != "complete"
    assert [issue["code"] for issue in automatic["validation"]["value"]["issues"]] == ["missing_required_fact"]
    # The appendix remains visible; its presence no longer fills an author's
    # omitted check. Supplementary saved-text coverage still grants no credit.
    assert setup["mutation_effectiveness"]["status"] == "not_effective"
    assert setup["mutation_effectiveness"]["full_flow_coverage"] == "adapter_gap"
    assert setup["mutation_effectiveness"]["detection_credit"] is False
    assert original.classify(control, automatic, "M05") == "detected"

    probe = adapter.probe_m05_authoring_boundary(
        cli, automatic, setup["mutation_effectiveness"]["expected_residual_fact_ids"])
    assert probe["mutation_effectiveness"]["status"] == "effective"
    assert probe["current_draft"]["quality"]["status"] == "needs_attention"
    assert [issue["code"] for issue in probe["validation"]["value"]["issues"]] == ["missing_required_fact"]
    assert len(probe["draft_receipts"]) == 1
    assert probe["draft_receipts"][0]["status"] != "complete"
    assert probe["refresh"]["returncode"] == 0
    assert probe["control"]["accepted"] is True
    assert probe["mutant"]["accepted"] is False
    assert probe["authoring_completion_flow_verified"] is True
    assert probe["replay_same_receipt"] is True
    assert probe["status"] == "detected"
    assert probe["original_case_credit"] is False
    for record in probe["exports"].values():
        assert record["returncode"] == 0
        assert record["value"]["publication_status"] == "draft"
        artifact = Path(record["value"]["path"])
        assert artifact.is_file()
        assert original.file_hash(artifact) == record["value"]["sha256"]


def test_original_driver_identity_remains_pinned_and_wrong_bytes_are_refused(tmp_path, monkeypatch):
    assert adapter.file_hash(adapter.ORIGINAL) == adapter.ORIGINAL_SHA256
    original_before = adapter.ORIGINAL.read_bytes()
    invalid = tmp_path / "wrong-driver.py"
    invalid.write_text("raise AssertionError(\"must never execute\")\n")
    monkeypatch.setattr(adapter, "ORIGINAL", invalid)
    with pytest.raises(ValueError, match="frozen original mutation driver identity mismatch"):
        adapter.load_original()
    assert (ROOT / "tools/verify_finance_mutation_pipeline.py").read_bytes() == original_before


def test_new_observer_output_never_overwrites_existing_records(tmp_path):
    target = tmp_path / "result.json"
    adapter.write_new(target, {"preserved": True})
    with pytest.raises(FileExistsError):
        adapter.write_new(target, {"replacement": True})
    assert "preserved" in target.read_text()
