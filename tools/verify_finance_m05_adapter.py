#!/usr/bin/env python3
"""Independent M05 authoring diagnostics; no original release-slot credit.

The original mutation driver is immutable because other frozen contracts bind
its exact bytes. This observer calls that driver without changing its functions,
classification, constants, or stored observations. Supplementary draft evidence
never substitutes for the original save/validation/completion gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "tools/verify_finance_mutation_pipeline.py"
ORIGINAL_SHA256 = "7868708a037dce6fabd89a0b41915ded1dc31913e55bf216960e48f1e4a8c7bf"


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def load_original():
    if file_hash(ORIGINAL) != ORIGINAL_SHA256:
        raise ValueError("frozen original mutation driver identity mismatch")
    spec = importlib.util.spec_from_file_location("m05_immutable_original_driver", ORIGINAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observe_vmp_case(cli):
    original = load_original()
    control, mutant, setup = original.vmp_case(cli)
    residual_ids = [claim["fact_id"] for claim in (control.get("current_draft") or {}).get("claims", [])
                    if claim.get("column") == "residual" and claim.get("fact_id")]
    return control, mutant, {**setup, "mutation_effectiveness": m05_saved_effectiveness(mutant, residual_ids)}


def m05_saved_effectiveness(mutant, residual_ids):
    """Observe the saved omission; never award detection credit to an auto-repaired draft."""
    expected = set(residual_ids)
    request = mutant.get("request") or {}
    saved = mutant.get("current_draft") or {}
    request_claims = request.get("claims") or []
    saved_claims = saved.get("claims") or []
    request_cites = sorted(expected & set(request.get("fact_ids") or []))
    request_cites += [c.get("fact_id") for c in request_claims if isinstance(c, dict)
                     and (c.get("fact_id") in expected or c.get("column") == "residual")]
    saved_ids = sorted(expected & set(saved.get("fact_ids") or []))
    saved_claim_ids = [c.get("fact_id") for c in saved_claims if isinstance(c, dict)
                       and (c.get("fact_id") in expected or c.get("column") == "residual")]
    request_text = str(request.get("body") or "")
    saved_text = "\n".join(str(saved.get(key) or "") for key in ("body", "body_template", "evidence_appendix"))
    request_marker = "residual" in request_text.lower() or "残差" in request_text
    saved_marker = "residual" in saved_text.lower() or "残差" in saved_text
    submitted_omission = bool(expected) and not request_cites and not any(
        "{{fact:" + fact_id + "}}" in request_text for fact_id in expected) and not request_marker
    saved_omission = (bool(saved) and bool(expected) and not saved_ids and not saved_claim_ids
                      and not saved_marker and not any(fact_id in saved_text for fact_id in expected))
    effective = submitted_omission and saved_omission
    return {"status": "effective" if effective else "not_effective",
            "expected_residual_fact_ids": sorted(expected),
            "submitted_omission": submitted_omission,
            "saved_omission": saved_omission,
            "request_residual_text_marker": request_marker, "saved_residual_text_marker": saved_marker,
            "saved_residual_fact_ids": saved_ids, "saved_residual_claim_fact_ids": saved_claim_ids,
            "saved_appendix_render_version": (saved.get("evidence_appendix_meta") or {}).get("render_version"),
            "full_flow_coverage": "observed_omission" if effective else "adapter_gap",
            "detection_credit": False,
            "reason": ("The saved document actually omits the residual; classification still requires the existing gates."
                       if effective else
                       "The saved document does not preserve the requested omission; an auto-repaired document is not an omitted-check negative control.")}


def probe_m05_authoring_boundary(cli, automatic, residual_ids):
    """Effective saved omission through actual validation and completion; no original credit."""
    original = load_original()
    saved = automatic["current_draft"]
    expected = set(residual_ids)
    body = saved["body"]
    appendix = saved.get("evidence_appendix") or ""
    if appendix and body.endswith(appendix):
        body = body[:-len(appendix)].rstrip()
    spec = {"requirements_id": saved["requirements_id"], "run_ids": saved["run_ids"],
            "body": body, "body_template": saved.get("body_template"),
            "claims": [c for c in saved["claims"] if c.get("fact_id") not in expected
                       and c.get("column") != "residual"],
            "fact_ids": [fact_id for fact_id in saved["fact_ids"] if fact_id not in expected],
            "evidence_appendix": "", "evidence_appendix_meta": {}, "materiality": saved["materiality"]}
    facts = cli.call("prepare-explanation", spec={"run_ids": saved["run_ids"]})["facts"]
    residuals = [fact for fact in facts if fact["id"] in expected]
    if not residuals or any(str(fact["value"]) != "0" for fact in residuals):
        raise ValueError("M05 probe requires the actual source-bound zero residual")
    positive = {**spec,
        "body": body + "\n" + "\n".join("residual: " + fact["display_value"] for fact in residuals),
        "body_template": (spec.get("body_template") or body) + "\n"
                         + "\n".join("residual: {{fact:" + fact["id"] + "}}" for fact in residuals),
        "claims": [*spec["claims"], *(fact["reference_template"]["claim"] for fact in residuals)],
        "fact_ids": [*spec["fact_ids"], *(fact["id"] for fact in residuals)]}

    def saved_outcome(request):
        creation = cli.call("analysis-draft", spec=request, required=False)
        if creation["returncode"] or not isinstance(creation["value"], dict):
            raise RuntimeError("M05 authoring probe failed to persist its draft")
        draft = creation["value"]
        validation = cli.call("validate-explanation", spec={"draft_id": draft["id"]}, required=False)
        refresh = cli.call("save-explanation-draft", spec={"draft_id": draft["id"]}, required=False)
        state = cli.state()
        current = next(row for row in state["drafts"] if row["id"] == draft["id"])
        receipt_id = ((refresh.get("value") or {}).get("completion") or {}).get("id")
        receipt = next((row for row in state["completions"] if row["id"] == receipt_id), None)
        observed = {"request": request, "authoring_save": creation, "save": refresh,
                    "validation": validation, "current_draft": current, "current_completion": receipt}
        observed["accepted"] = bool(validation["returncode"] == 0
            and (validation.get("value") or {}).get("status") == "pass"
            and current.get("quality", {}).get("status") == "pass"
            and (receipt or {}).get("status") == "complete")
        observed["rejection_reasons"] = original.rejection_reasons(observed)
        observed["saved_content_unchanged"] = all(
            draft.get(key) == current.get(key) for key in
            ("body", "body_template", "claims", "fact_ids", "evidence_appendix", "content_hash"))
        return observed

    control = saved_outcome(positive)
    mutant = saved_outcome(spec)
    draft = mutant["current_draft"]
    validation, refresh = mutant["validation"], mutant["save"]
    before_replay = cli.state()
    replay = cli.call("save-explanation-draft", spec={"draft_id": draft["id"]}, required=False)
    after_replay = cli.state()
    receipt_id = (mutant["current_completion"] or {}).get("id")
    replay_same_receipt = (replay.get("returncode") == 0
        and ((replay.get("value") or {}).get("completion") or {}).get("id") == receipt_id
        and len(before_replay["completions"]) == len(after_replay["completions"]))
    exports = {fmt: cli.call("analysis-export", "--draft", draft["id"], "--format", fmt,
                             "--mode", "management", required=False) for fmt in ("md", "xlsx")}
    state = cli.state()
    current = next(row for row in state["drafts"] if row["id"] == draft["id"])
    receipts = [row for row in state["completions"] if row.get("draft_id") == draft["id"]]
    effectiveness = m05_saved_effectiveness({"request": spec, "current_draft": current}, residual_ids)
    classification = original.classify(control, mutant, "M05")
    verified = (classification == "detected" and effectiveness["status"] == "effective"
                and control["saved_content_unchanged"] and mutant["saved_content_unchanged"]
                and replay_same_receipt and receipt_id is not None
                and not any(row.get("status") == "complete" for row in receipts))
    return {"request": spec, "control": control, "mutant": mutant,
            "current_draft": current, "validation": validation,
            "refresh": refresh, "exports": exports, "draft_receipts": receipts,
            "completion_replay": replay, "replay_same_receipt": replay_same_receipt,
            "mutation_effectiveness": effectiveness,
            "original_case_credit": False, "status": "detected" if verified else "adapter_gap",
            "authoring_completion_flow_verified": verified,
            "coverage_boundary": "An effective editable-draft omission is validated and receives a non-complete receipt through the actual save API; its complete positive control and replay are checked without rewriting saved content. This supplementary authoring flow does not change the ineffective original mutation or its frozen classification. Draft exports confer no completion or publication approval."}


def run_probe(foundry, output, candidate_manifest=None):
    original = load_original()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if candidate_manifest:
        manifest = json.loads(Path(candidate_manifest).read_text())
        if manifest["files"].get("tools/verify_finance_m05_adapter.py") != file_hash(__file__):
            raise ValueError("M05 observer is not bound to the candidate manifest")
    identity = original.candidate_identity(foundry, candidate_manifest)
    before = {"original_driver_sha256": file_hash(ORIGINAL), "observer_sha256": file_hash(__file__)}
    cli = original.CLI(foundry, output / "public-cli")
    cli.start("M05 independent authoring boundary; no original-slot credit")
    control, mutant, setup = observe_vmp_case(cli)
    original_observation = {"control": control, "mutant": mutant,
                            "status": original.classify(control, mutant, "M05"),
                            "original_setup": {key: value for key, value in setup.items()
                                               if key != "mutation_effectiveness"}}
    write_new(output / "original-observation.json", original_observation)
    supplement = probe_m05_authoring_boundary(
        cli, mutant, setup["mutation_effectiveness"]["expected_residual_fact_ids"])
    after = {"original_driver_sha256": file_hash(ORIGINAL), "observer_sha256": file_hash(__file__)}
    result = {"kind": "independent_m05_authoring_diagnostic", "status": "adapter_gap",
              "frozen_case_coverage": "partial", "original_slots_credit": 0,
              "original_case_status": original_observation["status"],
              "mutation_effectiveness": setup["mutation_effectiveness"],
              "supplementary_authoring_probe": supplement, "provider_calls": 0,
              "independent_authoring_completion_status": supplement["status"],
              "candidate_identity": identity, "source_before": before, "source_after": after,
              "source_identity_unchanged": before == after}
    write_new(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path)
    args = parser.parse_args()
    result = run_probe(args.foundry, args.output, args.candidate_manifest)
    print(json.dumps({"status": result["status"], "original_case_status": result["original_case_status"],
                      "original_slots_credit": result["original_slots_credit"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
