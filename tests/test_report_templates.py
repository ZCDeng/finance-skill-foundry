from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.report_documents import report_document_markdown, validate_report_document
from foundry.report_templates import apply_excel_named_ranges, bundled_templates, excel_brief_template_bytes
from foundry.task import TaskStore

SCOPE = {
    "ledger": "service-co",
    "organization": "华东",
    "period": "2026-08",
    "currency": "CNY",
    "unit": "万元",
    "scenario": "actual",
}


def _finance(tmp_path: Path):
    task = TaskStore(tmp_path / "var").create(title="公司模板")
    return FinanceStore(task), task


def test_cf16_management_brief_keeps_annual_v1_and_hashes_template_id(tmp_path: Path) -> None:
    service, _task = _finance(tmp_path)
    listed = {row["template_id"]: row for row in service.report_template_list({})["templates"]}
    assert listed["management-brief-v1"] == {"template_id": "management-brief-v1", "label": "经营简报", "kind": "word"}
    assert set(listed["management-brief-v1"]) == {"template_id", "label", "kind"}
    draft = service.report_template_apply({"template_id": "management-brief-v1", "scope": SCOPE})["draft"]
    document = draft["document"]
    assert document["template_version"] == "annual-v1"
    assert document["template_id"] == "management-brief-v1"
    assert "经营简报" in draft["body"]
    assert "账套：service-co" in draft["body"]
    assert "组织：华东" in draft["body"]
    assert "期间：2026-08" in draft["body"]
    assert "单位：万元" in draft["body"]
    assert "template_id" not in draft["body"]
    missing = validate_report_document(
        {
            "schema_version": 1,
            "template_version": "annual-v1",
            "template_id": "management-brief-v1",
            "metadata": {},
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "空页眉"}]}],
        }
    )
    markdown = report_document_markdown(missing)
    assert "账套：未声明" in markdown
    assert "组织：未声明" in markdown
    clone = dict(document)
    clone["template_id"] = "variance-note-v1"
    changed = _finance(tmp_path)[1]
    other = AnalysisStore(TaskStore(tmp_path / "var").create(title="哈希对照"))
    first = other.save_draft({"title": "经营简报", "document": document})
    second = other.save_draft({"title": "经营简报", "document": clone})
    assert first["content_hash"] != second["content_hash"]
    assert "template_id" in first["document"]


def test_cf17_excel_named_ranges_write_g1_amounts_as_summable_numbers() -> None:
    data = apply_excel_named_ranges(excel_brief_template_bytes())
    workbook = load_workbook(io.BytesIO(data))
    sheet = workbook["Brief"]
    assert sheet["B2"].value == Decimal("30")
    assert sheet["B2"].data_type == "n"
    assert sheet["B3"].value == Decimal("20")
    assert sheet["B4"].value == Decimal("-10")
    assert sheet["B5"].value == Decimal("-5")
    assert sheet["B6"].value == "=SUM(B2:B5)"
    workbook.close()


def test_cf18_apply_writes_new_draft_and_rejects_unknown_ids(tmp_path: Path) -> None:
    service, task = _finance(tmp_path)
    analysis = AnalysisStore(task)
    original = analysis.save_draft(
        {
            "title": "旧稿",
            "document": {
                "schema_version": 1,
                "template_version": "annual-v1",
                "metadata": {"period": "2026-01"},
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "旧正文留着"}]}],
            },
        }
    )
    before = dict(original)
    applied = service.report_template_apply({"template_id": "management-brief-v1", "scope": SCOPE})["draft"]
    assert applied["id"] != original["id"]
    reread = analysis.get_draft(original["id"])
    assert reread["body"] == before["body"]
    assert reread["content_hash"] == before["content_hash"]
    assert "旧正文留着" in reread["body"]
    with pytest.raises(FoundryError, match="unknown report template"):
        service.report_template_apply({"template_id": "not-a-company-file"})


def test_cf18f_foreign_task_cannot_list_or_apply_published_snapshot(tmp_path: Path) -> None:
    service, task = _finance(tmp_path)
    source = tmp_path / "company.docx"
    source.write_bytes(_minimal_docx())
    published = service.report_template_publish({"path": str(source), "label": "本公司简报"})
    assert published["kind"] == "word"
    listed = service.report_template_list({})["templates"]
    assert any(row["template_id"] == published["template_id"] for row in listed)
    for row in listed:
        blob = " ".join(row.values())
        assert "http" not in blob
        assert "/" not in blob or row["kind"] in {"word", "excel"}
        assert "path" not in row
        assert "bytes" not in row
    other = FinanceStore(TaskStore(tmp_path / "var").create(title="外任务"))
    foreign_ids = {row["template_id"] for row in other.report_template_list({})["templates"]}
    assert published["template_id"] not in foreign_ids
    with pytest.raises(FoundryError, match="unknown report template"):
        other.report_template_apply({"template_id": published["template_id"]})
    applied = service.report_template_apply({"template_id": published["template_id"], "scope": SCOPE})
    assert applied["draft"]["document"]["template_id"] == published["template_id"]


def test_cf34_publish_rejects_pptx(tmp_path: Path) -> None:
    service, _task = _finance(tmp_path)
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"PK\x03\x04ppt/presentation.xml fake")
    with pytest.raises(FoundryError, match="pptx"):
        service.report_template_publish({"path": str(pptx)})


def test_bundled_templates_are_metadata_only() -> None:
    for row in bundled_templates():
        assert set(row) == {"template_id", "label", "kind"}


def _minimal_docx() -> bytes:
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("word/document.xml", "<w:document></w:document>")
    return buffer.getvalue()
