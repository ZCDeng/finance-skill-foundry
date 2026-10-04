from __future__ import annotations

import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.analysis import REPORT_EXPORT_FORMATS, AnalysisStore
from foundry.cli import main
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.report_documents import MAX_SOURCE_BYTES, REPORT_FORMATS, check_report_source_bytes
from foundry.report_pptx import PPTX_WARNING, report_document_from_pptx
from foundry.report_review import CLOSING_NOTE, extract_report_numbers
from foundry.task import TaskStore

ROOT = Path(__file__).resolve().parents[1]
NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
SLIDE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
SOURCE = {"id": "a" * 32, "name": "月报.pptx", "sha256": "b" * 64, "format": "pptx"}


# --------------------------------------------------------------------------- PPTX fixtures

def _shape(text: str, placeholder: str | None = None) -> str:
    ph = f'<p:ph type="{placeholder}"/>' if placeholder else ""
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="t"/><p:cNvSpPr/><p:nvPr>{ph}</p:nvPr></p:nvSpPr>'
            f'<p:txBody><a:bodyPr/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>')


def _cell(text: str = "", **attrs: str) -> str:
    extra = "".join(f' {key}="{value}"' for key, value in attrs.items())
    body = f"<a:txBody><a:bodyPr/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></a:txBody>" if text else ""
    return f"<a:tc{extra}>{body}</a:tc>"


def _table(rows: list[list[str]]) -> str:
    body = "".join(f"<a:tr>{''.join(row)}</a:tr>" for row in rows)
    return f"<p:graphicFrame><a:graphic><a:graphicData><a:tbl>{body}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"


def _slide(body: str, show: str | None = None) -> str:
    hidden = f' show="{show}"' if show else ""
    return f'<?xml version="1.0" encoding="UTF-8"?><p:sld {NS}{hidden}><p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>'


