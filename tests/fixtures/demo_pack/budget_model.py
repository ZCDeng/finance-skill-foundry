# -*- coding: utf-8 -*-
"""
华宸物业 2026年度全面预算 + 合同台账 —— 数据模型层
口径体系：BUD（年初批复预算）→ LE（8月底滚动预测）→ ACT（1-8月实际）
LE 即月结套表「04·合并利润表」的「全年预算」列，两个工作簿在此对齐。
"""
import calendar
import random
from collections import OrderedDict, defaultdict
from model import *          # 复用月结套表的全部模型
from model import _norm

# ============================================================
# 0. 预算编制依据（调研所得）
# ============================================================
BUD_BENCHMARK = [
    ("收入预算公式", "在管面积 × 单价 × 12 × 收缴率 ×(1±空置率变动)",
     "《物业管理公司年度财务预算编制方案》通行做法", "见「02·收入预算」驱动因子表"),
    ("收缴率预算档位", "乐观 92% / 保守 88%（历史均值 90%）",
     "行业预算实操：按乐观、保守双档设定", "BUD 取 92.0%，LE 修正至 87.9%"),
    ("应急维修基金", "按在管面积 0.5 元/㎡/年计提",
     "行业弹性预算惯例", "见「07·资本性支出与专项预算」"),
    ("预算偏差预警", "偏差 >10% 触发调整；成本超支 15% 为红色预警",
     "行业预算监控惯例", "见「09·预算执行分析」红黄绿灯"),
    ("合约在管比", "1.30 倍（41 家上市物企 2024 年均值，2023 年 1.34）",
     "克而瑞物管 / 中指院", "本模型 1.27 倍（合约 2.54 亿㎡）"),
    ("第三方在管面积占比", "61.8%（32 家上市物企 2024 年）",
     "克而瑞物管", "本模型 62.0%（外拓 46% + 收并购 16%）"),
    ("非住宅业态面积占比", "34.21%（2024 年百强企业）",
     "中指院《2025 百强企业研究》", "本模型 32.0%"),
    ("计费方式结构", "包干制 98% / 酬金制 2%（建发物业 2023H1 营收口径）",
     "建发物业年报", "本模型包干制 96% / 酬金制 4%"),
    ("包干制费用构成", "物业服务成本 + 法定税费 + 物业管理企业利润",
     "发改价格〔2003〕1864 号《物业服务收费管理办法》第十一条", "见「11·物业服务合同台账」"),
    ("项目退出（行业主线）", "万物云退出 53 个住宅项目，涉及饱和收入 2.86 亿元",
     "2024 年报 / 克而瑞", "本模型全年退场 42 个项目，饱和收入 1.42 亿元"),
    ("百强净利率", "4.98%（2024 年，首次跌破 5%）",
     "中指院《2025 百强企业研究》", "BUD 5.15% / LE 4.00%"),
    ("上市物企管理费率", "9.4%（2024 年，同比 -0.6pct）",
     "克而瑞物管", "BUD 期间费用率 9.22% / LE 9.30%"),
    ("人均在管面积", "8,528 ㎡（50 家上市物企 2024 年，同比 +9.3%）",
     "克而瑞物管", "BUD 6,715 ㎡ / ACT 6,250 ㎡（本模型自有员工口径偏保守）"),
]

# ============================================================
# 1. 在管面积月度序列（BUD / LE 两条线）
# ============================================================
# 单位：㎡，月末在管口径
AREA_OPEN = int(1.9200 * YI)                    # 2026年初在管面积
AREA_LE_M = [int(x * YI) for x in
    [1.9260,1.9320,1.9450,1.9580,1.9640,1.9720,1.9660,1.9740,1.9820,1.9880,1.9940,2.0000]]
AREA_BUD_M = [int(x * YI) for x in
    [1.9320,1.9440,1.9680,1.9920,2.0080,2.0280,2.0320,2.0480,2.0640,2.0840,2.1000,2.1200]]
AREA_LE_AVG  = sum(AREA_LE_M) / 12
AREA_BUD_AVG = sum(AREA_BUD_M) / 12
AREA_LE_AVG8  = sum(AREA_LE_M[:8]) / 8
AREA_BUD_AVG8 = sum(AREA_BUD_M[:8]) / 8

# 面积增减台账（万㎡）
AREA_MOVE = OrderedDict([
    # 项目 -> (BUD 面积, BUD 项目数, LE 面积, LE 项目数)
    ("年初在管",            (AREA_OPEN, 578, AREA_OPEN, 578)),
    ("关联方开发交付",       (int(0.0820*YI), 22, int(0.0510*YI), 15)),
    ("第三方市场外拓",       (int(0.1350*YI), 34, int(0.0740*YI), 21)),
    ("收并购承接",          (int(0.0480*YI), 12, int(0.0200*YI),  5)),
    ("低质低效项目退场",     (int(-0.0450*YI), -12, int(-0.0650*YI), -19)),
    ("合同到期未续约",       (int(-0.0200*YI),  -6, int(-0.0300*YI),  -9)),
])
CONTRACT_AREA = int(2.5400 * YI)                # 合约面积（含储备）
CONTRACT_RATIO = CONTRACT_AREA / (2.0 * YI)     # 合约在管比

# ============================================================
# 2. 年初批复预算 BUD-2026（P&L）
# ============================================================
BUD_REV = OrderedDict([
    ("住宅物业管理服务",        int(32.05 * YI)),
    ("非住宅物业管理服务",       int(11.20 * YI)),
    ("案场协销及非业主增值服务",   int(4.42 * YI)),
    ("社区增值服务",           int(3.10 * YI)),
    ("多种经营（车位·广告·场地）", int(1.66 * YI)),
    ("顾问咨询及物资销售",       int(0.37 * YI)),
])
BUD_REV_TOTAL = sum(BUD_REV.values())                       # 52.80 亿
BUD_REV_MAIN  = sum(v for k, v in BUD_REV.items() if k in
                    ("住宅物业管理服务","非住宅物业管理服务","案场协销及非业主增值服务"))
BUD_REV_OTHER = BUD_REV_TOTAL - BUD_REV_MAIN
BUD_BASE_FEE  = BUD_REV["住宅物业管理服务"] + BUD_REV["非住宅物业管理服务"]

BUD_COGS_TARGET = int(42.502 * YI)
BUD_COGS = OrderedDict([
    ("职工薪酬",            0),          # 由人员预算驱动，见第 5 节回填
    ("分包及外包服务费",      int(9.620 * YI)),
    ("能源费（水/电/气/暖）",  int(2.740 * YI)),
    ("维修维护费",           int(2.620 * YI)),
    ("物料及低值易耗品",      int(1.230 * YI)),
    ("折旧与摊销",           int(1.150 * YI)),
    ("办公及差旅费",         int(0.690 * YI)),
    ("保险费及项目税费",      int(0.300 * YI)),
    ("其他项目直接费用",      0),          # 预算弹性储备，轧差回填
])
BUD_COGS_TOTAL = BUD_COGS_TARGET
BUD_OPEX = OrderedDict([
    ("税金及附加",  int(0.158 * YI)), ("销售费用", int(0.620 * YI)),
    ("管理费用",   int(3.850 * YI)), ("研发费用", int(0.420 * YI)),
    ("财务费用",   int(-0.180 * YI)),
])
BUD_IMPAIR = OrderedDict([("信用减值损失", int(1.420*YI)), ("资产减值损失", int(0.150*YI))])
BUD_OTHER_INC = OrderedDict([("其他收益", int(0.320*YI)), ("投资收益", int(0.140*YI)),
                             ("公允价值变动收益", int(0.020*YI)), ("资产处置收益", int(0.010*YI))])
