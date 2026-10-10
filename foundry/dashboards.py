"""A task's 看板: cards pinned from its calculated results.

A card holds no figure of its own. It names one stored run and which of its rows it shows (``select``), so every
number on the board is a number that run already holds, and opens to the same source as on the result page.

Three kinds:

- ``figure``: one cell, the row ``select.match`` names in ``select.column``.
- ``rank``: one column across the rows ``select.match`` names, each labelled by ``select.label``, sorted by
  ``select.order`` and cut at ``select.limit``.
- ``bridge``: the profit bridge of the variance rows ``select.match`` names.
- ``scenario`` (回款情景): one entity's 本期 lines of a collection-health run, which ``select.match`` names. The card
  moves the collection rate by hand and shows what follows (距生死线, cash operating profit, a year's collections).
  What it shows past the run's own lines is a what-if, never a figure of the run, so the card is never accepted
  and never goes into the close or a report.

Three states (notes/claude-dashboards-borrowing-plan-20261010.md, 八):

- ``explore``: the assistant proposed it; it is not on the board until the manager pins it.
- ``pinned``: on the board, waiting for the manager to accept it.
- ``accepted``: the manager accepted it on the run it shows. Only the manager arranges the board, so only the
  manager accepts; a card moved to another run is pinned again until accepted there.

The board is versioned like every other record here: each save is a new version naming the one it replaced.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from foundry.errors import FoundryError
from foundry.task import now_iso

KINDS = frozenset({"figure", "rank", "bridge", "scenario"})
STATES = frozenset({"explore", "pinned", "accepted"})
TEMPLATES = frozenset({"operating", "collection", "city"})
ORDERS = frozenset({"asc", "desc"})
PROPOSERS = frozenset({"manager", "assistant"})

MAX_CARDS = 40
MAX_TITLE = 60
MAX_NOTE = 200
MAX_MATCH = 8
MAX_SELECT_BYTES = 4096
MAX_RANK = 50

# The bridge reads the profit lines of a variance run (foundry/finance_variance.py).
BRIDGE_METHOD = "revenue_minus_cost_minus_expense"
# The lines a scenario card moves the collection rate against (foundry/collection_metrics.py).
SCENARIO_LINES = ("gross_margin", "expense_ratio", "break_even_collection", "collection_gap")


def _text(value: Any, label: str, *, maximum: int, required: bool = True) -> str | None:
    if value is None or value == "":
        if required:
            raise FoundryError(f"dashboard card {label} is required")
        return None
    if not isinstance(value, str) or not value.strip():
        raise FoundryError(f"dashboard card {label} must be text")
    if len(value) > maximum:
        raise FoundryError(f"dashboard card {label} is longer than {maximum} characters")
    return value.strip()


def _match(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_MATCH:
        raise FoundryError(f"dashboard card match must name at most {MAX_MATCH} columns")
    out = {}
    for column, text in value.items():
        if not isinstance(column, str) or not column or not isinstance(text, (str, int, float)) or isinstance(text, bool):
            raise FoundryError("dashboard card match maps a column to the text it holds")
        out[column] = str(text)
    return out


def matching_rows(rows: list[dict], match: dict[str, str]) -> list[tuple[int, dict]]:
    """The rows whose every named column holds the named text, as collection_metrics matches a source row."""
    def cell(row: dict, column: str) -> str:
        value = row.get(column)
        return "" if value is None else str(value).strip()

    return [(index, row) for index, row in enumerate(rows)
            if isinstance(row, dict) and all(cell(row, column) == text.strip() for column, text in match.items())]


def _numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    try:
        float(value.strip())
    except ValueError:
        return False
    return True


def normalize_select(kind: str, select: Any, run: dict) -> dict:
    """The card's selector, checked against the run it reads: a card that would draw nothing is refused here."""
    if not isinstance(select, dict):
        raise FoundryError("dashboard card select must be an object")
    if len(json.dumps(select, ensure_ascii=False)) > MAX_SELECT_BYTES:
        raise FoundryError("dashboard card select is too large")
    result = run.get("result") or {}
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    match = _match(select.get("match"))
    found = matching_rows(rows, match)
    if kind == "figure":
        column = _text(select.get("column"), "column", maximum=200)
        if len(found) != 1:
            raise FoundryError(f"a figure card must name exactly one row of its run; it names {len(found)}")
        if column not in found[0][1]:
            raise FoundryError(f"the run has no column {column}")
        return {"match": match, "column": column}
    if kind == "rank":
        column = _text(select.get("column"), "column", maximum=200)
        label = _text(select.get("label"), "label", maximum=200)
        order = select.get("order", "desc")
        if order not in ORDERS:
            raise FoundryError("a rank card orders asc or desc")
        limit = select.get("limit", 10)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_RANK:
            raise FoundryError(f"a rank card shows 1 to {MAX_RANK} rows")
        ranked = [row for _, row in found if _numeric(row.get(column)) and row.get(label) not in (None, "")]
        if len(ranked) < 2:
            raise FoundryError("a rank card needs at least two rows with a figure to rank")
        out = {"match": match, "column": column, "label": label, "order": order, "limit": limit}
        if select.get("reference") is not None:
            reference = select["reference"]
            if not isinstance(reference, dict) or not _numeric(reference.get("value")):
                raise FoundryError("a rank card reference is a figure with a label")
            out["reference"] = {"value": str(reference["value"]),
                                "label": _text(reference.get("label"), "reference label", maximum=MAX_TITLE)}
        return out
    if kind == "scenario":
        if result.get("scenario_kind") != "collection_health":
            raise FoundryError("a scenario card reads a collection health result")
        if len({row.get("entity") for _, row in found}) != 1:
            raise FoundryError("a scenario card reads the lines of one entity")
        for key in SCENARIO_LINES:
            if sum(1 for _, row in found if row.get("metric_key") == key) != 1:
                raise FoundryError(f"a scenario card needs one {key} line of its entity; name the 本期 lines")
        return {"match": match}
    if result.get("method") != BRIDGE_METHOD:
        raise FoundryError("a bridge card reads a budget or prior-period variance result")
    if not any(row.get("metric") == "profit" for _, row in found):
        raise FoundryError("a bridge card must name rows with a profit line")
    return {"match": match}


