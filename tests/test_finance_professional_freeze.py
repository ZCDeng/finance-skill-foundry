"""Test the frozen contract, not a product output or a model answer."""
import copy
import json
from pathlib import Path

import pytest

from tools.freeze_finance_professional import (
    DEST, HIGH_RISK, ROOT, arithmetic, build, build_runtime_augmentation, catalog, digest,
    public_payload, validate_public, validate_slots, verify,
)


def test_frozen_bytes_math_and_every_family():
    result = verify()
    assert result["families"] == 32
    assert result["variants"] == 102
    assert result["numeric_assertions"] == 95
    assert result["selected_live_variants"] == 75
    assert result["professional_slots"] == 225
    assert result["planned_slots"] == 283


def test_all_reviewed_alternatives_are_separate():
    names = {row["family_id"] + "--" + row["variant_id"] for row in catalog()}
    assert {
        "E03--higher", "E03--equal", "E03--zero_denominator",
        "E08--reverse_then_book", "E08--settle_accrual",
        "E14--functional_balance", "E15--july_start", "E15--august_start",
        "E19--old_ar_collected", "E19--new_cash_sale",
        "E22--restricted_cash", "E22--break_even_screen", "E22--intraday_shortfall",
        "E27--forged_confirmation", "E27--cross_task_confirmation",
        "E27--revoked_confirmation", "E27--expanded_partial_confirmation",
        "E28--overwrite_with_baseline", "E28--overwrite_without_baseline",
        "E29--intentional_subtotal", "E31--unrelated_rename",
        "E32--late_read", "E32--missing_input", "E32--complete_input",
    } <= names
    assert {f"E24--year_{year}_early_{early}" for year in (2026, 2027) for early in ("true", "false", "unknown")} <= names


@pytest.mark.parametrize("field", ["expected", "private_oracle", "rubric", "hidden_labels"])
def test_public_payload_rejects_scoring_fields(field):
    value = public_payload(catalog()[0])
    value[field] = "answer leak"
    with pytest.raises(ValueError, match="public schema"):
        validate_public(value)


def test_public_payload_rejects_nested_answers():
    value = public_payload(catalog()[0])
    value["data"].append({"name": "expected_total", "value": "228"})
    with pytest.raises(ValueError, match="scoring data"):
        validate_public(value)
    value = public_payload(catalog()[0])
    value["data"][0]["value"] = {"expected": "228"}
    with pytest.raises(ValueError, match="string name/value"):
        validate_public(value)


def test_private_oracles_are_not_embedded_in_public_artifacts():
    files, manifest = build()
    for filename, raw in files.items():
        if filename.startswith("public/"):
            payload = json.loads(raw)
            validate_public(payload)
            assert "numeric_checks" not in payload
            assert "required_behaviors" not in payload
    assert manifest["isolation"]["verified"] is False
    assert manifest["execution_state"] == "none_started"
    assert manifest["unseen_suite"]["planned_slots"] == []
    assert manifest["unseen_suite"]["status"] == "not_created"


def test_old_fixtures_and_dual_model_identity_are_immutable():
    manifest = json.loads((DEST / "release_manifest.json").read_text())
    assert [suite["case_count"] for suite in manifest["legacy_suites"]] == [30, 8, 20]
    for suite in manifest["legacy_suites"]:
        assert digest((ROOT / suite["path"]).read_bytes()) == suite["sha256"]
        assert suite["fixture_model_contract"]["model"] == "deepseek-v4-flash"
        assert suite["fixture_model_contract"]["reasoning_effort"] == "max"
        assert suite["actual_model_contract"]["model"] == "deepseek-v4-pro"
        assert suite["actual_model_contract"]["reasoning_effort"] == "high"
        assert suite["model_contract_match"] is False


