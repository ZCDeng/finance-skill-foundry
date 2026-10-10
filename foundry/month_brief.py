"""本月三句话: what moved most, the biggest risk and what waits on the manager, each picked by a rule from results the
task already holds (notes/intelligent-ui-borrowing-plan-20261010.md, 五).

- 变化: the board's cards run again on newer files or carried from last month (foundry/dashboard_recompute.py), the one
  that moved most: a light that changed first, then a figure that changed sign or a ranking that gained or lost one past
  its line, then the figure furthest past the line a recompute marks a change at.
- 风险: the 风险雷达 of the newest 回款健康 run, the entity scoring highest.
- 等你拍板: the task's 等你处理 as 总览 lists it (foundry/overview.py close_todo), and the board's cards waiting to be
  accepted.

The rule writes each line and names where each figure in it came from; nothing is calculated here. The assistant may
reword a line (``word``) but keeps every figure and link as written and adds no other figure; the wording is kept beside
the figures it was written for and set aside the moment they change.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from typing import Any

from foundry.dashboard_recompute import CHANGE_POINTS, CHANGE_SHARE, _number, _sign
from foundry.dashboards import WHAT_IF
from foundry.errors import FoundryError

LABELS = {"change": "变化", "risk": "风险", "waiting": "等你拍板"}
LEVEL_ORDER = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
WORDS = {"red": "红色", "orange": "橙色"}
MAX_WORDED = 120
DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
SCORE = re.compile(r"（\d+分）")


def _text(text: str) -> dict:
    return {"text": text}


def _part(text: str, ref: dict) -> dict:
    """A figure, or words that open what they name: the manager clicks it to see where it came from."""
    return {"text": text, "ref": ref}


def _line(key: str, parts: list[dict], **more) -> dict:
    return {"key": key, "label": LABELS[key], "parts": parts, "text": "".join(part["text"] for part in parts), **more}


def _board(store) -> dict:
    board = store._dashboard() or {}
    return store._dashboard_in_view(board) if board and store.allowed is not None else board


# -- 变化 ---------------------------------------------------------------------------------------------------------------

def _past_line(before: dict, after: dict) -> Decimal:
    """How many times past the line a recompute marks a change at (1 个百分点, or a tenth) the figure moved."""
    old, new = _number(before.get("value")), _number(after.get("value"))
    if old is None or new is None:
        return Decimal(0)
    rate = after.get("rate") or ("points" if after.get("unit") in ("%", "百分点") else None)
    if rate:
        return abs(new - old) * (100 if rate == "fraction" else 1) / CHANGE_POINTS
    return abs(new - old) / abs(old) / CHANGE_SHARE if old else Decimal(1)


def _weight(card: dict) -> tuple:
    """The card's place among the others: (whether the recompute marked it, how it moved, whether for the worse, by how
    much). A figure inside the line still says how far it moved, so the one that moved most is named all the same."""
    said = card["recomputed"]
    before, after = said.get("before") or {}, said.get("after") or {}
    marked = bool(said.get("changed"))
    if card["kind"] == "figure":
        old, new = LEVEL_ORDER.get(before.get("level")), LEVEL_ORDER.get(after.get("level"))
        if old is not None and new is not None and old != new:
            return marked, 3, new > old, Decimal(abs(new - old))
        if _sign(_number(before.get("value"))) * _sign(_number(after.get("value"))) < 0:
            return marked, 2, False, Decimal(0)
        return marked, 1, False, _past_line(before, after)
    if not marked:
        return marked, 0, False, Decimal(0)
    if card["kind"] == "rank":
        was, now = before.get("beyond"), after.get("beyond")
        if was is not None and now is not None and len(was) != len(now):
            return marked, 2, len(now) > len(was), Decimal(abs(len(now) - len(was)))
        return marked, 1, False, Decimal(1)
    return marked, 2, False, Decimal(0)


def _moved(card: dict, after_title: str = "") -> list[dict]:
    """「title」从 before 变为 after，change: the figures as the board showed them, the change in the recompute's words."""
    said = card["recomputed"]
    ref = {"kind": "card", "card_id": card["id"]}
    parts = [_text(f"「{card['title']}」{after_title}")]
    before, after = (said.get("before") or {}).get("display"), (said.get("after") or {}).get("display")
    if card["kind"] == "figure" and after:
        if before:
            parts += [_text("从 "), _part(str(before), {"kind": "card_before", "card_id": card["id"]}), _text(" 变为 ")]
        else:
            parts.append(_text("现在是 "))
        parts += [_part(str(after), ref), _text("，")]
    words = said.get("change") or "有变化"
    # 「+0.29 个百分点」 reads as a change only with the word for it; 「级别 黄 → 红」 says so itself.
    return [*parts, *([_text("变动 ")] if words[:1] in "+-" else []), _part(words, {"kind": "card_change", "card_id": card["id"]}),
            _text("。")]


