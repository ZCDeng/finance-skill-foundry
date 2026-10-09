"""收费明细: CSV in any encoding a billing system writes, confirmed by the manager, and the rates it gives.

The figures are worked by hand from the rows below (as of 2026-08-31, a calendar year):
本年应收 = 100 + 100 + 200 + 300 + 0 + 40 = 740 (B8 void, B9 netted by its red line);
当期已收 = 100 + 60 + 200 = 360; 年初欠费 = 50 + 150 - 20 = 180; 本年清欠 = 30 + 50 = 80.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.billing_detail import BillingDetailStore, propose_mapping
from foundry.cli import main
from foundry.errors import FoundryError
from foundry.task import TaskStore

RECEIVABLE_HEADER = "应收单号,房产编号,收费项目,账期,应收原额,减免额,应收净额,单据状态"
RECEIVABLES = [
    "B1,P1,住宅物业服务费,2026-01,100,0,100,正常",
    "B2,P1,住宅物业服务费,202608,100,0,100,正常",
    "B3,P2,商办物业服务费,2026年3月,220,20,200,正常",
    "B4,P3,住宅物业服务费,2026/5,300,0,300,正常",
    "B5,P1,住宅物业服务费,2025-12,50,0,50,正常",
    "B6,P2,商办物业服务费,2025-06,150,0,150,正常",
    "B7,P1,住宅物业服务费,2027-01,100,0,100,正常",
    "B8,P2,商办物业服务费,2026-04,999,0,999,作废",
    "B9,P2,商办物业服务费,2026-02,80,0,80,正常",
    "B9,P2,商办物业服务费,2026-02,-80,0,-80,冲红",
    "B10,P9,车位管理费,2026-06,40,0,40,正常",
]
RECEIPT_HEADER = "收款单号,收款日期,应收单号,收款金额,收款方式,款项性质"
RECEIPTS = [
    "R1,2026-01-15,B1,100,微信,当期",
    "R2,2026/8/20,B2,60,银行,当期",
    "R3,20260401,B3,200,银行,当期",
    "R4,2025-12-20,B5,20,现金,当期",
    "R5,2026-02-01,B5,30,微信,当期",
    "R6,2026-05-01,B6,50,银行,清欠",
    "R7,2026-07-01,B7,100,预存冲抵,当期",
    "R8,2026-03-01,BX,10,现金,预收",
    "R9,2026-09-05,B2,40,微信,当期",
]
PROPERTIES = ["房产编号,房产性质,房产类型,产权归属", "P1,商品房,洋房,业主", "P2,散售,商业,业主", "P3,商品房,别墅,地产"]


def _write(path: Path, lines: list[str], encoding: str) -> Path:
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode(encoding))
    return path


@pytest.fixture
def pack(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="收费明细")
    files = tmp_path / "files"
    files.mkdir()
    # The receivables come in two GBK files, the way a system exports by quarter.
    first = _write(files / "应收_1.csv", [RECEIVABLE_HEADER, *RECEIVABLES[:6]], "gbk")
    second = _write(files / "应收_2.csv", [RECEIVABLE_HEADER, *RECEIVABLES[6:]], "gbk")
    receipts = _write(files / "实收.csv", [RECEIPT_HEADER, *RECEIPTS], "utf-8-sig")
    properties = _write(files / "房产.csv", PROPERTIES, "utf-8")
    manager = BillingDetailStore(task, actor="manager")
    ids = {
        "receivable": manager.add("receivable", [first, second], name="应收明细")["id"],
        "receipt": manager.add("receipt", [receipts], name="实收明细")["id"],
        "property": manager.add("property", [properties], name="房产主数据")["id"],
    }
    for detail in ids.values():
        manager.confirm(detail)
    return task, manager, ids


def test_files_of_one_table_are_read_in_any_encoding_and_keep_their_lines(pack):
    _task, manager, ids = pack
    receivable = manager.get(ids["receivable"])
    assert receivable["row_count"] == len(RECEIVABLES)
    assert [(entry["name"], entry["encoding"], entry["rows"]) for entry in receivable["files"]] == [
        ("应收_1.csv", "gb18030", 6), ("应收_2.csv", "gb18030", 5)]
    assert receivable["columns"] == RECEIVABLE_HEADER.split(",")
    assert receivable["confirmation"]["by"] == "manager" and receivable["missing"] == []
    assert manager.get(ids["receipt"])["files"][0]["encoding"] == "utf-8"


def test_the_rates_follow_the_bills_period_and_net_receivables(pack):
    _task, manager, ids = pack
    run = manager.collection_run({**ids, "as_of": "2026-08-31"})
    figures = run["result"]["figures"]
    assert figures["receivable"] == "740.00" and figures["collected"] == "360.00"
    assert figures["collection_rate_current"] == "0.4865"
    assert (figures["month_receivable"], figures["month_collected"], figures["collection_rate_month"]) == ("100.00", "60.00", "0.6000")
    assert (figures["arrears_opening"], figures["arrears_collected"], figures["arrears_recovery_rate"]) == ("180.00", "80.00", "0.4444")
    # (360 + 80) / (740 + 180): bounded, never above 100%.
    assert figures["collection_rate_total"] == "0.4783"
    # A payment for a 2027 bill and one with no bill are prepayments, not this year's collections.
    assert figures["advance_balance"] == "110.00"
    assert (figures["waiver"], figures["waiver_rate"]) == ("20.00", "0.0263")
    assert (figures["households"], figures["households_settled"], figures["household_rate"]) == (4, 1, "0.2500")
    assert run["inputs"]["receivable"]["mapping"]["amount_net"] == "应收净额"


def test_the_common_variants_are_parameters(pack):
    _task, manager, ids = pack
    every_receipt = manager.collection_run({**ids, "as_of": "2026-08-31", "total_method": "all_receipts"})
    # Every receipt dated this year over this year's receivable: 550 / 740.
    assert every_receipt["result"]["figures"]["collection_rate_total"] == "0.7432"
    related = manager.collection_run({**ids, "as_of": "2026-08-31"})["result"]["related"]
    assert related["only"]["receivable"] == "300.00" and related["only"]["collected"] == "0.00"
    assert related["excluded"]["collection_rate_current"] == "0.8182"
    leaving_out = manager.collection_run({**ids, "as_of": "2026-08-31", "exclude_related": True})
    assert leaving_out["result"]["figures"]["collection_rate_total"] == "0.7097"
    # A July-to-June service year: the window starts 2026-07, so everything before is arrears.
    service_year = manager.collection_run({**ids, "as_of": "2026-08-31", "year_start_month": 7})
    assert service_year["result"]["window"]["year_start"] == "2026-07"
    assert service_year["result"]["figures"]["receivable"] == "100.00"


def test_it_says_what_it_left_out_and_which_labels_disagree(pack):
    _task, manager, ids = pack
    result = manager.collection_run({**ids, "as_of": "2026-08-31", "reported": {"collection_rate_current": 0.52}})["result"]
    quality = {issue["code"]: issue for issue in result["quality"]}
    assert (quality["void_bills"]["rows"], quality["void_bills"]["amount"]) == (1, "999.00")
    assert quality["void_bills"]["lines"] == ["应收_2.csv 第 3 行"]
    assert quality["red_letter_lines"]["amount"] == "-80.00"
    assert quality["receipts_without_bill"]["amount"] == "10.00"
    assert quality["bills_without_property"]["lines"] == ["应收_2.csv 第 6 行"]
    labels = {issue["code"]: issue for issue in result["labels"]}
    assert labels["advance_labelled_current"]["amount"] == "100.00"
    assert labels["arrears_labelled_current"]["amount"] == "30.00"
    assert result["figures"]["reported"]["collection_rate_current"]["difference_points"] == "-3.35"


def test_grouping_splits_the_same_rates(pack):
    _task, manager, ids = pack
    groups = manager.collection_run({**ids, "as_of": "2026-08-31", "group_by": ["type"]})["result"]["groups"]
    by_type = {group["key"]["type"]: group["figures"] for group in groups}
    assert by_type["洋房"]["collection_rate_current"] == "0.8000"
    assert by_type["商业"]["collection_rate_current"] == "1.0000"
    assert by_type["别墅"]["collected"] == "0.00"
    assert by_type[None]["receivable"] == "40.00"


def test_only_the_manager_confirms_and_nothing_runs_unconfirmed(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="收费明细")
    source = _write(tmp_path / "实收.csv", ["收款单号,收款日期,单号,金额", "R1,2026-01-15,B1,100"], "utf-8")
    assistant = BillingDetailStore(task)
    detail = assistant.add("receipt", [source], name="实收")
    assert detail["missing"] == ["应收单号", "收款金额"]
    proposed = assistant.propose(detail["id"], {"date": "收款日期", "bill_id": "单号", "amount": "金额"})
    assert proposed["proposal"]["by"] == "assistant" and proposed["confirmation"] is None
    with pytest.raises(FoundryError, match="only the manager"):
        assistant.confirm(detail["id"])
    confirmed = BillingDetailStore(task, actor="manager").confirm(detail["id"])
    assert confirmed["confirmation"]["mapping"]["bill_id"] == "单号"
    with pytest.raises(FoundryError, match="not confirmed"):
        unconfirmed = assistant.add("receivable", [_write(tmp_path / "应收.csv", [RECEIVABLE_HEADER, RECEIVABLES[0]], "utf-8")], name="应收")
        assistant.collection_run({"receivable": unconfirmed["id"], "receipt": detail["id"], "as_of": "2026-08-31"})


def test_files_that_do_not_belong_together_are_refused(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="收费明细")
    manager = BillingDetailStore(task, actor="manager")
    one = _write(tmp_path / "a.csv", [RECEIVABLE_HEADER, RECEIVABLES[0]], "utf-8")
    other = _write(tmp_path / "b.csv", ["应收单号,房产编号", "B1,P1"], "utf-8")
    with pytest.raises(FoundryError, match="columns differ"):
        manager.add("receivable", [one, other], name="应收")
    with pytest.raises(FoundryError, match="CSV"):
        manager.add("receivable", [tmp_path / "a.xlsx"], name="应收")
    assert not any(path.name.startswith(".staging") for path in (task.root / "analysis" / "details").iterdir())


def test_the_cli_adds_confirms_and_runs(pack, tmp_path, capsys):
    task, _manager, ids = pack
    root = str(tmp_path / "var")
    assert main(["--var", root, "--task", task.id, "--actor", "manager", "collection-run",
                 "--spec", json.dumps({**ids, "as_of": "2026-08-31"})]) == 0
    run = json.loads(capsys.readouterr().out)
    assert main(["--var", root, "--task", task.id, "collection-run-read", "--run", run["id"]]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == run["result"]
    assert main(["--var", root, "--task", task.id, "detail-list"]) == 0
    assert [row["kind"] for row in json.loads(capsys.readouterr().out)] == ["receivable", "receipt", "property"]
    assert main(["--var", root, "--task", task.id, "collection-run-list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in listed] == [run["id"]]
    assert listed[0]["figures"]["collection_rate_current"] == run["result"]["figures"]["collection_rate_current"]
    assert listed[0]["caliber"] == run["caliber"] and listed[0]["as_of"] == "2026-08-31"
    assert main(["--var", root, "--task", task.id, "collection-state"]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["runs"] == listed and len(state["details"]) == 3 and state["caliber"]["effective"]["total_method"] == "bounded"


def test_a_run_needs_no_source_file_beside_the_code(pack, tmp_path, monkeypatch):
    # The packaged app carries bytecode only; 0.10.0 failed every run reading this module's source.
    import foundry.billing_detail as billing_detail

    task, manager, ids = pack
    monkeypatch.setattr(billing_detail, "__file__", str(tmp_path / "missing" / "billing_detail.py"))
    run = manager.collection_run({**ids, "as_of": "2026-08-31"})
    assert run["engine_version"] == billing_detail.COLLECTION_ENGINE_VERSION
    assert "code_sha256" not in run


def test_names_billing_systems_use_are_proposed():
    assert propose_mapping("receipt", ["实收单号", "缴费日期", "账单号", "实收金额"]) == {
        "receipt_id": "实收单号", "date": "缴费日期", "bill_id": "账单号", "amount": "实收金额"}


def test_an_overpaid_bill_and_a_property_listed_twice_inflate_nothing(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="收费明细")
    manager = BillingDetailStore(task, actor="manager")
    receivable = _write(tmp_path / "应收.csv", [RECEIVABLE_HEADER, "B1,P1,住宅物业服务费,2026-08,100,0,100,正常",
                                                "B2,P2,住宅物业服务费,2026-08,100,0,100,正常"], "utf-8")
    # B1 paid twice over (a receipt exported twice); B2 not paid at all.
    receipts = _write(tmp_path / "实收.csv", [RECEIPT_HEADER, "R1,2026-08-10,B1,100,微信,当期", "R2,2026-08-10,B1,100,微信,当期"], "utf-8")
    properties = _write(tmp_path / "房产.csv", ["房产编号,房产类型,产权归属", "P1,洋房,业主", "P2,洋房,业主", "P1,洋房,业主"], "utf-8")
    ids = {"receivable": manager.add("receivable", [receivable], name="应收")["id"],
           "receipt": manager.add("receipt", [receipts], name="实收")["id"],
           "property": manager.add("property", [properties], name="房产")["id"]}
    for detail in ids.values():
        manager.confirm(detail)
    result = manager.collection_run({**ids, "as_of": "2026-08-31"})["result"]
    figures = result["figures"]
    assert (figures["receivable"], figures["collected"]) == ("200.00", "100.00")
    assert figures["collection_rate_total"] == "0.5000"
    # What B1 was paid beyond what it owed is a credit, not a collection of B2.
    assert figures["advance_balance"] == "100.00"
    repeated = next(issue for issue in result["quality"] if issue["code"] == "repeated_properties")
    assert repeated["lines"] == ["房产.csv 第 4 行"]


def test_the_caliber_is_proposed_by_anyone_and_confirmed_only_by_the_manager(pack):
    task, manager, ids = pack
    spec = {**ids, "as_of": "2026-08-31"}
    assert manager.collection_run(spec)["caliber"] == {"version": None, "status": "default", "differs": []}
    assistant = BillingDetailStore(task)
    # 「我们对外报的综合收缴率是本年全部实收除以本年应收」
    proposed = assistant.caliber_propose({"total_method": "all_receipts"}, "集团对外报本年全部实收 ÷ 本年应收")
    assert proposed["proposed"]["by"] == "assistant" and proposed["effective"]["total_method"] == "bounded"
    assert assistant.collection_run(spec)["caliber"]["status"] == "default"
    with pytest.raises(FoundryError, match="only the manager"):
        assistant.caliber_confirm()
    with pytest.raises(FoundryError, match="no excluded_fee"):
        assistant.caliber_propose({"excluded_fee": ["商业租金代收"]})
    confirmed = manager.caliber_confirm()
    assert confirmed["confirmed"]["version"] == 1 and confirmed["proposed"] is None
    run = assistant.collection_run(spec)
    assert run["caliber"] == {"version": 1, "status": "confirmed", "differs": []}
    assert run["result"]["figures"]["collection_rate_total"] == "0.7432"
    # A different setting in the spec is a trial, and says which keys it moved.
    trial = assistant.collection_run({**spec, "total_method": "bounded"})
    assert trial["caliber"] == {"version": 1, "status": "trial", "differs": ["total_method"]}
    assert trial["result"]["figures"]["collection_rate_total"] == "0.4783"
    # The manager may also confirm values of her own; the earlier version is superseded, not lost.
    mine = manager.caliber_confirm(params={"exclude_related": True})
    assert mine["confirmed"]["version"] == 2 and mine["effective"]["total_method"] == "bounded"
    assert [entry["status"] for entry in mine["versions"]] == ["superseded", "confirmed"]


def test_a_fee_item_left_out_takes_its_receipts_with_it(pack):
    _task, manager, ids = pack
    figures = manager.collection_run({**ids, "as_of": "2026-08-31", "excluded_fee_items": ["商办物业服务费"]})["result"]["figures"]
    # B3, B6 and B9 are 商办: 540 receivable, 160 collected, 30 of last year's 30 recovered.
    assert (figures["receivable"], figures["collected"]) == ("540.00", "160.00")
    assert (figures["arrears_opening"], figures["arrears_collected"]) == ("30.00", "30.00")
    assert figures["collection_rate_total"] == "0.3333"
    # Their receipts are set aside with them, not mistaken for prepayments without a bill.
    assert figures["advance_balance"] == "110.00"


def test_the_cli_proposes_and_confirms_the_caliber(pack, tmp_path, capsys):
    task, _manager, _ids = pack
    root = str(tmp_path / "var")
    assert main(["--var", root, "--task", task.id, "collection-caliber-propose", "--spec",
                 json.dumps({"params": {"year_start_month": 7}, "note": "服务年度 7 月起"})]) == 0
    assert json.loads(capsys.readouterr().out)["proposed"]["params"]["year_start_month"] == 7
    assert main(["--var", root, "--task", task.id, "collection-caliber-confirm"]) != 0
    assert "only the manager" in capsys.readouterr().err
    assert main(["--var", root, "--task", task.id, "--actor", "manager", "collection-caliber-confirm", "--version", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["effective"]["year_start_month"] == 7
    assert main(["--var", root, "--task", task.id, "collection-caliber"]) == 0
    assert json.loads(capsys.readouterr().out)["confirmed"]["note"] == "服务年度 7 月起"


def test_a_bill_mixing_kept_and_left_out_fee_items_keeps_its_kept_part(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="收费明细")
    manager = BillingDetailStore(task, actor="manager")
    # One 账单号 per shop per month, with the property fee and the rent collected for the landlord on it.
    receivable = _write(tmp_path / "应收.csv", [RECEIVABLE_HEADER, "B1,S1,商办物业服务费,2026-08,100,0,100,正常",
                                                "B1,S1,商业租金代收,2026-08,300,0,300,正常"], "utf-8")
    receipts = _write(tmp_path / "实收.csv", [RECEIPT_HEADER, "R1,2026-08-10,B1,200,银行,当期"], "utf-8")
    ids = {"receivable": manager.add("receivable", [receivable], name="应收")["id"],
           "receipt": manager.add("receipt", [receipts], name="实收")["id"]}
    for detail in ids.values():
        manager.confirm(detail)
    result = manager.collection_run({**ids, "as_of": "2026-08-31", "excluded_fee_items": ["商业租金代收"]})["result"]
    # The fee is a quarter of the bill, so a quarter of the 200 paid counts against it.
    assert (result["figures"]["receivable"], result["figures"]["collected"]) == ("100.00", "50.00")
    assert result["figures"]["advance_balance"] == "0.00"
    mixed = next(issue for issue in result["quality"] if issue["code"] == "mixed_fee_bills")
    assert (mixed["rows"], mixed["lines"]) == (2, ["应收.csv 第 2 行", "应收.csv 第 3 行"])
    whole = manager.collection_run({**ids, "as_of": "2026-08-31"})["result"]
    assert (whole["figures"]["receivable"], whole["figures"]["collected"]) == ("400.00", "200.00")
    assert not any(issue["code"] == "mixed_fee_bills" for issue in whole["quality"])
