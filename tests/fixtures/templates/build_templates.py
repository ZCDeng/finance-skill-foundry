# -*- coding: utf-8 -*-
"""补充数据模板：ERP 里没有、客户又常常没有现成表的三类数据。

    python3 build_templates.py <输出目录>

只在客户手头没有现成台账时用；已有台账的照样直接导入，系统按表结构确认去读。
列名用系统认得的写法（组织、业态、期间），金额列名带单位后缀。每本模板第一张是
「封面与填写说明」，名字带「封面」，导入时默认不参与计算。应用随包的一份在
foundry/resources/data_templates/，tests/test_templates.py 逐格比对两边。
"""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

AREA = "补充数据模板_在管面积台账.xlsx"
CONTRACT = "补充数据模板_物业服务合同台账.xlsx"
HEADCOUNT = "补充数据模板_人数.xlsx"

HEAD = PatternFill("solid", fgColor="EDEDED")
COMMON = [
    "1. 一行一个项目（人数模板一行一个部门），「组织」写城市公司或区域，和月结套表里的叫法一致。",
    "2. 第 2 行的期间和单位按实际改；金额和面积只填数字，不要在格子里写单位。",
    "3. 示例行以「示例」开头，填好自己的数据后删掉。",
    "4. 不要合并单元格，不要在表格中间插小计行；合计由系统算。",
    "5. 已有现成台账的不必改用模板，直接加入资料，在资料页确认表结构即可。",
]


def cover(book: Workbook, title: str, purpose: list[str]) -> None:
    sheet = book.active
    sheet.title = "00·封面与填写说明"
    sheet["A1"] = title
    sheet["A1"].font = Font(bold=True, size=14)
    row = 3
    for line in ["用途", *purpose, "", "填写要求", *COMMON]:
        sheet.cell(row=row, column=1, value=line or None)
        if line in {"用途", "填写要求"}:
            sheet.cell(row=row, column=1).font = Font(bold=True)
        row += 1
    sheet.column_dimensions["A"].width = 100


def table(book: Workbook, name: str, title: str, scope: str, headers: list[str], rows: list[list]) -> None:
    sheet = book.create_sheet(name)
    sheet["A1"] = title
    sheet["A1"].font = Font(bold=True, size=13)
    sheet["A2"] = scope
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=4, column=column, value=header)
        cell.font = Font(bold=True)
        cell.fill = HEAD
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        sheet.column_dimensions[cell.column_letter].width = max(12, len(header) * 2 + 2)
    for offset, values in enumerate(rows, start=5):
        for column, value in enumerate(values, start=1):
            sheet.cell(row=offset, column=column, value=value)
    sheet.freeze_panes = "A5"


def area() -> Workbook:
    book = Workbook()
    cover(book, "在管面积台账（补充数据模板）", [
        "回款健康里的「在管面积增长」「退场面积占比」「人均在管面积」要读在管面积。",
        "年初、期末按合同口径的计费面积；低效退场指主动退出的项目，到期未续约指合同到期后没有续签的项目。",
    ])
    table(book, "面积台账", "在管面积台账", "期间：2026年8月　面积单位：万㎡",
          ["组织", "项目", "业态", "在管面积年初（万㎡）", "在管面积期末（万㎡）", "低效退场面积（万㎡）", "到期未续约面积（万㎡）"],
          [["示例城市公司A", "示例项目1", "住宅", 12.5, 12.5, 0, 0],
           ["示例城市公司A", "示例项目2", "写字楼", 3.2, 0, 0, 3.2],
           ["示例城市公司B", "示例项目3", "商业", 6.8, 6.8, 0, 0]])
    return book


def contract() -> Workbook:
    book = Workbook()
    cover(book, "物业服务合同台账（补充数据模板）", [
        "回款健康里的「续约风险敞口」、拟退场合同的收缴率，以及合同台账和月结实收的跨表核对要读合同台账。",
        "「续约状态」只写三种：在约、12个月内到期、拟退场。",
        "「本年实收」按收款所属合同汇总，用来和月结套表的区域实收对数。",
    ])
    table(book, "合同台账", "物业服务合同台账", "期间：2026年8月　金额单位：万元　币种：人民币",
          ["组织", "合同编号", "项目", "业态", "合同开始日", "合同到期日", "续约状态",
           "年化合同额（万元）", "本年确认收入（万元）", "本年账单（万元）", "本年实收（万元）"],
          [["示例城市公司A", "示例-HT-001", "示例项目1", "住宅", "2024-01-01", "2027-12-31", "在约", 360, 240, 250, 228],
           ["示例城市公司A", "示例-HT-002", "示例项目2", "写字楼", "2023-07-01", "2026-12-31", "12个月内到期", 180, 120, 125, 98],
           ["示例城市公司B", "示例-HT-003", "示例项目3", "商业", "2022-03-01", "2026-10-31", "拟退场", 96, 64, 70, 41]])
    return book


def headcount() -> Workbook:
    book = Workbook()
    cover(book, "人数（补充数据模板）", [
        "回款健康里的「人均创收」「人均在管面积」要读在岗人数。",
        "在岗人数按期末口径，含外包驻场人员的请在说明里写清楚，前后各月保持一致。",
    ])
    table(book, "人数", "在岗人数", "期间：2026年8月　人数单位：人",
          ["组织", "部门", "在岗人数", "上年同期在岗人数"],
          [["示例城市公司A", "项目服务", 420, 405],
           ["示例城市公司A", "职能", 36, 38],
           ["示例城市公司B", "项目服务", 260, 271]])
    return book


BUILDERS = {AREA: area, CONTRACT: contract, HEADCOUNT: headcount}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: build_templates.py <输出目录>")
    out = Path(sys.argv[1]).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name, build in BUILDERS.items():
        build().save(out / name)


if __name__ == "__main__":
    main()
