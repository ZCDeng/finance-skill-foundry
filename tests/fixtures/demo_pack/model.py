# -*- coding: utf-8 -*-
"""
华宸物业服务集团 2026年8月 月结财务套表 —— 数据模型层
所有金额单位：元（整数）。对标口径见 BENCHMARK。
"""
import os
from collections import OrderedDict, defaultdict

# 演示开关（build_demo.py 设置）。HUACHEN_DEMO=1 时保留两处「必须检出」的差异：
#   F-01 账单年度坏账按账龄段比例直接相乘，分项合计 33,780 万 ≠ 账龄组合 22,125 万
#   F-02 合同台账实收不回调到月结区域实收，台账少约 2,793 万
# 同时把 2025 年全年收入抬到 57 亿（四季度一次性案场收入），让「按去年节奏估全年」与 LE 拉开差距。
DEMO = os.environ.get("HUACHEN_DEMO") == "1"
PY_FULL_REV_DEMO = 5_700_000_000   # 演示版 2025 年全年营业收入（元）

YI = 100_000_000          # 亿
WAN = 10_000              # 万

# ============================================================
# 0. 行业对标（来源见 sources.md）
# ============================================================
BENCHMARK = [
    ("综合毛利率", "19.0%", "2024年58家样本上市物企（国金证券行业综述）", "本模型 19.0%"),
    ("基础物管毛利率", "15.8%", "2024年样本物企，同比-1.3pct", "本模型基础物管 15.6%"),
    ("社区增值服务毛利率", "29.0%", "2024年样本物企，同比-1.7pct", "本模型 30.8%"),
    ("净利率", "4.2%", "2024年样本物企，同比-1.2~1.3pct", "本模型归母 4.0% / 全口径 4.7%"),
    ("应收账款周转天数", "106天", "2024年58家样本物企（2023年105天）", "本模型 109.5天"),
    ("应收账款/营业收入", "34.3%", "南都物业2024年报：AR原值6.19亿/营收18.05亿", "本模型 30.0%（题设）"),
    ("坏账准备计提比例", "17.4%", "南都物业2024年报：1.07亿/6.19亿", "本模型 14.8%"),
    ("物业费收缴率", "82%", "2024年重点城市均值（克而瑞物管），同比-3pct", "本模型综合 82.4%"),
    ("员工成本/营业成本", "53.5%", "2025年百强企业均值（中指院），2024年约54.7%", "本模型狭义 54.6%"),
    ("清洁卫生费/营业成本", "9.4%", "2025年百强企业均值", "含于分包及外包服务费"),
    ("秩序维护费/营业成本", "5.0%", "2025年百强企业均值", "含于分包及外包服务费"),
    ("营业成本率", "81.0%", "2025年百强企业均值", "本模型 81.0%"),
    ("在管面积（行业头部）", "10.6/10.5/7.9亿㎡", "万物云/碧桂园服务/保利物业 2024年末", "本模型 2.0亿㎡（TOP20量级）"),
]

# ============================================================
# 1. 主体与期间参数
# ============================================================
ENTITY = "华宸物业服务集团股份有限公司"
ENTITY_SHORT = "华宸物业"
PERIOD_Y, PERIOD_M = 2026, int(os.environ.get("HUACHEN_PERIOD_M") or 8)
PERIOD_LABEL = f"{PERIOD_Y}年{PERIOD_M:02d}月"
YTD_LABEL = f"{PERIOD_Y}年1-{PERIOD_M}月"

AREA_TOTAL = 200_000_000          # 2亿㎡
PROJECT_TOTAL = 600
HEADCOUNT_OWN = 32_000            # 自有在册员工
HEADCOUNT_OUTSOURCE = 11_400      # 外包用工（折算）

# ============================================================
# 2. 年度损益模型（全年模拟 / 预算口径）
# ============================================================
REV_TOTAL_Y   = 50 * YI
REV_MAIN_Y    = int(REV_TOTAL_Y * 0.90)   # 主营业务收入 45亿
REV_OTHER_Y   = REV_TOTAL_Y - REV_MAIN_Y  # 其他业务收入 5亿

# 主营业务收入细分（合计 = REV_MAIN_Y）
REV_MAIN_MIX = OrderedDict([
    ("住宅物业管理服务", 0.680),
    ("非住宅物业管理服务", 0.230),
    ("案场协销及非业主增值服务", 0.090),
])
# 其他业务收入细分（合计 = REV_OTHER_Y）
REV_OTHER_MIX = OrderedDict([
    ("社区增值服务", 0.580),
    ("多种经营（车位·广告·场地）", 0.320),
    ("顾问咨询及物资销售", 0.100),
])

# 营业成本明细（合计 = 40.50亿 = 收入 81.0%）
COGS_TOTAL_Y = int(REV_TOTAL_Y * 0.810)
COGS_MIX = OrderedDict([
    ("职工薪酬——工资及奖金",        0.4000),
    ("职工薪酬——社会保险及公积金",   0.0975),
    ("职工薪酬——职工福利费",        0.0259),
    ("职工薪酬——工会及教育经费",     0.0074),
    ("职工薪酬——劳务派遣费",        0.0148),
    ("分包及外包服务费",            0.2210),
    ("能源费（水/电/气/暖）",        0.0704),
    ("维修维护费",                 0.0580),
    ("物料及低值易耗品",            0.0284),
    ("折旧与摊销",                 0.0270),
    ("办公及差旅费",               0.0153),
    ("保险费及项目税费",            0.0070),
    ("其他项目直接费用",            0.0273),
])
# 分包外包合同中的人工含量（用于还原广义人工成本口径）
OUTSOURCE_LABOR_RATIO = 0.700

OPEX_Y = OrderedDict([
    ("税金及附加",     15_000_000),
    ("销售费用",       55_000_000),
    ("管理费用",      375_000_000),
    ("研发费用",       35_000_000),
    ("财务费用",      -15_000_000),   # 净利息收入
])
IMPAIR_Y = OrderedDict([
    ("信用减值损失",  185_000_000),
    ("资产减值损失",   20_000_000),
])
OTHER_INC_Y = OrderedDict([
    ("其他收益",       30_000_000),
    ("投资收益",       12_000_000),
    ("公允价值变动收益", 2_000_000),
    ("资产处置收益",    1_000_000),
])
NONOP_Y = OrderedDict([("营业外收入", 5_000_000), ("营业外支出", 2_000_000)])
TAX_RATE_EFFECTIVE = 0.2775          # 有效税率（部分亏损子公司递延资产不确认）
MINORITY_SHARE = 0.15604692               # 少数股东损益占净利润比

# ============================================================
# 3. 月度分布系数
# ============================================================
def _norm(xs):
    s = sum(xs)
    return [x / s for x in xs]

# 基础物业费：随在管面积逐月爬坡，季节性弱
S_BASE = _norm([1 + 0.0060 * (m - 6.5) for m in range(1, 13)])
# 案场协销：跟随地产推盘节奏
S_DEV  = _norm([0.070,0.065,0.085,0.090,0.085,0.090,0.080,0.075,0.085,0.090,0.090,0.095])
# 社区增值 / 多经：Q1 春节低，Q4 冲刺高
S_VAS  = _norm([0.055,0.050,0.075,0.080,0.085,0.090,0.085,0.080,0.090,0.095,0.105,0.110])
# 营业成本：夏冬能源高、年末年终奖计提
S_COST = _norm([0.0790,0.0765,0.0815,0.0818,0.0832,0.0855,0.0862,0.0852,0.0835,0.0828,0.0840,0.0908])
# 期间费用：Q4 集中
S_OPEX = _norm([0.075,0.072,0.081,0.082,0.083,0.086,0.083,0.082,0.085,0.088,0.090,0.093])
# 减值：前8月按月匀提，Q4 集中补提（行业惯例）
S_IMPAIR = _norm([0.065]*8 + [0.080,0.100,0.130,0.170])
# 其他收益等：政府补助集中在 Q2/Q4
S_MISC = _norm([0.060,0.060,0.080,0.110,0.090,0.095,0.075,0.075,0.085,0.090,0.090,0.090])

def alloc(total, coefs, m):
    """第 m 月金额（1-based），末月吸收舍入差"""
    if m == 12:
        return total - sum(int(round(total * c)) for c in coefs[:11])
    return int(round(total * coefs[m - 1]))

def alloc_ytd(total, coefs, upto):
    return sum(alloc(total, coefs, m) for m in range(1, upto + 1))

# ============================================================
# 4. 三口径损益表（本月 / 本年累计 / 全年）
# ============================================================
def build_pl(scope):
    """scope: 'M'(本月) | 'YTD'(1-8月) | 'FY'(全年)"""
    def A(total, coefs):
        if scope == "FY":  return total
        if scope == "M":   return alloc(total, coefs, PERIOD_M)
        return alloc_ytd(total, coefs, PERIOD_M)

    rev_main_lines = OrderedDict()
    for k, w in REV_MAIN_MIX.items():
        base = int(round(REV_MAIN_Y * w))
        coefs = S_DEV if "案场" in k else S_BASE
        rev_main_lines[k] = A(base, coefs)
    rev_other_lines = OrderedDict()
    for k, w in REV_OTHER_MIX.items():
        rev_other_lines[k] = A(int(round(REV_OTHER_Y * w)), S_VAS)

    rev_main = sum(rev_main_lines.values())
    rev_other = sum(rev_other_lines.values())
    rev_total = rev_main + rev_other

    cogs_lines = OrderedDict()
    for k, w in COGS_MIX.items():
        cogs_lines[k] = A(int(round(COGS_TOTAL_Y * w)), S_COST)
    cogs_total = sum(cogs_lines.values())

    opex = OrderedDict((k, A(v, S_OPEX)) for k, v in OPEX_Y.items())
    impair = OrderedDict((k, A(v, S_IMPAIR)) for k, v in IMPAIR_Y.items())
    other_inc = OrderedDict((k, A(v, S_MISC)) for k, v in OTHER_INC_Y.items())
    nonop = OrderedDict((k, A(v, S_MISC)) for k, v in NONOP_Y.items())

    op_profit = (rev_total - cogs_total - sum(opex.values())
                 - sum(impair.values()) + sum(other_inc.values()))
    ebt = op_profit + nonop["营业外收入"] - nonop["营业外支出"]
    tax = int(round(ebt * TAX_RATE_EFFECTIVE))
    net = ebt - tax
    minority = int(round(net * MINORITY_SHARE))
    parent = net - minority

    return OrderedDict(
        scope=scope, rev_main_lines=rev_main_lines, rev_other_lines=rev_other_lines,
        rev_main=rev_main, rev_other=rev_other, rev_total=rev_total,
        cogs_lines=cogs_lines, cogs_total=cogs_total, gross=rev_total - cogs_total,
        opex=opex, impair=impair, other_inc=other_inc, nonop=nonop,
        op_profit=op_profit, ebt=ebt, tax=tax, net=net,
        minority=minority, parent=parent,
    )