BUD_NONOP = OrderedDict([("营业外收入", int(0.050*YI)), ("营业外支出", int(0.015*YI))])
BUD_TAX_RATE, BUD_MINORITY = 0.2650, 0.1560

BUD_STAFF_OPEX = int(round(sum(BUD_OPEX[k] * OPEX_LABOR[k] for k in OPEX_LABOR)))
BUD_GROSS = BUD_REV_TOTAL - BUD_COGS_TOTAL
BUD_OP = BUD_GROSS - sum(BUD_OPEX.values()) - sum(BUD_IMPAIR.values()) + sum(BUD_OTHER_INC.values())
BUD_EBT = BUD_OP + BUD_NONOP["营业外收入"] - BUD_NONOP["营业外支出"]
BUD_TAX = int(round(BUD_EBT * BUD_TAX_RATE))
BUD_NET = BUD_EBT - BUD_TAX
BUD_MI = int(round(BUD_NET * BUD_MINORITY))
BUD_PARENT = BUD_NET - BUD_MI

# 上年（2025）实际，用于预算增长率
# 演示版：2025 年四季度一次性确认 6.08 亿案场协销收入，全年 57 亿，1-8 月只占 58%
LY_FY = dict(rev=(PY_FULL_REV_DEMO if DEMO else int(round(PL_FY["rev_total"]/0.982))),
             parent=int(round(LY_YTD["parent"]/ (PL_YTD["parent"]/PL_FY["parent"]))))

# ============================================================
# 3. 预算月度分解系数（预算假设比实际更平滑）
# ============================================================
S_BASE_BUD = [a / sum(AREA_BUD_M) for a in AREA_BUD_M]
S_DEV_BUD  = _norm([0.078,0.076,0.084,0.086,0.084,0.086,0.082,0.080,0.084,0.086,0.086,0.088])
S_VAS_BUD  = _norm([0.062,0.058,0.078,0.082,0.086,0.088,0.084,0.082,0.088,0.092,0.098,0.102])
S_COST_BUD = _norm([0.0800,0.0778,0.0812,0.0820,0.0832,0.0845,0.0852,0.0850,0.0838,0.0838,0.0845,0.0890])
S_OPEX_BUD = _norm([0.0790,0.0770,0.0810,0.0818,0.0824,0.0838,0.0828,0.0822,0.0838,0.0852,0.0878,0.0932])
S_IMP_BUD  = _norm([0.070]*8 + [0.085,0.100,0.115,0.140])
S_MISC_BUD = _norm([0.070,0.068,0.082,0.100,0.086,0.088,0.078,0.078,0.084,0.088,0.090,0.088])

def bud_month(m):
    """第 m 月（1-based）预算 P&L"""
    rev = OrderedDict()
    for k, v in BUD_REV.items():
        s = (S_BASE_BUD if k in ("住宅物业管理服务","非住宅物业管理服务")
             else S_DEV_BUD if k == "案场协销及非业主增值服务" else S_VAS_BUD)
        rev[k] = alloc(v, s, m)
    cogs = OrderedDict((k, alloc(v, S_COST_BUD, m)) for k, v in BUD_COGS.items())
    opex = OrderedDict((k, alloc(v, S_OPEX_BUD, m)) for k, v in BUD_OPEX.items())
    imp  = OrderedDict((k, alloc(v, S_IMP_BUD, m)) for k, v in BUD_IMPAIR.items())
    oi   = OrderedDict((k, alloc(v, S_MISC_BUD, m)) for k, v in BUD_OTHER_INC.items())
    no   = OrderedDict((k, alloc(v, S_MISC_BUD, m)) for k, v in BUD_NONOP.items())
    rt, ct = sum(rev.values()), sum(cogs.values())
    op = rt - ct - sum(opex.values()) - sum(imp.values()) + sum(oi.values())
    ebt = op + no["营业外收入"] - no["营业外支出"]
    tax = int(round(ebt * BUD_TAX_RATE)); net = ebt - tax
    mi = int(round(net * BUD_MINORITY))
    return dict(m=m, rev=rev, cogs=cogs, opex=opex, imp=imp, oi=oi, no=no,
                rev_total=rt, cogs_total=ct, gross=rt-ct, op=op, ebt=ebt,
                tax=tax, net=net, mi=mi, parent=net-mi,
                area=AREA_BUD_M[m-1])
# 注意：BUD_M 的构建须在第 5 节回填 BUD_COGS["职工薪酬"] 之后，见文件末尾的 finalize_budget_months()

def bud_ytd(upto=PERIOD_M):
    a = OrderedDict()
    for key in ("rev","cogs","opex","imp","oi","no"):
        d = OrderedDict()
        for k in BUD_M[0][key]:
            d[k] = sum(BUD_M[m][key][k] for m in range(upto))
        a[key] = d
    for key in ("rev_total","cogs_total","gross","op","ebt","tax","net","mi","parent"):
        a[key] = sum(BUD_M[m][key] for m in range(upto))
    return a

# ============================================================
# 4. 单方指标（元/㎡/月，按加权平均在管面积）
# ============================================================
def unit(amount, area_avg, months=12): return amount / area_avg / months
BUD_UNIT = OrderedDict([
    ("单方营业收入", unit(BUD_REV_TOTAL, AREA_BUD_AVG)),
    ("单方基础物业费", unit(BUD_BASE_FEE, AREA_BUD_AVG)),
    ("单方营业成本", unit(BUD_COGS_TOTAL, AREA_BUD_AVG)),
    ("单方毛利", unit(BUD_GROSS, AREA_BUD_AVG)),
])
LE_BASE_FEE = PL_FY["rev_main_lines"]["住宅物业管理服务"] + PL_FY["rev_main_lines"]["非住宅物业管理服务"]
LE_UNIT = OrderedDict([
    ("单方营业收入", unit(PL_FY["rev_total"], AREA_LE_AVG)),
    ("单方基础物业费", unit(LE_BASE_FEE, AREA_LE_AVG)),
    ("单方营业成本", unit(PL_FY["cogs_total"], AREA_LE_AVG)),
    ("单方毛利", unit(PL_FY["gross"], AREA_LE_AVG)),
])

# ============================================================
# 5. 人员预算（按岗位序列）—— 职工薪酬预算的驱动因子
# ============================================================
HC_BUD = OrderedDict([                     # 岗位 -> (预算人数, 预算年人均全成本 元/人)
    ("秩序维护（安保）",   (9_180,  65_850)),
    ("环境保洁",         (7_820,  56_500)),
    ("工程设备维保",      (4_260, 102_130)),
    ("客服及管家",        (4_050,  84_550)),
    ("绿化养护",         (1_530,  59_150)),
    ("项目及区域管理",     (2_240, 170_700)),
    ("职能与共享中心",     (1_120, 256_100)),
])
HC_BUD_TOTAL = sum(v[0] for v in HC_BUD.values())
BUD_STAFF_ALL = sum(n * c for n, c in HC_BUD.values())        # 职工薪酬预算总额
# 回填：营业成本中的职工薪酬 = 总额 － 计入期间费用的部分；其他项目直接费用作弹性储备
BUD_COGS["职工薪酬"] = BUD_STAFF_ALL - BUD_STAFF_OPEX
BUD_COGS["其他项目直接费用"] = BUD_COGS_TARGET - sum(v for k, v in BUD_COGS.items()
                                                if k != "其他项目直接费用")
