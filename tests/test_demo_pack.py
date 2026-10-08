"""The demo pack generator still plants the differences the demo walks through.

`tests/fixtures/demo_pack/build_demo.py` writes the Huachen demo files; its README lists what each
planted difference should make FA Foundry report. This runs the generator once and checks the ones the
controls engine reads directly, so a change to the generator cannot quietly remove them. The app ships
the same files in `foundry/resources/demo_pack`; the last tests hold the two copies cell for cell, so a
generator change that is not regenerated into the bundle fails here.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook

from foundry.analysis import AnalysisStore
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore
from foundry.workbook_health import check_workbook

GENERATOR = Path(__file__).parent / "fixtures" / "demo_pack" / "build_demo.py"
BUNDLED = Path(__file__).parents[1] / "foundry" / "resources" / "demo_pack"


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("demo") / "演示版"
    subprocess.run([sys.executable, "-I", str(GENERATOR), str(out)], check=True, capture_output=True)
    return out


def test_demo_pack_plants_the_documented_differences(generated: Path, tmp_path: Path) -> None:
    out = generated
    names = sorted(path.name for path in out.iterdir())
    assert any("2026年09月_月结" in name for name in names)
    assert "演示说明.md" in names

    task = TaskStore(tmp_path / "var").create(title="演示套表")
    analysis = AnalysisStore(task)
    store = FinanceStore(task)
    pack = analysis.add_dataset(next(out.glob("*2026年08月_月结*.xlsx")), name="月结")
    budget = analysis.add_dataset(next(out.glob("*全面预算与合同台账.xlsx")), name="预算")

    def side(dataset, sheet, cell):
        return {"dataset_id": dataset["id"], "source_hash": dataset["source_hash"], "sheet": sheet, "range": cell}

    # F-01: the bill-year bad-debt detail does not add up to its total.
    suggestions = store.finance_controls_propose({})["suggestions"]
    f01 = [s for s in suggestions if s["control"]["label"].startswith("08·AR收缴率与欠费 · 已计提坏账")]
    assert f01 and f01[0]["preview"]["status"] == "break" and Decimal(f01[0]["preview"]["difference"]) == 11655

    def preview(control):
        return store.finance_controls_preview({"control": control})["preview"]

    # F-02: the contract ledger's collections fall short of the month-close regional total.
    f02 = preview({"kind": "tie_out", "label": "F-02", "left": side(budget, "11·物业服务合同台账", "T5:T604"),
                   "right": side(pack, "08·AR收缴率与欠费", "C11"), "tolerance": "1"})
    assert f02["status"] == "break" and Decimal(f02["difference"]).quantize(Decimal("0.01")) == Decimal("-2793.28")

    # The AR roll-forward on 07 overshoots its closing balance by 1,200.
    sheet = "07·AR账龄及减值"
    roll = preview({"kind": "formula", "formula": "signed_sum", "label": "应收滚动",
                    "inputs": {"begin": side(pack, sheet, "B34"), "new": side(pack, sheet, "B35"),
                               "collected": side(pack, sheet, "B36"), "written_off": side(pack, sheet, "B38")},
                    "right": side(pack, sheet, "B39")})
    assert roll["status"] == "break" and Decimal(roll["difference"]) == 1200

    # The long tables carry their one-sided rows and the price/quantity slip.
    book = load_workbook(next(out.glob("*明细长表.xlsx")), data_only=True)
    budget_rows = list(book["预算长表"].iter_rows(min_row=2, values_only=True))
    actual_rows = list(book["实际长表"].iter_rows(min_row=2, values_only=True))
    assert any(row[1] == "西南区域" for row in budget_rows) and not any(row[1] == "西南区域" for row in actual_rows)
    assert any(row[6] == "non_operating" for row in actual_rows)
    assert any(row[7] < 0 for row in budget_rows)
    office = next(row for row in book["量价实际"].iter_rows(min_row=2, values_only=True) if row[6] == "写字楼")
    assert round(office[9] - office[7] * office[8], 2) == 260
    wrong = list(book["收款计划_含错误行"].iter_rows(min_row=2, values_only=True))
    assert wrong[0][3] == "forecast" and wrong[0][1] <= "2026-09-06"


def test_the_formula_sample_carries_its_cache_without_excel(generated: Path) -> None:
    health = check_workbook(next(generated.glob("*公式体检样本.xlsx")).read_bytes())
    assert sorted(issue["code"] for issue in health["issues"]) == [
        "cached_error", "error_in_formula", "external_links", "external_reference", "hardcoded_number",
        "hidden_sheets", "inconsistent_column_formula", "inconsistent_row_formula", "volatile_function",
    ]


def _same(value):
    # Python 3.12 made sum() of floats exact, so the last bits of a generated figure depend on
    # the interpreter; ten significant digits are what any reader of the pack can see.
    return float(f"{value:.10g}") if isinstance(value, float) else value


def _cells(path: Path) -> dict:
    """Every cell's formula (or value) and its cached value: what a reader of the file sees."""
    formulas, cached = load_workbook(path), load_workbook(path, data_only=True)
    return {
        (sheet.title, sheet.sheet_state, cell.coordinate): (_same(cell.value), _same(cached[sheet.title][cell.coordinate].value))
        for sheet in formulas.worksheets for row in sheet.iter_rows() for cell in row if cell.value is not None
    }


def test_the_bundled_pack_is_what_the_generator_writes(generated: Path) -> None:
    import json

    manifest = json.loads((BUNDLED / "pack.json").read_text(encoding="utf-8"))
    listed = {*manifest["practice"], *manifest["next_month"], manifest["report"], manifest["notes"]}
    assert listed == {path.name for path in generated.iterdir()} == {path.name for path in BUNDLED.iterdir()} - {"pack.json"}
    for name in sorted(listed):
        made, shipped = generated / name, BUNDLED / name
        if name.endswith(".xlsx"):
            assert _cells(made) == _cells(shipped), f"{name} differs: regenerate foundry/resources/demo_pack"
        elif name.endswith(".docx"):
            read = lambda path: zipfile.ZipFile(path).read("word/document.xml")  # noqa: E731
            assert read(made) == read(shipped), name
        else:
            assert made.read_bytes() == shipped.read_bytes(), name
