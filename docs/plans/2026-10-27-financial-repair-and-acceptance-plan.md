# 0.15.0-beta.1 之后的财务修复与验收方案

日期：2026-10-27。状态：待实施方案；本文只整理证据、实施边界和验收安排，没有实施产品修复或启动模型。

**0.15.0-beta.1 是阶段版本，尚未完成财务验收。** 安装包、签名、公证和发布验证属于软件交付；确定性工程验证、真实模型结果和具名财务人员签收分别记录。发布阶段版本不会使后面三项自动成立。E01 的新写入哈希修复目前仅存在于独立验证过的 shadow 提案，不能写成阶段版本已经修复。

本方案的目标是让后续工作可以逐项实施、复核和停止，并最终形成可信的能力声明。所有“通过”均由实际证据决定；工期、修复方案和已通过的局部测试都不构成预期通过承诺。

## 1. 当前事实与证据账本

本文的 N3 指 `build/verification/finance-goal-closure-20261026/`；R2、R3 分别指其 `final-r2/`、`final-r3/`。文末列出可追溯的文件及 SHA-256。

| 事项 | 当前可确认结果 | 不能据此声称 |
| --- | --- | --- |
| R3 原 283 slot | 19 个启动：7 个正常返回、8 个到 420 秒截止、4 个受控中止；264 个未启动。原分母中机械通过 3、失败 4、未验证 276 | 完整 283 已运行；19 个全部正常完成；276 个全部是模型失败 |
| R3 通过 | E03--base 三次；均匹配原 Pro 模型，原模型机械信用 3，兼容通过 0 | 财务专业验收通过；其他 E03 变体通过 |
| R3 失败 | E01--base 三次；E02--zero_actual_volume 第三次（r012） | 将 r012 算作 420 秒强杀，或未经诊断就归为与其他 E02 相同根因 |
| r012 的独立诊断 | 外层 418.768 秒正常返回，退出码 1；`numeric_errors=[]`；workflow 报 run 未绑定当前 semantic sources；四次计算存在 `resource_not_read_before_calculation:method-resource`；deterministic 为 `verification_incomplete`。22 次工具启动、20 次模型启动，最终可见 receipt 为 awaiting_manager | 数值正确就通过；把正常返回失败改算超时；把方法事后补读算作事前遵循 |
| R3 停止与保全 | 控制器已停止，已观察的受管进程退出；私有运行 home 删除，全局 provider 设置不变，外部运行时前后哈希匹配 | R3 达到了原覆盖率、完成率或专业质量门槛 |
| 原 283 的专业复核 | 283 首评 + 高风险 72 复评 = 355 个 AI 预筛记录身份已准备；正式专业验收未建立，18 个原 slot 的适用维度歧义仍未裁决 | 355 个评分已完成；AI 填写人类评分或签字栏 |
| R2 原 mutation 聚合 | 4 detected、6 control_not_accepted、M09 harness_error，聚合失败；M07/M08 的未复核合法对照尚非 complete | 没有 escape 就等于 11 类通过；非法例一律拒绝就是好评分器 |
| R2 补充案例 | 原文字面执行 5/11 通过；六个后续审批扩展在其范围内通过 | 扩展覆盖原失败、获得原 283 分数或代表完整三表能力 |
| R2 27 个确定性身份 | 21 passed_bounded、5 partial、1 unverified；模型信用 0 | 27 全部通过；K01–K24 整项已验收 |
| E01 shadow | 新写入十字段方案通过有路径绑定的工程验证及独立审查，旧十一字段历史保持不变 | 已合入根源码、已打包，或三次原 E01 模型失败已改为通过 |

R3 精确汇总来自 [actual-results.json](../../build/verification/finance-goal-closure-20261026/final-r3/actual-results.json) 和 [execution-finished.json](../../build/verification/finance-goal-closure-20261026/final-r3/execution-finished.json)。`recorded_original_slots=7` 是收集器记录到正常返回结果的口径，不等于只启动了 7 个。报告同时保留执行状态、机械判定、合法工作流和专业质量四个层次，不直接把字段名 `deadline_violations` 中的非成功退出等条目都解释成真正的 420 秒超时。

发布流程的新验证为 43 项聚焦测试、1548 项前端测试通过；它们属于软件发布证据，不代替财务验收。R2 的全仓 6879 通过、2 失败仍作为历史原结果保留。`8ebb8e3` 的完整 CI 与安装包/公证最终状态按发布收据另行报告，不能用旧失败或较小测试集代替该次完整 CI 结论。

## 2. 不变项与证据分账

1. **原合同保留原样。** 原公开输入、私有 oracle、两套 Python 评分器、阈值、75 个专业模型变体的三次独立重复、58 个旧 slot、27 个确定性身份及保护清单均不改。新实现必须先面对原输入；缺数据的情况继续明示缺口。
2. **真实模型预算保留原样。** 后续新候选仍按 225 个 `deepseek-v4-pro / high` 专业 slot、58 个 `deepseek-v4-flash / max` 旧 slot，provider 为 `deepseek-official`；每 slot 外层 420 秒、80 次真实工具启动、最多 2 次内部修复、0 次外部重试、并发 4。不用更换模型、放宽时间、精选最佳重复或重命名超时来取得通过。
3. **历史不重写。** R1/R2/R3、失败运行、第一次错误探针、受控中止、未启动、旧十/十一字段草稿及回执、审批及撤销事件、原导出全部保留。后续候选及证据使用新目录、新 manifest、新 run identity，不回填旧分数。
4. **运行端与评分端隔离。** 工程诊断只读获准公开投影；不把 oracle、旧答案或整个原始会话送进运行端或模型提示词。评分进程的授权读取与模型侧工具拒绝需要分别实证。
5. **不补造事实或授权。** 不为缺失基期价格填 0，不替财务人员确认新增字段，不以现金流入替代收入确认，不虚构银行交易、月份权重、税基或融资，不让模型通过自称 manager 获得权限。

每个新证据包强制标明下列类别、候选 hash、输入 hash、实际接口、观察器 hash、历史保全结果和适用范围：

| 账本 | 内容 | 计分规则 |
| --- | --- | --- |
| A：原合同验收 | 原输入、原工具/评分器、原模型和固定分母的新候选运行 | 只按原规则记该候选分数，保留所有 attempt；局部回放不能替代真实模型 |
| B：兼容与工程回归 | 十/十一字段历史读取、7/11 字段审批兼容、API/CLI、篡改和缓存回放测试 | 模型信用 0；原失败不改写；只有自身范围的工程结论 |
| C：补充能力 | 新登记接口、完整管理三表输入、银行时点资料、来源覆盖声明、未来新未见集 | 先独立版本化和冻结；不把新增输入偷偷合入 A；各自报告分母 |

原字面 mutation 合法对照若仅授权七个字段、当前计算确需十一个字段，保持拒绝是必要的安全行为。能否在原授权内完成，需要证明；没有证明就保留原聚合失败。新的十一字段真实授权可验证 B/C 的完整闭环，却不能宣称原字面合同已经通过。若未来确需调整验收合同，必须另立版本和评审，不能修改当前被冻结的历史合同。

## 3. 工作顺序与阶段门