assert sum(BUD_COGS.values()) == BUD_COGS_TARGET

# 实际人员结构（月结套表口径），人均成本按实际职工薪酬总额校准
ACT_STAFF_OPEX = int(round(sum(PL_FY["opex"][k] * OPEX_LABOR[k] for k in OPEX_LABOR)))
ACT_STAFF_ALL = CG_TOT_FY["职工薪酬"] + ACT_STAFF_OPEX
_HC_ACT_RAW = OrderedDict([
    ("秩序维护（安保）",   (9_850,  63_500)), ("环境保洁",     (8_420,  54_200)),
    ("工程设备维保",      (4_360,  98_000)), ("客服及管家",    (4_180,  81_500)),
    ("绿化养护",         (1_640,  56_800)), ("项目及区域管理", (2_350, 165_000)),
    ("职能与共享中心",     (1_200, 248_000)),
])
_SC = ACT_STAFF_ALL / sum(n * c for n, c in _HC_ACT_RAW.values())
HC_ACT, _acc, _ks = OrderedDict(), 0, list(_HC_ACT_RAW)
for _i, _k in enumerate(_ks):
    _n, _c = _HC_ACT_RAW[_k]
    if _i == len(_ks) - 1:
        HC_ACT[_k] = (_n, (ACT_STAFF_ALL - _acc) / _n)        # 末项承担校准尾差
    else:
        _v = round(_c * _SC); _acc += _n * _v; HC_ACT[_k] = (_n, _v)
ACT_STAFF_ALL_CHK = int(round(sum(n * c for n, c in HC_ACT.values())))

# 月度预算展开（须在 BUD_COGS 回填完成后执行），并令 12 月吸收所得税与少数股东损益的舍入尾差
BUD_M = [bud_month(m) for m in range(1, 13)]
for _key, _tgt in (("tax", BUD_TAX), ("mi", BUD_MI)):
    BUD_M[11][_key] += _tgt - sum(x[_key] for x in BUD_M)
BUD_M[11]["net"] = BUD_M[11]["ebt"] - BUD_M[11]["tax"]
BUD_M[11]["parent"] = BUD_M[11]["net"] - BUD_M[11]["mi"]
BUD_YTD = bud_ytd()

# 职工薪酬差异分解（量差/价差）
HC_ACT_TOTAL = sum(v[0] for v in HC_ACT.values())
BUD_UNIT_STAFF = BUD_STAFF_ALL / HC_BUD_TOTAL
ACT_UNIT_STAFF = ACT_STAFF_ALL_CHK / HC_ACT_TOTAL
STAFF_VAR_QTY   = (HC_ACT_TOTAL - HC_BUD_TOTAL) * BUD_UNIT_STAFF          # 人数差异
STAFF_VAR_PRICE = (ACT_UNIT_STAFF - BUD_UNIT_STAFF) * HC_ACT_TOTAL        # 人均成本差异

# ============================================================
# 6. 差异分析：量价分解与利润桥
# ============================================================
LE_OPEX_TOTAL = sum(PL_FY["opex"].values())
BUD_OPEX_TOTAL = sum(BUD_OPEX.values())
LE_IMPAIR_TOTAL = sum(PL_FY["impair"].values())
BUD_IMPAIR_TOTAL = sum(BUD_IMPAIR.values())
LE_OI_TOTAL = sum(PL_FY["other_inc"].values())
BUD_OI_TOTAL = sum(BUD_OTHER_INC.values())

def qty_price(bud_amt, bud_qty, act_amt, act_qty, months=12):
    """量价分解：量差＝ΔQ×预算单价；价差＝Δ单价×实际Q（残差并入价差）"""
    p_bud = bud_amt / bud_qty / months
    p_act = act_amt / act_qty / months
    q_var = (act_qty - bud_qty) * p_bud * months
    p_var = (act_amt - bud_amt) - q_var
    return dict(p_bud=p_bud, p_act=p_act, q_var=q_var, p_var=p_var,
                total=act_amt - bud_amt)
REV_QP  = qty_price(BUD_BASE_FEE, AREA_BUD_AVG, LE_BASE_FEE, AREA_LE_AVG)
COST_QP = qty_price(BUD_COGS_TOTAL, AREA_BUD_AVG, PL_FY["cogs_total"], AREA_LE_AVG)
REVALL_QP = qty_price(BUD_REV_TOTAL, AREA_BUD_AVG, PL_FY["rev_total"], AREA_LE_AVG)

# 收入分板块差异
SEG_MAP = OrderedDict([
    ("住宅物业管理服务", ("main", "住宅物业管理服务")),
    ("非住宅物业管理服务", ("main", "非住宅物业管理服务")),
    ("案场协销及非业主增值服务", ("main", "案场协销及非业主增值服务")),
    ("社区增值服务", ("other", "社区增值服务")),
    ("多种经营（车位·广告·场地）", ("other", "多种经营（车位·广告·场地）")),
    ("顾问咨询及物资销售", ("other", "顾问咨询及物资销售")),
])
def le_rev(seg):
    kind, k = SEG_MAP[seg]
    return PL_FY["rev_main_lines"][k] if kind == "main" else PL_FY["rev_other_lines"][k]
REV_VAR = [(s, BUD_REV[s], le_rev(s), le_rev(s) - BUD_REV[s]) for s in SEG_MAP]

# 成本分科目差异（BUD 科目名 -> LE 分组名）
COGS_KEYMAP = {"职工薪酬":"职工薪酬", "分包及外包服务费":"分包及外包服务费",
               "能源费（水/电/气/暖）":"能源费", "维修维护费":"维修维护费",
               "物料及低值易耗品":"物料及低值易耗品", "折旧与摊销":"折旧与摊销",
               "办公及差旅费":"办公及差旅费", "保险费及项目税费":"保险费及项目税费",
               "其他项目直接费用":"其他直接费用"}
COGS_VAR = [(k, BUD_COGS[k], CG_TOT_FY[COGS_KEYMAP[k]], CG_TOT_FY[COGS_KEYMAP[k]] - BUD_COGS[k])
            for k in BUD_COGS]

