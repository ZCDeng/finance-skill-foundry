# R4 自动收尾运行时补齐

状态：源码与候选窗口已验证，尚未安装及整体验收。本文补齐 r4 设计四；cee4c26 旧冻结主集已结束，保留其原观察和成绩。最新构建与后续补修以执行台账为准。

## 需要解决的问题

旧实现的两轮预算绑定要求语义链。模型删除或改变要求后可能新建链，实际发生过一个问题五次保存检查；评测超时也不能代替产品超时。新增持久 operation 约束一次真实用户请求中的自动收尾，保留原语义链检查。

## 身份与权限

- 模型工具仍是 save_explanation_draft，不添加可由模型声明的 operation、revision、manager_save 参数。
- DSH wrapper 从真实 session 的 user/message 事件（data.source.kind=user）生成 request_key；事件序号和 session 共同确定身份。模型改要求不能改变该身份。
- 后端 begin 生成 opaque operation id，并绑定授权 session/task。CLI begin/status/stop 仅由运行时调用，不注册成模型工具。
- 同一次工具执行的 callId 由 runtime 注入；后端在锁内分配 revision。同 callId 同 payload 重放原结果；不同 payload 明确冲突。未知 operation 和跨 session 访问拒绝。
- 普通 UI/本地编辑保存继续走非 operation 保存；模型不能通过参数声明自己是经理。

## 持久状态与预算

- operation 保存首次 started_at、deadline_at、policy、各 revision 的 payload hash、原始待保存正文、draft/receipt 绑定和事件。
- 默认最多两轮修复；配置只允许0、1、2。timeout_seconds为1..3600整数秒，默认420。配置在begin冻结，重启、重试和要求变更不能重置。
- 首次保存加两轮修复最多三个不同 attempt。旧语义链已判无进展或已耗尽时，新 operation也不能使该次检查变成通过。
- 超时、取消、缺资料或耗尽预算后，不再启动同 operation 的自动保存；精确的已结算重放仍允许。
- 已取消操作的迟到结果只登记证据，不把操作重新激活。

## 运行时与保存链

- invokeFoundry 转发取消，等待实际子进程终止；不只取消上层等待。
- 保存前先核验运行、要求、父稿和来源授权，再记录可恢复payload；准备事实后、来源分页之间、正式保存前检查持久deadline。
- 运行时定时器覆盖工具调用及两次保存之间的模型思考。到期持久stop，并只取消当前operation对应的轮次，keepInbox=true保留经理输入。
- tools/result使用实际DSH签名和agent/callId匹配，不用猜测事件或无身份匹配。需要停止自动收尾时先保留当前工具结果。
- 新用户消息不得被旧timer取消；不得清空composer，不改变全局工具allowlist。
- 保存过程被中断时，既有稿保留，新正文留在operation payload供恢复；该payload不是已检查通过的正式稿。成果界面提供“可恢复的未保存文稿”，载入可编辑副本，明确未检查；不覆盖当前未保存编辑。恢复读取仅开放给任务编辑界面，不注册成模型工具。已保存未结算的崩溃重试记录通过真实operation/call绑定排除，避免重复恢复。

## 必须验证

1. 真实CLI/runtime链路使用持久后端，不能只以mock事件测试证明接入。
2. 不同session、未知operation、模型伪造身份和同callId异payload被拒绝。
3. 重启后deadline不变；模型修改要求不增加operation预算。
4. 超时确实终止子进程；已保存稿和待保存正文可恢复，检查状态不冒用。
5. 新用户输入、经理自由保存、普通讨论仍可用。
6. 安装版重包后重新验证；完整30+8+20及经理校准继续独立进行。

## 验收进度

- 源码已接入持久操作、真实 CLI flags、工具进程取消和恢复读取；尚未随安装版交付。
- 后端、服务、CLI、插件与真实 DSH 装载组合检查82项通过；真实DSH本地适配器事件链通过，恢复界面真实Electron10项通过；最终完整回归994 passed/2 skipped，含App402项，构建通过。
- 当前冻结30例观察继续使用旧候选构建，保留全部原始结果。不能把新源码测试算入旧构建模型成绩，也不能据此宣称解释质量全面达标。
