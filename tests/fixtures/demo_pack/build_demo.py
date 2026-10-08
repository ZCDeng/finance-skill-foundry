# -*- coding: utf-8 -*-
"""华宸物业 演示套表：一次生成六个文件，覆盖 FA Foundry 的全部分析能力。

    python3 build_demo.py <输出目录>

A  2026年08月 月结套表（14 表）      build.py，演示开关打开，另埋应收滚动差异
B  2026年度 全面预算与合同台账（16 表）build_budget.py，演示开关打开
C  2026年09月 月结套表               build.py，同形状下一个月
D  2026年08月 明细长表               本文件：实际/预算长表、量价、发票、回款、13 周收付
E  经营分析会纪要（md）/ 经理汇报稿（docx，本文件直接写 WordprocessingML）
F  公式体检样本（xlsx）               本文件写公式、外部链接和公式缓存值，不需要 Excel

整套文件不依赖 Excel 或 macOS，云端、CI 和 Mac 上生成的内容相同；应用随包的一份在
foundry/resources/demo_pack/，tests/test_demo_pack.py 逐格比对两边。

埋了哪些差异、系统应该怎么报，见同目录 README.md「演示埋点」一节；本文件末尾会把
同样的清单写进输出目录的 演示说明.md。币种一律人民币。
"""
from __future__ import annotations

import datetime as dt
import html
import os
import random
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
A_NAME = "华宸物业_2026年08月_月结财务套表_GL-AP-AR-CF.xlsx"
B_NAME = "华宸物业_2026年度_全面预算与合同台账.xlsx"
C_NAME = "华宸物业_2026年09月_月结财务套表_GL-AP-AR-CF.xlsx"
D_NAME = "华宸物业_2026年08月_明细长表.xlsx"
E1_NAME = "华宸物业_2026年08月_经营分析会纪要.md"
E2_NAME = "华宸物业_2026年08月_经理汇报稿.docx"
F_NAME = "华宸物业_2026年08月_公式体检样本.xlsx"

# 这一版资料的日期，写进 演示说明.md；改了埋点或数据就改它，随包资料的版本号跟着加一
PACK_DATE = "2026-10-08"

# 应收滚动埋点：本期收回少记 1,200 万元，年初 + 新增 − 收回 − 核销 比期末多 1,200 万
ROLLFORWARD_GAP_WAN = 1200


def run_builder(script: str, out: Path, period_m: int) -> None:
    env = {**os.environ, "HUACHEN_DEMO": "1", "HUACHEN_PERIOD_M": str(period_m), "HUACHEN_OUT_DIR": str(out)}
    subprocess.run([sys.executable, "-I", str(HERE / script)], cwd=HERE, env=env, check=True)


def plant_rollforward(path: Path) -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(path)
    ws = wb["07·AR账龄及减值"]
    row = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "本期收回")
    before = ws.cell(row, 2).value
    ws.cell(row, 2).value = round(before + ROLLFORWARD_GAP_WAN, 4)
    wb.save(path)
    return {"cell": f"07·AR账龄及减值!B{row}", "before": before, "after": ws.cell(row, 2).value}


def _models():
    os.environ["HUACHEN_DEMO"] = "1"
    os.environ["HUACHEN_PERIOD_M"] = "8"
    sys.path.insert(0, str(HERE))
    import budget_model  # noqa: E402  (imports model with the same switches)

    return budget_model


def _sheet(wb, title, header, rows):
    ws = wb.create_sheet(title)
    ws.append(header)
    for row in rows:
        ws.append(row)
    for i, name in enumerate(header, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, len(str(name)) * 2 + 2)
    ws.freeze_panes = "A2"
    return ws


