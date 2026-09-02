---
title: 会话产出的落点，与挂载粒度 —— 两条借鉴的收束
type: study
date: 2026-09-01
topic: task-project-deliverable
method: 每题三条独立立场提案，各由 fence / operator / durability 三个镜头打分，共 27 个 agent
verification: 决定结论的断言由主线程复核，标注在文内
---

# 会话产出的落点，与挂载粒度

承 [YouMind 容器模型研究](2026-09-01-youmind-containment-model.md) 里值得抄的两条。每题出三条互相冲突的提案，各打三次分，下面是收束。

**先说一件不属于这两题的事。** 三个 judge 在两道题里各自独立指到同一个洞，我实测复现了。见最后一节。

---

## 题一：会话产出的落点

### 收束：走会话内的按工具名 keyed 槽，不做右侧栏

三条路是右侧栏（改我们自己的矩形）、会话内回执（占 Cordis 槽）、归档回执（靠上游自己的卡片渲染）。

第三条**机制上是死信**，我复核了。上游 `dsh-client-ui-tool/lib/client.js` 的 `toolRowModel` 全部字段出自 `TOOL_TITLES[toolName]`、`VARIANT_TITLES[variant]` 和 `resultText(block)`，压根不读 `resultView`。紧跟着的注释自陈，read-card 是把 `card:'read'` 意图变成 props 的**唯一**一处。所以 foundry 工具就算声明 `presentResult`，标题不会动，正文不会换。这条以后不必再论。

第一条和第二条的分歧是真分歧，且没被裁掉：

- **fence judge 支持右侧栏**，理由是他去读了写入方。`session_id` 来自 `exec.agent.id`，`cause` 由 Python 写死，`seq / sha256 / bytes / at` 由 `register_bytes` 盖章——整行没有一列是模型能写的。把这一行摆在模型自己那段话旁边，操作员对「这个数是对着锁库重算的」的证据就不再只是模型自己抄的那句 `我重算`。他要的是一条可被抓的物证。
- **operator judge 反对**，理由是他去量了宽度。右侧栏端上来的是版本索引，而真正值得跟对话并排看的是底稿本身，`components.css` 给 `.fnd-table` 钉了 `min-width: 560px`，塞进侧栏等于把 Reader 当初从 dump 里救出来的表退回横向拖动。

**两边看的是两个东西：物证 vs 文档。这条没裁出来，别在下一轮假装它裁了。**

选第二条的理由不是它赢了辩论，是它省下的动作是另外两条省不下的：从对话切到 `交付物` 只要一次点击，真正省不下来的是**把某一版绑到引发它的那一轮对话上**。`cause` 是 `query-locked:followup-3`，在交付物表里它是一个要靠脑子解析的外键，在那一行卡片上它紧挨着引发它的那个问题。

槽是 `tool.call.toolview`，我复核过：keyed，按 wire tool name 分发，对自己注册的工具是纯增量。

### 最小第一步：完全在 foundry 里，一次 commit

**已做（2026-09-02，KTD15）。** 四条验收全过，含「不带 `--receipt` 与改动前逐字节一致」（对 stash 出来的旧代码比过）。

回执由**写入侧**报出来，不要用 seq 前后快照相减去推——那个推法有两处会静默错：任务解析链和写入侧不是同一条，而 `seq` 是 `len(rows)+1` 在 task lock 里全局递增，并发会把别人那一行算进来。

1. `register_bytes` 返回行的同时报出这次是否真的追加了（字节相同时它返回上一行、不追加，而 `_register_period_outputs` 是可重入的，所以「刚归档」和「早就在册」在行本身里分辨不出来）。
2. `_register_period_outputs` / `_record_followup` / `record_reference` 三处把已经算好的行往上传——它们现在都握着却丢掉了，`cli.py` 的 export 路径就是现成样板。
3. 三个子命令加 `--receipt`。带上它 stdout 变成 `{"text": …, "filed": [...]}`，不带它逐字节等同于今天。
4. 验收只用 CLI：同窗口连跑两次 emit-brief，第一次两行 `appended: true`，第二次两行 `false`；窗口没有 task 时 `filed` 为空数组。

