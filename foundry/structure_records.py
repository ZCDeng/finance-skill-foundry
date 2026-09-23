"""The lifecycle of a table structure: proposed, confirmed, acknowledged, withdrawn.

Who confirmed a structure is not something a request may claim. The call layer
stamps it — the desktop app says `manager` for a click the manager made, and
anything that arrives unstamped is recorded as `assistant`, which needs the
manager's acknowledgement before it counts as reviewed. A missed stamp
therefore costs an extra acknowledgement, never a silent promotion to the
highest trust level.
"""

from __future__ import annotations

from typing import Any

from foundry.errors import FoundryError

MANAGER = "manager"
ASSISTANT = "assistant"
TEMPLATE = "template"
SOURCES = frozenset({MANAGER, ASSISTANT, TEMPLATE})

CONFIRMED = "confirmed"
PENDING_ACKNOWLEDGEMENT = "pending_acknowledgement"
ACKNOWLEDGED = "acknowledged"
WITHDRAWN = "withdrawn"
STATES = frozenset({CONFIRMED, PENDING_ACKNOWLEDGEMENT, ACKNOWLEDGED, WITHDRAWN})
ACTIVE_STATES = frozenset({CONFIRMED, PENDING_ACKNOWLEDGEMENT, ACKNOWLEDGED})

# A dataset the proposal flow never touched — a CSV, a JSON table, a runner
# output. It is not pending anything, and binding it stays exactly as it was.
NOT_APPLICABLE = "not_applicable"
PENDING_CONFIRMATION = "pending_confirmation"
NO_TABLE = "no_table"
BINDABLE_STATES = frozenset(
    {NOT_APPLICABLE, CONFIRMED, PENDING_ACKNOWLEDGEMENT, ACKNOWLEDGED}
)

# A confirmation request carries a declaration, never a way to reach the disk.
FORBIDDEN_SPEC_KEYS = frozenset(
    {"path", "url", "file", "bytes", "preview_path", "allowedRoot", "data"}
)
# Provenance is stamped by the call layer; a request that claims it is stripped.
CLAIMED_SOURCE_KEYS = ("source", "actor", "confirmed_by")


def resolve_source(actor: str | None) -> str:
    """The trust level a call carries. Unstamped means assistant, never manager."""
    text = str(actor or "").strip().casefold()
    if text == MANAGER:
        return MANAGER
    if text in {ASSISTANT, ""}:
        return ASSISTANT
    raise FoundryError("actor must be manager or assistant")


def reject_forbidden_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise FoundryError("structure confirmation spec must be an object")
    extra = FORBIDDEN_SPEC_KEYS & set(spec)
    if extra:
        raise FoundryError(
            "structure confirmation cannot take a path, URL or workbook bytes"
        )
    return spec