def build_long_tables(path: Path) -> dict:
    """D：系统导出格式的长表，表头在第 1 行，便于直接确认结构。"""
    from openpyxl import Workbook

    b = _models()
    WAN = 10_000
    ident = ["华宸物业经营总账", "华宸物业服务集团", "CNY", "万元"]
    wb = Workbook()
    wb.remove(wb.active)

    # 1) 实际与预算：区域 × 管理科目，2026 年 1-8 月累计，万元。两张表各一个情景，口径分别绑定
    head = ["ledger", "organization", "period", "currency", "unit", "scenario", "management_account", "amount"]
    bud_ytd = sum(b.bud_month(m)["rev_total"] for m in range(1, 9)) / b.BUD_REV_TOTAL
    act_rows, bud_rows = [], []
    for region, act in b.REGPL_YTD.items():
        if region == b.HQ_NAME:
            continue
        for account, value in (("revenue", act["rev"]), ("cost", act["cogs"]), ("expense", act["opex"] + act["impair"])):
            act_rows.append([ident[0], region, "2026-08", "CNY", "万元", "actual", account, round(value / WAN, 2)])
    for region, bud in b.REG_BUD.items():
        if region == b.HQ_NAME:
            continue
        for account, value in (("revenue", bud["rev"]), ("cost", bud["cogs"]), ("expense", bud["opex"] + bud["impair"])):
            bud_rows.append([ident[0], region, "2026-08", "CNY", "万元", "budget", account, round(value * bud_ytd / WAN, 2)])
    # 埋点：西南区域只有预算（年中新设，尚未并表）；华东一行营业外支出只有实际；华中一行负预算（政府补助冲减费用）
    bud_rows += [[ident[0], "西南区域", "2026-08", "CNY", "万元", "budget", "revenue", 3200.00],
                 [ident[0], "西南区域", "2026-08", "CNY", "万元", "budget", "cost", 2650.00],
                 [ident[0], "华中区域", "2026-08", "CNY", "万元", "budget", "expense", -420.00]]
    act_rows.append([ident[0], "华东区域", "2026-08", "CNY", "万元", "actual", "non_operating", 128.60])
    _sheet(wb, "实际长表", head, act_rows)
    _sheet(wb, "预算长表", head, bud_rows)
    rows = act_rows + bud_rows

    # 2) 量价：业态 × 计费面积（万㎡·月，即在管面积 × 8 个月）× 单方物业费（元/㎡/月），金额万元；实际、预算各一张
    formats = [("住宅", 12600, 1.52, 13050, 1.49), ("写字楼", 1900, 4.10, 2050, 4.05),
               ("商业综合体", 900, 5.60, 980, 5.40), ("产业园", 1700, 2.20, 1800, 2.30),
               ("公建市政", 2900, 1.15, 3120, 1.18)]
    qp_head = ["ledger", "organization", "period", "currency", "unit", "scenario", "product", "quantity", "price", "amount"]
    for scenario, title in (("actual", "量价实际"), ("budget", "量价预算")):
        qp = []
        for fmt, q_act, p_act, q_bud, p_bud in formats:
            q, pr = (q_act, p_act) if scenario == "actual" else (q_bud, p_bud)
            q *= 8
            amount = round(q * pr, 2)
            if scenario == "actual" and fmt == "写字楼":
                amount = round(amount + 260.0, 2)  # 埋点：写字楼实际金额比 计费面积 × 单价 多 260 万
            qp.append([ident[0], ident[1], "2026-08", "CNY", "万元", scenario, fmt, q, pr, amount])
        _sheet(wb, title, qp_head, qp)

    # 3) 应收发票与回款流水（华南区域样本，元）
    rnd = random.Random(20261008)
    customers = ["业主（住宅）", "租户（写字楼）", "关联方地产", "政府及国企", "商户"]
    invoices, activity = [], []
    start = dt.date(2025, 9, 1)
    for i in range(1, 61):
        issue = start + dt.timedelta(days=rnd.randrange(0, 330))
        due = issue + dt.timedelta(days=30)
        amount = rnd.randrange(80_000, 1_800_000, 100)
        status = "争议" if i % 13 == 0 else "正常"
        inv = f"HC-AR-{i:04d}"
        invoices.append([inv, customers[i % 5], "华南区域", issue.isoformat(), due.isoformat(), amount, status,
                         ident[0], "华宸物业华南区域", "CNY", "元"])
        paid_share = rnd.choice([0, 0, 0.3, 0.6, 1, 1, 1])
        if paid_share:
            paid_on = min(due + dt.timedelta(days=rnd.randrange(-10, 120)), dt.date(2026, 8, 31))
            activity.append([f"PAY-{i:04d}", inv, "payment", paid_on.isoformat(), round(amount * paid_share, 2),
                             ident[0], "华宸物业华南区域", "CNY", "元"])
        if i % 17 == 0:
            activity.append([f"CR-{i:04d}", inv, "credit", (issue + dt.timedelta(days=45)).isoformat(), round(amount * 0.1, 2),
                             ident[0], "华宸物业华南区域", "CNY", "元"])
        if i % 29 == 0:
            activity.append([f"WO-{i:04d}", inv, "writeoff", "2026-08-25", round(amount * 0.2, 2),
                             ident[0], "华宸物业华南区域", "CNY", "元"])
    _sheet(wb, "应收发票", ["invoice_id", "customer", "region", "issue_date", "due_date", "amount", "status",
                           "ledger", "organization", "currency", "unit"], invoices)
    _sheet(wb, "回款流水", ["activity_id", "invoice_id", "kind", "effective_date", "amount",
                           "ledger", "organization", "currency", "unit"], activity)

    # 4) 13 周收付（集团，万元），实际截止 2026-09-06；收款、付款各一张
    receipts, payments = [], []
    day = dt.date(2026, 8, 31)
    for week in range(13):
        d = day + dt.timedelta(days=7 * week + 3)
        status = "actual" if d <= dt.date(2026, 9, 6) else "forecast"
        receipts.append([f"R{week + 1:02d}", d.isoformat(), 31_500 + 900 * (week % 4) + (6000 if week >= 10 else 0), status,
                         ident[0], ident[1], "CNY", "万元"])
        payments.append([f"P{week + 1:02d}", d.isoformat(), 33_800 + (9_500 if week in (1, 5, 9) else 0), status,
                         ident[0], ident[1], "CNY", "万元"])
    cash_head = ["id", "date", "amount", "status", "ledger", "organization", "currency", "unit"]
    _sheet(wb, "收款计划", cash_head, receipts)
    # 埋点另放一张：截止日前的收款仍标 forecast，换绑这张时系统应拒收
    wrong = [list(row) for row in receipts]
    wrong[0][3] = "forecast"
    _sheet(wb, "收款计划_含错误行", cash_head, wrong)
    _sheet(wb, "付款计划", cash_head, payments)
    cash = receipts + payments
    ws = wb.create_sheet("说明")
    for line in ("期初货币资金 186,000 万元（与月结套表 05 表一致），实际截止日 2026-09-06。",
                 "长表为系统导出格式，表头在第 1 行；金额单位见 unit 列。"):
        ws.append([line])
    wb.save(path)
    return {"rows": len(rows), "invoices": len(invoices), "activity": len(activity), "cash": len(cash)}