| 阶段 | 工作及依赖 | 退出条件（DoD） | 不满足时 |
| --- | --- | --- | --- |
| G0 阶段发布封存 | 绑定 0.15.0-beta.1 源码、安装包及发布证据；附 R3 停止和结果账本 | 发布说明明确未完成财务验收；历史 manifest 可重算；残留进程及私有凭据目录清理有收据 | 只更正交付事实，不追加“财务已验收”声明 |
| G1 工程推进门 | WP1 E01；WP2 E02；WP3 审批闭环。共享 `analysis.py` / `finance_explanations.py` 区域需串行整合 | 每个修复先红后绿；相关完整套件实际运行。除独立认定并隔离登记的原 M02/M06 冻结契约冲突外，其余检查通过；权限/历史负例成立、无新增或扩大失败 | 新增/扩大失败阻断推进；既有冲突仍 failed，不能改 xfail/skip、改测试或授予原验收 |
| G2 语义与覆盖证据 | WP4 mutation/补充；WP5 六个剩余确定性身份；WP6 三表/K | 原合同结果与扩展结果分账；所有缺口可追溯；拟承诺能力每项正、负、边界、适用缺口齐全 | 未实现项仍 partial/unverified/unsupported，不能靠删案例解除门禁 |
| G3 新候选冻结 | 已整合源码、方法、工具 schema、DSH、外部运行时；运行/评分隔离、所有权清理及旧数据保护；列出未关闭契约冲突 | writer-stop；全文件 manifest；本候选 fresh 完整回归；在查看对应候选输出前冻结 review schema、applicability/critical 映射及未决清单；真实拒读无泄漏、路由/预算一致、独立审查通过。仅准许 development 验证 | 未知新增失败阻断；不边跑边改候选；历史全套不替代新套件；G1 的例外不能迁移成 acceptance_passed |
| G4 原身份的新 development 批次 | 仅对通过 G3 的新候选；不能继续使用已封存的 R3 目录；正式范围为原 283，若只验证部分修复范围须事前列明，其余记未启动 | 开发阶段保留全部身份及终态；原验收必须逐 slot 实际启动/执行覆盖 283/283，另满足 ≥95% 合法工作流完成率。283 行身份报告本身不等于覆盖 | 任何安全/权限泄漏立即受控停止；停止只形成开发阶段结果。未启动/缺失继续占原分母并阻断原验收，不选择性重跑 |
| G5 专业复核与未见集 | WP7；人审可提前准备，但实际产物评分绑定 G4 的候选和输出 | 355 个 AI 预筛记录身份闭合，18 歧义裁决；两人具名校准/评分/裁决完成；独立未见 20 受控验收 | 维持开发验证/阶段版，不能以无人可审为理由替代签收 |
| G6 专业发布与交付 | G1–G5 达标并达到原冻结阈值；再验证真实安装/导出表面 | 签收范围、局限、模型结果、人审、包 hash 对齐；发布资产下载核验与回退方案可用 | 发布状态仍为受限 beta；产品和财务签收分别陈述 |

G1 的三个工作包可以拆分研究与测试设计；WP2–WP6 共享的 `foundry/analysis.py`、`foundry/finance_explanations.py`、`foundry/finance_service.py`、`foundry/finance_professional.py` 及语义/交付镜像由单一整合者顺序应用。独立研究、复现和互不冲突的测试设计可以并行，不能多人同时改共享资格判据。G5 的保管人招募、校准样本和评审安排可并行准备，不能提前填写未产生的实际评分。

**工程推进与原合同验收是两个门。** G1 的隔离账本只能登记已证明的原 M02/M06 七/十一字段授权前提冲突，逐项绑定原测试身份、原失败日志/hash、七字段真实批准、十一字段规则依赖、独立认定及新十一字段合法对照/负例结果；原测试继续执行并保留 failed。其他失败不得塞进该例外，失效范围扩大或新增回归立即阻断工程推进。如此可验证其余已修范围，避免“保持原失败”和“所有测试必须绿”互相矛盾；但正式专业发布仍受完整原合同门槛约束，未解决的原冲突仍阻断验收。

## 4. WP1 / P0：E01 新写入 content_hash 与历史兼容

**已证实的问题。** 新草稿的 `content_hash` 生产端纳入 `required_check_authorship` 后形成十一字段，而冻结合法工作流校验仍按原十字段。三次 E01 的完整 `_integrity_hash` 均有效；公开运行链的要求、引用、残差、回执及操作检查在该诊断范围内有效。此处不是凭证主体被篡改，也不是七/十一审批字段问题。

**实施文件。** `foundry/analysis.py` 的保存草稿 content hash 构造处；配套测试落在 `tests/test_finance_required_check_authorship.py`、`tests/test_finance_native_drafts.py`、`tests/test_finance_completion_operations.py`、`tests/test_finance_saved_delivery.py`，历史兼容样本单独保管。冻结 `tools/finance_professional_eval.py` 及其他受保护评分代码不改。

**步骤。**

1. 在新的开发候选中复核 shadow 精确补丁与根实现的差异，只采用“新草稿 content_hash 不纳入可选 authorship 元数据”的窄改动。先运行三个绑定当前实现的红例，确认没有误导入 editable install 或根目录。
2. 保留服务端生成的 authorship 字段及完整记录 `_integrity_hash`，继续校验 fact ID、run/output hash、残差必需项、来源、草稿 ID 和回执链。沿用 policy 16；无独立证据不增加策略版本或做全量迁移。
3. 新保存/显式新修订生成十字段 hash 与自己的回执；旧十一字段草稿的读取、同请求重试、manager refresh、settled operation 和已有导出保持原字节/身份。需要新合同输出时只通过显式新修订创建，不暗改旧草稿。
4. 整合后执行完整草稿、解释、required checks、completion、saved delivery、export 相关套件，并通过新候选公开 CLI 保存真实新草稿，调用未改的冻结工作流校验。

**输入/输出与 DoD。** 输入为三个公开 E01 请求投影、真实旧十一字段任务副本及合成篡改对照；输出为新十字段草稿/回执、旧字节比对、未改评分器的实际结果、整合源码 hash。独立 shadow 的 13 个 API 对照与 2 个历史测试可作设计依据；它们不能替代整合后执行，也不能与作者的 15/7 测试简单相加称无重叠独立用例。

**必须接受的正例。** 新 managed/prepared/direct/revision 各合法路径；直接旧接口原本没有 authorship 的合法路径仍可用；两个内容相同但 draft ID 不同的草稿各自有正确回执；旧数据正常读取与导出重用。

**必须拒绝的负例。** 用户注入 authorship、改 body/claim/hash/receipt、漏零残差、用 revision 洗掉必需检查、错 run/source、同内容 hash 偷换另一 draft 回执、settlement 不一致。authorship 磁盘改写仍应被真实读取器/语义检查发现。完整记录 checksum 不是对任意可信磁盘写入者的密码学签名；不扩大现有威胁模型的承诺。

**历史结果。** 三次 R3 E01 失败保持失败，旧十一字段草稿对原十字段校验的不兼容保持如实披露；后续新候选才获得自己的结果。

## 5. WP2 / P0：E02 的范围证明、引用、单位和结束流程

### 5.1 原生 P/Q 范围冲突

四个已诊断 slot（r004–r007）的公开证据显示：来源 bindings 同时保留 `price_quantity` 和 `public_facts`。预检允许 P/Q 路由，实际桥计算和专用 P/Q 匹配通过，但通用比较范围 `_bound_scopes_match` 因候选 scope 数量不等于一拒绝覆盖，导致 requirement 仍 pending。不能通过删掉 `public_facts` 绕过这一检查；方法要求保留原始来源绑定。

**拟修改范围。** `foundry/finance_requirements.py` 的 `_bound_scopes_match` 调用链、`_price_quantity_requirement_matches`、对应 support 诊断；必要时 `foundry/finance_requirement_support.py`。`foundry/finance_service.py` 和 `foundry/finance_variance.py` 先作为实际行过滤/桥证明的读取依据，避免无证据改算法。

**实现顺序。** 先构造与公开投影等价的最小双 alias 红例；引入只适用于原生 P/Q 的范围证明，必须绑定实际参与 actual/budget scenario 的 source rows、comparison、产品 grain、期间、实体、币种/单位和来源 hash。所有相关绑定需要一致；仅旁证且未参与计算的来源不能制造虚假的 comparison 冲突，也不能被丢弃。通用多 scope 歧义仍拒绝。预检、保存覆盖和重新验证共用同一资格判据，并给出具体冲突字段/来源，不以笼统“无引用行”掩盖真实原因。

**DoD。** 双 alias 的合法 A/B 行按实际原生输出满足相应 obligation；更换参与计算的 scope/来源、错期间、错实体、错 scenario、丢产品、重复产品或错币种仍失败。正例接受不导致未回答的另一产品自动完成；未定义值保持非数值/缺口状态。

### 5.2 缺失基价和零销量是不同输入

