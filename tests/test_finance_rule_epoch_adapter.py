"""Public adapter and actual persistent rule-transition precondition contracts."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from copy import deepcopy

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.mark.parametrize("case_id", ["E27--method_change", "E27--unrelated_rule"])
def test_rule_epoch_adapter_requires_actual_persistent_state(case_id):
    adapters = module("finance_professional_adapters")
    bootstrap = module("finance_professional_bootstrap")
    original = json.loads((ROOT / "tests/fixtures/finance_evals/professional/public" / f"{case_id}.json").read_text())
    public, trace = adapters.adapt(original)
    assert trace["readiness"]["runtime_readiness"] == "candidate_with_explicit_state_bootstrap"
    assert trace["readiness"]["blockers"] == []
    assert trace["readiness"]["acceptance_readiness"] == "not_verified"
    assert case_id in bootstrap.LIVE_CASES
    assert [{"name": r["name"], "value": r["value"]} for r in public["datasets"][0]["rows"]] == original["data"]
    assert "approved" not in public["question"]


def test_runtime_rule_probe_has_no_process_global_override():
    source = (ROOT / "tools/finance_professional_adapter_probe.py").read_text()
    assert "RULES[key]=" not in source
    assert "finance-rule-epoch-advance" in source
    assert "volume_mix_price_closure" in (ROOT / "tools/finance_professional_bootstrap.py").read_text()


@pytest.mark.parametrize("variant", ["basis_change", "purpose_change", "tax_change", "cross_task_confirmation",
                                     "revoked_confirmation", "expanded_partial_confirmation"])
def test_rule_epoch_does_not_claim_unimplemented_state_transitions_ready(variant):
    adapters = module("finance_professional_adapters")
    original = json.loads((ROOT / "tests/fixtures/finance_evals/professional/public" / f"E27--{variant}.json").read_text())
    _, trace = adapters.adapt(original)
    assert trace["readiness"]["runtime_readiness"] == "blocked_state_precondition"
    assert trace["readiness"]["blockers"] == ["no_declared_runtime_state_bootstrap_for_" + variant]


@pytest.mark.parametrize("mutation", ["noop", "wrong_record", "implementation_change", "unrelated_change", "assistant"])
def test_epoch_probe_cannot_pass_unchanged_or_unrelated_receipts(mutation):
    bootstrap = module("finance_professional_bootstrap")
    key = "variance.volume_mix_price"
    before = {"rules": [{"rule_id": key, "implementation_version": 1, "epoch": 0, "epoch_record_id": None},
                        {"rule_id": "unrelated", "implementation_version": 1, "epoch": 0, "epoch_record_id": None}]}
    after = deepcopy(before)
    after["rules"][0].update(epoch=1, epoch_record_id="event-one")
    event = {"rule_epoch": {"id": "event-one", "rule_id": key, "epoch": 1, "previous_epoch": 0,
                            "implementation_version": 1, "changed_by": "manager"}}
    bootstrap.verify_epoch_transition(key, before, event, after)
    if mutation == "noop":
        after = before
    elif mutation == "wrong_record":
        after["rules"][0]["epoch_record_id"] = "some-other-event"
    elif mutation == "implementation_change":
        after["rules"][0]["implementation_version"] = 2
    elif mutation == "unrelated_change":
        after["rules"][1]["epoch"] = 1
    else:
        event["rule_epoch"]["changed_by"] = "assistant"
    with pytest.raises(AssertionError, match="persistent rule epoch"):
        bootstrap.verify_epoch_transition(key, before, event, after)
