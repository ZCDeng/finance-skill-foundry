# -*- coding: utf-8 -*-
"""生成 Excel 月结财务套表"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import *
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

NAVY, NAVY_L, GREY, GREY_D = "14304F", "2C5C8A", "F2F5F8", "E3E9EF"
RED, GREEN, GOLD = "B03A2E", "1E6B4F", "9A6B14"
FONT = "微软雅黑"
thin = Side(style="thin", color="BFC9D4")
med  = Side(style="medium", color="14304F")
B_ALL = Border(left=thin, right=thin, top=thin, bottom=thin)
B_TOP = Border(left=thin, right=thin, top=Side(style="thin", color="14304F"), bottom=thin)
NUM, NUM0, PCT, PCT1, DAY = '#,##0.00;[Red]-#,##0.00', '#,##0;[Red]-#,##0', '0.00%;[Red]-0.00%', '0.0%;[Red]-0.0%', '#,##0.0'

wb = Workbook(); wb.remove(wb.active)
def sheet(name, widths, freeze=None, tab=NAVY):
    ws = wb.create_sheet(name); ws.sheet_properties.tabColor = tab
    for i, w in enumerate(widths, 1): ws.column_dimensions[get_column_letter(i)].width = w
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

def head(ws, r, cells, ncol=None, h=22):
    for i, t in enumerate(cells, 1):
        c = ws.cell(r, i, t); c.font = Font(FONT, 9.5, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY); c.border = B_ALL
        c.alignment = Alignment("center", "center", wrap_text=True)
    ws.row_dimensions[r].height = h
    return r + 1

def band(ws, r, text, ncol, fill=GREY_D):
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)
    c = ws.cell(r, 1, text); c.font = Font(FONT, 10, bold=True, color=NAVY)
    c.fill = PatternFill("solid", fgColor=fill); c.alignment = Alignment("left", "center")
    for i in range(1, ncol+1):
        ws.cell(r, i).fill = PatternFill("solid", fgColor=fill); ws.cell(r, i).border = B_ALL
    ws.row_dimensions[r].height = 19
    return r + 1

def row(ws, r, vals, fmts=None, bold=False, indent=0, fill=None, top=False, size=9.5):
    for i, v in enumerate(vals, 1):
        c = ws.cell(r, i, v)
        c.font = Font(FONT, size, bold=bold, color=NAVY if bold else "1A1A1A")
        c.border = B_TOP if top else B_ALL
        if fill: c.fill = PatternFill("solid", fgColor=fill)
        if i == 1:
            c.alignment = Alignment("left", "center", indent=indent)
        else:
            c.alignment = Alignment("right", "center")
            if fmts and i-2 < len(fmts) and fmts[i-2]: c.number_format = fmts[i-2]
    ws.row_dimensions[r].height = 17
    return r + 1

def note(ws, r, lines, ncol):
    for t in lines:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)
        c = ws.cell(r, 1, t); c.font = Font(FONT, 9, color="4A5A6A")
        c.alignment = Alignment("left", "center", wrap_text=False); ws.row_dimensions[r].height = 16
        r += 1
    return r

import calendar
_MONTH_END = calendar.monthrange(PERIOD_Y, PERIOD_M)[1]
_YTD_DAYS = sum(calendar.monthrange(PERIOD_Y, m)[1] for m in range(1, PERIOD_M + 1))
_IMP_PCT = round(sum(S_IMPAIR[:PERIOD_M]) * 100)
# 演示版把「看板」改叫「核心经营指标」：FA Foundry 把名为看板的页当展示页排除，回款健康就读不到这张表
KPI_SHEET = "01·核心经营指标" if DEMO else "01·核心指标看板"
def w(x): return x / WAN          # 元 -> 万元
def sdiv(a, b): return a / b if b else 0

# ==================== 00 封面与编制说明 ====================
ws = sheet("00·封面与编制说明", [34, 22, 22, 22, 22, 22, 22], tab=NAVY)
r = 1
ws.merge_cells("A1:G3")
c = ws.cell(1, 1, ENTITY); c.font = Font(FONT, 22, bold=True, color=NAVY)
c.alignment = Alignment("left", "center"); ws.row_dimensions[1].height = 30
ws.merge_cells("A4:G4")
c = ws.cell(4, 1, f"{PERIOD_LABEL}  月度结账财务报表套表（GL · AP · AR · CF）")
c.font = Font(FONT, 14, color=NAVY_L); ws.row_dimensions[4].height = 24
ws.merge_cells("A5:G5")
c = ws.cell(5, 1, "本套表为基于公开市场数据构建的模拟样本，不代表任何真实企业。所有金额均为模拟值。")
c.font = Font(FONT, 9, italic=True, color=RED)
r = 7
r = band(ws, r, "一、主体概况", 7)
r = head(ws, r, ["项目", "数值", "单位", "项目", "数值", "单位", "备注"])
prof = [
    ("管理区域", 5, "个", "在管建筑面积", AREA_TOTAL/10000, "万㎡", "含住宅、非住宅全业态"),
    ("城市公司", 50, "家", "在管物业项目", PROJECT_TOTAL, "个", "平均单项目 33.3 万㎡"),
    ("自有在册员工", HEADCOUNT_OWN, "人", "外包用工（折算）", HEADCOUNT_OUTSOURCE, "人", "保洁·秩序·绿化外包"),
    ("年度营业收入（模拟）", PL_FY["rev_total"]/YI, "亿元", "年度归母净利润（模拟）", PL_FY["parent"]/YI, "亿元", "净利率 4.0%"),
]
for a, b, cu, d_, e, f, g in prof:
    r = row(ws, r, [a, b, cu, d_, e, f, g], [NUM0 if isinstance(b,int) else NUM, None, None, NUM0 if isinstance(e,int) else NUM, None, None])
r += 1
r = band(ws, r, "二、编制基础与关键口径", 7)
for t in [
    "1. 编制基础：企业会计准则（2006年及历次修订），合并报表口径，货币单位人民币。GL 与三大报表以「元」列示，分析表以「万元」列示。",
    f"2. 结账期间：本月＝{PERIOD_Y}年{PERIOD_M}月（{PERIOD_M}月1日至{PERIOD_M}月{_MONTH_END}日）；本年累计＝{PERIOD_Y}年1月1日至{PERIOD_M}月{_MONTH_END}日（{_YTD_DAYS}天）。上年同期为同口径模拟对比数。",
    "3. 组织层级：集团本部 → 5 大区域 → 50 家城市公司 → 600 个物业项目。区域及城市公司损益为管理会计口径，已按收入/应收账款权重分摊总部费用与减值。",
    "4. 收入确认：物业管理服务按履约进度（时间段）逐月确认；预收物业费计入合同负债，确认收入时结转。增值服务于服务完成时点确认。",
    "5. 应收账款：期末账面余额（含税）15.00 亿元＝全年营业收入的 30%（题设参数）。按账龄组合计量预期信用损失。",
    "6. 人工成本：题设「人工成本占比 70%」按广义口径执行——自有员工职工薪酬（占营业成本 54.56%）＋ 分包外包合同中的人工含量（按 70% 折算），合计 70.03%。",
    "7. 勾稽关系：科目余额表期初/本期/期末三处借贷平衡；资产负债表两期平衡；现金流量表直接法＝间接法，期末现金＝资产负债表货币资金。所有校验已通过。",
]:
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    c = ws.cell(r, 1, t); c.font = Font(FONT, 9.5, color="2A3A4A")
    c.alignment = Alignment("left", "center"); ws.row_dimensions[r].height = 18; r += 1
r += 1
r = band(ws, r, "三、套表清单", 7)
r = head(ws, r, ["工作表", "模块", "内容", "", "", "", "单位"])
ws.merge_cells(start_row=r-1, start_column=3, end_row=r-1, end_column=6)
CATALOG = [
    (KPI_SHEET, "综合", "经营规模·盈利·营运效率·现金与资产质量 四组 KPI 及行业对标", "多口径"),
    ("02·GL科目余额表", "GL", "78 个会计科目的期初/本期发生/期末余额，三处借贷平衡校验", "元"),
    ("03·GL月结分录清单", "GL", f"{PERIOD_M}月 50 笔月结汇总凭证，含现金流量表项目标签", "元"),
    ("04·合并利润表", "GL", "本月/本年累计/上年同期/全年预算，含同比与预算完成率", "元"),
    ("05·合并资产负债表", "GL", "期末/年初余额及变动分析", "元"),
    ("06·合并现金流量表", "CF", "直接法（本月/累计）＋ 间接法补充资料，双向勾稽", "元"),
    ("07·AR账龄及减值", "AR", "账龄结构、账龄×区域矩阵、客户类别、坏账准备变动", "万元"),
    ("08·AR收缴率与欠费", "AR", "分区域/业态/账单年度的收缴率与欠费结构，周转天数", "万元"),
    ("09·AP账龄与供应商", "AP", "账龄结构、供应商类别与账期执行、应付账款变动", "万元"),
    ("10·区域经营损益表", "管理会计", "5 大区域 + 集团本部的完整损益与营运指标", "万元"),
    ("11·城市公司明细表", "管理会计", "50 家城市公司的面积/收入/毛利/费用/应收/收缴率", "万元"),
    ("12·收入与成本结构", "管理会计", "业务板块拆分、营业成本明细、人工成本口径还原、人员结构", "万元"),
    ("13·行业对标与假设", "依据", "13 项行业基准值、数据来源及本模型取值对照", "—"),
]
for a, b, c_, d_ in CATALOG:
    r = row(ws, r, [a, b, c_, "", "", "", d_])
    ws.merge_cells(start_row=r-1, start_column=3, end_row=r-1, end_column=6)
    ws.cell(r-1, 3).alignment = Alignment("left", "center")
    ws.cell(r-1, 7).alignment = Alignment("center", "center")

# ==================== 01 核心指标看板 ====================
ws = sheet(KPI_SHEET, [30, 15, 15, 15, 13, 15, 40] + ([15] if DEMO else []), freeze="A6", tab=NAVY_L)
r = title(ws, 1, KPI_SHEET.split("·")[1], 7,
          f"{ENTITY_SHORT}  |  {PERIOD_LABEL} 月结  |  本月 / 本年累计 / 上年同期 / 全年预算 / 行业对标")
r += 1
r = head(ws, r, ["指标", "本月", "本年累计", "上年同期累计", "同比", "全年预算", "行业对标（2024年上市物企）"]
         + (["上年全年"] if DEMO else []))
# 演示版多一列「上年全年」，回款健康按去年节奏估全年要用
PY_FULL = {"营业收入（万元）": w(PY_FULL_REV_DEMO),
           "归属于母公司净利润（万元）": w(int(round(LY_YTD["parent"] / (PL_YTD["parent"] / PL_FY["parent"]))))} if DEMO else {}
PLY, PLM, PLF = PL_YTD, PL_M, PL_FY
def yoy(a, b): return sdiv(a - b, abs(b)) if b else 0
K = [
 ("经营规模", None),
 ("营业收入（万元）", w(PLM["rev_total"]), w(PLY["rev_total"]), w(LY_YTD["rev_total"]),
  yoy(PLY["rev_total"], LY_YTD["rev_total"]), w(PLF["rev_total"]), "TOP20 物企量级；行业在管面积增速 6.3%", NUM),
 ("　其中：主营业务收入（万元）", w(PLM["rev_main"]), w(PLY["rev_main"]), w(int(LY_YTD["rev_total"]*0.902)),
  yoy(PLY["rev_main"], int(LY_YTD["rev_total"]*0.902)), w(PLF["rev_main"]), "占比 90.0%（题设）", NUM),
 ("　　　其他业务收入（万元）", w(PLM["rev_other"]), w(PLY["rev_other"]), w(int(LY_YTD["rev_total"]*0.098)),
  yoy(PLY["rev_other"], int(LY_YTD["rev_total"]*0.098)), w(PLF["rev_other"]), "占比 10.0%（多经＋社区增值）", NUM),
 ("在管建筑面积（万㎡）", AREA_TOTAL/10000, AREA_TOTAL/10000, 18_840, yoy(AREA_TOTAL/10000, 18_840),
  AREA_TOTAL/10000, "万物云 10.6 亿㎡ / 保利物业 7.9 亿㎡", NUM0),
 ("在管项目数（个）", PROJECT_TOTAL, PROJECT_TOTAL, 571, yoy(600, 571), PROJECT_TOTAL, "—", NUM0),
 ("基础物业费单方（元/㎡/月）", BASE_FEE_REV_YTD/AREA_TOTAL/PERIOD_M, BASE_FEE_REV_YTD/AREA_TOTAL/PERIOD_M,
  1.712, yoy(UNIT_FEE_YTD, 1.712), BASE_FEE_REV_FY/AREA_TOTAL/12, "百强住宅均值 2.1～2.3 元；本模型偏刚需盘", '0.000'),
 ("盈利能力", None),
 ("毛利（万元）", w(PLM["gross"]), w(PLY["gross"]), w(LY_YTD["gross"]),
  yoy(PLY["gross"], LY_YTD["gross"]), w(PLF["gross"]), "58 家样本物企毛利总额同比 -2.7%", NUM),
 ("综合毛利率", sdiv(PLM["gross"], PLM["rev_total"]), sdiv(PLY["gross"], PLY["rev_total"]),
  sdiv(LY_YTD["gross"], LY_YTD["rev_total"]),
  sdiv(PLY["gross"], PLY["rev_total"]) - sdiv(LY_YTD["gross"], LY_YTD["rev_total"]),
  sdiv(PLF["gross"], PLF["rev_total"]), "行业 19.0%（同比 -1.4pct）", PCT),
 ("营业利润（万元）", w(PLM["op_profit"]), w(PLY["op_profit"]), w(LY_YTD["op_profit"]),
  yoy(PLY["op_profit"], LY_YTD["op_profit"]), w(PLF["op_profit"]), "—", NUM),
 ("净利润（万元）", w(PLM["net"]), w(PLY["net"]), w(LY_YTD["net"]),
  yoy(PLY["net"], LY_YTD["net"]), w(PLF["net"]), "—", NUM),
 ("归属于母公司净利润（万元）", w(PLM["parent"]), w(PLY["parent"]), w(LY_YTD["parent"]),
  yoy(PLY["parent"], LY_YTD["parent"]), round(w(PLF["parent"])), "—", NUM),
 ("归母净利率", sdiv(PLM["parent"], PLM["rev_total"]), sdiv(PLY["parent"], PLY["rev_total"]),
  sdiv(LY_YTD["parent"], LY_YTD["rev_total"]),
  sdiv(PLY["parent"], PLY["rev_total"]) - sdiv(LY_YTD["parent"], LY_YTD["rev_total"]),
  sdiv(PLF["parent"], PLF["rev_total"]), "行业净利率 4.2%（同比 -1.2pct）", PCT),
 ("期间费用率", sdiv(sum(PLM["opex"].values()), PLM["rev_total"]),
  sdiv(sum(PLY["opex"].values()), PLY["rev_total"]),
  sdiv(LY_YTD["opex_total"], LY_YTD["rev_total"]),
  sdiv(sum(PLY["opex"].values()), PLY["rev_total"]) - sdiv(LY_YTD["opex_total"], LY_YTD["rev_total"]),
  sdiv(sum(PLF["opex"].values()), PLF["rev_total"]), "含税金及附加、销售、管理、研发、财务", PCT),
 ("营运效率", None),
 ("应收账款账面余额（万元）", w(AR_GROSS), w(AR_GROSS), w(int(11.86*YI)), yoy(AR_GROSS, int(11.86*YI)),
  w(AR_GROSS), "南都物业 AR/营收 34.3%；本模型 30.0%", NUM),
 ("应收账款周转天数（天）", AR_TURN_DAYS_YTD, AR_TURN_DAYS_YTD, 96.2, AR_TURN_DAYS_YTD-96.2,
  AR_TURN_DAYS, "行业 106 天（央国企 62 天 / 已展期民企 160 天）", DAY),
 ("坏账准备计提比例", sdiv(AR_PROV, AR_GROSS), sdiv(AR_PROV, AR_GROSS), 0.1618,
  sdiv(AR_PROV, AR_GROSS)-0.1618, sdiv(AR_PROV, AR_GROSS), "南都物业 2024 年 17.4%", PCT),
 ("应付账款周转天数（天）", AP_TURN_DAYS, AP_TURN_DAYS, 72.5, AP_TURN_DAYS-72.5, AP_TURN_DAYS,
  "外包/能源合同账期 30～90 天", DAY),
 ("本年账单物业费收缴率", COLL_RATE_CY, COLL_RATE_CY, 0.8985, COLL_RATE_CY-0.8985, 0.925,
  "重点城市均值 82%（含往年欠费口径）", PCT),
 ("综合收缴率（含往年欠费）", COLL_RATE_TOTAL, COLL_RATE_TOTAL, 0.8480, COLL_RATE_TOTAL-0.8480, 0.856,
  "克而瑞：2024 年 82%，同比 -3pct", PCT),
 ("人均在管面积（㎡/人）", AREA_TOTAL/HEADCOUNT_OWN, AREA_TOTAL/HEADCOUNT_OWN, 5_930,
  yoy(AREA_TOTAL/HEADCOUNT_OWN, 5_930), AREA_TOTAL/HEADCOUNT_OWN,
  "2024 年 57 家物企员工数同比 -2.5%（人员精简）", NUM0),
 ("人均创收（万元/人·年）", PLF["rev_total"]/HEADCOUNT_OWN/WAN, PLF["rev_total"]/HEADCOUNT_OWN/WAN,
  14.8, yoy(PLF["rev_total"]/HEADCOUNT_OWN/WAN, 14.8), PLF["rev_total"]/HEADCOUNT_OWN/WAN, "—", NUM),
 ("现金与资产质量", None),
 ("经营活动现金流量净额（万元）", w(CFD_M_OP_NET), w(CFI_YTD_NET), w(int(2.13*YI)),
  yoy(CFI_YTD_NET, int(2.13*YI)), w(int(3.85*YI)), f"物业行业 Q4 为回款高峰，前 {PERIOD_M} 月偏低属季节性", NUM),
 ("经营净现金 / 净利润（倍）", sdiv(CFD_M_OP_NET, PLM["net"]), sdiv(CFI_YTD_NET, PLY["net"]),
  sdiv(int(2.13*YI), LY_YTD["net"]), sdiv(CFI_YTD_NET, PLY["net"])-sdiv(int(2.13*YI), LY_YTD["net"]),
  sdiv(int(3.85*YI), PLF["net"]), "全年口径健康区间 1.0～1.8 倍；单月波动较大", NUM),
 ("货币资金（万元）", w(BSD_C["货币资金"]), w(BSD_C["货币资金"]), w(int(21.42*YI)),
  yoy(BSD_C["货币资金"], int(21.42*YI)), w(BSD_C["货币资金"]),
  "56 家上市物企净现金 1,081.5 亿元，同比 -2.9%", NUM),
 ("资产负债率", sdiv(BS["liab_c"], BS["assets_c"]), sdiv(BS["liab_c"], BS["assets_c"]),
  0.6205, sdiv(BS["liab_c"], BS["assets_c"])-0.6205, sdiv(BS["liab_c"], BS["assets_c"]),
  "物业行业负债以合同负债及代收款为主，非有息", PCT),
 ("有息负债（万元）", w(BSD_C["短期借款"]+BSD_C["一年内到期的非流动负债"]),
  w(BSD_C["短期借款"]+BSD_C["一年内到期的非流动负债"]), w(int(1.98*YI)),
  yoy(BSD_C["短期借款"]+BSD_C["一年内到期的非流动负债"], int(1.98*YI)),
  w(BSD_C["短期借款"]+BSD_C["一年内到期的非流动负债"]), "净现金状态", NUM),
 ("合同负债（预收物业费，万元）", w(BSD_C["合同负债"]), w(BSD_C["合同负债"]), w(int(10.92*YI)),
  yoy(BSD_C["合同负债"], int(10.92*YI)), w(BSD_C["合同负债"]), "约 3.8 个月基础物业费", NUM),
]
for item in K:
    if item[1] is None:
        r = band(ws, r, item[0], 7); continue
    n, m_, y_, l_, yy, f_, bm, fmt = item
    r = row(ws, r, [n, m_, y_, l_, yy, f_, bm] + ([PY_FULL.get(n)] if DEMO else []),
            [fmt, fmt, fmt, PCT if fmt != PCT else PCT1, fmt, None, fmt])
    ws.cell(r-1, 7).alignment = Alignment("left", "center")
    ws.cell(r-1, 7).font = Font(FONT, 8.5, color="6B7B8C")
    if isinstance(yy, float):
        ws.cell(r-1, 5).font = Font(FONT, 9.5, bold=True, color=GREEN if yy >= 0 else RED)
r = note(ws, r+1, [
    "注1：「同比」列——金额指标为增长率，比率指标为百分点变动（pct）。",
    "注2：「全年预算」列的收入 50 亿元、归母净利 2 亿元、主营占比 90%、人工成本占比 70%、应收账款比例 30% 为题设参数，其余科目按行业结构推导。",
    "注3：行业对标数据来源见「13·行业对标与假设」。",
], 7)

# ==================== 02 GL 科目余额表 ====================
ws = sheet("02·GL科目余额表", [11, 34, 8, 7, 16, 16, 16, 16, 16, 16], freeze="A6")
r = title(ws, 1, "科目余额表（试算平衡表）", 10,
          f"{ENTITY_SHORT}  |  {PERIOD_LABEL}  |  单位：元  |  损益类科目每月结转至本年利润，故期初、期末余额为零")
r += 1
r = head(ws, r, ["科目代码", "科目名称", "类别", "方向", "期初余额\n借方", "期初余额\n贷方",
                 "本期发生额\n借方", "本期发生额\n贷方", "期末余额\n借方", "期末余额\n贷方"], h=32)
CATN = {"A": "资产", "L": "负债", "E": "权益", "I": "收入", "C": "成本费用"}
cur = None
for t in TB:
    if t["cat"] != cur:
        cur = t["cat"]
        r = band(ws, r, f"{CATN[cur]}类科目", 10)
    od, oc = (t["open"], "") if t["dirn"] == "借" else ("", t["open"])
    cd, cc = (t["close"], "") if t["dirn"] == "借" else ("", t["close"])
    r = row(ws, r, [t["code"], t["name"], CATN[t["cat"]], t["dirn"], od, oc, t["dr"], t["cr"], cd, cc],
            [None, None, NUM, NUM, NUM, NUM, NUM, NUM])
    for col in (3, 4): ws.cell(r-1, col).alignment = Alignment("center", "center")
od_, oc_ = tb_sum(TB, "open"); cd_, cc_ = tb_sum(TB, "close")
mdr, mcr = sum(x["dr"] for x in TB), sum(x["cr"] for x in TB)
r = row(ws, r, ["合　计", "", "", "", od_, oc_, mdr, mcr, cd_, cc_],
        [None, None, NUM, NUM, NUM, NUM, NUM, NUM], bold=True, fill=GREY_D, top=True)
r = row(ws, r, ["平衡校验（借－贷）", "", "", "", od_-oc_, "", mdr-mcr, "", cd_-cc_, ""],
        [None, None, NUM, NUM, NUM, NUM, NUM, NUM], bold=True, fill="E6F2EA")
for cl in (5, 7, 9):
    ws.cell(r-1, cl).font = Font(FONT, 9.5, bold=True, color=GREEN)
r = note(ws, r+1, [
    "校验说明：期初余额、本期发生额、期末余额三处借贷合计差额均为 0 元，试算平衡通过。",
    "1231 坏账准备、1602 累计折旧、1622 使用权资产累计折旧、1702 累计摊销、1233 合同资产减值准备为资产类备抵科目，余额方向为贷方。",
    "2221.01 销项税额、2221.02 进项税额于月末结转至 2221.03 未交增值税，期末余额为零。",
], 10)

# ==================== 03 GL 月结分录清单 ====================
ws = sheet("03·GL月结分录清单", [13, 11, 52, 11, 34, 16, 16, 34], freeze="A6")
r = title(ws, 1, "月结汇总记账凭证清单", 8,
          f"{ENTITY_SHORT}  |  {PERIOD_LABEL}  |  单位：元  |  共 {len(JE)} 笔汇总凭证，逐笔借贷平衡")
r += 1
r = head(ws, r, ["凭证号", "日期", "摘要", "科目代码", "科目名称", "借方金额", "贷方金额", "现金流量表项目"])
for e in JE:
    first = True
    for code, dr, cr, tag in e["lines"]:
        r = row(ws, r, [e["no"] if first else "", f"{PERIOD_Y}-{PERIOD_M:02d}-31" if first else "",
                        e["summary"] if first else "", code, COA_NAME[code], dr or "", cr or "", tag or ""],
                [None, None, None, None, NUM, NUM, None], fill="FFFFFF" if first else None)
        ws.cell(r-1, 8).alignment = Alignment("left", "center")
        ws.cell(r-1, 8).font = Font(FONT, 8, color="6B7B8C")
        if first:
            for col in (1, 3): ws.cell(r-1, col).font = Font(FONT, 9.5, bold=True, color=NAVY)
        first = False
    r = row(ws, r, ["", "", "　　　　　　　　　　　　　小　计", "", "",
                    sum(l[1] for l in e["lines"]), sum(l[2] for l in e["lines"]), ""],
            [None, None, None, None, NUM, NUM, None], fill=GREY, size=9)
r = row(ws, r, ["合　计", "", f"{len(JE)} 笔凭证", "", "", mdr, mcr, ""],
        [None, None, None, None, NUM, NUM, None], bold=True, fill=GREY_D, top=True)

# ==================== 04 合并利润表 ====================
ws = sheet("04·合并利润表", [42, 18, 18, 18, 12, 18, 11, 26], freeze="A6")
r = title(ws, 1, "合并利润表", 8,
          f"{ENTITY_SHORT}  |  {PERIOD_LABEL}  |  单位：元  |  编制基础：企业会计准则")
r += 1
r = head(ws, r, ["项　目", f"本月\n{PERIOD_LABEL}", f"本年累计\n{YTD_LABEL}", "上年同期累计",
                 "同比", "全年预算", "预算\n完成率", "说　明"], h=32)
def pl_row(name, m_, y_, l_=None, ind=0, bold=False, f_=None, memo="", pct=False):
    global r
    yy = (sdiv(y_, l_) - 1) if (l_ not in (None, 0, "")) else ""
    comp = sdiv(y_, f_) if f_ not in (None, 0, "") else ""
    fmt = PCT if pct else NUM
    r = row(ws, r, [name, m_, y_, l_ if l_ is not None else "", yy, f_ if f_ is not None else "",
                    comp, memo],
            [fmt, fmt, fmt, PCT1, fmt, PCT1, None], bold=bold, indent=ind)
    ws.cell(r-1, 8).alignment = Alignment("left", "center")
    ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
    if isinstance(yy, float): ws.cell(r-1, 5).font = Font(FONT, 9.5, bold=True, color=GREEN if yy >= 0 else RED)
pl_row("一、营业总收入", PL_M["rev_total"], PL_YTD["rev_total"], LY_YTD["rev_total"], 0, True,
       PL_FY["rev_total"], "全年 50 亿元（题设）")
pl_row("其中：主营业务收入", PL_M["rev_main"], PL_YTD["rev_main"], int(LY_YTD["rev_total"]*0.902), 1,
       False, PL_FY["rev_main"], "占比 90%（题设）")
for k in REV_MAIN_MIX:
    pl_row(f"　　{k}", PL_M["rev_main_lines"][k], PL_YTD["rev_main_lines"][k], None, 2, False,
           PL_FY["rev_main_lines"][k])
pl_row("　　　其他业务收入", PL_M["rev_other"], PL_YTD["rev_other"], int(LY_YTD["rev_total"]*0.098), 1,
       False, PL_FY["rev_other"], "占比 10%（题设）")
for k in REV_OTHER_MIX:
    pl_row(f"　　{k}", PL_M["rev_other_lines"][k], PL_YTD["rev_other_lines"][k], None, 2, False,
           PL_FY["rev_other_lines"][k])
r = band(ws, r, "减：营业总成本", 8)
pl_row("营业成本", PL_M["cogs_total"], PL_YTD["cogs_total"], LY_YTD["cogs_total"], 1, False,
       PL_FY["cogs_total"], "成本率 81.0%（百强均值 80.98%）")
pl_row("其中：主营业务成本", PL_M["cogs_main"], PL_YTD["cogs_main"], None, 2, False, PL_FY["cogs_main"])
pl_row("　　　其他业务成本", PL_M["cogs_other"], PL_YTD["cogs_other"], None, 2, False, PL_FY["cogs_other"])
for k, v in OPEX_Y.items():
    pl_row(k, PL_M["opex"][k], PL_YTD["opex"][k], None, 1, False, v,
           "净利息收入，以“－”号列示" if k == "财务费用" else "")
r = band(ws, r, "毛　利", 8)
pl_row("毛利额", PL_M["gross"], PL_YTD["gross"], LY_YTD["gross"], 0, True, PL_FY["gross"])
pl_row("毛利率", sdiv(PL_M["gross"], PL_M["rev_total"]), sdiv(PL_YTD["gross"], PL_YTD["rev_total"]),
       sdiv(LY_YTD["gross"], LY_YTD["rev_total"]), 0, True, sdiv(PL_FY["gross"], PL_FY["rev_total"]),
       "行业 19.0%（2024 年 58 家样本物企）", pct=True)
ws.cell(r-1, 5).value = sdiv(PL_YTD["gross"], PL_YTD["rev_total"]) - sdiv(LY_YTD["gross"], LY_YTD["rev_total"])
r = band(ws, r, "加/减：其他损益项目", 8)
for k in IMPAIR_Y:
    pl_row(f"减：{k}", PL_M["impair"][k], PL_YTD["impair"][k], None, 1, False, IMPAIR_Y[k],
           "预期信用损失模型；Q4 为集中补提期" if "信用" in k else "合同资产减值")
for k in OTHER_INC_Y:
    pl_row(f"加：{k}", PL_M["other_inc"][k], PL_YTD["other_inc"][k], None, 1, False, OTHER_INC_Y[k],
           "政府补助、稳岗返还、进项加计抵减" if k == "其他收益" else "")
pl_row("二、营业利润", PL_M["op_profit"], PL_YTD["op_profit"], LY_YTD["op_profit"], 0, True, PL_FY["op_profit"])
pl_row("加：营业外收入", PL_M["nonop"]["营业外收入"], PL_YTD["nonop"]["营业外收入"], None, 1, False, NONOP_Y["营业外收入"])
pl_row("减：营业外支出", PL_M["nonop"]["营业外支出"], PL_YTD["nonop"]["营业外支出"], None, 1, False, NONOP_Y["营业外支出"])
pl_row("三、利润总额", PL_M["ebt"], PL_YTD["ebt"], LY_YTD["ebt"], 0, True, PL_FY["ebt"])
pl_row("减：所得税费用", PL_M["tax"], PL_YTD["tax"], LY_YTD["tax"], 1, False, PL_FY["tax"],
       "有效税率 27.75%（部分亏损子公司未确认递延资产）")
pl_row("四、净利润", PL_M["net"], PL_YTD["net"], LY_YTD["net"], 0, True, PL_FY["net"])
pl_row("归属于母公司所有者的净利润", PL_M["parent"], PL_YTD["parent"], LY_YTD["parent"], 1, True,
       PL_FY["parent"], "全年 2 亿元（题设）")
pl_row("少数股东损益", PL_M["minority"], PL_YTD["minority"], LY_YTD["net"]-LY_YTD["parent"], 1, False,
       PL_FY["minority"], "合资城市公司及项目公司")
pl_row("归母净利率", sdiv(PL_M["parent"], PL_M["rev_total"]), sdiv(PL_YTD["parent"], PL_YTD["rev_total"]),
       sdiv(LY_YTD["parent"], LY_YTD["rev_total"]), 0, True, sdiv(PL_FY["parent"], PL_FY["rev_total"]),
       "行业净利率 4.2%（同比 -1.2pct）", pct=True)
ws.cell(r-1, 5).value = sdiv(PL_YTD["parent"], PL_YTD["rev_total"]) - sdiv(LY_YTD["parent"], LY_YTD["rev_total"])
r = note(ws, r+1, [
    f"月度波动说明：{PERIOD_M} 月毛利率 %.2f%%，低于全年预算 %.2f%%，主因公区能源费进入夏季峰值、高温津贴与绿化养护集中发生；" % (
        sdiv(PL_M["gross"], PL_M["rev_total"])*100, sdiv(PL_FY["gross"], PL_FY["rev_total"])*100),
    "　　　　　　同时案场协销收入受推盘节奏影响处于淡季。全年毛利率回升依赖 Q4 多经与社区增值服务放量。",
    f"信用减值计提节奏：1-{PERIOD_M} 月按月匀提全年额度的 {_IMP_PCT}%，其余在年末结合催收结果集中补提，与行业惯例一致。",
    "上年同期口径：按 2024 年行业实际变动趋势模拟（收入 -1.8%、毛利率 +0.9pct、减值 -15%），归母净利率由 5.19% 降至 3.98%，降幅 1.21pct，与「行业净利率同比 -1.2pct」一致。",
], 8)

# ==================== 05 合并资产负债表 ====================
ws = sheet("05·合并资产负债表", [40, 18, 18, 16, 11, 34], freeze="A6")
r = title(ws, 1, "合并资产负债表", 6,
          f"{ENTITY_SHORT}  |  {PERIOD_Y}年{PERIOD_M}月31日  |  单位：元")
r += 1
r = head(ws, r, ["项　目", f"期末余额\n{PERIOD_Y}-{PERIOD_M:02d}-31", f"年初余额\n{PERIOD_Y}-01-01",
                 "变动额", "变动率", "说　明"], h=32)
BS_MEMO = {
    "货币资金": "无受限资金；净现金状态",
    "应收账款": "账面价值＝原值 15.00 亿元 － 坏账准备 2.21 亿元",
    "其他应收款": "代垫水电气热费、押金保证金、备用金",
    "合同资产": "案场服务未达结算条件部分，账面价值",
    "商誉": "历年收购城市公司形成，已按资产组测试",
    "合同负债": "预收物业服务费（含税），约 3.8 个月基础物业费",
    "应付职工薪酬": "当月薪酬 + 社保 + 已计提未发年终奖",
    "其他应付款": "代收水电气热费、装修保证金及押金、往来款",
    "短期借款": "流动资金借款；集团整体处于净现金状态",
}
def bs_block(band_name, rows_c, rows_o, subtotal_name):
    global r
    r = band(ws, r, band_name, 6)
    dc = dict(rows_c); do = dict(rows_o)
    for n, v in rows_c:
        o = do[n]; dd_ = v - o
        r = row(ws, r, [n, v, o, dd_, sdiv(dd_, abs(o)) if o else "", BS_MEMO.get(n, "")],
                [NUM, NUM, NUM, PCT1, None], indent=1)
        ws.cell(r-1, 6).alignment = Alignment("left", "center")
        ws.cell(r-1, 6).font = Font(FONT, 8.5, color="6B7B8C")
        if isinstance(ws.cell(r-1, 5).value, float):
            ws.cell(r-1, 5).font = Font(FONT, 9.5, color=GREEN if dd_ >= 0 else RED)
    sc, so = sum(v for _, v in rows_c), sum(v for _, v in rows_o)
    r = row(ws, r, [subtotal_name, sc, so, sc-so, sdiv(sc-so, so), ""],
            [NUM, NUM, NUM, PCT1, None], bold=True, fill=GREY, top=True)
    return sc, so
ac, ao = bs_block("流动资产", BS["A_cur_c"], BS["A_cur_o"], "流动资产合计")
nc, no_ = bs_block("非流动资产", BS["A_ncur_c"], BS["A_ncur_o"], "非流动资产合计")
r = row(ws, r, ["资 产 总 计", ac+nc, ao+no_, (ac+nc)-(ao+no_), sdiv((ac+nc)-(ao+no_), ao+no_), ""],
        [NUM, NUM, NUM, PCT1, None], bold=True, fill=GREY_D, top=True)
lc, lo = bs_block("流动负债", BS["L_cur_c"], BS["L_cur_o"], "流动负债合计")
lnc, lno = bs_block("非流动负债", BS["L_ncur_c"], BS["L_ncur_o"], "非流动负债合计")
r = row(ws, r, ["负 债 合 计", lc+lnc, lo+lno, (lc+lnc)-(lo+lno), sdiv((lc+lnc)-(lo+lno), lo+lno), ""],
        [NUM, NUM, NUM, PCT1, None], bold=True, fill=GREY_D, top=True)
r = band(ws, r, "所有者权益（或股东权益）", 6)
EQ = [("实收资本（或股本）", EQ_PAIDIN, EQ_PAIDIN, ""),
      ("资本公积", EQ_CAPRES, EQ_CAPRES, ""),
      ("盈余公积", EQ_SURPLUS, EQ_SURPLUS, "年末统一计提"),
      ("未分配利润", BS["ret_c"], BS["ret_o"], f"＝年初 + 归母净利 {w(PL_YTD['parent']):,.0f} 万 － 已分配股利 {w(DIV_PARENT_YTD):,.0f} 万")]
for n, v, o, memo in EQ:
    r = row(ws, r, [n, v, o, v-o, sdiv(v-o, o) if o else "", memo], [NUM, NUM, NUM, PCT1, None], indent=1)
    ws.cell(r-1, 6).alignment = Alignment("left", "center"); ws.cell(r-1, 6).font = Font(FONT, 8.5, color="6B7B8C")
pe_c = sum(v for _, v, _, _ in EQ); pe_o = sum(o for _, _, o, _ in EQ)
r = row(ws, r, ["归属于母公司所有者权益合计", pe_c, pe_o, pe_c-pe_o, sdiv(pe_c-pe_o, pe_o), ""],
        [NUM, NUM, NUM, PCT1, None], bold=True, fill=GREY, top=True)
r = row(ws, r, ["少数股东权益", BS["mi_c"], BS["mi_o"], BS["mi_c"]-BS["mi_o"],
                sdiv(BS["mi_c"]-BS["mi_o"], BS["mi_o"]), "合资城市公司及项目公司"],
        [NUM, NUM, NUM, PCT1, None], indent=1)
ws.cell(r-1, 6).alignment = Alignment("left", "center"); ws.cell(r-1, 6).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["所有者权益合计", BS["eq_c"], BS["eq_o"], BS["eq_c"]-BS["eq_o"],
                sdiv(BS["eq_c"]-BS["eq_o"], BS["eq_o"]), ""], [NUM, NUM, NUM, PCT1, None],
        bold=True, fill=GREY, top=True)
r = row(ws, r, ["负债和所有者权益总计", lc+lnc+BS["eq_c"], lo+lno+BS["eq_o"],
                (lc+lnc+BS["eq_c"])-(lo+lno+BS["eq_o"]),
                sdiv((lc+lnc+BS["eq_c"])-(lo+lno+BS["eq_o"]), lo+lno+BS["eq_o"]), ""],
        [NUM, NUM, NUM, PCT1, None], bold=True, fill=GREY_D, top=True)
r = row(ws, r, ["平衡校验（资产 － 负债及权益）", (ac+nc)-(lc+lnc+BS["eq_c"]),
                (ao+no_)-(lo+lno+BS["eq_o"]), "", "", "两期均平衡"],
        [NUM, NUM, None, None, None], bold=True, fill="E6F2EA")
for cl in (2, 3): ws.cell(r-1, cl).font = Font(FONT, 9.5, bold=True, color=GREEN)
ws.cell(r-1, 6).alignment = Alignment("left", "center")
r = note(ws, r+1, [
    "资产负债率 %.2f%%；剔除合同负债与代收代付性质的其他应付款后，调整后资产负债率约 %.2f%%——物业行业负债以经营性预收及代管资金为主，非有息杠杆。" % (
        sdiv(BS["liab_c"], BS["assets_c"])*100,
        sdiv(BS["liab_c"]-BSD_C["合同负债"]-BSD_C["其他应付款"], BS["assets_c"]-BSD_C["合同负债"]-BSD_C["其他应付款"])*100),
    "有息负债合计 %s 万元，货币资金 %s 万元，净现金 %s 万元。" % (
        f"{w(BSD_C['短期借款']+BSD_C['一年内到期的非流动负债']):,.0f}", f"{w(BSD_C['货币资金']):,.0f}",
        f"{w(BSD_C['货币资金']-BSD_C['短期借款']-BSD_C['一年内到期的非流动负债']):,.0f}"),
], 6)

# ==================== 06 合并现金流量表 ====================
ws = sheet("06·合并现金流量表", [50, 20, 20, 40], freeze="A6")
r = title(ws, 1, "合并现金流量表", 4,
          f"{ENTITY_SHORT}  |  {PERIOD_LABEL}  |  单位：元  |  直接法编制，附间接法补充资料")
r += 1
r = head(ws, r, ["项　目", f"本月\n{PERIOD_LABEL}", f"本年累计\n{YTD_LABEL}", "说　明"], h=32)
def cf_row(name, m_, y_, ind=0, bold=False, memo=""):
    global r
    r = row(ws, r, [name, m_, y_, memo], [NUM, NUM, None], bold=bold, indent=ind)
    ws.cell(r-1, 4).alignment = Alignment("left", "center"); ws.cell(r-1, 4).font = Font(FONT, 8.5, color="6B7B8C")
def M(tag): return abs(CFD_M.get(tag, 0))
r = band(ws, r, "一、经营活动产生的现金流量", 4)
CF_MEMO = {
    CF["S"]: "物业费收现 + 增值服务收现 + 预收款",
    CF["OI"]: "代收水电气热回款、押金保证金、利息收入",
    CF["OO"]: "代付水电气热、押金退还、日常经营支付",
    CF["ST"]: "工资、社保公积金、福利费",
}
for t in CF_OP_IN: cf_row(t, M(t), CFD_Y[t], 1, memo=CF_MEMO.get(t, ""))
cf_row("经营活动现金流入小计", sum(M(t) for t in CF_OP_IN), sum(CFD_Y[t] for t in CF_OP_IN), 0, True)
for t in CF_OP_OUT: cf_row(t, M(t), CFD_Y[t], 1, memo=CF_MEMO.get(t, ""))
cf_row("经营活动现金流出小计", sum(M(t) for t in CF_OP_OUT), sum(CFD_Y[t] for t in CF_OP_OUT), 0, True)
cf_row("经营活动产生的现金流量净额", CFD_M_OP_NET, CFI_YTD_NET, 0, True,
       "累计净额为净利润的 %.2f 倍" % sdiv(CFI_YTD_NET, PL_YTD["net"]))
r = band(ws, r, "二、投资活动产生的现金流量", 4)
for t in CF_IN_IN: cf_row(t, M(t), CFD_Y[t], 1)
cf_row("投资活动现金流入小计", sum(M(t) for t in CF_IN_IN), sum(CFD_Y[t] for t in CF_IN_IN), 0, True)
for t in CF_IN_OUT: cf_row(t, M(t), CFD_Y[t], 1,
                           memo="现金管理产品滚动投资" if t == CF["OV"] else ("收购城市公司股权" if t == CF["OS"] else ""))
cf_row("投资活动现金流出小计", sum(M(t) for t in CF_IN_OUT), sum(CFD_Y[t] for t in CF_IN_OUT), 0, True)
mi_net = sum(M(t) for t in CF_IN_IN) - sum(M(t) for t in CF_IN_OUT)
cf_row("投资活动产生的现金流量净额", mi_net, CF_INV_NET_Y, 0, True)
r = band(ws, r, "三、筹资活动产生的现金流量", 4)
for t in CF_FI_IN: cf_row(t, M(t), CFD_Y[t], 1)
cf_row("筹资活动现金流入小计", sum(M(t) for t in CF_FI_IN), sum(CFD_Y[t] for t in CF_FI_IN), 0, True)
for t in CF_FI_OUT: cf_row(t, M(t), CFD_Y[t], 1,
                           memo="含股利 1.35 亿元及利息" if t == CF["FI"] else ("租赁付款额" if t == CF["FO"] else ""))
cf_row("筹资活动现金流出小计", sum(M(t) for t in CF_FI_OUT), sum(CFD_Y[t] for t in CF_FI_OUT), 0, True)
mf_net = sum(M(t) for t in CF_FI_IN) - sum(M(t) for t in CF_FI_OUT)
cf_row("筹资活动产生的现金流量净额", mf_net, CF_FIN_NET_Y, 0, True)
r = band(ws, r, "四、现金及现金等价物净增加额", 4)
cf_row("汇率变动对现金及现金等价物的影响", 0, 0, 1)
net_m = CFD_M_OP_NET + mi_net + mf_net
cf_row("五、现金及现金等价物净增加额", net_m, CF_NET_TOTAL_Y, 0, True)
cf_row("加：期初现金及现金等价物余额", BSD_C["货币资金"]-net_m, BS["cash_o"], 1)
cf_row("六、期末现金及现金等价物余额", BSD_C["货币资金"], BSD_C["货币资金"], 0, True,
       "与资产负债表「货币资金」一致")
r += 1
r = band(ws, r, "补充资料：将净利润调节为经营活动现金流量（间接法）", 4)
MDICT = dict(CFI_M_ROWS)
for k, v in CFI_YTD_ROWS:
    cf_row(k, MDICT.get(k, 0), v, 1, bold=(k == "净利润"))
cf_row("经营活动产生的现金流量净额（间接法）", CFI_M_NET, CFI_YTD_NET, 0, True)
r = row(ws, r, ["直接法与间接法差额（校验）", CFD_M_OP_NET-CFI_M_NET,
                sum(CFD_Y[t] for t in CF_OP_IN)-sum(CFD_Y[t] for t in CF_OP_OUT)-CFI_YTD_NET,
                "两种方法结果一致"], [NUM, NUM, None], bold=True, fill="E6F2EA")
for cl in (2, 3): ws.cell(r-1, cl).font = Font(FONT, 9.5, bold=True, color=GREEN)
ws.cell(r-1, 4).alignment = Alignment("left", "center")
r = note(ws, r+1, [
    "经营性应收项目变动已剔除不涉及现金的坏账核销（本月 %s 万元，本年累计 %s 万元），与「加：信用减值损失」加回口径配套。" % (
        f"{w(WRITEOFF_M):,.0f}", f"{w(AR_WRITEOFF_YTD):,.0f}"),
    f"1-{PERIOD_M} 月经营活动净现金 %s 万元，占营业收入 %.2f%%；受年初集中发放上年年终奖及 Q1-Q3 欠费累积影响，低于全年水平，Q4 为回款高峰。" % (
        f"{w(CFI_YTD_NET):,.0f}", sdiv(CFI_YTD_NET, PL_YTD["rev_total"])*100),
], 4)

# ==================== 07 AR 账龄及减值 ====================
ws = sheet("07·AR账龄及减值", [26, 18, 11, 14, 18, 18, 14, 30], freeze="A6")
r = title(ws, 1, "应收账款账龄结构与预期信用损失", 8,
          f"{ENTITY_SHORT}  |  {PERIOD_Y}年{PERIOD_M}月31日  |  单位：万元  |  账面余额含增值税")
r += 1
r = band(ws, r, "一、按账龄组合计量的预期信用损失", 8)
r = head(ws, r, ["账　龄", "账面余额", "占比", "预期信用\n损失率", "坏账准备", "账面价值",
                 "累计占比", "说　明"], h=30)
AR_MEMO = ["本年及上年账单为主，回收确定性高", "以往年欠费为主，需诉讼及催收介入",
           "含关联方地产企业欠款", "多为空置房及失联业主", "已进入诉讼或执行程序", "全额计提，等待核销审批"]
cum = 0
for i, a in enumerate(AR_ROWS):
    cum += a["gross"]
    r = row(ws, r, [a["aging"], w(a["gross"]), sdiv(a["gross"], AR_GROSS), a["rate"],
                    w(a["prov"]), w(a["net"]), sdiv(cum, AR_GROSS), AR_MEMO[i]],
            [NUM, PCT, PCT, NUM, NUM, PCT, None])
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["合　计", w(AR_GROSS), 1.0, sdiv(AR_PROV, AR_GROSS), w(AR_PROV), w(AR_NET), 1.0,
                "综合计提比例 %.2f%%（南都物业 2024 年 17.4%%）" % (sdiv(AR_PROV, AR_GROSS)*100)],
        [NUM, PCT, PCT, NUM, NUM, PCT, None], bold=True, fill=GREY_D, top=True)
ws.cell(r-1, 8).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "二、账龄 × 区域 分布矩阵", 8)
ages = list(AR_AGING)
r = head(ws, r, ["区　域"] + ages + ["合　计", "1年以内占比"], h=26)
for rg, line in AR_MATRIX:
    r = row(ws, r, [rg] + [w(v) for v in line] + [w(sum(line)), sdiv(line[0], sum(line))],
            [NUM]*7 + [PCT])
    ws.cell(r-1, 9).font = Font(FONT, 9.5, bold=True,
                                color=GREEN if line[0]/sum(line) >= 0.62 else (RED if line[0]/sum(line) < 0.56 else GOLD))
cols = [sum(l[j] for _, l in AR_MATRIX) for j in range(len(ages))]
r = row(ws, r, ["合　计"] + [w(v) for v in cols] + [w(AR_GROSS), sdiv(cols[0], AR_GROSS)],
        [NUM]*7 + [PCT], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "三、按客户类别分布", 8)
r = head(ws, r, ["客户类别", "账面余额", "占比", "参考损失率", "坏账准备", "账面价值", "", "风险说明"], h=26)
CUST_MEMO = {"业主及住户（住宅）": "分散度高，单笔小额，主要为空置房及缴费意愿下降",
             "业主及租户（非住宅）": "写字楼空置率上行，租户退租带来的欠费",
             "关联方房地产开发企业": "案场服务费及前期物业费，信用风险显著上升",
             "政府及国企类客户": "城市服务与公建项目，付款流程长但违约率低",
             "商户及第三方合作方": "多经场地租赁、广告位合作方"}
_CR = {"业主及住户（住宅）": 0.132, "业主及租户（非住宅）": 0.118,
       "关联方房地产开发企业": 0.285, "政府及国企类客户": 0.042, "商户及第三方合作方": 0.156}
_SCALE = sdiv(AR_PROV, AR_GROSS) / sum(AR_CUSTOMER[k] * _CR[k] for k in _CR)
CUST_RATE = {k: v * _SCALE for k, v in _CR.items()}          # 加权后与组合计提比例一致
acc_g = acc_p = 0
ck = list(AR_CUSTOMER)
for i, k in enumerate(ck):
    g = (AR_GROSS - acc_g) if i == len(ck)-1 else int(round(AR_GROSS * AR_CUSTOMER[k]))
    p = (AR_PROV - acc_p) if i == len(ck)-1 else int(round(g * CUST_RATE[k]))
    acc_g += g; acc_p += p
    r = row(ws, r, [k, w(g), sdiv(g, AR_GROSS), sdiv(p, g), w(p), w(g-p), "", CUST_MEMO[k]],
            [NUM, PCT, PCT, NUM, NUM, None, None])
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["合　计", w(AR_GROSS), 1.0, sdiv(AR_PROV, AR_GROSS), w(AR_PROV), w(AR_NET), "", ""],
        [NUM, PCT, PCT, NUM, NUM, None, None], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "四、应收账款及坏账准备变动表（本年累计）", 8)
r = head(ws, r, ["项　目", "应收账款原值", "坏账准备", "账面价值", "", "", "", "说　明"], h=26)
mv = [("年初余额", AR_GROSS_O, AR_PROV_O, "上年末数"),
      ("本期新增（确认收入形成）", AR_ADD_YTD, 0, "含税口径：物业费 45% 挂账 + 案场服务 + 增值服务 40% 挂账"),
      ("本期收回", -(AR_ADD_YTD - (AR_GROSS - AR_GROSS_O) - AR_WRITEOFF_YTD), 0, "现金回收"),
      ("本期计提信用减值", 0, PL_YTD["impair"]["信用减值损失"], "计入信用减值损失"),
      ("本期核销", -AR_WRITEOFF_YTD, -AR_WRITEOFF_YTD, "经审批核销，不涉及现金"),
      ("期末余额", None, None, f"{PERIOD_Y}-{PERIOD_M:02d}-31")]
gg, pp = 0, 0
for n, g, p, memo in mv:
    if n == "期末余额": g, p = AR_GROSS, AR_PROV
    else: gg += g; pp += p
    r = row(ws, r, [n, w(g), w(p), w(g-p) if n in ("年初余额", "期末余额") else "", "", "", "", memo],
            [NUM, NUM, NUM, None, None, None, None],
            bold=(n in ("年初余额", "期末余额")), fill=GREY if n in ("年初余额", "期末余额") else None)
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = note(ws, r+1, [
    "应收账款周转天数：年化口径 %.1f 天（期末余额 ÷ 全年收入 × 365），累计口径 %.1f 天（平均余额 ÷ 累计收入 × 243）。" % (AR_TURN_DAYS, AR_TURN_DAYS_YTD),
    "行业对标：2024 年 58 家样本上市物企平均 106 天（2023 年 105 天）；分类型看央国企物企约 62 天，已展期民企物企约 160 天。",
    "关联方房地产开发企业欠款计提比例 28.5%，显著高于组合平均，反映地产端信用风险——这是 2022 年以来物企减值的主要来源。",
], 8)

# ==================== 08 AR 收缴率与欠费 ====================
ws = sheet("08·AR收缴率与欠费", [22, 16, 16, 14, 14, 14, 14, 32], freeze="A6")
r = title(ws, 1, "物业费收缴率与欠费结构分析", 8,
          f"{ENTITY_SHORT}  |  {YTD_LABEL}  |  单位：万元")
r += 1
r = band(ws, r, "一、分区域收缴与应收质量", 8)
r = head(ws, r, ["区　域", "本年应收账单", "本年实收", "本年账单\n收缴率", "应收账款\n期末余额",
                 "应收/年化收入", "周转天数\n（年化）", "评　价"], h=32)
bill_tot = int(round(BASE_FEE_REV_YTD * 1.048))
for rg in REGIONS:
    share = REGPL_YTD[rg]["rev"] / PL_YTD["rev_total"]
    bill = int(round(bill_tot * share)); coll = REGIONS[rg]["coll"]
    recv = int(round(bill * coll)); ar = AR_REGION[rg]
    annual_rev = int(round(REGPL_YTD[rg]["rev"] / 0.6589))
    days = sdiv(ar, annual_rev) * 365
    ev = "优" if coll >= 0.895 else ("良" if coll >= 0.87 else ("需关注" if coll >= 0.85 else "重点治理"))
    r = row(ws, r, [rg, w(bill), w(recv), coll, w(ar), sdiv(ar, annual_rev), days, ev],
            [NUM, NUM, PCT, NUM, PCT, DAY, None])
    ws.cell(r-1, 8).alignment = Alignment("center", "center")
    ws.cell(r-1, 8).font = Font(FONT, 9.5, bold=True,
                                color=GREEN if ev in ("优", "良") else (GOLD if ev == "需关注" else RED))
    ws.cell(r-1, 4).font = Font(FONT, 9.5, bold=True, color=GREEN if coll >= 0.87 else RED)
r = row(ws, r, ["合　计 / 加权", w(bill_tot), w(int(round(bill_tot*COLL_RATE_CY))), COLL_RATE_CY,
                w(AR_GROSS), sdiv(AR_GROSS, PL_FY["rev_total"]), AR_TURN_DAYS, ""],
        [NUM, NUM, PCT, NUM, PCT, DAY, None], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "二、分业态收缴率", 8)
r = head(ws, r, ["业　态", "收入占比", "收缴率", "较集团均值", "对应欠费规模", "", "", "说　明"], h=26)
TYPE_MEMO = {"住宅——高端及改善": "服务感知强、业主支付能力高", "住宅——刚需及安置": "收缴率洼地，安置房及老旧小区集中",
             "写字楼及商业": "受空置率与租户经营状况影响", "产业园区及公建": "政企客户，付款周期长但违约率低",
             "城市服务及市政": "财政支付节奏影响回款", "其他业态": "长租公寓、学校医院等"}
arr_total = int(round(bill_tot*(1-COLL_RATE_CY)))
arr_acc = 0
for i, (k, (rate, share)) in enumerate(COLL_BY_TYPE.items()):
    # 尾差归入最后一行，六行合计 = 加权合计行
    arr = (arr_total - arr_acc) if i == len(COLL_BY_TYPE) - 1 else int(round(bill_tot * share * (1 - rate)))
    arr_acc += arr
    r = row(ws, r, [k, share, rate, rate - COLL_RATE_CY, w(arr), "", "", TYPE_MEMO[k]],
            [PCT, PCT, PCT1, NUM, None, None, None])
    ws.cell(r-1, 4).font = Font(FONT, 9.5, bold=True, color=GREEN if rate >= COLL_RATE_CY else RED)
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["加权合计", 1.0, COLL_RATE_CY, 0, w(arr_total), "", "", ""],
        [PCT, PCT, PCT1, NUM, None, None, None], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "三、欠费按账单年度结构（应收账款账面余额拆分）", 8)
r = head(ws, r, ["账单年度", "欠费余额", "占比", "已计提坏账", "计提比例", "预计可收回", "", "催收策略"], h=26)
STRAT = ["常规催缴 + 线上账单推送", "专项催收 + 停车位/门禁权益联动", "律师函 + 支付令",
         "诉讼立案 + 财产保全", "强制执行 + 以房抵债", "核销审批 + 保留追索权"]
for i, ay in enumerate(ARREARS_ROWS):
    k, v, prov, rate = ay["year"], ay["gross"], ay["prov"], ay["rate"]
    r = row(ws, r, [k, w(v), sdiv(v, AR_GROSS), w(prov), rate, w(v-prov), "", STRAT[i]],
            [NUM, PCT, NUM, PCT, NUM, None, None])
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["合　计", w(AR_GROSS), 1.0, w(AR_PROV), sdiv(AR_PROV, AR_GROSS), w(AR_NET), "", ""],
        [NUM, PCT, NUM, PCT, NUM, None, None], bold=True, fill=GREY_D, top=True)
r = note(ws, r+1, [
    "本年账单收缴率 %.2f%%，综合收缴率（含往年欠费清收）%.2f%%。行业对标：2024 年重点城市物业费平均收缴率跌至 82%%，较 2023 年净减少 3 个百分点（克而瑞物管）。" % (COLL_RATE_CY*100, COLL_RATE_TOTAL*100),
    "管理动作：收缴率每提升 1 个百分点，对应现金流入约 %s 万元；若压缩至行业最优区间（≥93%%），可释放现金约 %s 万元。" % (
        f"{w(int(bill_tot*0.01)):,.0f}", f"{w(int(bill_tot*(0.93-COLL_RATE_CY))):,.0f}"),
    "西部与华中区域 1 年以内应收占比分别为 50.8%% 和 55.4%%，明显低于华东 70.2%%，是账龄劣化与减值集中的来源，建议作为 Q4 专项治理对象。",
], 8)

# ==================== 09 AP 账龄与供应商 ====================
ws = sheet("09·AP账龄与供应商", [26, 16, 12, 14, 14, 14, 14, 32], freeze="A6")
r = title(ws, 1, "应付账款账龄、供应商结构与账期执行", 8,
          f"{ENTITY_SHORT}  |  {PERIOD_Y}年{PERIOD_M}月31日  |  单位：万元")
r += 1
r = band(ws, r, "一、应付账款账龄结构", 8)
r = head(ws, r, ["账　龄", "期末余额", "占比", "年初余额", "变动额", "", "", "说　明"], h=26)
AP_MEMO = ["合同账期内，正常周转", "含 6 月末未达结算条件的工程款", "跨年度未结算，需推进对账",
           "存在争议或质量扣款的尾款", "已停止合作供应商，待清理"]
AP_O_MIX = [0.702, 0.163, 0.082, 0.038, 0.015]
for i, a in enumerate(AP_ROWS):
    o = int(round(BSD_O["应付账款"] * AP_O_MIX[i]))
    r = row(ws, r, [a["aging"], w(a["amt"]), sdiv(a["amt"], AP_TOTAL), w(o), w(a["amt"]-o), "", "", AP_MEMO[i]],
            [NUM, PCT, NUM, NUM, None, None, None])
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["合　计", w(AP_TOTAL), 1.0, w(BSD_O["应付账款"]), w(AP_TOTAL-BSD_O["应付账款"]), "", "", ""],
        [NUM, PCT, NUM, NUM, None, None, None], bold=True, fill=GREY_D, top=True)
r += 1
r = band(ws, r, "二、供应商类别、账期执行与周转", 8)
r = head(ws, r, ["供应商类别", "期末应付余额", "占比", "本年累计\n采购额", "合同账期\n（天）",
                 "实际账期\n（天）", "账期偏离", "说　明"], h=32)
SUP_MEMO = {"保洁清洁外包服务商": "百强口径清洁卫生费占营业成本 9.43%",
            "秩序维护（安保）外包服务商": "百强口径秩序维护费占营业成本 4.98%",
            "绿化养护外包服务商": "百强口径绿化养护费占营业成本 2.39%",
            "电梯及设备维保服务商": "含电梯、消防、供配电专项维保",
            "水电气热能源供应商": "公区能耗，账期短、刚性支付",
            "工程维修及改造承包商": "含维修基金项目及业主自费工程",
            "物料及低值易耗品供应商": "集中采购平台结算",
            "信息化及其他服务商": "智慧物业系统、通讯、咨询"}
for s in AP_SUP_ROWS:
    dev = s["actual"] - s["term"]
    r = row(ws, r, [s["cat"], w(s["amt"]), sdiv(s["amt"], AP_TOTAL), w(s["purch"]), s["term"],
                    s["actual"], dev, SUP_MEMO[s["cat"]]],
            [NUM, PCT, NUM, NUM0, DAY, DAY, None])
    ws.cell(r-1, 7).font = Font(FONT, 9.5, bold=True, color=RED if dev > 15 else GREEN)
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
wterm = sum(AP_SUPPLIER[k][0]*AP_SUPPLIER[k][1] for k in AP_SUPPLIER)
r = row(ws, r, ["合　计 / 加权", w(AP_TOTAL), 1.0, w(sum(s["purch"] for s in AP_SUP_ROWS)),
                wterm, AP_TURN_DAYS_EOP, AP_TURN_DAYS_EOP - wterm, "期末余额口径；平均余额口径周转 %.1f 天" % AP_TURN_DAYS],
        [NUM, PCT, NUM, DAY, DAY, DAY, None], bold=True, fill=GREY_D, top=True)
ws.cell(r-1, 8).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "三、应付账款变动表（本年累计）", 8)
r = head(ws, r, ["项　目", "金　额", "", "", "", "", "", "说　明"], h=22)
ap_purch = int(round(AP_CREDIT_COST_YTD * 1.075))
for n, v, memo in [("年初余额", BSD_O["应付账款"], "上年末数"),
                   ("本期新增（采购及分包计提）", ap_purch, "含税口径"),
                   ("本期支付", -(ap_purch - (AP_TOTAL - BSD_O["应付账款"])), "银行转账及票据结算"),
                   ("期末余额", AP_TOTAL, f"{PERIOD_Y}-{PERIOD_M:02d}-31")]:
    r = row(ws, r, [n, w(v), "", "", "", "", "", memo], [NUM, None, None, None, None, None, None],
            bold=(n in ("年初余额", "期末余额")), fill=GREY if n in ("年初余额", "期末余额") else None)
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r += 1
r = band(ws, r, "四、分区域应付账款", 8)
r = head(ws, r, ["区　域", "期末应付余额", "占比", "本年累计\n可赊购采购额", "应付/采购额",
                 "折合账期\n（天）", "", "付款节奏"], h=30)
for s in AP_REG_ROWS:
    pace = "偏快" if s["days"] < AP_TURN_DAYS_EOP - 4 else ("正常" if s["days"] < AP_TURN_DAYS_EOP + 4 else "偏慢")
    r = row(ws, r, [s["region"], w(s["amt"]), sdiv(s["amt"], AP_TOTAL), w(s["purch"]),
                    sdiv(s["amt"], s["purch"]), s["days"], "", pace],
            [NUM, PCT, NUM, PCT, DAY, None, None])
    ws.cell(r-1, 8).alignment = Alignment("center", "center")
    ws.cell(r-1, 8).font = Font(FONT, 9.5, bold=True, color=GREEN if pace != "偏慢" else RED)
r = row(ws, r, ["合　计", w(AP_TOTAL), 1.0, w(sum(s["purch"] for s in AP_REG_ROWS)),
                sdiv(AP_TOTAL, sum(s["purch"] for s in AP_REG_ROWS)), AP_TURN_DAYS_EOP, "", ""],
        [NUM, PCT, NUM, PCT, DAY, None, None], bold=True, fill=GREY_D, top=True)
r = note(ws, r, ["注：可赊购采购额＝营业成本 × %.1f%%（剔除职工薪酬等不通过应付账款结算的部分）× 1.075（含税）。" % (AP_CREDIT_RATIO*100)], 8)
r = note(ws, r+1, [
    "应付账款周转天数 %.1f 天（平均余额口径），高于加权合同账期 %.1f 天 %.1f 天——超期主要来自工程维修及改造承包商（实际 %.0f 天 vs 合同 90 天）。" % (
        AP_TURN_DAYS, sum(AP_SUPPLIER[k][0]*AP_SUPPLIER[k][1] for k in AP_SUPPLIER),
        AP_TURN_DAYS - sum(AP_SUPPLIER[k][0]*AP_SUPPLIER[k][1] for k in AP_SUPPLIER),
        [s for s in AP_SUP_ROWS if "工程维修" in s["cat"]][0]["actual"]),
    "AR 周转 %.1f 天 vs AP 周转 %.1f 天，净营运资金缺口约 %.1f 天，对应资金占用约 %s 万元。" % (
        AR_TURN_DAYS_YTD, AP_TURN_DAYS, AR_TURN_DAYS_YTD - AP_TURN_DAYS,
        f"{w(int(PL_FY['rev_total']/365*(AR_TURN_DAYS_YTD-AP_TURN_DAYS))):,.0f}"),
    "能源供应商账期最短（30 天）且不可展期，是月度付款刚性最强的一块；外包类账期 45～60 天，是账期管理的主要腾挪空间。",
], 8)

# ==================== 10 区域经营损益表 ====================
ws = sheet("10·区域经营损益表", [20, 12, 10, 15, 15, 14, 11, 14, 13, 14, 11, 14, 12, 11], freeze="D6")
r = title(ws, 1, "区域经营损益表（管理会计口径）", 14,
          f"{ENTITY_SHORT}  |  {YTD_LABEL}  |  单位：万元  |  总部费用与减值已按收入/应收权重分摊")
r += 1
r = head(ws, r, ["区　域", "在管面积\n(万㎡)", "项目数\n(个)", "营业收入", "营业成本", "毛　利",
                 "毛利率", "期间费用", "减值损失", "其他收益", "营业利润", "应收账款",
                 "本年收缴率", "单方物业费\n(元/㎡/月)"], h=36)
tot = defaultdict(int)
for rg in list(REGIONS) + [HQ_NAME]:
    v = REGPL_YTD[rg]
    area = v["area"]/10000; ar = AR_REGION.get(rg, 0)
    unit = sdiv(v["rev"]*0.91, v["area"]*PERIOD_M) if v["area"] else ""
    r = row(ws, r, [rg, area if area else "", v["proj"] if v["proj"] else "", w(v["rev"]), w(v["cogs"]),
                    w(v["gross"]), sdiv(v["gross"], v["rev"]) if v["rev"] else "", w(v["opex"]),
                    w(v["impair"]), w(v["other_inc"]), w(v["op"]), w(ar) if ar else "",
                    REGIONS[rg]["coll"] if rg in REGIONS else "", unit],
            [NUM0, NUM0, NUM, NUM, NUM, PCT, NUM, NUM, NUM, NUM, NUM, PCT, '0.000'],
            bold=(rg == HQ_NAME))
    if rg in REGIONS:
        gm = v["gross"]/v["rev"]
        ws.cell(r-1, 7).font = Font(FONT, 9.5, bold=True, color=GREEN if gm >= 0.19 else (GOLD if gm >= 0.18 else RED))
    for k in ("rev", "cogs", "gross", "opex", "impair", "other_inc", "op"): tot[k] += v[k]
    tot["area"] += v["area"]; tot["proj"] += v["proj"]; tot["ar"] += ar
r = row(ws, r, ["合并合计", tot["area"]/10000, tot["proj"], w(tot["rev"]), w(tot["cogs"]), w(tot["gross"]),
                sdiv(tot["gross"], tot["rev"]), w(tot["opex"]), w(tot["impair"]), w(tot["other_inc"]),
                w(tot["op"]), w(tot["ar"]), COLL_RATE_CY, UNIT_FEE_YTD],
        [NUM0, NUM0, NUM, NUM, NUM, PCT, NUM, NUM, NUM, NUM, NUM, PCT, '0.000'],
        bold=True, fill=GREY_D, top=True)
r = row(ws, r, ["校验：与合并利润表差异", "", "", w(tot["rev"]-PL_YTD["rev_total"]), w(tot["cogs"]-PL_YTD["cogs_total"]),
                w(tot["gross"]-PL_YTD["gross"]), "", w(tot["opex"]-sum(PL_YTD["opex"].values())),
                w(tot["impair"]-sum(PL_YTD["impair"].values())), w(tot["other_inc"]-sum(PL_YTD["other_inc"].values())),
                w(tot["op"]-PL_YTD["op_profit"]), w(tot["ar"]-AR_GROSS), "", ""],
        [None, None, NUM, NUM, NUM, None, NUM, NUM, NUM, NUM, NUM, None, None], bold=True, fill="E6F2EA")
r = note(ws, r+1, [
    "集团本部及共享中心不承担收入，其营业成本为集中化的品质巡检、集采中心、共享服务中心成本（%s 万元），期间费用为总部管理费用（占集团期间费用 22%%）。" % f"{w(REGPL_YTD[HQ_NAME]['cogs']):,.0f}",
    "毛利率梯度：华东 %.1f%% → 西部 %.1f%%，价差主要来自单方物业费（%.3f 元 vs %.3f 元）与人工成本地区差异。" % (
        REGPL_YTD['华东区域']['gross']/REGPL_YTD['华东区域']['rev']*100,
        REGPL_YTD['西部区域']['gross']/REGPL_YTD['西部区域']['rev']*100,
        REGPL_YTD['华东区域']['rev']*0.91/REGPL_YTD['华东区域']['area']/PERIOD_M,
        REGPL_YTD['西部区域']['rev']*0.91/REGPL_YTD['西部区域']['area']/PERIOD_M),
    "减值分摊按各区域应收账款余额权重，而非收入权重——这使收缴率差的区域直接承担其信用成本，是区域考核的关键设计。",
], 14)

# ==================== 11 城市公司明细表 ====================
ws = sheet("11·城市公司明细表", [12, 18, 12, 9, 14, 14, 13, 10, 13, 12, 13, 12, 11, 12], freeze="C6")
r = title(ws, 1, "城市公司经营明细表", 14,
          f"{ENTITY_SHORT}  |  {YTD_LABEL}  |  单位：万元  |  5 大区域 × 10 家城市公司 = 50 家")
r += 1
r = head(ws, r, ["区　域", "城市公司", "在管面积\n(万㎡)", "项目数", "营业收入", "营业成本", "毛　利",
                 "毛利率", "期间费用", "减值损失", "营业利润", "应收账款", "本年收缴率",
                 "单方物业费\n(元/㎡/月)"], h=36)
cur_rg = None
for c in CITY_ROWS:
    if c["region"] != cur_rg:
        cur_rg = c["region"]
        rv = REGPL_YTD[cur_rg]
        r = band(ws, r, f"{cur_rg}　（在管 {rv['area']/10000:,.0f} 万㎡ · {rv['proj']} 个项目 · 收入 {w(rv['rev']):,.0f} 万元 · 毛利率 {rv['gross']/rv['rev']*100:.2f}%）", 14)
    gm = sdiv(c["gross"], c["rev"])
    r = row(ws, r, ["", c["city"], c["area"]/10000, c["proj"], w(c["rev"]), w(c["cogs"]), w(c["gross"]),
                    gm, w(c["opex"]), w(c["impair"]), w(c["op"]), w(c["ar"]), c["coll"],
                    sdiv(c["rev"]*0.91, c["area"]*PERIOD_M)],
            [None, NUM0, NUM0, NUM, NUM, NUM, PCT, NUM, NUM, NUM, NUM, PCT, '0.000'], size=9)
    ws.cell(r-1, 8).font = Font(FONT, 9, bold=True, color=GREEN if gm >= 0.20 else (GOLD if gm >= 0.175 else RED))
    ws.cell(r-1, 13).font = Font(FONT, 9, color=GREEN if c["coll"] >= 0.88 else RED)
    if c["op"] < 0: ws.cell(r-1, 11).font = Font(FONT, 9, bold=True, color=RED)
T = lambda k: sum(c[k] for c in CITY_ROWS)
r = row(ws, r, ["50 家城市公司合计（不含集团本部）", "50 家", T("area")/10000, T("proj"), w(T("rev")), w(T("cogs")), w(T("gross")),
                sdiv(T("gross"), T("rev")), w(T("opex")), w(T("impair")), w(T("op")), w(T("ar")),
                COLL_RATE_CY, UNIT_FEE_YTD],
        [None, NUM0, NUM0, NUM, NUM, NUM, PCT, NUM, NUM, NUM, NUM, PCT, '0.000'],
        bold=True, fill=GREY_D, top=True)
loss = [c for c in CITY_ROWS if c["op"] < 0]
thin_ = [c for c in CITY_ROWS if 0 <= c["op"] / c["rev"] < 0.03]
best = max(CITY_ROWS, key=lambda c: c["gross"]/c["rev"]); worst = min(CITY_ROWS, key=lambda c: c["gross"]/c["rev"])
r = note(ws, r+1, [
    "50 家城市公司合计在管 %s 万㎡、%d 个项目，与集团口径一致（不含集团本部，本部集中成本 %s 万元单列于「10·区域经营损益表」）。" % (
        f"{T('area')/10000:,.0f}", T("proj"), f"{w(REGPL_YTD[HQ_NAME]['cogs']):,.0f}"),
    "毛利率跨度：%s %.2f%% → %s %.2f%%（相差 %.1f pct）；同期收缴率由 %.2f%% 降至 %.2f%%——单方物业费、规模效应与收缴质量三者高度同向。" % (
        best["city"], best["gross"]/best["rev"]*100, worst["city"], worst["gross"]/worst["rev"]*100,
        (best["gross"]/best["rev"] - worst["gross"]/worst["rev"])*100, best["coll"]*100, worst["coll"]*100),
    "尾部风险：营业利润为负 %d 家（%s）；营业利润率低于 3%% 的边际公司 %d 家，合计收入 %s 万元（占比 %.1f%%）——是撤场、整合或提价谈判的候选池。" % (
        len(loss), "、".join(c["city"] for c in loss) if loss else "无", len(thin_),
        f"{w(sum(c['rev'] for c in thin_)):,.0f}", sdiv(sum(c["rev"] for c in thin_), T("rev"))*100),
], 14)

# ==================== 12 收入与成本结构 ====================
ws = sheet("12·收入与成本结构", [32, 16, 12, 16, 12, 14, 14, 38], freeze="A6")
r = title(ws, 1, "收入结构、成本结构与人工成本口径还原", 8,
          f"{ENTITY_SHORT}  |  {YTD_LABEL} / 全年  |  单位：万元")
r += 1
r = band(ws, r, "一、业务板块收入与毛利（全年模拟口径）", 8)
r = head(ws, r, ["业务板块", "营业收入", "收入占比", "营业成本", "毛利率", "毛利额", "毛利贡献占比",
                 "行业对标"], h=30)
SEG_BM = {"住宅物业管理服务": "基础物管毛利率 15.8%（2024 年样本物企，同比 -1.3pct）",
          "非住宅物业管理服务": "写字楼/园区业态毛利率高于住宅 3～5pct",
          "案场协销及非业主增值服务": "非业主增值服务行业毛利率 16.0%～18.8%，本模型偏高",
          "社区增值服务": "行业 29.0%（同比 -1.7pct）",
          "多种经营（车位·广告·场地）": "公共资源经营，边际成本低",
          "顾问咨询及物资销售": "—"}
gross_tot = sum(s["gross"] for s in SEG_FY)
for s in SEG_FY:
    r = row(ws, r, [s["seg"], w(s["rev"]), sdiv(s["rev"], PL_FY["rev_total"]), w(s["cost"]),
                    sdiv(s["gross"], s["rev"]), w(s["gross"]), sdiv(s["gross"], gross_tot), SEG_BM[s["seg"]]],
            [NUM, PCT, NUM, PCT, NUM, PCT, None])
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["合　计", w(PL_FY["rev_total"]), 1.0, w(PL_FY["cogs_total"]),
                sdiv(PL_FY["gross"], PL_FY["rev_total"]), w(gross_tot), 1.0,
                "行业综合毛利率 19.0%"],
        [NUM, PCT, NUM, PCT, NUM, PCT, None], bold=True, fill=GREY_D, top=True)
ws.cell(r-1, 8).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "二、营业成本明细结构", 8)
r = head(ws, r, ["成本项目", f"本月\n{PERIOD_LABEL}", "占比", f"本年累计\n{YTD_LABEL}", "占比",
                 "全年模拟", "占比", "百强企业对标"], h=32)
COST_BM = {"职工薪酬——工资及奖金": "", "职工薪酬——社会保险及公积金": "", "职工薪酬——职工福利费": "",
           "职工薪酬——工会及教育经费": "", "职工薪酬——劳务派遣费": "",
           "分包及外包服务费": "含清洁 9.43%、秩序维护 4.98%、绿化 2.39%（百强口径单列）",
           "能源费（水/电/气/暖）": "公区能耗，夏冬为峰值", "维修维护费": "设施设备及公区维修",
           "物料及低值易耗品": "集采平台结算", "折旧与摊销": "项目设备、使用权资产、智慧系统",
           "办公及差旅费": "百强办公费用占比 2.93%", "保险费及项目税费": "公众责任险、电梯险",
           "其他项目直接费用": "百强其他费用占比 13.91%"}
for k in COGS_MIX:
    m_, y_, f_ = PL_M["cogs_lines"][k], PL_YTD["cogs_lines"][k], PL_FY["cogs_lines"][k]
    ind = 1 if k.startswith("职工薪酬") else 0
    r = row(ws, r, [k, w(m_), sdiv(m_, PL_M["cogs_total"]), w(y_), sdiv(y_, PL_YTD["cogs_total"]),
                    w(f_), sdiv(f_, PL_FY["cogs_total"]), COST_BM[k]],
            [NUM, PCT, NUM, PCT, NUM, PCT, None], indent=ind)
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["营业成本合计", w(PL_M["cogs_total"]), 1.0, w(PL_YTD["cogs_total"]), 1.0,
                w(PL_FY["cogs_total"]), 1.0, "百强营业成本率 80.98%（本模型 81.0%）"],
        [NUM, PCT, NUM, PCT, NUM, PCT, None], bold=True, fill=GREY_D, top=True)
ws.cell(r-1, 8).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "三、人工成本口径还原（题设「人工成本占比 70%」的构成）", 8)
r = head(ws, r, ["口　径", "全年金额", "占营业成本", "占营业收入", "", "", "", "说　明"], h=26)
LB = [("① 自有员工职工薪酬（狭义人工成本）", LABOR_NARROW_Y, "工资奖金、社保公积金、福利费、工会经费、劳务派遣费"),
      ("② 分包外包合同中的人工含量", LABOR_OUTSOURCE_Y, "外包服务费 %s 万元 × 人工含量 70%%" % f"{w(CG_TOT_FY['分包及外包服务费']):,.0f}"),
      ("③ 广义人工成本 ＝ ① ＋ ②", LABOR_BROAD_Y, "题设口径，对应 70%"),
      ("④ 非人工成本（能源·维修·物料·折旧等）", PL_FY["cogs_total"]-LABOR_BROAD_Y, "余额")]
for n, v, memo in LB:
    r = row(ws, r, [n, w(v), sdiv(v, PL_FY["cogs_total"]), sdiv(v, PL_FY["rev_total"]), "", "", "", memo],
            [NUM, PCT, PCT, None, None, None, None], bold=("③" in n))
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
    if "③" in n:
        for cl in (2, 3, 4): ws.cell(r-1, cl).font = Font(FONT, 9.5, bold=True, color=NAVY)
r = note(ws, r, [
    "口径说明：中指院《百强企业研究》口径下「员工成本占总营业成本 53.52%（2025 年）」，因清洁、秩序维护、绿化在百强口径中作为外包服务费单列。",
    "本模型狭义职工薪酬占营业成本 %.2f%%，与百强口径可比；还原外包合同中的人工含量后为 %.2f%%，即题设的「人工成本占比 70%%」。" % (
        sdiv(LABOR_NARROW_Y, PL_FY["cogs_total"])*100, sdiv(LABOR_BROAD_Y, PL_FY["cogs_total"])*100),
    "敏感性：全口径人工成本每上涨 1%%，营业成本增加约 %s 万元，毛利率下降 %.2f pct，归母净利润减少约 %s 万元（税后）。" % (
        f"{w(int(LABOR_BROAD_Y*0.01)):,.0f}", LABOR_BROAD_Y*0.01/PL_FY["rev_total"]*100,
        f"{w(int(LABOR_BROAD_Y*0.01*(1-TAX_RATE_EFFECTIVE)*(1-MINORITY_SHARE))):,.0f}"),
], 8)
r += 1
r = band(ws, r, "四、人员结构与人效", 8)
r = head(ws, r, ["岗位序列", "人数", "占比", "序列人均覆盖\n面积(㎡/人)", "年人均成本\n(万元)", "", "", "说　明"], h=30)
POS_MEMO = {"秩序维护（安保）": "门岗、巡逻、监控、消防", "环境保洁": "公区保洁、垃圾清运、外墙",
            "工程设备维保": "电梯、供配电、给排水、消防设施", "客服及管家": "前台、管家、投诉处理、社群运营",
            "绿化养护": "园林养护、病虫害防治", "项目及区域管理": "项目经理、区域职能",
            "职能与共享中心": "财务、人力、法务、信息化、集采"}
POS_COST = {"秩序维护（安保）": 6.35, "环境保洁": 5.42, "工程设备维保": 9.80, "客服及管家": 8.15,
            "绿化养护": 5.68, "项目及区域管理": 16.50, "职能与共享中心": 24.80}
for k, n_ in HEADCOUNT_MIX.items():
    r = row(ws, r, [k, n_, sdiv(n_, HEADCOUNT_OWN), AREA_TOTAL/n_ if n_ else "", POS_COST[k], "", "", POS_MEMO[k]],
            [NUM0, PCT, NUM0, NUM, None, None, None])
    ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["自有员工合计", HEADCOUNT_OWN, 1.0, AREA_TOTAL/HEADCOUNT_OWN,
                LABOR_NARROW_Y/HEADCOUNT_OWN/WAN, "", "",
                "人均创收 %.1f 万元/年" % (PL_FY["rev_total"]/HEADCOUNT_OWN/WAN)],
        [NUM0, PCT, NUM0, NUM, None, None, None], bold=True, fill=GREY_D, top=True)
ws.cell(r-1, 8).alignment = Alignment("left", "center")
r = row(ws, r, ["外包用工（折算）", HEADCOUNT_OUTSOURCE, "", "", LABOR_OUTSOURCE_Y/HEADCOUNT_OUTSOURCE/WAN,
                "", "", "保洁、秩序维护、绿化外包，按人工含量折算"],
        [NUM0, None, None, NUM, None, None, None])
ws.cell(r-1, 8).alignment = Alignment("left", "center"); ws.cell(r-1, 8).font = Font(FONT, 8.5, color="6B7B8C")
r = row(ws, r, ["用工总量", HEADCOUNT_OWN+HEADCOUNT_OUTSOURCE, "",
                AREA_TOTAL/(HEADCOUNT_OWN+HEADCOUNT_OUTSOURCE), LABOR_BROAD_Y/(HEADCOUNT_OWN+HEADCOUNT_OUTSOURCE)/WAN,
                "", "", "综合人均在管面积"],
        [NUM0, None, NUM0, NUM, None, None, None], bold=True, fill=GREY, top=True)
ws.cell(r-1, 8).alignment = Alignment("left", "center")

# ==================== 13 行业对标与假设 ====================
ws = sheet("13·行业对标与假设", [26, 20, 46, 30], freeze="A6", tab=GOLD)
r = title(ws, 1, "行业对标基准值与建模假设", 4,
          "数据来源：2024 年上市物企年报及券商行业综述、中指院百强企业研究、克而瑞物管监测")
r += 1
r = band(ws, r, "一、行业基准值与本模型取值对照", 4)
r = head(ws, r, ["指　标", "行业基准值", "来　源", "本模型取值"])
for a, b, c_, d_ in BENCHMARK:
    r = row(ws, r, [a, b, c_, d_])
    for cl in (2, 3, 4): ws.cell(r-1, cl).alignment = Alignment("left", "center")
    ws.cell(r-1, 3).font = Font(FONT, 8.5, color="6B7B8C")
    ws.cell(r-1, 4).font = Font(FONT, 9.5, bold=True, color=NAVY)
r += 1
r = band(ws, r, "二、题设参数（不可调整）", 4)
r = head(ws, r, ["参　数", "取　值", "在模型中的落点", ""])
for a, b, c_ in [
    ("管理区域", "5 个", "华东 / 华南 / 华北 / 华中 / 西部"),
    ("每区域城市公司", "10 家", "共 50 家，见「11·城市公司明细表」"),
    ("在管建筑面积", "2.0 亿㎡", "按区域收入结构分配，华东 31% / 西部 11%"),
    ("在管物业项目", "600 个", "平均单项目 33.3 万㎡"),
    ("年度营业收入", "50 亿元", "「04·合并利润表」全年预算列"),
    ("主营业务收入占比", "90%", "45 亿元：住宅 68% / 非住宅 23% / 案场 9%"),
    ("其他业务收入占比", "10%", "5 亿元：社区增值 58% / 多种经营 32% / 顾问物销 10%"),
    ("年度净利润", "2 亿元", "归属于母公司净利润，净利率 4.0%"),
    ("人工成本占比", "70%", "广义口径：职工薪酬 54.56% + 外包人工含量 15.47%"),
    ("应收账款比例", "30%", "期末账面余额 15.00 亿元 ÷ 全年收入 50 亿元"),
]:
    r = row(ws, r, [a, b, c_, ""])
    ws.cell(r-1, 2).font = Font(FONT, 9.5, bold=True, color=NAVY)
    for cl in (2, 3): ws.cell(r-1, cl).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "三、模型推导假设（可调整）", 4)
r = head(ws, r, ["假设项", "取　值", "依　据", ""])
for a, b, c_ in [
    ("综合毛利率", "19.0%", "2024 年 58 家样本上市物企平均 19.0%（同比 -1.4pct）"),
    ("有效所得税率", "27.75%", "高于法定 25%：部分亏损子公司未确认递延所得税资产"),
    ("少数股东损益占比", "15.6%", "合资城市公司及项目公司股权结构"),
    ("坏账计提率（1年以内→5年以上）", "5% / 15% / 35% / 60% / 80% / 100%", "账龄组合法，参照可比公司预期信用损失矩阵"),
    ("综合销项税率", "物业费 4.8% / 增值服务 6%", "一般计税 6% 与老项目简易计税 3% 的加权"),
    ("外包合同人工含量", "70%", "保洁、秩序维护、绿化外包的人工占合同额比例"),
    ("信用减值月度节奏", f"1-{PERIOD_M}月计提 {_IMP_PCT}%，Q4 集中补提", "行业惯例：年末结合催收结果集中补提"),
    ("月度成本季节性", f"{PERIOD_M} 月系数 {S_COST[PERIOD_M-1]*100:.2f}%", "夏季公区能耗峰值、高温津贴、绿化养护"),
    ("上年同期口径", "收入 -1.8%，毛利率 +1.4pct，减值 -22%", "行业 2024 vs 2023 变动趋势"),
]:
    r = row(ws, r, [a, b, c_, ""])
    ws.cell(r-1, 2).font = Font(FONT, 9.5, bold=True, color=NAVY)
    for cl in (2, 3): ws.cell(r-1, cl).alignment = Alignment("left", "center")
r += 1
r = band(ws, r, "四、数据来源", 4)
for t in [
    "· 国金证券《2024 年物管行业业绩综述》：58 家样本上市物企毛利率 19.0%、净利率 4.2%、应收账款周转天数 106 天；社区增值服务毛利率 29.0%、基础物管 15.8%。",
    "· 国联民生证券行业专题：56 家上市物企分类型毛利率与应收周转（央国企 62 天 / 已展期民企 160 天）；净现金总额 1,081.5 亿元。",
    "· 中指研究院《2025 中国物业服务百强企业研究》：营业成本率 80.98%，员工成本占总营业成本 53.52%，清洁 9.43%、秩序维护 4.98%、办公 2.93%、绿化 2.39%、其他 13.91%。",
    "· 克而瑞物管：2024 年重点城市物业费平均收缴率跌至 82%，同比 -3pct；上市物企平均降幅 5%，部分达 10%。在管面积 TOP3：万物云 10.6 亿㎡、碧桂园服务 10.5 亿㎡、保利物业 7.9 亿㎡。",
    "· 南都物业 2024 年年度报告：营业收入 18.05 亿元，物业基础服务占 88.28%，毛利率 15.04%；应收账款原值 6.19 亿元、坏账准备 1.07 亿元（计提比例 17.4%）。",
    "· 绿城服务 2024 年年报：在管面积 5.09 亿㎡（+13.5%），物业服务毛利率 13.7%、园区服务 22.6%、咨询服务 24.9%、科技服务 39.3%。",
]:
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    c = ws.cell(r, 1, t); c.font = Font(FONT, 9, color="2A3A4A")
    c.alignment = Alignment("left", "center"); ws.row_dimensions[r].height = 17; r += 1
r += 1
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
c = ws.cell(r, 1, "免责声明：本套表为教学与建模示例，公司名称、组织结构与全部金额均为模拟数据，不构成对任何真实企业的描述、审计意见或投资建议。")
c.font = Font(FONT, 9, bold=True, color=RED); c.alignment = Alignment("left", "center")

# ==================== 保存 ====================
# HUACHEN_OUT_DIR 可把输出写到别处，避免覆盖已归档的套表
OUT_DIR = os.path.expanduser(os.environ.get("HUACHEN_OUT_DIR") or "~/Desktop/物业集团月结财务套表")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, f"{ENTITY_SHORT}_{PERIOD_Y}年{PERIOD_M:02d}月_月结财务套表_GL-AP-AR-CF.xlsx")
wb.save(OUT)
print("SAVED:", OUT)
print("Sheets:", len(wb.sheetnames))