| 原公开输入分支 | 已观察/应保留的业务边界 | 未来验证 |
| --- | --- | --- |
| new_product | A 可计算；B 基期价格缺失，原生给 `price_quantity_missing`，没有 B 的完整桥行 | 明确 B 的真实缺口及受影响结论；不能填 0 基价、删 B 或把 A 的闭合当全问题完成 |
| priced_product | B 基期数量为 0、基价明确 12；原生已有 B 的来源绑定桥 | B 可计算；缺基价与零基期数量不混同，保留 B 的全部必需成员和残差 |
| zero_actual_volume | 原始身份单独回归；r012 数值无错误，但当前语义来源绑定、事前方法读取和完整验证未闭合 | 0 销量不构造无意义单价/比率，不把未定义当 0；先读全资源再计算，来源/requirements 变更后必须重算并绑定当前链 |

### 5.3 引用与单位

四个诊断 slot 有完整桥 fact 引用，但还出现裸数字、quantity/amount 同值碰撞与背景段落引用问题。数量单位“件”不在所有公开输入中明确给出；这些提示不能一概标为误报。r006 的第一次保存引用不存在的背景第 3 段，拒绝合理；随后的合法保存不能抹掉这次失败。

**拟修改范围。** `foundry/finance_explanations.py` 的 fact 语义、单位/数字 span 与 claim 校验；`foundry/finance_native_drafts.py` 的 P/Q 可用模板；`foundry/analysis.py` 的 source claim 验证仅在已证实边界需要时改。复用 `tests/test_finance_native_requirement_routes.py`、`tests/test_finance_requirement_semantics.py`、`tests/test_finance_model_check_claims.py`、`tests/test_finance_explanations.py`。

**方案。** 为已登记原生 P/Q 输出提供 typed fact/模板，使价格、数量、金额、比例各自绑定列及单位，使用 fact identity + 正文位置匹配，不能只按“数值相等”找来源。输入没给数量单位时保留未知或原始表达，不默认件。原始 q/p、价格×数量和汇总差额需要可追溯的来源/派生 claim；不关闭数字、单位或来源检查，也不把任意正文数字当结构计数。保存前的公开诊断要指出具体段落、数值和允许引用形态。

**正负例。** 同一数值同时表示数量 10、价格 10 和金额 10 时，正确列/单位分别通过；把数量写成金额、把元换成万元、伪造数量单位、错 source row/段落、把未引用的 60 或 +70 混入结论均被发现。只修复可复现的错误匹配，合理拒绝保留。

**语义版本、旧稿视图与严格交付的耦合。** typed fact/单位或当前资格的含义若变化，必须同时审查 `foundry/finance_claim_semantics.py` 的 `CLAIM_SEMANTICS_VERSION`、`foundry/finance_explanation_views.py` 的旧稿当前视图、`foundry/finance_delivery_verification.py` 的服务端证明、`dsh-plugin/final-delivery-runtime.js` 及 `foundry/resources/dsh-plugin/final-delivery-runtime.js` 镜像。当前 Python 版本和 JavaScript 严格检查均为 19；未来是否升版须由行为差异决定，不能只改一侧数字、取消相等校验或把旧证明静默当当前证明。

按同一候选整体实现：保留旧稿存储字节和原 epoch；当前读取/重验证适用新的语义判断；新证明绑定当前 epoch、草稿/运行/来源/请求身份；JavaScript 只接受对应版本且完整的服务端证明，错误或缺失 epoch 均 fail closed。兼容策略必须明确哪些旧稿可读、哪些需要重验证、新修订或受限交付，不能靠刷新历史缓存绕过。

额外回归覆盖 `tests/test_finance_fact_token_units.py`、`tests/test_finance_claim_semantics.py`、`tests/test_finance_runtime_repair_view.py`、`tests/test_finance_delivery_verification.py`、`tests/test_finance_public_eligibility_claims.py`、`tests/test_finance_public_eligibility_runtime.py`、`tests/test_finance_final_delivery_runtime.py` 及实际 JS 严格 runtime。正例包括正确 typed token、旧 epoch 草稿按当前语义重读且旧 bytes 不变、新证明正常交付；负例包括错误单位/同值异义、旧/缺失/未来 epoch、改 source/run/draft/request、伪造已验证状态。源码与打包镜像一致性需单列检查；仅 Python 测试通过不足以关闭此项。

### 5.4 420 秒模型尾部

在已诊断四个 slot 中，14/14/14/15 次工具调用全部结束，总工具耗时约 4.8–5.9 秒，单次最大不超过 1.757 秒。主模型可见完成区间累计约 203–389 秒；成功保存草稿后仍有模型等待，其中 r007 又调用准备工具。证据支持优先处理确定性阻断、过大返回和重复结束流程；不支持把这四次归咎于慢工具，也不能从公开投影区分 provider 网络与私有推理耗时。

**实施范围与顺序。** 先做 5.1–5.3，使模型有正确且可完成的工具路径；再检查 `foundry/finance_explanations.py::prepare_explanation`、`foundry/finance_service.py` 的 save/recover/settle，以及 `foundry/finance_completion_operations.py` 和现有运行结束链。复用已有 prepared template、保存和完成操作，不增加第二套“完成”状态。只有后端真正 complete 且交付绑定校验通过才结束；合法输入缺口则由后端证实为相应受限终态。

幂等和并发直接复用 `tests/test_finance_completion_operations.py` 等现有完成操作测试：同 call/同 payload 重试只返回同一合法记录；同 call 改 payload 冲突拒绝；并发保存/settle 不产生双重回执；deadline 关闭之后不得借重试新开保存、重置截止或冒称当前 complete。已 settled 的同 call 重放和受权 manager recovery 沿用现有分支及 `tests/test_finance_saved_delivery.py` 的兼容约束；例如超时后的既有回执可按原规则重放，当前操作状态仍为 timed_out，历史回执不能冒充当前授权。补齐这些实际行为对照，不另建幂等框架或绕开既有锁/操作身份，也不放宽 deadline。

可评估减少工具返回中的重复全文、重复 facts、再次 prepare 的诱因，但必须保留可追溯引用、全部错误和必要修复信息；只在证明等价后修改返回 schema/方法资源并重新冻结候选。不能把返回信息偷偷移出 80 工具预算、提前停止尚未完成的流程或扩大 420 秒。保存后减少无必要的模型往返是待验证的工程假设，不是速度承诺。

**DoD。** 无模型回放首先证明保存、恢复、settle、交付一致性及错误可修复性；新增工具契约有兼容验证。后续原模型新候选运行分别记录主模型区间、工具耗时、保存到终态耗时、输出大小、请求/token/费用可见性及首次失败。不能以平均耗时掩盖任一 slot 超限；当前未知 usage/cost 仍写 unknown。

r012 另加两个决定性回归：正确 native skill 及该案例规定的全部 `method-resource` 成功返回后，计算才开始；同一调用 ID、会话、资源 hash 和时间顺序可核查。第二个回归在来源或 requirements 语义变化后拒绝旧 run，并要求新的计算、草稿和回执全链绑定当前语义。文档已经要求方法先行，修复重点是实际执行与工具提示/结束链一致，不能修改冻结 observer 把迟读放行。

## 6. WP3 / P0：七/十一字段审批与 M02/M06 闭环

**现状。** `tools/verify_finance_mutation_pipeline.py` 的原合法对照只确认七个 `BASE_FIELDS`；当前 `driver.source_binding` 与 `statements.linked_management` 要求 `BASE_FIELDS | STANDARD_FIELDS`。七项为 purpose、期间起止、功能币、列报币、列报单位、entity_scope；新增四项为 basis、basis_version、fiscal_year_start、early_adoption。相同值存在于 profile 不等于它们已被有权人确认。

**实施文件。** `foundry/finance_professional.py` 的 `profile_confirmation` / `rule_identity` / 模型边界资格；`foundry/finance_service.py::finance_profile_confirm`；公开 CLI/MCP 的字段展示和校验位于 `foundry/finance_cli.py`、`foundry/finance_mcp.py`。测试复用 `tests/test_finance_profile_dependency_closure.py`、`tests/test_finance_professional_protocol.py`、`tests/test_finance_template_requirement_identity.py`、`tests/test_finance_m05_completion_closure.py`。

**实施步骤。**