# 营业利润桥（BUD → LE）
d_rev = PL_FY["rev_total"] - BUD_REV_TOTAL
d_gm  = PL_FY["gross"]/PL_FY["rev_total"] - BUD_GROSS/BUD_REV_TOTAL
BRIDGE = [
    ("年初批复预算 营业利润", BUD_OP, "anchor"),
    ("① 收入规模缺口（按预算毛利率折算）", int(round(d_rev * BUD_GROSS / BUD_REV_TOTAL)), "step"),
    ("② 毛利率变动（按实际收入折算）", int(round(d_gm * PL_FY["rev_total"])), "step"),
    ("③ 期间费用节约", -(LE_OPEX_TOTAL - BUD_OPEX_TOTAL), "step"),
    ("④ 减值损失超支", -(LE_IMPAIR_TOTAL - BUD_IMPAIR_TOTAL), "step"),
    ("⑤ 其他收益及投资收益变动", LE_OI_TOTAL - BUD_OI_TOTAL, "step"),
]
_bridge_sum = sum(v for _, v, t in BRIDGE if t == "step")
BRIDGE.append(("⑥ 尾差（毛利分解交叉项）", (PL_FY["op_profit"] - BUD_OP) - _bridge_sum, "step"))
BRIDGE.append(("滚动预测 营业利润", PL_FY["op_profit"], "anchor"))

PARENT_BRIDGE = [
    ("年初批复预算 归母净利润", BUD_PARENT, "anchor"),
    ("营业利润差异", PL_FY["op_profit"] - BUD_OP, "step"),
    ("营业外收支变动", (PL_FY["nonop"]["营业外收入"] - PL_FY["nonop"]["营业外支出"])
                    - (BUD_NONOP["营业外收入"] - BUD_NONOP["营业外支出"]), "step"),
    ("所得税费用变动", -(PL_FY["tax"] - BUD_TAX), "step"),
    ("少数股东损益变动", -(PL_FY["minority"] - BUD_MI), "step"),
    ("滚动预测 归母净利润", PL_FY["parent"], "anchor"),
]

# 1-8月预算执行（日历进度 vs 预算进度 vs 实际完成）
TIME_PROGRESS = PERIOD_M / 12                        # 日历进度 66.67%
PROG_REV  = BUD_YTD["rev_total"] / BUD_REV_TOTAL     # 收入预算进度
PROG_COGS = BUD_YTD["cogs_total"] / BUD_COGS_TOTAL
PROG_OPEX = sum(BUD_YTD["opex"].values()) / BUD_OPEX_TOTAL
PROG_OP   = BUD_YTD["op"] / BUD_OP                   # 营业利润预算进度
PROG_PAR  = BUD_YTD["parent"] / BUD_PARENT
EXEC_ROWS = [
    ("营业收入", BUD_YTD["rev_total"], PL_YTD["rev_total"], BUD_REV_TOTAL, "正向"),
    ("　其中：基础物业管理费", sum(BUD_YTD["rev"][k] for k in ("住宅物业管理服务","非住宅物业管理服务")),
     BASE_FEE_REV_YTD, BUD_BASE_FEE, "正向"),
    ("　　　　案场协销及非业主增值", BUD_YTD["rev"]["案场协销及非业主增值服务"],
     PL_YTD["rev_main_lines"]["案场协销及非业主增值服务"], BUD_REV["案场协销及非业主增值服务"], "正向"),
    ("　　　　社区增值及多种经营", sum(BUD_YTD["rev"][k] for k in
        ("社区增值服务","多种经营（车位·广告·场地）","顾问咨询及物资销售")),
     PL_YTD["rev_other"], BUD_REV_OTHER, "正向"),
    ("营业成本", BUD_YTD["cogs_total"], PL_YTD["cogs_total"], BUD_COGS_TOTAL, "反向"),
    ("　其中：职工薪酬", BUD_YTD["cogs"]["职工薪酬"], CG_TOT_Y["职工薪酬"], BUD_COGS["职工薪酬"], "反向"),
    ("　　　　分包及外包服务费", BUD_YTD["cogs"]["分包及外包服务费"], CG_TOT_Y["分包及外包服务费"],
     BUD_COGS["分包及外包服务费"], "反向"),
    ("　　　　能源费", BUD_YTD["cogs"]["能源费（水/电/气/暖）"], CG_TOT_Y["能源费"],
     BUD_COGS["能源费（水/电/气/暖）"], "反向"),
    ("　　　　维修维护费", BUD_YTD["cogs"]["维修维护费"], CG_TOT_Y["维修维护费"],
     BUD_COGS["维修维护费"], "反向"),
    ("毛利", BUD_YTD["gross"], PL_YTD["gross"], BUD_GROSS, "正向"),
    ("期间费用合计", sum(BUD_YTD["opex"].values()), sum(PL_YTD["opex"].values()), BUD_OPEX_TOTAL, "反向"),
    ("　其中：管理费用", BUD_YTD["opex"]["管理费用"], PL_YTD["opex"]["管理费用"], BUD_OPEX["管理费用"], "反向"),
    ("　　　　销售费用", BUD_YTD["opex"]["销售费用"], PL_YTD["opex"]["销售费用"], BUD_OPEX["销售费用"], "反向"),
    ("　　　　研发费用", BUD_YTD["opex"]["研发费用"], PL_YTD["opex"]["研发费用"], BUD_OPEX["研发费用"], "反向"),
    ("信用减值损失", BUD_YTD["imp"]["信用减值损失"], PL_YTD["impair"]["信用减值损失"],
     BUD_IMPAIR["信用减值损失"], "反向"),
    ("营业利润", BUD_YTD["op"], PL_YTD["op_profit"], BUD_OP, "正向"),
    ("归属于母公司净利润", BUD_YTD["parent"], PL_YTD["parent"], BUD_PARENT, "正向"),
]

def light(bud, act, direction):
    """红黄绿灯：正向指标看完成率，反向（成本费用）看超支率"""
    if not bud: return "—", ""
    r = act / bud - 1
    if direction == "正向":
        return ("绿灯", r) if r >= -0.05 else (("黄灯", r) if r >= -0.10 else ("红灯", r))
    return ("绿灯", r) if r <= 0.05 else (("黄灯", r) if r <= 0.15 else ("红灯", r))

# ============================================================
# 7. 收缴率预算
# ============================================================
COLL_BUD = OrderedDict([                    # 区域 -> (预算本年账单收缴率, 预算综合收缴率)
    ("华东区域", (0.9350, 0.8880)), ("华南区域", (0.9250, 0.8760)),
    ("华北区域", (0.9150, 0.8620)), ("华中区域", (0.9020, 0.8480)),
    ("西部区域", (0.8900, 0.8350)),
])
COLL_BUD_ALL = sum(COLL_BUD[r][0] * BUD_REV_TOTAL * (REGPL_YTD[r]["rev"]/PL_YTD["rev_total"])
                   for r in COLL_BUD) / sum(BUD_REV_TOTAL * (REGPL_YTD[r]["rev"]/PL_YTD["rev_total"])
                   for r in COLL_BUD)

