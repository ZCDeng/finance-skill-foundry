"""A fact token's explicit unit is checked against that exact source fact."""
import hashlib
import json

import pytest

from foundry.finance_service import FinanceStore
from foundry.task import TaskStore
from test_finance_adjustment_fact_typing import adjustment_store as adjustment_store, _facts, _run, _save_adjustment


def _measurements(tmp_path, units, *, column="value", value="7.25"):
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="事实单位边界"), actor="manager")
    path = tmp_path / "units.json"
    path.write_text(json.dumps([{"label": f"measure-{index}", "value": value, "unit": unit}
                                for index, unit in enumerate(units)]))
    dataset = service.analysis.add_dataset(path, name="Archived unit measurements")
    revision = service.analysis.save_analysis({
        "question": "Retain each measure's stated unit", "bindings": {"inputs": dataset["id"]},
        "scope": {"currency": "CNY"},
        "sql": f"SELECT label, unit, CAST(value AS DECIMAL(38,6)) AS {column} FROM inputs ORDER BY label",
    })
    run = service.analysis.run_analysis(revision["id"])
    assert run["execution_status"] == "succeeded", run.get("error")
    facts = service.prepare_explanation({"run_ids": [run["id"]], "fact_view": "inspection"})["facts"]
    facts = sorted((fact for fact in facts if fact["column"] == column), key=lambda fact: fact["row"])
    assert len(facts) == len(units)
    return service, run, facts


def _save(service, run, facts, suffix, *, index=0):
    body = "\n".join("指标值为{{fact:" + fact["id"] + "}}" + (suffix if n == index else "") + "。"
                     for n, fact in enumerate(facts))
    return service.save_explanation_draft({"run_ids": [run["id"]], "fact_ids": [f["id"] for f in facts], "body": body})


def _unit_issues(draft):
    return [issue for issue in draft["quality"]["issues"] if issue["code"] == "fact_unit_mismatch"]


@pytest.mark.parametrize("source_unit,written_unit", [
    ("元", "万元"), ("万元", "元"), ("元", "亿元"), ("元", "千元"), ("元", "百万元"),
    ("千元", "百万元"), ("万元", "人民币元"), ("元", "人民币万元"),
    ("元", "元/平方米"), ("元/件", "元/平方米"), ("元/平方米", "元/件"),
    ("%", "个百分点"), ("百分点", "%"), ("元", "百分比"), ("元", "pct"),
    ("元/平方米", "元/平方米·月"), ("元", "万元人民币"),
    ("人民币元", "万元"), ("人民币万元", "人民币元"),
])
def test_explicit_unit_conflicts_cannot_hide_behind_the_rendered_fact_unit(tmp_path, source_unit, written_unit):
    service, run, facts = _measurements(tmp_path, [source_unit])
    archived = service.analysis.root / "runs" / f"{run['id']}.json"
    before = archived.read_bytes()
    draft = _save(service, run, facts, written_unit)
    issues = _unit_issues(draft)
    assert issues, (draft["body"], draft["quality"])
    assert {issue["fact_id"] for issue in issues} == {facts[0]["id"]}
    assert draft["quality"]["status"] == "needs_attention"
    assert written_unit in draft["body_template"]
    assert written_unit in draft["body"]  # Flag the user's unit; never silently replace or convert it.
    assert draft["claims"][0]["value"] == facts[0]["value"]
    assert archived.read_bytes() == before
    again = service.validate_explanation({"draft_id": draft["id"]})
    assert any(issue["code"] == "fact_unit_mismatch" for issue in again["issues"])


@pytest.mark.parametrize("source_unit,written_unit", [
    ("元", "元"), ("万元", "万元"), ("亿元", "亿元"), ("千元", "千元"), ("百万元", "百万元"),
    ("元", "人民币元"), ("万元", "人民币万元"),
    ("人民币元", "元"), ("人民币元", "人民币元"), ("人民币万元", "万元"),
    ("人民币元/平方米", "元/平方米"),
    ("元", "元人民币"), ("元人民币", "人民币元"),
    ("元/平方米·月", "元/平方米·月"), ("元/平方米/月", "元/平方米/月"),
    ("元/件", "元/件"), ("元/平方米", "元/平方米"), ("元/件", "元／件"),
    ("%", "%"), ("％", "%"), ("pct", "百分比"), ("百分比", "pct"),
    ("百分点", "个百分点"), ("百分点", "个 百分点"),
    ("元", ""), ("万元", ""), ("元/件", ""), ("元/平方米", ""),
])
def test_matching_units_and_no_explicit_unit_remain_valid(tmp_path, source_unit, written_unit):
    service, run, facts = _measurements(tmp_path, [source_unit])
    draft = _save(service, run, facts, written_unit)
    assert not _unit_issues(draft), draft["quality"]["issues"]
    assert draft["claims"][0]["value"] == facts[0]["value"]


@pytest.mark.parametrize("word", ["元旦前结清", "元素清单另附", "万元素样本", "个百分点位另行说明"])
def test_a_unit_prefix_inside_an_ordinary_word_is_not_an_explicit_unit(tmp_path, word):
    service, run, facts = _measurements(tmp_path, ["万元"])
    draft = _save(service, run, facts, " " + word)
    assert not _unit_issues(draft), draft["quality"]["issues"]