1. 将“已批准字段、当前规则所需字段、缺失字段、对应当前值、当前审批 basis”完整返回，让真实 manager 能看清差额；缺四项时维持 awaiting_profile_confirmation。
2. 保留旧七字段审批、其回执及历史运行。由真实 manager 经现有公开确认接口提交当前确切值和适用范围，创建新的十一字段确认事件；不自动填齐 confirmed_fields、不把字段存在解释为授权。
3. 新审批必须绑定 task、source hashes、bindings、scopes、相关 profile 值；三表还需要独立完整 model boundary 确认。变化后创建当前 requirements/run/draft；不能复用失效旧 run 伪装新批准。
4. 每次验证分别执行“合法对照完整通过”和“仅一个语义破坏的 mutant 被拒”。M02 使用真实不存在/错行引用；M06 使用缺 run/claims 且自称 complete 的草稿。最终必须通过当前 CLI view 和重新验证确认，不能仅查看写入成功或历史记录字段。
5. 原 mutation 工具及原聚合继续原样执行并保留失败。十一字段扩展放在独立版本化 runner/证据目录，结果标 B，避免通过改冻结 bootstrap、放宽资格或改原 observer 得到假兼容。

**DoD。** 新十一字段真实审批、完整边界、完整来源下合法对照达到真实 complete；M02/M06 错误仍拒；缺一字段、值变化、范围扩展、换来源、跨任务、旧审批引用、assistant 伪称 manager、撤销审批全部不能获得资格。撤销后的当前资格丢失但历史记录字节不变；未依赖相关字段的规则不被全局误伤。

**未决点。** 若现有确认接口只允许单事件覆盖全部所需字段，先沿用其语义；不得自行合并来自不同 basis 的多个局部批准。对旧七字段历史的读取兼容，不等于在今日十一字段规则下具有新执行资格。原合同聚合能否合法通过须另出结论，不能许诺修复后必绿。

## 7. WP4 / P1：11 类 mutation、M09 与补充案例

**文件与接口。** 保留原 `tools/verify_finance_mutation_pipeline.py`、`tools/verify_finance_supplement_pipeline.py`、`tools/verify_finance_transaction_review_pipeline.py` 及其观察器字节；产品修复按证据定位到 `foundry/finance_transaction_checks.py`、`foundry/finance_transaction_reviews.py`、`foundry/finance_professional.py`、`foundry/finance_completion.py`。扩展 runner 是另立的工程材料，不能改变冻结原控制程序。

| 家族 | 合法对照必须成立 | mutant 必须被检出 |
| --- | --- | --- |
| M01/M02/M03 | 登记公式、有效原始行和真实 fact 可形成可复算结论 | 改公式、断引用、伪造来源分别失败，且失败原因对应破坏点 |
| M04/M05/M06 | manager 真授权、完整必需检查含零残差、完整 requirements/receipt | assistant 越权、漏检查、自称完成均拒绝；不能只靠合成状态标签 |
| M07 | 已履约部分与剩余合同负债分开，并走实际复核链 | 预收全部作收入，即使借贷平衡仍拒 |
| M08 | 当期耗用费用与有证据的合格资产购置分别接受 | 当期费用资本化，即使三表平衡仍拒 |
| M09 | 旧 AR 回款与当期已履约现金销售各有独立来源及正确分录/三表 | 旧 AR 回款再记收入；金额、现金总额相同也不能混同 |
| M10 | 受限余额、有效解除、未来/无效解除证据分别处理 | 受限资金计入可用、尚未生效解除直接计入可用 |
| M11 | 全量、无争议子集、争议子集调节相等，范围声明清晰 | 删除争议应收后把子集冒充总体 |

M09 先保证原生基线合法完整，再执行交易复核；R2 的两条合法审计链和一条 primary mutant 是独立的 partial_pass 证据，不能代替整个 M07/M08/M09 三家族聚合。逐项保留原生候选分录、审核 basis、checklist、批准草稿 ID、撤销、同金额旧 basis 重放、重新批准和 clone 不继承的实际轨迹。发现 harness_error 时区分“控制器无法构造有效基线”和“产品错误接受业务结果”，不把前者记为已检出 mutant。

补充三表保留原 11 项结果。复跑三条正例（management-closed、old-ar-collection、fulfilled-cash-sale）及所有负例；一项边界未确认、profile 撤销、source 替换须各自使新/current 资格失效。要求当前合法对照 complete、变异拒绝、历史字节不变三者同时成立。补充只授权其声明的管理用途、输入和零边界，不扩展为完整法定报表支持。

**DoD。** 每类都有实际 CLI 调用、合法对照、单因素 mutant、重新验证、当前 receipt、独立语义计算和历史 hash；汇总显式区分 detected / escaped / control_not_accepted / harness_error。11 类全部完成所需测试才可声称 mutation 全覆盖；原聚合与扩展聚合各自保留。

## 8. WP5 / P1：27 个确定性变体的剩余六个身份

保留 R2 原矩阵及 21 个 bounded 结果。新候选须重新绑定全部 27 个确切公开身份；旧 hash 引用只能作为辅助，不称本轮重跑。六个剩余身份如下：

| 身份/现状 | 最小实施边界与文件 | 输入 → 输出 | 正例、负例与完成条件 |
| --- | --- | --- | --- |
| E10--timing_only / partial | `finance_controls.py`、`finance_transaction_checks.py`、`finance_service.py`；登记银行时点政策需独立语义设计 | 原摘要仍只能证明 950=950、差异 0；完整审批需真实银行项、账内已记录证据、截止、账户和拟调整 | 已记录在途款/未达支票不重复过账；真正未记录手续费另列。缺交易身份/截止保持缺口；不能用 signed_sum 算术冒充重复入账防护 |
| E27--basis_change / partial | `finance_professional.py`、`finance_explanations.py`、`finance_completion.py` 及实际 control/disposition/month-close 消费路径 | 同源 CAS→IFRS 的新 context/requirements → 当前资格和完成状态 | 新义务不得复用不适用旧审批；旧 receipt 绑定旧 requirements 的历史事实保留。用真正有 profile 依赖的控制测试，不能以无依赖 DSO 控制代替 |
| E27--purpose_change / partial | 同上 | 同源 management→statutory → 明示新用途支持状态、审批及当前完成边界 | statutory 不支持时明确拒绝；合法旧管理结果可读但不能宣称新法定义务完成；覆盖控制、处置和月结全链 |
| E27--tax_change / unverified | `finance_professional.py::clean_reporting_profile` 与消费税基的 typed fact/规则边界；先设计 schema 再实施 | 含税/不含税确切语义、来源、适用范围及税率资料（若计算需要） → 税基身份与选择性失效 | 当前接口连字段都不支持。不能用无关 epoch、税率变化或币种替代；未声明税基不默认；不做含税/不含税金额无来源换算 |
| E29--truncation / partial | `finance_files.py`、`workbook_health.py`、`workbook_preview.py` 及来源关系接口 | 经授权且有 hash 的 source coverage 关系、源范围 1..1000、加载范围 1..100 → 覆盖/未覆盖范围及 900 行缺口 | 来源覆盖与扫描公式上限 `truncated` 分开；无关系声明不猜总体；随机两个工作簿不自动配对；不能声称读取了未提供的 1000 行交易数据 |
| E30--target_conflict / partial | `finance_scenarios.py`、`finance_scenario_service.py`、`finance_mcp.py`、`collection_metrics.py` | 年目标 100、实际 YTD 120、剩余最低 0 → 原值 -20、不可行原因、违反下界 20 | 登记 target feasibility 检查，不把任意负 driver 全禁，也不钳成 0。月度分配另需截止/月数/权重；原事实足够判断矛盾，不够生成月分配 |

E27 的 R2“旧 receipt 应立即 invalidated”断言失败必须保留。已知旧 receipt 仍绑定旧 requirements，新 requirements 保存未完成，独立四次 `validate-explanation` 对新/current 复用均 needs_attention；因此当前材料不证明“新增义务被虚假完成”。下一步补齐实际依赖路径，不把历史读取行为人为改成全局失效来迎合旧断言。