def signature(card: dict) -> str:
    """What a card shows, for telling two cards apart: the same run, kind and rows read alike."""
    return json.dumps([card["kind"], card["run_id"], card["select"]], ensure_ascii=False, sort_keys=True)


def normalize_card(card: Any, *, run_of, previous: dict | None, proposer: str, state: str | None = None) -> dict:
    """One card as stored. ``run_of`` reads a run the caller may read; ``previous`` is the stored card of the same id."""
    if not isinstance(card, dict):
        raise FoundryError("dashboard card must be an object")
    kind = card.get("kind")
    if kind not in KINDS:
        raise FoundryError("dashboard card kind must be figure, rank, bridge or scenario")
    state = state or card.get("state", "pinned")
    if state not in STATES:
        raise FoundryError("dashboard card state must be explore, pinned or accepted")
    if kind == "scenario" and state == "accepted":
        raise FoundryError("a scenario card is never accepted; what it shows is a what-if, not a figure of the run")
    run = run_of(card.get("run_id"))
    if run.get("execution_status") not in {"succeeded", "success"}:
        raise FoundryError("a dashboard card reads a run that succeeded")
    template = card.get("template")
    if template is not None and template not in TEMPLATES:
        raise FoundryError("dashboard card template must be operating, collection or city")
    stored = {
        "id": previous["id"] if previous else uuid.uuid4().hex,
        "kind": kind,
        "title": _text(card.get("title"), "title", maximum=MAX_TITLE),
        "state": state,
        "run_id": run["id"],
        "select": normalize_select(kind, card.get("select"), run),
        "template": template,
        "note": _text(card.get("note"), "note", maximum=MAX_NOTE, required=False),
        "proposed_by": previous["proposed_by"] if previous else proposer,
        "accepted": None,
    }
    if state == "accepted":
        kept = previous.get("accepted") if previous and previous.get("state") == "accepted" else None
        stored["accepted"] = kept if kept and kept.get("run_id") == run["id"] else {"run_id": run["id"], "at": now_iso()}
    # What a recompute said of the card (dashboard_recompute) holds while the card stays on that run; no caller writes it.
    same_run = previous is not None and previous.get("run_id") == run["id"]
    stored["recomputed"] = previous.get("recomputed") if same_run else None
    stored["recompute_failed"] = previous.get("recompute_failed") if same_run else None
    return stored


def arrange(cards: Any, previous: list[dict], *, run_of) -> list[dict]:
    """The manager's board: every card as stored, a known card keeping its id, who proposed it and when it was accepted."""
    if not isinstance(cards, list):
        raise FoundryError("dashboard cards must be a list")
    if len(cards) > MAX_CARDS:
        raise FoundryError(f"a dashboard holds at most {MAX_CARDS} cards")
    by_id = {card["id"]: card for card in previous}
    stored, seen = [], set()
    for card in cards:
        card_id = card.get("id") if isinstance(card, dict) else None
        if card_id is not None and card_id not in by_id:
            raise FoundryError("dashboard card is not on this board; read the board again")
        if card_id is not None and card_id in seen:
            raise FoundryError("dashboard card is listed twice")
        seen.add(card_id)
        if card_id is None and isinstance(card, dict) and card.get("state") == "explore":
            raise FoundryError("only the assistant proposes an explore card")
        stored.append(normalize_card(card, run_of=run_of, previous=by_id.get(card_id), proposer="manager"))
    signatures = [signature(card) for card in stored]
    if len(set(signatures)) != len(signatures):
        raise FoundryError("two dashboard cards show the same thing")
    return stored


def propose(card: Any, previous: list[dict], *, run_of) -> list[dict]:
    """The board with one more explore card from the assistant. A card the board already shows is not added twice."""
    if isinstance(card, dict) and card.get("id") is not None:
        raise FoundryError("a proposed card is new; it has no id")
    stored = normalize_card(card, run_of=run_of, previous=None, proposer="assistant", state="explore")
    if signature(stored) in {signature(row) for row in previous}:
        raise FoundryError("the board already has this card")
    if len(previous) >= MAX_CARDS:
        raise FoundryError(f"a dashboard holds at most {MAX_CARDS} cards")
    return [*previous, stored]
