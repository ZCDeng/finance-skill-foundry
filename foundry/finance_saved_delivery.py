"""Conservative final-response text bound to the current readable saved version."""
from foundry.errors import FoundryError


_LIMIT = "仍待专业复核，不作为审定或过账授权。"
_PENDING = {
    "repair_available": "草稿已保存，待修复",
    "needs_review": "草稿已保存，待复核处理",
    "needs_requirements": "草稿已保存，待补充有效需求",
    "awaiting_input": "草稿已保存，待补充资料",
    "awaiting_manager": "草稿已保存，待经理处理",
}


def saved_delivery(service, result, *, cache=None):
    """Project a reply only; never create a receipt or change a saved verdict.

    Read the actual immutable records through the same reader's current view.
    Matching the entire draft view also detects edited body/claims paired with an
    unchanged content_hash. A missing, stale or mismatched proof stays unverified.
    """
    draft = receipt = None
    try:
        stored = service.analysis._get("drafts", result["id"])
        service._authorize_draft(stored)
        current = service._readable_draft(stored, cache=cache)
        if all(key in result and result[key] == value for key, value in current.items()):
            draft = current
            supplied = result.get("completion")
            if isinstance(supplied, dict):
                stored_receipt = service.analysis._get("completions", supplied["id"])
                viewed = service._readable_receipt(stored_receipt, cache=cache)
                if (viewed == supplied and isinstance(viewed, dict)
                        and viewed.get("draft_id") == draft["id"]
                        and viewed.get("draft_content_hash") == draft.get("content_hash")
                        and viewed.get("task_id") == draft.get("task_id")):
                    receipt = viewed
    except (FoundryError, OSError, KeyError, TypeError, ValueError):
        pass

    complete = (receipt is not None and receipt.get("status") == "complete"
                and receipt.get("response_status") == "complete"
                and receipt.get("original_requirements_completed") is True
                and receipt.get("repair_allowed") is False
                and receipt.get("stop_reason") == "complete"
                and isinstance(draft.get("quality"), dict)
                and draft["quality"].get("status") == "pass")
    status = "complete" if complete else (receipt or {}).get("status", "unverified")
    if not complete and status not in _PENDING:
        status = "unverified"
    if complete:
        line = f"已保存完成，草稿{draft['id']}；{_LIMIT}"
    elif (receipt is not None and receipt.get("stop_reason") == "verified_undefined_result"
          and receipt.get("verified_non_numeric_outcomes") and receipt.get("repair_allowed") is False
          and receipt.get("original_requirements_completed") is False):
        line = f"草稿已保存；收缴率已核验为未定义，原数值要求未完成；草稿{draft['id']}；{_LIMIT}"
    elif draft is not None:
        label = _PENDING.get(status, "草稿已保存，完成状态尚未核实")
        line = f"{label}；草稿{draft['id']}；{_LIMIT}"
    else:
        line = f"保存完成状态尚未核实；{_LIMIT}"
    return {**result, "final_response": line, "delivery_contract": {
        "draft_id": draft["id"] if draft is not None else None,
        "receipt_id": receipt["id"] if receipt is not None else None,
        "completion_status": status,
        "content_scope": "正文内容以已保存草稿为准；逐项模型检查请查看对应运行结果。",
    }}
