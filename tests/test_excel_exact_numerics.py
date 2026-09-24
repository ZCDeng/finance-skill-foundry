from __future__ import annotations

import io
import re
import zipfile
from decimal import Decimal

from openpyxl import Workbook

from foundry.analysis_data import excel_number, read_exact_numerics


def _xlsx_with_literals(literals: dict[str, str]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "预算"
    for coordinate in literals:
        sheet[coordinate] = 1
    buffer = io.BytesIO()
    book.save(buffer)
    source = zipfile.ZipFile(io.BytesIO(buffer.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                xml = data.decode()
                for coordinate, literal in literals.items():
                    xml = re.sub(
                        rf'(<c r="{coordinate}"[^>]*>\s*<v>)[^<]*(</v>)',
                        rf"\g<1>{literal}\g<2>",
                        xml,
                    )
                data = xml.encode()
            target.writestr(item, data)
    return out.getvalue()


def test_seventeen_digit_literal_reads_as_shortest_form_of_the_same_double():
    assert excel_number("64441.376900000001") == Decimal("64441.3769")
    assert excel_number("527999.9999000001") == Decimal("527999.9999")
    assert float("64441.376900000001") == float("64441.3769")


def test_round_trip_literals_keep_their_digits():
    for literal in ("3185", "6984.7414", "0.1", "-12012.0347", "1E-7"):
        value = excel_number(literal)
        assert value == Decimal(literal)
        assert str(value) == str(Decimal(literal))


def test_distinct_doubles_stay_distinct():
    assert excel_number("64441.3769") != excel_number("64441.37690000002")


def test_workbook_reader_uses_the_stored_double_not_its_serialisation_tail():
    data = _xlsx_with_literals({"B2": "64441.376900000001", "C2": "3185", "D2": "527999.9999000001"})

    values = read_exact_numerics(data, "预算")

    assert values["B2"] == Decimal("64441.3769")
    assert values["C2"] == Decimal("3185")
    assert values["D2"] == Decimal("527999.9999")