PL_M   = build_pl("M")
PL_YTD = build_pl("YTD")
PL_FY  = build_pl("FY")

# 主营/其他业务成本拆分（按毛利率倒推：其他业务毛利率显著高于主营）
def split_cogs(pl):
    """其他业务（社区增值+多经）毛利率 30.8%，倒推主营业务成本"""
    other_gm = 0.308
    cogs_other = int(round(pl["rev_other"] * (1 - other_gm)))
    return pl["cogs_total"] - cogs_other, cogs_other

for _pl in (PL_M, PL_YTD, PL_FY):
    _pl["cogs_main"], _pl["cogs_other"] = split_cogs(_pl)

# 上年同期（用于同比）：收入 -1.8%，毛利率高 0.9pct，减值少 15%
def build_ly(pl):
    rev = int(round(pl["rev_total"] / 0.982))
    gross = int(round(rev * ((pl["gross"] / pl["rev_total"]) + 0.009)))
    cogs = rev - gross
    opex_t = int(round(sum(pl["opex"].values()) * 0.985))
    imp = int(round(sum(pl["impair"].values()) * 0.85))
    oth = int(round(sum(pl["other_inc"].values()) * 1.06))
    op = rev - cogs - opex_t - imp + oth
    ebt = op + int(round((pl["nonop"]["营业外收入"] - pl["nonop"]["营业外支出"]) * 1.1))
    tax = int(round(ebt * 0.265))
    net = ebt - tax
    return dict(rev_total=rev, cogs_total=cogs, gross=gross, opex_total=opex_t,
                impair_total=imp, other_inc_total=oth, op_profit=op, ebt=ebt,
                tax=tax, net=net, parent=net - int(round(net * 0.150)))

LY_M, LY_YTD = build_ly(PL_M), build_ly(PL_YTD)

# ============================================================
# 5. 区域与城市公司
# ============================================================
# (区域, 面积占比, 收入占比, 项目数, 毛利率, 本年账单收缴率, AR占比)
REGIONS = OrderedDict([
    ("华东区域", dict(area=0.3100, rev=0.3370, proj=182, gm=0.2120, coll=0.902, ar=0.2760)),
    ("华南区域", dict(area=0.2200, rev=0.2240, proj=128, gm=0.2050, coll=0.886, ar=0.2010)),
    ("华北区域", dict(area=0.1900, rev=0.1810, proj=116, gm=0.1890, coll=0.871, ar=0.1930)),
    ("华中区域", dict(area=0.1700, rev=0.1550, proj=105, gm=0.1800, coll=0.854, ar=0.1750)),
    ("西部区域", dict(area=0.1100, rev=0.1030, proj=69,  gm=0.1720, coll=0.842, ar=0.1550)),
])
HQ_NAME = "集团本部及共享中心"

CITY_NAMES = {
    "华东区域": ["上海","杭州","南京","苏州","宁波","合肥","无锡","常州","南通","徐州"],
    "华南区域": ["广州","深圳","佛山","东莞","珠海","中山","厦门","福州","南宁","海口"],
    "华北区域": ["北京","天津","青岛","济南","石家庄","大连","太原","烟台","唐山","保定"],
    "华中区域": ["武汉","长沙","郑州","南昌","洛阳","宜昌","株洲","襄阳","九江","赣州"],
    "西部区域": ["成都","重庆","西安","昆明","贵阳","兰州","绵阳","南充","遵义","宝鸡"],
}
# 城市公司在区域内的权重（第1家为区域中心城市，规模最大）
CITY_W = _norm([0.185,0.148,0.123,0.108,0.098,0.088,0.076,0.066,0.058,0.050])

def build_regions(pl):
    """按区域拆分收入/成本/毛利；HQ 承担集中成本，轧平至合并数"""
    rows = OrderedDict()
    rev_acc = cogs_acc = 0
    keys = list(REGIONS)
    for i, r in enumerate(keys):
        cfg = REGIONS[r]
        if i == len(keys) - 1:
            rev = pl["rev_total"] - rev_acc
        else:
            rev = int(round(pl["rev_total"] * cfg["rev"]))
        cogs = int(round(rev * (1 - cfg["gm"])))
        rows[r] = dict(rev=rev, cogs=cogs, gross=rev - cogs,
                       area=int(round(AREA_TOTAL * cfg["area"])), proj=cfg["proj"])
        rev_acc += rev; cogs_acc += cogs
    rows[HQ_NAME] = dict(rev=0, cogs=pl["cogs_total"] - cogs_acc, gross=-(pl["cogs_total"] - cogs_acc),
                         area=0, proj=0)
    return rows

REG_M, REG_YTD, REG_FY = build_regions(PL_M), build_regions(PL_YTD), build_regions(PL_FY)

# 区域完整损益（分摊期间费用与减值）
def region_pl(pl, reg):
    """区域层完整利润表：期间费用按收入分摊(HQ 自留 22%)，减值按 AR 占比分摊"""
    opex_t = sum(pl["opex"].values())
    hq_opex = int(round(opex_t * 0.220))
    out = OrderedDict()
    acc_opex = 0
    keys = [k for k in reg if k != HQ_NAME]
    for i, r in enumerate(keys):
        share = reg[r]["rev"] / pl["rev_total"]
        o = (opex_t - hq_opex - acc_opex) if i == len(keys) - 1 else int(round((opex_t - hq_opex) * share))
        acc_opex += o
        imp = int(round(sum(pl["impair"].values()) * REGIONS[r]["ar"]))
        oi = int(round(sum(pl["other_inc"].values()) * share))
        out[r] = dict(**reg[r], opex=o, impair=imp, other_inc=oi,
                      op=reg[r]["gross"] - o - imp + oi)
    imp_hq = sum(pl["impair"].values()) - sum(v["impair"] for v in out.values())
    oi_hq = sum(pl["other_inc"].values()) - sum(v["other_inc"] for v in out.values())
    out[HQ_NAME] = dict(**reg[HQ_NAME], opex=hq_opex, impair=imp_hq, other_inc=oi_hq,
                        op=reg[HQ_NAME]["gross"] - hq_opex - imp_hq + oi_hq)
    return out

REGPL_M, REGPL_YTD = region_pl(PL_M, REG_M), region_pl(PL_YTD, REG_YTD)

# 收入权重（规模越大单方物业费越高）与毛利率分档，均做零和归一化
CITY_WR = _norm([w * (1 + 0.09 * (w - 0.10) / 0.10) for w in CITY_W])
_GM_ADJ_RAW = [0.030, 0.030, 0.014, 0.014, 0.010, 0.002, -0.006, -0.022, -0.038, -0.056]
_GM_MEAN = sum(CITY_WR[i] * _GM_ADJ_RAW[i] for i in range(10))
CITY_GM_ADJ = [a - _GM_MEAN for a in _GM_ADJ_RAW]          # 收入加权后净影响为 0
_COLL_ADJ_RAW = [0.024, 0.024, 0.011, 0.011, 0.006, 0.001, -0.005, -0.018, -0.030, -0.042]
_COLL_MEAN = sum(CITY_WR[i] * _COLL_ADJ_RAW[i] for i in range(10))
CITY_COLL_ADJ = [a - _COLL_MEAN for a in _COLL_ADJ_RAW]

def build_cities(regpl_ytd, ar_by_region):
    """50 家城市公司明细，权重法拆分并在区域内轧平"""
    rows = []
    for r in REGIONS:
        R = regpl_ytd[r]
        n = len(CITY_NAMES[r])
        acc = defaultdict(int)
        for i, c in enumerate(CITY_NAMES[r]):
            last = (i == n - 1)
            def take(key, total, weight):
                if last: return total - acc[key]
                v = int(round(total * weight)); acc[key] += v; return v
            area = take("area", R["area"], CITY_W[i])
            proj = take("proj", R["proj"], CITY_W[i])
            rev  = take("rev",  R["rev"],  CITY_WR[i])
            gm = REGIONS[r]["gm"] + CITY_GM_ADJ[i]
            cogs = int(round(rev * (1 - gm))) if not last else R["cogs"] - acc["cogs"]
            if not last: acc["cogs"] += cogs
            opex = take("opex", R["opex"], CITY_WR[i])
            imp  = take("impair", R["impair"], CITY_WR[i])
            oi   = take("other_inc", R["other_inc"], CITY_WR[i])
            ar   = take("ar", ar_by_region[r], CITY_WR[i])
            coll = REGIONS[r]["coll"] + CITY_COLL_ADJ[i]
            rows.append(dict(region=r, city=f"{c}城市公司", area=area, proj=proj,
                             rev=rev, cogs=cogs, gross=rev - cogs, opex=opex,
                             impair=imp, other_inc=oi, op=rev - cogs - opex - imp + oi,
                             ar=ar, coll=coll))
    return rows

# ============================================================
# 6. 应收账款（AR）
# ============================================================
AR_GROSS = 15 * YI                      # 8月末应收账款账面余额（含税）= 全年收入 30%
AR_AGING = OrderedDict([                # 账龄 -> (占比, 预期信用损失率)
    ("1年以内（含1年）", (0.620, 0.05)),
    ("1至2年",          (0.210, 0.15)),
    ("2至3年",          (0.100, 0.35)),
    ("3至4年",          (0.040, 0.60)),
    ("4至5年",          (0.020, 0.80)),
    ("5年以上",         (0.010, 1.00)),
])
# 客户类别（物业公司特有：业主/关联方地产/政企/商户）
AR_CUSTOMER = OrderedDict([
    ("业主及住户（住宅）",      0.462),
    ("业主及租户（非住宅）",    0.183),
    ("关联方房地产开发企业",    0.152),
    ("政府及国企类客户",       0.121),
    ("商户及第三方合作方",      0.082),
])

