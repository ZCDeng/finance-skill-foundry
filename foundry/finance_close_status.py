"""One answer to "where is this month's close": the six blocks and the line at the top.

The month-close control center (app MonthCloseControlCenter) shows what this
returns and nothing else, so no panel can call a close finished on its own
terms. The top line is one of five, never a bare 完成 or 通过:

    尚未准备   something in 范围 / 来源 / 结构 still has to be confirmed
    可计算     those are confirmed and nothing has been calculated yet
    需要复核   calculated, but a control, a difference or the draft still needs work
    可提交经理复核  everything the system can check is clear; a person signs it off
    已归档     the task is archived with what it held then

Pure: ``close_status`` takes the facts the store already holds and decides.
"""

from __future__ import annotations

from typing import Any

SCOPE_REQUIRED = (("period", "期间"), ("organization", "组织"), ("unit", "单位"), ("currency", "币种"))

NOT_READY = "not_ready"
CALCULABLE = "calculable"
NEEDS_REVIEW = "needs_review"
READY_FOR_REVIEW = "ready_for_review"
ARCHIVED = "archived"

DONE = "done"
BLOCKED = "blocked"
ATTENTION = "attention"
NOT_STARTED = "not_started"

ISSUE_TEXT = {
    "open": "差异待处理",
    "pending_external": "待外部确认",
    "awaiting_reimport": "待重新导入修正后的资料",
    "awaiting_review": "接受差异待第二人复核",
    "stale": "资料已更新，控制需要在新版本上重新确认",
    "not_run": "已确认但还没运行",
}


def close_status(
    *,
    archived: bool,
    scope: dict[str, Any] | None,
    scope_seq: int | None,
    datasets: list[dict[str, Any]],
    superseded: int,
    pending_structures: list[str],
    controls: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    draft: dict[str, Any] | None,
) -> dict[str, Any]:
    blocks = [
        _scope_block(scope),
        _source_block(datasets, superseded),
        _structure_block(datasets, pending_structures),
        _controls_block(controls),
        _exceptions_block(controls),
        _review_block(runs, draft, scope_seq),
    ]
    must = [item["text"] for block in blocks[:3] for item in block["items"] if item["blocking"]]
    later = [item["text"] for block in blocks[3:] for item in block["items"] if item["blocking"]]
    succeeded = [run for run in runs if run.get("execution_status") == "succeeded"]
    conflicts = sum(1 for row in controls if (row.get("issue") or {}).get("blocking") and row.get("state") == "confirmed"
                    and (row.get("issue") or {}).get("state") in {"open", "pending_external", "awaiting_reimport", "awaiting_review"})
    if archived:
        state, text = ARCHIVED, "已归档：保留当时快照与版本"
    elif must:
        state, text = NOT_READY, f"尚未准备：还有 {len(must)} 项必须确认"
    elif not succeeded:
        state, text = CALCULABLE, "可计算：范围和结构已确认"
    elif later:
        detail = f"有 {conflicts} 项来源冲突" if conflicts and conflicts == len(later) else f"还有 {len(later)} 项待处理"
        state, text = NEEDS_REVIEW, f"需要复核：计算完成，但{detail}"
    else:
        state, text = READY_FOR_REVIEW, "可提交经理复核"
    return {
        "schema_version": 1,
        "headline": {"state": state, "text": text},
        "blocks": blocks,
        "blocking": [*must, *later],
    }


def _block(key: str, label: str, items: list[dict[str, Any]], *, empty_state: str = DONE) -> dict[str, Any]:
    if any(item["blocking"] for item in items):
        state = BLOCKED
    elif any(item.get("attention") for item in items):
        state = ATTENTION
    else:
        state = empty_state
    return {"key": key, "label": label, "state": state, "items": items}


def _item(text: str, *, blocking: bool = False, attention: bool = False, target: str | None = None) -> dict[str, Any]:
    return {"text": text, "blocking": blocking, "attention": attention, **({"target": target} if target else {})}


def _scope_block(scope: dict[str, Any] | None) -> dict[str, Any]:
    scope = scope or {}
    items = [
        _item(f"{label}未确认", blocking=True, target="scope")
        for key, label in SCOPE_REQUIRED
        if not str(scope.get(key) or "").strip()
    ]
    if not items:
        items.append(_item(" · ".join(str(scope[key]) for key, _ in SCOPE_REQUIRED), target="scope"))
    return _block("scope", "范围", items)