# ============================================================
# 8. 区域与城市公司预算
# ============================================================
REG_BUD_MIX = OrderedDict([          # 区域 -> (收入占比, 目标毛利率, 面积占比)
    ("华东区域", (0.3420, 0.2200, 0.3080)), ("华南区域", (0.2260, 0.2130, 0.2190)),
    ("华北区域", (0.1830, 0.1970, 0.1920)), ("华中区域", (0.1520, 0.1860, 0.1710)),
    ("西部区域", (0.0970, 0.1780, 0.1100)),
])
def region_budget():
    out, acc_r, acc_c, acc_a = OrderedDict(), 0, 0, 0
    ks = list(REG_BUD_MIX)
    for i, r in enumerate(ks):
        sr, gm, sa = REG_BUD_MIX[r]
        rev = (BUD_REV_TOTAL - acc_r) if i == len(ks)-1 else int(round(BUD_REV_TOTAL * sr))
        area = (int(2.12*YI) - acc_a) if i == len(ks)-1 else int(round(2.12 * YI * sa))
        cogs = int(round(rev * (1 - gm)))
        acc_r += rev; acc_c += cogs; acc_a += area
        out[r] = dict(rev=rev, cogs=cogs, gross=rev-cogs, area=area,
                      opex=int(round(BUD_OPEX_TOTAL * 0.78 * sr)),
                      impair=int(round(BUD_IMPAIR_TOTAL * REGIONS[r]["ar"])))
    hq_c = BUD_COGS_TOTAL - acc_c
    out[HQ_NAME] = dict(rev=0, cogs=hq_c, gross=-hq_c, area=0,
                        opex=BUD_OPEX_TOTAL - sum(v["opex"] for v in out.values()),
                        impair=BUD_IMPAIR_TOTAL - sum(v["impair"] for v in out.values()))
    for r in out:
        out[r]["op"] = out[r]["gross"] - out[r]["opex"] - out[r]["impair"]
    return out
REG_BUD = region_budget()

def city_budget():
    """城市公司预算：按区域内权重拆分，与月结套表城市公司口径一一对应"""
    rows, idx = [], 0
    for r in REGIONS:
        R = REG_BUD[r]; acc = defaultdict(int); n = len(CITY_NAMES[r])
        for i, c in enumerate(CITY_NAMES[r]):
            last = (i == n - 1)
            def take(key, total, wt):
                if last: return total - acc[key]
                v = int(round(total * wt)); acc[key] += v; return v
            rev = take("rev", R["rev"], CITY_WR[i])
            gm = REG_BUD_MIX[r][1] + CITY_GM_ADJ[i]
            cogs = int(round(rev * (1 - gm))) if not last else R["cogs"] - acc["cogs"]
            if not last: acc["cogs"] += cogs
            rows.append(dict(region=r, city=f"{c}城市公司",
                             area=take("area", R["area"], CITY_W[i]),
                             rev=rev, cogs=cogs, gross=rev-cogs,
                             opex=take("opex", R["opex"], CITY_WR[i]),
                             impair=take("impair", R["impair"], CITY_WR[i])))
            rows[-1]["op"] = rows[-1]["gross"] - rows[-1]["opex"] - rows[-1]["impair"]
            idx += 1
    return rows
CITY_BUD = city_budget()

# ============================================================
# 9. 资本性支出与专项预算
# ============================================================
CAPEX_BUD = OrderedDict([
    ("项目设施设备更新改造", (int(0.620*YI), int(0.372*YI), "电梯、供配电、消防、监控")),
    ("智慧物业与数字化投入", (int(0.380*YI), int(0.196*YI), "IoT 平台、AI 客服、清洁机器人")),
    ("车辆及工程装备",      (int(0.140*YI), int(0.082*YI), "巡逻车、高压清洗、绿化机械")),
    ("办公场所及信息化",     (int(0.090*YI), int(0.058*YI), "区域办公、ERP 升级")),
    ("收并购股权对价",      (int(0.850*YI), int(0.360*YI), "城市公司及项目组合收购")),
    ("新项目前期投入",      (int(0.320*YI), int(0.222*YI), "承接查验、开办费，计入长期待摊")),
])
CAPEX_BUD_TOTAL = sum(v[0] for v in CAPEX_BUD.values())
CAPEX_ACT_YTD = sum(v[1] for v in CAPEX_BUD.values())
EMERGENCY_FUND_RATE = 0.50            # 元/㎡/年，行业弹性预算惯例
EMERGENCY_FUND_BUD = int(round(AREA_BUD_AVG * EMERGENCY_FUND_RATE))

# ============================================================
# 10. 月度资金预算
# ============================================================
CASH_OP_BUD  = [int(x*YI) for x in [-0.35,0.28,0.52,0.55,0.58,0.60,0.42,0.55,0.62,0.68,0.85,0.90]]
CASH_INV_BUD = [int(x*YI) for x in [-0.12,-0.15,-0.22,-0.18,-0.25,-0.20,-0.28,-0.22,-0.18,-0.25,-0.20,-0.15]]
CASH_FIN_BUD = [int(x*YI) for x in [-0.08,-0.05,-0.12,-0.10,-0.85,-0.15,-0.08,-0.05,-0.12,-0.10,-0.30,-0.15]]
CASH_OPEN = BS["cash_o"]
def cash_budget():
    rows, bal = [], CASH_OPEN
    for m in range(12):
        net = CASH_OP_BUD[m] + CASH_INV_BUD[m] + CASH_FIN_BUD[m]
        rows.append(dict(m=m+1, open=bal, op=CASH_OP_BUD[m], inv=CASH_INV_BUD[m],
                         fin=CASH_FIN_BUD[m], net=net, close=bal+net))
        bal += net
    return rows
CASH_BUD_ROWS = cash_budget()
CASH_ACT_YTD = dict(op=CFI_YTD_NET, inv=CF_INV_NET_Y, fin=CF_FIN_NET_Y,
                    net=CF_NET_TOTAL_Y, close=BSD_C["货币资金"])

# ============================================================
# 11. 物业服务合同台账（600 个在管项目）
# ============================================================
RNG = random.Random(20260831)

# 业态 -> (面积占比, 基准单价元/㎡/月, 空置率区间, 合同年限权重, 政府指导价概率)
FORMATS = OrderedDict([
    ("住宅——高端及改善", (0.21, 2.680, (0.020,0.065), {2:0.20,3:0.46,5:0.34}, 0.18)),
    ("住宅——刚需及安置", (0.47, 1.380, (0.035,0.095), {2:0.34,3:0.48,5:0.18}, 0.62)),
    ("写字楼及商业",     (0.06, 3.600, (0.080,0.220), {3:0.52,5:0.38,8:0.10}, 0.02)),
    ("产业园区及公建",   (0.14, 1.320, (0.040,0.130), {3:0.46,5:0.42,8:0.12}, 0.10)),
    ("城市服务及市政",   (0.09, 1.050, (0.000,0.020), {3:0.58,5:0.34,8:0.08}, 0.24)),
    ("其他业态",        (0.03, 1.650, (0.050,0.160), {2:0.28,3:0.50,5:0.22}, 0.14)),
])
SAT_TARGET = int(43.60 * YI)                  # 年化饱和收入合计
SAT_FACTOR = SAT_TARGET / LE_BASE_FEE
BASE_AR_SHARE = AR_CUSTOMER["业主及住户（住宅）"] + AR_CUSTOMER["业主及租户（非住宅）"]
BASE_FEE_YTD_SHARE = BASE_FEE_REV_YTD / PL_YTD["rev_total"]
SOURCE_W = [("关联方开发交付", 0.38), ("第三方市场外拓", 0.46), ("收并购承接", 0.16)]
BILL_MODE_W = [("包干制", 0.96), ("酬金制", 0.04)]
PRICE_ADJ_W = [("固定单价，无自动调价", 0.62), ("每 3 年协商调价", 0.26), ("与 CPI 联动", 0.12)]
NAME_A = ["锦绣","翡翠","金域","天玺","云锦","观澜","悦","璟宸","香颂","和风","清源","明珠",
          "紫台","龙湾","江山","水岸","林语","盛世","华庭","鼎峰","星河","康城","雅","澜庭",
          "御景","新元","嘉裕","瑞宸","栖谷","宸章","汀兰","서","朗阅","叠翠","沁园","风华"]
