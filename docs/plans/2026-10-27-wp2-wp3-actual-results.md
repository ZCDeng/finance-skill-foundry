# WP2 / WP3 实际结果：E02 范围证明与七/十一字段审批

日期：2026-10-27。候选分支：`cursor/financial-repair-acceptance-c524`，基线仍是 `codex/finance-stage-0.15.0-beta.1`。本文只记录这次已经跑过的命令和退出结果。

人审状态：**human_review_pending**。没有填写人类评分或签字栏。原模型验收没有启动，模型信用为 0，provider 调用为 0。完成策略仍是 16。外层时限默认仍是 420 秒，工具预算仍是 80 次。本轮没有消费这 420 秒，也没有启动 283 slot。

WP1 的十字段修复和方案记载的历史 R3 都不是原模型通过。R3 的历史账本保持原样：方案记载 19 个启动、机械通过 3（E03--base 三次）、E01--base 三次失败、r012 是正常返回失败。本检出没有 `build/verification/finance-goal-closure-20261026/`，那些 SHA-256 未在本机重算。

## 账本

| 账本 | 本轮实际执行 | 实际结果 | 不能据此声称 |
| --- | --- | --- | --- |
| A 原模型验收 | 未启动。没有新 run identity，没有 provider | 无新分数。WP1 与历史 R3 都不计为原模型通过 | 283/283 已跑；E01 或 E02 的模型失败已改为通过 |
| A 原七字段 mutation 合同 | 未改 `tools/verify_finance_mutation_pipeline.py`。`tools/verify_finance_eleven_field_approval.py` 先按原工具跑 M02、M06 | 两次独立 CLI：M02 与 M06 都是 `control_not_accepted`。合法对照 `accepted=false`，完成状态 `awaiting_manager`。拒绝样本含 `fact_amount_evidence_ineligible` / `awaiting_profile_confirmation`。测试未改成 xfail 或 skip | 原 11 类聚合通过；原字面七字段合同已经通过 |
| B 十一字段审批 | 同一 runner 在独立目录用现有公开确认接口，由 manager 先确认七字段，再确认十一字段和八个模型边界，然后跑同一 M02/M06 检查 | 两次独立 CLI：M02 与 M06 都是 `detected`。合法对照 `accepted=true`，完成状态 `complete`。assistant 伪称 manager 被拒。七字段确认文件字节在十一字段事件之后不变。十一字段事件 id 与七字段不同。七字段缺口正好是 basis、basis_version、fiscal_year_start、early_adoption；十一字段缺口为空。十一字段确认后、边界确认前，状态是 `awaiting_model_boundary_confirmation` | 这项 B 结果补上了原合同的分数；人审完成 |
| B E02 工程回归 | 原生量价双 alias 范围证明、缺基价与零基期数量、零实际销量的有限总差异 | 见下方测试。合法双 alias 覆盖通过；旁证币种冲突和参与来源错币种都点名字段，不删除 `public_facts`，也不写成“没有已引用的结果行”。通用双 alias 比较仍然拒绝。缺基价的篮子保持 pending。零实际销量保留金额总差异，结构/价格/残差保持空，不补“件” | 原 E02 模型 slot 通过；r012 的方法迟读被放行 |

## 代码边界

`foundry/finance_requirements.py` 只对原生 `quantity_then_price`、`base_weights_with_interaction`、`volume_mix_price` 增加范围证明。证明绑定参与计算的 source rows、comparison、产品、期间、实体、币种/单位和来源 hash。单 alias 且旧的范围匹配已经成立时，缺少历史 run 上从未存储的 hash 不会把该行打回 pending；币种、来源 hash 不一致、旁证口径冲突这类正面矛盾仍拒绝。通用比较在候选 scope 数量不为 1 时仍拒绝。

缺基价、显式零基期数量、全体实际销量为零，走三条不同路径。零实际销量只在每个实际数量都是明确 0、每个基期数量都大于 0 时给出金额总差异；量/结构/价格/残差保持空。基期零或负数仍是 `volume_mix_price_nonpositive_quantity`，金额保持空。

`foundry/finance_professional.py` 的 `profile_gap` 只挂在 `finance_profile_status` 上，不写入 `rule_identity`。它按当前 confirmation basis 取最新一条非边界事件，不合并其他 basis。`foundry/finance_service.py` 的确认接口仍要求 manager，并只写入调用方提交且 profile 上已经存在的字段。