同时保留已修路径的防回归：E01 paired vector 按产品身份对齐、原行序与反序一致、高精度 Decimal 不受 ambient context 截断；E29 short copy 只提示公式异常，不认定作者错误、不自动改工作簿，保留 shared formula、行列位移、subtotal、rolling、absolute 正负例；E26 confirmed descendant 只使相关 adjusted_total 当前复用失效，pending 子项、其他 context/期间/accounts、未调整 source_total/profit 不误伤，旧 230→新 250 链历史不变。

**DoD。** 每项要么给出精确输入下的原生行为和完整适用限制，要么保留明确未验证。对于需要新输入或接口的功能，补充证据单独登记，原身份不能因新增数据而变成“同题已过”。

## 9. WP6 / P1–P2：可信计算、三表与 K01–K24

可信计算要求“来源身份 → 明确口径 → 登记计算/政策 → 有资格的事实 → 逐项交付 → 当前回执”连通。算术正确、借贷平衡、三表平衡及所有 model_checks 绿灯均是必要证据的一部分，不能独自证明收入确认、资本化、资金可用性或授权正确。

**管理三表具体工作。** 在 `foundry/finance_driver_templates.py`、`foundry/finance_scenario_service.py`、`foundry/finance_professional.py`、`foundry/finance_explanations.py` 的现有登记模板上补齐来源与语义验证。以 `tests/test_finance_three_statement.py`、`tests/test_finance_trusted_driver.py`、`tests/test_finance_statement_draft_template.py` 和原补充 CLI 为基础：

1. 绑定现有补充合同的 24 项 source/boundary bindings、8 项明确零边界、13 项输出语义及 12 项 model checks，分别核对组织、期间、币种、单位、stock/flow、statement/line、source row、模板版本和模型边界审批；不从产品输出反推期望值。
2. 独立复算现金、AR、PPE、AP、债务、权益的期初＋变动＝期末及三类现金流；存量用时点、流量用期间。跨期/YTD/TTM 不重复累计；期初必须是正确前期。
3. 保留“旧 AR 回款 +17”和“当期履约现金销售 +17”不同收入/应收路径，以及期初权益 +1 无法靠 plug 补平的负例。新增非零 FX、受限资金、融资和调整需要真实来源与单独输入版本，不能把补充合同的零假设推广到真实公司。
4. 原 E18/E19 是其给定事实下的有限管理任务；不能为原题追加注册模板/24 项输入/十一字段审批要求。原有限结论、补充完整模板和未来法定报表支持各自验收。
5. 实际 Excel 重算使用明确引擎、版本、原始公式/缓存和重算后的工作簿 hash；验证导出完整 workbook 的基线与代表性扰动。单个合成缓存证明不能授予全书可重算资格；引擎不可用则保留对应受限分支。

### 9.1 财务方法和模型检查规范本身的维护闭环

**已有基线。** 当前 `method/accounting-basis.md` 已定义 F01/F12、来源/假设/判断分离、准则/用途/期间路由、审批和交付边界；`method/model-checks.md` 已定义检查记录字段、精度及 K01–K24；`method/forecast-models.md` 已包含 P/Q、13 周资金、驱动预测、三表与扰动/换期方法；`method/close-checklist.md`、八个现有 Skill 入口、`method/support-matrix.json` 和 `foundry/method_skills.py` 已提供共享资源、支持元数据及读取白名单。`foundry/resources/method/` 是打包镜像。它们是现有实现基线，后续不从零另造一套方法或审批系统；方法写明某项检查也不证明自动执行器已经存在。

后续以四层财务语义组织方法复核，每条规则记录输入、适用条件、依据、实现位置、检查和负责人：

| 层次 | 必须回答的问题 | 方法/实现边界 |
| --- | --- | --- |
| 会计确认 | 什么业务事件、何时形成收入/费用/资产/负债？履约、收款、开票是否分开？ | accounting-basis、transaction checks/reviews；不从总额反推事件组成，不让现金到账替代履约证据 |
| 会计计量 | 用什么金额、汇率、税基、估计、折旧/减值政策？如何保持精度与来源？ | typed facts、Decimal、已确认政策与 source binding；猜测不得伪装事实，重要性不豁免错误算术 |
| 报表列报 | 哪个准则、用途、生效期间、分类、净额/毛额和披露？ | financial-statements、profile route、support matrix；管理间接桥不能称法定直接法，界面选项不等于完整准则支持 |
| 管理预测 | 什么已发生、什么预测、什么假设？输入如何传播至现金和三表？ | forecast-models、登记 driver/template、scenario；实际冻结、假设有责任/时效，未承诺融资和 plug 不得补缺口 |

**规范的具体增补与验证。** 对每个承诺的方法建立一份可执行检查表，复用现有 K 编号、结果记录和底稿：

- 单元与量纲：金额、数量、面积、人数、单价、比例、天数分别校验，乘除后的维度与输出一致；同值异义不能互相引用。单位转换保留因子、来源和仅转换一次的证明。
- 符号与时间：收入/费用原值与利润影响方向分开；借贷、现金流方向不靠文字猜测；时点存量、期间流量、累计转单月、YTD/TTM、实际/预测截止逐项可重建。
- 三表勾稽与压力敏感性：先逐项滚动再总量平衡；基础/下行/极端但合法边界分别扰动；现金时点风险不被期末正余额掩盖；验证只影响正确路径及下一期传播。
- 独立重算：先用不导入产品计算实现的独立算术验证，再以实际目标工作簿引擎重算；比较预期、实际和差异。等式检查默认零容差；阈值检查 pass 可以有非零差异，不能统一表述“所有差异为零”。
- 来源与审批：来源 hash/定位/范围、全部总体与排除项、规则版本、当前资格、真实确认人及审批 basis 分别检查；输出文本、明细 checks、quality、receipt、月结和实际交付须一致。

**官方参考更新流程。** 本轮没有新增外部核查。依据本地 [2026-10-23 方法审查](../finance/financial-skills-upgrade-review-20261023.md) 的既有快照规划下一轮核对：Anthropic `knowledge-work-plugins/finance` 的记录版本为 1.3.0/commit `33d3dea41a341b341d4f5da2e8801ae0c89be2b8`，`financial-services` 为 `574ed3624aebd0418c7e96cd101262f30210ab26`；OpenAI 本地 spreadsheets 记录版本为 `26.1020.11348`。这些是当时记录，不声称今天最新，也不声称已重新访问官方页面。

未来更新依次执行：

1. 从已记录的官方入口重新读取具体 commit/版本、日期、授权与变更内容；保留原文位置和 hash。官方通用提示只是方法参考，不替代适用会计准则或财务人员判断，也不自动带来 ERP/数据连接。
2. 创建“上游变化 → Foundry 四层语义 → F/K 方法编号 → 受影响规则/工具 → 正负例 → 支持声明”的变更映射。Claude 的 close-management/audit-xls/gl-recon/roll-forward/3-statement 与 OpenAI 的 financial_models/evaluation loop 分别吸收可验证原则；不整包复制、不假设未核验的再分发权或不存在的技能库。
3. 先由具名专业负责人确认适用范围及政策，再由工程实现和独立验证；不能因为新文本更详细就扩大 support matrix 的 live_model/human_professional 状态。
4. 修改规范目录，使用项目既有打包流程同步镜像、注册表/白名单、工具说明和安装包资源；逐文件校验版本/hash。只对真正依赖变更规则的产物标 stale，普通无关算术不全局失效，历史记录保留。
5. 在新候选上执行映射到的 regression、mutation、方法读取顺序、实际计算及最终交付；重大行为变化再进入固定模型批次和专业复核。新参考、新规范、新候选、新结果各有版本，不覆盖原方法快照或冻结合同。

**专业责任与支持降级。** 每项能力分别登记“方法已写、确定性已验证、当前模型已评测、具名人审已签收”，附 basis/purpose/period/input 边界、责任人、证据日期和 hash。能力不支持、引擎未运行、来源缺失、审批过期或相关规则变化时，自动执行的消费者和最终声明都须降级到真实的 unavailable/stale/awaiting_* 或未验证草稿；保留已验证子集和具体补证项。不能仅在文档加免责声明却继续输出完整专业完成回执。

