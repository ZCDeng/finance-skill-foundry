from __future__ import annotations

import pytest

from foundry.analysis import AnalysisStore
from foundry.finance_service import FinanceStore
from foundry.sample_reference import DECIDER
from foundry.sample_task import KINDS, create_reference_task, create_sample_task, sample_status
from foundry.task import TaskStore

AUGUST = "华宸物业_2026年08月_月结财务套表_GL-AP-AR-CF.xlsx"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    var = tmp_path_factory.mktemp("reference") / "var"
    made = create_reference_task(var)
    return var, TaskStore(var).get(made["id"]), made


def test_the_reference_task_walks_the_whole_route(built):
    _, task, made = built
    assert made["created"] is True and task.meta()["title"] == KINDS["reference"]
    blocks = {block["key"]: block for block in FinanceStore(task, actor="manager").finance_close_status({})["blocks"]}
    assert {key: block["state"] for key, block in blocks.items()} == {
        "source": "done", "structure": "done", "scope": "done", "controls": "done",
        # Two differences wait on 合同管理部 and 应收会计: the example shows a close as it usually stands.
        "exceptions": "blocked", "review": "done",
    }
    waiting = [item["text"] for item in blocks["exceptions"]["items"] if "待外部确认" in item["text"]]
    assert len(waiting) == 2 and any("-2793.2794" in text for text in waiting)


def test_every_decision_and_the_draft_say_they_are_the_examples(built):
    _, task, _ = built
    manager = FinanceStore(task, actor="manager")
    decided = [(row.get("issue") or {}).get("disposition") for row in manager.finance_controls_list({})["controls"]]
    decided = [disposition for disposition in decided if disposition]
    assert len(decided) == 4 and all(disposition["decided_by_name"] == DECIDER for disposition in decided)
    draft = AnalysisStore(task).state()["drafts"][-1]
    dimensions = draft["explanation_check"]["status_dimensions"]
    assert {key: dimensions[key]["status"] for key in ("execution", "numeric_citation", "source_validation")} == {
        "execution": "pass", "numeric_citation": "pass", "source_validation": "pass"}
    assert "91.14%" in draft["body"] and "-3.22 个百分点" in draft["body"]


def test_the_reference_is_reused_rebuilt_on_request_and_never_prefills_the_practice_task(built):
    var, task, made = built
    assert create_reference_task(var) == {"id": made["id"], "created": False}

    practice = TaskStore(var).get(create_sample_task(var)["id"])
    dataset = next(row for row in AnalysisStore(practice).state()["datasets"] if row["name"] == AUGUST)
    proposal = FinanceStore(practice).structure_proposal_list({"dataset_id": dataset["id"]})["proposals"][0]
    assert not proposal.get("template_matches")
    assert {row["kind"] for row in sample_status(var)["tasks"]} == {"reference", "practice"}

    rebuilt = create_reference_task(var, rebuild=True)
    assert rebuilt["created"] is True and rebuilt["id"] != made["id"]
    assert task.lifecycle_status() == "trashed"


def test_a_second_request_waits_for_the_reference_being_built(tmp_path, monkeypatch):
    import threading
    import time

    import foundry.sample_reference as reference

    started, var = threading.Event(), tmp_path / "var"

    def slow(task):
        started.set()
        time.sleep(12)  # longer than the ordinary 10-second lock wait
        return {}

    monkeypatch.setattr(reference, "build_reference", slow)
    first: dict = {}
    builder = threading.Thread(target=lambda: first.update(create_reference_task(var)))
    builder.start()
    started.wait(30)
    second = create_reference_task(var)
    builder.join()
    assert second == {"id": first["id"], "created": False}


def test_the_figures_the_guide_quotes_are_the_ones_the_reference_computes(built):
    """跟着做 prints these from expected.json; the reference computes them with the installed engine."""
    import json
    from collections import Counter
    from decimal import Decimal

    from foundry.sample_task import pack_dir

    expected = json.loads((pack_dir() / "expected.json").read_text(encoding="utf-8"))
    _, task, _ = built
    controls = FinanceStore(task, actor="manager").finance_controls_list({})["controls"]
    results = [(row["control"]["label"], (row.get("result") or {})) for row in controls if row.get("state") == "confirmed"]
    breaks = {label: Decimal(result["difference"]) for label, result in results if result.get("status") != "pass"}
    assert {"confirmed": len(results), "pass": len(results) - len(breaks), "breaks": len(breaks)} == expected["controls"]
    assert Decimal(breaks["合同台账本年实收 = 月结区域实收"]).quantize(Decimal("0.01")) == Decimal(expected["f02_difference"])
    assert breaks["应收滚动：年初 + 新增 − 收回 − 核销 = 期末"] == Decimal(expected["ar_rollforward_difference"])
    assert abs(breaks["08·AR收缴率与欠费 · 已计提坏账：分项合计 = 合计"]) == Decimal(expected["f01_difference"])
    decided = Counter((row.get("issue") or {}).get("disposition", {}).get("decision") for row in controls if (row.get("issue") or {}).get("disposition"))
    assert dict(decided) == expected["dispositions"]

    run = AnalysisStore(task).state()["runs"][-1]["result"]["rows"]
    group = {row["metric_key"]: Decimal(str(row["value"])) for row in run if row["entity"] == "华宸物业" and row.get("value") is not None}
    for key in ("break_even_collection", "collection_gap", "collection_gap_total"):
        assert group[key].quantize(Decimal("0.01")) == Decimal(expected[key]), key
    assert dict(Counter(row["level"] for row in run if row["metric_key"] == "risk_score")) == expected["radar"]


