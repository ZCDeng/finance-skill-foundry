# WP1 实际结果：新草稿十字段 content_hash

日期：2026-10-27。候选基线：`codex/finance-stage-0.15.0-beta.1` 的 `e21533a89d2eab4b09f2702f7b39f17efe5b5699`。本文只记录这次候选上已经跑过的命令和退出结果。

人审状态：**human_review_pending**。没有填写人类评分或签字栏。原模型验收没有启动，模型信用为 0。完成策略仍是 16。外层时限默认仍是 420 秒，本轮没有消费这 420 秒。

## 账本

| 账本 | 本轮实际执行 | 实际结果 | 不能据此声称 |
| --- | --- | --- | --- |
| A 原模型验收 | 未启动。没有新 run identity、没有 provider 调用、没有把 R3 目录继续用作本候选 | 无新分数。方案记载的 R3 仍是历史：19 个启动、机械通过 3（E03--base 三次）、E01--base 三次失败。本检出没有 `build/verification/finance-goal-closure-20261026/`，那些 SHA-256 未在本机重算 | 283/283 已跑；E01 模型失败已改为通过；可复用 R3 的 3 分 |
| A 原 mutation 合同 | 未改 `tools/verify_finance_mutation_pipeline.py`。用真实 CLI 重跑 M02、M05、M06，两次：一次是本候选，一次是未改的 `analysis.py` | M05 为 detected，合法对照 complete。M02 与 M06 仍是 `control_not_accepted`，拒绝码 `fact_amount_evidence_ineligible` / `awaiting_profile_confirmation`。改前改后相同。测试未改成 xfail 或 skip | 原 11 类聚合通过；把这项失败算进兼容回归的通过 |
| B 兼容与工程回归 | 只改新写入的 content_hash。评分器、oracle、420 秒默认、历史失败记录都没改 | 见下方命令。新 managed / prepared / revision 草稿的 content_hash 等于冻结十字段，且仍保存 `required_check_authorship`。直接旧接口仍无 authorship。合成的旧十一字段草稿在读取、同请求重试、manager refresh、导出后字节和 content_hash 不变 | 财务专业验收通过；阶段包已经带上这个修复；人审完成 |

## 代码边界

`foundry/analysis.py` 的新草稿 `content_hash` 只哈希冻结的十个字段：`title`、`requirements_id`、`materiality`、`body`、`body_template`、`document`、`run_ids`、`fact_ids`、`claims`、`limitations`。`required_check_authorship` 仍由服务端写入记录，并进入整记录 `_integrity_hash`。

`tools/finance_professional_eval.py` 的 git 对象仍是 `ea4e9368b2619c04c71bb17eb20d093861313e92`，与工作区 `git hash-object` 一致。文件 SHA-256 为 `20fb69a5c752e83bda240773fd1da51884b91ea71b324b6b07746c5675d1f08d`。`legal_workflow` 的十字段和 `--timeout-seconds` 默认 420 都还在。

修复前，三个绑定当前实现的红例失败（3 failed，3.49 秒）。存储哈希含 authorship，与十字段不同：

| 路径 | 当时存储哈希 | 冻结十字段 |
| --- | --- | --- |
| managed save | `8d90c98ede6db7940b45101a18431ee2aff69f883e987c25fdbe409f6e612763` | `ca7df30ead66573384252adee9a2344ba743b7629b1cc7ddde3467c27cea4a32` |
| prepared template | `abf77caa44408e56fbb8a78139d9b1a03fba30c5066d54a36f9a5c361daf83cf` | `055e0fd8d055ef86ef384bddd27fb93df122fe838d083fc68dccdb7c2e370bb1` |
| managed revision | `ec6a677e95d04e3b825deddbadc5777edffe84ec843c22ee7a6c336813ce5286` | `de359ccff94b0b186315daa5685401dcd0b556377ad2096e469d248f548b72d4` |

这三行是修复前的观察，不是新的通过分数，也不回填 R3。

## 命令与结果

环境：Linux，CPython 3.12.3，pytest 9.1.1。命令使用 `PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider`。解释器是系统 Python；`.venv/bin/python` 只是指向它的本地符号链接，未提交。

1. 合同测试 `tests/test_finance_e01_content_hash_contract.py`：9 passed，8.60 秒。覆盖新十字段、直接旧接口、两个同内容不同 draft 的各自回执、十一字段历史不迁移、磁盘改写 authorship 被完整性或语义检查拒绝、回执不能改绑到另一份草稿、评分器源码仍是十字段和 420 秒。
2. 相关套件第一次一起跑时，529 passed、2 skipped、2 failed，190.33 秒。两个失败都是当时没有 `.venv/bin/python`：`test_actual_cli_registered_session_rechecks_without_new_records`、`test_hard_stop_kills_same_group_descendant_that_ignores_sigterm`。补上解释器后这两个测试通过。两次跳过是环境条件，不是改出来的：`set FOUNDRY_DSH_BIN to the installed runtime`，以及 `real macOS isolation unavailable`。
3. 独立复核重新执行合同、deadline、兼容、冻结、专业评测器和上述 CLI 交付测试：159 passed，2 skipped，73.70 秒，退出码 0。跳过原因与上一条相同。
4. 原 mutation CLI：本候选 16 passed、2 failed，45.32 秒。失败只有 M02 与 M06，状态 `control_not_accepted`。未改 `analysis.py` 时同一命令是 1 passed、2 failed，45.25 秒，拒绝码相同。M05 在本候选上通过。

本轮没有跑完整仓历史的 6879 项，也没有把发布聚焦测试的 43/1548 加进本候选分数。

## 仍未关闭

- G3 未做，因此没有新的 283 slot 模型批次。
- E02 范围、引用、单位和结束链未改。
- 七/十一字段审批冲突仍在。M02/M06 保持失败，留在原合同账本。
- 人审、18 个适用性歧义和独立未见 20 仍是未完成。
- 阶段提交 `e21533a` 本身没有这个写入修复；修复在后续候选上，不能写成 0.15.0-beta.1 安装包已经修好。
