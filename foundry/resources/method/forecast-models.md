# 差异、现金与预测模型方法

版本：finance-methods-20261023。支持范围见 [support-matrix.json](support-matrix.json)，
检查口径见 [model-checks.md](model-checks.md)。本资源中的示例不是自动启用的新计算能力。
只调用当前 schema 中可用且在相应范围验证过的模式；一般 driver 算术结果不能自动取得专业金额证据资格。

## F06 预算与经营驱动差异

输入需同实体、期间、科目、单位、税基础；预算/实际均绑定来源，先建立金额控制总额。
已有两因素按明确顺序保留交互分配，数量贡献与经营原因分开。三因素固定顺序量→结构→价：

```text
量差 = (Va - Vb) × Σ(mb_i × pb_i)
结构差 = Va × Σ((ma_i - mb_i) × pb_i)
价差 = Va × Σ(ma_i × (pa_i - pb_i))
总差 = Va × Σ(ma_i × pa_i) - Vb × Σ(mb_i × pb_i)
```

预算V100、价格10/20、结构.5/.5；实际V120、价格12/18、结构.6/.4：贡献300、−120、48，总差228。
数量单位须可合计、产品价格和可比集合完整。负退货、全零量、新产品缺基期价必须走已验证限制或明确可比子集，不能猜价或把残差当结构差。
输出闭合桥、范围、逐项来源、重大抵消、未证实业务原因与验证动作；零预算不输出无定义百分比。

## F08 13周资金与压力测试

输入：可用期初现金及受限调节、预计回款日期和依据、工资/经营付款、税款、资本开支、债务本息、已承诺融资、币种及预测版本。
先调节账面现金和可用现金；同一内部转账不在总体双计，不同币种没有转换依据不能直接相加。

1. 将现金事件分配到正确日期/周，收入确认、发票和收款分别处理，禁止重复计入。
2. 每周期初＋收−支±适用汇兑＝期末，保留负余额；融资未承诺不能自动补齐缺口。
3. 分别测试回款延迟、费用上升、受限资金和下行情景。每个假设有来源或责任角色、有效日期、确认状态；不会修改历史实际。
4. 输出最低余额、首次短缺周、资金缺口及行动。只有周末汇总的工具不能证明周内安全，必要时补日期级底稿；不能把未做检查标通过。

反例：账面现金100、受限30、收20付100，则可用期末−10。经营筛查公式1−毛利率＋费用率不能替代此现金桥；70%筛查阈值下仍可因capex出现−50现金。

## F09 驱动预测与附表

最低输入：实际截止期、预测期间、数量/价格/面积、履约时点、人员与薪酬、成本费用、季节性及假设来源。保留客户模板，输入与派生公式分开，不用硬编码覆盖结果。

先检查DAG引用和无环，再核对财务定义：收入量价并处理履约；headcount/FTE/paid FTE和到离职日期分清；固定/变动/一次性成本分开；月薪不再次除12，年薪不当月薪。
固定资产成本120、残值0、12个月寿命、7月在用：若已确认7月起整月折旧，12月累计60；若已确认8月开始，累计50。缺起算政策就列缺口，不能仅看在用日猜政策。

可信输入须由后端解析 alias、source locator、范围、期间、单位和来源版本；模型不能手填 source_rows 或自报语义获得授信。直接假设保留其独立身份和有效确认。输出绑定已登记的指标/报表行，不能把任意 driver 名称改成利润、现金或应收事实。
履约定性说明以同一合同、预测期间和场景的明确来源设定为准；预测内设为已履约不等于现实已经发生，缺失、混合或部分履约状态不反推待履约，也不从收款金额推定履约。
实际月份冻结；非负流量年度目标低于已发生实际时解释冲突，不静默生成负预测。输出基础/下行情景、驱动附表、输入缺口、检查与来源。

## F10 三表联动

最低输入：经核对的期初BS、经营驱动、收付时点、capex/折旧、债务本息、税费、股利/权益、现金定义及适用用途。
顺序：经营预测 → 营运资本/PPE/债务/权益滚动 → 利润表 → 现金流 → BS → 勾稽/扰动。先支持明确的不循环模型；循环利息或现金扫款未支持时返回限制，不启用不透明迭代。

固定管理算例（无税息、无股利）：期初cash100、AR50、PPE200、AP50、debt100、equity200；当期收入120、收款100、费用60、现金付费50、折旧10、capex40、还本20。

| 结果 | 金额 |
| --- | --- |
| 净利 / CFO / CFI / CFF | 50 / 50 / −40 / −20 |
| 期末cash / AR / PPE | 90 / 70 / 230 |
| 期末AP / debt / equity | 60 / 80 / 250 |
| 资产 / 负债＋权益 | 390 / 390 |

检查：A=L+E；期初cash＋三类流量＋FX＝期末cash；成本/累计折旧/净PPE、债务、本金/利息、留存收益/OCI各自调节。BS现金与现金流范围不一致时列调节。不得插入现金、权益或“其他”凑平。

关系测试：额外收回旧AR10，仅cash＋10/AR−10，净利和权益不变；已履约新现金销售10且无额外成本税费，则cash/净利/权益各＋10。仅跑基础平衡不能替代这两种扰动。
更新下一期保留历史实际和原来源，生成后继版本，不移动期初值掩盖差异。

管理间接法桥不是CAS法定直接法报表；完整合并、租赁、递延税、金融工具和未声明循环不因三表算平而获支持。
导出Excel后，只有记录实际目标引擎/版本、重算时间、基础和情景结果才能称重算验证；无目标引擎时明确未验证，不以公式缓存代替。


## Registered management-template authority

`linked_three_statement_management_v1` requires sixteen explicit source-bound inputs and eight zero-effect boundary bindings. A source row declaring zero is a forecast assumption, not proof that no historical transaction exists. The manager first confirms the reporting profile, then previews and separately approves all eight boundaries for the exact saved scenario and archived source hashes. The ordinary profile confirmation does not approve model boundaries. Requirements bind both `template_id` and `scenario_id`; absent or revoked approval leaves results readable but ineligible as professional amount evidence. A repeated approval cannot revive an older approval after the latest is revoked.

The current template is limited to one entity, currency, ledger/scenario and monthly period. It does not bridge differently labelled actual and forecast scenarios. Tax, interest, VAT, inventory movement, FX, OCI, noncash investing/financing and other balance-sheet effects must fit the declared zero boundaries; unsupported effects require an explicit unsupported/input-gap result. A cash shortfall is a business alert and remains reportable when the arithmetic and source checks pass.