_DOCX_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
               '<Default Extension="xml" ContentType="application/xml"/>'
               '<Override PartName="/word/document.xml" '
               'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
_DOCX_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
              'Target="word/document.xml"/></Relationships>')


def _docx(title: str, paragraphs: list[str], path: Path) -> Path:
    """一个只有标题和段落的 Word 文档。直接写 WordprocessingML，任何系统上生成的内容都相同。"""
    def para(text: str, bold: bool = False) -> str:
        run = "<w:rPr><w:b/><w:sz w:val=\"32\"/></w:rPr>" if bold else ""
        return f'<w:p><w:r>{run}<w:t xml:space="preserve">{html.escape(text)}</w:t></w:r></w:p>'

    body = para(title, bold=True) + "".join(para(text) for text in paragraphs)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body>{body}</w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in (("[Content_Types].xml", _DOCX_TYPES), ("_rels/.rels", _DOCX_RELS), ("word/document.xml", document)):
            package.writestr(zipfile.ZipInfo(name, date_time=(2026, 10, 8, 0, 0, 0)), data)
    return path


def build_documents(minutes: Path, report: Path) -> None:
    """E：纪要给业务背景引用；汇报稿给数字复核（一处单位写错、一处数字写错）。"""
    # 纪要用 Markdown：FA Foundry 把 md/txt 登记为背景资料，可按段落引用
    minutes.write_text("""# 华宸物业 2026 年 8 月经营分析会纪要

时间：2026 年 9 月 5 日。参会：财务部、运营管理部、五大区域总经理。

一、8 月华南区域两个写字楼项目（深圳南山科技园 A 座、广州天河中心）提前退场，合计在管面积 46 万平方米，退场前三个月收缴率已降至 61%。

二、关联方地产企业欠款余额 22,800 万元，较年初增加 3,900 万元，拟于 9 月启动以房抵款谈判。

三、9 月起执行高温津贴标准上调，预计四季度营业成本增加约 1,100 万元。

四、四季度为回款高峰，集团要求各区域 12 月底前综合收缴率回到 86% 以上。
""", encoding="utf-8")
    _docx("2026 年 1-8 月经营情况汇报", [
        "1-8 月实现营业收入 325,644 万元，完成全年滚动预测的 65.1%，同比下降 1.8%。",
        "营业成本 266,854.5 元，综合毛利率 18.05%，同比下降 0.9 个百分点。",
        "营业利润 21,086 万元，归属于母公司净利润 12,975.30 万元。",
        "期末应收账款余额 150,000 万元，坏账准备 22,125 万元，综合计提比例 14.75%。",
        "1-8 月经营活动现金流量净额 18,431.94 万元，为净利润的 1.13 倍。",
    ], report)