def _deck(slides: dict[str, str], order: list[tuple[str, str]], extra: dict[str, str] | None = None) -> bytes:
    """`order` is the sldIdLst as (relationship id, target); file names say nothing about the order."""
    listing = "".join(f'<p:sldId id="{256 + index}" r:id="{rid}"/>' for index, (rid, _) in enumerate(order))
    rels = "".join(f'<Relationship Id="{rid}" Type="{SLIDE}" Target="{target}"/>' for rid, target in order)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/presentation.xml", f"<p:presentation {NS}><p:sldIdLst>{listing}</p:sldIdLst></p:presentation>")
        archive.writestr("ppt/_rels/presentation.xml.rels",
                         f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for name, xml in {**slides, **(extra or {})}.items():
            archive.writestr(name, xml)
    return buffer.getvalue()


def _nodes(node):
    yield node
    for child in node.get("content", []) or []:
        if isinstance(child, dict):
            yield from _nodes(child)


def _texts(document: dict) -> list[str]:
    return [node["text"] for node in _nodes({"content": document["content"]}) if node.get("type") == "text"]


def test_pptx_reads_slides_in_presentation_order_with_text_pages() -> None:
    data = _deck(
        {
            "ppt/slides/slide1.xml": _slide(_shape("收入分析", "title") + _shape("营业收入 1,234.56 万元") + _shape("7", "sldNum")),
            "ppt/slides/slide2.xml": _slide(_shape("八月经营汇报", "ctrTitle") + _shape("编制：财务部")),
        },
        # The deck shows slide2.xml first: the order comes from sldIdLst, not from the file names.
        [("rId3", "slides/slide2.xml"), ("rId2", "slides/slide1.xml")],
        extra={"ppt/notesSlides/notesSlide1.xml": _slide(_shape("讲稿备注 999 万元"))},
    )
    result = report_document_from_pptx(data, SOURCE)

    assert result["needsReview"] is True
    assert result["warnings"] == [PPTX_WARNING]
    assert result["title"] == "月报.pptx"
    document = result["document"]
    headings = [(node["attrs"]["level"], "".join(child["text"] for child in node["content"]))
                for node in document["content"] if node["type"] == "heading"]
    assert headings == [(2, "第 1 页"), (3, "八月经营汇报"), (2, "第 2 页"), (3, "收入分析")]
    texts = _texts(document)
    assert "营业收入 1,234.56 万元" in texts
    assert "讲稿备注 999 万元" not in texts  # notes are not part of the slide
    assert "7" not in texts  # slide-number box is layout, not content
    located = [node["attrs"] for node in _nodes({"content": document["content"]})
               if isinstance(node.get("attrs"), dict) and "page" in node["attrs"]]
    assert located and all(isinstance(attrs["page"], str) and attrs["source_id"] == SOURCE["id"] for attrs in located)
    assert {attrs["page"] for attrs in located} == {"1", "2"}


def test_pptx_tables_keep_spans_and_skip_merged_continuations() -> None:
    table = _table([
        [_cell("项目", rowSpan="2"), _cell("2026 年 8 月", gridSpan="2"), _cell(hMerge="1")],
        [_cell(vMerge="1"), _cell("实际"), _cell("预算")],
        [_cell("营业收入"), _cell("1,234.56"), _cell("1,200.00")],
    ])
    data = _deck({"ppt/slides/s.xml": _slide(table)}, [("rId1", "slides/s.xml")])
    document = report_document_from_pptx(data, SOURCE)["document"]

    node = next(node for node in document["content"] if node["type"] == "table")
    rows = node["content"]
    assert [len(row["content"]) for row in rows] == [2, 2, 3]
    first = rows[0]["content"]
    assert first[0]["type"] == "tableHeader" and first[0]["attrs"]["rowspan"] == 2
    assert first[1]["attrs"]["colspan"] == 2
    amount = rows[2]["content"][1]
    assert amount["type"] == "tableCell" and amount["attrs"]["textAlign"] == "right"
    assert amount["attrs"]["page"] == "1"
    # The review reads the grid with the spans: 1,234.56 sits under 「实际」, column 2.
    numbers = extract_report_numbers(document)
    revenue = next(number for number in numbers if number["text"] == "1,234.56")
    assert revenue["location"]["page"] == "1"
    assert (revenue["location"]["row"], revenue["location"]["column"]) == (3, 2)
    assert "实际" in revenue["context"]["period_text"]


def test_pptx_hidden_slides_are_skipped_with_a_warning() -> None:
    data = _deck(
        {"ppt/slides/a.xml": _slide(_shape("公开页")), "ppt/slides/b.xml": _slide(_shape("隐藏页 500 万元"), show="0")},
        [("rId1", "slides/a.xml"), ("rId2", "slides/b.xml")],
    )
    result = report_document_from_pptx(data, SOURCE)
    assert result["warnings"] == [PPTX_WARNING, "第 2 页是隐藏页，未导入。"]
    assert "隐藏页 500 万元" not in _texts(result["document"])


def test_pptx_guards_archive_size_structure_and_dtd() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ppt/presentation.xml", b"0" * (MAX_SOURCE_BYTES * 4 + 1))
    with pytest.raises(FoundryError, match="expands beyond"):
        report_document_from_pptx(buffer.getvalue(), SOURCE)
    with pytest.raises(FoundryError, match="invalid PPTX source archive"):
        report_document_from_pptx(b"not a zip", SOURCE)
    with pytest.raises(FoundryError, match="PPTX has no slides"):
        report_document_from_pptx(_deck({}, []), SOURCE)
    with pytest.raises(FoundryError, match="outside the deck"):
        report_document_from_pptx(_deck({}, [("rId1", "../../docProps/app.xml")]), SOURCE)
    entity = '<?xml version="1.0"?><!DOCTYPE p:sld [<!ENTITY x "x">]><p:sld/>'
    with pytest.raises(FoundryError, match="DTD"):
        report_document_from_pptx(_deck({"ppt/slides/s.xml": entity}, [("rId1", "slides/s.xml")]), SOURCE)
    with pytest.raises(FoundryError, match="PPTX part is missing"):
        report_document_from_pptx(_deck({}, [("rId1", "slides/gone.xml")]), SOURCE)


def test_pptx_is_an_import_format_only(tmp_path: Path, capsys) -> None:
    assert "pptx" in REPORT_FORMATS
    assert "pptx" not in REPORT_EXPORT_FORMATS
    check_report_source_bytes(_deck({"ppt/slides/s.xml": _slide("")}, [("rId1", "slides/s.xml")]), "pptx")

    root = tmp_path / "var"
    task = TaskStore(root).create(title="PPT 导入")
    store = AnalysisStore(task)
    deck = tmp_path / "八月月报.pptx"
    deck.write_bytes(_deck({"ppt/slides/s.xml": _slide(_shape("营业收入 1,234.56 万元"))}, [("rId1", "slides/s.xml")]))
    source = store.add_report_source(deck)["source"]
    assert source["format"] == "pptx" and source["name"] == "八月月报.pptx"
    result = store.read_report_pptx(source["id"])
    assert result["document"]["sources"] == [source]
    with pytest.raises(FoundryError, match="requires an XLSX source"):
        store.read_report_xlsx(source["id"])

    html = tmp_path / "report.html"
    html.write_text("<h1>报告</h1>", encoding="utf-8")
    other = store.add_report_source(html)["source"]
    with pytest.raises(FoundryError, match="report pptx read requires a PPTX source"):
        store.read_report_pptx(other["id"])

    draft = store.save_draft({"title": "导入 PPT", "document": result["document"]})
    exported = tmp_path / "out.pptx"
    exported.write_bytes(b"x")
    with pytest.raises(FoundryError, match="report export format"):
        store.register_report_export(draft["id"], "pptx", exported)

    args = ["--var", str(root), "--task", task.id]
    assert main([*args, "report-pptx-read", "--source", source["id"]]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["needsReview"] is True
    assert printed["warnings"] == [PPTX_WARNING]
    assert str(tmp_path) not in json.dumps(printed, ensure_ascii=False)


# --------------------------------------------------------------------------- number extraction

def _paragraph(text: str, **attrs) -> dict:
    return {"type": "paragraph", **({"attrs": attrs} if attrs else {}), "content": [{"type": "text", "text": text}]}


def _heading(text: str, level: int = 1) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [{"type": "text", "text": text}]}


def _row(*cells: str, header: bool = False) -> dict:
    kind = "tableHeader" if header else "tableCell"
    return {"type": "tableRow", "content": [
        {"type": kind, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]} for text in cells
    ]}