def build_ar():
    rows, acc_g, acc_p = [], 0, 0
    keys = list(AR_AGING)
    for i, (k) in enumerate(keys):
        w, rate = AR_AGING[k]
        g = (AR_GROSS - acc_g) if i == len(keys) - 1 else int(round(AR_GROSS * w))
        p = int(round(g * rate))
        acc_g += g; acc_p += p
        rows.append(dict(aging=k, gross=g, rate=rate, prov=p, net=g - p))
    return rows

AR_ROWS = build_ar()
AR_PROV = sum(r["prov"] for r in AR_ROWS)
AR_NET = AR_GROSS - AR_PROV

def ar_by_region():
    out, acc = OrderedDict(), 0
    keys = list(REGIONS)
    for i, r in enumerate(keys):
        v = (AR_GROSS - acc) if i == len(keys) - 1 else int(round(AR_GROSS * REGIONS[r]["ar"]))
        acc += v; out[r] = v
    return out

AR_REGION = ar_by_region()
CITY_ROWS = build_cities(REGPL_YTD, AR_REGION)

# 收缴率：本年账单 vs 含往年欠费的综合收缴率
BILLED_YTD = int(round(PL_YTD["rev_main_lines"]["住宅物业管理服务"] * 1.048
                       + PL_YTD["rev_main_lines"]["非住宅物业管理服务"] * 1.048))
COLL_RATE_CY = sum(REGIONS[r]["coll"] * REGIONS[r]["rev"] for r in REGIONS) / sum(REGIONS[r]["rev"] for r in REGIONS)
ARREARS_OPENING = int(round(AR_GROSS * 0.38))     # 年初结转的往年欠费
COLL_RATE_TOTAL = 0.824                            # 综合收缴率（含往年欠费清收）

def _ar_add_ytd():
    """1-8月因确认收入形成的应收账款（含税）"""
    pm = int(round((PL_YTD["rev_main_lines"]["住宅物业管理服务"]
                    + PL_YTD["rev_main_lines"]["非住宅物业管理服务"]) * 1.048 * 0.45))
    dev = int(round(PL_YTD["rev_main_lines"]["案场协销及非业主增值服务"] * 1.06))
    vas = int(round(PL_YTD["rev_other"] * 1.06 * 0.40))
    return pm + dev + vas
AR_ADD_YTD = _ar_add_ytd()

# ============================================================
# 7. 应付账款（AP）
# ============================================================
AP_TOTAL = int(3.42 * YI)
AP_AGING = OrderedDict([
    ("3个月以内", 0.678), ("3至6个月", 0.170), ("6个月至1年", 0.091),
    ("1至2年", 0.044), ("2年以上", 0.017),
])
AP_SUPPLIER = OrderedDict([          # 类别 -> (采购额占比, 合同账期天数, 实际结算天数[未归一])
    ("保洁清洁外包服务商",       (0.196, 45,  53)),
    ("秩序维护（安保）外包服务商",  (0.174, 45,  51)),
    ("绿化养护外包服务商",        (0.082, 60,  65)),
    ("电梯及设备维保服务商",      (0.148, 60,  72)),
    ("水电气热能源供应商",        (0.163, 30,  32)),
    ("工程维修及改造承包商",      (0.098, 90, 138)),
    ("物料及低值易耗品供应商",    (0.071, 60,  69)),
    ("信息化及其他服务商",        (0.068, 60,  74)),
])
AP_REGION_LAG = OrderedDict([        # 区域付款节奏系数（现金紧张的区域账期更长）
    ("华东区域", 0.90), ("华南区域", 0.95), ("华北区域", 1.02),
    ("华中区域", 1.10), ("西部区域", 1.18),
])
AP_SETTLE_BASE_Y = (COGS_TOTAL_Y * (COGS_MIX["分包及外包服务费"] + COGS_MIX["能源费（水/电/气/暖）"]
                    + COGS_MIX["维修维护费"] + COGS_MIX["物料及低值易耗品"]
                    + COGS_MIX["其他项目直接费用"]))

def build_ap():
    rows, acc = [], 0
    keys = list(AP_AGING)
    for i, k in enumerate(keys):
        v = (AP_TOTAL - acc) if i == len(keys) - 1 else int(round(AP_TOTAL * AP_AGING[k]))
        acc += v
        rows.append(dict(aging=k, amt=v))
    return rows
AP_ROWS = build_ap()

# ============================================================
# 8. 资产负债表（8月末 / 年初），单位：万元 → 元
# ============================================================
def W(x): return int(round(x * WAN))

BS_ASSET_CUR = [   # (科目, 8月末万元, 年初万元)
    ("货币资金",          186_000, None),        # None = 轧平项
    ("交易性金融资产",      32_000, 26_000),
    ("应收账款",       AR_NET / WAN, 109_300),
    ("应收款项融资",         1_500, 2_200),
    ("预付款项",           10_500, 7_800),
    ("其他应收款",         68_500, 62_000),
    ("合同资产",            8_500, 7_200),
    ("存货",               4_200, 3_500),
    ("其他流动资产",         6_800, 5_500),
]
BS_ASSET_NCUR = [
    ("长期股权投资",        12_000, 11_500),
    ("其他非流动金融资产",     4_500, 4_200),
    ("固定资产",           38_500, 37_200),
    ("使用权资产",          26_500, 28_800),
    ("无形资产",           19_500, 20_500),
    ("商誉",              64_000, 62_800),
    ("长期待摊费用",        11_500, 10_800),
    ("递延所得税资产",       13_500, 11_300),
    ("其他非流动资产",       5_500, 4_800),
]
BS_LIAB_CUR = [
    ("短期借款",           15_000, 8_500),
    ("应付账款",     AP_TOTAL / WAN, 30_500),
    ("合同负债",          128_500, 115_000),
    ("应付职工薪酬",        52_000, 62_000),
    ("应交税费",           13_500, 16_200),
    ("其他应付款",         113_000, 96_000),
    ("一年内到期的非流动负债",  9_500, 8_800),
    ("其他流动负债",        10_500, 9_200),
]
BS_LIAB_NCUR = [
    ("租赁负债",           18_500, 20_500),
    ("长期应付款",          3_500, 3_200),
    ("预计负债",            2_800, 2_500),
    ("递延收益",            2_200, 1_800),
    ("递延所得税负债",        4_500, 3_800),
]
EQ_PAIDIN, EQ_CAPRES, EQ_SURPLUS = W(60_000), W(45_500), W(18_500)
MI_CLOSE = W(24_000)
DIV_PARENT_YTD = int(1.05 * YI)      # 1-8月已宣告并支付的母公司股东股利
DIV_MINOR_YTD  = int(0.30 * YI)      # 支付少数股东股利

def bs_build():
    A_cur_c = [(n, W(c)) for n, c, o in BS_ASSET_CUR]
    A_ncur_c = [(n, W(c)) for n, c, o in BS_ASSET_NCUR]
    L_cur_c = [(n, W(c)) for n, c, o in BS_LIAB_CUR]
    L_ncur_c = [(n, W(c)) for n, c, o in BS_LIAB_NCUR]
    assets_c = sum(v for _, v in A_cur_c) + sum(v for _, v in A_ncur_c)
    liab_c = sum(v for _, v in L_cur_c) + sum(v for _, v in L_ncur_c)
    eq_c = assets_c - liab_c
    ret_c = eq_c - EQ_PAIDIN - EQ_CAPRES - EQ_SURPLUS - MI_CLOSE

    # 年初
    ret_o = ret_c - PL_YTD["parent"] + DIV_PARENT_YTD
    mi_o = MI_CLOSE - PL_YTD["minority"] + DIV_MINOR_YTD
    eq_o = EQ_PAIDIN + EQ_CAPRES + EQ_SURPLUS + ret_o + mi_o
    L_cur_o = [(n, W(o)) for n, c, o in BS_LIAB_CUR]
    L_ncur_o = [(n, W(o)) for n, c, o in BS_LIAB_NCUR]
    liab_o = sum(v for _, v in L_cur_o) + sum(v for _, v in L_ncur_o)
    assets_o = liab_o + eq_o
    A_cur_o, A_ncur_o = [], [(n, W(o)) for n, c, o in BS_ASSET_NCUR]
    known = sum(W(o) for n, c, o in BS_ASSET_CUR if o is not None) + sum(v for _, v in A_ncur_o)
    cash_o = assets_o - known
    for n, c, o in BS_ASSET_CUR:
        A_cur_o.append((n, cash_o if o is None else W(o)))
    return dict(A_cur_c=A_cur_c, A_ncur_c=A_ncur_c, L_cur_c=L_cur_c, L_ncur_c=L_ncur_c,
                A_cur_o=A_cur_o, A_ncur_o=A_ncur_o, L_cur_o=L_cur_o, L_ncur_o=L_ncur_o,
                assets_c=assets_c, assets_o=assets_o, liab_c=liab_c, liab_o=liab_o,
                eq_c=eq_c, eq_o=eq_o, ret_c=ret_c, ret_o=ret_o, mi_c=MI_CLOSE, mi_o=mi_o,
                cash_c=W(186_000), cash_o=cash_o)

BS = bs_build()
BSD_C = dict(BS["A_cur_c"] + BS["A_ncur_c"] + BS["L_cur_c"] + BS["L_ncur_c"])
BSD_O = dict(BS["A_cur_o"] + BS["A_ncur_o"] + BS["L_cur_o"] + BS["L_ncur_o"])
def d(k): return BSD_C[k] - BSD_O[k]

# 应收账款原值/坏账准备 两期
AR_GROSS_O, AR_PROV_O = int(12.85 * YI), int(1.92 * YI)
AR_WRITEOFF_YTD = AR_PROV_O + PL_YTD["impair"]["信用减值损失"] - AR_PROV
CONTRACT_ASSET_IMPAIR_YTD = PL_YTD["impair"]["资产减值损失"]

# 折旧摊销（1-8月 / 8月）
DEP_AMORT_YTD = OrderedDict([
    ("固定资产折旧",        int(0.360 * YI)),
    ("使用权资产折旧",       int(0.340 * YI)),
    ("无形资产摊销",        int(0.200 * YI)),
    ("长期待摊费用摊销",     int(0.150 * YI)),
])
DEP_AMORT_M = OrderedDict((k, int(round(v / 8))) for k, v in DEP_AMORT_YTD.items())
INT_EXPENSE_YTD, INT_INCOME_YTD = int(0.090 * YI), int(0.243 * YI)