def build_formula_sample(path: Path) -> list[str]:
    """F：每种公式体检提示各一处。返回埋点清单。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "月度收入"
    ws.append(["华宸物业 2026 年月度营业收入（万元）"])
    ws.append(["项目"] + [f"{m}月" for m in range(1, 13)] + ["全年"])
    base = [39500, 37800, 40100, 40600, 41200, 41800, 41600, 41469.6, 41900, 42300, 43800, 48000]
    ws.append(["基础物业费"] + base + ["=SUM(B3:M3)"])
    ws.append(["增值服务"] + [round(v * 0.11, 1) for v in base] + ["=SUM(B4:M4)"])
    letters = "BCDEFGHIJKLMN"
    total = [f"={c}3+{c}4" for c in letters[:12]]
    total[8] = "=J3+J4*1.13"  # 9 月公式与同行其他月份不同，还写死了 1.13
    ws.append(["营业收入合计"] + total + ["=SUM(B5:M5)+2793.28"])  # 合计里加了一个倒挤数
    ws.append(["上年同期（外部链接）"] + [f"='[2025年报.xlsx]利润表'!{c}6" for c in letters[:12]] + ["=SUM(B6:M6)"])
    ws.append(["预算差异"] + [f"={c}5-#REF!" if c == "D" else f"={c}5-{c}7" for c in letters[:12]] + [""])
    ws.append(["编制日期", "=TODAY()"])
    hidden = wb.create_sheet("口径备注")
    hidden.append(["本表为隐藏表，记录倒挤数 2,793.28 的来源：台账实收与月结区域实收之差"])
    hidden.sheet_state = "hidden"
    wb.save(path)
    return ["9 月合计公式与同行不同（=J3+J4*1.13）", "全年合计里加了写死的 +2793.28", "外部链接 [2025年报.xlsx]",
            "#REF! 错误", "TODAY() 易失函数", "隐藏表「口径备注」"]


# 「编制日期」=TODAY() 的缓存值固定为这一天，同一份脚本任何一天生成的文件都一样
CACHE_DATE = dt.date(2026, 9, 5)
_ERROR = "#REF!"
_CELL = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)")
_RANGE_SUM = re.compile(r"SUM\(\$?([A-Z]{1,3})\$?(\d+):\$?([A-Z]{1,3})\$?(\d+)\)")


def _col(letters: str) -> int:
    number = 0
    for char in letters:
        number = number * 26 + ord(char) - 64
    return number


def _formula_values(sheet) -> dict[str, object]:
    """按 Excel 的结果算出这张表每个公式的值。

    只覆盖样本里用到的写法：单元格引用、SUM(区域)、加减乘、TODAY()。读别的工作簿、或公式里写着
    #REF! 的，结果是 #REF!（Excel 打开时不更新链接，找不到来源就是这个值）；错误值向上传递；
    循环引用里读到自己的那一处按 0 算。
    """
    values: dict[str, object] = {}
    visiting: set[str] = set()

    def cell(ref: str) -> object:
        if ref in values:
            return values[ref]
        raw = sheet[ref].value
        if not (isinstance(raw, str) and raw.startswith("=")):
            return raw if raw is not None else 0
        if ref in visiting:
            return 0
        visiting.add(ref)
        try:
            values[ref] = evaluate(raw[1:])
        finally:
            visiting.discard(ref)
        return values[ref]

    def evaluate(text: str) -> object:
        if "[" in text or _ERROR in text:
            return _ERROR
        if text == "TODAY()":
            return (CACHE_DATE - dt.date(1899, 12, 30)).days
        parts: list[object] = []

        def total(match: re.Match) -> str:
            first, last = (_col(match.group(1)), int(match.group(2))), (_col(match.group(3)), int(match.group(4)))
            amount = 0.0
            for row in range(first[1], last[1] + 1):
                for column in range(first[0], last[0] + 1):
                    parts.append(cell(sheet.cell(row, column).coordinate))
                    amount += parts[-1] if isinstance(parts[-1], (int, float)) else 0
            return repr(amount)

        def one(match: re.Match) -> str:
            parts.append(cell(match.group(1) + match.group(2)))
            return repr(parts[-1]) if isinstance(parts[-1], (int, float)) else "0"

        expression = _CELL.sub(one, _RANGE_SUM.sub(total, text))
        if any(part == _ERROR for part in parts):
            return _ERROR
        if not re.fullmatch(r"[\d.+\-*/() e]+", expression):
            raise ValueError(f"公式样本里出现了缓存算不了的写法：={text}")
        result = eval(expression, {"__builtins__": {}})  # noqa: S307  只剩数字和四则运算
        return round(result, 6)

    for row in sheet.iter_rows():
        for item in row:
            if isinstance(item.value, str) and item.value.startswith("="):
                cell(item.coordinate)
    return values


def write_formula_cache(path: Path) -> int:
    """给公式体检样本补上外部链接和公式缓存值，效果和用 Excel 打开另存一次相同。返回写了几个缓存。"""
    from openpyxl import load_workbook
    from openpyxl.packaging.relationship import Relationship
    from openpyxl.workbook.external_link.external import ExternalBook, ExternalLink, ExternalSheetNames

    book = load_workbook(path)
    # Excel 另存时会把「读别的工作簿」的公式登记成工作簿级的外部链接
    link = ExternalLink(externalBook=ExternalBook(sheetNames=ExternalSheetNames(sheetName=["利润表"])))
    link.file_link = Relationship(type="externalLinkPath", Target="2025年报.xlsx", TargetMode="External")
    book._external_links.append(link)
    values = {sheet.title: _formula_values(sheet) for sheet in book.worksheets}
    book.save(path)

    index = {sheet.title: number for number, sheet in enumerate(book.worksheets, start=1)}
    written = 0
    with zipfile.ZipFile(path) as package:
        parts = {name: package.read(name) for name in package.namelist()}
    for title, cached in values.items():
        name = f"xl/worksheets/sheet{index[title]}.xml"
        xml = parts[name].decode("utf-8")

        def fill(match: re.Match) -> str:
            nonlocal written
            value = cached.get(match.group(2))
            if value is None:
                return match.group(0)
            written += 1
            attrs = re.sub(r'\s+t="[^"]*"', "", match.group(3))
            if value == _ERROR:
                return f'<c r="{match.group(2)}"{attrs} t="e">{match.group(4)}<v>{_ERROR}</v></c>'
            return f'<c r="{match.group(2)}"{attrs}>{match.group(4)}<v>{value!r}</v></c>'

        xml = re.sub(r'(<c r="([A-Z]+\d+)"([^>]*)>)(<f>.*?</f>)<v\s*/?>(?:</v>)?</c>', fill, xml)
        parts[name] = xml.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in parts.items():
            package.writestr(name, data)
    return written


NOTES = """# 华宸物业演示套表（{date}）