def _report(*content: dict, unit: str = "", sources: list | None = None) -> dict:
    return {
        "schema_version": 1,
        "template_version": "annual-v1",
        "metadata": {"company": "", "period": "", "currency": "", "unit": unit},
        **({"sources": sources} if sources else {}),
        "content": list(content),
    }


def test_extraction_reads_signs_widths_units_and_skips_places() -> None:
    document = _report(
        _heading("第 3 章 经营情况"),
        _paragraph("2026年8月31日，营业收入 1,234.50 万元，净亏损（1,234.56）万元，利润 −12.5 亿元，现金 －3 万。"),
        _paragraph("毛利率３５．２％，较上月下降 (2.1)%。详见第 5 页表 3 及附注 7。"),
        _paragraph("2026-08-31 余额 10 元，2026年1-8月累计 900。（1）（2）"),
        _paragraph("单位：万元"),
        _paragraph("应收账款 1,000.00，员工 120 人，12 月回款 6 家。"),
        _heading("明细", 2),
        {"type": "table", "attrs": {"unit": "千元"}, "content": [
            _row("项目", "2026年", "占比", "科目编码", header=True),
            _row("营业收入", "(1,234)", "35.2", "6001"),
        ]},
        unit="元",
    )
    numbers = {number["text"]: number for number in extract_report_numbers(document)}

    assert list(numbers) == [
        "1,234.50 万元", "（1,234.56）万元", "−12.5 亿元", "－3 万", "３５．２％", "(2.1)%", "10 元", "900",
        "1,000.00", "120 人", "6 家", "(1,234)", "35.2",
    ]
    assert numbers["1,234.50 万元"]["raw"] == Decimal("1234.50") and numbers["1,234.50 万元"]["places"] == 2
    assert numbers["（1,234.56）万元"]["raw"] == Decimal("-1234.56")
    assert numbers["−12.5 亿元"]["raw"] == Decimal("-12.5") and numbers["−12.5 亿元"]["unit"] == "亿元"
    assert numbers["－3 万"]["unit"] == "万"
    assert numbers["３５．２％"]["raw"] == Decimal("35.2") and numbers["３５．２％"]["unit"] == "%"
    assert numbers["(2.1)%"]["raw"] == Decimal("-2.1")
    assert (numbers["900"]["unit"], numbers["900"]["unit_source"]) == ("元", "metadata")
    assert (numbers["1,000.00"]["unit"], numbers["1,000.00"]["unit_source"]) == ("万元", "unit_line")
    assert numbers["120 人"]["unit"] == "人"
    assert (numbers["(1,234)"]["raw"], numbers["(1,234)"]["unit"], numbers["(1,234)"]["unit_source"]) == (
        Decimal("-1234"), "千元", "table")
    # A rate column does not take the table's amount unit.
    assert numbers["35.2"]["unit"] is None
    cell = numbers["(1,234)"]["location"]
    assert cell == {"section": "第 3 章 经营情况 / 明细", "kind": "table_cell", "table_index": 1, "row": 2, "column": 2}
    assert all(len(number["excerpt"]) <= 80 for number in numbers.values())
    assert "营业收入 1,234.50 万元" in numbers["1,234.50 万元"]["excerpt"]