# ============================================================
# 9. 会计科目表
# ============================================================
# (代码, 名称, 类别, 余额方向)  类别: A资产 L负债 E权益 I收入 C成本费用
COA = [
    ("1001","库存现金","A","借"),("1002","银行存款","A","借"),
    ("1101","交易性金融资产","A","借"),("1122","应收账款","A","借"),
    ("1231","坏账准备","A","贷"),("1181","应收款项融资","A","借"),
    ("1123","预付账款","A","借"),("1221","其他应收款","A","借"),
    ("1232","合同资产","A","借"),("1233","合同资产减值准备","A","贷"),
    ("1405","库存商品及周转材料","A","借"),("1489","其他流动资产","A","借"),
    ("1511","长期股权投资","A","借"),("1524","其他非流动金融资产","A","借"),
    ("1601","固定资产","A","借"),("1602","累计折旧","A","贷"),
    ("1621","使用权资产","A","借"),("1622","使用权资产累计折旧","A","贷"),
    ("1701","无形资产","A","借"),("1702","累计摊销","A","贷"),
    ("1711","商誉","A","借"),("1801","长期待摊费用","A","借"),
    ("1811","递延所得税资产","A","借"),("1901","其他非流动资产","A","借"),
    ("2001","短期借款","L","贷"),("2202","应付账款","L","贷"),
    ("2211.01","应付职工薪酬——工资奖金及绩效","L","贷"),
    ("2211.02","应付职工薪酬——社会保险及住房公积金","L","贷"),
    ("2211.03","应付职工薪酬——职工福利及其他","L","贷"),
    ("2221.01","应交税费——应交增值税（销项税额）","L","贷"),
    ("2221.02","应交税费——应交增值税（进项税额）","L","借"),
    ("2221.03","应交税费——未交增值税","L","贷"),
    ("2221.04","应交税费——应交企业所得税","L","贷"),
    ("2221.05","应交税费——应交个人所得税","L","贷"),
    ("2221.06","应交税费——城建税及教育费附加","L","贷"),
    ("2221.07","应交税费——其他税费","L","贷"),
    ("2241","其他应付款","L","贷"),("2314","合同负债","L","贷"),
    ("2401","其他流动负债","L","贷"),("2431","一年内到期的非流动负债","L","贷"),
    ("2701","租赁负债","L","贷"),("2801","长期应付款","L","贷"),
    ("2811","预计负债","L","贷"),("2901","递延收益","L","贷"),
    ("2911","递延所得税负债","L","贷"),
    ("4001","实收资本","E","贷"),("4002","资本公积","E","贷"),
    ("4101","盈余公积","E","贷"),("4103","本年利润","E","贷"),
    ("4104","利润分配——未分配利润","E","贷"),("4201","少数股东权益","E","贷"),
    ("6001.01","主营业务收入——住宅物业管理服务","I","贷"),
    ("6001.02","主营业务收入——非住宅物业管理服务","I","贷"),
    ("6001.03","主营业务收入——案场协销及非业主增值服务","I","贷"),
    ("6051.01","其他业务收入——社区增值服务","I","贷"),
    ("6051.02","其他业务收入——多种经营（车位·广告·场地）","I","贷"),
    ("6051.03","其他业务收入——顾问咨询及物资销售","I","贷"),
    ("6101","公允价值变动损益","I","贷"),("6111","投资收益","I","贷"),
    ("6115","资产处置收益","I","贷"),("6117","其他收益","I","贷"),
    ("6301","营业外收入","I","贷"),
    ("6401.01","主营业务成本——职工薪酬","C","借"),
    ("6401.02","主营业务成本——分包及外包服务费","C","借"),
    ("6401.03","主营业务成本——能源费","C","借"),
    ("6401.04","主营业务成本——维修维护费","C","借"),
    ("6401.05","主营业务成本——物料及低值易耗品","C","借"),
    ("6401.06","主营业务成本——折旧与摊销","C","借"),
    ("6401.07","主营业务成本——办公及差旅费","C","借"),
    ("6401.08","主营业务成本——保险费及项目税费","C","借"),
    ("6401.09","主营业务成本——其他直接费用","C","借"),
    ("6402","其他业务成本","C","借"),("6403","税金及附加","C","借"),
    ("6601","销售费用","C","借"),("6602","管理费用","C","借"),
    ("6603","财务费用","C","借"),("6604","研发费用","C","借"),
    ("6701","资产减值损失","C","借"),("6702","信用减值损失","C","借"),
    ("6711","营业外支出","C","借"),("6801","所得税费用","C","借"),
]
COA_NAME = {c: n for c, n, _, _ in COA}
COA_CAT  = {c: k for c, _, k, _ in COA}
COA_DIR  = {c: d for c, _, _, d in COA}

# ============================================================
# 10. 8月末科目余额（由资产负债表映射）
# ============================================================
def yi(x): return int(round(x * YI))

CLOSE_BAL = {                            # 期末余额（正数=按科目余额方向）
    "1001": yi(0.0200), "1002": BSD_C["货币资金"] - yi(0.0200),
    "1101": BSD_C["交易性金融资产"],
    "1122": AR_GROSS, "1231": AR_PROV,
    "1181": BSD_C["应收款项融资"], "1123": BSD_C["预付款项"],
    "1221": BSD_C["其他应收款"],
    "1232": yi(1.0000), "1233": yi(0.1500),
    "1405": BSD_C["存货"], "1489": BSD_C["其他流动资产"],
    "1511": BSD_C["长期股权投资"], "1524": BSD_C["其他非流动金融资产"],
    "1601": yi(9.8500), "1602": yi(6.0000),
    "1621": yi(5.3500), "1622": yi(2.7000),
    "1701": yi(3.4500), "1702": yi(1.5000),
    "1711": BSD_C["商誉"], "1801": BSD_C["长期待摊费用"],
    "1811": BSD_C["递延所得税资产"], "1901": BSD_C["其他非流动资产"],
    "2001": BSD_C["短期借款"], "2202": BSD_C["应付账款"],
    "2211.01": yi(3.4200), "2211.02": yi(1.1500), "2211.03": yi(0.6300),
    "2221.01": 0, "2221.02": 0, "2221.03": yi(0.0980), "2221.04": yi(1.1520),
    "2221.05": yi(0.0350), "2221.06": yi(0.0480), "2221.07": yi(0.0170),
    "2241": BSD_C["其他应付款"], "2314": BSD_C["合同负债"],
    "2401": BSD_C["其他流动负债"], "2431": BSD_C["一年内到期的非流动负债"],
    "2701": BSD_C["租赁负债"], "2801": BSD_C["长期应付款"],
    "2811": BSD_C["预计负债"], "2901": BSD_C["递延收益"], "2911": BSD_C["递延所得税负债"],
    "4001": EQ_PAIDIN, "4002": EQ_CAPRES, "4101": EQ_SURPLUS,
    "4103": PL_YTD["net"], "4104": BS["ret_c"] - PL_YTD["parent"],
    "4201": MI_CLOSE - PL_YTD["minority"],
}

# ============================================================
# 11. 2026年8月 月结汇总分录
# ============================================================
CF = dict(  # 现金流量表项目标签
    S="销售商品、提供劳务收到的现金", TR="收到的税费返还", OI="收到其他与经营活动有关的现金",
    G="购买商品、接受劳务支付的现金", ST="支付给职工以及为职工支付的现金",
    TX="支付的各项税费", OO="支付其他与经营活动有关的现金",
    ID="收回投资收到的现金", IR="取得投资收益收到的现金",
    IF="处置固定资产、无形资产和其他长期资产收回的现金净额",
    OF="购建固定资产、无形资产和其他长期资产支付的现金",
    OV="投资支付的现金", OS="取得子公司及其他营业单位支付的现金净额",
    FL="取得借款收到的现金", FD="偿还债务支付的现金",
    FI="分配股利、利润或偿付利息支付的现金", FO="支付其他与筹资活动有关的现金",
)
P = PL_M
VAT_PM, VAT_VAS = 0.048, 0.060          # 物业费综合销项税率 / 增值服务销项税率
AR_SHARE_PM, AR_SHARE_VAS = 0.45, 0.40  # 形成应收的比例

rev_res, rev_nonres = P["rev_main_lines"]["住宅物业管理服务"], P["rev_main_lines"]["非住宅物业管理服务"]
rev_dev = P["rev_main_lines"]["案场协销及非业主增值服务"]
rev_o1 = P["rev_other_lines"]["社区增值服务"]
rev_o2 = P["rev_other_lines"]["多种经营（车位·广告·场地）"]
rev_o3 = P["rev_other_lines"]["顾问咨询及物资销售"]

# 营业成本分组（本月）
OTHER_COGS_MIX = OrderedDict([
    ("职工薪酬",0.320),("分包及外包服务费",0.200),("物料及低值易耗品",0.150),
    ("能源费",0.045),("维修维护费",0.035),("折旧与摊销",0.040),
    ("办公及差旅费",0.035),("保险费及项目税费",0.015),("其他直接费用",0.160),
])
GRP_MAP = OrderedDict([
    ("职工薪酬", ["职工薪酬——工资及奖金","职工薪酬——社会保险及公积金","职工薪酬——职工福利费",
                "职工薪酬——工会及教育经费","职工薪酬——劳务派遣费"]),
    ("分包及外包服务费", ["分包及外包服务费"]), ("能源费", ["能源费（水/电/气/暖）"]),
    ("维修维护费", ["维修维护费"]), ("物料及低值易耗品", ["物料及低值易耗品"]),
    ("折旧与摊销", ["折旧与摊销"]), ("办公及差旅费", ["办公及差旅费"]),
    ("保险费及项目税费", ["保险费及项目税费"]), ("其他直接费用", ["其他项目直接费用"]),
])
def cogs_groups(pl):
    tot = OrderedDict((g, sum(pl["cogs_lines"][k] for k in ks)) for g, ks in GRP_MAP.items())
    oth, acc = OrderedDict(), 0
    gk = list(OTHER_COGS_MIX)
    for i, g in enumerate(gk):
        v = (pl["cogs_other"] - acc) if i == len(gk) - 1 else int(round(pl["cogs_other"] * OTHER_COGS_MIX[g]))
        acc += v; oth[g] = v
    main = OrderedDict((g, tot[g] - oth[g]) for g in tot)
    return tot, main, oth
