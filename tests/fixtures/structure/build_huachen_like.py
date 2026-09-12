"""Build 华宸-shaped workbooks for structure-proposal tests.

The real month-end packs are customer files. These generators reproduce their
*shape* — a three-row title area, a header on row 4, section rows, subtotal and
check-note footers, 借方/贷方 column pairs, and voucher numbers that appear only
on the first line of each voucher — with synthetic amounts that add up to the
figures the plan's success criteria name.
"""

from __future__ import annotations

import io
from pathlib import Path

from openpyxl import Workbook

TITLE = "华宸物业服务集团股份有限公司"
SUBTITLE = "华宸物业  |  2026年08月  |  单位：元  |  损益类科目每月结转至本年利润，故期初、期末余额为零"

# 本期发生额 that reproduce the plan's success-criteria totals:
#   revenue 414,696,250 · cost 346,290,000 · expense 53,262,500
LEDGER_ROWS: list[tuple[str, str, str, str, int, int]] = [
    # (code, name, category, direction, 借方, 贷方)
    ("1001", "库存现金", "资产", "借", 2_000_000, 0),
    ("1002", "银行存款", "资产", "借", 738_777_500, 763_187_500),
    ("1122", "应收账款", "资产", "借", 211_539_402, 206_500_000),
    ("2202", "应付账款", "负债", "贷", 162_000_000, 168_997_254),
    ("2314", "合同负债", "负债", "贷", 198_466_768, 195_000_000),
    ("4001", "实收资本", "权益", "贷", 0, 0),
    ("4103", "本年利润", "权益", "贷", 402_709_297, 418_446_250),
    ("6001.01", "主营业务收入——住宅物业管理服务", "收入", "贷", 0, 257_295_000),
    ("6001.02", "主营业务收入——非住宅物业管理服务", "收入", "贷", 0, 87_026_250),
    ("6001.03", "主营业务收入——案场协销及非业主增值服务", "收入", "贷", 0, 30_375_000),
    ("6051.01", "其他业务收入——社区增值服务", "收入", "贷", 0, 23_200_000),
    ("6051.02", "其他业务收入——多种经营（车位·广告·场地）", "收入", "贷", 0, 12_800_000),
    ("6051.03", "其他业务收入——顾问咨询及物资销售", "收入", "贷", 0, 4_000_000),
    ("6401.01", "主营业务成本——职工薪酬", "成本费用", "借", 179_407_136, 0),
    ("6401.02", "主营业务成本——分包及外包服务费", "成本费用", "借", 70_722_260, 0),
    ("6401.03", "主营业务成本——能源费", "成本费用", "借", 23_046_624, 0),
    ("6401.04", "主营业务成本——维修维护费", "成本费用", "借", 19_044_680, 0),
    ("6401.05", "主营业务成本——物料及低值易耗品", "成本费用", "借", 5_647_704, 0),
    ("6401.06", "主营业务成本——折旧与摊销", "成本费用", "借", 9_316_620, 0),
    ("6401.07", "主营业务成本——办公及差旅费", "成本费用", "借", 4_310_618, 0),
    ("6401.08", "主营业务成本——保险费及项目税费", "成本费用", "借", 2_000_220, 0),
    ("6401.09", "主营业务成本——其他直接费用", "成本费用", "借", 4_991_338, 0),
    ("6402", "其他业务成本", "成本费用", "借", 26_572_800, 0),
    ("6403", "税金及附加", "成本费用", "借", 1_230_000, 0),
    ("6601", "销售费用", "成本费用", "借", 4_510_000, 0),
    ("6602", "管理费用", "成本费用", "借", 30_750_000, 0),
    ("6603", "财务费用", "成本费用", "借", 1_807_500, 0),
    ("6604", "研发费用", "成本费用", "借", 2_870_000, 0),
    ("6701", "资产减值损失", "成本费用", "借", 1_300_000, 0),
    ("6702", "信用减值损失", "成本费用", "借", 12_025_000, 0),
]