# --------------------------------------------------------------------------- review against the task

def _month_pack(path: Path, cost: float = 800) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "利润表"
    sheet.append(["2026年8月利润表"])
    sheet.append(["单位：万元"])
    sheet.append(["项目", "本月实际", "本年累计", "预算"])
    sheet.append(["营业收入", 1234.5678, 9876.54, 1200])
    sheet.append(["营业成本", cost, 6000, 790])
    sheet.append(["毛利率", 0.352, 0.3925, 0.34])
    detail = workbook.create_sheet("明细")
    detail.append(["门店", "收入（元）"])
    detail.append(["一店", 12345600])
    workbook.save(path)
    return path


@pytest.fixture
def pack(tmp_path: Path):
    task = TaskStore(tmp_path / "var").create(title="外部报告复核")
    analysis = AnalysisStore(task)
    dataset = analysis.add_dataset(_month_pack(tmp_path / "月结.xlsx"), name="月结.xlsx")
    return task, analysis, dataset


def _by_text(review: dict) -> dict[str, dict]:
    return {item["text"]: item for item in review["items"]}


def test_review_classifies_each_status_against_the_workbook(pack) -> None:
    task, _, dataset = pack
    store = FinanceStore(task, actor="manager")
    document = _report(
        _heading("八月经营分析"),
        _paragraph("本年累计营业收入 9,876.54 万元，本月营业收入 1,234.57 万元。"),
        _paragraph("营业成本本月实际 820 万元。毛利率 35.2%。一店收入 1,234.56 万元。"),
        _paragraph("营业成本预算 790 元。其他 77 万元。"),
    )
    review = store.report_review({"document": document})
    items = _by_text(review)

    assert items["9,876.54 万元"]["status"] == "match"
    best = items["9,876.54 万元"]["candidates"][0]
    assert best == {"kind": "workbook", "dataset_id": dataset["id"], "source_hash": dataset["source_hash"],
                    "sheet": "利润表", "range": "C4", "label": "营业收入 · 本年累计", "value": "9876.54", "unit": "万元"}
    assert items["1,234.57 万元"]["status"] == "match_rounded"
    assert "2 位小数" in items["1,234.57 万元"]["note"]
    assert items["1,234.56 万元"]["status"] == "match"  # 12,345,600 元 in 明细, the same amount in 万元
    assert items["1,234.56 万元"]["candidates"][0]["range"] == "B2"
    assert items["35.2%"]["status"] == "match"
    assert items["35.2%"]["candidates"][0]["range"] == "B6"

    mismatch = items["820 万元"]
    assert mismatch["status"] == "mismatch"
    assert (mismatch["compared_value"], mismatch["difference"]) == ("800", "20")
    assert mismatch["candidates"][0]["range"] == "B5"
    scaled = items["790 元"]
    assert scaled["status"] == "match_scaled"
    assert "10000 倍" in scaled["note"]
    assert items["77 万元"]["status"] == "needs_review"

    summary = review["summary"]
    assert summary["status"] == "needs_attention"
    assert (summary["total"], summary["match"], summary["match_rounded"], summary["match_scaled"],
            summary["mismatch"], summary["needs_review"]) == (7, 3, 1, 1, 1, 1)

    issues = {issue["original_text"]: issue for issue in review["issues"]}
    assert set(issues) == {"820 万元", "790 元", "77 万元"}
    assert issues["820 万元"]["code"] == "report_review_mismatch"
    assert issues["820 万元"]["location"] == {"dataset_id": dataset["id"], "sheet": "利润表", "range": "B5",
                                              "source_hash": dataset["source_hash"]}
    assert "相差 20 万元" in issues["820 万元"]["message"]
    assert issues["790 元"]["code"] == "report_review_scaled"
    assert issues["77 万元"]["code"] == "report_review_unmatched" and "location" not in issues["77 万元"]
    assert all(issue["excerpt"] and issue["business_key"] for issue in issues.values())
    assert review["closing_note"] == CLOSING_NOTE


