from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def _task(tmp_path: Path):
    task = TaskStore(tmp_path / "var").create(title="公式勾稽")
    return AnalysisStore(task), FinanceStore(task), FinanceStore(task, actor="manager")


def _pack(path: Path, *, closing: int = 150000, reported_dso: float = 103.91) -> Path:
    """A pack with an AR roll-forward, a dashboard and a balance sheet, in 万元."""
    book = Workbook()
    roll = book.active
    roll.title = "07·AR"
    roll.append(["应收账款滚动"])
    roll.append(["项目", "金额"])
    roll.append(["年初余额", 118600])  # B3
    roll.append(["本期新增", 300000])  # B4
    roll.append(["本期收回", 266100])  # B5
    roll.append(["本期核销", 2500])  # B6
    roll.append(["期末余额", closing])  # B7
    kpi = book.create_sheet("01·看板")
    kpi.append(["指标", "本年累计", "上年同期累计", "上年全年"])
    kpi.append(["营业收入", 325644, 331613.0346, 520000])  # row 2
    kpi.append(["应收账款周转天数（天）", reported_dso, 96.2, None])  # row 3
    kpi.append(["综合收缴率", 0.824, 0.848, None])  # row 4
    kpi.append(["信用减值损失", -6000, -5000, None])  # row 5
    bs = book.create_sheet("05·资产负债表")
    bs.append(["项目", "期末", "年初"])
    bs.append(["应收账款", 150000, 118600])  # row 2
    bs.append(["合同资产", 0, 0])  # row 3
    book.save(path)
    return path


def _side(dataset: dict, sheet: str, cells: str, **extra) -> dict:
    return {"dataset_id": dataset["id"], "source_hash": dataset["source_hash"], "sheet": sheet, "range": cells, **extra}


def _rollforward(pack: dict) -> dict:
    return {
        "kind": "formula",
        "formula": "signed_sum",
        "label": "应收滚动：年初 + 新增 − 收回 − 核销 = 期末",
        "unit": "万元",
        "inputs": {
            "opening": _side(pack, "07·AR", "B3"),
            "added": _side(pack, "07·AR", "B4"),
            "collected": _side(pack, "07·AR", "B5", sign=-1),
            "written_off": _side(pack, "07·AR", "B6", sign=-1),
        },
        "right": _side(pack, "07·AR", "B7"),
    }


def test_a_roll_forward_that_does_not_close_is_a_break_and_counts_only_once_confirmed(tmp_path):
    analysis, assistant, manager = _task(tmp_path)
    pack = analysis.add_dataset(_pack(tmp_path / "pack.xlsx", closing=151000), name="月结")
    saved = assistant.finance_controls_save({"control": _rollforward(pack)})["controls"][0]
    assert saved["state"] == "proposed"
    run = assistant.finance_controls_run({"ids": [saved["id"]]})
    (result,) = run["results"]
    assert result["status"] == "break"
    assert result["left"]["value"] == "150000" and result["left"]["formula"] == "signed_sum"
    assert result["left"]["inputs"]["collected"]["sign"] == "-1"
    assert result["difference"] == "-1000"
    assert run["summary"]["break"] == 0
    manager.finance_controls_confirm({"id": saved["id"]})
    assert assistant.finance_controls_run({})["summary"]["break"] == 1


def test_a_roll_forward_that_closes_passes(tmp_path):
    analysis, assistant, _manager = _task(tmp_path)
    pack = analysis.add_dataset(_pack(tmp_path / "pack.xlsx"), name="月结")
    preview = assistant.finance_controls_preview({"control": _rollforward(pack)})["preview"]
    assert preview["status"] == "pass"