CG_TOT_M, CG_MAIN_M, CG_OTH_M = cogs_groups(PL_M)
CG_TOT_Y, CG_MAIN_Y, CG_OTH_Y = cogs_groups(PL_YTD)
CG_TOT_FY, CG_MAIN_FY, CG_OTH_FY = cogs_groups(PL_FY)

# 期间费用人工占比
OPEX_LABOR = {"管理费用": 0.62, "销售费用": 0.55, "研发费用": 0.78}
mgmt, sell, rd = P["opex"]["管理费用"], P["opex"]["销售费用"], P["opex"]["研发费用"]
lab_mgmt = int(round(mgmt * OPEX_LABOR["管理费用"]))
lab_sell = int(round(sell * OPEX_LABOR["销售费用"]))
lab_rd   = int(round(rd * OPEX_LABOR["研发费用"]))
dep_m = DEP_AMORT_M
dep_cost_m = CG_TOT_M["折旧与摊销"]
dep_opex_m = sum(dep_m.values()) - dep_cost_m          # 计入管理费用的折旧摊销
staff_total_m = CG_TOT_M["职工薪酬"] + lab_mgmt + lab_sell + lab_rd
sal_wage = int(round(staff_total_m * 0.733))
sal_ins  = int(round(staff_total_m * 0.179))
sal_wel  = staff_total_m - sal_wage - sal_ins

JE = []   # 每笔: dict(no, summary, lines=[(code, debit, credit, cf)])
def je(no, summary, lines):
    dr = sum(l[1] for l in lines); cr = sum(l[2] for l in lines)
    assert dr == cr, f"{no} 借贷不平 {dr} vs {cr}"
    JE.append(dict(no=f"记-{PERIOD_M:02d}-{len(JE)+1:03d}", summary=summary, lines=lines))

# —— 收入循环 ——
pm_incl = int(round((rev_res + rev_nonres) * (1 + VAT_PM)))
pm_vat = pm_incl - rev_res - rev_nonres
pm_ar = int(round(pm_incl * AR_SHARE_PM)); pm_cl = pm_incl - pm_ar
je("PZ-08-001", "计提本月住宅及非住宅物业管理服务收入（权责发生制），预收部分自合同负债结转", [
    ("1122", pm_ar, 0, None), ("2314", pm_cl, 0, None),
    ("6001.01", 0, rev_res, None), ("6001.02", 0, rev_nonres, None),
    ("2221.01", 0, pm_vat, None)])
dev_incl = int(round(rev_dev * (1 + VAT_VAS))); dev_vat = dev_incl - rev_dev
je("PZ-08-002", "确认本月案场协销及非业主增值服务收入", [
    ("1122", dev_incl, 0, None), ("6001.03", 0, rev_dev, None), ("2221.01", 0, dev_vat, None)])
vas = rev_o1 + rev_o2 + rev_o3
vas_incl = int(round(vas * (1 + VAT_VAS))); vas_vat = vas_incl - vas
vas_ar = int(round(vas_incl * AR_SHARE_VAS)); vas_cash = vas_incl - vas_ar
je("PZ-08-003", "确认本月社区增值服务、多种经营及顾问咨询收入", [
    ("1002", vas_cash, 0, CF["S"]), ("1122", vas_ar, 0, None),
    ("6051.01", 0, rev_o1, None), ("6051.02", 0, rev_o2, None), ("6051.03", 0, rev_o3, None),
    ("2221.01", 0, vas_vat, None)])
COLL_AR_M, PREPAY_M = yi(1.9800), yi(1.9500)
je("PZ-08-004", "收取业主物业服务费：清收往期欠费及收取下期预收款", [
    ("1002", COLL_AR_M + PREPAY_M, 0, CF["S"]),
    ("1122", 0, COLL_AR_M, None), ("2314", 0, PREPAY_M, None)])

# —— 人工与成本循环 ——
je("PZ-08-005", "计提本月项目一线及区域人员职工薪酬（计入营业成本）", [
    ("6401.01", CG_MAIN_M["职工薪酬"], 0, None), ("6402", CG_OTH_M["职工薪酬"], 0, None),
    ("2211.01", 0, int(round(CG_TOT_M["职工薪酬"]*0.733)), None),
    ("2211.02", 0, int(round(CG_TOT_M["职工薪酬"]*0.179)), None),
    ("2211.03", 0, CG_TOT_M["职工薪酬"] - int(round(CG_TOT_M["职工薪酬"]*0.733))
                   - int(round(CG_TOT_M["职工薪酬"]*0.179)), None)])
lab_opex = lab_mgmt + lab_sell + lab_rd
je("PZ-08-006", "计提本月管理、销售及研发人员职工薪酬（计入期间费用）", [
    ("6602", lab_mgmt, 0, None), ("6601", lab_sell, 0, None), ("6604", lab_rd, 0, None),
    ("2211.01", 0, int(round(lab_opex*0.733)), None),
    ("2211.02", 0, int(round(lab_opex*0.179)), None),
    ("2211.03", 0, lab_opex - int(round(lab_opex*0.733)) - int(round(lab_opex*0.179)), None)])
PAY_WAGE = yi(1.5800); PIT_W = yi(0.0350); SI_PERSONAL = yi(0.1800)
je("PZ-08-007", "发放上月工资、绩效及津贴，代扣个人所得税与社保公积金个人部分", [
    ("2211.01", PAY_WAGE, 0, None), ("1002", 0, PAY_WAGE - PIT_W - SI_PERSONAL, CF["ST"]),
    ("2221.05", 0, PIT_W, None), ("2241", 0, SI_PERSONAL, None)])
SI_CORP, SI_PAY_PERSONAL, PIT_PAY, WELFARE_PAY = yi(0.3720), yi(0.1780), yi(0.0340), yi(0.1750)
je("PZ-08-008", "缴纳社会保险费及住房公积金（企业部分与代扣个人部分）", [
    ("2211.02", SI_CORP, 0, None), ("2241", SI_PAY_PERSONAL, 0, None),
    ("1002", 0, SI_CORP + SI_PAY_PERSONAL, CF["ST"])])
je("PZ-08-009", "支付职工福利费、劳保用品及高温津贴", [
    ("2211.03", WELFARE_PAY, 0, None), ("1002", 0, WELFARE_PAY, CF["ST"])])
sub = CG_TOT_M["分包及外包服务费"]; sub_vat = int(round(sub * 0.06))
je("PZ-08-010", "计提本月保洁、秩序维护、绿化及电梯维保等分包外包服务费", [
    ("6401.02", CG_MAIN_M["分包及外包服务费"], 0, None), ("6402", CG_OTH_M["分包及外包服务费"], 0, None),
    ("2221.02", sub_vat, 0, None), ("2202", 0, sub + sub_vat, None)])
ene, rep, mat = CG_TOT_M["能源费"], CG_TOT_M["维修维护费"], CG_TOT_M["物料及低值易耗品"]
emr_vat = int(round((ene + rep + mat) * 0.096))
je("PZ-08-011", "计提本月公共区域能源费、设施设备维修维护费及物料消耗", [
    ("6401.03", CG_MAIN_M["能源费"], 0, None), ("6401.04", CG_MAIN_M["维修维护费"], 0, None),
    ("6401.05", CG_MAIN_M["物料及低值易耗品"], 0, None),
    ("6402", CG_OTH_M["能源费"]+CG_OTH_M["维修维护费"]+CG_OTH_M["物料及低值易耗品"], 0, None),
    ("2221.02", emr_vat, 0, None), ("2202", 0, ene+rep+mat+emr_vat, None)])
oth_d = CG_TOT_M["办公及差旅费"] + CG_TOT_M["保险费及项目税费"] + CG_TOT_M["其他直接费用"]
oth_vat = int(round(oth_d * 0.040))
je("PZ-08-012", "计提本月项目办公差旅费、保险费及其他直接费用", [
    ("6401.07", CG_MAIN_M["办公及差旅费"], 0, None), ("6401.08", CG_MAIN_M["保险费及项目税费"], 0, None),
    ("6401.09", CG_MAIN_M["其他直接费用"], 0, None),
    ("6402", CG_OTH_M["办公及差旅费"]+CG_OTH_M["保险费及项目税费"]+CG_OTH_M["其他直接费用"], 0, None),
    ("2221.02", oth_vat, 0, None), ("2202", 0, oth_d + oth_vat, None)])
nm_mgmt = mgmt - lab_mgmt - dep_opex_m; nm_sell = sell - lab_sell; nm_rd = rd - lab_rd
nm_vat = int(round((nm_mgmt + nm_sell + nm_rd) * 0.050))
je("PZ-08-013", "计提本月总部及区域管理、销售、研发费用（非人工部分）", [
    ("6602", nm_mgmt, 0, None), ("6601", nm_sell, 0, None), ("6604", nm_rd, 0, None),
    ("2221.02", nm_vat, 0, None), ("2202", 0, nm_mgmt+nm_sell+nm_rd+nm_vat, None)])
PAY_AP = yi(1.6200)
je("PZ-08-014", "按合同账期支付外包服务商、能源及物料供应商款项", [
    ("2202", PAY_AP, 0, None), ("1002", 0, PAY_AP, CF["G"])])
je("PZ-08-015", "计提本月固定资产折旧、使用权资产折旧及无形资产、长期待摊费用摊销", [
    ("6401.06", dep_cost_m, 0, None), ("6602", dep_opex_m, 0, None),
    ("1602", 0, dep_m["固定资产折旧"], None), ("1622", 0, dep_m["使用权资产折旧"], None),
    ("1702", 0, dep_m["无形资产摊销"], None), ("1801", 0, dep_m["长期待摊费用摊销"], None)])
LEASE_INT, LEASE_PAY = yi(0.0060), yi(0.0750)
je("PZ-08-016", "计提租赁负债利息并支付项目用房及办公场地租金", [
    ("6603", LEASE_INT, 0, None), ("2701", 0, LEASE_INT, None)])
je("PZ-08-017", "支付租赁付款额（使用权资产对应租金）", [
    ("2701", LEASE_PAY, 0, None), ("1002", 0, LEASE_PAY, CF["FO"])])

# —— 减值与税金 ——
je("PZ-08-018", "按预期信用损失模型计提应收账款坏账准备", [
    ("6702", P["impair"]["信用减值损失"], 0, None), ("1231", 0, P["impair"]["信用减值损失"], None)])