SECTION_BEFORE = {
    "1001": "资产类科目",
    "2202": "负债类科目",
    "4001": "权益类科目",
    "6001.01": "收入类科目",
    "6401.01": "成本费用类科目",
}

REVENUE_PREFIXES = ("6001", "6051")
COST_CODES = {"6402", "6403"}
EXPENSE_CODES = {"6601", "6602", "6603", "6604", "6701", "6702"}


def management_account(code: str) -> str | None:
    if code.startswith(REVENUE_PREFIXES):
        return "revenue"
    if code.startswith("6401") or code in COST_CODES:
        return "cost"
    if code in EXPENSE_CODES:
        return "expense"
    return None


def expected_pnl() -> dict[str, int]:
    totals = {"revenue": 0, "cost": 0, "expense": 0}
    for code, _name, _cat, _dir, debit, credit in LEDGER_ROWS:
        account = management_account(code)
        if account == "revenue":
            totals["revenue"] += credit
        elif account in {"cost", "expense"}:
            totals[account] += debit
    return totals


def _title_area(sheet, title: str, subtitle: str) -> None:
    sheet["A1"] = title
    sheet["A2"] = subtitle
    # row 3 stays empty, as in the real packs


def ledger_sheet(book: Workbook, name: str = "02·GL科目余额表") -> None:
    """Trial-balance sheet: title area, header on row 4, section and footer rows."""
    sheet = book.create_sheet(name)
    _title_area(sheet, "科目余额表（试算平衡表）", SUBTITLE)
    headers = [
        "科目代码", "科目名称", "类别", "方向",
        "期初余额\n借方", "期初余额\n贷方",
        "本期发生额\n借方", "本期发生额\n贷方",
        "期末余额\n借方", "期末余额\n贷方",
    ]
    for index, text in enumerate(headers, start=1):
        sheet.cell(row=4, column=index, value=text)
    row = 5
    debit_total = credit_total = 0
    for code, account_name, category, direction, debit, credit in LEDGER_ROWS:
        section = SECTION_BEFORE.get(code)
        if section:
            sheet.cell(row=row, column=1, value=section)
            row += 1
        sheet.cell(row=row, column=1, value=code)
        sheet.cell(row=row, column=2, value=account_name)
        sheet.cell(row=row, column=3, value=category)
        sheet.cell(row=row, column=4, value=direction)
        sheet.cell(row=row, column=7, value=debit)
        sheet.cell(row=row, column=8, value=credit)
        debit_total += debit
        credit_total += credit
        row += 1
    sheet.cell(row=row, column=1, value="合　计")
    sheet.cell(row=row, column=7, value=debit_total)
    sheet.cell(row=row, column=8, value=credit_total)
    row += 1
    sheet.cell(row=row, column=1, value="平衡校验（借－贷）")
    sheet.cell(row=row, column=7, value=0)
    row += 1
    for note in (
        "校验说明：期初余额、本期发生额、期末余额三处借贷合计差额均为 0 元，试算平衡通过。",
        "1231 坏账准备等为资产类备抵科目，余额方向为贷方。",
        "2221.01 销项税额于月末结转至 2221.03 未交增值税，期末余额为零。",
    ):
        sheet.cell(row=row, column=1, value=note)
        row += 1