NAME_A = [x for x in NAME_A if x != "서"]
SUF = {"住宅——高端及改善": ["华府","公馆","天玺","云邸","璟园","雅集"],
       "住宅——刚需及安置": ["家园","花园","新苑","嘉园","佳苑","安置区","保障房片区"],
       "写字楼及商业":     ["国际中心","广场","大厦","商务中心","中心"],
       "产业园区及公建":   ["产业园","科技园","创新中心","行政中心","人民医院","实验学校","文体中心"],
       "城市服务及市政":   ["片区城市服务","街道环境项目","新区市政管养","开发区综合服务"],
       "其他业态":        ["长租公寓","人才公寓","康养中心","物流园"]}
TODAY_Y, TODAY_M = PERIOD_Y, PERIOD_M          # 台账基准日 2026-08-31

def _pick(rng, pairs):
    x = rng.random(); c = 0
    for k, w in pairs:
        c += w
        if x <= c: return k
    return pairs[-1][0]

def region_collection_targets():
    """月结套表「08·AR收缴率与欠费」第一段的区域实收，按 build.py 同一公式算（元）。"""
    bill_tot = int(round(BASE_FEE_REV_YTD * 1.048))
    out = OrderedDict()
    for rg in REGIONS:
        share = REGPL_YTD[rg]["rev"] / PL_YTD["rev_total"]
        bill = int(round(bill_tot * share))
        out[rg] = int(round(bill * REGIONS[rg]["coll"]))
    return out


def _align_collections_to_regions(rows):
    """逐份收缴率随机生成后带业态偏移（刚需 -5.5pct、公建市政 +4.5pct），不回调会让
    台账实收整体比月结区域实收低约 2,793 万元。这里按区域等比例回调收缴率，
    使台账区域实收 = 月结区域实收，尾差归入区域内账单最大的合同。"""
    targets = region_collection_targets()
    for rg, target in targets.items():
        mine = [r for r in rows if r["区域"] == rg]
        bills = [r["本年账单含税（元）"] for r in mine]
        raw = [b * r["本年账单收缴率"] for b, r in zip(bills, mine)]
        k = target / sum(raw)
        for r, b, x in zip(mine, bills, raw):
            coll = min(0.995, x * k / b)
            r["本年实收（元）"] = int(round(b * coll))
        big = max(mine, key=lambda r: r["本年账单含税（元）"])
        big["本年实收（元）"] += target - sum(r["本年实收（元）"] for r in mine)
        for r in mine:
            r["本年账单收缴率"] = round(r["本年实收（元）"] / r["本年账单含税（元）"], 4)
        assert sum(r["本年实收（元）"] for r in mine) == target, "台账区域实收必须等于月结区域实收"
        assert all(0 < r["本年实收（元）"] <= r["本年账单含税（元）"] for r in mine)


def build_property_contracts():
    rows = []
    fmt_keys = list(FORMATS)
    fmt_w = [(k, FORMATS[k][0]) for k in fmt_keys]
    seq = defaultdict(int)
    for ci, C in enumerate(CITY_ROWS):
        n = C["proj"]
        city_short = C["city"].replace("城市公司", "")
        # 城市能级系数：区域内排序越靠前，单价越高
        rank = ci % 10
        lvl = 1.0 + 0.24 * (0.5 - rank / 9.0) * 2 * 0.5
        # 面积分布（大小项目混合），归一到城市面积
        raw = [max(rng_v, 0.12) for rng_v in
               (RNG.lognormvariate(0, 0.62) for _ in range(n))]
        s = sum(raw); areas = [C["area"] * x / s for x in raw]
        areas = [int(round(a)) for a in areas]; areas[-1] += C["area"] - sum(areas)
        fmts = [_pick(RNG, fmt_w) for _ in range(n)]
        prices = [FORMATS[f][1] * lvl * RNG.uniform(0.90, 1.12) for f in fmts]
        # 城市内价格归一，使饱和收入 = 城市目标
        city_sat = C["rev"] * BASE_FEE_YTD_SHARE / 0.6589 * SAT_FACTOR
        sat_raw = sum(a * p * 12 for a, p in zip(areas, prices))
        prices = [p * city_sat / sat_raw for p in prices]
        sats = [int(round(a * p * 12)) for a, p in zip(areas, prices)]
        sats[-1] += int(round(city_sat)) - sum(sats)
        # 1-8 月确认收入：饱和 ×(1-空置折扣)× 进度
        vac = [RNG.uniform(*FORMATS[f][2]) for f in fmts]
        rec_raw = [s_ * (1 - v * 0.62) * 0.6589 / SAT_FACTOR for s_, v in zip(sats, vac)]
        city_rec = C["rev"] * BASE_FEE_YTD_SHARE
        k = city_rec / sum(rec_raw)
        recs = [int(round(x * k)) for x in rec_raw]
        recs[-1] += int(round(city_rec)) - sum(recs)
        # 应收账款
        ar_raw = [max(r_ * (1 - C["coll"]) * RNG.uniform(0.7, 1.9) + s_ * 0.012 * RNG.uniform(0.3, 2.2), 1)
                  for r_, s_ in zip(recs, sats)]
        city_ar = C["ar"] * BASE_AR_SHARE
        k = city_ar / sum(ar_raw)
        ars = [int(round(x * k)) for x in ar_raw]
        ars[-1] += int(round(city_ar)) - sum(ars)
        for i in range(n):
            f = fmts[i]
            seq[C["region"]] += 1
            # 先定到期档（12个月内 18% / 13-24月 22% / 25-36月 24% / >36月 36%），
            # 再在能容纳该剩余期限的合同年限中选取，避免出现剩余期限超过合同期的矛盾
            bucket = _pick(RNG, [(0, 0.18), (1, 0.22), (2, 0.24), (3, 0.36)])
            lo, hi = [(1, 12), (13, 24), (25, 36), (37, 96)][bucket]
            elig = [(tm, w) for tm, w in FORMATS[f][3].items() if tm * 12 >= lo]
            if not elig:
                elig = [(max(FORMATS[f][3]), 1.0)]
            sw = sum(w for _, w in elig)
            term = _pick(RNG, [(tm, w / sw) for tm, w in elig])
            rem = RNG.randint(lo, min(hi, term * 12))
            end_m = TODAY_M + rem
            end_y = TODAY_Y + (end_m - 1) // 12; end_m = (end_m - 1) % 12 + 1
            start_y = end_y - term; start_m = end_m
            coll = min(0.995, max(0.60, C["coll"] + RNG.uniform(-0.075, 0.075)
                                  + (0.045 if "公建" in f or "市政" in f else 0)
                                  - (0.055 if "刚需" in f else 0)))
            bill = int(round(recs[i] * 1.048))
            gm = C["gross"]/C["rev"] + RNG.uniform(-0.055, 0.055) + (0.03 if "高端" in f else 0) \
                 - (0.025 if "市政" in f else 0)
            status = ("已续签待生效" if (rem <= 12 and RNG.random() < 0.42) else
                      "12 个月内到期，待谈判" if rem <= 12 else
                      "24 个月内到期，跟进中" if rem <= 24 else "正常在约")
            rows.append(OrderedDict([
                ("合同编号", f"WY-{start_y}-{C['region'][:2]}-{seq[C['region']]:04d}"),
                ("项目名称", f"{city_short}·{RNG.choice(NAME_A)}{RNG.choice(SUF[f])}"),
                ("区域", C["region"]), ("城市公司", C["city"]), ("城市", city_short),
                ("业态", f),
                ("项目来源", _pick(RNG, SOURCE_W)),
                ("计费方式", _pick(RNG, BILL_MODE_W)),
                ("定价方式", "政府指导价" if RNG.random() < FORMATS[f][4] else "市场调节价"),
                ("合同起始日", f"{start_y}-{start_m:02d}-01"),
                ("合同到期日", f"{end_y}-{end_m:02d}-{calendar.monthrange(end_y, end_m)[1]:02d}"),
                ("合同期限（年）", term), ("剩余期限（月）", rem),
                ("在管建筑面积（㎡）", areas[i]),
                ("物业费单价（元/㎡/月）", round(prices[i], 4)),
                ("年化饱和收入（元）", sats[i]),
                ("空置率", round(vac[i], 4)),
                ("本年确认收入（元）", recs[i]),
                ("本年账单含税（元）", bill),
                ("本年实收（元）", int(round(bill * coll))),
                ("本年账单收缴率", round(coll, 4)),
                ("应收账款余额（元）", ars[i]),
                ("调价条款", _pick(RNG, PRICE_ADJ_W)),
                ("项目毛利率", round(max(gm, -0.08), 4)),
                ("在岗人数", max(3, int(round(areas[i] / RNG.uniform(5200, 7600))))),
                ("续约状态", status),
            ]))
    if not DEMO:  # F-02：演示版保留台账实收与月结区域实收的差异
        _align_collections_to_regions(rows)
    # 饱和收入尾差归入最大项目
    diff = SAT_TARGET - sum(r["年化饱和收入（元）"] for r in rows)
    big = max(rows, key=lambda r: r["年化饱和收入（元）"])
    big["年化饱和收入（元）"] += diff
    # 退场候选：按「毛利率 + 收缴率」综合评分取末位 26 个，对应 AREA_MOVE 中的次年退场计划
    rows.sort(key=lambda r: r["项目毛利率"] * 0.60 + (r["本年账单收缴率"] - 0.85) * 0.40)
    for r in rows[:26]:
        r["续约状态"] = "拟退场（已提交评审）"
    rows.sort(key=lambda r: r["合同编号"])
    return rows
