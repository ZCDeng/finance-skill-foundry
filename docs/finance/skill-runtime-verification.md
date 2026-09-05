# 随包财务技能的运行与验收

四项技能 `financial-statements`、`reconciliation`、`variance-analysis`、`journal-entry` 由 harness 的真实技能提供方发现，再通过 `skill` 工具加载正文。`method-resource` 读取技能引用的 Foundry 适配和连接说明，返回来源路径与内容哈希。它们给出财务方法；实际计算仍使用当前任务的 SQL/Python、run 和可编辑草稿。

开发环境的 canonical 目录是 `method/`，打包镜像在 `foundry/resources/method/`。安装版从自身 `Contents/Resources/foundry/_internal/foundry/resources/method` 定位，不要求用户另外安装全局副本。个人同名技能沿用提供方原有优先级；覆盖关系由真实提供方测试验证。

普通 `analysis` 任务不要求 Window，可以组合多份资料。旧 `period` / `f3` 会话继续执行各自约束。币种、报表口径、重要性阈值和说明由财务经理决定，普通计算与草稿保存不增加逐工具审批。CONNECTORS 中的 ERP 类别是接口占位，不能据此宣称已连接企业账套。

## 确定性验证

从仓库根目录运行，使用已有开发依赖，不触发模型请求：

```sh
FOUNDRY_DSH_BIN="$PWD/app/extra/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js" \
  .venv/bin/python -m pytest -q
cd app
npm test
npm run build
```

未准备 DSH 时，真实运行时测试会明确跳过。完整验收必须提供实际运行时并补跑，不能只报跳过后的测试数。资源列表可用 `.venv/bin/foundry method-skills --json` 检查；列表本身不能替代 loader 证据。

## 实际模型与安装版验证

`tools/verify_method_skill_session.py` 创建隔离任务和 harness 配置，复制现有配置模型所需的单个凭据引用到临时 0600 文件。退出时删除临时配置与凭据，保留合成输入、会话观察和财务结果。当前脚本只支持已有 `deepseek-official` 配置；不会自动改用其他模型。运行需要显式 `--live`，会产生真实模型请求。

```sh
.venv/bin/python tools/verify_method_skill_session.py \
  --dsh-root app/extra/dsh \
  --foundry .venv/bin/foundry --plugin dsh-plugin \
  --credentials-home "$HOME/Library/Application Support/FA Foundry/harness" \
  --output build/verification/skill-dev-unique --live
```

安装版使用实际应用及其随包运行时：

```sh
.venv/bin/python tools/verify_method_skill_session.py \
  --app '/Applications/FA Foundry.app' \
  --dsh-root '/Applications/FA Foundry.app/Contents/Resources/dsh' \
  --foundry '/Applications/FA Foundry.app/Contents/Resources/foundry/foundry' \
  --plugin '/Applications/FA Foundry.app/Contents/Resources/dsh-plugin' \
  --credentials-home "$HOME/Library/Application Support/FA Foundry/harness" \
  --output build/verification/skill-installed-unique --live
```

每次使用新的输出目录，避免旧的完成记录污染新结果。验收器将观察插件挂入真实运行时，先逐项加载四个技能和引用，再让当前模型在独立会话中自主处理 G1/G2。观察插件不提供预写 SQL、模拟模型回复或预期答案。

检查包括：

- 正文与引用的来源路径、内容哈希；匹配技能在第一次实际计算前已加载。
- 成功 run 的利润差异 5、收入差异 32 及分项金额；排除碰巧相同的比率列。成本费用的实际减预算差异可按明确规则取反为利润贡献，证据同时保留原始值。
- 同一草稿引用全部差异分量的真实成功 run，每个 claim 对应原始结果单元格，验证状态为 `matches_run`，归一化后的分量之和等于总差异。完整模型回合结束后才评定结果；工具错误及模型恢复过程保留。
- 安装版 harness 的真实父进程和自身资源根；退出应用后重新启动，复验四个正文及引用，并检查原任务 run 和草稿仍存在。

`verification.json` 是结构化结论，`session.json` 保留调用和回合记录，安装版另有 `session-restart.json`。两道题只证明阶段 0 的方法接入闭环，不能替代后续 30 题说明评测、财务领域算子、真实 ERP 或原生 Excel 宿主验收。