VOUCHERS: list[tuple[str, str, list[tuple[str, str, int, int]]]] = [
    (
        "记-08-001",
        "计提本月住宅及非住宅物业管理服务收入（权责发生制）",
        [
            ("1122", "应收账款", 162_381_902, 0),
            ("2314", "合同负债", 198_466_768, 0),
            ("6001.01", "主营业务收入——住宅物业管理服务", 0, 257_295_000),
            ("6001.02", "主营业务收入——非住宅物业管理服务", 0, 87_026_250),
            ("2221.01", "应交税费——应交增值税（销项税额）", 0, 16_527_420),
        ],
    ),
    (
        "记-08-002",
        "确认本月案场协销及非业主增值服务收入",
        [
            ("1122", "应收账款", 32_197_500, 0),
            ("6001.03", "主营业务收入——案场协销及非业主增值服务", 0, 30_375_000),
            ("2221.01", "应交税费——应交增值税（销项税额）", 0, 1_822_500),
        ],
    ),
    (
        "记-08-003",
        "结转本月主营业务成本",
        [
            ("6401.01", "主营业务成本——职工薪酬", 179_407_136, 0),
            ("6401.02", "主营业务成本——分包及外包服务费", 70_722_260, 0),
            ("2211.01", "应付职工薪酬——工资奖金及绩效", 0, 158_000_000),
            ("2202", "应付账款", 0, 92_129_396),
        ],
    ),
]


def journal_sheet(book: Workbook, name: str = "03·GL月结分录清单") -> None:
    """Voucher list: voucher number and date only on the first line of each voucher."""
    sheet = book.create_sheet(name)
    _title_area(sheet, "月结汇总记账凭证清单", "华宸物业  |  2026年08月  |  单位：元  |  逐笔借贷平衡")
    headers = ["凭证号", "日期", "摘要", "科目代码", "科目名称", "借方金额", "贷方金额", "现金流量表项目"]
    for index, text in enumerate(headers, start=1):
        sheet.cell(row=4, column=index, value=text)
    row = 5
    grand_debit = grand_credit = 0
    for number, summary, lines in VOUCHERS:
        first = True
        subtotal_debit = subtotal_credit = 0
        for code, account_name, debit, credit in lines:
            if first:
                sheet.cell(row=row, column=1, value=number)
                sheet.cell(row=row, column=2, value="2026-08-31")
                sheet.cell(row=row, column=3, value=summary)
                first = False
            sheet.cell(row=row, column=4, value=code)
            sheet.cell(row=row, column=5, value=account_name)
            if debit:
                sheet.cell(row=row, column=6, value=debit)
            if credit:
                sheet.cell(row=row, column=7, value=credit)
            subtotal_debit += debit
            subtotal_credit += credit
            row += 1
        sheet.cell(row=row, column=3, value="　　　　小　计")
        sheet.cell(row=row, column=6, value=subtotal_debit)
        sheet.cell(row=row, column=7, value=subtotal_credit)
        row += 1
        grand_debit += subtotal_debit
        grand_credit += subtotal_credit
    sheet.cell(row=row, column=1, value="合　计")
    sheet.cell(row=row, column=3, value=f"{len(VOUCHERS)} 笔凭证")
    sheet.cell(row=row, column=6, value=grand_debit)
    sheet.cell(row=row, column=7, value=grand_credit)


def journal_line_count() -> int:
    return sum(len(lines) for _number, _summary, lines in VOUCHERS)


def cover_sheet(book: Workbook, name: str = "00·封面与编制说明") -> None:
    sheet = book.create_sheet(name)
    sheet["A1"] = TITLE
    sheet["A4"] = "2026年08月  月度结账财务报表套表（GL · AP · AR · CF）"
    sheet["A5"] = "本套表为基于公开市场数据构建的模拟样本，不代表任何真实企业。"
    sheet["A7"] = "编制：财务部"


def dashboard_sheet(book: Workbook, name: str = "01·核心指标看板") -> None:
    sheet = book.create_sheet(name)
    sheet["A1"] = "核心指标看板"
    sheet["A2"] = "华宸物业  |  2026年08月 月结"
    for index, text in enumerate(["指标", "本月", "本年累计", "同比"], start=1):
        sheet.cell(row=4, column=index, value=text)
    sheet.cell(row=5, column=1, value="经营规模")
    sheet.cell(row=6, column=1, value="营业收入")
    sheet.cell(row=6, column=2, value=414_696_250)


