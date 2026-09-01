---
title: YouMind 的容器模型，以及它跟 FA Foundry 对不上的地方
type: study
date: 2026-09-01
topic: task-project-deliverable
sources: youmind.com, caicai.me, openapi.json, sspai, huxiu, zhihu, 第三方测评
verification: 一遍。交叉验证阶段被 403 打断，未跑完
---

# YouMind 的容器模型，以及它跟 FA Foundry 对不上的地方

四路独立检索，187 条断言，每条带 URL。对抗性核验那一轮挂在基础设施故障上没跑完，所以下面是一遍的结论不是两遍的，写出处就是为了让你能自己抽查。

## 先说一条跟出发点相反的

你说 YouMind 把任务、项目、交付三者隔离得很好。**它现在的方向是往回并，不是往开分。**

2026 年 6 月 1 日的 1.0，CPO 自己写：把旧的三个概念（works、materials、conversations）并成两个（Task 和 Files）。原话是 "We took all the old concepts (works, materials, conversations) and collapsed them into two simple ideas"（[caicai.me](https://www.caicai.me/blogs/youmind-10-the-choices-we-made)）。changelog 那一行更直白：`Materials and Craft have merged into Files.`（[updates](https://youmind.com/updates/youmind-update-new-tasks-files-image-editor)）。

并的理由不是技术是转化率。同一篇里写付费转化是健康的，但新用户跑掉，因为 "YouMind felt like a dense textbook. Too many concepts, too many steps that didn't feel natural."

更早还有一次减法。0.8（2026 年 1 月）是他们第一次砍结构而不是加结构，三条自陈的病因：功能膨胀、同一个功能在 A/B/C 三处都有入口、概念之间藏着隐式关系（[caicai.me](https://www.caicai.me/blogs/youmind-finding-product-balance-through-subtraction)）。同一篇里 CPO 数了一下：六个月改了三次界面。

所以「隔离得好」这个印象，多半来自两件具体的事，而不是来自概念分层。下面第三节说这两件事，它们确实值得抄。

## YouMind 现在的名词

| 名词 | 是什么 | 出处 |
| --- | --- | --- |
| Space / Library | 真正的顶层，但从不出现在界面上。每个 Board 都带一个必填 `spaceId`，`/space` 路由被 robots.txt 挡掉 | [openapi.json](https://youmind.com/openapi.json) |
| Board | 用户看得见的顶层容器，一个主题或一个项目一个。删除的级联边界，检索的两个 scope 之一 | [skill.md](https://youmind.com/skill.md) |
| Task | 跟 AI 干一件事的那一次。2026 年 6 月由 Chat 升格而来 | [updates](https://youmind.com/updates/youmind-update-new-tasks-files-image-editor) |
| File | 一个扁平名词，同时装收来的材料和产出的成品 | [skill.md](https://youmind.com/skill.md) |

没有 Project 这个实体。中文社区管 Board 叫项目（[sspai](https://sspai.com/post/103818)），YouMind 自己的 release note 也在同一条里标题写 Project 正文写 board（[updates](https://youmind.com/updates/youmind-update-skill-market-onboarding-task-management)）。

Files 是刻意不区分来源的。CPO 原话 "Files is where everything lives, whether you collected it, processed it, or created it."

底下的骨架从 2025 到 1.0 没变过，是 IPO：Input → Process → Output（[caicai.me](https://www.caicai.me/blogs/youmind-a-bitter-lesson-from-squirrels)）。变的一直是这三段在界面上怎么摆。

## 真正值得抄的两条

### 一，Task 拥有它产出的东西，并且就地打开

`Every Task gives you quick access to everything it has produced. Any output created inside a Task can be opened right where you are.`（[updates](https://youmind.com/updates/youmind-update-new-tasks-files-image-editor)）

这才是「隔离干净」的来源。不是概念分层干净，是**一次会话和它产出的东西绑死，而且不用跳出去看**。1.0 之后交付物甚至没有自己的家了，就在 Task 里编辑（[caicai.me](https://www.caicai.me/blogs/youmind-10-the-choices-we-made)）。

我们这边：交付物表里有 `session_id` 和 `cause`，数据是全的，但 harness 会话里看不见自己产出了什么，要切到交付物页面去翻。这是个真缺口。

### 二，上下文靠显式 @ 引用挂上去，不靠容器成员身份

`atReferences: Optional referenced files, groups, or boards to include as context for the message.`（[openapi.json](https://youmind.com/openapi.json)）

而且 Task 默认是游离的 —— `boardId` 在建 chat 时是可选的，Task 归属用户不归属 Board，Board 只是列表时的一个过滤器。四种粒度可挂：整个 Board、一个 Group、单个 File、或者选中的摘录（[compare/mymind](https://youmind.com/compare/mymind)）。

我们这边**正好相反，而且是对的**：不绑任务的会话直接不让开。原因不一样 —— 他们的容器是主题，我们的容器是一个锁死的口径，一个不知道自己站在哪个窗口上的会话算不出任何能追溯的数。这条不抄。

但粒度那一半可以抄。今天我们的会话要么看得见整个窗口的目录，要么什么都没有。「只把这三张表挂进来」这种中间态不存在。

## 对照表

| | YouMind | FA Foundry | 差在哪 |
| --- | --- | --- | --- |
| 顶层 | Space / Library，藏着 | `var/` 一个store，也藏着 | 一样，都不必露 |
| 项目 | Board，一个主题一个 | task，一个结账期一个 | 一样。我们的 period 字段是他们没有的约束 |
| 会话 | Task，默认游离，可选挂 Board | session，必须绑 task | 我们更紧，理由是口径不是整洁 |
| 口径 | 无对应物 | window + 锁库 + 哈希 | 他们没有这层，也不需要 |
| 材料 | File，跟成品同一个名词 | `inputs/` 归档，跟交付物两个名词 | 我们分，他们并。我们分是因为一边是证据一边是结论 |
| 交付物 | File，产出后默认隐藏，要显式 save 才上架 | deliverable，每一版自动登记 | 他们有草稿/归档的接缝，我们没有 |
| 会话产出的可见性 | Task 里就地看、就地改 | 要切页面 | **我们缺的那条** |
| 上下文挂载 | 显式 @，四种粒度 | 隐式，整个窗口 | 中间粒度我们没有 |
| 跨容器检索 | 两个 scope：全库 / 单 board | 无 | 他们的测评说跨 Board 找东西是弱点，我们连弱点都还没有 |

## 他们踩过的坑，我们已经在坑边上

三条来自第三方测评，都指向同一件事 —— 容器会变成垃圾桶。

- 一个 Board 超过 30 项，组织就开始退化，除非用户手工建子分组（[aboahreviews](https://aboahreviews.com/youmind-review/)）。
- 存在一个结构性的挤压：Board 太空产出的稿子就差，Board 太满就变慢，用户被挤在一个很窄的体量带里（[aishortcutlab](https://aishortcutlab.com/tools/youmind/review)）。
- 失败模式被一个测评说得很准：把堆积误当成进展（[advenboost](https://advenboost.com/youmind-ai/)）。

一个测评的土办法值得记：**把想要的产出物写在 Board 顶上，用交付物给容器定范围**，防止它变成堆场（[aboahreviews](https://aboahreviews.com/youmind-review/)）。

我们的 task 现在就是按这个走的 —— 一个结账期，问题清单先登记再出稿。`record-questions` 事实上就是那个「写在顶上的产出物」。这条我们碰巧已经做对了，但没有意识到它在防什么。

## 不建议抄的

**不抄 Files 那个扁平名词。** 他们并材料和成品，是因为对创作者来说一段引用和一段自己写的话在编辑器里就是同一类东西。对我们不是：`inputs/` 里是被哈希锁住的证据，交付物是从证据算出来的结论。并成一个名词，等于把「这个数哪来的」这个问题从数据模型里删掉 —— 那正是这个产品存在的理由。

**不抄默认游离的会话。** 上面说过了。

**不抄自动建目录结构。** 他们的 agent 在研究过程中自动建 Board 的文件夹结构，初始组织是机器选的（[loudegg](https://www.loudegg.com/youmind-review/)）。在一个会计期里，谁决定分类就是谁决定口径。

## 落到具体动作

按「能拿到多少 / 要动多少」排：

1. **会话里能看见自己产出了什么。** 动 `app/electron/harness/` 的任务条，或者往 harness 页面注一块。数据全都有了（`deliverables` 表带 `session_id` 和 `cause`），缺的只是一个入口。这是四条里最划算的一条，也是 YouMind 唯一一条真正值得抄的界面决策。
2. **交付物的草稿/归档接缝。** 他们产出物默认隐藏、显式 save 才上架。我们每一版自动登记，好处是审计链完整，坏处是交付物页面上一次追问就多一版，翻起来是流水账。可以加一个「这一版是我要给人看的」的标记，不删任何版本。动 `foundry/task.py` 和交付物页面。
3. **中间粒度的上下文挂载。** 「只把这三张表挂进这次会话」。动的是 `record-questions` 和 window 的目录暴露方式，比前两条大，而且要先想清楚它跟锁的关系 —— 挂载粒度变了，追溯链不能跟着变松。
4. **跨 task 的检索。** 他们的弱点，我们还没有。等到有三四个结账期堆起来再说，现在做是空转。