WRITEOFF_M = yi(0.0850)
je("PZ-08-019", "经审批核销确认无法收回的往期物业服务费应收款", [
    ("1231", WRITEOFF_M, 0, None), ("1122", 0, WRITEOFF_M, None)])
je("PZ-08-020", "计提合同资产减值准备（案场服务未结算部分）", [
    ("6701", P["impair"]["资产减值损失"], 0, None), ("1233", 0, P["impair"]["资产减值损失"], None)])
sur = P["opex"]["税金及附加"]; sur_a = int(round(sur * 0.69))
je("PZ-08-021", "计提本月城市维护建设税、教育费附加、房产税及印花税", [
    ("6403", sur, 0, None), ("2221.06", 0, sur_a, None), ("2221.07", 0, sur - sur_a, None)])
out_vat = pm_vat + dev_vat + vas_vat
in_vat = sub_vat + emr_vat + oth_vat + nm_vat + yi(0.0098)   # 末项为资本性支出进项
je("PZ-08-022", "月末结转本月应交增值税（销项税额抵减进项税额）", [
    ("2221.01", out_vat, 0, None), ("2221.02", 0, in_vat, None),
    ("2221.03", 0, out_vat - in_vat, None)])
VAT_PAY, SUR_PAY, CIT_PAY = yi(0.0950), yi(0.0120), yi(0.0200)
je("PZ-08-023", "缴纳上月增值税、附加税费及个人所得税", [
    ("2221.03", VAT_PAY, 0, None), ("2221.06", SUR_PAY, 0, None), ("2221.05", PIT_PAY, 0, None),
    ("1002", 0, VAT_PAY + SUR_PAY + PIT_PAY, CF["TX"])])
je("PZ-08-024", "缴纳子公司企业所得税", [
    ("2221.04", CIT_PAY, 0, None), ("1002", 0, CIT_PAY, CF["TX"])])
je("PZ-08-025", "收到财政补贴、稳岗返还及增值税进项加计抵减", [
    ("1002", P["other_inc"]["其他收益"], 0, CF["TR"]),
    ("6117", 0, P["other_inc"]["其他收益"], None)])

# —— 投融资 ——
REDEEM, BUY_WM = yi(1.2000), yi(1.3500)
je("PZ-08-026", "赎回到期结构性存款及现金管理产品", [
    ("1002", REDEEM, 0, CF["ID"]), ("1101", 0, REDEEM, None)])
je("PZ-08-027", "收到现金管理产品投资收益", [
    ("1002", P["other_inc"]["投资收益"], 0, CF["IR"]), ("6111", 0, P["other_inc"]["投资收益"], None)])
je("PZ-08-028", "以闲置资金购买保本型现金管理产品", [
    ("1101", BUY_WM, 0, None), ("1002", 0, BUY_WM, CF["OV"])])
je("PZ-08-029", "确认交易性金融资产公允价值变动", [
    ("1101", P["other_inc"]["公允价值变动收益"], 0, None),
    ("6101", 0, P["other_inc"]["公允价值变动收益"], None)])
INT_INC_M = int(round(INT_INCOME_YTD / 8))
je("PZ-08-030", "结转银行存款利息收入", [
    ("1002", INT_INC_M, 0, CF["OI"]), ("6603", 0, INT_INC_M, None)])
LOAN_INT = yi(0.0053); BANK_FEE = P["opex"]["财务费用"] + INT_INC_M - LEASE_INT - LOAN_INT
je("PZ-08-031", "计提短期借款利息并支付银行手续费", [
    ("6603", LOAN_INT + BANK_FEE, 0, None), ("2241", 0, LOAN_INT, None),
    ("1002", 0, BANK_FEE, CF["OO"])])
UTIL_ACCRUE, UTIL_RECV, UTIL_PAY = yi(1.8500), yi(1.7200), yi(1.6800)
je("PZ-08-032", "计提代业主收取及代付的水电气热费用（夏季用能高峰）", [
    ("1221", UTIL_ACCRUE, 0, None), ("2241", 0, UTIL_ACCRUE, None)])
je("PZ-08-033", "收取业主代收水电费", [
    ("1002", UTIL_RECV, 0, CF["OI"]), ("1221", 0, UTIL_RECV, None)])
je("PZ-08-034", "向供电、供水、供热单位划付代收费用", [
    ("2241", UTIL_PAY, 0, None), ("1002", 0, UTIL_PAY, CF["OO"])])
DEP_IN, DEP_OUT = yi(0.1200), yi(0.0800)
je("PZ-08-035", "收取业主装修保证金、门禁卡押金及公共资源经营保证金", [
    ("1002", DEP_IN, 0, CF["OI"]), ("2241", 0, DEP_IN, None)])
je("PZ-08-036", "退还到期装修保证金及押金", [
    ("2241", DEP_OUT, 0, None), ("1002", 0, DEP_OUT, CF["OO"])])
FA_BUY, IA_BUY, LTD_ADD = yi(0.0750), yi(0.0125), yi(0.0450)
je("PZ-08-037", "购置项目设施设备、智慧物业系统及支付项目前期投入", [
    ("1601", FA_BUY, 0, None), ("1701", IA_BUY, 0, None), ("1801", LTD_ADD, 0, None),
    ("2221.02", yi(0.0098), 0, None),
    ("1002", 0, FA_BUY + IA_BUY + LTD_ADD, CF["OF"]),
    ("1002", 0, yi(0.0098), CF["G"])])
FA_COST, FA_DEP = yi(0.0350), yi(0.0280)
FA_CASH = FA_COST - FA_DEP + P["other_inc"]["资产处置收益"]
je("PZ-08-038", "处置报废项目设备及车辆", [
    ("1002", FA_CASH, 0, CF["IF"]), ("1602", FA_DEP, 0, None),
    ("1601", 0, FA_COST, None), ("6115", 0, P["other_inc"]["资产处置收益"], None)])
GW_ADD = yi(0.0500)
je("PZ-08-039", "支付收购城市公司股权对价（确认合并商誉）", [
    ("1711", GW_ADD, 0, None), ("1002", 0, GW_ADD, CF["OS"])])
REPAY = yi(0.1000)
je("PZ-08-040", "偿还到期短期流动资金借款", [
    ("2001", REPAY, 0, None), ("1002", 0, REPAY, CF["FD"])])
je("PZ-08-041", "支付短期借款利息", [
    ("2241", LOAN_INT, 0, None), ("1002", 0, LOAN_INT, CF["FI"])])
NONOP_IN, NONOP_OUT = P["nonop"]["营业外收入"], P["nonop"]["营业外支出"]
je("PZ-08-042", "确认营业外收入（违约赔偿及无法支付款项转销）", [
    ("1002", NONOP_IN, 0, CF["OI"]), ("6301", 0, NONOP_IN, None)])
je("PZ-08-043", "确认营业外支出（非流动资产报废损失及对外捐赠）", [
    ("6711", NONOP_OUT, 0, None), ("1002", 0, NONOP_OUT, CF["OO"])])
PRE_ADD, INV_ADD, OCA_ADD = yi(0.1200), yi(0.0300), yi(0.0500)
je("PZ-08-043", "支付预付保险费、采购周转物料及其他流动资产变动", [
    ("1123", PRE_ADD, 0, None), ("1405", INV_ADD, 0, None), ("1489", OCA_ADD, 0, None),
    ("1002", 0, PRE_ADD + INV_ADD + OCA_ADD, CF["OO"])])
LTI_ADD, ONF_ADD, ONC_ADD = yi(0.0200), yi(0.0100), yi(0.0400)
je("PZ-08-044", "增持联营企业股权及支付其他长期资产款项", [
    ("1511", LTI_ADD, 0, None), ("1524", ONF_ADD, 0, None), ("1901", ONC_ADD, 0, None),
    ("1002", 0, LTI_ADD + ONF_ADD + ONC_ADD, CF["OV"])])
OCL_ADD, PRV_ADD, DFI_ADD = yi(0.0500), yi(0.0200), yi(0.0200)
je("PZ-08-045", "收到待转销项税额、计提预计负债及递延收益（政府专项补助）", [
    ("1002", OCL_ADD + PRV_ADD + DFI_ADD, 0, CF["OI"]),
    ("2401", 0, OCL_ADD, None), ("2811", 0, PRV_ADD, None), ("2901", 0, DFI_ADD, None)])
DTA_ADD, DTL_ADD = int(round(yi(0.2200)/8)), int(round(yi(0.0700)/8))
cit_cur = P["tax"] + DTA_ADD - DTL_ADD
je("PZ-08-046", "计提本月企业所得税费用及递延所得税", [
    ("6801", cit_cur, 0, None), ("2221.04", 0, cit_cur, None)])
je("PZ-08-047", "确认递延所得税资产及递延所得税负债变动", [
    ("1811", DTA_ADD, 0, None), ("6801", DTL_ADD, 0, None),
    ("6801", 0, DTA_ADD, None), ("2911", 0, DTL_ADD, None)])

# —— 月末结转损益 ——
_pre = defaultdict(lambda: [0, 0])
for e in JE:
    for c, dr, cr, _ in e["lines"]:
        _pre[c][0] += dr; _pre[c][1] += cr
inc_lines, cost_lines, inc_tot, cost_tot = [], [], 0, 0
for c, _n, cat, _d in COA:
    if cat == "I":
        v = _pre[c][1] - _pre[c][0]
        if v: inc_lines.append((c, v, 0, None)); inc_tot += v
    elif cat == "C":
        v = _pre[c][0] - _pre[c][1]
        if v: cost_lines.append((c, 0, v, None)); cost_tot += v
je("PZ-08-048", "月末结转本月收入类科目至本年利润",
   inc_lines + [("4103", 0, inc_tot, None)])
je("PZ-08-049", "月末结转本月成本、费用及税金类科目至本年利润",
   [("4103", cost_tot, 0, None)] + cost_lines)
assert inc_tot - cost_tot == PL_M["net"], (inc_tot - cost_tot, PL_M["net"])