def _source_block(datasets: list[dict[str, Any]], superseded: int) -> dict[str, Any]:
    if not datasets:
        return _block("source", "来源", [_item("还没有资料", blocking=True, target="datasets")])
    items = [_item(f"{row.get('name') or '资料'} · 摘要 {str(row.get('source_hash') or '')[:12]}", target="datasets") for row in datasets]
    if superseded:
        items.append(_item(f"另有 {superseded} 份旧版本已被更新的资料取代，只读保留", attention=False))
    return _block("source", "来源", items)


def _structure_block(datasets: list[dict[str, Any]], pending: list[str]) -> dict[str, Any]:
    if not datasets:
        return _block("structure", "结构", [], empty_state=NOT_STARTED)
    if pending:
        return _block("structure", "结构", [_item(f"{name} 的表结构等你确认", blocking=True, target="structure") for name in pending])
    return _block("structure", "结构", [_item("表头、明细范围和合计行已确认", target="structure")])


def _controls_block(controls: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed = [row for row in controls if row.get("state") == "confirmed"]
    if not confirmed:
        return _block("controls", "控制", [_item("还没有确认的勾稽控制", blocking=True, target="controls")])
    items = []
    for row in confirmed:
        issue = row.get("issue") or {}
        state = issue.get("state")
        if state in {"stale", "not_run"}:
            items.append(_item(f"{row['control']['label']}：{ISSUE_TEXT[state]}", blocking=True, target="controls"))
        elif (row.get("result") or {}).get("status") == "error" and state == "open":
            items.append(_item(f"{row['control']['label']}：读不出", blocking=True, target="controls"))
    passed = sum(1 for row in confirmed if (row.get("result") or {}).get("status") == "pass")
    items.append(_item(f"已确认 {len(confirmed)} 条，相符 {passed} 条", target="controls"))
    return _block("controls", "控制", items)


def _exceptions_block(controls: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for row in controls:
        issue = row.get("issue") or {}
        status = (row.get("result") or {}).get("status")
        if row.get("state") != "confirmed" or status != "break":
            continue
        if issue.get("blocking"):
            difference = (row.get("result") or {}).get("difference")
            items.append(_item(f"{row['control']['label']}：{ISSUE_TEXT.get(issue.get('state'), '待处理')}，差额 {difference}", blocking=True, target="controls"))
        elif issue.get("state") == "waived":
            reason = (issue.get("disposition") or {}).get("reason") or ""
            items.append(_item(f"{row['control']['label']}：已接受差异（{reason}）", attention=True, target="controls"))
    return _block("exceptions", "异常", items or [_item("没有未处置的差异")])


def _review_block(runs: list[dict[str, Any]], draft: dict[str, Any] | None, scope_seq: int | None) -> dict[str, Any]:
    succeeded = [run for run in runs if run.get("execution_status") == "succeeded"]
    if not succeeded:
        return _block("review", "复核", [_item("还没有计算结果", target="results")], empty_state=NOT_STARTED)
    items = []
    last_run = max(run.get("seq", 0) for run in succeeded)
    if scope_seq is not None and scope_seq > last_run:
        items.append(_item("范围在上次计算之后改过，请重新计算", blocking=True, target="results"))
    if draft is None:
        items.append(_item("还没有文稿", blocking=True, target="drafts"))
        return _block("review", "复核", items)
    if draft.get("seq", 0) < last_run:
        items.append(_item("文稿早于最新一次计算，请按新结果更新", blocking=True, target="drafts"))
    dimensions = ((draft.get("explanation_check") or {}).get("status_dimensions") or {})
    # Executed is not cited, cited is not sourced: each has to pass on its own. A dimension the
    # draft never set up (not_configured) is unverified, not clear.
    for key, label in (("execution", "执行状态"), ("numeric_citation", "数值引用"), ("source_validation", "来源核验")):
        dimension = dimensions.get(key) or {}
        status = dimension.get("status")
        if status != "pass":
            words = "未核验" if status in {None, "not_configured", "unverified"} else "需要处理"
            items.append(_item(f"文稿{dimension.get('label') or label}：{words}", blocking=True, target="drafts"))
    review = (dimensions.get("professional_review") or {}).get("status")
    items.append(_item("经理已复核" if review == "pass" else "经理尚未复核（提交后由经理完成）", target="drafts"))
    return _block("review", "复核", items)