def _change_line(store) -> dict:
    board = _board(store)
    cards = [card for card in board.get("cards", []) if card.get("state") in ("pinned", "accepted")
             and card.get("kind") not in WHAT_IF and card.get("recomputed")]
    to_board = {"kind": "open", "target": "dashboard"}
    if not cards:
        return _line("change", [_text("看板上还没有按新资料重算过的卡，暂时没有可比的变化。")])
    # The board's order breaks ties: the card the manager put first.
    ranked = sorted(cards, key=_weight, reverse=True)
    top = ranked[0]
    moved = sum(bool(card["recomputed"].get("changed")) for card in cards)
    if moved:
        parts = _moved(top)
        if moved > 1:
            parts += [_text("另有 "), _part(f"{moved - 1} 张卡", to_board), _text("也有变化。")]
        return _line("change", parts)
    head = [_text("看板上 "), _part(f"{len(cards)} 张卡", to_board),
            _text(f"按新资料重算，变动都不到 {CHANGE_POINTS} 个百分点或 {CHANGE_SHARE * 100:.0f}%")]
    if top["kind"] != "figure" or not _weight(top)[3]:
        return _line("change", [*head, _text("，数都没有变。") if top["kind"] == "figure" else _text("。")])
    return _line("change", [*head, _text("；动得最多的是"), *_moved(top, "，")])


# -- 风险 ---------------------------------------------------------------------------------------------------------------

def _health(run: dict) -> bool:
    result = run.get("result") or {}
    return run.get("engine") == "finance" and result.get("scenario_kind") == "collection_health" \
        and isinstance(result.get("rows"), list)


def _latest_health(store) -> dict | None:
    runs = [run for run in store.analysis._list("runs") if run.get("execution_status") == "succeeded" and _health(run)
            and (store.allowed is None or set((run.get("bindings") or {}).values()) <= store.allowed)]
    if not runs:
        return None
    return store._named_run(max(runs, key=lambda run: (run.get("seq", 0), run.get("created_at") or ""))["id"])


def _hits(note: Any) -> str:
    """The signals a score was taken from, without their points: 营业利润为负、减值占毛利高."""
    found = re.search(r"触发：([^；]*)", note if isinstance(note, str) else "")
    return SCORE.sub("", found[1]).strip() if found else ""


def _risk_line(store) -> dict:
    run = _latest_health(store)
    if run is None:
        return _line("risk", [_text("还没有风险雷达：做一次回款健康分析后，这里写风险最高的主体。")], ask="collection-health")
    rows = [row for row in run["result"]["rows"] if isinstance(row, dict) and row.get("metric_key") == "risk_score"
            and row.get("scenario") == "本期" and _number(row.get("value")) is not None]
    result = {"kind": "result", "run_id": run["id"]}
    if not rows:
        return _line("risk", [_text("最近一次"), _part("回款健康分析", result), _text("没有风险雷达：每个主体能判断的信号都不到两项。")])
    # The run's own order breaks ties: the group before its cities, the cities as the workbook lists them.
    rows.sort(key=lambda row: (LEVEL_ORDER.get(row.get("level"), -1), _number(row["value"])), reverse=True)
    top = rows[0]
    if LEVEL_ORDER.get(top.get("level")) == 0:
        return _line("risk", [_text("风险雷达上 "), _part(f"{len(rows)} 个主体", result),
                              _text("都是绿色，没有要先看的。" if len(rows) > 1 else "是绿色，没有要先看的。")])
    match = {"entity": str(top["entity"]), "metric_key": "risk_score", "scenario": "本期"}
    if top.get("entity_origin"):
        match["entity_origin"] = str(top["entity_origin"])
    figure = {"kind": "row", "run_id": run["id"], "match": match, "column": "value", "metric": f"{top['entity']}风险雷达"}
    parts = [_text(f"{top['entity']}风险雷达 "), _part(str(top.get("display_value") or top["value"]), figure),
             _text(f"（{top.get('level_label') or top.get('level')}）")]
    hits = _hits(top.get("note"))
    parts.append(_text(f"，触发{hits}。" if hits else "。"))
    others = [(level, sum(row.get("level") == level for row in rows[1:])) for level in ("red", "orange")]
    others = [(level, count) for level, count in others if count]
    if len(others) == 1:
        parts += [_text("另有 "), _part(f"{others[0][1]} 个主体", result), _text(f"是{WORDS[others[0][0]]}。")]
    elif others:
        parts += [_text("另有 "), _part(f"{others[0][1]} 个{WORDS['red']}", result), _text("、"),
                  _part(f"{others[1][1]} 个{WORDS['orange']}", result), _text("的主体。")]
    return _line("risk", parts)