def test_the_next_month_route_adopts_what_the_practice_task_confirmed(tmp_path):
    """Step 9: confirm the August month-close in the practice task, then make the September one."""
    import json

    from foundry.sample_reference import MONTH_CLOSE, Reference
    from foundry.sample_task import create_next_month_sample, pack_dir

    expected = json.loads((pack_dir() / "expected.json").read_text(encoding="utf-8"))["next_month"]
    var = tmp_path / "var"
    reference = Reference(TaskStore(var).get(create_sample_task(var)["id"]))
    reference.datasets = {MONTH_CLOSE: reference.datasets[MONTH_CLOSE]}
    reference.confirm_structures()
    september = TaskStore(var).get(create_next_month_sample(var)["id"])
    dataset = AnalysisStore(september).state()["datasets"][0]
    matches = FinanceStore(september).structure_proposal_list({"dataset_id": dataset["id"]})["proposals"][0]["template_matches"]
    assert len(matches) == expected["matched"]
    assert sum(1 for match in matches if match["auto_apply"]) == expected["auto_apply"]
    assert [match["sheet"] for match in matches if not match["auto_apply"]] == [expected["differs"]]



def test_the_billing_figures_the_guide_quotes_are_the_ones_the_reference_computes(built):
    """Step 5 of 跟着做: 海口城市公司's 收费明细, every planted finding where the guide says it is."""
    import json
    from decimal import Decimal

    import openpyxl

    from foundry import billing_sample
    from foundry.billing_detail import BillingDetailStore
    from foundry.sample_task import pack_dir

    expected = json.loads((pack_dir() / "expected.json").read_text(encoding="utf-8"))["billing"]
    pct = lambda value: str((Decimal(value) * 100).quantize(Decimal("0.01")))  # noqa: E731
    _, task, _ = built
    store = BillingDetailStore(task, actor="manager")
    details = {row["kind"]: row for row in store.list()}
    # The generator writes the same bytes on every machine and Python: CI and the app see one export.
    assert {kind: row["row_count"] for kind, row in details.items()} == expected["rows"]
    assert {entry["name"]: entry["sha256"] for row in details.values() for entry in row["files"]} == expected["sha256"]
    assert all(row["confirmation"] and not row["missing"] for row in details.values())

    runs = sorted((store.root / "runs").glob("*.json"))
    run = json.loads(runs[0].read_text(encoding="utf-8"))
    assert len(runs) == 1 and run["caliber"]["status"] == "confirmed"
    result = run["result"]
    figures, groups = result["figures"], {group["key"]["nature"]: group["figures"] for group in result["groups"]}
    assert pct(figures["collection_rate_current"]) == expected["current"]
    assert figures["reported"]["collection_rate_current"]["difference_points"] == expected["difference_points"]
    assert pct(figures["arrears_recovery_rate"]) == expected["arrears_recovery"]
    assert pct(figures["collection_rate_total"]) == expected["total"]
    assert pct(result["related"]["excluded"]["collection_rate_total"]) == expected["total_excluding_related"]
    assert pct(groups["住宅"]["collection_rate_current"]) == expected["residential_current"]
    assert pct(groups["住宅"]["arrears_recovery_rate"]) == expected["residential_recovery"]
    assert pct(groups["商业/办公"]["collection_rate_current"]) == expected["commercial_current"]
    assert pct(groups["商业/办公"]["arrears_recovery_rate"]) == expected["commercial_recovery"]
    assert pct(figures["waiver_rate"]) == expected["waiver_rate"]
    issues = {issue["code"]: issue for issue in result["quality"] + result["labels"]}
    assert {code: issues[code]["rows"] for code in ("void_bills", "red_letter_lines", "bills_without_property")} == {
        code: expected[code] for code in ("void_bills", "red_letter_lines", "bills_without_property")}
    assert issues["advance_labelled_current"]["amount"] == expected["advance_labelled_current"]
    assert issues["arrears_labelled_current"]["amount"] == expected["arrears_labelled_current"]
    # Counted by their labels the receipts give the billing system's own 本年收缴率, the 套表's 83.76%.
    labelled = Decimal(figures["collected"]) + Decimal(expected["advance_labelled_current"]) + Decimal(expected["arrears_labelled_current"])
    assert abs(labelled / Decimal(figures["receivable"]) - Decimal(billing_sample.REPORTED_CURRENT)) < Decimal("0.001")
    assert pct(billing_sample.REPORTED_CURRENT) == expected["reported_current"]

    ids = {kind: row["id"] for kind, row in details.items()}
    by_project = store.collection_run({**ids, "as_of": expected["as_of"], "group_by": ["project"]})["result"]["groups"]
    waivers = {group["key"]["project"]: group["figures"]["waiver_rate"] for group in by_project}
    assert pct(waivers.pop("云海苑")) == expected["waiver_rate_yunhai"] and max(map(Decimal, waivers.values())) < Decimal("0.01")
    # The guide's variant: 本年全部实收 ÷ 本年应收, 商业租金代收 not a property fee. Unconfirmed, so a trial.
    variant = store.collection_run({**ids, "as_of": expected["as_of"], "total_method": "all_receipts",
                                    "excluded_fee_items": ["商业租金代收"]})
    assert variant["caliber"]["status"] == "trial"
    assert pct(variant["result"]["figures"]["collection_rate_total"]) == expected["variant_total"]

    # The reported rate is the 套表's own cell for the city.
    sheet = openpyxl.load_workbook(pack_dir() / AUGUST, data_only=True)["11·城市公司明细表"]
    row = next(row for row in sheet.iter_rows(values_only=True) if row[1] == expected["city"])
    assert str(row[12]) == billing_sample.REPORTED_CURRENT