def strip_claimed_source(spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop any self-reported provenance and say which keys were dropped."""
    claimed = [key for key in CLAIMED_SOURCE_KEYS if key in spec]
    if not claimed:
        return spec, []
    return {key: value for key, value in spec.items() if key not in claimed}, claimed


def state_for_source(source: str) -> str:
    """A manager's own confirmation is reviewed; anyone else's awaits her word."""
    return CONFIRMED if source == MANAGER else PENDING_ACKNOWLEDGEMENT


def active_confirmation(confirmations: list[dict]) -> dict | None:
    """The confirmation currently in force for a shell, if any.

    An acknowledgement or a withdrawal is filed as its own record pointing back
    at the one it settles, so the record it names is no longer in force.
    """
    settled = {
        record["parent_id"] for record in confirmations if record.get("parent_id")
    }
    for record in sorted(confirmations, key=lambda row: row.get("seq", 0), reverse=True):
        if record["id"] in settled:
            continue
        if record.get("state") in ACTIVE_STATES:
            return record
    return None


def latest_proposal(proposals: list[dict]) -> dict | None:
    if not proposals:
        return None
    return max(proposals, key=lambda row: (row.get("revision", 0), row.get("seq", 0)))


def structure_state(
    proposal: dict | None, confirmations: list[dict], *, is_snapshot: bool = False
) -> str:
    """What the data list and the readiness report say about one dataset."""
    if is_snapshot:
        if not confirmations:
            return NOT_APPLICABLE
        confirmation = max(confirmations, key=lambda row: row.get("seq", 0))
        state = confirmation.get("state")
        if state == WITHDRAWN:
            return WITHDRAWN
        if state == PENDING_ACKNOWLEDGEMENT:
            return PENDING_ACKNOWLEDGEMENT
        return CONFIRMED
    if proposal is None:
        return NOT_APPLICABLE
    # A table nothing can be derived from leaves her nothing to confirm, so the
    # file is "no table" rather than forever pending: otherwise readiness would
    # report pending_structure with no action that could ever clear it.
    if not any(
        sheet.get("decision") == "table" and not sheet.get("blocked_reason")
        for sheet in proposal.get("sheets") or []
    ):
        return NO_TABLE
    active = active_confirmation(confirmations)
    if active is None:
        return PENDING_CONFIRMATION
    return (
        PENDING_ACKNOWLEDGEMENT
        if active["state"] == PENDING_ACKNOWLEDGEMENT
        else CONFIRMED
    )


def assert_bindable(dataset_id: str, state: str, *, is_shell: bool) -> None:
    """Refuse a binding the structure flow has not settled.

    A workbook waiting for its card is refused, and so is a table the manager
    withdrew. A plain table the flow never replaced is bound exactly as before.
    """
    if state in BINDABLE_STATES:
        return
    if state in {PENDING_CONFIRMATION, NO_TABLE} and not is_shell:
        return
    reason = "pending_structure" if state in {PENDING_CONFIRMATION, NO_TABLE} else state
    raise FoundryError(
        f"dataset {dataset_id} cannot be bound while its table structure is {reason}"
    )


def assert_confirmable(declaration_sheets: list[dict]) -> None:
    """Refuse a confirmation that still leaves a debit/credit side unchosen."""
    from foundry.structure_proposal import has_undecided_direction

    tables = [sheet for sheet in declaration_sheets if sheet.get("decision") == "table"]
    if not tables:
        raise FoundryError("structure confirmation requires at least one table sheet")
    _reject_duplicate_or_overlapping_blocks(tables)
    _reject_missing_column_exclusion_reasons(tables)
    undecided = [sheet["sheet"] for sheet in tables if has_undecided_direction(sheet)]
    if undecided:
        raise FoundryError(
            "choose the debit/credit side before confirming: " + ", ".join(undecided)
        )


def _reject_duplicate_or_overlapping_blocks(tables: list[dict]) -> None:
    seen: set[tuple[str, str]] = set()
    rectangles: list[tuple[str, dict[str, int], str]] = []
    for sheet in tables:
        name = str(sheet.get("sheet") or "")
        bounds = _table_bounds(sheet)
        block_id = str(sheet.get("selected_block_id") or _bounds_key(bounds))
        key = (name, block_id)
        if key in seen:
            raise FoundryError(f"duplicate table block confirmation: {name} {block_id}")
        seen.add(key)
        for existing_name, existing, existing_id in rectangles:
            if existing_name == name and _overlaps(existing, bounds):
                raise FoundryError(
                    f"overlapping table block confirmation: {name} {existing_id} and {block_id}"
                )
        rectangles.append((name, bounds, block_id))


def _reject_missing_column_exclusion_reasons(tables: list[dict]) -> None:
    for sheet in tables:
        missing = [
            column.get("letter") or column.get("display") or "unknown"
            for column in sheet.get("columns") or []
            if column.get("include") is False and not str(column.get("exclusion_reason") or "").strip()
        ]
        if missing:
            raise FoundryError(
                f"excluded columns require a reason on {sheet.get('sheet')}: {', '.join(map(str, missing))}"
            )


def _table_bounds(sheet: dict) -> dict[str, int]:
    block = _selected_block(sheet)
    start_row = _positive_int(sheet.get("start_row") or block.get("start_row") or sheet.get("header_row"), "start row")
    end_row = _positive_int(sheet.get("end_row") or block.get("end_row"), "end row")
    start_column = str(sheet.get("start_column") or block.get("start_column") or "").upper()
    end_column = str(sheet.get("end_column") or block.get("end_column") or "").upper()
    if not start_column or not end_column:
        raise FoundryError(f"table bounds require columns on {sheet.get('sheet')}")
    start_col = _column_index(start_column)
    end_col = _column_index(end_column)
    if start_row > end_row or start_col > end_col:
        raise FoundryError(f"invalid table bounds on {sheet.get('sheet')}")
    return {"start_row": start_row, "end_row": end_row, "start_col": start_col, "end_col": end_col}


def _selected_block(sheet: dict) -> dict:
    selected = sheet.get("selected_block_id")
    blocks = sheet.get("table_blocks") or []
    if selected:
        match = next((block for block in blocks if block.get("id") == selected), None)
        if match is None:
            raise FoundryError(f"selected table block is not in proposal: {sheet.get('sheet')}")
        return match
    return {}


def _positive_int(value: Any, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise FoundryError(f"table bounds require a {label}") from exc
    if number < 1:
        raise FoundryError(f"table bounds require a positive {label}")
    return number


def _column_index(letter: str) -> int:
    if not letter or not letter.isalpha():
        raise FoundryError("table bounds require column letters")
    index = 0
    for char in letter:
        index = index * 26 + (ord(char) - 64)
    return index


def _overlaps(left: dict[str, int], right: dict[str, int]) -> bool:
    return not (
        left["end_row"] < right["start_row"]
        or right["end_row"] < left["start_row"]
        or left["end_col"] < right["start_col"]
        or right["end_col"] < left["start_col"]
    )


def _bounds_key(bounds: dict[str, int]) -> str:
    return f"{bounds['start_row']}:{bounds['end_row']}:{bounds['start_col']}:{bounds['end_col']}"