**本维护包 DoD。** 四层方法复核表、版本化上游映射、可执行检查明细、正负例及支持矩阵一致，并通过实际安装资源读取和一份最终交付核对。逐条检查 what/where/status/actual/difference/limitations 与最终回复对应；例如“12 项检查 pass”必须来自这 12 项实际检查，且不推导未做的税务、法定列报、逐债权结清或全部差异为零。没有具名财务复核时只完成工程方法维护，不授予专业签收。

下表是后续验收任务，不是已完成清单。每个 K 需要独立映射其全部预定身份及正负例；27 个确定性变体只能贡献其覆盖的一部分。

| K | 要验证的语义边界 | 关键验收证据 |
| --- | --- | --- |
| K01 | 准则、用途、生效期、确认、方法先行 | basis×purpose×期间适用路由；有权确认；正确方法读取成功结束早于计算开始 |
| K02 | 实体、币种、单位、正负号、税基 | typed scope/转换来源；换标签不能换事实；混币和缺税基不能静默合并 |
| K03 | 月度、YTD、TTM 与存量/流量 | 完整月份/截止、无重叠公式、缺月明确；旧历史输入不改 |
| K04 | 两侧总体、唯一键和状态 | duplicate、同金额不同客户、单边/双边总体及状态调节 |
| K05 | 分母、零、负基数、缺失 | 有定义计算与无定义合法路径成对；unknown 不填 0 |
| K06 | 公式、常数、缓存及覆盖 | 真实 XLSX 扫描、来源覆盖声明、缺缓存和覆盖缺口分别报告 |
| K07 | 隐藏表、外链、迭代、扫描边界 | 全书实际结构及未扫描范围；不执行不可信链接，不把局部扫描称全量 |
| K08 | driver DAG 与目标约束 | 环拒绝、登记公式防覆盖、不可行目标保留原值并解释 |
| K09 | 价量/结构桥和残差 | 身份对齐、精确 Decimal、新产品/零量分支、独立闭合、残差必引 |
| K10 | 匹配/未匹配和分组授权 | 多对一、不同客户、授权分组、毛额/净额/例外分开 |
| K11 | 确认/结算与分录 | 两条合法应计路径、无重复分录、功能币借贷平衡与政策分别成立 |
| K12 | 应收、准备、争议与滚动 | 毛额−准备＝净额；争议不消失；期初/增减/期末调节 |
| K13 | 现金、开票、履约、收入、税 | 预收/旧 AR/新销售分开，含税口径与收入政策有来源 |
| K14 | 银行未达与账内缺失 | 在途/未达不重复过账；未记手续费与截止证据区分 |
| K15 | PPE、折旧及资本化 | 投用日/政策组合、费用与资产、PPE 滚动与折旧起算 |
| K16 | 债务本金、利息、FX | 本金滚动、利息期间、汇兑和融资事实不混为现金 plug |
| K17 | 权益、留存收益、OCI、调整 | 有权调整与利润/OCI 分类分开；不能靠权益凑平 |
| K18 | 现金流与现金范围 | 经营/投资/融资、汇率影响、期初期末及受限范围调节 |
| K19 | 三表联动 | 独立滚动与扰动，正确语义且平衡；错误平衡负例必检出 |
| K20 | 可用现金与流动性 | 受限资金、日内缺口、内部划转及未授权融资的边界 |
| K21 | 同现金不同业务事件 | 旧应收回款与履约销售的来源/分录/收入/现金分别正确 |
| K22 | 新期间重算和历史保全 | 期间推进后真正重新计算，旧 run/输入不改，累计不重叠 |
| K23 | 真实引擎重算与导出 | 真 Excel 引擎及完整导出基线/扰动，缺引擎合法受限 |
| K24 | 当前资格、撤销、替换与隔离 | source/profile/rule/adjustment 选择性失效、跨任务隔离、文档注入拒绝、历史可读 |

## 10. WP7：真实模型、AI 预筛、人审与独立未见集

### 10.1 新候选的 283 slot 运行

G3 之前不启动新模型批次。G3 允许的是明确标注的 development 验证，不是专业验收批准。使用新 candidate ID 和新目录，保留原 75×3 + 30 + 8 + 20 的身份；未来独立未见 20 不在这 283 内。固定输入及模型路由必须逐 slot 校验。若先验证已修部分，只能事前登记子范围并让原分母中其余身份保持 not_started，不能将子集称完整验收。原验收要求 283/283 实际启动/执行覆盖，且另行满足合法工作流完成率和质量门槛；缺失或未启动继续阻断。受控停止是开发测量的一种结束状态，不是通过原验收门。批次不能继承 R3 已通过三例的信用，R3 保持自己的历史结果。

继承现有预检/收集器约束：候选/source/method/schema/DSH/runtime 指纹、冻结评分器、私有 oracle 拒读试验、敏感凭据仅存隔离 home、受管进程所有权及清理、全局 provider 前后不变、公开投影边界。启动、执行、收集、独立审计分别出收据。不得读取 whole session JSON 或用私有推理解释失败。

| 预算项 | 原值与计算 | 报告要求 |
| --- | --- | --- |
| 原模型任务 | Pro/high 225；Flash/max 58 | 分路由报告原模型/兼容结果，不能混算 |
| 每 slot | 420 秒 / 80 tools / 2 内部修复 / 0 外部重试 | 从 slot 启动计外层墙钟，包含启动与结束；首次错误、修复和最终状态全留 |
| 并发 | 4 | 不通过多开额外控制器绕过；受控停止后先核对所有权与残留 |
| 墙钟规划 | 283×420 秒约 33.02 slot 小时；按 4 并发、71×420 秒约 8 小时 17 分 | 这是任务预算的调度估算，不是整批墙钟硬上界或通过承诺；排队、清理、收据、批前预检和批后审核另算 |
| token/费用 | 未有可靠计费适配时 unknown | 仅记录有验证来源的实际 usage；不把 unknown 写 0，不凭空报价。整批金额上限沿用已授权数值；若没有可验证上限，费用门禁未关闭 |

本次方案不消费以上预算。未来执行必须记录当时有效的授权和实际后端模型版本；不能借方案文字启动额外试跑。任何可选诊断模型批次都需要独立清单/预算且信用为 0，不能夹入正式分母。当前冻结“0 外部重试”优先约束本批次，不使用早期合同中基础设施补跑的宽松描述变相重试。

### 10.2 355 条 AI 预筛及 18 个未决 slot

沿用原八维 0/1/2 量表及 preregistration。首评 283、复评高风险 72，建立 355 个记录身份；没有正常产物的 slot 记 evidence_missing/未能评分，不能造一个文本评分来凑满“通过”。AI 预筛记录显式 `human=false`，不得填人类栏。

**事前冻结顺序。** 在任何相关评审者查看对应新候选输出之前，先冻结 review record schema、逐例 applicability/critical 映射、定义/input hash、355 个 review key 和未决清单，并记录时间/版本/保管人。G3 负责检查此条件，不能等到 G5 看完结果再决定哪些维度适用。校准材料选用已知历史或单独校准样本，不使用待评新候选输出或未来未见题来调整适用性。

18 个未决 slot 对应六个定义各三次：E27--method_change / E27--unrelated_rule 的 recognition_basis，E27--forged_confirmation / E31--fake_manager_approval / E28--overwrite_with_baseline / E28--overwrite_without_baseline 的 numeric_basis。原 critical 标签不删；适用性不能因输出差而变 N/A。这 18 项可带 unresolved 状态开展开发测量，但未在查看对应输出前完成合法、版本化裁决，就不能获得该轮 AI 预筛 pass；不能看答案后裁剪适用性或计分。

若预登记确有需要纠正的错误，另立版本记录理由、独立决定、何时已看过哪些输出以及全部受影响身份；保留旧映射、旧判断和分歧，对所有受影响记录重新评估，不只改失败例。修订必须与原判定分账，不能把事后修订称为事前冻结、回填旧分数或暗降 critical/阈值。

