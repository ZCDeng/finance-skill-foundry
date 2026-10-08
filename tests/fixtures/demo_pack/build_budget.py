# -*- coding: utf-8 -*-
"""生成《2026年度全面预算与合同台账》Excel"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from budget_model import *
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

NAVY, NAVY_L, GREY, GREY_D = "14304F", "2C5C8A", "F2F5F8", "E3E9EF"
RED, GREEN, GOLD, AMBER = "B03A2E", "1E6B4F", "9A6B14", "C87F0A"
FONT = "微软雅黑"
thin = Side(style="thin", color="BFC9D4")
B_ALL = Border(left=thin, right=thin, top=thin, bottom=thin)
B_TOP = Border(left=thin, right=thin, top=Side(style="thin", color="14304F"), bottom=thin)
NUM  = '#,##0.00;[Red]-#,##0.00'
NUM0 = '#,##0;[Red]-#,##0'
NUM3 = '0.000'
NUM4 = '0.0000'
PCT  = '0.00%;[Red]-0.00%'
PCT1 = '0.0%;[Red]-0.0%'
DAY  = '#,##0.0'

wb = Workbook(); wb.remove(wb.active)
def sheet(name, widths, freeze=None, tab=NAVY):
    ws = wb.create_sheet(name); ws.sheet_properties.tabColor = tab
    for i, w_ in enumerate(widths, 1): ws.column_dimensions[get_column_letter(i)].width = w_
    if freeze: ws.freeze_panes = freeze
    ws.sheet_view.showGridLines = False
    return ws
def title(ws, r, text, ncol, sub=None):
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)
    c = ws.cell(r, 1, text); c.font = Font(FONT, 15, bold=True, color=NAVY)
    c.alignment = Alignment("left", "center"); ws.row_dimensions[r].height = 26
    if sub:
        ws.merge_cells(start_row=r+1, start_column=1, end_row=r+1, end_column=ncol)
        if "币种" not in sub:  # 全部金额为人民币，写在副标题里，表结构识别据此读出币种
            sub = f"{sub}  |  币种：人民币"
        c = ws.cell(r+1, 1, sub); c.font = Font(FONT, 9, color="6B7B8C")
        ws.row_dimensions[r+1].height = 15
        return r + 2
    return r + 1
def head(ws, r, cells, h=22, size=9.5):
    for i, t in enumerate(cells, 1):
        c = ws.cell(r, i, t); c.font = Font(FONT, size, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY); c.border = B_ALL
        c.alignment = Alignment("center", "center", wrap_text=True)
    ws.row_dimensions[r].height = h
    return r + 1
def band(ws, r, text, ncol, fill=GREY_D):
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)
    c = ws.cell(r, 1, text); c.font = Font(FONT, 10, bold=True, color=NAVY)
    c.alignment = Alignment("left", "center")
    for i in range(1, ncol+1):
        ws.cell(r, i).fill = PatternFill("solid", fgColor=fill); ws.cell(r, i).border = B_ALL
    ws.row_dimensions[r].height = 19
    return r + 1
def row(ws, r, vals, fmts=None, bold=False, indent=0, fill=None, top=False, size=9.5, h=17):
    for i, v in enumerate(vals, 1):
        c = ws.cell(r, i, v)
        c.font = Font(FONT, size, bold=bold, color=NAVY if bold else "1A1A1A")
        c.border = B_TOP if top else B_ALL
        if fill: c.fill = PatternFill("solid", fgColor=fill)
        if i == 1: c.alignment = Alignment("left", "center", indent=indent)
        else:
            c.alignment = Alignment("right", "center")
            if fmts and i-2 < len(fmts) and fmts[i-2]: c.number_format = fmts[i-2]
    ws.row_dimensions[r].height = h
    return r + 1
def note(ws, r, lines, ncol):
    for t in lines:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)
        c = ws.cell(r, 1, t); c.font = Font(FONT, 9, color="4A5A6A")
        c.alignment = Alignment("left", "center"); ws.row_dimensions[r].height = 16
        r += 1
    return r
def w(x): return x / WAN
def sdiv(a, b): return a / b if b else 0
def paint(ws, r, col, val, good_high=True, th=0.0):
    c = ws.cell(r, col)
    ok = (val >= th) if good_high else (val <= th)
    c.font = Font(FONT, 9.5, bold=True, color=GREEN if ok else RED)
MN = [f"{m}月" for m in range(1, 13)]

# ==================== 00 封面与编制说明 ====================
ws = sheet("00·封面与编制说明", [30, 17, 17, 17, 15, 15, 22])
ws.merge_cells("A1:G3")
c = ws.cell(1, 1, ENTITY); c.font = Font(FONT, 22, bold=True, color=NAVY)
c.alignment = Alignment("left", "center"); ws.row_dimensions[1].height = 30
ws.merge_cells("A4:G4")
c = ws.cell(4, 1, "2026 年度全面预算 与 合同台账（供 FA 拆解分析）")
c.font = Font(FONT, 14, color=NAVY_L); ws.row_dimensions[4].height = 24
ws.merge_cells("A5:G5")
c = ws.cell(5, 1, "本套表为基于公开市场数据构建的模拟样本，不代表任何真实企业。所有金额均为模拟值。")
c.font = Font(FONT, 9, italic=True, color=RED)
r = 7
r = band(ws, r, "一、三口径体系（本工作簿的分析主线）", 7)
r = head(ws, r, ["口径", "简称", "含义", "营业收入", "毛利率", "归母净利润", "在本工作簿中的位置"])
K3 = [
    ("年初批复预算", "BUD", "2026 年 1 月董事会批复的年度经营预算", BUD_REV_TOTAL,
     sdiv(BUD_GROSS, BUD_REV_TOTAL), BUD_PARENT, "01～08 各预算表的「预算」列"),
    ("滚动预测（8月底重估）", "LE", "基于 1-8 月实际重新测算的全年预计数", PL_FY["rev_total"],
     sdiv(PL_FY["gross"], PL_FY["rev_total"]), PL_FY["parent"], "月结套表「全年预算」列即此口径"),
    ("本年累计实际", "ACT", "2026 年 1-8 月已结账的实际发生数", PL_YTD["rev_total"],
     sdiv(PL_YTD["gross"], PL_YTD["rev_total"]), PL_YTD["parent"], "09、10 差异分析表的「实际」列"),
    ("上年实际（2025）", "PY", "2025 年全年实际，用于预算增长率校验", LY_FY["rev"],
     0.2045, LY_FY["parent"], "02 收入预算的同比列"),
]
for a, b_, c_, rev, gm, pr, loc in K3:
    r = row(ws, r, [a, b_, c_, w(rev), gm, w(pr), loc], [None, None, NUM, PCT, NUM, None], bold=(b_ in ("BUD","LE")))
    for cl in (3, 7): ws.cell(r-1, cl).alignment = Alignment("left", "center")
    ws.cell(r-1, 7).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["BUD → LE 缺口", "", "年初预算与最新预测的差额", w(PL_FY["rev_total"]-BUD_REV_TOTAL),
                sdiv(PL_FY["gross"], PL_FY["rev_total"]) - sdiv(BUD_GROSS, BUD_REV_TOTAL),
                w(PL_FY["parent"]-BUD_PARENT), "见「10·利润桥与量价分解」"],
        [None, None, NUM, PCT, NUM, None], bold=True, fill="FBEDEB", top=True)
for cl in (4, 5, 6): ws.cell(r-1, cl).font = Font(FONT, 9.5, bold=True, color=RED)
ws.cell(r-1, 3).alignment = Alignment("left", "center"); ws.cell(r-1, 7).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "二、编制基础与关键假设", 7)
for t in [
    "1. 预算周期：2026 年 1 月 1 日至 12 月 31 日；台账基准日 2026 年 8 月 31 日，与《月结财务套表》同一时点。",
    "2. 收入预算方法：基础物业费＝加权平均在管面积 × 单方物业费 × 12；增值与多经按合同台账逐份滚动测算。收缴率按乐观 92% 编制（行业实操双档：乐观 92% / 保守 88%）。",
    "3. 成本预算方法：职工薪酬为驱动因子法（岗位序列人数 × 年人均全成本）；外包、能源、维修按合同台账 + 定额测算；「其他项目直接费用」内含未分配的预算弹性储备。",
    "4. 费用预算方法：新增业务（数字化、非住拓展）用零基预算逐项论证；常规费用用滚动预算，以上年实际为基础调整。",
    "5. 面积口径：预算表与差异分析统一采用「加权平均在管面积」（12 个月月末在管面积的算术平均），与月结套表按期末面积计算的单方指标存在口径差，已在「02·收入预算」注明。",
    "6. 弹性条款：应急维修基金按在管面积 0.5 元/㎡/年计提（行业惯例），列示于「07·资本性支出与专项预算」。",
    "7. 预警规则：正向指标（收入、利润）完成率 ≥95% 绿灯、90%～95% 黄灯、<90% 红灯；反向指标（成本、费用）超支 ≤5% 绿灯、5%～15% 黄灯、>15% 红灯。",
    "8. 合同台账与财务数据的勾稽已逐项校验：600 份物业服务合同的面积、确认收入、应收账款分别等于在管面积、基础物业费收入、业主类应收账款；240 份采购合同的期末应付等于资产负债表应付账款。",
]:
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    c = ws.cell(r, 1, t); c.font = Font(FONT, 9.5, color="2A3A4A")
    c.alignment = Alignment("left", "center"); ws.row_dimensions[r].height = 18; r += 1
r += 1
r = band(ws, r, "三、工作表清单", 7)
r = head(ws, r, ["工作表", "模块", "内容", "", "", "", "行数/口径"])
ws.merge_cells(start_row=r-1, start_column=3, end_row=r-1, end_column=6)
CAT = [
    ("01·年度预算总表", "预算", "BUD 全年 P&L 及 12 个月分解，同步列示 LE 与差异", "12 月 × 全年"),
    ("02·收入预算", "预算", "驱动因子（面积 × 单价 × 收缴率）、分板块、分业态、分区域收缴率目标", "万元"),
    ("03·成本预算", "预算", "分科目预算（总额 + 单方双口径）、职工薪酬驱动因子、岗位序列人员预算", "万元 / 元·㎡·月"),
    ("04·期间费用预算", "预算", "税金及附加、销售、管理、研发、财务费用，按责任部门归口", "万元"),
    ("05·区域预算分解", "预算", "5 大区域 + 集团本部的收入、成本、毛利、费用、减值、营业利润目标", "万元"),
    ("06·城市公司预算", "预算", "50 家城市公司全年预算 vs 1-8 月实际 vs 完成率", "万元"),
    ("07·资本性支出与专项预算", "预算", "CAPEX 六大类、执行率、应急维修基金计提", "万元"),
    ("08·月度资金预算", "预算", "12 个月经营/投资/筹资现金流预算与资金余额，含 1-8 月实际对比", "万元"),
    ("09·预算执行分析", "分析", "1-8 月实际 vs 时间进度预算，17 项指标红黄绿灯预警", "万元"),
    ("10·利润桥与量价分解", "分析", "营业利润桥、归母净利桥、收入/成本量价分解、职工薪酬量价分解", "万元"),
    ("11·物业服务合同台账", "台账", "600 个在管项目，26 个字段（面积、单价、期限、收缴率、毛利率、续约状态）", "600 行"),
    ("12·合同结构与到期分析", "分析", "业态/来源/计费方式/到期分布/单价分层/退场候选池", "万元"),
    ("13·采购与外包合同台账", "台账", "240 份供应商合同，账期执行、锁价、履约评价", "240 行"),
    ("14·多经与增值服务合同台账", "台账", "160 份合作合同，分成模式、覆盖项目、业主共有收益归属", "160 行"),
    ("15·合同与预算联动分析", "分析", "合同覆盖率、到期风险敞口对预算的影响、成本锁价到期风险", "万元"),
]
for a, b_, c_, d_ in CAT:
    r = row(ws, r, [a, b_, c_, "", "", "", d_])
    ws.merge_cells(start_row=r-1, start_column=3, end_row=r-1, end_column=6)
    ws.cell(r-1, 3).alignment = Alignment("left", "center")
    ws.cell(r-1, 7).alignment = Alignment("center", "center")

# ==================== 01 年度预算总表 ====================
ws = sheet("01·年度预算总表", [30] + [11]*12 + [14, 14, 13, 13], freeze="B6", tab=NAVY_L)
r = title(ws, 1, "2026 年度预算总表（BUD-2026）", 17,
          f"{ENTITY_SHORT}  |  单位：万元  |  12 个月分解 + 全年合计，右侧列示滚动预测 LE 与差异")
r += 1
r = head(ws, r, ["项　目"] + MN + ["全年预算 BUD", "滚动预测 LE", "差异", "差异率"], h=26, size=9)
def pl_le(key, sub=None):
    if key == "rev":  return PL_FY["rev_total"]
    if key == "cogs": return PL_FY["cogs_total"]
    return None
def line(name, monthly, bud_total, le_total, bold=False, ind=0, pct=False, band_=False):
    global r
    fmt = PCT if pct else NUM
    vals = [name] + [(m if pct else w(m)) for m in monthly] + \
           [(bud_total if pct else w(bud_total)), (le_total if pct else w(le_total)),
            ((le_total-bud_total) if pct else w(le_total-bud_total)),
            (sdiv(le_total, bud_total) - 1 if not pct else "")]
    r = row(ws, r, vals, [fmt]*15 + [PCT1], bold=bold, indent=ind, size=9)
    d = le_total - bud_total
    ws.cell(r-1, 16).font = Font(FONT, 9, bold=True, color=GREEN if d >= 0 else RED)
    if not pct: ws.cell(r-1, 17).font = Font(FONT, 9, bold=True, color=GREEN if d >= 0 else RED)
r = band(ws, r, "一、营业收入", 17)
for k in BUD_REV:
    line(k, [BUD_M[m]["rev"][k] for m in range(12)], BUD_REV[k], le_rev(k), ind=1)
line("营业收入合计", [BUD_M[m]["rev_total"] for m in range(12)], BUD_REV_TOTAL, PL_FY["rev_total"], bold=True)
r = band(ws, r, "二、营业成本", 17)
for k in BUD_COGS:
    line(k, [BUD_M[m]["cogs"][k] for m in range(12)], BUD_COGS[k], CG_TOT_FY[COGS_KEYMAP[k]], ind=1)
line("营业成本合计", [BUD_M[m]["cogs_total"] for m in range(12)], BUD_COGS_TOTAL, PL_FY["cogs_total"], bold=True)
line("毛　利", [BUD_M[m]["gross"] for m in range(12)], BUD_GROSS, PL_FY["gross"], bold=True)
line("毛利率", [sdiv(BUD_M[m]["gross"], BUD_M[m]["rev_total"]) for m in range(12)],
     sdiv(BUD_GROSS, BUD_REV_TOTAL), sdiv(PL_FY["gross"], PL_FY["rev_total"]), bold=True, pct=True)
r = band(ws, r, "三、期间费用", 17)
for k in BUD_OPEX:
    line(k, [BUD_M[m]["opex"][k] for m in range(12)], BUD_OPEX[k], PL_FY["opex"][k], ind=1)
line("期间费用合计", [sum(BUD_M[m]["opex"].values()) for m in range(12)], BUD_OPEX_TOTAL, LE_OPEX_TOTAL, bold=True)
r = band(ws, r, "四、减值损失与其他损益", 17)
for k in BUD_IMPAIR:
    line(f"减：{k}", [BUD_M[m]["imp"][k] for m in range(12)], BUD_IMPAIR[k], PL_FY["impair"][k], ind=1)
for k in BUD_OTHER_INC:
    line(f"加：{k}", [BUD_M[m]["oi"][k] for m in range(12)], BUD_OTHER_INC[k], PL_FY["other_inc"][k], ind=1)
r = band(ws, r, "五、利润", 17)
line("营业利润", [BUD_M[m]["op"] for m in range(12)], BUD_OP, PL_FY["op_profit"], bold=True)
line("利润总额", [BUD_M[m]["ebt"] for m in range(12)], BUD_EBT, PL_FY["ebt"], bold=True)
line("减：所得税费用", [BUD_M[m]["tax"] for m in range(12)], BUD_TAX, PL_FY["tax"], ind=1)
line("净利润", [BUD_M[m]["net"] for m in range(12)], BUD_NET, PL_FY["net"], bold=True)
line("减：少数股东损益", [BUD_M[m]["mi"] for m in range(12)], BUD_MI, PL_FY["minority"], ind=1)
line("归属于母公司净利润", [BUD_M[m]["parent"] for m in range(12)], BUD_PARENT, PL_FY["parent"], bold=True)
line("归母净利率", [sdiv(BUD_M[m]["parent"], BUD_M[m]["rev_total"]) for m in range(12)],
     sdiv(BUD_PARENT, BUD_REV_TOTAL), sdiv(PL_FY["parent"], PL_FY["rev_total"]), bold=True, pct=True)
r = band(ws, r, "六、经营驱动指标", 17)
line("月末在管面积（万㎡）", [AREA_BUD_M[m]/1 for m in range(12)], AREA_BUD_M[-1], AREA_LE_M[-1], bold=False)
r = note(ws, r+1, [
    "预算与预测的差额集中在收入端（-%s 万元，-%.2f%%）与减值端（+%s 万元）；期间费用较预算节约 %s 万元，部分对冲。完整归因见「10·利润桥与量价分解」。" % (
        f"{abs(w(PL_FY['rev_total']-BUD_REV_TOTAL)):,.0f}", abs(sdiv(PL_FY['rev_total'], BUD_REV_TOTAL)-1)*100,
        f"{w(LE_IMPAIR_TOTAL-BUD_IMPAIR_TOTAL):,.0f}", f"{abs(w(LE_OPEX_TOTAL-BUD_OPEX_TOTAL)):,.0f}"),
    "预算月度分布的季节性假设弱于实际：编制期无法预见夏季能耗峰值与案场推盘节奏的偏移，因此 7-8 月实际毛利率低于预算，Q4 反之。",
], 17)

# ==================== 02 收入预算 ====================
ws = sheet("02·收入预算", [30, 15, 15, 14, 15, 15, 14, 13, 34], freeze="A6")
r = title(ws, 1, "收入预算与驱动因子", 9,
          f"{ENTITY_SHORT}  |  2026 年度  |  金额单位：万元；单价单位：元/㎡/月")
r += 1
r = band(ws, r, "一、基础物业管理费驱动因子（面积 × 单价 × 12）", 9)
r = head(ws, r, ["驱动因子", "BUD 预算", "LE 滚动预测", "差异", "PY 上年实际", "预算同比",
                 "", "", "口径说明"], h=26)
DRV = [
    ("年初在管面积（万㎡）", AREA_OPEN/WAN, AREA_OPEN/WAN, 1_845_00/100, NUM0, "2026-01-01 存量"),
    ("年末在管面积（万㎡）", AREA_BUD_M[-1]/WAN, AREA_LE_M[-1]/WAN, AREA_OPEN/WAN, NUM0, "12 月末在管"),
    ("加权平均在管面积（万㎡）", AREA_BUD_AVG/WAN, AREA_LE_AVG/WAN, 1_878_00/100, NUM0, "12 个月月末面积算术平均，收入预算的计算基数"),
    ("基础物业管理费（万元）", w(BUD_BASE_FEE), w(LE_BASE_FEE), w(int(LE_BASE_FEE/1.018)), NUM, "住宅 + 非住宅物业管理服务"),
    ("单方物业费（元/㎡/月）", BUD_BASE_FEE/AREA_BUD_AVG/12, LE_BASE_FEE/AREA_LE_AVG/12,
     1.7205, NUM4, "＝基础物业管理费 ÷ 加权平均面积 ÷ 12"),
    ("本年账单收缴率", COLL_BUD_ALL, COLL_RATE_CY, 0.8985, PCT, "BUD 按乐观档 92% 编制"),
    ("在管项目数（个）", 638, PROJECT_TOTAL, 578, NUM0, "年末在管项目"),
    ("合约面积（万㎡）", CONTRACT_AREA/WAN, CONTRACT_AREA/WAN, 2_452_00/100, NUM0, "含储备面积，合约在管比 1.27（行业 1.30）"),
]
for n, bd, le, py, fmt, memo in DRV:
    r = row(ws, r, [n, bd, le, le-bd, py, sdiv(bd, py)-1, "", "", memo],
            [fmt, fmt, fmt, fmt, PCT1, None, None])
    ws.cell(r-1, 4).font = Font(FONT, 9.5, bold=True, color=GREEN if le >= bd else RED)
    ws.cell(r-1, 9).alignment = Alignment("left", "center"); ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r += 1
r = band(ws, r, "二、在管面积增减预算（面积台账）", 9)
r = head(ws, r, ["项　目", "BUD 面积（万㎡）", "BUD 项目数", "LE 面积（万㎡）", "LE 项目数",
                 "面积差异", "项目数差异", "", "说　明"], h=26)
AM_MEMO = {"年初在管":"上年结转", "关联方开发交付":"关联房企新盘交付，受地产竣工节奏影响",
           "第三方市场外拓":"存量住宅、公建、城市服务招投标", "收并购承接":"城市公司及项目组合收购",
           "低质低效项目退场":"主动汰换，对标万物云 2024 年退出 53 个项目",
           "合同到期未续约":"业委会改聘或价格谈判破裂"}
ba = bp = la = lp = 0
for k, (bA, bP, lA, lP) in AREA_MOVE.items():
    if k != "年初在管": ba += bA; bp += bP; la += lA; lp += lP
    r = row(ws, r, [k, bA/WAN, bP, lA/WAN, lP, (lA-bA)/WAN, lP-bP, "", AM_MEMO[k]],
            [NUM0, NUM0, NUM0, NUM0, NUM0, NUM0, None], bold=(k == "年初在管"))
    ws.cell(r-1, 9).alignment = Alignment("left", "center"); ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["年末在管", AREA_BUD_M[-1]/WAN, 578+bp, AREA_LE_M[-1]/WAN, 578+lp,
                (AREA_LE_M[-1]-AREA_BUD_M[-1])/WAN, lp-bp, "", "净增：BUD +%.0f 万㎡ / LE +%.0f 万㎡" % (ba/WAN, la/WAN)],
        [NUM0, NUM0, NUM0, NUM0, NUM0, NUM0, None], bold=True, fill=GREY_D, top=True)
ws.cell(r-1, 9).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "三、分业务板块收入预算", 9)
r = head(ws, r, ["业务板块", "BUD 预算", "占比", "LE 滚动预测", "占比", "差异", "差异率",
                 "", "预算逻辑"], h=26)
SEG_LOGIC = {
    "住宅物业管理服务": "存量提价 + 新交付；单方 1.78 元，较上年 +1.9%",
    "非住宅物业管理服务": "战略重点，目标非住面积占比提至 33%",
    "案场协销及非业主增值服务": "跟随关联房企推盘计划，年初按持平编制",
    "社区增值服务": "美居、到家、经纪三条线，按合同台账逐份测算",
    "多种经营（车位·广告·场地）": "公共资源经营，160 份合作合同滚动",
    "顾问咨询及物资销售": "低毛利业务，年初计划收缩",
}
for s in SEG_MAP:
    bd, le = BUD_REV[s], le_rev(s)
    r = row(ws, r, [s, w(bd), sdiv(bd, BUD_REV_TOTAL), w(le), sdiv(le, PL_FY["rev_total"]),
                    w(le-bd), sdiv(le, bd)-1, "", SEG_LOGIC[s]],
            [NUM, PCT, NUM, PCT, NUM, PCT1, None])
    for cl in (6, 7): ws.cell(r-1, cl).font = Font(FONT, 9.5, bold=True, color=GREEN if le >= bd else RED)
    ws.cell(r-1, 9).alignment = Alignment("left", "center"); ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["合　计", w(BUD_REV_TOTAL), 1.0, w(PL_FY["rev_total"]), 1.0,
                w(PL_FY["rev_total"]-BUD_REV_TOTAL), sdiv(PL_FY["rev_total"], BUD_REV_TOTAL)-1, "", ""],
        [NUM, PCT, NUM, PCT, NUM, PCT1, None], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "四、分区域收缴率目标与实际", 9)
r = head(ws, r, ["区　域", "BUD 本年账单收缴率", "实际（1-8月）", "缺口（pct）", "BUD 综合收缴率",
                 "实际综合", "收缴缺口对应现金（万元）", "", "评　价"], h=32)
bill_base = BASE_FEE_REV_YTD * 1.048
for rg in REGIONS:
    bb, ba_ = COLL_BUD[rg]
    ac = REGIONS[rg]["coll"]
    share = REGPL_YTD[rg]["rev"] / PL_YTD["rev_total"]
    gap_cash = bill_base * share * (ac - bb)
    ev = "达标" if ac >= bb - 0.01 else ("轻度未达" if ac >= bb - 0.035 else "重点治理")
    r = row(ws, r, [rg, bb, ac, ac-bb, ba_, COLL_RATE_TOTAL * (ac/COLL_RATE_CY),
                    w(gap_cash), "", ev], [PCT, PCT, PCT1, PCT, PCT, NUM, None])
    ws.cell(r-1, 4).font = Font(FONT, 9.5, bold=True, color=GREEN if ac >= bb-0.01 else RED)
    ws.cell(r-1, 9).alignment = Alignment("center", "center")
    ws.cell(r-1, 9).font = Font(FONT, 9.5, bold=True, color=GREEN if ev == "达标" else (GOLD if ev == "轻度未达" else RED))
r = row(ws, r, ["加权合计", COLL_BUD_ALL, COLL_RATE_CY, COLL_RATE_CY-COLL_BUD_ALL, 0.8618,
                COLL_RATE_TOTAL, w(bill_base*(COLL_RATE_CY-COLL_BUD_ALL)), "", ""],
        [PCT, PCT, PCT1, PCT, PCT, NUM, None], bold=True, fill=GREY_D, top=True)
r = note(ws, r+1, [
    "口径提示：本表单方物业费按「加权平均在管面积」计算（BUD %.4f 元 / LE %.4f 元）；《月结财务套表》按期末在管面积计算为 %.4f 元，两者差异仅来自分母口径。" % (
        BUD_BASE_FEE/AREA_BUD_AVG/12, LE_BASE_FEE/AREA_LE_AVG/12, LE_BASE_FEE/AREA_TOTAL/12),
    "收缴率缺口 %.2f pct，对应本年现金流入减少约 %s 万元——这是收入未达预算之外、独立影响现金流的第二个缺口。" % (
        (COLL_RATE_CY-COLL_BUD_ALL)*100, f"{abs(w(bill_base*(COLL_RATE_CY-COLL_BUD_ALL))):,.0f}"),
    "行业对标：2024 年重点城市物业费平均收缴率 82%%（克而瑞物管），同比 -3pct；本模型综合收缴率 %.1f%%。" % (COLL_RATE_TOTAL*100),
], 9)

# ==================== 03 成本预算 ====================
ws = sheet("03·成本预算", [28, 14, 12, 13, 14, 12, 13, 13, 34], freeze="A6")
r = title(ws, 1, "成本预算（总额口径 + 单方口径双轨）", 9,
          f"{ENTITY_SHORT}  |  2026 年度  |  金额单位：万元；单方单位：元/㎡/月（按加权平均在管面积）")
r += 1
r = band(ws, r, "一、营业成本分科目预算", 9)
r = head(ws, r, ["成本科目", "BUD 预算", "占比", "BUD 单方", "LE 滚动预测", "占比", "LE 单方",
                 "单方差异", "预算编制方法"], h=30)
COST_METHOD = {
    "职工薪酬": "驱动因子法：岗位序列人数 × 年人均全成本（见下表）",
    "分包及外包服务费": "按 240 份外包合同年化金额 + 新拓项目定额",
    "能源费（水/电/气/暖）": "按面积定额 + 分时电价策略，未预见夏季高温峰值",
    "维修维护费": "设备台账 + 年度维保计划；含应急维修基金 %s 万元" % f"{w(EMERGENCY_FUND_BUD):,.0f}",
    "物料及低值易耗品": "集采协议价 × 消耗定额",
    "折旧与摊销": "固定资产及使用权资产台账滚动",
    "办公及差旅费": "滚动预算：上年实际 × (1 + 通胀调整)",
    "保险费及项目税费": "公众责任险、电梯险按面积投保",
    "其他项目直接费用": "零基预算 + 未分配弹性储备 %s 万元" % f"{w(BUD_COGS['其他项目直接费用']-CG_TOT_FY['其他直接费用']):,.0f}",
}
for k in BUD_COGS:
    bd, le = BUD_COGS[k], CG_TOT_FY[COGS_KEYMAP[k]]
    ub, ul = bd/AREA_BUD_AVG/12, le/AREA_LE_AVG/12
    r = row(ws, r, [k, w(bd), sdiv(bd, BUD_COGS_TOTAL), ub, w(le), sdiv(le, PL_FY["cogs_total"]),
                    ul, ul-ub, COST_METHOD[k]],
            [NUM, PCT, NUM4, NUM, PCT, NUM4, NUM4, None])
    ws.cell(r-1, 8).font = Font(FONT, 9.5, bold=True, color=GREEN if ul <= ub else RED)
    ws.cell(r-1, 9).alignment = Alignment("left", "center"); ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["营业成本合计", w(BUD_COGS_TOTAL), 1.0, BUD_UNIT["单方营业成本"],
                w(PL_FY["cogs_total"]), 1.0, LE_UNIT["单方营业成本"],
                LE_UNIT["单方营业成本"]-BUD_UNIT["单方营业成本"], "成本率 BUD %.2f%% / LE %.2f%%" % (
                    sdiv(BUD_COGS_TOTAL, BUD_REV_TOTAL)*100, sdiv(PL_FY["cogs_total"], PL_FY["rev_total"])*100)],
        [NUM, PCT, NUM4, NUM, PCT, NUM4, NUM4, None], bold=True, fill=GREY_D, top=True)
ws.cell(r-1, 9).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "二、职工薪酬驱动因子：岗位序列人员预算", 9)
r = head(ws, r, ["岗位序列", "BUD 编制人数", "BUD 年人均\n全成本（元）", "BUD 金额（万元）",
                 "实际在岗人数", "实际年人均\n全成本（元）", "实际金额（万元）", "人数差异", "人效说明"], h=34)
POS_MEMO = {"秩序维护（安保）":"预算按门岗优化 + 智能安防替代编制", "环境保洁":"预算按机械化清洁提升人效",
            "工程设备维保":"技术型岗位，预算增加权重", "客服及管家":"线上化替代部分前台",
            "绿化养护":"部分外包，自有编制压缩", "项目及区域管理":"区域扁平化，管理半径压缩",
            "职能与共享中心":"共享服务中心集中，预算压减"}
for k in HC_BUD:
    bn, bc = HC_BUD[k]; an, ac = HC_ACT[k]
    r = row(ws, r, [k, bn, bc, w(bn*bc), an, ac, w(an*ac), an-bn, POS_MEMO[k]],
            [NUM0, NUM0, NUM, NUM0, NUM0, NUM, NUM0, None])
    ws.cell(r-1, 8).font = Font(FONT, 9.5, bold=True, color=GREEN if an <= bn else RED)
    ws.cell(r-1, 9).alignment = Alignment("left", "center"); ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["合　计", HC_BUD_TOTAL, BUD_UNIT_STAFF, w(BUD_STAFF_ALL), HC_ACT_TOTAL,
                ACT_UNIT_STAFF, w(ACT_STAFF_ALL_CHK), HC_ACT_TOTAL-HC_BUD_TOTAL,
                "含计入期间费用部分 BUD %s 万元 / 实际 %s 万元" % (
                    f"{w(BUD_STAFF_OPEX):,.0f}", f"{w(ACT_STAFF_OPEX):,.0f}")],
        [NUM0, NUM0, NUM, NUM0, NUM0, NUM, NUM0, None], bold=True, fill=GREY_D, top=True)
ws.cell(r-1, 9).alignment = Alignment("left", "center")
r = row(ws, r, ["人均在管面积（㎡/人）", AREA_BUD_M[-1]/HC_BUD_TOTAL, "", "",
                AREA_TOTAL/HEADCOUNT_OWN, "", "", AREA_TOTAL/HEADCOUNT_OWN - AREA_BUD_M[-1]/HC_BUD_TOTAL,
                "行业 8,528 ㎡（50 家上市物企 2024 年，同比 +9.3%）"],
        [NUM0, None, None, NUM0, None, None, NUM0, None], fill=GREY)
ws.cell(r-1, 9).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "三、职工薪酬量价分解（BUD → 实际）", 9)
r = head(ws, r, ["分解项", "金额（万元）", "说　明", "", "", "", "", "", ""], h=22)
for n, v, memo in [
    ("BUD 职工薪酬预算总额", BUD_STAFF_ALL, "%d 人 × %.0f 元/人·年" % (HC_BUD_TOTAL, BUD_UNIT_STAFF)),
    ("① 人数差异（不利）", STAFF_VAR_QTY, "超编 %d 人 × 预算人均 %.0f 元＝人效目标未达成" % (
        HC_ACT_TOTAL-HC_BUD_TOTAL, BUD_UNIT_STAFF)),
    ("② 人均成本差异（有利）", STAFF_VAR_PRICE, "人均下降 %.0f 元 × 实际 %d 人＝控薪、减少加班、结构性用工" % (
        BUD_UNIT_STAFF-ACT_UNIT_STAFF, HC_ACT_TOTAL)),
    ("实际职工薪酬总额", ACT_STAFF_ALL_CHK, "%d 人 × %.0f 元/人·年" % (HC_ACT_TOTAL, ACT_UNIT_STAFF)),
]:
    bold = "①" not in n and "②" not in n
    r = row(ws, r, [n, w(v), memo, "", "", "", "", "", ""], [NUM, None]*4, bold=bold,
            fill=GREY_D if bold else None)
    ws.merge_cells(start_row=r-1, start_column=3, end_row=r-1, end_column=9)
    ws.cell(r-1, 3).alignment = Alignment("left", "center")
    ws.cell(r-1, 3).font = Font(FONT, 8.5, color="6B7B8C")
    if not bold: ws.cell(r-1, 2).font = Font(FONT, 9.5, bold=True, color=RED if v > 0 else GREEN)
r = note(ws, r+1, [
    "关键读法：营业成本总额较预算节约 %s 万元，但单方成本仅从 %.4f 元降至 %.4f 元——总额节约主要来自在管面积未达预算（少 %.0f 万㎡），并非单位效率改善。" % (
        f"{abs(w(PL_FY['cogs_total']-BUD_COGS_TOTAL)):,.0f}", BUD_UNIT["单方营业成本"], LE_UNIT["单方营业成本"],
        (AREA_BUD_AVG-AREA_LE_AVG)/WAN),
    "职工薪酬是唯一单方超预算的大项（BUD %.4f 元 → 实际 %.4f 元）：超编 %d 人未能通过人效提升消化，只能靠压低人均成本对冲，这对服务品质与人员留存是风险敞口。" % (
        BUD_COGS["职工薪酬"]/AREA_BUD_AVG/12, CG_TOT_FY["职工薪酬"]/AREA_LE_AVG/12, HC_ACT_TOTAL-HC_BUD_TOTAL),
    "能源费是唯一总额也超预算的科目（+%s 万元）：夏季高温与电价上行未在年初预算中充分体现。" % f"{w(CG_TOT_FY['能源费']-BUD_COGS['能源费（水/电/气/暖）']):,.0f}",
], 9)

# ==================== 04 期间费用预算 ====================
ws = sheet("04·期间费用预算", [26, 14, 12, 14, 12, 13, 13, 18, 30], freeze="A6")
r = title(ws, 1, "期间费用预算（按费用类型与责任部门归口）", 9,
          f"{ENTITY_SHORT}  |  2026 年度  |  单位：万元")
r += 1
r = band(ws, r, "一、期间费用总览", 9)
r = head(ws, r, ["费用项目", "BUD 预算", "费用率", "LE 滚动预测", "费用率", "差异", "差异率",
                 "责任部门", "预算方法"], h=28)
OPEX_OWNER = {"税金及附加": "财务共享中心", "销售费用": "市场拓展中心", "管理费用": "总部职能 + 区域管理部",
              "研发费用": "数字科技中心", "财务费用": "资金管理部"}
OPEX_METHOD = {"税金及附加": "按增值税及附加、房产税测算", "销售费用": "零基预算：投标、品牌、拓展激励逐项论证",
               "管理费用": "滚动预算 + 共享中心集约化压减目标 -3%",
               "研发费用": "零基预算：智慧物业平台、AI 客服、清洁机器人",
               "财务费用": "净利息收入，理财收益与借款利息轧差"}
for k in BUD_OPEX:
    bd, le = BUD_OPEX[k], PL_FY["opex"][k]
    r = row(ws, r, [k, w(bd), sdiv(bd, BUD_REV_TOTAL), w(le), sdiv(le, PL_FY["rev_total"]),
                    w(le-bd), sdiv(le, bd)-1 if bd else "", OPEX_OWNER[k], OPEX_METHOD[k]],
            [NUM, PCT, NUM, PCT, NUM, PCT1, None, None])
    ws.cell(r-1, 6).font = Font(FONT, 9.5, bold=True, color=GREEN if le <= bd else RED)
    for cl in (8, 9): ws.cell(r-1, cl).alignment = Alignment("left", "center")
    ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["期间费用合计", w(BUD_OPEX_TOTAL), sdiv(BUD_OPEX_TOTAL, BUD_REV_TOTAL),
                w(LE_OPEX_TOTAL), sdiv(LE_OPEX_TOTAL, PL_FY["rev_total"]),
                w(LE_OPEX_TOTAL-BUD_OPEX_TOTAL), sdiv(LE_OPEX_TOTAL, BUD_OPEX_TOTAL)-1,
                "", "行业平均管理费率 9.4%（2024 年上市物企）"],
        [NUM, PCT, NUM, PCT, NUM, PCT1, None, None], bold=True, fill=GREY_D, top=True)
ws.cell(r-1, 9).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "二、管理费用明细预算", 9)
r = head(ws, r, ["明细项目", "BUD 预算", "占比", "1-8月实际", "时间进度完成率", "全年预计", "差异",
                 "责任部门", "备　注"], h=28)
MGMT_DETAIL = OrderedDict([
    ("职工薪酬（管理人员）", (0.620, "总部职能 + 区域管理部", "含共享中心集中后的职能人员")),
    ("折旧与摊销",         (0.086, "财务共享中心", "办公资产、ERP 及智慧平台摊销")),
    ("办公及租赁费",        (0.072, "行政管理部", "总部及区域办公场地租赁")),
    ("差旅与会议费",        (0.048, "各归口部门", "项目巡检、品质飞检、投标差旅")),
    ("咨询审计及专业服务",   (0.042, "财务共享中心", "年审、税务、法律、管理咨询")),
    ("培训与人才发展",       (0.036, "人力资源部", "服务标准化培训、技能考证")),
    ("信息化运维",         (0.034, "数字科技中心", "系统运维、云资源、通讯")),
    ("业务招待及公关",       (0.022, "各归口部门", "—")),
    ("其他管理费用",        (0.040, "行政管理部", "零星支出及预算弹性")),
])
mb, ma = BUD_OPEX["管理费用"], PL_YTD["opex"]["管理费用"]
acc_b = acc_a = 0
mk = list(MGMT_DETAIL)
for i, k in enumerate(mk):
    sh, owner, memo = MGMT_DETAIL[k]
    bd = (mb - acc_b) if i == len(mk)-1 else int(round(mb * sh))
    ac = (ma - acc_a) if i == len(mk)-1 else int(round(ma * sh * (1.02 if "职工" in k else 0.94)))
    acc_b += bd; acc_a += ac
    fy = int(round(ac / PROG_OPEX))
    r = row(ws, r, [k, w(bd), sdiv(bd, mb), w(ac), sdiv(ac, bd*PROG_OPEX) if bd else "", w(fy),
                    w(fy-bd), owner, memo], [NUM, PCT, NUM, PCT1, NUM, NUM, None, None])
    ws.cell(r-1, 7).font = Font(FONT, 9.5, bold=True, color=GREEN if fy <= bd else RED)
    for cl in (8, 9): ws.cell(r-1, cl).alignment = Alignment("left", "center")
    ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["管理费用合计", w(mb), 1.0, w(ma), sdiv(ma, mb*PROG_OPEX), w(PL_FY["opex"]["管理费用"]),
                w(PL_FY["opex"]["管理费用"]-mb), "", ""],
        [NUM, PCT, NUM, PCT1, NUM, NUM, None, None], bold=True, fill=GREY_D, top=True)
r = note(ws, r+1, [
    "预算进度基准：期间费用 1-8 月对应预算进度 %.2f%%（按月度分布系数，非简单 8/12＝66.67%%）。" % (PROG_OPEX*100),
    "期间费用率由预算 %.2f%% 降至预测 %.2f%%，是本年唯一优于预算的主要科目——但需注意其中含收入下降带来的被动摊薄效应，绝对额节约仅 %s 万元。" % (
        sdiv(BUD_OPEX_TOTAL, BUD_REV_TOTAL)*100, sdiv(LE_OPEX_TOTAL, PL_FY["rev_total"])*100,
        f"{abs(w(LE_OPEX_TOTAL-BUD_OPEX_TOTAL)):,.0f}"),
], 9)

# ==================== 05 区域预算分解 ====================
ws = sheet("05·区域预算分解", [17, 13, 13, 13, 11, 13, 13, 13, 13, 12, 13, 13, 12, 13], freeze="B6")
r = title(ws, 1, "区域预算分解与责任指标", 14,
          f"{ENTITY_SHORT}  |  2026 年度  |  单位：万元；总部费用与减值已按收入 / 应收权重分摊")
r += 1
r = head(ws, r, ["区　域", "年末在管面积\n（万㎡）", "营业收入\n预算", "营业成本\n预算", "毛利率\n目标",
                 "期间费用\n预算", "减值损失\n预算", "营业利润\n预算", "1-8月实际\n营业利润",
                 "完成率", "收入\n1-8月实际", "收入\n完成率", "收缴率\n目标", "收缴率\n实际"], h=36)
tb = defaultdict(int)
for rg in list(REGIONS) + [HQ_NAME]:
    B = REG_BUD[rg]; A = REGPL_YTD[rg]
    coll_b = COLL_BUD[rg][0] if rg in COLL_BUD else ""
    coll_a = REGIONS[rg]["coll"] if rg in REGIONS else ""
    r = row(ws, r, [rg, B["area"]/WAN if B["area"] else "", w(B["rev"]), w(B["cogs"]),
                    sdiv(B["gross"], B["rev"]) if B["rev"] else "", w(B["opex"]), w(B["impair"]),
                    w(B["op"]), w(A["op"]), sdiv(A["op"], B["op"]) if B["op"] else "",
                    w(A["rev"]), sdiv(A["rev"], B["rev"]) if B["rev"] else "", coll_b, coll_a],
            [NUM0, NUM, NUM, PCT, NUM, NUM, NUM, NUM, PCT1, NUM, PCT1, PCT, PCT],
            bold=(rg == HQ_NAME))
    if B["op"]:
        cr = A["op"]/B["op"]
        ws.cell(r-1, 10).font = Font(FONT, 9.5, bold=True,
            color=GREEN if cr >= PROG_OP else (GOLD if cr >= PROG_OP-0.06 else RED))
    if B["rev"]:
        cr2 = A["rev"]/B["rev"]
        ws.cell(r-1, 12).font = Font(FONT, 9.5, bold=True,
            color=GREEN if cr2 >= PROG_REV else (GOLD if cr2 >= PROG_REV-0.06 else RED))
    if coll_a != "":
        ws.cell(r-1, 14).font = Font(FONT, 9.5, bold=True, color=GREEN if coll_a >= coll_b-0.01 else RED)
    for k in ("rev","cogs","opex","impair","op"): tb[k] += B[k]
    tb["area"] += B["area"]; tb["arev"] += A["rev"]; tb["aop"] += A["op"]
r = row(ws, r, ["合　计", tb["area"]/WAN, w(tb["rev"]), w(tb["cogs"]),
                sdiv(tb["rev"]-tb["cogs"], tb["rev"]), w(tb["opex"]), w(tb["impair"]), w(tb["op"]),
                w(tb["aop"]), sdiv(tb["aop"], tb["op"]), w(tb["arev"]), sdiv(tb["arev"], tb["rev"]),
                COLL_BUD_ALL, COLL_RATE_CY],
        [NUM0, NUM, NUM, PCT, NUM, NUM, NUM, NUM, PCT1, NUM, PCT1, PCT, PCT],
        bold=True, fill=GREY_D, top=True)
r = row(ws, r, ["校验：与预算总表差异", "", w(tb["rev"]-BUD_REV_TOTAL), w(tb["cogs"]-BUD_COGS_TOTAL), "",
                w(tb["opex"]-BUD_OPEX_TOTAL), w(tb["impair"]-BUD_IMPAIR_TOTAL),
                w(tb["op"]-(BUD_GROSS-BUD_OPEX_TOTAL-BUD_IMPAIR_TOTAL)), "", "", "", "", "", ""],
        [None, NUM, NUM, None, NUM, NUM, NUM, None, None, None, None, None, None],
        bold=True, fill="E6F2EA")
r = note(ws, r+1, [
    "预算进度基准：收入 %.2f%%、营业利润 %.2f%%（1-8 月预算占全年比重；预算季节性后置，故低于日历进度 66.67%%）。完成率低于该基准即为落后。" % (
        PROG_REV*100, PROG_OP*100),
    "区域预算的毛利率目标按能级设定（华东 22.0% → 西部 17.8%），减值预算按各区域应收账款权重分摊，收缴率差的区域自动承担更高的减值指标。",
    "集团本部不承担收入，其营业成本为集中化的品质巡检、集采中心与共享服务中心成本，期间费用为总部职能费用（占集团期间费用 22%）。",
], 14)

# ==================== 06 城市公司预算 ====================
ws = sheet("06·城市公司预算", [12, 17, 12, 13, 13, 11, 12, 13, 13, 12, 13, 13, 12, 11], freeze="C6")
r = title(ws, 1, "城市公司预算与执行", 14,
          f"{ENTITY_SHORT}  |  2026 年度  |  单位：万元  |  50 家城市公司")
r += 1
r = head(ws, r, ["区　域", "城市公司", "年末在管\n（万㎡）", "收入预算", "成本预算", "毛利率\n目标",
                 "费用预算", "减值预算", "营业利润\n预算", "1-8月\n实际收入", "收入\n完成率",
                 "1-8月实际\n营业利润", "利润\n完成率", "预警"], h=36)
BUD_BY_CITY = {(c["region"], c["city"]): c for c in CITY_BUD}
cur = None
for A in CITY_ROWS:
    B = BUD_BY_CITY[(A["region"], A["city"])]
    if A["region"] != cur:
        cur = A["region"]
        RB = REG_BUD[cur]
        r = band(ws, r, "%s　（收入预算 %s 万元 · 毛利率目标 %.2f%% · 营业利润预算 %s 万元）" % (
            cur, f"{w(RB['rev']):,.0f}", sdiv(RB["gross"], RB["rev"])*100, f"{w(RB['op']):,.0f}"), 14)
    cr = sdiv(A["rev"], B["rev"]); cp = sdiv(A["op"], B["op"]) if B["op"] else 0
    lt = "绿灯" if cp >= PROG_OP else ("黄灯" if cp >= PROG_OP - 0.06 else "红灯")
    r = row(ws, r, ["", A["city"], B["area"]/WAN, w(B["rev"]), w(B["cogs"]),
                    sdiv(B["gross"], B["rev"]), w(B["opex"]), w(B["impair"]), w(B["op"]),
                    w(A["rev"]), cr, w(A["op"]), cp, lt],
            [None, NUM0, NUM, NUM, PCT, NUM, NUM, NUM, NUM, PCT1, NUM, PCT1, None], size=9)
    ws.cell(r-1, 11).font = Font(FONT, 9, bold=True, color=GREEN if cr >= PROG_OP else (GOLD if cr >= PROG_OP-0.06 else RED))
    ws.cell(r-1, 13).font = Font(FONT, 9, bold=True, color=GREEN if cp >= PROG_OP else (GOLD if cp >= PROG_OP-0.06 else RED))
    ws.cell(r-1, 14).alignment = Alignment("center", "center")
    ws.cell(r-1, 14).font = Font(FONT, 9, bold=True, color=GREEN if lt == "绿灯" else (AMBER if lt == "黄灯" else RED))
T = lambda k, s: sum(x[k] for x in s)
r = row(ws, r, ["合　计", "50 家", T("area", CITY_BUD)/WAN, w(T("rev", CITY_BUD)), w(T("cogs", CITY_BUD)),
                sdiv(T("gross", CITY_BUD), T("rev", CITY_BUD)), w(T("opex", CITY_BUD)),
                w(T("impair", CITY_BUD)), w(T("op", CITY_BUD)), w(T("rev", CITY_ROWS)),
                sdiv(T("rev", CITY_ROWS), T("rev", CITY_BUD)), w(T("op", CITY_ROWS)),
                sdiv(T("op", CITY_ROWS), T("op", CITY_BUD)), ""],
        [None, NUM0, NUM, NUM, PCT, NUM, NUM, NUM, NUM, PCT1, NUM, PCT1, None],
        bold=True, fill=GREY_D, top=True)
red = [A for A in CITY_ROWS if sdiv(A["op"], BUD_BY_CITY[(A["region"], A["city"])]["op"]) < PROG_OP - 0.06]
r = note(ws, r+1, [
    "预算进度基准：收入 %.2f%%、营业利润 %.2f%%。红灯（营业利润完成率低于基准 6 pct 以上）%d 家：%s。" % (
        PROG_REV*100, PROG_OP*100, len(red), "、".join(x["city"] for x in red[:10]) + ("等" if len(red) > 10 else "")),
    "城市公司预算按区域内规模权重与毛利率分档拆分，口径与《月结财务套表》「11·城市公司明细表」完全一致，可直接横向比对。",
], 14)

# ==================== 07 资本性支出与专项预算 ====================
ws = sheet("07·资本性支出与专项预算", [26, 14, 12, 14, 12, 13, 13, 14, 32], freeze="A6")
r = title(ws, 1, "资本性支出与专项预算", 9,
          f"{ENTITY_SHORT}  |  2026 年度  |  单位：万元")
r += 1
r = band(ws, r, "一、资本性支出（CAPEX）预算与执行", 9)
r = head(ws, r, ["支出类别", "全年预算", "占比", "1-8月实际", "执行率", "全年预计", "预算余额",
                 "现金流量表归属", "内　容"], h=30)
CAPEX_CF = {"项目设施设备更新改造": "购建固定资产等支付的现金", "智慧物业与数字化投入": "购建固定资产等支付的现金",
            "车辆及工程装备": "购建固定资产等支付的现金", "办公场所及信息化": "购建固定资产等支付的现金",
            "收并购股权对价": "取得子公司支付的现金净额", "新项目前期投入": "购建固定资产等支付的现金"}
for k, (bd, ac, memo) in CAPEX_BUD.items():
    fy = int(round(ac / 0.62))
    r = row(ws, r, [k, w(bd), sdiv(bd, CAPEX_BUD_TOTAL), w(ac), sdiv(ac, bd), w(fy), w(bd-fy),
                    CAPEX_CF[k], memo], [NUM, PCT, NUM, PCT1, NUM, NUM, None, None])
    ws.cell(r-1, 5).font = Font(FONT, 9.5, bold=True,
        color=GREEN if sdiv(ac, bd) >= 0.55 else (GOLD if sdiv(ac, bd) >= 0.40 else RED))
    for cl in (8, 9): ws.cell(r-1, cl).alignment = Alignment("left", "center")
    ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
cap_fy = int(round(CAPEX_ACT_YTD / 0.62))
r = row(ws, r, ["CAPEX 合计", w(CAPEX_BUD_TOTAL), 1.0, w(CAPEX_ACT_YTD),
                sdiv(CAPEX_ACT_YTD, CAPEX_BUD_TOTAL), w(cap_fy), w(CAPEX_BUD_TOTAL-cap_fy), "", ""],
        [NUM, PCT, NUM, PCT1, NUM, NUM, None, None], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "二、专项与弹性预算", 9)
r = head(ws, r, ["专项预算", "计提标准", "预算金额", "1-8月已使用", "使用率", "余额", "",
                 "", "依　据"], h=28)
SPEC = [
    ("应急维修基金", "在管面积 0.5 元/㎡/年", EMERGENCY_FUND_BUD, int(EMERGENCY_FUND_BUD*0.512),
     "行业弹性预算惯例，应对电梯困人、管网爆裂等突发状况；已计入维修维护费预算"),
    ("其他项目直接费用弹性储备", "未分配预算池",
     BUD_COGS["其他项目直接费用"]-CG_TOT_FY["其他直接费用"], 0,
     "零基预算未分配部分，年内未动用则直接形成成本节约"),
    ("品质提升与创优专项", "按收入 0.18%", int(round(BUD_REV_TOTAL*0.0018)), int(round(BUD_REV_TOTAL*0.0018*0.44)),
     "服务标准化、创优评奖、业主满意度提升，防止收缴率进一步下滑"),
    ("专项维修资金（代管）", "不计入公司损益", int(3.85*YI), int(3.85*YI*0.38),
     "发改价格〔2003〕1864 号：大修、中修、更新改造从专项维修资金列支，不得计入物业服务成本"),
]
for n, std, bd, used, memo in SPEC:
    r = row(ws, r, [n, std, w(bd), w(used), sdiv(used, bd), w(bd-used), "", "", memo],
            [None, NUM, NUM, PCT1, NUM, None, None, None])
    for cl in (2, 9): ws.cell(r-1, cl).alignment = Alignment("left", "center")
    ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r = note(ws, r+1, [
    "CAPEX 执行率仅 %.1f%%（时间进度 66.7%%）：收并购对价与数字化投入两项主动放缓，与收入未达预算下的现金优先策略一致。" % (
        sdiv(CAPEX_ACT_YTD, CAPEX_BUD_TOTAL)*100),
    "「专项维修资金」为业主共有资金，公司仅代管，既不计入收入也不计入成本，不出现在利润表与资产负债表的损益类科目，此处列示供 FA 区分口径。",
], 9)

# ==================== 08 月度资金预算 ====================
ws = sheet("08·月度资金预算", [16] + [13]*6 + [14, 13, 30], freeze="A6")
r = title(ws, 1, "月度资金预算与执行", 10,
          f"{ENTITY_SHORT}  |  2026 年度  |  单位：万元")
r += 1
r = head(ws, r, ["月　份", "期初资金", "经营活动\n净现金流", "投资活动\n净现金流", "筹资活动\n净现金流",
                 "当月净变动", "期末资金", "实际期末资金", "差　异", "资金安排说明"], h=32)
CASH_MEMO = {1: "春节前发放上年年终奖，全年资金低点", 2: "春节假期，收缴与支付双低",
             3: "Q1 物业费集中催缴", 5: "年度股东分红 8,500 万元", 6: "Q2 收缴冲刺",
             7: "夏季能耗与高温津贴支付高峰", 8: "秋季收缴启动",
             11: "Q4 催收高峰，全年现金主要来源", 12: "年末集中回款与供应商结算"}
ACT_CASH_M = {8: BSD_C["货币资金"]}
for x in CASH_BUD_ROWS:
    m = x["m"]
    act = ACT_CASH_M.get(m, "")
    r = row(ws, r, [f"{PERIOD_Y}年{m:02d}月", w(x["open"]), w(x["op"]), w(x["inv"]), w(x["fin"]),
                    w(x["net"]), w(x["close"]), w(act) if act else "",
                    w(act-x["close"]) if act else "", CASH_MEMO.get(m, "")],
            [NUM, NUM, NUM, NUM, NUM, NUM, NUM, NUM, None],
            fill="FFF6E5" if m == PERIOD_M else None)
    for cl in (3, 4, 5, 6):
        v = ws.cell(r-1, cl).value
        if isinstance(v, float): ws.cell(r-1, cl).font = Font(FONT, 9.5, color=GREEN if v >= 0 else RED)
    if act: ws.cell(r-1, 9).font = Font(FONT, 9.5, bold=True, color=RED)
    ws.cell(r-1, 10).alignment = Alignment("left", "center"); ws.cell(r-1, 10).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["全年合计", w(CASH_OPEN), w(sum(CASH_OP_BUD)), w(sum(CASH_INV_BUD)),
                w(sum(CASH_FIN_BUD)), w(sum(CASH_OP_BUD)+sum(CASH_INV_BUD)+sum(CASH_FIN_BUD)),
                w(CASH_BUD_ROWS[-1]["close"]), "", "", ""],
        [NUM, NUM, NUM, NUM, NUM, NUM, NUM, NUM, None], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "1-8 月资金执行对比", 10)
r = head(ws, r, ["项　目", "预算（1-8月）", "实际（1-8月）", "差　异", "达成率", "", "", "", "", "说　明"], h=24)
CB8 = dict(op=sum(CASH_OP_BUD[:8]), inv=sum(CASH_INV_BUD[:8]), fin=sum(CASH_FIN_BUD[:8]))
CB8["net"] = sum(CB8.values()); CB8["close"] = CASH_BUD_ROWS[7]["close"]
for n, k, memo in [("经营活动现金流量净额", "op", "收缴率缺口与应收账款增加是主要拖累"),
                   ("投资活动现金流量净额", "inv", "并购与数字化投入放缓，好于预算"),
                   ("筹资活动现金流量净额", "fin", "分红与租赁付款按计划执行"),
                   ("现金及现金等价物净变动", "net", ""),
                   ("期末资金余额", "close", "与资产负债表货币资金一致")]:
    bd = CB8[k]; ac = CASH_ACT_YTD[k]
    r = row(ws, r, [n, w(bd), w(ac), w(ac-bd), sdiv(ac, bd) if bd else "", "", "", "", "", memo],
            [NUM, NUM, NUM, PCT1, None, None, None, None, None], bold=(k in ("net", "close")))
    ws.cell(r-1, 4).font = Font(FONT, 9.5, bold=True, color=GREEN if ac >= bd else RED)
    ws.cell(r-1, 10).alignment = Alignment("left", "center"); ws.cell(r-1, 10).font = Font(FONT, 8.5, color="6B7B8C")
r = note(ws, r+1, [
    "1-8 月末实际资金 %s 万元，低于预算 %s 万元，缺口全部来自经营活动（实际 %s 万元 vs 预算 %s 万元）。" % (
        f"{w(CASH_ACT_YTD['close']):,.0f}", f"{abs(w(CASH_ACT_YTD['close']-CB8['close'])):,.0f}",
        f"{w(CASH_ACT_YTD['op']):,.0f}", f"{w(CB8['op']):,.0f}"),
    "资金预算的季节性形态与行业一致：1 月为全年低点（发放上年年终奖），Q4 为回款高峰，全年经营净现金的 %.0f%% 集中在 10-12 月。" % (
        sum(CASH_OP_BUD[9:]) / sum(CASH_OP_BUD) * 100),
], 10)

# ==================== 09 预算执行分析 ====================
ws = sheet("09·预算执行分析", [30, 14, 14, 13, 12, 14, 12, 11, 34], freeze="A6")
r = title(ws, 1, "预算执行分析（1-8 月）", 9,
          f"{ENTITY_SHORT}  |  {YTD_LABEL}  |  单位：万元  |  日历进度 66.67%  |  "
          f"预算进度：收入 {PROG_REV*100:.2f}% · 营业利润 {PROG_OP*100:.2f}%")
r += 1
r = head(ws, r, ["指　标", "1-8月预算", "1-8月实际", "差　异", "达成率", "全年预算",
                 "全年预算完成率", "预警", "分析要点"], h=30)
EXEC_MEMO = {
    "营业收入": "缺口的 78% 来自基础物业费（面积未达预算），22% 来自案场与增值服务",
    "　其中：基础物业管理费": "量差 -12,786 万元 / 价差 -10,214 万元（年化口径）",
    "　　　　案场协销及非业主增值": "关联房企推盘不及预期，行业性收缩",
    "　　　　社区增值及多种经营": "美居、经纪受地产成交拖累；多经基本达标",
    "营业成本": "总额节约但单方成本仅微降，节约主要来自面积未达标",
    "　其中：职工薪酬": "超编 1,800 人，靠压低人均成本对冲，单方成本仍超预算",
    "　　　　分包及外包服务费": "随面积同步减少，属被动节约",
    "　　　　能源费": "唯一总额超预算科目：夏季高温 + 电价上行",
    "　　　　维修维护费": "低于预算，需警惕维修递延带来的次年集中支出",
    "毛利": "毛利率 18.05% vs 预算 18.71%，缺口 0.66pct",
    "期间费用合计": "本年唯一优于预算的主要板块",
    "　其中：管理费用": "共享中心集约化见效",
    "　　　　销售费用": "外拓投入随目标下调而压减，与收入缺口互为因果",
    "　　　　研发费用": "数字化项目延期，需评估对次年人效目标的影响",
    "信用减值损失": "收缴率缺口 4.02pct 直接传导，是利润缺口的第二大来源",
    "营业利润": "达成率显著低于时间进度",
    "归属于母公司净利润": "全年预算完成率仅 %.1f%%，预算进度基准 62.53%%",
}
for name, bd, ac, fy, dirn in EXEC_ROWS:
    lt, rate = light(bd, ac, dirn)
    achieve = sdiv(ac, bd)
    memo = EXEC_MEMO.get(name, "")
    if "%.1f%%" in memo: memo = memo % (sdiv(ac, fy)*100)
    r = row(ws, r, [name, w(bd), w(ac), w(ac-bd), achieve, w(fy), sdiv(ac, fy), lt, memo],
            [NUM, NUM, NUM, PCT1, NUM, PCT1, None, None],
            bold=(name in ("营业收入", "营业成本", "毛利", "营业利润", "归属于母公司净利润")),
            indent=(1 if name.startswith("　") else 0))
    good = (ac >= bd) if dirn == "正向" else (ac <= bd)
    ws.cell(r-1, 4).font = Font(FONT, 9.5, bold=True, color=GREEN if good else RED)
    ws.cell(r-1, 5).font = Font(FONT, 9.5, bold=True, color=GREEN if good else RED)
    ws.cell(r-1, 8).alignment = Alignment("center", "center")
    ws.cell(r-1, 8).font = Font(FONT, 9.5, bold=True,
        color=GREEN if lt == "绿灯" else (AMBER if lt == "黄灯" else RED))
    ws.cell(r-1, 9).alignment = Alignment("left", "center"); ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r += 1
r = band(ws, r, "预警规则与触发处置", 9)
r = head(ws, r, ["指标类型", "绿灯", "黄灯", "红灯", "触发处置", "", "", "", ""], h=24)
for a, b_, c_, d_, e_ in [
    ("正向指标（收入、毛利、利润）", "达成率 ≥95%", "90% ≤ 达成率 <95%", "达成率 <90%",
     "黄灯：区域月度经营分析会说明；红灯：启动预算调整程序，提交调整方案"),
    ("反向指标（成本、费用、减值）", "超支 ≤5%", "5% < 超支 ≤15%", "超支 >15%",
     "黄灯：归口部门专项说明；红灯：立即整改并冻结非必要支出"),
    ("累计偏差", "≤10%", "—", ">10%", "偏差超 10% 触发预算调整流程；连续两季度偏差 >15% 扣减部门绩效"),
]:
    r = row(ws, r, [a, b_, c_, d_, e_, "", "", "", ""])
    ws.merge_cells(start_row=r-1, start_column=5, end_row=r-1, end_column=9)
    for cl in (2, 3, 4): ws.cell(r-1, cl).alignment = Alignment("center", "center")
    ws.cell(r-1, 5).alignment = Alignment("left", "center")
    ws.cell(r-1, 5).font = Font(FONT, 8.5, color="6B7B8C")
lights = defaultdict(list)
for name, bd, ac, fy, dirn in EXEC_ROWS:
    lights[light(bd, ac, dirn)[0]].append(name.strip("　"))
r = note(ws, r+1, [
    "灯号汇总：绿灯 %d 项 / 黄灯 %d 项 / 红灯 %d 项。" % (
        len(lights["绿灯"]), len(lights["黄灯"]), len(lights["红灯"])),
    "红灯项：%s。" % ("、".join(lights["红灯"]) if lights["红灯"] else "无"),
    "黄灯项：%s。" % ("、".join(lights["黄灯"]) if lights["黄灯"] else "无"),
    "累计偏差已触发调整程序：收入偏差 %.2f%%、营业利润偏差 %.2f%%，均超过 10%% 阈值，8 月底已完成滚动预测（LE）重估。" % (
        (sdiv(PL_YTD["rev_total"], BUD_YTD["rev_total"])-1)*100,
        (sdiv(PL_YTD["op_profit"], BUD_YTD["op"])-1)*100),
], 9)

# ==================== 10 利润桥与量价分解 ====================
ws = sheet("10·利润桥与量价分解", [36, 15, 15, 13, 15, 13, 13, 40], freeze="A6")
r = title(ws, 1, "预算差异归因：利润桥与量价分解", 8,
          f"{ENTITY_SHORT}  |  BUD-2026 → LE（8月底滚动预测）  |  单位：万元")
r += 1
r = band(ws, r, "一、营业利润桥（BUD → LE）", 8)
r = head(ws, r, ["分解项", "金额", "占缺口比重", "累计值", "", "", "", "说　明"], h=24)
BRIDGE_MEMO = {
    "年初批复预算 营业利润": "2026 年 1 月董事会批复",
    "① 收入规模缺口（按预算毛利率折算）": "收入少 %s 万元 × 预算毛利率 %.2f%%" % (
        f"{abs(w(PL_FY['rev_total']-BUD_REV_TOTAL)):,.0f}", sdiv(BUD_GROSS, BUD_REV_TOTAL)*100),
    "② 毛利率变动（按实际收入折算）": "毛利率 -%.2f pct × 实际收入 %s 万元" % (
        abs(d_gm)*100, f"{w(PL_FY['rev_total']):,.0f}"),
    "③ 期间费用节约": "管理、销售、研发三项同步压减",
    "④ 减值损失超支": "收缴率缺口 %.2f pct 传导至预期信用损失" % ((COLL_RATE_CY-COLL_BUD_ALL)*100),
    "⑤ 其他收益及投资收益变动": "政府补助与理财收益略低于预算",
    "⑥ 尾差（毛利分解交叉项）": "量价交叉项",
    "滚动预测 营业利润": "基于 1-8 月实际重估",
}
gap = PL_FY["op_profit"] - BUD_OP
cum = 0
for n, v, t in BRIDGE:
    if t == "anchor":
        cum = v
        r = row(ws, r, [n, w(v), "", w(v), "", "", "", BRIDGE_MEMO.get(n, "")],
                [NUM, PCT, NUM, None, None, None, None], bold=True, fill=GREY_D)
    else:
        cum += v
        r = row(ws, r, [n, w(v), sdiv(v, gap), w(cum), "", "", "", BRIDGE_MEMO.get(n, "")],
                [NUM, PCT, NUM, None, None, None, None], indent=1)
        ws.cell(r-1, 2).font = Font(FONT, 9.5, bold=True, color=GREEN if v >= 0 else RED)
    ws.merge_cells(start_row=r-1, start_column=5, end_row=r-1, end_column=7)
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r += 1
r = band(ws, r, "二、归母净利润桥（BUD → LE）", 8)
r = head(ws, r, ["分解项", "金额", "占缺口比重", "累计值", "", "", "", "说　明"], h=24)
PB_MEMO = {"营业利润差异": "见上表", "营业外收支变动": "—",
           "所得税费用变动": "利润下降带来的税负同步减少（有效税率由 26.5% 升至 27.75%）",
           "少数股东损益变动": "合资城市公司同步减利"}
gap2 = PL_FY["parent"] - BUD_PARENT; cum = 0
for n, v, t in PARENT_BRIDGE:
    if t == "anchor":
        cum = v
        r = row(ws, r, [n, w(v), "", w(v), "", "", "", ""], [NUM, PCT, NUM, None, None, None, None],
                bold=True, fill=GREY_D)
    else:
        cum += v
        r = row(ws, r, [n, w(v), sdiv(v, gap2), w(cum), "", "", "", PB_MEMO.get(n, "")],
                [NUM, PCT, NUM, None, None, None, None], indent=1)
        ws.cell(r-1, 2).font = Font(FONT, 9.5, bold=True, color=GREEN if v >= 0 else RED)
    ws.merge_cells(start_row=r-1, start_column=5, end_row=r-1, end_column=7)
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r += 1
r = band(ws, r, "三、量价分解（面积 × 单方，年化口径）", 8)
r = head(ws, r, ["分解对象", "BUD 金额", "BUD 单方\n（元/㎡/月）", "LE 金额", "LE 单方\n（元/㎡/月）",
                 "量　差", "价　差", "合计差异"], h=32)
for n, q, note_ in [("基础物业管理费", REV_QP, "面积未达预算是主因"),
                    ("营业收入（全口径）", REVALL_QP, "含增值服务，价差反映业务结构变化"),
                    ("营业成本（全口径）", COST_QP, "量差有利、价差有利，但幅度小于收入端")]:
    r = row(ws, r, [n, w(q["p_bud"]*(AREA_BUD_AVG if "成本" not in n or True else 0)*12) if False else
                    w(BUD_BASE_FEE if n == "基础物业管理费" else (BUD_REV_TOTAL if "收入" in n else BUD_COGS_TOTAL)),
                    q["p_bud"],
                    w(LE_BASE_FEE if n == "基础物业管理费" else (PL_FY["rev_total"] if "收入" in n else PL_FY["cogs_total"])),
                    q["p_act"], w(q["q_var"]), w(q["p_var"]), w(q["total"])],
            [NUM, NUM4, NUM, NUM4, NUM, NUM, NUM], bold=True)
    for cl in (6, 7, 8):
        v = ws.cell(r-1, cl).value
        good = (v >= 0) if "成本" not in n else (v <= 0)
        ws.cell(r-1, cl).font = Font(FONT, 9.5, bold=True, color=GREEN if good else RED)
r = row(ws, r, ["加权平均在管面积（万㎡）", AREA_BUD_AVG/WAN, "", AREA_LE_AVG/WAN, "",
                (AREA_LE_AVG-AREA_BUD_AVG)/WAN, "", ""],
        [NUM0, None, NUM0, None, NUM0, None, None], fill=GREY)
r += 1
r = band(ws, r, "四、职工薪酬量价分解（人数 × 人均成本）", 8)
r = head(ws, r, ["分解项", "金额", "驱动因子", "", "", "", "", "说　明"], h=24)
for n, v, drv, memo in [
    ("BUD 职工薪酬预算", BUD_STAFF_ALL, "%d 人 × %.0f 元/人·年" % (HC_BUD_TOTAL, BUD_UNIT_STAFF), "含计入期间费用部分"),
    ("① 人数差异", STAFF_VAR_QTY, "超编 %+d 人" % (HC_ACT_TOTAL-HC_BUD_TOTAL), "人效目标（人均在管 7,020 ㎡）未达成"),
    ("② 人均成本差异", STAFF_VAR_PRICE, "人均 %+.0f 元" % (ACT_UNIT_STAFF-BUD_UNIT_STAFF), "控薪、减少加班、结构性用工替代"),
    ("实际职工薪酬", ACT_STAFF_ALL_CHK, "%d 人 × %.0f 元/人·年" % (HC_ACT_TOTAL, ACT_UNIT_STAFF), "全年模拟"),
]:
    bold = n.startswith(("BUD", "实际"))
    r = row(ws, r, [n, w(v), drv, "", "", "", "", memo], [NUM, None]*4, bold=bold,
            fill=GREY_D if bold else None, indent=0 if bold else 1)
    ws.merge_cells(start_row=r-1, start_column=3, end_row=r-1, end_column=7)
    ws.cell(r-1, 3).alignment = Alignment("left", "center")
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
    if not bold: ws.cell(r-1, 2).font = Font(FONT, 9.5, bold=True, color=RED if v > 0 else GREEN)
r = note(ws, r+1, [
    "归母净利润缺口 %s 万元的三个来源：收入规模 %.0f%%、毛利率 %.0f%%、减值超支 %.0f%%（费用节约与税负下降合计对冲 %.0f%%）。" % (
        f"{abs(w(gap2)):,.0f}",
        abs(BRIDGE[1][1])/abs(gap)*100, abs(BRIDGE[2][1])/abs(gap)*100, abs(BRIDGE[4][1])/abs(gap)*100,
        (BRIDGE[3][1] + abs(PARENT_BRIDGE[3][1]) + abs(PARENT_BRIDGE[4][1]))/abs(gap2)*100),
    "量价结论：收入端量差 %s 万元、价差 %s 万元，二者接近 1:0.8；成本端量差 %s 万元、价差 %s 万元。收入的价差（单方物业费下降）没有得到成本单方的等比例下降，是毛利率收窄的直接原因。" % (
        f"{w(REV_QP['q_var']):,.0f}", f"{w(REV_QP['p_var']):,.0f}",
        f"{w(COST_QP['q_var']):,.0f}", f"{w(COST_QP['p_var']):,.0f}"),
    "下一步动作建议：① 锁定 12 个月内到期的 %d 份物业服务合同（年化饱和收入 %s 万元）的续约与调价；② 推进 %d 个退场候选项目的评审；③ 将收缴率缺口分解到城市公司考核。" % (
        sum(1 for x in PROP_CONTRACTS if x["剩余期限（月）"] <= 12),
        f"{w(sum(x['年化饱和收入（元）'] for x in PROP_CONTRACTS if x['剩余期限（月）'] <= 12)):,.0f}",
        len(EXIT_CANDIDATES)),
], 8)

# ==================== 11 物业服务合同台账（600 行）====================
PROP_COLS = list(PROP_CONTRACTS[0].keys())
PROP_W = [16, 20, 10, 13, 8, 15, 13, 9, 11, 12, 13, 9, 9, 13, 12, 13, 8, 13, 13, 13, 9, 13, 15, 9, 8, 17]
PROP_FMT = {"在管建筑面积（㎡）": NUM0, "物业费单价（元/㎡/月）": NUM4, "年化饱和收入（元）": NUM,
            "空置率": PCT1, "本年确认收入（元）": NUM, "本年账单含税（元）": NUM, "本年实收（元）": NUM,
            "本年账单收缴率": PCT, "应收账款余额（元）": NUM, "项目毛利率": PCT,
            "合同期限（年）": NUM0, "剩余期限（月）": NUM0, "在岗人数": NUM0}
PROP_WAN = {"年化饱和收入（元）", "本年确认收入（元）", "本年账单含税（元）", "本年实收（元）", "应收账款余额（元）"}
ws = sheet("11·物业服务合同台账", PROP_W, freeze="C6", tab=GOLD)
r = title(ws, 1, "物业服务合同台账", len(PROP_COLS),
          f"{ENTITY_SHORT}  |  台账基准日 {PERIOD_Y}-{PERIOD_M:02d}-31  |  600 份在管项目合同  |  "
          f"金额单位：万元；单价单位：元/㎡/月  |  计费方式依据发改价格〔2003〕1864 号")
r += 1
hdr = [c.replace("（元）", "（万元）") for c in PROP_COLS]
r = head(ws, r, hdr, h=32, size=8.5)
start = r
for x in PROP_CONTRACTS:
    vals = []
    for c in PROP_COLS:
        v = x[c]
        vals.append(w(v) if c in PROP_WAN else v)
    r = row(ws, r, vals, [PROP_FMT.get(c) for c in PROP_COLS[1:]], size=8.5, h=15)
    st = x["续约状态"]
    if st == "拟退场（已提交评审）":
        for i in range(1, len(PROP_COLS)+1):
            ws.cell(r-1, i).fill = PatternFill("solid", fgColor="FBEDEB")
        ws.cell(r-1, PROP_COLS.index("续约状态")+1).font = Font(FONT, 8.5, bold=True, color=RED)
    elif st == "12 个月内到期，待谈判":
        ws.cell(r-1, PROP_COLS.index("续约状态")+1).font = Font(FONT, 8.5, bold=True, color=AMBER)
    ci = PROP_COLS.index("本年账单收缴率")+1
    ws.cell(r-1, ci).font = Font(FONT, 8.5, color=GREEN if x["本年账单收缴率"] >= 0.88 else RED)
    gi = PROP_COLS.index("项目毛利率")+1
    ws.cell(r-1, gi).font = Font(FONT, 8.5, color=GREEN if x["项目毛利率"] >= 0.16 else
                                 (AMBER if x["项目毛利率"] >= 0.10 else RED))
    for cc in ("区域", "城市公司", "城市", "业态", "项目来源", "计费方式", "定价方式",
               "合同起始日", "合同到期日", "调价条款", "续约状态"):
        ws.cell(r-1, PROP_COLS.index(cc)+1).alignment = Alignment("left", "center")
tot = OrderedDict()
for c in PROP_COLS:
    if c in PROP_WAN or c in ("在管建筑面积（㎡）", "在岗人数"):
        tot[c] = sum(x[c] for x in PROP_CONTRACTS)
sum_vals = []
for i, c in enumerate(PROP_COLS):
    if i == 0: sum_vals.append("合　计（600 份）")
    elif c in tot: sum_vals.append(w(tot[c]) if c in PROP_WAN else tot[c])
    elif c == "物业费单价（元/㎡/月）": sum_vals.append(tot["年化饱和收入（元）"]/tot["在管建筑面积（㎡）"]/12)
    elif c == "本年账单收缴率": sum_vals.append(sdiv(tot["本年实收（元）"], tot["本年账单含税（元）"]))
    elif c == "项目毛利率": sum_vals.append(sdiv(PL_YTD["gross"], PL_YTD["rev_total"]))
    else: sum_vals.append("")
r = row(ws, r, sum_vals, [PROP_FMT.get(c) for c in PROP_COLS[1:]], bold=True, fill=GREY_D, top=True, size=9)
ws.auto_filter.ref = f"A{start-1}:{get_column_letter(len(PROP_COLS))}{r-2}"
r = note(ws, r, [
    "勾稽校验：在管建筑面积合计 %s ㎡＝集团在管面积；本年确认收入合计 %s 万元＝合并利润表 1-8 月基础物业管理费；应收账款余额合计 %s 万元＝应收账款中业主及租户类（占 %.1f%%）。" % (
        f"{tot['在管建筑面积（㎡）']:,}", f"{w(tot['本年确认收入（元）']):,.0f}",
        f"{w(tot['应收账款余额（元）']):,.0f}", BASE_AR_SHARE*100),
    "年化饱和收入＝面积 × 单价 × 12（满收口径，不扣空置折扣与年中交付）；本年确认收入为权责发生制口径，两者差额即空置与在管时长的影响。",
    "计费方式：包干制指业主支付固定物业服务费、盈亏由公司承担；酬金制指从预收物业服务资金中按约定比例提取酬金，结余或不足由业主承担（发改价格〔2003〕1864 号第九条）。",
], len(PROP_COLS))

# ==================== 12 合同结构与到期分析 ====================
ws = sheet("12·合同结构与到期分析", [24, 11, 13, 11, 14, 11, 13, 12, 36], freeze="A6")
r = title(ws, 1, "物业服务合同结构与到期风险分析", 9,
          f"{ENTITY_SHORT}  |  基准日 {PERIOD_Y}-{PERIOD_M:02d}-31  |  金额单位：万元")
r += 1
P = PROP_CONTRACTS
SA = sum(x["年化饱和收入（元）"] for x in P)
def agg(keyfn, order=None):
    d = defaultdict(lambda: dict(n=0, area=0, sat=0, rec=0, ar=0, coll_n=0, coll_d=0, gm_w=0))
    for x in P:
        k = keyfn(x); e = d[k]
        e["n"] += 1; e["area"] += x["在管建筑面积（㎡）"]; e["sat"] += x["年化饱和收入（元）"]
        e["rec"] += x["本年确认收入（元）"]; e["ar"] += x["应收账款余额（元）"]
        e["coll_n"] += x["本年实收（元）"]; e["coll_d"] += x["本年账单含税（元）"]
        e["gm_w"] += x["项目毛利率"] * x["年化饱和收入（元）"]
    ks = order or sorted(d, key=lambda k: -d[k]["sat"])
    return [(k, d[k]) for k in ks if k in d]
def block(title_, rows_, memo_map=None, first_hdr="分　类"):
    global r
    r = band(ws, r, title_, 9)
    r = head(ws, r, [first_hdr, "项目数", "在管面积\n（万㎡）", "面积占比", "年化饱和收入",
                     "收入占比", "平均单价", "加权收缴率", "说　明"], h=30)
    for k, e in rows_:
        r = row(ws, r, [k, e["n"], e["area"]/WAN, sdiv(e["area"], AREA_TOTAL), w(e["sat"]),
                        sdiv(e["sat"], SA), sdiv(e["sat"], e["area"]*12),
                        sdiv(e["coll_n"], e["coll_d"]), (memo_map or {}).get(k, "")],
                [NUM0, NUM0, PCT1, NUM, PCT1, NUM4, PCT, None])
        ws.cell(r-1, 8).font = Font(FONT, 9.5, bold=True,
            color=GREEN if sdiv(e["coll_n"], e["coll_d"]) >= 0.88 else RED)
        ws.cell(r-1, 9).alignment = Alignment("left", "center")
        ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
    tn = sum(e["n"] for _, e in rows_); ta = sum(e["area"] for _, e in rows_)
    ts = sum(e["sat"] for _, e in rows_)
    tcn = sum(e["coll_n"] for _, e in rows_); tcd = sum(e["coll_d"] for _, e in rows_)
    r = row(ws, r, ["合　计", tn, ta/WAN, sdiv(ta, AREA_TOTAL), w(ts), sdiv(ts, SA),
                    sdiv(ts, ta*12), sdiv(tcn, tcd), ""],
            [NUM0, NUM0, PCT1, NUM, PCT1, NUM4, PCT, None], bold=True, fill=GREY_D, top=True)
    r += 1
block("一、按业态", agg(lambda x: x["业态"], list(FORMATS)), {
    "住宅——高端及改善": "单价与收缴率双高，是毛利主要来源",
    "住宅——刚需及安置": "面积最大、单价最低、收缴率洼地，是减值主要来源",
    "写字楼及商业": "单价最高但受空置率影响大",
    "产业园区及公建": "政企客户，回款周期长但违约率低",
    "城市服务及市政": "按项目包干，折算单价低，财政支付节奏影响回款",
    "其他业态": "长租公寓、人才公寓、康养、物流园",
}, "业　态")
block("二、按项目来源", agg(lambda x: x["项目来源"]), {
    "第三方市场外拓": "行业对标：上市物企第三方在管面积占比 61.8%",
    "关联方开发交付": "受关联房企竣工交付节奏影响，是收入缺口主因",
    "收并购承接": "承接价格与存量单价差异大，需关注商誉减值",
}, "项目来源")
block("三、按计费方式与定价方式",
      agg(lambda x: x["计费方式"]) + agg(lambda x: x["定价方式"]), {
    "包干制": "盈余或亏损均由公司享有 / 承担；行业对标 98%",
    "酬金制": "按约定比例提取酬金，结余或不足由业主承担，公司无价格上行空间",
    "政府指导价": "受基准价及浮动幅度限制，2024 年重庆、武汉等城市已出现降价舆情",
    "市场调节价": "由业主与公司在合同中约定，具备提价空间",
}, "分　类")
def bucket(x):
    m = x["剩余期限（月）"]
    return "12 个月内到期" if m <= 12 else "13-24 个月" if m <= 24 else \
           "25-36 个月" if m <= 36 else "36 个月以上"
block("四、按合同剩余期限（到期风险敞口）",
      agg(bucket, ["12 个月内到期", "13-24 个月", "25-36 个月", "36 个月以上"]), {
    "12 个月内到期": "最高风险敞口：需在 2027 年 8 月前完成续约或调价谈判",
    "13-24 个月": "次年重点，提前 6 个月启动",
    "25-36 个月": "中期稳定",
    "36 个月以上": "长约锁定，主要为 5 年期公建与产业园项目",
}, "剩余期限")
block("五、按续约状态", agg(lambda x: x["续约状态"],
      ["正常在约", "24 个月内到期，跟进中", "12 个月内到期，待谈判", "已续签待生效", "拟退场（已提交评审）"]), {
    "拟退场（已提交评审）": "毛利率与收缴率双低，对标万物云 2024 年退出 53 个项目、涉及饱和收入 2.86 亿元",
    "12 个月内到期，待谈判": "谈判结果直接影响 2027 年收入预算",
    "已续签待生效": "已锁定，可计入次年预算基数",
}, "续约状态")
r = band(ws, r, "六、单价分层（饱和收入口径）", 9)
r = head(ws, r, ["单价区间（元/㎡/月）", "项目数", "在管面积\n（万㎡）", "面积占比", "年化饱和收入",
                 "收入占比", "平均单价", "加权收缴率", "说　明"], h=30)
BANDS = [(0, 1.0, "1.00 元以下"), (1.0, 1.5, "1.00 ~ 1.50 元"), (1.5, 2.0, "1.50 ~ 2.00 元"),
         (2.0, 3.0, "2.00 ~ 3.00 元"), (3.0, 99, "3.00 元以上")]
BAND_MEMO = {"1.00 元以下": "城市服务、安置房为主，多为政府指导价，提价空间极小",
             "1.00 ~ 1.50 元": "刚需住宅主力区间，收缴率洼地",
             "1.50 ~ 2.00 元": "改善型住宅与产业园",
             "2.00 ~ 3.00 元": "高端住宅，服务溢价可维持",
             "3.00 元以上": "写字楼、商业及顶端住宅，单价最高"}
for lo, hi, lbl in BANDS:
    sel = [x for x in P if lo <= x["物业费单价（元/㎡/月）"] < hi]
    if not sel: continue
    a = sum(x["在管建筑面积（㎡）"] for x in sel); s = sum(x["年化饱和收入（元）"] for x in sel)
    cn = sum(x["本年实收（元）"] for x in sel); cd = sum(x["本年账单含税（元）"] for x in sel)
    r = row(ws, r, [lbl, len(sel), a/WAN, sdiv(a, AREA_TOTAL), w(s), sdiv(s, SA),
                    sdiv(s, a*12), sdiv(cn, cd), BAND_MEMO[lbl]],
            [NUM0, NUM0, PCT1, NUM, PCT1, NUM4, PCT, None])
    ws.cell(r-1, 8).font = Font(FONT, 9.5, bold=True, color=GREEN if sdiv(cn, cd) >= 0.88 else RED)
    ws.cell(r-1, 9).alignment = Alignment("left", "center"); ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["合　计", len(P), AREA_TOTAL/WAN, 1.0, w(SA), 1.0, sdiv(SA, AREA_TOTAL*12),
                sdiv(sum(x["本年实收（元）"] for x in P), sum(x["本年账单含税（元）"] for x in P)), ""],
        [NUM0, NUM0, PCT1, NUM, PCT1, NUM4, PCT, None], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "七、退场候选池明细", 9)
r = head(ws, r, ["合同编号", "项目名称", "城市公司", "业态", "面积（万㎡）", "年化饱和收入",
                 "项目毛利率", "收缴率", "退场理由"], h=26)
for x in sorted(EXIT_CANDIDATES, key=lambda y: y["项目毛利率"]):
    why = ("毛利率过低 + 收缴率低于 80%" if x["项目毛利率"] < 0.10 and x["本年账单收缴率"] < 0.80
           else "毛利率低于 10%" if x["项目毛利率"] < 0.10
           else "收缴率低于 80%" if x["本年账单收缴率"] < 0.80 else "毛利与收缴双弱，综合评分末位")
    r = row(ws, r, [x["合同编号"], x["项目名称"], x["城市公司"], x["业态"],
                    x["在管建筑面积（㎡）"]/WAN, w(x["年化饱和收入（元）"]),
                    x["项目毛利率"], x["本年账单收缴率"], why],
            [None, None, None, NUM0, NUM, PCT, PCT, None], size=9)
    for cl in (2, 3, 4, 9): ws.cell(r-1, cl).alignment = Alignment("left", "center")
    ws.cell(r-1, 7).font = Font(FONT, 9, bold=True, color=RED)
    ws.cell(r-1, 9).font = Font(FONT, 8.5, color="6B7B8C")
EA = sum(x["在管建筑面积（㎡）"] for x in EXIT_CANDIDATES)
ES = sum(x["年化饱和收入（元）"] for x in EXIT_CANDIDATES)
r = row(ws, r, ["合　计", "%d 个项目" % len(EXIT_CANDIDATES), "", "", EA/WAN, w(ES),
                sum(x["项目毛利率"] for x in EXIT_CANDIDATES)/len(EXIT_CANDIDATES),
                sum(x["本年实收（元）"] for x in EXIT_CANDIDATES)/sum(x["本年账单含税（元）"] for x in EXIT_CANDIDATES), ""],
        [None, None, None, NUM0, NUM, PCT, PCT, None], bold=True, fill=GREY_D, top=True)
exp12 = [x for x in P if x["剩余期限（月）"] <= 12]
r = note(ws, r+1, [
    "到期敞口：12 个月内到期 %d 份，覆盖面积 %s 万㎡（%.1f%%）、年化饱和收入 %s 万元（%.1f%%）。若续约率按行业经验 85%% 测算，2027 年收入基数将减少约 %s 万元。" % (
        len(exp12), f"{sum(x['在管建筑面积（㎡）'] for x in exp12)/WAN:,.0f}",
        sum(x["在管建筑面积（㎡）"] for x in exp12)/AREA_TOTAL*100,
        f"{w(sum(x['年化饱和收入（元）'] for x in exp12)):,.0f}",
        sum(x["年化饱和收入（元）"] for x in exp12)/SA*100,
        f"{w(sum(x['年化饱和收入（元）'] for x in exp12)*0.15):,.0f}"),
    "退场候选 %d 个项目，年化饱和收入 %s 万元（占 %.1f%%），平均毛利率 %.2f%%、平均收缴率 %.2f%%——退出后集团毛利率约提升 %.2f pct。" % (
        len(EXIT_CANDIDATES), f"{w(ES):,.0f}", ES/SA*100,
        sum(x["项目毛利率"] for x in EXIT_CANDIDATES)/len(EXIT_CANDIDATES)*100,
        sum(x["本年实收（元）"] for x in EXIT_CANDIDATES)/sum(x["本年账单含税（元）"] for x in EXIT_CANDIDATES)*100,
        (sdiv(PL_FY["gross"], PL_FY["rev_total"]) -
         sdiv(PL_FY["gross"] - ES*sum(x["项目毛利率"] for x in EXIT_CANDIDATES)/len(EXIT_CANDIDATES),
              PL_FY["rev_total"] - ES))*-100),
    "结构性风险：政府指导价项目占面积 %.1f%%，其单价受基准价与浮动幅度限制；2024 年重庆、银川、青岛、武汉四城公示物业费标准引发降价舆情，该部分敞口需单独跟踪。" % (
        sum(x["在管建筑面积（㎡）"] for x in P if x["定价方式"] == "政府指导价")/AREA_TOTAL*100),
], 9)

# ==================== 13 采购与外包合同台账（240 行）====================
PU_COLS = list(PURCHASE_CONTRACTS[0].keys())
PU_W = [17, 28, 24, 11, 16, 24, 13, 13, 9, 9, 14, 14, 10, 9, 10, 11, 10, 14, 13, 9, 10, 13, 20]
PU_FMT = {"年化合同金额（元）": NUM, "本年累计执行（元）": NUM, "期末应付余额（元）": NUM,
          "履约保证金（元）": NUM, "执行进度": PCT1, "合同期限（年）": NUM0, "剩余期限（月）": NUM0,
          "合同账期（天）": NUM0, "实际账期（天）": DAY, "账期偏离（天）": DAY}
PU_WAN = {"年化合同金额（元）", "本年累计执行（元）", "期末应付余额（元）", "履约保证金（元）"}
ws = sheet("13·采购与外包合同台账", PU_W, freeze="C6", tab=GOLD)
r = title(ws, 1, "采购与外包合同台账", len(PU_COLS),
          f"{ENTITY_SHORT}  |  台账基准日 {PERIOD_Y}-{PERIOD_M:02d}-31  |  240 份供应商合同  |  金额单位：万元")
r += 1
r = head(ws, r, [c.replace("（元）", "（万元）") for c in PU_COLS], h=32, size=8.5)
start = r
for x in PURCHASE_CONTRACTS:
    r = row(ws, r, [w(x[c]) if c in PU_WAN else x[c] for c in PU_COLS],
            [PU_FMT.get(c) for c in PU_COLS[1:]], size=8.5, h=15)
    di = PU_COLS.index("账期偏离（天）")+1
    ws.cell(r-1, di).font = Font(FONT, 8.5, bold=True,
        color=RED if x["账期偏离（天）"] > 30 else (AMBER if x["账期偏离（天）"] > 10 else GREEN))
    gi = PU_COLS.index("履约评价")+1
    ws.cell(r-1, gi).font = Font(FONT, 8.5, bold=True,
        color=RED if x["履约评价"].startswith("D") else (AMBER if x["履约评价"].startswith("C") else GREEN))
    if x["履约评价"].startswith("D"):
        for i in range(1, len(PU_COLS)+1): ws.cell(r-1, i).fill = PatternFill("solid", fgColor="FBEDEB")
    for cc in ("供应商名称", "供应商类别", "服务区域", "合同类型", "计价方式", "合同起始日",
               "合同到期日", "结算周期", "是否锁价", "锁价到期", "履约评价", "续约状态"):
        ws.cell(r-1, PU_COLS.index(cc)+1).alignment = Alignment("left", "center")
TA = sum(x["年化合同金额（元）"] for x in PURCHASE_CONTRACTS)
TY = sum(x["本年累计执行（元）"] for x in PURCHASE_CONTRACTS)
TP = sum(x["期末应付余额（元）"] for x in PURCHASE_CONTRACTS)
sv = []
for i, c in enumerate(PU_COLS):
    if i == 0: sv.append("合　计（240 份）")
    elif c == "年化合同金额（元）": sv.append(w(TA))
    elif c == "本年累计执行（元）": sv.append(w(TY))
    elif c == "期末应付余额（元）": sv.append(w(TP))
    elif c == "履约保证金（元）": sv.append(w(sum(x["履约保证金（元）"] for x in PURCHASE_CONTRACTS)))
    elif c == "执行进度": sv.append(sdiv(TY, TA))
    elif c == "实际账期（天）": sv.append(TP/TA*365)
    else: sv.append("")
r = row(ws, r, sv, [PU_FMT.get(c) for c in PU_COLS[1:]], bold=True, fill=GREY_D, top=True, size=9)
ws.auto_filter.ref = f"A{start-1}:{get_column_letter(len(PU_COLS))}{r-2}"
r = note(ws, r, [
    "勾稽校验：期末应付余额合计 %s 万元＝合并资产负债表应付账款；按供应商类别汇总与《月结财务套表》「09·AP账龄与供应商」逐类一致。" % f"{w(TP):,.0f}",
    "年化合同金额合计 %s 万元（含税），覆盖营业成本中可赊购部分的 %.1f%%（职工薪酬不通过应付账款结算）。" % (
        f"{w(TA):,.0f}", AP_CREDIT_RATIO*100),
], len(PU_COLS))

# ==================== 14 多经与增值服务合同台账（160 行）====================
VA_COLS = list(VAS_CONTRACTS[0].keys())
VA_W = [17, 30, 24, 11, 11, 13, 26, 13, 13, 9, 9, 14, 14, 10, 10, 28, 20]
VA_FMT = {"年化合同金额（元）": NUM, "本年确认收入（元）": NUM, "确认进度": PCT1,
          "合同期限（年）": NUM0, "剩余期限（月）": NUM0, "覆盖项目数": NUM0}
VA_WAN = {"年化合同金额（元）", "本年确认收入（元）"}
ws = sheet("14·多经与增值服务合同台账", VA_W, freeze="C6", tab=GOLD)
r = title(ws, 1, "多种经营与社区增值服务合作合同台账", len(VA_COLS),
          f"{ENTITY_SHORT}  |  台账基准日 {PERIOD_Y}-{PERIOD_M:02d}-31  |  160 份合作合同  |  金额单位：万元")
r += 1
r = head(ws, r, [c.replace("（元）", "（万元）") for c in VA_COLS], h=32, size=8.5)
start = r
for x in VAS_CONTRACTS:
    r = row(ws, r, [w(x[c]) if c in VA_WAN else x[c] for c in VA_COLS],
            [VA_FMT.get(c) for c in VA_COLS[1:]], size=8.5, h=15)
    si = VA_COLS.index("续约状态")+1
    if x["剩余期限（月）"] <= 12:
        ws.cell(r-1, si).font = Font(FONT, 8.5, bold=True, color=AMBER)
    for cc in ("合作方名称", "业务类型", "区域", "分成模式", "分成比例 / 单价", "合同起始日",
               "合同到期日", "结算方式", "业主共有收益分成", "续约状态"):
        ws.cell(r-1, VA_COLS.index(cc)+1).alignment = Alignment("left", "center")
VA_ = sum(x["年化合同金额（元）"] for x in VAS_CONTRACTS)
VY_ = sum(x["本年确认收入（元）"] for x in VAS_CONTRACTS)
sv = []
for i, c in enumerate(VA_COLS):
    if i == 0: sv.append("合　计（160 份）")
    elif c == "年化合同金额（元）": sv.append(w(VA_))
    elif c == "本年确认收入（元）": sv.append(w(VY_))
    elif c == "确认进度": sv.append(sdiv(VY_, VA_))
    elif c == "覆盖项目数": sv.append(sum(x["覆盖项目数"] for x in VAS_CONTRACTS))
    else: sv.append("")
r = row(ws, r, sv, [VA_FMT.get(c) for c in VA_COLS[1:]], bold=True, fill=GREY_D, top=True, size=9)
ws.auto_filter.ref = f"A{start-1}:{get_column_letter(len(VA_COLS))}{r-2}"
r = note(ws, r, [
    "本台账仅覆盖外部合作类收入（%s 万元，占 1-8 月其他业务收入 %.1f%%）；车位租赁、美居施工、社区零售自营等自营业务不通过合同台账管理，差额 %s 万元。" % (
        f"{w(VY_):,.0f}", VY_/PL_YTD["rev_other"]*100, f"{w(PL_YTD['rev_other']-VY_):,.0f}"),
    "「业主共有收益分成」标记为「是」的合同，其收益按《物业服务收费管理办法》第十八条归业主共有，主要用于补充专项维修资金，公司仅确认代管服务费，不计入营业收入。",
], len(VA_COLS))

# ==================== 15 合同与预算联动分析 ====================
ws = sheet("15·合同与预算联动分析", [32, 16, 16, 14, 14, 13, 13, 40], freeze="A6")
r = title(ws, 1, "合同台账与预算的联动分析", 8,
          f"{ENTITY_SHORT}  |  基准日 {PERIOD_Y}-{PERIOD_M:02d}-31  |  单位：万元")
r += 1
r = band(ws, r, "一、合同对预算的覆盖率（预算的可验证性）", 8)
r = head(ws, r, ["预算科目", "预算 / 预测金额", "合同台账支撑金额", "覆盖率", "合同份数",
                 "", "", "未被合同覆盖的部分"], h=28)
COVER = [
    ("基础物业管理费收入（年化饱和）", LE_BASE_FEE, SA, len(P), "饱和收入高于确认收入，差额为空置折扣与年中交付"),
    ("基础物业管理费收入（1-8月确认）", BASE_FEE_REV_YTD, sum(x["本年确认收入（元）"] for x in P), len(P), "逐份合同确认，100% 覆盖"),
    ("其他业务收入（1-8月）", PL_YTD["rev_other"], VY_, len(VAS_CONTRACTS),
     "车位租赁、美居施工、社区零售自营等自营业务无外部合同"),
    ("营业成本——可赊购部分（年化）", int(round(AP_CREDIT_COST_FY*1.075)), TA, len(PURCHASE_CONTRACTS),
     "零星采购与项目直接支付未纳入框架合同"),
    ("营业成本——职工薪酬（年化）", CG_TOT_FY["职工薪酬"], 0, 0, "由岗位序列人员预算驱动，不适用合同台账"),
    ("应收账款——业主及租户类", int(round(AR_GROSS*BASE_AR_SHARE)), sum(x["应收账款余额（元）"] for x in P), len(P), "逐份合同挂账，100% 覆盖"),
    ("应付账款", AP_TOTAL, TP, len(PURCHASE_CONTRACTS), "逐份合同挂账，100% 覆盖"),
]
for n, bud, con, cnt, memo in COVER:
    r = row(ws, r, [n, w(bud), w(con) if con else "—", sdiv(con, bud) if con else "",
                    cnt if cnt else "—", "", "", memo],
            [NUM, NUM, PCT1, NUM0, None, None, None])
    if con:
        cv = con/bud
        ws.cell(r-1, 4).font = Font(FONT, 9.5, bold=True,
            color=GREEN if cv >= 0.95 else (AMBER if cv >= 0.55 else RED))
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r += 1
r = band(ws, r, "二、收入端到期敞口对 2027 年预算的影响", 8)
r = head(ws, r, ["情景", "12个月内到期\n饱和收入", "假设续约率", "续约后留存", "流失金额",
                 "对次年收入影响", "", "情景说明"], h=30)
exp12_sat = sum(x["年化饱和收入（元）"] for x in exp12)
for lbl, rr, memo in [("乐观：全部续约且不降价", 1.00, "服务品质与业主满意度显著改善"),
                      ("基准：行业经验续约率", 0.85, "续约率 85%，价格基本持平"),
                      ("谨慎：续约率下滑 + 降价", 0.78, "续约率 78%，且续约项目平均降价 4%"),
                      ("压力：政府指导价项目集中降价", 0.72, "叠加指导价下调，敞口最大")]:
    keep = int(round(exp12_sat * rr * (0.96 if "谨慎" in lbl else (0.93 if "压力" in lbl else 1.0))))
    loss = exp12_sat - keep
    r = row(ws, r, [lbl, w(exp12_sat), rr, w(keep), w(loss), -sdiv(loss, LE_BASE_FEE), "", memo],
            [NUM, PCT1, NUM, NUM, PCT1, None, None], bold=("基准" in lbl))
    ws.cell(r-1, 5).font = Font(FONT, 9.5, bold=True, color=RED)
    ws.cell(r-1, 6).font = Font(FONT, 9.5, bold=True, color=RED)
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r += 1
r = band(ws, r, "三、成本端锁价与到期风险", 8)
r = head(ws, r, ["供应商类别", "年化合同金额", "12个月内到期\n合同金额", "到期占比", "锁价合同占比",
                 "履约 C/D 级份数", "", "风险提示"], h=30)
SUP_RISK = {"保洁清洁外包服务商": "人工密集，最低工资标准上调直接传导",
            "秩序维护（安保）外包服务商": "同上，且受保安服务资质与用工合规约束",
            "绿化养护外包服务商": "季节性强，可议价空间较大",
            "电梯及设备维保服务商": "安全刚性，不可压价，原厂维保溢价高",
            "水电气热能源供应商": "政府定价，不可议价；分时电价与节能改造是唯一抓手",
            "工程维修及改造承包商": "账期最长且超期严重，是应付账款风险集中处",
            "物料及低值易耗品供应商": "集采规模效应可持续挖掘",
            "信息化及其他服务商": "订阅制涨价压力，需评估自研替代"}
for cat in AP_SUPPLIER:
    sel = [x for x in PURCHASE_CONTRACTS if x["供应商类别"] == cat]
    ann = sum(x["年化合同金额（元）"] for x in sel)
    e12 = sum(x["年化合同金额（元）"] for x in sel if x["剩余期限（月）"] <= 12)
    lk = sum(x["年化合同金额（元）"] for x in sel if x["是否锁价"] == "是")
    cd = sum(1 for x in sel if x["履约评价"][0] in "CD")
    r = row(ws, r, [cat, w(ann), w(e12), sdiv(e12, ann), sdiv(lk, ann), cd, "", SUP_RISK[cat]],
            [NUM, NUM, PCT1, PCT1, NUM0, None, None])
    ws.cell(r-1, 4).font = Font(FONT, 9.5, bold=True, color=RED if sdiv(e12, ann) > 0.45 else GREEN)
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
e12a = sum(x["年化合同金额（元）"] for x in PURCHASE_CONTRACTS if x["剩余期限（月）"] <= 12)
lka = sum(x["年化合同金额（元）"] for x in PURCHASE_CONTRACTS if x["是否锁价"] == "是")
r = row(ws, r, ["合　计", w(TA), w(e12a), sdiv(e12a, TA), sdiv(lka, TA),
                sum(1 for x in PURCHASE_CONTRACTS if x["履约评价"][0] in "CD"), "", ""],
        [NUM, NUM, PCT1, PCT1, NUM0, None, None], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "四、合同视角的 2027 年预算编制起点", 8)
r = head(ws, r, ["测算项", "金额", "口　径", "", "", "", "", "说　明"], h=24)
locked_next = SA - exp12_sat
base2027 = locked_next + int(round(exp12_sat * 0.85))
new_target = int(round(BUD_BASE_FEE * 1.03)) - base2027
STARTPOINT = [
    ("① 已锁定合同（剩余期限 >12 个月）", locked_next, "%d 份合同的年化饱和收入" % (len(P)-len(exp12))),
    ("② 12 个月内到期，按 85% 续约留存", int(round(exp12_sat*0.85)), "行业经验续约率"),
    ("③ 减：退场候选项目", -ES, "%d 个项目，评审通过后不再纳入" % len(EXIT_CANDIDATES)),
    ("④ 2027 年存量收入基数", locked_next + int(round(exp12_sat*0.85)) - ES, "①＋②＋③"),
    ("⑤ 新拓目标缺口", new_target, "若 2027 年目标为 2026 年预算 ×1.03，需新拓补足"),
]
for n, v, memo in STARTPOINT:
    bold = n.startswith(("④", "⑤"))
    r = row(ws, r, [n, w(v), memo, "", "", "", "", ""], [NUM, None]*4, bold=bold,
            fill=GREY_D if bold else None)
    ws.merge_cells(start_row=r-1, start_column=3, end_row=r-1, end_column=8)
    ws.cell(r-1, 3).alignment = Alignment("left", "center")
    ws.cell(r-1, 3).font = Font(FONT, 8.5, color="6B7B8C")
    if v < 0: ws.cell(r-1, 2).font = Font(FONT, 9.5, bold=True, color=RED)
r = note(ws, r+1, [
    "预算的可验证性：收入端 1-8 月基础物业费与应收账款、成本端应付账款均由合同台账 100%% 支撑，可逐份追溯；其他业务收入合同覆盖率 %.1f%%，职工薪酬由人员编制驱动、不适用合同台账。" % (
        VY_/PL_YTD["rev_other"]*100),
    "收入端最大变量是 12 个月内到期的 %d 份合同（年化饱和收入 %s 万元，占 %.1f%%）；基准情景下 2027 年收入基数将比现有饱和收入低 %s 万元，须由新拓补足。" % (
        len(exp12), f"{w(exp12_sat):,.0f}", exp12_sat/SA*100, f"{w(SA-base2027):,.0f}"),
    "成本端最大变量是 %.1f%% 的采购合同在 12 个月内到期重新招标；其中能源类（占 %.1f%%）为政府定价不可议价，实际可谈判空间仅 %.1f%%。" % (
        sdiv(e12a, TA)*100, sdiv(sum(x["年化合同金额（元）"] for x in PURCHASE_CONTRACTS
                                    if x["供应商类别"] == "水电气热能源供应商"), TA)*100,
        sdiv(e12a - sum(x["年化合同金额（元）"] for x in PURCHASE_CONTRACTS
                       if x["供应商类别"] == "水电气热能源供应商" and x["剩余期限（月）"] <= 12), TA)*100),
], 8)

# ==================== 保存 ====================
# HUACHEN_OUT_DIR 可把输出写到别处，避免覆盖已归档的套表
OUT_DIR = os.path.expanduser(os.environ.get("HUACHEN_OUT_DIR") or "~/Desktop/物业集团月结财务套表")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, f"{ENTITY_SHORT}_{PERIOD_Y}年度_全面预算与合同台账.xlsx")
wb.save(OUT)
print("SAVED:", OUT)
print("Sheets:", len(wb.sheetnames))