# ============================================================
# 12. 科目余额表（试算平衡表）
# ============================================================
def build_tb():
    mv = defaultdict(lambda: [0, 0])
    for e in JE:
        for c, dr, cr, _ in e["lines"]:
            mv[c][0] += dr; mv[c][1] += cr
    rows = []
    for code, name, cat, dirn in COA:
        dr, cr = mv[code]
        close = CLOSE_BAL.get(code, 0)          # 按余额方向的正数
        sign = 1 if dirn == "借" else -1
        # 期初(方向口径) = 期末 - sign*(借-贷)
        open_ = close - sign * (dr - cr)
        rows.append(dict(code=code, name=name, cat=cat, dirn=dirn,
                         open=open_, dr=dr, cr=cr, close=close))
    return rows
TB = build_tb()

def tb_sum(rows, key):
    dr = sum(r[key] for r in rows if r["dirn"] == "借")
    cr = sum(r[key] for r in rows if r["dirn"] == "贷")
    return dr, cr

# ============================================================
# 13. 现金流量表
# ============================================================
TBD_O = {r["code"]: r["open"] for r in TB}
TBD_C = {r["code"]: r["close"] for r in TB}
# 年初科目口径（1-8月累计用）
YB = dict(TBD_C)
YB.update({
    "1122": AR_GROSS_O, "1231": AR_PROV_O,
    "1181": BSD_O["应收款项融资"], "1123": BSD_O["预付款项"], "1221": BSD_O["其他应收款"],
    "1232": yi(0.7660), "1233": yi(0.0460), "1405": BSD_O["存货"], "1489": BSD_O["其他流动资产"],
    "1811": BSD_O["递延所得税资产"], "2911": BSD_O["递延所得税负债"],
    "2202": BSD_O["应付账款"], "2314": BSD_O["合同负债"], "2241": BSD_O["其他应付款"],
    "2401": BSD_O["其他流动负债"], "2811": BSD_O["预计负债"], "2901": BSD_O["递延收益"],
    "2211.01": int(BSD_O["应付职工薪酬"]*0.658), "2211.02": int(BSD_O["应付职工薪酬"]*0.221),
    "2211.03": BSD_O["应付职工薪酬"] - int(BSD_O["应付职工薪酬"]*0.658) - int(BSD_O["应付职工薪酬"]*0.221),
    "2221.03": yi(0.1120), "2221.04": yi(1.4020), "2221.05": yi(0.0330),
    "2221.06": yi(0.0530), "2221.07": yi(0.0200),
})

# 经营性应收按原值口径（与"加回减值损失"配套），并剔除不涉及现金的坏账核销
OP_RECV = ["1122","1123","1221","1181","1232"]
OP_PAY  = ["2202","2314","2211.01","2211.02","2211.03","2221.03","2221.04",
           "2221.05","2221.06","2221.07","2241","2401","2811","2901"]

def cf_indirect(pl, ob, cb, dep, int_exp, writeoff):
    def dd(c): return cb[c] - ob[c]
    rows = [
        ("净利润", pl["net"]),
        ("加：信用减值损失", pl["impair"]["信用减值损失"]),
        ("    资产减值损失", pl["impair"]["资产减值损失"]),
        ("    固定资产折旧", dep["固定资产折旧"]),
        ("    使用权资产折旧", dep["使用权资产折旧"]),
        ("    无形资产摊销", dep["无形资产摊销"]),
        ("    长期待摊费用摊销", dep["长期待摊费用摊销"]),
        ("    处置固定资产、无形资产的损失（收益以“－”号填列）", -pl["other_inc"]["资产处置收益"]),
        ("    公允价值变动损失（收益以“－”号填列）", -pl["other_inc"]["公允价值变动收益"]),
        ("    财务费用（利息支出）", int_exp),
        ("    投资损失（收益以“－”号填列）", -pl["other_inc"]["投资收益"]),
        ("    递延所得税资产减少（增加以“－”号填列）", -dd("1811")),
        ("    递延所得税负债增加（减少以“－”号填列）", dd("2911")),
        ("    存货的减少（增加以“－”号填列）", -dd("1405")),
        ("    经营性应收项目的减少（增加以“－”号填列）", -(sum(dd(c) for c in OP_RECV) + writeoff)),
        ("    经营性应付项目的增加（减少以“－”号填列）", sum(dd(c) for c in OP_PAY)),
        ("    其他经营性资产的减少（增加以“－”号填列）", -dd("1489")),
    ]
    return rows, sum(v for _, v in rows)

INT_EXP_M = LOAN_INT + LEASE_INT
CFI_M_ROWS,  CFI_M_NET  = cf_indirect(PL_M,   TBD_O, TBD_C, DEP_AMORT_M,   INT_EXP_M, WRITEOFF_M)
CFI_YTD_ROWS, CFI_YTD_NET = cf_indirect(PL_YTD, YB,   TBD_C, DEP_AMORT_YTD, INT_EXPENSE_YTD, AR_WRITEOFF_YTD)

# —— 8月直接法：由分录 CF 标签汇总 ——
def cf_direct_month():
    agg = defaultdict(int)
    for e in JE:
        for c, dr, cr, tag in e["lines"]:
            if tag:
                agg[tag] += dr - cr
    return agg
CFD_M = cf_direct_month()

CF_OP_IN  = [CF["S"], CF["TR"], CF["OI"]]
CF_OP_OUT = [CF["G"], CF["ST"], CF["TX"], CF["OO"]]
CF_IN_IN  = [CF["ID"], CF["IR"], CF["IF"]]
CF_IN_OUT = [CF["OF"], CF["OV"], CF["OS"]]
CF_FI_IN  = [CF["FL"]]
CF_FI_OUT = [CF["FD"], CF["FI"], CF["FO"]]

def _m(tag): return abs(CFD_M.get(tag, 0))
CFD_M_OP_NET = sum(_m(t) for t in CF_OP_IN) - sum(_m(t) for t in CF_OP_OUT)
assert abs(CFD_M_OP_NET - CFI_M_NET) < 5, (CFD_M_OP_NET, CFI_M_NET)

# —— 1-8月直接法 ——
incl_rev_ytd = (int(round((PL_YTD["rev_main_lines"]["住宅物业管理服务"]
                + PL_YTD["rev_main_lines"]["非住宅物业管理服务"]) * (1 + VAT_PM)))
              + int(round(PL_YTD["rev_main_lines"]["案场协销及非业主增值服务"] * (1 + VAT_VAS)))
              + int(round(PL_YTD["rev_other"] * (1 + VAT_VAS))))
CFD_Y = OrderedDict()
CFD_Y[CF["S"]]  = incl_rev_ytd - (TBD_C["1122"] - YB["1122"]) - AR_WRITEOFF_YTD + (TBD_C["2314"] - YB["2314"])
CFD_Y[CF["TR"]] = PL_YTD["other_inc"]["其他收益"]
CFD_Y[CF["OI"]] = yi(14.8500)          # 代收水电回款、押金保证金、利息收入、往来款
cash_cogs = int(round(sum(CG_TOT_Y[g] for g in ["分包及外包服务费","能源费","维修维护费",
                          "物料及低值易耗品","办公及差旅费","保险费及项目税费","其他直接费用"]) * 1.075))
CFD_Y[CF["G"]]  = cash_cogs - (TBD_C["2202"] - YB["2202"]) + yi(0.3200)
staff_ytd = CG_TOT_Y["职工薪酬"] + int(round(sum(PL_YTD["opex"][k] * OPEX_LABOR[k]
                                               for k in OPEX_LABOR)))
CFD_Y[CF["ST"]] = staff_ytd - (TBD_C["2211.01"]+TBD_C["2211.02"]+TBD_C["2211.03"]
                               - YB["2211.01"]-YB["2211.02"]-YB["2211.03"])
tax_codes = ["2221.03","2221.04","2221.05","2221.06","2221.07"]
CFD_Y[CF["TX"]] = (PL_YTD["tax"] + PL_YTD["opex"]["税金及附加"] + yi(2.0400)
                   - sum(TBD_C[c] - YB[c] for c in tax_codes))
CFD_Y[CF["OO"]] = (sum(CFD_Y[t] for t in CF_OP_IN)
                   - CFD_Y[CF["G"]] - CFD_Y[CF["ST"]] - CFD_Y[CF["TX"]] - CFI_YTD_NET)

CFD_Y[CF["ID"]] = yi(9.6500); CFD_Y[CF["IR"]] = PL_YTD["other_inc"]["投资收益"]
CFD_Y[CF["IF"]] = yi(0.0620)
CFD_Y[CF["OF"]] = yi(1.0900); CFD_Y[CF["OS"]] = yi(0.3600)
CFD_Y[CF["FL"]] = yi(1.5000); CFD_Y[CF["FD"]] = yi(0.8500)
CFD_Y[CF["FI"]] = DIV_PARENT_YTD + DIV_MINOR_YTD + INT_EXPENSE_YTD - yi(0.0400)
CFD_Y[CF["FO"]] = yi(0.6200)
CF_NET_TOTAL_Y = BS["cash_c"] - BS["cash_o"]
CF_FIN_NET_Y = sum(CFD_Y[t] for t in CF_FI_IN) - sum(CFD_Y[t] for t in CF_FI_OUT)
CFD_Y[CF["OV"]] = (sum(CFD_Y[t] for t in CF_IN_IN) - CFD_Y[CF["OF"]] - CFD_Y[CF["OS"]]
                   - (CF_NET_TOTAL_Y - CFI_YTD_NET - CF_FIN_NET_Y))
CF_INV_NET_Y = sum(CFD_Y[t] for t in CF_IN_IN) - sum(CFD_Y[t] for t in CF_IN_OUT)
assert abs(CFI_YTD_NET + CF_INV_NET_Y + CF_FIN_NET_Y - CF_NET_TOTAL_Y) < 5

# ============================================================
# 14. 分析层
# ============================================================
DAYS_YTD = 243          # 1-8月天数
BASE_FEE_REV_YTD = (PL_YTD["rev_main_lines"]["住宅物业管理服务"]
                    + PL_YTD["rev_main_lines"]["非住宅物业管理服务"])
BASE_FEE_REV_FY  = (PL_FY["rev_main_lines"]["住宅物业管理服务"]
                    + PL_FY["rev_main_lines"]["非住宅物业管理服务"])
UNIT_FEE_YTD = BASE_FEE_REV_YTD / AREA_TOTAL / PERIOD_M          # 元/㎡/月
AR_TURN_DAYS = AR_GROSS / PL_FY["rev_total"] * 365
AR_TURN_DAYS_YTD = ((AR_GROSS + AR_GROSS_O) / 2) / PL_YTD["rev_total"] * DAYS_YTD
AP_CREDIT_COST_YTD = sum(CG_TOT_Y[g] for g in ["分包及外包服务费","能源费","维修维护费",
                         "物料及低值易耗品","办公及差旅费","保险费及项目税费","其他直接费用"])