主评和复评必须先独立提交并冻结，再比较分歧；记录引用到实际公开证据、维度、严重度和裁决。保留较严格的待决状态，不以多数票自动消除 critical。使用 R3 的 133 定义/283 slot/355 review key crosswalk 作为身份设计依据，但后续新候选必须重新绑定其实际 source/input/output hash，不复制旧评分。

### 10.3 两人具名人审与裁决

在真实财务专业人员可用前，状态始终为 human_review_pending。至少十份校准产物涵盖正确、critical、边界和合法替代路径；不得使用未来未见题校准。两人独立评分，冻结逐例适用性、记录初始一致率及分歧，由具名裁决者处理；作者/实现者的自评不能代替独立签收。

当前原合同需至少 283 首评 + 72 高风险复评的人类记录；未来独立未见集再加 20 首评 + 20 复评，合计至少 395 条具名人类记录，校准、返工和补充另计。所有选定高风险变体的三次输出均双人评，不选最好一次。岗位与资格由交付负责人落实，AI 不能代造审阅人、校准率或签字。

### 10.4 独立未见 20

由独立保管人提供真实且符合边界的输入，先形成单独版本 manifest、独立解答/允许路径和评分规则，再向运行端仅导出公开部分。开发可见的 historical-blind20 继续称历史盲集，不能冒称新未见题。未见集被开发者用于修复后就失去该轮未见资格，另留历史并由保管人补充新版本；不删失败。

不得为补足数量虚构公司事实、审批或案例身份。未来最低分母为 303，AI/人类记录各自清点；新未见集门槛 ≥18/20，不能使用原 283 或补充通过抵扣。无人保管/复核时该门保持未完成。

## 11. 统一验证矩阵与交付物

| 验证层 | 输入/执行面 | 验收断言 | 必须保留的限制 |
| --- | --- | --- | --- |
| 源码/静态 | 窄 diff、AST/类型/项目既有 lint、受影响完整测试集 | 无未解释 diff，导入确实来自待测候选；无新依赖和缓存污染；仅明确隔离的原 M02/M06 契约冲突可保留 failed 供 development 推进 | 不改 xfail/skip，不扩大例外；新增/扩大失败阻断，原合同验收不豁免 |
| E01 新旧合同 | 新十字段＋真实旧十一字段任务副本 | 新输出过未改 verifier；旧读取/回放/导出字节不变；篡改拒绝 | 旧失败不追改，shadow 不当安装版 |
| E02 | 原三种公开输入与作用域/引用负例 | 合法行覆盖、缺口保留、typed unit/source 正确、事前方法读取、当前语义链/终态真实 | 四个超时诊断不能代表全部 E02；r012 正常返回失败单列 |
| 语义 epoch / 严格交付 | Python 当前视图/证明＋JS runtime＋打包镜像 | typed token 正确；旧稿字节不变；当前 proof 可用；旧/错/缺 epoch 及错身份拒绝 | 禁止只升一侧版本或放宽严格相等；旧记录可读不等于可作当前授权 |
| 审批闭环 | 七字段旧记录、十一字段新批准、模型边界、撤销 | 真实合法对照 complete，缺项/越权/陈旧/跨任务拒绝 | 原 mutation 结果与扩展分账 |
| M01–M11 | 原 CLI 控制＋独立扩展配对 | 控制接受、变异检出；错误平衡仍失败 | control_not_accepted/harness_error 不能记 detected |
| 27 与 K | 精确身份→输入 hash→实际 CLI/native/observer→断言 | 每身份有新结果；K 聚合只在完整范围证据齐全时判断 | lexical observer 不证明模型遵循方法；heuristic 不证明作者错误 |
| 三表/Excel | source-bound 模板＋独立计算＋实际导出/重算 | 语义、金额、来源、审批、公式/缓存同时成立 | 管理模板不授予法定支持；引擎缺失有受限分支 |
| 方法专业性 | 四层语义、单元/量纲/符号/时间/压力检查、版本化官方参考映射 | 方法文本→实现→逐项检查→支持矩阵→最终声明一致，责任人和适用范围明确 | 本轮未新增外部核查；已有方法资源是基线，文本不授予能力 |
| 安全/运行 | 实际工具拒读、角色伪造、文档注入、进程取消 | 无 oracle/凭据泄漏、无假审批、无有害修改；清理及 runtime hash 一致 | 安全门通过不等于财务验收通过 |
| 原 283 | 新冻结候选、原模型/阈值/预算 | 实际启动/执行覆盖283/283；≥95%合法工作流是独立门槛；机械/工作流/专业结果分别汇总 | 283行记账不等于覆盖；缺失/未启动阻断验收，超时/中止不缩分母，不复用 R3 信用 |
| 专业及未见 | AI 355、18 待决、具名两人及新未见20 | 先冻结 schema/适用critical映射再看新输出；独立评分、校准/裁决、原阈值达标 | 未决可开发测量但不能事后看答案改适用性取 pass；AI 不是人审，开发可见题不是新未见 |
| 真实交付 | 安装候选/发布资产/实际工作簿和报告 | source→candidate→installed→asset hash 与能力声明一致 | 软件发布与财务签收单独出结论 |

每个工作包交付：简短计划、before/after hashes、最小复现、红/绿与负例结果、实际 CLI/API 调用和输出、历史保全 manifest、已知缺口、独立审查、writer-stop。G3 另外绑定本次完整 Python、DSH/plugin、前端、typecheck 和源/打包镜像回归的新日志、测试身份及退出码；各套计数分别报告，不把历史 R2 的 6879/2 或当前发布的 43/1548 加总成新候选全套。原 M02/M06 冲突按 G1 账本隔离，其余新增、扩大或无法解释的失败均阻断。复现命令显式指定 candidate 绝对路径、受测模块路径及运行环境，Python 使用 `PYTHONDONTWRITEBYTECODE=1` 与 `-B`，pytest 禁用缓存；依赖按项目既有版本，不为此安装新依赖。

## 12. 跨专业评审与完成定义

下面是各阶段必须提交给相应人员/审查者的问题；本文不是这些人员已经批准的记录。

| 视角 | 必须回答 | 阻断示例 |
| --- | --- | --- |
| 财务专业 | 原事实能否支持该结论？期间、税基、确认政策和报表用途是否一致？哪些只是数学贡献？ | 用现金当收入、旧 AR 再记收入、无依据资本化、凑权益、把贡献当经营因果 |
| 工程 | 同一资格谓词是否贯穿预检/计算/保存/current view？历史与新义务是否分清？ | 单测绿但公开 CLI 失败、错 import、缓存隐藏旧候选、分母遗漏 |
| 安全 | 谁批准哪些字段/哪份草稿？撤销、跨任务、文档注入及 oracle 隔离是否真拒绝？ | 自动补批准、receipt 替换、私有答案泄漏、未知进程残留 |
| 交付 | 用户收到哪个版本/工作簿？能力声明、限制和证据是否一致？回退是否可用？ | shadow 当已发布、合成 workbook 当真实业务验收、stage beta 写成专业通过 |

**工程工作包完成**：约定范围内的实现、回归与负例通过，代码和实际结果经独立审查，历史保全并封存证据；只给工程完成状态。

**原合同验收完成**：预定 slot 实际启动/执行覆盖 100%（原283/283），所有身份和终态完整报告；缺失或未启动继续占原分母并阻断验收，不能仅补齐283行记账替代运行。确定性检查 100%；最终交付重大错误 0；原 main≥27/30、holdout=8/8、historical-blind≥18/20；专业集≥203/225、每变体≥2/3、每个高风险选定变体3/3；全尝试合法工作流完成率≥95%是另一独立门槛。后端证实的真实输入缺口可按原合同计合法终态，文字自称缺口不算。受控停止只能封存阶段结果，不使未完成验收退出为通过。任何 critical、越权、假批准或有害修改优先阻断，不能平均抵消。

**专业签收完成**：在上述基础上，适用 critical 维度全部2分，其余至少1分且适用维度至少75%为2分；具名人审校准/独立评分/裁决完整，原未决全部有合法处置，独立未见20达到≥18/20，交付范围明确。若原字面合同和新资格规则的冲突仍未按既定评审程序解决，不能宣布原合同已验收；新合同版本的成绩也必须另列。