def test_review_passes_only_when_every_number_ties_and_flags_ocr_text(pack) -> None:
    task, _, _ = pack
    store = FinanceStore(task, actor="manager")
    clean = store.report_review({"document": _report(_paragraph("本年累计营业收入 9,876.54 万元。"))})
    assert clean["summary"]["status"] == "pass"

    ocr = store.report_review({"document": _report(_heading("OCR 补充草稿", 2), _paragraph("营业收入 9,876.54 万元。"))})
    item = ocr["items"][0]
    assert item["status"] == "needs_review"
    assert item["note"].startswith("OCR 识别的文字没有页码")
    assert ocr["summary"]["status"] == "needs_attention"

    empty = store.report_review({"document": _report(_paragraph("本月经营平稳。"))})
    assert empty["summary"] == {"status": "needs_attention", "total": 0, "match": 0, "match_rounded": 0,
                                "match_scaled": 0, "mismatch": 0, "needs_review": 0, "needs_review_not_amount": 0}
    assert "文稿里没有找到可比对的数字。" in empty["notes"]


def _variance_task(tmp_path: Path):
    task = TaskStore(tmp_path / "var").create(title="计算结果复核")
    analysis = AnalysisStore(task)
    bindings = {}
    for scenario, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15])):
        path = tmp_path / f"{scenario}.json"
        path.write_text(json.dumps([
            {"account_code": code, "management_account": account, "amount": amount}
            for code, account, amount in zip(("6001", "6401", "6601"), ("revenue", "cost", "expense"), amounts)
        ]))
        bindings[scenario] = analysis.add_dataset(path, name=scenario)["id"]
    store = FinanceStore(task, actor="manager")
    context = store.save_context({"bindings": bindings, "scopes": {
        alias: {"ledger": "L1", "organization": "O1", "period": "2026-09", "currency": "CNY", "unit": "万元",
                "scenario": alias} for alias in bindings}})
    run = store.explain_variance({"context_id": context["id"]})
    return task, analysis, store, bindings, run


def test_review_matches_calculation_facts_and_table_snapshots(tmp_path: Path) -> None:
    _, _, store, bindings, _ = _variance_task(tmp_path)
    review = store.report_review({"document": _report(_paragraph("收入实际 120 万元，预算 100 万元，差异 20 万元。"))})
    items = _by_text(review)
    assert [items[text]["status"] for text in ("120 万元", "100 万元", "20 万元")] == ["match"] * 3
    assert items["20 万元"]["candidates"][0]["kind"] == "fact"
    assert items["20 万元"]["candidates"][0]["label"] == "收入 · 差异 2026-09"
    assert items["100 万元"]["candidates"][0]["dataset_id"] in {bindings["budget"], bindings["actual"]}
    # Account codes are DECIMAL in the snapshot but never an amount to compare with.
    codes = store.report_review({"document": _report(_paragraph("科目 6001 收入 6,001 万元。"))})
    assert all(candidate.get("label") != "收入 · account_code"
               for item in codes["items"] for candidate in item["candidates"])
    assert all(item["status"] == "needs_review" for item in codes["items"])


def test_review_ignores_superseded_snapshots(pack, tmp_path: Path) -> None:
    task, analysis, old = pack
    newer = analysis.add_dataset(_month_pack(tmp_path / "更正.xlsx", cost=820), name="月结.xlsx")
    store = FinanceStore(task, actor="manager")
    review = store.report_review({"document": _report(_paragraph("营业成本本月实际 820 万元，预算 790 万元。"))})
    items = _by_text(review)
    assert items["820 万元"]["status"] == "match"
    assert items["820 万元"]["candidates"][0]["dataset_id"] == newer["id"]
    cited = {candidate["dataset_id"] for item in review["items"] for candidate in item["candidates"]}
    assert old["id"] not in cited
    assert any("已被新版本取代" in note for note in review["notes"])