由仓库 `tests/fixtures/demo_pack/build_demo.py` 生成。虚构主体，金额为模拟值，币种一律人民币。

| 文件 | 演示什么 |
|---|---|
| {A} | 勾稽控制、表结构确认、管理损益、回款健康、风险雷达 |
| {B} | 跨工作簿对数、预算差异、量价分解、续约人效、按去年节奏估全年 |
| {C} | 同形状下月套表：表结构模板自动命中、换期后结果变旧 |
| {D} | 预算差异长表、量价桥、应收账龄、13 周现金 |
| {E1} | 业务背景按段落引用 |
| {E2} | 汇报稿数字复核 |
| {F} | 公式体检 |

## 埋点：系统应该检出的差异

1. F-01 小计勾稽：A「08·AR收缴率与欠费」账单年度坏账分项合计 33,780 万元，账龄组合与总账 1231 为 22,125 万元，差 11,655 万元。
2. F-02 跨工作簿对数：B「11·物业服务合同台账」本年实收合计比 A「08」区域实收少约 2,793 万元，五个区域都少。
3. 应收滚动：A「07」变动表 年初 + 新增 − 收回 − 核销 比期末多 {gap:,} 万元（{cell} 由 {before} 改为 {after}）。
4. DSO：A「01」报 103.9 天（1-8 月累计口径）；按 2025 全年 57 亿推 TTM 收入重算约 97 天，差 6 天以上，属口径不同。
5. 隐含回款率：A「01」综合收缴率 82.4%；按应收变动、减值和收入反推约 91%，差约 8.6 个百分点。
6. 按去年节奏估全年：2025 年全年收入 57 亿（四季度一次性案场收入 6.08 亿），1-8 月只占 58%，按节奏估全年约 56 亿，LE 50 亿比它低 10% 以上。
7. 预算差异长表：西南区域只有预算；营业外支出只有实际；华中一行负预算。
8. 量价桥：写字楼实际金额比 计费面积 × 单价 多 260 万元。
9. 13 周现金：用「收款计划」正常出 13 周现金；换绑「收款计划_含错误行」时，R01 在实际截止日前却标 forecast，系统应拒收。
10. 汇报稿：营业成本写成「266,854.5 元」（应为万元）；经营现金流写成 18,431.94 万元（套表为 17,431.94 万元）。
11. 公式体检：{formula}。