def test_dso_is_recomputed_from_cells_and_compared_with_the_reported_days(tmp_path):
    analysis, assistant, _manager = _task(tmp_path)
    pack = analysis.add_dataset(_pack(tmp_path / "pack.xlsx"), name="月结")
    control = {
        "kind": "formula",
        "formula": "dso",
        "label": "应收天数重算",
        "unit": "天",
        "tolerance": "5",
        "inputs": {
            "ar_end": _side(pack, "05·资产负债表", "B2"),
            "contract_assets_end": _side(pack, "05·资产负债表", "B3"),
            "revenue_py_full": _side(pack, "01·看板", "D2"),
            "revenue_py": _side(pack, "01·看板", "C2"),
            "revenue": _side(pack, "01·看板", "B2"),
        },
        "right": _side(pack, "01·看板", "B3"),
    }
    result = assistant.finance_controls_preview({"control": control})["preview"]
    ttm = Decimal("520000") - Decimal("331613.0346") + Decimal("325644")
    assert Decimal(result["left"]["value"]) == Decimal("150000") * 365 / ttm
    # 106.09 days recomputed against 103.91 reported: inside the 5-day tolerance.
    assert result["status"] == "pass"
    assert assistant.finance_controls_preview({"control": {**control, "tolerance": "1"}})["preview"]["status"] == "break"


def test_implied_collection_reads_a_negative_impairment_as_a_loss_and_compares_with_the_reported_rate(tmp_path):
    analysis, assistant, _manager = _task(tmp_path)
    pack = analysis.add_dataset(_pack(tmp_path / "pack.xlsx"), name="月结")
    control = {
        "kind": "formula",
        "formula": "implied_collection",
        "label": "反推回款率对综合收缴率",
        "tolerance": "0.03",
        "inputs": {
            "ar_end": _side(pack, "05·资产负债表", "B2"),
            "ar_begin": _side(pack, "05·资产负债表", "C2"),
            "impairment": _side(pack, "01·看板", "B5"),
            "revenue": _side(pack, "01·看板", "B2"),
        },
        "right": _side(pack, "01·看板", "B4"),
    }
    result = assistant.finance_controls_preview({"control": control})["preview"]
    implied = 1 - (Decimal("31400") + Decimal("6000")) / (Decimal("325644") * Decimal("1.06"))
    assert Decimal(result["left"]["value"]) == implied
    assert result["status"] == "break"  # 89.17% against a reported 82.40%


def test_formula_controls_refuse_inputs_they_do_not_read_and_missing_ones(tmp_path):
    analysis, assistant, _manager = _task(tmp_path)
    pack = analysis.add_dataset(_pack(tmp_path / "pack.xlsx"), name="月结")
    right = _side(pack, "01·看板", "B3")
    with pytest.raises(FoundryError, match="does not read"):
        assistant.finance_controls_save({"control": {
            "kind": "formula", "formula": "dso", "label": "x", "right": right,
            "inputs": {"ar_end": _side(pack, "05·资产负债表", "B2"), "cash": _side(pack, "01·看板", "B2")},
        }})
    with pytest.raises(FoundryError, match="revenue_ttm"):
        assistant.finance_controls_save({"control": {
            "kind": "formula", "formula": "dso", "label": "x", "right": right,
            "inputs": {"ar_end": _side(pack, "05·资产负债表", "B2")},
        }})
    with pytest.raises(FoundryError, match="sign must be"):
        bad = _rollforward(pack)
        bad["inputs"]["opening"]["sign"] = 2
        assistant.finance_controls_save({"control": bad})


def test_a_repeat_save_of_a_formula_control_returns_the_live_one_and_a_new_file_makes_it_stale(tmp_path):
    analysis, assistant, _manager = _task(tmp_path)
    pack = analysis.add_dataset(_pack(tmp_path / "pack.xlsx"), name="月结")
    first = assistant.finance_controls_save({"control": _rollforward(pack)})["controls"][0]
    again = assistant.finance_controls_save({"control": _rollforward(pack)})["controls"][0]
    assert again["id"] == first["id"]
    flipped = _rollforward(pack)
    flipped["inputs"]["written_off"]["sign"] = 1
    assert assistant.finance_controls_save({"control": flipped})["controls"][0]["id"] != first["id"]
    analysis.add_dataset(_pack(tmp_path / "pack2.xlsx", closing=149000), name="月结")
    result = assistant.finance_controls_run({"ids": [first["id"]]})["results"][0]
    assert result["status"] == "stale"