@pytest.mark.parametrize("suffix", ["%", "％", "百分比", "pct", ""])
def test_ratio_percent_display_does_not_change_exact_fraction(tmp_path, suffix):
    service, run, facts = _measurements(tmp_path, ["比率"], column="ratio", value="0.25")
    assert facts[0]["unit"] == "%" and facts[0]["display_value"] == "25.00%"
    draft = _save(service, run, facts, suffix)
    assert not _unit_issues(draft), draft["quality"]["issues"]
    assert draft["claims"][0]["value"] == "0.250000"


@pytest.mark.parametrize("index", [0, 1])
def test_another_same_valued_fact_cannot_supply_a_token_unit(tmp_path, index):
    service, run, facts = _measurements(tmp_path, ["元", "万元"])
    assert facts[0]["value"] == facts[1]["value"]
    wrong = _save(service, run, facts, facts[1-index]["unit"], index=index)
    assert {issue["fact_id"] for issue in _unit_issues(wrong)} == {facts[index]["id"]}
    right = _save(service, run, facts, facts[index]["unit"], index=index)
    assert not _unit_issues(right)


@pytest.mark.parametrize("column", ["profit", "source_total", "adjusted_total"])
def test_native_adjustment_tokens_reject_wrong_units_without_changing_math(adjustment_store, column):
    service, context = adjustment_store
    approved = _save_adjustment(service, context, "-140.125")
    run = _run(service, context, approved)
    facts = list(_facts(service, run).values())
    index = next(index for index, fact in enumerate(facts) if fact["column"] == column)
    source_hash = hashlib.sha256(service.analysis._object_path("runs", run["id"]).read_bytes()).hexdigest()
    wrong = _save(service, run, facts, "万元", index=index)
    assert {issue["fact_id"] for issue in _unit_issues(wrong)} == {facts[index]["id"]}
    assert run["result"]["rows"][0]["source_total"] == "130"
    assert run["result"]["rows"][0]["adjusted_total"] == "-10.125"
    assert hashlib.sha256(service.analysis._object_path("runs", run["id"]).read_bytes()).hexdigest() == source_hash
    assert not _unit_issues(_save(service, run, facts, "元", index=index))


@pytest.mark.parametrize("suffix", ["万元", "元", ""])
def test_version_18_draft_is_rechecked_in_current_view_without_rewriting_history(tmp_path, monkeypatch, suffix):
    from foundry import finance_claim_semantics, finance_explanations

    service, run, facts = _measurements(tmp_path, ["元"])
    original = finance_explanations._fact_context_issues
    # Exercise a real saved version-18 verdict, with the former token-unit omission.
    with monkeypatch.context() as legacy:
        legacy.setattr(finance_claim_semantics, "CLAIM_SEMANTICS_VERSION", 18)
        legacy.setattr(finance_explanations, "_fact_context_issues", lambda *args, **kwargs:
                       [issue for issue in original(*args, **kwargs) if issue["code"] != "fact_unit_mismatch"])
        saved = _save(service, run, facts, suffix)
    paths = [service.analysis._object_path("drafts", saved["id"]),
             service.analysis._object_path("runs", run["id"]),
             service.analysis._object_path("completions", saved["completion"]["id"])]
    before = [path.read_bytes() for path in paths]
    raw = service.analysis.get_draft(saved["id"])
    assert raw["quality"]["status"] == "pass"
    assert raw["quality"]["claim_semantics_version"] == 18
    current = service.analysis.draft_in_view(raw, None)
    manager = service._readable_draft(raw)
    for viewed in (current, manager):
        assert bool(_unit_issues(viewed)) == (suffix == "万元")
        assert viewed["quality"]["status"] == ("needs_attention" if suffix == "万元" else "pass")
        assert viewed["body"] == raw["body"] and viewed["claims"] == raw["claims"]
    validation = service.validate_explanation({"draft_id": saved["id"]})
    assert any(i["code"] == "fact_unit_mismatch" for i in validation["issues"]) == (suffix == "万元")
    assert [path.read_bytes() for path in paths] == before


def test_current_correct_draft_keeps_the_no_relevant_assertion_fast_path(tmp_path, monkeypatch):
    from foundry import finance_claim_semantics, finance_explanations

    service, run, facts = _measurements(tmp_path, ["元"])
    saved = _save(service, run, facts, "元")
    raw = service.analysis.get_draft(saved["id"])
    assert raw["quality"]["claim_semantics_version"] == finance_claim_semantics.CLAIM_SEMANTICS_VERSION

    def unexpected(*args, **kwargs):
        raise AssertionError("current version without relevant assertions must not prepare facts again")

    monkeypatch.setattr(finance_explanations, "prepare_explanation", unexpected)
    assert finance_explanations.saved_claim_semantic_issues(service.analysis, raw) == []
    assert service.analysis.draft_in_view(raw, None)["quality"]["status"] == "pass"