## 其余能力用到的现成数据

- 回款健康、生死线、现金经营利润率：A「01」「04」「07」。
- 规模续约人效：B「02」面积台账、「11」合同台账（续约状态、退场候选）、A「12」人员结构。
- 风险雷达：A「11」50 家城市公司，合计行在 `exclude` 里排除。
- 业务背景：{E1} 「一、」那一段（华南两个写字楼项目提前退场，按段落编号是第 3 段）。
"""


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: build_demo.py <输出目录>")
    out = Path(sys.argv[1]).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} 已有文件，换一个新目录，不覆盖旧套表")
    out.mkdir(parents=True, exist_ok=True)
    stage = out / ".stage"
    stage.mkdir()
    run_builder("build.py", stage, 8)
    run_builder("build_budget.py", stage, 8)
    shutil.move(stage / A_NAME, out / A_NAME)
    shutil.move(stage / B_NAME, out / B_NAME)
    run_builder("build.py", stage, 9)
    shutil.move(stage / C_NAME, out / C_NAME)
    shutil.rmtree(stage)

    planted = plant_rollforward(out / A_NAME)
    build_long_tables(out / D_NAME)
    build_documents(out / E1_NAME, out / E2_NAME)
    formula = build_formula_sample(out / F_NAME)
    write_formula_cache(out / F_NAME)
    (out / "演示说明.md").write_text(NOTES.format(
        date=PACK_DATE, A=A_NAME, B=B_NAME, C=C_NAME, D=D_NAME, E1=E1_NAME, E2=E2_NAME, F=F_NAME,
        gap=ROLLFORWARD_GAP_WAN, formula="；".join(formula), **planted,
    ), encoding="utf-8")
    print("WROTE", out)


if __name__ == "__main__":
    main()