`tools/finance_professional_eval.py` 的 git 对象仍是 `ea4e9368b2619c04c71bb17eb20d093861313e92`。文件 SHA-256 仍是 `20fb69a5c752e83bda240773fd1da51884b91ea71b324b6b07746c5675d1f08d`。`--timeout-seconds` 默认 420，`--max-tool-turns` 默认 80。`CLAIM_SEMANTICS_VERSION` 与 `dsh-plugin/final-delivery-runtime.js` 的严格检查都仍是 19。本轮没有改语义版本。

## 命令与结果

环境：Linux，CPython 3.12.3，pytest 9.1.1。测试命令使用 `PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider`。CLI 使用 `.venv/bin/foundry`。原始 CLI 目录在 gitignore 的 `build/verification/` 下，未提交。

1. 新测试第一次执行：8 failed，3 passed，0.73 秒。失败来自测试自身的参数和缺 import，不是产品结论。
2. 修正测试后：3 failed，8 passed，2.00 秒。旁证币种被要求范围收成参与来源的币种；缺基价的说明当时只在质量 issue 上；零实际销量因缺币种/单位而没有金额总差异。
3. 产品与测试对齐后，E02、profile gap、三因子、方差和通用双 alias 负例：69 passed，2.80 秒。
4. 相关套件（含 E01 合同、原生草稿、profile、fact token、eval compatibility、requirement paths、M05）：643 passed，3 failed，125.36 秒。三处失败是单 alias 合成量价 run 没有历史 source hash，被新证明误伤。收窄为“正面矛盾才推翻旧的单 alias 匹配”之后，`tests/test_requirement_evidence_paths.py` 整文件 429 passed，52.09 秒。
5. 独立复核，新进程重跑 E02、profile gap、三因子、方差、E01 合同、fact token、profile 依赖、专业协议、方法资源必须先读、以及上述量价/双 alias 负例：198 passed，56.57 秒，退出码 0。评分器 `git hash-object` 仍是上面的对象。`tools/verify_finance_mutation_pipeline.py` 与评分器相对 HEAD 无 diff。
6. 十一字段 CLI，第一次 `build/verification/eleven-field-approval-20261027`：退出码 0，报告 `status=passed`。账本 A 的 M02/M06 为 `control_not_accepted`；账本 B 为 `detected`。第一次 M02 的七字段确认 `d4b9e0af42da45dc8f48515aec94d1c3`，十一字段确认 `d7b60781943e4e0ea117e967a1dbbf3b`。M02 mutant 拒绝点是 `driver binding requires matching rows and exactly one row for single`。M06 mutant 拒绝点是 `requirement_unanswered`。
7. 同一 CLI 独立第二遍，目录 `build/verification/eleven-field-approval-20261027-review`：退出码 0，账本状态与第一次相同。确认 id 是新任务上的新 id，不回写第一次目录。
8. 完成链与已保存交付 `tests/test_finance_completion_operations.py`、`tests/test_finance_saved_delivery.py`：68 passed，23.45 秒。这只说明现有保存、恢复、settle 路径没有被这轮改坏。它不是 5.4 的模型尾部测量，也没有放宽 420 秒。

方法先行仍由未改的评分器拒绝：`test_compatibility_does_not_waive_reading_method_resource` 与 `test_e03_requires_both_method_resources_before_calculation` 在独立复核里通过，失败码仍是 `resource_not_read_before_calculation:method-resource`。同值异单位仍由 `test_another_same_valued_fact_cannot_supply_a_token_unit` 拒绝。本轮没有因此升语义版本。

## 仍未关闭

- 5.3 的原生 P/Q typed 模板没有新改。现有 fact identity 加单位路径仍在，语义版本保持 19。不能把这一点写成 r012 或四个 E02 超时 slot 已通过。
- 5.4 的模型尾部没有新的无模型回放测量之外的结论。工具返回体积没有改，420 秒和 80 次工具预算没有放宽。
- G3 未做。没有新的 283 slot，也没有 DeepSeek 凭据可用。
- WP4 至 WP6、原 11 类聚合、六个剩余确定性身份、三表/K 与人审未见集都还没有本候选的新通过分数。
- 阶段提交 `e21533a` 本身没有这些修复。修复在后续候选上，不能写成 0.15.0-beta.1 安装包已经修好。