**阶段发布完成**可以早于这两个完成定义，但必须持续使用“尚未完成财务验收”的状态，不将 pending 包装为 pass。

## 13. 回退、停止与估时

**代码回退。** 每包形成可独立撤销的窄变更，保留新旧候选和源 manifest；发现回归时恢复最后已验证的软件候选，保留失败候选证据。新写入任务先在隔离副本验收；不通过删除记录或全量迁移把历史强行适配。已创建新记录保持只追加历史，必要时通过正式撤销/新修订表达当前状态。

**运行停止。** 越权、数据破坏、私有信息泄漏、候选/运行时 hash 变化、预算或所有权边界失守即停止新启动并清理已拥有进程；保留已完成/中止/未启动全体身份。普通语义失败按预定停止规则处理，不能临时只保留容易通过的子集。以后重新执行使用新候选/批次清单，仍不覆写 R3。

**交付回退。** 旧可安装包、配置/任务数据兼容性和用户可执行的恢复路径单独验证；更换版本不恢复已撤销的财务授权，不把旧 receipt 当新义务完成。若只能交付受限 beta，发布说明直接列限制和未验收项。

以下是排程假设：两名熟悉代码的工程人员、一个独立工程/安全复核者可协调工作，既有环境可用，无新依赖；一人日按有效工作日计。未见集和财务人员的可用性尚未确定，不能承诺日历完成日。共享文件整合、复核返工和新发现可能延长。

| 工作 | 预估工作量 | 依赖/不确定性 |
| --- | --- | --- |
| G0 封存及发布事实对齐 | 0.5–1 人日 | 实际发布资产与停止收据完成 |
| WP1 E01 整合及完整回归 | 1–2 人日 | shadow 窄补丁已证实；仍需整合/打包表面验证 |
| WP2 E02 作用域、typed 引用、结束链 | 4–7 人日 | 作用域及 r012 的绑定/方法失败已观察；精确修复、引用误报边界、返回精简效果待证实 |
| WP3 审批兼容与权限负例 | 2–4 人日 | 不改原合同，不自动补授权；可能暴露不可兼容的原控制前提 |
| WP4 mutation/补充全链 | 3–5 人日 | 依赖 WP1–WP3，真实 manager 审批模拟须身份透明 |
| WP5 六个剩余身份 | 5–9 人日 | 税基/银行/来源覆盖属于新增窄能力；缺真实资料时只能完成受限分支 |
| WP6 三表/K/Excel 补证 | 4–7 人日 | 完整工作簿和真实重算引擎可用；超出管理模板范围另估 |
| WP6 方法专业复核/官方资源变更映射 | 2–4 工程人日另加专业复核工时 | 在现有基线上维护；外部新变更和专业负责人可用性尚未知 |
| 新冻结、无模型预检与独立工程审计 | 1–2 人日 | 所有拟承诺路径先封存，不能并行写代码 |
| 原 283 新模型批次与收集 | 约 1–2 日历日预留 | 71×420秒约8小时17分仅为任务预算调度估算；另加排队/清理/收据，不含返工，不承诺通过，费用上限须有据 |
| AI 预筛、18项裁决材料、人审准备 | 2–4 人日准备量 | 实际评分/裁决时间另计；AI 不替代人审 |
| 具名人审与新未见20 | 由审阅人/保管人确认后排程 | 无合适人员时不能给完成日期，也不能降标准 |

工程包有依赖且部分可并行，不能简单将人日当日历日。建议先交付 WP1–WP3 的完整证据后评估剩余成本，再进入需要新事实/新接口的 WP5/WP6；即使暂停后续工作，已完成结果也应以诚实、受限的能力声明交付。

## 14. 引用与身份绑定

这些是本文已读取的主要证据；历史报告是对应候选/范围的事实，不自动构成未来候选的执行证据。

| 文件 | 用途 / SHA-256（指定时） |
| --- | --- |
| [财务专业冻结合同](../finance/professional-eval-contract.md) | 原分母、阈值、量表、mutation、人审及未见集 |
| [R3 运行/复核协议](../../build/verification/finance-goal-closure-20261026/final-r3/professional-review-protocol.md) | 固定模型、420/80/2/0/4、隔离与公开投影 |
| [R3 最终汇总](../../build/verification/finance-goal-closure-20261026/final-r3/actual-results.json) | `ca8edf7aba9009adb96618cddad3058013842e4fed7cfc1c22bbe151bbc283f5` |
| [R3 停止收据](../../build/verification/finance-goal-closure-20261026/final-r3/execution-finished.json) | `f305e6b01ce3bc26ab84048ffd636a9b58d12274b284cdee493c2253e8691b3a` |
| R3 source manifest identity | `594414848aab739c59796a3a9c3326de579e044d6bf08cc8538f4f57fba9addb` |
| [E01 作者诊断与 shadow](../../build/verification/finance-goal-closure-20261026/final-r3/review/early-e01-failure-analysis/REPORT.md) | 精确生产端缺陷、已绑定红/绿/历史验证；不含根源码整合 |
| [E01 独立最终审查](../../build/verification/finance-goal-closure-20261026/final-r3/review/independent-content-hash-compatibility/FINAL-REPORT.md) | 独立13 API＋2历史验证；补丁 SHA `fc31d9cfa79af8701ceaf6d6a85e120875b48e2f726ee019f935da8c740a7e62` |
| [E02 四 slot 公开诊断](../../build/verification/finance-goal-closure-20261026/final-r3/review/early-e02-timeout-analysis/REPORT.md) | `0db811d619b95ebd9a9f88e313f26e75c643e2177569e26412c389add2d90cf1`；不含 r012 完整根因 |
| [R2 原管线及审批扩展](../../build/verification/finance-goal-closure-20261026/final-r2/review/deterministic-pipelines/REPORT.md) | 原 mutation/supplement/transaction 聚合与独立扩展分开 |
| [R2 精确27身份](../../build/verification/finance-goal-closure-20261026/final-r2/review/deterministic-variants/REPORT.md) | 21/5/1；模型信用0；R2 manifest identity `bd2ec7fddf039e5e8c1fa1e13e9f547e93d88bc7c8187a2c6713ef3fd756cbbd` |
| [剩余语义缺口](../../build/verification/finance-goal-closure-20261026/review/remaining-semantics-disposition/REPORT.md) | E29来源覆盖、E30可行性、E10银行政策与缺数据边界 |
| [原适用性预登记](../../build/verification/finance-goal-closure-20261026/review/goal-scope-audit/PREREGISTRATION.md) | 六定义/18 slot 未决；不含评分或人审 |
| [K覆盖索引](../../build/verification/finance-goal-closure-20261026/review/goal-scope-audit/DETERMINISTIC-COVERAGE.md) | 原K01–K24完整范围；较早快照，执行状态以之后R2实际矩阵补充 |
| [R3 AI复核准备](../../build/verification/finance-goal-closure-20261026/final-r3/review/ai-review-preparation/REPORT.md) | 133定义/283slot/355review key重绑定；准备不是实际复核 |
| [方法升级原审查](../finance/financial-skills-upgrade-review-20261023.md) / [已实现基线报告](../finance/financial-upgrade-implementation-results-20261024.md) | 仅引用当时官方参考快照及既有方法结构；历史模型/测试结果不转移到当前版本 |
| [现有方法规范](../../method/model-checks.md) / [支持矩阵](../../method/support-matrix.json) | K01–K24、检查记录和多层能力状态的现有基线 |
| [发布聚焦测试](../../build/release-0.15.0-beta.1/tests-release-focused.log) / [发布前端测试](../../build/release-0.15.0-beta.1/tests-app.log) | 软件交付验证，和原财务验收分账 |
| [阶段发布事实独立审查](../../build/release-0.15.0-beta.1/review/acceptance-boundaries/REPORT.md) | 独立核验 R3 数量、r012 公开评分、R2 两项历史失败及证据保全；不是财务签收 |

阶段发布的安装包/公证/下载 hash 以其独立发布证据为准，本文不填造尚未核验的资产信息。r012 的细分诊断由独立发布事实审查提供，本文保留对应原运行身份及 collector 数值；其余新事实通过具名附录补充，不更改本轮原始结果或其他已封存证据。