AP_TURN_DAYS = ((AP_TOTAL + BSD_O["应付账款"]) / 2) / AP_CREDIT_COST_YTD * DAYS_YTD

def ap_supplier_rows():
    """供应商类别：采购额 → 按实际结算天数推算期末应付，归一化至应付账款总额"""
    purch_tot = AP_CREDIT_COST_YTD * 1.075
    raw = [(k, purch_tot * s, ct, ad) for k, (s, ct, ad) in AP_SUPPLIER.items()]
    scale = AP_TOTAL / sum(p * ad / DAYS_YTD for _, p, _, ad in raw)
    out, acc = [], 0
    for i, (k, p, ct, ad) in enumerate(raw):
        amt = (AP_TOTAL - acc) if i == len(raw)-1 else int(round(p * ad / DAYS_YTD * scale))
        acc += amt
        out.append(dict(cat=k, amt=amt, purch=int(round(p)), term=ct,
                        actual=amt / p * DAYS_YTD))
    return out
AP_SUP_ROWS = ap_supplier_rows()
AP_TURN_DAYS_EOP = AP_TOTAL / (AP_CREDIT_COST_YTD * 1.075) * DAYS_YTD
AP_CREDIT_RATIO = AP_CREDIT_COST_YTD / PL_YTD["cogs_total"]      # 可赊购成本占营业成本比重

def ap_region_rows():
    """分区域应付：按各区域成本 × 付款节奏系数分配"""
    base = {r: REGPL_YTD[r]["cogs"] * AP_REGION_LAG[r] for r in REGIONS}
    tot = sum(base.values()); out, acc = [], 0
    ks = list(REGIONS)
    for i, r in enumerate(ks):
        v = (AP_TOTAL - acc) if i == len(ks)-1 else int(round(AP_TOTAL * base[r] / tot))
        acc += v
        purch = REGPL_YTD[r]["cogs"] * AP_CREDIT_RATIO * 1.075
        out.append(dict(region=r, amt=v, cogs=REGPL_YTD[r]["cogs"], purch=int(round(purch)),
                        days=v / purch * DAYS_YTD))
    return out
AP_REG_ROWS = ap_region_rows()

LABOR_NARROW_Y = CG_TOT_FY["职工薪酬"]
LABOR_OUTSOURCE_Y = int(round(CG_TOT_FY["分包及外包服务费"] * OUTSOURCE_LABOR_RATIO))
LABOR_BROAD_Y = LABOR_NARROW_Y + LABOR_OUTSOURCE_Y

# 业务板块（含内部毛利率差异）
SEGMENTS = OrderedDict([
    ("住宅物业管理服务",        dict(gm=0.1450, rev_key=("main","住宅物业管理服务"))),
    ("非住宅物业管理服务",       dict(gm=0.1880, rev_key=("main","非住宅物业管理服务"))),
    ("案场协销及非业主增值服务",   dict(gm=0.3050, rev_key=("main","案场协销及非业主增值服务"))),
    ("社区增值服务",           dict(gm=0.3350, rev_key=("other","社区增值服务"))),
    ("多种经营（车位·广告·场地）", dict(gm=0.3120, rev_key=("other","多种经营（车位·广告·场地）"))),
    ("顾问咨询及物资销售",       dict(gm=0.2800, rev_key=("other","顾问咨询及物资销售"))),
])
def segment_rows(pl):
    """住宅板块吸收轧差（规模最大、扭曲最小），其余板块按目标毛利率列示"""
    out, acc_c = [], 0
    for s in SEGMENTS:
        kind, k = SEGMENTS[s]["rev_key"]
        rev = pl["rev_main_lines"][k] if kind == "main" else pl["rev_other_lines"][k]
        cost = None if s == "住宅物业管理服务" else int(round(rev * (1 - SEGMENTS[s]["gm"])))
        if cost is not None: acc_c += cost
        out.append(dict(seg=s, rev=rev, cost=cost))
    for r in out:
        if r["cost"] is None: r["cost"] = pl["cogs_total"] - acc_c
        r["gross"] = r["rev"] - r["cost"]
    return out
SEG_YTD, SEG_FY = segment_rows(PL_YTD), segment_rows(PL_FY)

# AR 账龄 × 区域 矩阵（区域收缴质量越差，长账龄占比越高）
def ar_matrix():
    """账龄×区域矩阵：迭代比例拟合(IPF)，行合计=区域应收，列合计=集团账龄结构"""
    import math
    ages = list(AR_AGING)
    rnames = list(REGIONS)
    base = [AR_AGING[a][0] for a in ages]
    row_t = [AR_REGION[r] for r in rnames]
    col_t = [x["gross"] for x in AR_ROWS]
    M = [[row_t[i] * base[j] * math.exp((0.879 - REGIONS[r]["coll"]) * 8.0 * (j - 1.5))
          for j in range(len(ages))] for i, r in enumerate(rnames)]
    for _ in range(60):
        for i in range(len(rnames)):
            s = sum(M[i]) or 1
            M[i] = [v * row_t[i] / s for v in M[i]]
        for j in range(len(ages)):
            s = sum(M[i][j] for i in range(len(rnames))) or 1
            for i in range(len(rnames)): M[i][j] *= col_t[j] / s
    out, col_acc = [], [0]*len(ages)
    for i, r in enumerate(rnames):
        line, acc = [], 0
        for j in range(len(ages)):
            v = (row_t[i] - acc) if j == len(ages)-1 else int(round(M[i][j]))
            acc += v; line.append(v); col_acc[j] += v
        out.append((r, line))
    for j in range(len(ages)-1):        # 列尾差调入最大区域
        out[0][1][j] += col_t[j] - col_acc[j]
    out[0][1][-1] = row_t[0] - sum(out[0][1][:-1])
    return out
AR_MATRIX = ar_matrix()

# 欠费按账单年度
ARREARS_BY_YEAR = OrderedDict([
    (f"{PERIOD_Y}年账单", 0.470), (f"{PERIOD_Y-1}年账单", 0.238),
    (f"{PERIOD_Y-2}年账单", 0.132), (f"{PERIOD_Y-3}年账单", 0.078),
    (f"{PERIOD_Y-4}年账单", 0.045), (f"{PERIOD_Y-5}年及以前", 0.037),
])

def build_arrears_by_year():
    """账单年度拆分：余额按 ARREARS_BY_YEAR 切分，坏账合计必须等于账龄组合计提的 AR_PROV。

    账单年度和账龄段是两种拆法，账龄段的计提比例不能直接乘到账单年度余额上
    （那样合计是 3.378 亿，与总账 1231 的 2.2125 亿对不上）。这里以账龄段比例为
    相对权重，全额计提的最老年份保持 100%，其余年份按比例缩放到 AR_PROV，
    尾差归入最后一个非全额年份。
    """
    keys = list(ARREARS_BY_YEAR)
    bal, acc = [], 0
    for i, k in enumerate(keys):
        v = (AR_GROSS - acc) if i == len(keys) - 1 else int(round(AR_GROSS * ARREARS_BY_YEAR[k]))
        acc += v; bal.append(v)
    rates = [AR_ROWS[i]["rate"] for i in range(len(keys))]
    fixed = [i for i, r in enumerate(rates) if r >= 1]
    free = [i for i in range(len(keys)) if i not in fixed]
    fixed_prov = sum(bal[i] for i in fixed)
    weight = sum(bal[i] * rates[i] for i in free)
    k = (AR_PROV - fixed_prov) / weight
    if DEMO:  # F-01：原版算法，账龄段比例直接乘到账单年度余额
        prov = [int(round(bal[i] * rates[i])) for i in range(len(keys))]
    else:
        prov = [bal[i] if i in fixed else int(round(bal[i] * rates[i] * k)) for i in range(len(keys))]
        prov[free[-1]] += AR_PROV - sum(prov)
    rows = [dict(year=key, gross=bal[i], prov=prov[i], rate=prov[i] / bal[i], net=bal[i] - prov[i])
            for i, key in enumerate(keys)]
    assert sum(r["gross"] for r in rows) == AR_GROSS
    assert DEMO or sum(r["prov"] for r in rows) == AR_PROV, "账单年度坏账合计必须等于账龄组合坏账准备"
    assert all(0 <= r["prov"] <= r["gross"] for r in rows)
    assert all(rows[i]["rate"] <= rows[i + 1]["rate"] for i in range(len(rows) - 1)), "越老的账单计提比例不应更低"
    return rows
ARREARS_ROWS = build_arrears_by_year()

# 业态收缴率
_COLL_BY_TYPE_RAW = OrderedDict([
    ("住宅——高端及改善",   (0.9280, 0.312)), ("住宅——刚需及安置",   (0.8420, 0.372)),
    ("写字楼及商业",       (0.9050, 0.128)), ("产业园区及公建",     (0.9410, 0.106)),
    ("城市服务及市政",     (0.8760, 0.052)), ("其他业态",          (0.8180, 0.030)),
])
# 业态收缴率等比例缩放，使按收入占比加权后正好等于区域加权的本年账单收缴率 COLL_RATE_CY：
# 原始值加权是 88.84%，比区域段与台账的 87.92% 高，「对应欠费规模」六行合计因此比
# 加权合计少 2,615.55 万元。缩放保持各业态的相对高低。
_TYPE_K = COLL_RATE_CY / sum(rate * share for rate, share in _COLL_BY_TYPE_RAW.values())
COLL_BY_TYPE = OrderedDict((k, (rate * _TYPE_K, share)) for k, (rate, share) in _COLL_BY_TYPE_RAW.items())
assert abs(sum(share for _, share in COLL_BY_TYPE.values()) - 1) < 1e-12
assert abs(sum(rate * share for rate, share in COLL_BY_TYPE.values()) - COLL_RATE_CY) < 1e-12
HEADCOUNT_MIX = OrderedDict([
    ("秩序维护（安保）", 9_850), ("环境保洁", 8_420), ("工程设备维保", 4_360),
    ("客服及管家", 4_180), ("绿化养护", 1_640), ("项目及区域管理", 2_350),
    ("职能与共享中心", 1_200),
])