PROP_CONTRACTS = build_property_contracts()
EXIT_CANDIDATES = [r for r in PROP_CONTRACTS if r["续约状态"] == "拟退场（已提交评审）"]

# ============================================================
# 12. 采购与外包合同台账（240 份）
# ============================================================
RNG2 = random.Random(20261231)
AP_CREDIT_COST_FY = sum(CG_TOT_FY[g] for g in ["分包及外包服务费","能源费","维修维护费",
                        "物料及低值易耗品","办公及差旅费","保险费及项目税费","其他直接费用"])
PURCH_FY_TOTAL = int(round(AP_CREDIT_COST_FY * 1.075))       # 年化采购额（含税）
SUP_FIRM = ["洁美","鑫安","绿源","恒达","明泰","宏图","瑞成","盛世","鼎丰","佳信","日兴","天诚",
            "康洁","卫安","沃野","蓝天","金盾","清扬","汇通","正阳","鸿运","力天","博远","启元",
            "华瑞","立信","嘉盛","中锐","远航","科捷"]
SUP_SUFFIX = {
    "保洁清洁外包服务商":       ["环境服务有限公司","保洁服务有限公司","环境科技有限公司"],
    "秩序维护（安保）外包服务商":  ["保安服务有限公司","安保服务有限公司","安全管理有限公司"],
    "绿化养护外包服务商":       ["园林绿化有限公司","生态景观有限公司"],
    "电梯及设备维保服务商":     ["电梯工程有限公司","机电设备有限公司","设施维保有限公司"],
    "水电气热能源供应商":       ["供电服务有限公司","自来水有限公司","燃气有限公司","热力有限公司"],
    "工程维修及改造承包商":     ["建设工程有限公司","装饰工程有限公司","机电安装有限公司"],
    "物料及低值易耗品供应商":   ["商贸有限公司","物资供应链有限公司"],
    "信息化及其他服务商":       ["信息技术有限公司","智能科技有限公司","数字科技有限公司"],
}
PRICE_MODE = {
    "保洁清洁外包服务商":       ["按人头包干（元/人/月）","按面积单价（元/㎡/月）"],
    "秩序维护（安保）外包服务商":  ["按人头包干（元/人/月）","按岗位配置固定年费"],
    "绿化养护外包服务商":       ["按面积单价（元/㎡/年）","固定总价"],
    "电梯及设备维保服务商":     ["按台套年费","按次计费 + 备件按实结算"],
    "水电气热能源供应商":       ["按实计量结算（政府定价）"],
    "工程维修及改造承包商":     ["工程量清单计价","固定总价 + 签证变更"],
    "物料及低值易耗品供应商":   ["集采协议价 + 按需下单"],
    "信息化及其他服务商":       ["年度订阅费","项目制固定总价"],
}
GRADE_W = [("A（优秀）", 0.24), ("B（良好）", 0.48), ("C（合格）", 0.22), ("D（限期整改）", 0.06)]

