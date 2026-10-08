"""Files as Chinese finance systems write them: a GBK CSV reads, an old .xls is answered with what to do."""

from __future__ import annotations

import pytest

from foundry.analysis import AnalysisStore
from foundry.analysis_data import decode_text, parse_source
from foundry.errors import FoundryError
from foundry.task import TaskStore

ROWS = "科目名称,本月金额\n主营业务收入,1200.50\n管理费用,300\n"


@pytest.mark.parametrize("encoding", ["gbk", "gb18030", "utf-8", "utf-8-sig"])
def test_a_csv_reads_the_same_in_every_encoding_a_chinese_erp_writes(encoding):
    parsed = parse_source(ROWS.encode(encoding), ".csv", {})
    assert [column["name"] for column in parsed["schema"]][:2] == ["科目名称", "本月金额"]
    assert parsed["rows"][0]["科目名称"] == "主营业务收入"
    assert parsed["transformation"].get("encoding", "utf-8") == ("gb18030" if encoding in {"gbk", "gb18030"} else "utf-8")


def test_a_gbk_note_reads_as_background():
    parsed = parse_source("一、华南写字楼提前退场。\n".encode("gbk"), ".txt", {})
    assert parsed["paragraphs"][0]["text"] == "一、华南写字楼提前退场。"
    assert parsed["transformation"]["encoding"] == "gb18030"


def test_an_old_xls_is_refused_with_what_to_do(tmp_path):
    source = tmp_path / "科目余额表.xls"
    source.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")  # the OLE header every .xls starts with
    analysis = AnalysisStore(TaskStore(tmp_path / "var").create(title="导入"))
    with pytest.raises(FoundryError, match=r"\.xls .*save it as \.xlsx"):
        analysis.add_dataset(source, name=source.name)


def test_a_gbk_file_that_also_happens_to_be_valid_utf8_still_reads_as_gbk():
    data = "目录,一\n".encode("gbk")
    data.decode("utf-8")  # the trap: these bytes are valid UTF-8 too
    assert decode_text(data) == ("目录,一\n", "gb18030")
    # Real UTF-8 with Chinese in it, or with a BOM, is never second-guessed.
    assert decode_text("目录,Ŀ¼\n".encode("utf-8")) == ("目录,Ŀ¼\n", "utf-8")
    assert decode_text("\ufeffŀ\n".encode("utf-8")) == ("ŀ\n", "utf-8")
