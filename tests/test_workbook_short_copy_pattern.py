"""Review hints for a stalled final reference in a short copied formula run."""

from __future__ import annotations

import io
import re
import zipfile

import pytest
from openpyxl import Workbook

from foundry.workbook_health import check_workbook


def _xlsx(formulas: dict[str, str]) -> bytes:
    book = Workbook()
    for cell, formula in formulas.items():
        book.active[cell] = formula
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def _check(formulas: dict[str, str]) -> dict:
    result = check_workbook(_xlsx(formulas))
    assert result["status"] == "checked"
    return result


@pytest.mark.parametrize(("formulas", "code", "cell", "example"), [
    ({"B1": "=A1*2", "B2": "=A2*2", "B3": "=A2*2"},
     "inconsistent_column_formula", "B3", "B2"),
    ({"B2": "=B1*2", "C2": "=C1*2", "D2": "=C1*2"},
     "inconsistent_row_formula", "D2", "C2"),
    ({"E8": "=B8*C8", "E9": "=B9*C9", "E10": "=B9*C9"},
     "inconsistent_column_formula", "E10", "E9"),
])
def test_short_run_reports_a_stalled_final_current_row_or_column_reference(
    formulas: dict[str, str], code: str, cell: str, example: str,
) -> None:
    result = _check(formulas)
    issues = [issue for issue in result["issues"] if issue["code"].startswith("inconsistent_")]
    assert len(issues) == 1
    issue = issues[0]
    assert issue["code"] == code
    assert issue["count"] == 1
    assert [(sample["cell"], sample["formula"], sample["detail"]) for sample in issue["samples"]] == [
        (cell, formulas[cell], example),
    ]


def test_short_shared_run_compares_the_predecessor_at_its_actual_cell() -> None:
    source = _xlsx({"B1": "=A1*2", "B2": "=A2*2", "B3": "=A2*2"})
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as archive, zipfile.ZipFile(output, "w") as rewritten:
        for item in archive.infolist():
            data = archive.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                xml = data.decode()
                for cell, formula in {
                    "B1": '<f t="shared" ref="B1:B2" si="0">A1*2</f>',
                    "B2": '<f t="shared" si="0"/>',
                }.items():
                    xml, count = re.subn(rf'<c r="{cell}">.*?</c>', f'<c r="{cell}">{formula}<v/></c>', xml)
                    assert count == 1
                data = xml.encode()
            rewritten.writestr(item, data)
    result = check_workbook(output.getvalue())
    issue = next(issue for issue in result["issues"] if issue["code"] == "inconsistent_column_formula")
    assert issue["count"] == 1
    assert [(sample["cell"], sample["detail"]) for sample in issue["samples"]] == [("B3", "B2")]


@pytest.mark.parametrize("formulas", [
    pytest.param({"B1": "=A1*2", "B2": "=A2*2", "B3": "=A3*2"}, id="correct-copy"),
    pytest.param({"B1": "=A1*2", "B2": "=A2*2", "B3": "=SUM(B1:B2)"}, id="subtotal"),
    pytest.param({"B1": "=A1*2", "B2": "=A2*2", "B3": "=B2/B1"}, id="ratio"),
    pytest.param({"B1": "=Opening!B1", "B2": "=A2*2", "B3": "=A3*2"}, id="opening"),
    pytest.param({"B3": "=SUM(A1:A2)", "B4": "=SUM(A2:A3)", "B5": "=SUM(A2:A3)"},
                 id="rolling-window"),
    pytest.param({"B3": "=A2*2", "B4": "=A3*2", "B5": "=A3*2"}, id="prior-period"),
    pytest.param({"B2": "=B1+A2", "B3": "=B2+A3", "B4": "=B2+A3"}, id="running-balance"),
    pytest.param({"B1": "=A$1*2", "B2": "=A$1*2", "B3": "=A$2*2"}, id="absolute-row"),
    pytest.param({"B1": "=$A1*2", "B2": "=$A2*2", "B3": "=$A2*2"}, id="absolute-column"),
    pytest.param({"B1": "=A1*$D$1", "B2": "=A2*$D$1", "B3": "=A2*$D$1"}, id="absolute-rate"),
    pytest.param({"B1": "=A1*2", "B3": "=A3*2", "B4": "=A3*2"}, id="gapped-run"),
    pytest.param({"B1": "=A1*2", "B2": "=A2*2", "B4": "=A2*2"}, id="gapped-tail"),
    pytest.param({"B10": "=SUM(B2:B9)", "C10": "=SUM(C2:C9)", "D10": "=SUM(D2:D8)"},
                 id="short-range-change"),
    pytest.param({"B1": "=A1*2", "B2": "=A2*2", "B3": "=A3*100"}, id="changed-method"),
    pytest.param({"B1": "=A1*2", "B2": "=A2*2", "B3": "=C3*2"}, id="changed-source"),
    pytest.param({"B1": "=A1*2", "B2": "=A1*2", "B3": "=A3*2"}, id="interior-anomaly"),
    pytest.param({"B1": "=A1*2", "B2": "=A2*2", "B3": "=A2*2", "B4": "=SUM(B1:B3)"},
                 id="insufficient-majority-in-longer-run"),
    pytest.param({"B1": "=SUM(1:1)", "B2": "=SUM(2:2)", "B3": "=SUM(2:2)"}, id="whole-row"),
    pytest.param({"B1": "=Other!A1*2", "B2": "=Other!A2*2", "B3": "=Other!A2*2"},
                 id="other-sheet"),
    pytest.param({"B1": "=OFFSET(A1,0,1)", "B2": "=OFFSET(A2,0,1)", "B3": "=OFFSET(A2,0,1)"},
                 id="dynamic-reference"),
],)
def test_ambiguous_short_runs_keep_the_existing_conservative_threshold(formulas: dict[str, str]) -> None:
    result = _check(formulas)
    assert not [issue for issue in result["issues"] if issue["code"].startswith("inconsistent_")]