def build_purchase_contracts():
    rows, seq = [], defaultdict(int)
    regions = list(REGIONS)
    reg_w = {r: REGPL_YTD[r]["cogs"] / sum(REGPL_YTD[x]["cogs"] for x in REGIONS) for r in regions}
    cats = list(AP_SUPPLIER)
    sup_by_cat = {s["cat"]: s for s in AP_SUP_ROWS}
    for cat in cats:
        share, term_d, act_d = AP_SUPPLIER[cat]
        cat_annual = int(round(PURCH_FY_TOTAL * share))
        cat_ytd    = sup_by_cat[cat]["purch"]
        cat_ap     = sup_by_cat[cat]["amt"]
        cells = [(r, i) for r in regions for i in range(6)]
        wts = [reg_w[r] * (1.55 if i == 0 else 1.10 if i == 1 else 0.78 if i < 4 else 0.52)
               for r, i in cells]
        wts = [w / sum(wts) for w in wts]
        # 应付余额单独加权：结算快慢因合同而异，使各合同实际账期有真实分布
        lag = [RNG2.uniform(0.55, 1.65) for _ in cells]
        ap_w = [w * l for w, l in zip(wts, lag)]
        ap_w = [x / sum(ap_w) for x in ap_w]
        acc = defaultdict(int)
        for j, ((r, i), w) in enumerate(zip(cells, wts)):
            last = (j == len(cells) - 1)
            def take(key, total, wt=None):
                if last: return total - acc[key]
                v = int(round(total * (w if wt is None else wt))); acc[key] += v; return v
            annual, ytd = take("a", cat_annual), take("y", cat_ytd)
            ap = take("p", cat_ap, ap_w[j])
            seq[r] += 1
            city = RNG2.choice(CITY_NAMES[r])
            if "能源" in cat:
                name = f"{city}市{RNG2.choice(SUP_SUFFIX[cat])}"
            else:
                name = f"{city}{RNG2.choice(SUP_FIRM)}{RNG2.choice(SUP_SUFFIX[cat])}"
            term = RNG2.choice([2, 2, 3, 3, 5])
            rem = RNG2.randint(1, term * 12)
            end_m = TODAY_M + rem
            end_y = TODAY_Y + (end_m - 1) // 12; end_m = (end_m - 1) % 12 + 1
            locked = RNG2.random() < (0.28 if "能源" in cat else 0.62)
            actual = ap / annual * 365 if annual else 0
            rows.append(OrderedDict([
                ("合同编号", f"CG-{end_y - term}-{r[:2]}-{seq[r]:03d}"),
                ("供应商名称", name), ("供应商类别", cat), ("服务区域", r),
                ("合同类型", "区域框架协议" if i == 0 else
                            "城市公司集中委托" if i < 3 else "项目单独委托"),
                ("计价方式", RNG2.choice(PRICE_MODE[cat])),
                ("合同起始日", f"{end_y - term}-{end_m:02d}-01"),
                ("合同到期日", f"{end_y}-{end_m:02d}-{calendar.monthrange(end_y, end_m)[1]:02d}"),
                ("合同期限（年）", term), ("剩余期限（月）", rem),
                ("年化合同金额（元）", annual),
                ("本年累计执行（元）", ytd),
                ("执行进度", round(ytd / annual, 4) if annual else 0),
                ("结算周期", "月结" if term_d <= 45 else "季结"),
                ("合同账期（天）", term_d),
                ("实际账期（天）", round(actual, 1)),
                ("账期偏离（天）", round(actual - term_d, 1)),
                ("期末应付余额（元）", ap),
                ("履约保证金（元）", int(round(annual * RNG2.uniform(0.02, 0.05)))),
                ("是否锁价", "是" if locked else "否"),
                ("锁价到期", f"{end_y}-{end_m:02d}" if locked else "—"),
                ("履约评价", _pick(RNG2, GRADE_W)),
                ("续约状态", "12 个月内到期，需重新招标" if rem <= 12 else
                            "24 个月内到期，跟进中" if rem <= 24 else "正常履约"),
            ]))
    return rows
PURCHASE_CONTRACTS = build_purchase_contracts()

# ============================================================
# 13. 多经与增值服务合作合同台账（160 份）
# ============================================================
RNG3 = random.Random(20270101)
VAS_ANNUAL_TOTAL = int(2.90 * YI)
VAS_YTD_FACTOR = 0.620
VAS_TYPES = OrderedDict([
    ("公区广告位及社区媒体",   (0.185, ["文化传媒有限公司","户外广告有限公司"], "收入分成")),
    ("通信基站及机房租赁",     (0.128, ["通信技术有限公司","通信塔业有限公司"], "固定租金")),
    ("新能源充电桩合作",       (0.142, ["新能源科技有限公司","充电服务有限公司"], "保底 + 分成")),
    ("智能快递柜及驿站",       (0.062, ["智能柜科技有限公司","社区物流有限公司"], "固定租金")),
    ("公共场地租赁及美陈",     (0.156, ["品牌管理有限公司","会展服务有限公司"], "按次计费")),
    ("社区团购及零售分成",     (0.118, ["供应链科技有限公司","生鲜科技有限公司"], "收入分成")),
    ("家政到家服务合作",       (0.108, ["家政服务有限公司","生活服务有限公司"], "保底 + 分成")),
    ("房屋经纪及资产管理合作",  (0.101, ["房地产经纪有限公司","资产管理有限公司"], "收入分成")),
])
VAS_FIRM = ["星驰","联合","优家","乐邻","宸悦","云图","筑家","万顺","知行","慧生活",
            "同行","新境","朴石","一方","恒美","锐达","禾风","南山"]

def build_vas_contracts():
    rows, seq = [], defaultdict(int)
    regions = list(REGIONS)
    reg_w = {r: REGPL_YTD[r]["rev"] / sum(REGPL_YTD[x]["rev"] for x in REGIONS) for r in regions}
    for typ, (share, sufs, mode) in VAS_TYPES.items():
        t_annual = int(round(VAS_ANNUAL_TOTAL * share))
        t_ytd = int(round(t_annual * VAS_YTD_FACTOR))
        cells = [(r, i) for r in regions for i in range(4)]
        wts = [reg_w[r] * (1.60 if i == 0 else 1.05 if i == 1 else 0.75) for r, i in cells]
        wts = [w / sum(wts) for w in wts]
        acc = defaultdict(int)
        for j, ((r, i), w) in enumerate(zip(cells, wts)):
            last = (j == len(cells) - 1)
            def take(key, total):
                if last: return total - acc[key]
                v = int(round(total * w)); acc[key] += v; return v
            annual, ytd = take("a", t_annual), take("y", t_ytd)
            seq[r] += 1
            term = RNG3.choice([1, 2, 3, 3, 5])
            rem = RNG3.randint(1, term * 12)
            end_m = TODAY_M + rem
            end_y = TODAY_Y + (end_m - 1) // 12; end_m = (end_m - 1) % 12 + 1
            rows.append(OrderedDict([
                ("合同编号", f"DJ-{end_y - term}-{r[:2]}-{seq[r]:03d}"),
                ("合作方名称", f"{RNG3.choice(CITY_NAMES[r])}{RNG3.choice(VAS_FIRM)}{RNG3.choice(sufs)}"),
                ("业务类型", typ), ("区域", r),
                ("覆盖项目数", max(1, int(round(annual / RNG3.uniform(180_000, 620_000))))),
                ("分成模式", mode),
                ("分成比例 / 单价", ("公司分成 %d%%" % RNG3.randint(28, 62)) if mode == "收入分成"
                    else ("保底 %.0f 万元 + 超额分成 %d%%" % (annual/WAN*RNG3.uniform(0.45,0.72), RNG3.randint(20,45)))
                        if mode == "保底 + 分成"
                    else ("固定年租金 %.0f 万元" % (annual/WAN)) if mode == "固定租金"
                    else "按场次计价"),
                ("合同起始日", f"{end_y - term}-{end_m:02d}-01"),
                ("合同到期日", f"{end_y}-{end_m:02d}-{calendar.monthrange(end_y, end_m)[1]:02d}"),
                ("合同期限（年）", term), ("剩余期限（月）", rem),
                ("年化合同金额（元）", annual),
                ("本年确认收入（元）", ytd),
                ("确认进度", round(ytd / annual, 4) if annual else 0),
                ("结算方式", RNG3.choice(["月结","季结","半年结"])),
                ("业主共有收益分成", "是（计入公共收益，不确认收入）"
                    if typ in ("公区广告位及社区媒体","通信基站及机房租赁","智能快递柜及驿站")
                       and RNG3.random() < 0.42 else "否（公司自营收益）"),
                ("续约状态", "12 个月内到期，待重谈" if rem <= 12 else
                            "24 个月内到期，跟进中" if rem <= 24 else "正常履约"),
            ]))
    return rows
VAS_CONTRACTS = build_vas_contracts()