第二个 commit 才动 `dsh-plugin`，那时 `presentationMeta` 只是把已经拿到手的 `filed` 原样投影。

**已做（2026-09-02，KTD16）。** 四条上游事实各自读了源码、各自钉了测试。判官说的两条 UI 事实也落进去了：没绑任务时画「未登记」而不是不画，字节没变时画「已在册」。另外补了一条判官没提的：占了 key 就等于接管整行，包括拒绝——拒绝是围栏在起作用，不能因为这行归我们画了就读起来像答案。

### 明确不做

- **不给 harness pane 装 preload。** `pane.ts` 用 `contextIsolation: true` 加 `sandbox: true`，整个 `harness/` 下没有 preload。`ipcMain.handle` 的通道是全 app 的，装上之后嵌入页面就够得到 `foundry:task-new` 和 `harness:open`——fence 的核心性质会从「页面根本没有桥」退化成「页面有一份 sender 白名单」。这条要以 KTD 形式进 plan，不要留在落败提案的脚注里等下一轮重新发现。
- **不开 host RPC 给页面取数。** 那等于在跑模型的进程旁边开一条载着归档正文的 loopback HTTP，安全性最后落在一个 preset 文件的 `fetch: false` 上。KTD11 说的就是别建这种。边界是「模型够得着的路径上不许有载着任务字节的 loopback」，不是「不许有 loopback」：KTD20 的预览 gateway 服务的是临时副本、没有任何工具能到、随状态条一起退出，所以不在此列。
- **不做头部常驻索引。** 它是交付物屏幕的劣化重复，而 `presentationMeta` 只投顶层调用，索引会漏报嵌套调用却自称完整。
- **收窄 `viewBounds` 这个几何手法留着。** 以后任何要跟对话并排的东西走这条，不要覆盖层，也不要为它注册槽。这一问不该用它。

---

## 题二：挂载粒度

### 收束：走口径表，只做读的一半

三条路是口径表（把已有的挂载显示出来）、会话挂载（在 `sessions.jsonl` 上加 scope）、视窗口（造只带指定表的后继窗口）。后两条 3-0 否。

**中间粒度今天其实已经存在，只是没画出来。** `record_questions` 强制每题声明 `required_table_ids`，写盘前还跑一次 `source_table_id` 纯粹为了它的拒绝——一道题只许指一张具名事实表，`coa/aux/map/units` 只负责切分。出稿和追问共用这个解析函数，两边不会各算各的。在 `app/src` 和 `app/electron` 底下 grep `required_table_ids`：零命中。这份声明清单唯一能被人看到的地方是上游自己的会话流水，那是别人家的渲染器，改版时我们这边不会有任何测试变红。

**分歧在 `amend-questions`（改口径）上，也没裁出来。** 两人引同一段代码，结论相反：`launch-formulator` 确实在 `STATE_TOOLS["Locked"]` 里，所以操作者可以先在 Formulator 里把数看一遍、回头改口径、再出稿。operator judge 判 fatal——诚实的修正被写进稿面，而 `re-import` 依旧提供一条不留痕的干净路径，于是不诚实的修正免费。fence judge 承认同一串事实但判 contained——这条路今天连披露都没有，加一条有记录的路比什么都没有强。

**这是对 fence 的两种读法：读成「阻止」，`amend-questions` 必须先解决 Formulator 那一步；读成「披露」，它现在就能上。** 所以这一轮只做读的一半。

### 最小第一步

`foundry/questions.py` 加 `questions_view(window)`，返回每题的 id、text、声明清单、解出的表、每个声明 id 是否在 `window.table_names()` 里，以及 `brief_facts.json` 存在时的 tag 和 schedule_id。同时把 `brief.py` 里那段内联的缺表判断抽成 `missing_tables`，两边都调它——面板若自己重写一遍，迟早会在「这张表在不在」上和文档打架，而那正是面板被拿来防的事。

然后塞进 `task-show` 已有的窗口循环，`TaskDetail.tsx` 在输入归档上方加一块面板，表 id 用现成的 chip，窗口没有的表用已有的 absent 标记。不新增 CLI 子命令，不新增 channel，`WRITES` 保持一行。