# -- 等你拍板 -----------------------------------------------------------------------------------------------------------

def _waiting_line(store) -> dict:
    from foundry.overview import close_todo

    todo = close_todo(store.task, store.finance_close_status({}))
    waiting = [card for card in _board(store).get("cards", []) if card.get("state") == "pinned" and card.get("kind") not in WHAT_IF]
    parts = []
    if todo:
        first = todo[0]
        parts += [_part(f"{len(todo)} 件事", {"kind": "open", "target": "close"}), _text("等你处理，先看："),
                  _part(first["text"], {"kind": "open", "target": first.get("target") or "close"}), _text("。")]
    if waiting:
        parts += [_text("看板还有 " if todo else "没有挡住月结的事；看板上 "), _part(f"{len(waiting)} 张卡", {"kind": "open", "target": "dashboard"}),
                  _text("等你认可。")]
    return _line("waiting", parts or [_text("没有等你拍板的事：月结没有挡着的事项，看板上的卡也都认可了。")])


# -- the three, and their wording ---------------------------------------------------------------------------------------

def _safe(pick, store, key: str) -> dict:
    """One line that cannot be read says so; the other two still stand."""
    try:
        return pick(store)
    except (FoundryError, OSError, ValueError, KeyError, TypeError) as exc:
        return _line(key, [_text(f"暂时读不出：{exc}")], failed=True)


def _signature(lines: list[dict]) -> str:
    body = [[line["key"], [[part["text"], part.get("ref")] for part in line["parts"]]] for line in lines]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def brief(store) -> dict:
    lines = [_safe(_change_line, store, "change"), _safe(_risk_line, store, "risk"), _safe(_waiting_line, store, "waiting")]
    signature = _signature(lines)
    worded = next((record for record in reversed(store._list("month_briefs")) if record.get("signature") == signature), None)
    return {"schema_version": 1, "lines": lines, "signature": signature,
            "worded": {key: worded[key] for key in ("lines", "by", "created_at")} if worded else None}


def word(store, spec: Any) -> dict:
    """The assistant's wording of the lines it was given: every figure and link kept as written, no figure added."""
    if not isinstance(spec, dict):
        raise FoundryError("month brief wording must be an object")
    current = brief(store)
    if spec.get("signature") != current["signature"]:
        raise FoundryError("本月三句话的数已经变了：先用 month_brief 重新读，再按新的原句改写")
    asked = spec.get("lines")
    if not isinstance(asked, dict) or not asked or set(asked) - set(LABELS):
        raise FoundryError("lines names change, risk or waiting, each with its new wording")
    lines = {line["key"]: line for line in current["lines"]}
    # A line not named keeps the wording it has: the assistant may reword one sentence at a time.
    kept = dict(current["worded"]["lines"]) if current["worded"] else {}
    for key, text in asked.items():
        label, line = LABELS[key], lines[key]
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_WORDED or "\n" in text.strip():
            raise FoundryError(f"{label}：改写是一行字，不超过 {MAX_WORDED} 个字")
        if line.get("failed"):
            raise FoundryError(f"{label}：这一句没读出来，不能改写")
        text = text.strip()
        missing = [part["text"] for part in line["parts"] if part.get("ref") and part["text"] not in text]
        if missing:
            raise FoundryError(f"{label}：要原样保留「{'」「'.join(missing)}」，数和能点开的部分不能改")
        added = sorted(set(DIGITS.findall(text)) - set(DIGITS.findall(line["text"])))
        if added:
            raise FoundryError(f"{label}：原句里没有 {'、'.join(added)}，只能改措辞，不能加数")
        kept[key] = text
    store._write("month_briefs", signature=current["signature"], lines=kept, by=store.actor, bindings={})
    return brief(store)