def test_review_reads_only_snapshots_the_session_may_see(tmp_path: Path) -> None:
    task, analysis, store, bindings, run = _variance_task(tmp_path)
    document = _report(_paragraph("收入实际 120 万元。"))
    assert store.report_review({"document": document})["items"][0]["status"] == "match"

    narrow = FinanceStore(task, actor="manager", snapshot_ids=[bindings["budget"]])
    review = narrow.report_review({"document": document})
    assert review["items"][0]["status"] == "needs_review"
    cited = {candidate.get("dataset_id") for item in review["items"] for candidate in item["candidates"]}
    assert bindings["actual"] not in cited

    draft = analysis.save_draft({"title": "九月月报", "run_ids": [run["id"]], "document": document})
    assert store.report_review({"draft_id": draft["id"]})["summary"]["status"] == "pass"
    with pytest.raises(FoundryError, match="outside this session context"):
        narrow.report_review({"draft_id": draft["id"]})


def test_review_record_is_its_own_immutable_record_and_leaves_the_draft_alone(pack, tmp_path: Path) -> None:
    task, analysis, _ = pack
    html = tmp_path / "八月月报.html"
    html.write_text("<p>营业收入 9,876.54 万元</p>", encoding="utf-8")
    source = analysis.add_report_source(html)["source"]
    store = FinanceStore(task, actor="manager")
    draft = analysis.save_draft({
        "title": "八月月报",
        "review_status": "unreviewed",
        "document": _report(_paragraph("营业收入 9,876.54 万元。", source_id=source["id"], page="2"), sources=[source]),
    })

    first = store.report_review({"draft_id": draft["id"]})
    assert (first["origin"], first["draft_id"], first["draft_content_hash"]) == ("draft", draft["id"], draft["content_hash"])
    assert first["domain"] == "foundry.finance.report_reviews.v1"
    assert first["sources"] == [{"id": source["id"], "name": "八月月报.html", "format": "html", "sha256": source["sha256"]}]
    assert first["items"][0]["location"]["page"] == "2"
    assert analysis.get_draft(draft["id"]) == draft

    second = store.report_review({"draft_id": draft["id"]})
    assert second["id"] != first["id"] and second["seq"] > first["seq"]
    listed = store._list("report_reviews")
    assert [row["id"] for row in listed] == [first["id"], second["id"]]
    assert listed[0] == first
    with pytest.raises(FoundryError, match="immutable"):
        analysis._write(store._path("report_reviews", first["id"]), {**first, "summary": {}})
    assert str(tmp_path) not in json.dumps(first, ensure_ascii=False)


def test_review_of_an_import_coerces_numeric_pages_and_validates_the_spec(pack, tmp_path: Path) -> None:
    task, analysis, _ = pack
    pdf = tmp_path / "月报.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    source = analysis.add_report_source(pdf)["source"]
    store = FinanceStore(task, actor="manager")
    document = _report(_paragraph("营业收入 9,876.54 万元。", source_id=source["id"], page=3), sources=[source])
    review = store.report_review({"document": document})
    assert review["origin"] == "import"
    assert review["items"][0]["location"]["page"] == "3"
    assert review["items"][0]["status"] == "match"

    for spec, message in (
        ([], "must be an object"),
        ({}, "either a draft_id or a document"),
        ({"draft_id": "a" * 32, "document": document}, "either a draft_id or a document"),
    ):
        with pytest.raises(FoundryError, match=message):
            store.report_review(spec)
    plain = analysis.save_draft({"title": "纯文本", "body": "营业收入 9,876.54 万元。"})
    with pytest.raises(FoundryError, match="structured document"):
        store.report_review({"draft_id": plain["id"]})


def test_report_review_cli_reads_a_spec_file(pack, tmp_path: Path, capsys) -> None:
    task, _, dataset = pack
    args = ["--var", str(tmp_path / "var"), "--task", task.id]
    spec = tmp_path / "review.json"
    spec.write_text(json.dumps({"document": _report(_paragraph("营业成本本月实际 820 万元。"))}, ensure_ascii=False),
                    encoding="utf-8")
    assert main([*args, "report-review", "--spec-file", str(spec)]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["summary"]["mismatch"] == 1
    assert record["issues"][0]["location"]["dataset_id"] == dataset["id"]
    assert record["bindings"] == {"source0": dataset["id"]}

    inline = json.dumps({"document": _report(_paragraph("本年累计营业收入 9,876.54 万元。"))}, ensure_ascii=False)
    assert main([*args, "report-review", "--spec", inline]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["status"] == "pass"


def test_report_review_is_not_an_assistant_tool() -> None:
    for name in ("client.js", "finance-tools.js"):
        text = (ROOT / "dsh-plugin" / name).read_text(encoding="utf-8")
        assert "report-review" not in text and "report-pptx-read" not in text