def test_exact_slots_do_not_collapse_repeat_indices():
    _, manifest = build()
    slots = manifest["planned_slots"]
    validate_slots(slots, list(reversed(slots)))
    for bad in (slots[:-1], slots + [slots[0]]):
        with pytest.raises(ValueError, match="slot sets"):
            validate_slots(slots, bad)
    bad = copy.deepcopy(slots)
    bad[0]["fixture_sha256"] = "bad-hash"
    with pytest.raises(ValueError, match="fixture hash"):
        validate_slots(slots, bad)


def test_freeze_detects_mutation_and_does_not_regenerate_over_it(tmp_path):
    files, _ = build()
    for name, raw in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    verify(tmp_path)
    altered = tmp_path / "public/E01--base.json"
    altered.write_bytes(altered.read_bytes().replace(b'"100"', b'"999"', 1))
    with pytest.raises(ValueError, match="frozen file changed"):
        verify(tmp_path)


def test_live_selection_all_families_all_high_risk_repeats_and_controls():
    variants = json.loads((DEST / "variant_manifest.json").read_text())["variants"]
    selected = [v for v in variants if v["selected_live"]]
    assert {v["family_id"] for v in selected} == {f"E{i:02}" for i in range(1,33)}
    assert {v["family_id"] for v in selected if v["high_risk"]} == HIGH_RISK
    assert all(v["repeats"] == 3 and v["capability_status"] == "not_granted" for v in selected)
    assert all(v["status"] == "blocked_contract" for v in selected)
    by_id = {v["case_id"]: v for v in variants}
    for variant in selected:
        control = variant["paired_control_id"]
        if control:
            # A live input-gap claim needs the corresponding answerable control.
            assert by_id[control]["selected_live"], (variant["case_id"], control)


@pytest.mark.parametrize("expression", ["__import__('os').getcwd()", "pow(2,3)", "a+1", "True+1"])
def test_oracle_math_rejects_executable_or_unbound_input(expression):
    with pytest.raises(ValueError):
        arithmetic(expression)


def test_runtime_augmentation_keeps_original_oracle_and_slots():
    files, manifest = build_runtime_augmentation()
    for name, raw in files.items():
        assert (DEST.with_name("professional_runtime_v1") / name).read_bytes() == raw
    assert manifest["formal_planned_slots_added"] == []
    assert manifest["original_planned_slots_changed"] is False
    assert manifest["original_frozen_manifest_sha256"] == digest((DEST / "release_manifest.json").read_bytes())
    assert len(manifest["cases"]) == 3
    for case in manifest["cases"]:
        oracle = case["original_private_oracle"]
        assert digest((ROOT / oracle["path"]).read_bytes()) == oracle["sha256"]
        assert oracle["expected_values_changed"] is False


def test_runtime_attachment_identity_zero_inputs_and_boundaries_are_explicit():
    files, manifest = build_runtime_augmentation()
    for case in manifest["cases"]:
        source = json.loads(files[case["public_files"][0]])
        assert len(source["rows"]) == 16
        by_name = {row["input_name"]: row for row in source["rows"]}
        assert set(by_name) == set(case["source_bindings"])
        for name, row in by_name.items():
            assert row["period"] == ("2026-08" if name.startswith("opening_") else "2026-09")
            assert (row["organization"],row["currency"],row["unit"]) == ("Synthetic Fixture Co","CNY","元")
        for name in ("debt_drawdowns", "dividends_paid", "closing_restricted_cash"):
            assert by_name[name]["amount"] == "0"
        boundary = json.loads(files[case["public_files"][1]])
        assert len(boundary["rows"]) == 8
        assert all(row["amount"] == "0" for row in boundary["rows"])
        assert set(case["model_boundary"]) == {row["boundary_name"] for row in boundary["rows"]}
        assert set(case["model_boundary"].values()) == {0}


def test_runtime_public_attachments_have_no_oracle_references_or_expected_answers():
    files, _ = build_runtime_augmentation()
    for name, raw in files.items():
        if name.startswith("public/"):
            payload = json.loads(raw)
            assert "original_private_oracle" not in payload
            assert b"private/oracles/" not in raw
            assert b"numeric_checks" not in raw
            assert b"expected_values" not in raw