### 明确不做

- **会话挂载否掉**，不是因为不安全，是因为它在自己要堵的场景上**必然 fail open**：`query_locked` 手上只有一个 `Window` 和一个 `session_id`，唯一的任务入口是被寻址窗口的那个任务；跨任务时会先在那个外来任务上写一条没有 mount 的 session 行，查过去查不到只能放行。而且 `session_id=None` 是正常路径，「查不到就拒绝」这条规则写不出来。
- **视窗口否掉。** `var/current` 只向前走，没有任何 CLI 动词能把它拨回去，所以 `narrow()` 要么把整个 store 不可逆收窄，要么只能靠模型自己传 `--window` 才够得着——被约束的一方自己选约束。而 `create` 在 `Locked` 允许集合里，握着 `narrow` 的模型同时永远握着开一个新宽窗口的动词。
- **行级、摘录级挂载不碰。** 任何比整表更细的切片都要先把 `derived_from` 这个判别符一般化。
- **主表不可裁**（来自视窗口提案，值得单独存档）。裁 `coa` 会让 `filter_map_rows` 对着变小的科目集重跑，`map.loaded_hash` 跟着变——这是唯一一处「子集」会改摘要的地方。将来任何作用域机制都得带这条断言，写在函数里不是注释里。
- **`amend-questions` 是暂缓不是永久否。** 重开之前先办四件事：Formulator 在 `Locked` 里先看数这个前提怎么处理；from / to / reason / at 完整写进底稿正文而不是只写次数（底稿出稿时被 sha256 收录，`questions.jsonl` 不是交付物，一条 `rm` 就没了）；reason 要过 `references.py` 那套保留词拒绝；补一条断言这个动词不在 `REQUIRED_TOOLS`、不在 `TOOL_SPECS`、不在任何 `STATE_TOOLS` 值里的测试。少一件都不要开。

---

## 两题之外：一个实测复现的洞

三个 judge 在两道题里各自独立指到同一处。我在真 store 上跑出来了。

`query_locked` 用 `WindowStore.get` 在**全库范围**解析 `brief_window_id`，没有任何任务归属检查（`WindowStore.get` 只验 id 格式和目录存在）。随后 `cli.py` 用 `extra_task_ids=(addressed.task_id,)` 把会话认领进被寻址窗口的任务。

复现，两个任务各自完成一次结账：

    先把 sess-real 记在任务 A 上（对 A 自己的窗口追问）
      A 的会话: ['sess-real']

    同一个 sess-real，指向 B 的窗口
      稿外追问 / 我重算: B 的 GL -> 100（窗口: a333e2a5…）

    A 期  会话: ['sess-real']               版本数: 3
    B 期  会话: ['sess-on-A', 'sess-real']   版本数: 4

一个已经记在 A 上的会话，对 B 的锁库算了数，现在同时出现在两边的会话列表里，而 B 长出了第四版底稿，成因是一次 A 的对话。

**性质要说准。** provenance 没破——那个数确实出自 B 的锁库，标着 `稿外追问`。破的是任务链那条「一个任务拥有它的会话」。单机单人，所以不是保密问题，是审计链问题：B 的时间线上有一版文档，来自一次不属于它的对话。

**可达性。** 模型要拿到 B 的窗口 id 才能做这件事，途径只有操作员贴进来或者压缩上下文带过来，概率低。但护栏很便宜：会话已经记在任务 X 上时，拒绝它寻址任务 Y 拥有的窗口。同一任务内追问旧窗口——`--brief-window` 本来的用途——不受影响。

**已修（2026-09-02，KTD14）。** 两道门都堵了，各带测试：会话那道在 `record_session` 上拒绝，窗口那道让 `bind_window` 和 `bind_task` 按同一条规则拒绝——后者一直会拒绝移动已设的反向指针，前者没有这道闸，而 adoption 在窗口已被拥有时干脆跳过了第一道检查。同任务追问旧窗口不受影响，无主窗口照旧被第一个碰到它的任务收养。