def benchmark_sheet(book: Workbook, name: str = "13·行业对标与假设") -> None:
    sheet = book.create_sheet(name)
    sheet["A1"] = "行业对标基准值与建模假设"
    sheet["A2"] = "数据来源：2024 年上市物企年报"
    sheet["A4"] = "一、行业基准值与本模型取值对照"


def region_sheet(book: Workbook, name: str = "10·区域经营损益表") -> None:
    sheet = book.create_sheet(name)
    _title_area(sheet, "区域经营损益表（管理会计口径）", "华宸物业  |  2026年1-8月  |  单位：万元")
    headers = ["区　域", "营业收入", "营业成本", "期间费用", "营业利润"]
    for index, text in enumerate(headers, start=1):
        sheet.cell(row=4, column=index, value=text)
    rows = [
        ("华东区域", 109742.028, 86476.7181, 7871.6056, 13429.6868),
        ("华南区域", 72944.26, 57990.68, 5232.17, 8228.91),
        ("华北区域", 58941.56, 47801.61, 4227.78, 5380.15),
    ]
    for offset, values in enumerate(rows):
        for index, value in enumerate(values, start=1):
            sheet.cell(row=5 + offset, column=index, value=value)
    sheet.cell(row=5 + len(rows), column=1, value="合并合计")


def city_sheet(book: Workbook, name: str = "11·城市公司明细表") -> None:
    sheet = book.create_sheet(name)
    _title_area(sheet, "城市公司经营明细表", "华宸物业  |  2026年1-8月  |  单位：万元")
    headers = ["区　域", "城市公司", "营业收入", "营业利润"]
    for index, text in enumerate(headers, start=1):
        sheet.cell(row=4, column=index, value=text)
    for offset, values in enumerate(
        [("华东区域", "宁波城市公司", 21000.5, 2600.1), ("华东区域", "常州城市公司", 18000.2, 2100.4)]
    ):
        for index, value in enumerate(values, start=1):
            sheet.cell(row=5 + offset, column=index, value=value)


def monthly_pack(path: Path | None = None, *, period: str = "2026年08月") -> bytes:
    """A 华宸-shaped month-end pack: cover, dashboard, ledger, journal, region, city, benchmark.

    ``period`` produces next month's pack: the same shape, different bytes, which
    is what a structure template has to recognise.
    """
    global SUBTITLE
    original = SUBTITLE
    SUBTITLE = original.replace("2026年08月", period)
    try:
        book = Workbook()
        book.remove(book.active)
        cover_sheet(book)
        dashboard_sheet(book)
        ledger_sheet(book)
        journal_sheet(book)
        region_sheet(book)
        city_sheet(book)
        benchmark_sheet(book)
        return _save(book, path)
    finally:
        SUBTITLE = original


def ledger_only(path: Path | None = None, *, sheet_name: str = "科目余额表") -> bytes:
    """A single-sheet export — the shape a manager gets when exporting one table."""
    book = Workbook()
    book.remove(book.active)
    ledger_sheet(book, sheet_name)
    return _save(book, path)


def no_category_ledger(path: Path | None = None) -> bytes:
    """Debit/credit columns with no category or direction column to infer sides from."""
    book = Workbook()
    book.remove(book.active)
    sheet = book.create_sheet("余额表")
    _title_area(sheet, "科目余额表", "华宸物业  |  2026年08月  |  单位：元")
    for index, text in enumerate(["科目名称", "借方", "贷方"], start=1):
        sheet.cell(row=4, column=index, value=text)
    for offset, (name, debit, credit) in enumerate(
        [("主营业务收入", 0, 120), ("管理费用", 20, 0)]
    ):
        sheet.cell(row=5 + offset, column=1, value=name)
        sheet.cell(row=5 + offset, column=2, value=debit)
        sheet.cell(row=5 + offset, column=3, value=credit)
    return _save(book, path)


def _save(book: Workbook, path: Path | None) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    book.close()
    data = buffer.getvalue()
    if path is not None:
        Path(path).write_bytes(data)
    return data
