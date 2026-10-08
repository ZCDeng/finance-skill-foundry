"""Remember a confirmed structure so next month's file needs no second look.

A month-end pack arrives in the same shape every period. Once the manager has
said what a sheet is, the next file that matches that shape can be read the same
way. A template records the shape — the roles its columns carry, in order,
under that sheet's name — and how often it has proved right. A structure the
manager withdrew loses weight, and at zero it stops matching.

The registry sits beside ``tasks/``, not inside one. A task is one closing
period, so a registry kept under the task could only ever answer for the month
that filled it, and the September pack would open to an empty memory. One var
root is one tenant's shelf: August's confirmation is what September reads, and
nothing crosses to another root.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from foundry.errors import FoundryError

# How close a sheet must sit to a remembered shape before it is the same table.
MATCH_THRESHOLD = 0.85
WEIGHT_CEILING = 8
PUBLIC_FIELDS = ("id", "signature", "sheet_pattern", "weight", "disabled")
DIGITS = re.compile(r"\d+")
SHAPE_FIELDS = ("decision", "columns", "amount_pairs", "fill_down_columns")
"""What a template is allowed to remember.

Everything else on a declaration belongs to one file rather than to the shape:
the preview rows are that workbook's cells, the period and unit are that
month's, the header and excluded rows are wherever they landed this time. A
shelf that outlives every task must not carry them, and a September
confirmation must not claim August's preview as its own.
"""

REGISTRY_DIRNAME = "structure_templates"
REGISTRY_LOCK = "structure_templates.lock"
# Practice tasks keep their own shelf. A shape confirmed on the 华宸 example must never pre-fill a
# customer's real pack, and the practice September must still find the practice August.
SAMPLE_REGISTRY_DIRNAME = "structure_templates_sample"
SAMPLE_REGISTRY_LOCK = "structure_templates_sample.lock"
DOMAIN = "foundry.finance.structure_templates.v1"
TEMPLATE_ID = re.compile(r"^[0-9a-f]{32}$")


class TemplateRegistry:
    """The remembered shapes for one var root, held outside any task.

    Records here are a live tally rather than a filed version: a shape that
    proves right again is the same record with a higher weight, so it is
    rewritten in place. That is the one place in the foundry where a record is
    not immutable, and it is why nothing derived -- no number, no fact, no
    locator -- is ever stored on it. A template holds a shape and a count.
    """

    def __init__(self, var_root, *, sample: bool = False) -> None:
        self.var_root = Path(var_root)
        self.root = self.var_root / (SAMPLE_REGISTRY_DIRNAME if sample else REGISTRY_DIRNAME)
        self.lock_path = self.var_root / (SAMPLE_REGISTRY_LOCK if sample else REGISTRY_LOCK)

    def _path(self, template_id: str) -> Path:
        if not isinstance(template_id, str) or not TEMPLATE_ID.fullmatch(template_id):
            raise FoundryError(f"invalid structure template id: {template_id}")
        return self._inside(self.root / f"{template_id}.json")

    def _inside(self, path: Path) -> Path:
        """Refuse anything that leaves the registry folder or walks a symlink."""
        root = self.root.resolve()
        if not path.resolve().is_relative_to(root):
            raise FoundryError("structure template path escapes the registry")
        current = path
        while True:
            if current.is_symlink():
                raise FoundryError("structure template paths cannot use symbolic links")
            if current.resolve() == root:
                break
            if current == current.parent:
                raise FoundryError("structure template path has no registry ancestor")
            current = current.parent
        return path

    def _load(self, path: Path) -> dict[str, Any]:
        import json

        try:
            record = json.loads(path.read_text(encoding="utf8"))
        except (OSError, ValueError) as exc:
            raise FoundryError(
                f"structure template is unavailable: {path.name}"
            ) from exc
        check = dict(record)
        digest = check.pop("_integrity_hash", None)
        if not digest or digest != _digest(check):
            raise FoundryError("structure template integrity check failed")
        return record

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        # The sequence file lives here too; only id-named files are records.
        records = [
            self._load(self._inside(path))
            for path in self.root.glob("*.json")
            if TEMPLATE_ID.fullmatch(path.stem)
        ]
        return sorted(records, key=lambda row: (row.get("seq", 0), row["id"]))

    def read(self, template_id: str) -> dict[str, Any]:
        path = self._path(template_id)
        if not path.is_file():
            raise FoundryError(f"structure template not found: {template_id}")
        return self._load(path)

    def create(self, **fields: Any) -> dict[str, Any]:
        from foundry.analysis_data import json_value
        from foundry.task import now_iso

        record = {
            "id": uuid.uuid4().hex,
            "schema_version": 1,
            "domain": DOMAIN,
            "created_at": now_iso(),
            **json_value(fields),
        }
        from foundry.locking import exclusive

        self.root.mkdir(parents=True, exist_ok=True)
        with exclusive(self.lock_path, timeout=10):
            record["seq"] = self._next_seq()
            self._commit(record)
        return record

    def adjust(self, template_id: str, delta: int, ceiling: int) -> dict[str, Any]:
        """Move one template's weight, reading and writing under one lock.

        Two closing periods can be open at once now that the shelf outlives the
        task, so a read here and a write a moment later is a real race: a lost
        decrement leaves a shape the manager withdrew still matching next
        month's file.
        """
        from foundry.locking import exclusive

        self.root.mkdir(parents=True, exist_ok=True)
        with exclusive(self.lock_path, timeout=10):
            current = self._load(self._path(template_id))
            weight = max(0, min(ceiling, int(current.get("weight", 0)) + delta))
            updated = {
                **current,
                "weight": weight,
                "disabled": bool(current.get("disabled")) or weight == 0,
            }
            self._commit(updated)
        return updated

    def overwrite(self, record: dict[str, Any]) -> dict[str, Any]:
        from foundry.locking import exclusive

        self.root.mkdir(parents=True, exist_ok=True)
        with exclusive(self.lock_path, timeout=10):
            self._commit(record)
        return record

    def _commit(self, record: dict[str, Any]) -> None:
        """Write one record; the caller holds the registry lock."""
        from foundry.fsutil import write_json_atomic

        path = self._path(record["id"])
        payload = {
            key: value for key, value in record.items() if key != "_integrity_hash"
        }
        payload["_integrity_hash"] = _digest(payload)
        write_json_atomic(path, payload)

    def _next_seq(self) -> int:
        # Called only while holding the registry lock. Gaps after an
        # interruption are fine; two records sharing a seq are not, because the
        # listing order is what decides which shape a tie goes to.
        import json

        path = self._inside(self.root / "sequence.json")
        if path.exists():
            try:
                value = json.loads(path.read_text())["seq"]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("invalid sequence")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise FoundryError("structure template sequence is invalid") from exc
        else:
            value = 0
        from foundry.fsutil import write_json_atomic

        write_json_atomic(path, {"seq": value + 1})
        return value + 1


def _digest(value: Any) -> str:
    from foundry.analysis import _hash

    return _hash(value)


def registry_for(store) -> TemplateRegistry:
    """The registry a finance store reads, which belongs to its var root; a practice task reads
    and writes the separate practice shelf."""
    from foundry.sample_marker import uses_sample_shelf

    return TemplateRegistry(store.task.store.var_root, sample=uses_sample_shelf(store.task))



def signature_for(sheet: dict[str, Any]) -> str:
    """The ordered column roles a sheet carries, which is what makes it itself."""
    return "|".join(
        f"{column.get('role')}:{column.get('display') or column.get('header') or ''}"
        for column in sheet.get("columns") or []
    )


def sheet_pattern(name: str) -> str:
    """Sheet names carry the period; the pattern is the name without it."""
    return DIGITS.sub("#", str(name or ""))


def _roles(sheet: dict[str, Any]) -> list[str]:
    return [str(column.get("role") or "") for column in sheet.get("columns") or []]


# Roles the proposal engine learnt after templates were already being remembered. A shape
# stored before then reads these columns as unknown (or, for the dates, as a plain date);
# that is the same shape, not a different one, and the newer reading is the one to keep.
LATER_ROLES = frozenset({
    "invoice_id", "due_date", "issue_date", "effective_date", "product", "quantity", "price",
    "posting_status", "status", "scenario", "kind", "event_id",
})
_EARLIER_READINGS = frozenset({"unknown", "date"})


def _same_role(current: str, stored: str) -> bool:
    return current == stored or (current in LATER_ROLES and stored in _EARLIER_READINGS)


def _roles_agree(sheet: dict[str, Any], stored: dict[str, Any]) -> bool:
    current, remembered = _roles(sheet), _roles(stored)
    return len(current) == len(remembered) and all(_same_role(a, b) for a, b in zip(current, remembered))


def _keep_later_roles(columns: list[dict[str, Any]], sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """A remembered shape keeps this month's reading of a column it only knew as unknown."""
    read = {column.get("letter"): column.get("role") for column in sheet.get("columns") or []}
    return [
        {**column, "role": read[column.get("letter")]}
        if read.get(column.get("letter")) in LATER_ROLES and column.get("role") in _EARLIER_READINGS
        else column
        for column in columns
    ]


def _letters(sheet: dict[str, Any]) -> list[str]:
    return [str(column.get("letter") or "") for column in sheet.get("columns") or []]


def _headers(sheet: dict[str, Any]) -> list[str]:
    return [
        str(column.get("display") or column.get("header") or "")
        for column in sheet.get("columns") or []
    ]


def similarity(sheet: dict[str, Any], template: dict[str, Any]) -> float:
    """Blend header overlap, column order and the sheet's own name."""
    stored = template.get("declaration") or {}
    left, right = set(_headers(sheet)), set(_headers(stored))
    if not left or not right:
        return 0.0
    jaccard = len(left & right) / len(left | right)
    roles_a, roles_b = _roles(sheet), _roles(stored)
    width = max(len(roles_a), len(roles_b))
    ordered = (
        sum(1 for a, b in zip(roles_a, roles_b) if _same_role(a, b)) / width if width else 0.0
    )
    named = 1.0 if sheet_pattern(sheet.get("sheet", "")) == template.get("sheet_pattern") else 0.0
    return round(0.5 * jaccard + 0.35 * ordered + 0.15 * named, 4)


def differences(sheet: dict[str, Any], template: dict[str, Any]) -> list[str]:
    """What a remembered shape does not answer for in this sheet."""
    stored = template.get("declaration") or {}
    found: list[str] = []
    # Letters as well as headers: an inserted blank column leaves the header
    # list untouched and moves every amount one cell to the right.
    if _headers(sheet) != _headers(stored) or _letters(sheet) != _letters(stored):
        found.append("columns")
    if not _roles_agree(sheet, stored):
        found.append("roles")
    stored_pairs = {
        pair.get("label"): (pair.get("direction") or {}).get("kind")
        for pair in stored.get("amount_pairs") or []
    }
    sheet_pairs = {
        pair.get("label"): (pair.get("direction") or {}).get("kind")
        for pair in sheet.get("amount_pairs") or []
    }
    if stored_pairs != sheet_pairs:
        found.append("amount_pairs")
    if sorted(sheet.get("fill_down_columns") or []) != sorted(
        stored.get("fill_down_columns") or []
    ):
        found.append("fill_down_columns")
    return found


def _learns(store) -> bool:
    """The reference task neither learns nor applies a shape: each of its structures is the example's
    own confirmation, and none of them may pre-fill the practice August the manager confirms by hand."""
    from foundry.sample_marker import is_reference

    return not is_reference(store.task)


def live_templates(store) -> list[dict[str, Any]]:
    if not _learns(store):
        return []
    return [
        row
        for row in registry_for(store).list()
        if not row.get("disabled") and row.get("weight", 0) > 0
    ]


def apply_matching_templates(
    store, sheets: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pre-fill each sheet from the closest remembered shape, and say how close."""
    templates = live_templates(store)
    if not templates:
        return sheets, []
    prepared: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    for sheet in sheets:
        # A presentation page the manager adopted last month is remembered like any table;
        # this month's copy of it is set aside again until a shape matches it exactly.
        adoptable = sheet.get("reason") == "presentation_sheet" and sheet.get("adoptable")
        if sheet.get("decision") != "table" and not adoptable:
            prepared.append(sheet)
            continue
        scored = sorted(
            ((similarity(sheet, template), template) for template in templates),
            key=lambda item: (item[0], item[1].get("weight", 0)),
            reverse=True,
        )
        score, template = scored[0]
        if score < MATCH_THRESHOLD:
            prepared.append(sheet)
            continue
        gaps = differences(sheet, template)
        if adoptable:
            # Only the page she adopted before: a 对标 page that copies a data table's
            # headers is not thereby a table she chose.
            if gaps or sheet_pattern(sheet.get("sheet", "")) != template.get("sheet_pattern"):
                prepared.append(sheet)
                continue
            sheet = {**sheet, "decision": "table", "reason": "adopted_presentation_sheet", "blocked_reason": None}
        filled = dict(sheet)
        if gaps:
            # A remembered shape that does not fit exactly is a starting point,
            # never a decision: the card opens pre-filled.
            filled["prefill"] = template.get("declaration")
        else:
            # This month's reading is the base; memory supplies the shape and
            # nothing else. Rows, title area, period and preview are all facts
            # about the file in hand, and only the engine can say where they are.
            filled = {**sheet, **(template.get("declaration") or {})}
            filled["columns"] = _keep_later_roles(filled.get("columns") or [], sheet)
        filled["template_id"] = template["id"]
        prepared.append(filled)
        matches.append(
            {
                "sheet": sheet["sheet"],
                "template_id": template["id"],
                "score": score,
                "differences": gaps,
                "auto_apply": not gaps,
            }
        )
    return prepared, matches


def remember_declaration(store, sheets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep what the manager settled, one record per shape rather than per month."""
    if not _learns(store):
        return []
    shelf = registry_for(store)
    kept: list[dict[str, Any]] = []
    for sheet in sheets:
        if sheet.get("decision") != "table":
            continue
        signature = signature_for(sheet)
        pattern = sheet_pattern(sheet.get("sheet", ""))
        existing = next(
            (
                row
                for row in shelf.list()
                if row.get("signature") == signature
                and row.get("sheet_pattern") == pattern
            ),
            None,
        )
        if existing is not None:
            kept.append(_reweigh(store, existing, +1))
            continue
        kept.append(
            shelf.create(
                signature=signature,
                sheet_pattern=pattern,
                sheet=str(sheet.get("sheet") or ""),
                declaration=shape_of(sheet),
                weight=1,
                disabled=False,
            )
        )
    return kept


def shape_of(sheet: dict[str, Any]) -> dict[str, Any]:
    """The part of a declaration that is about the shape rather than the file."""
    return {key: sheet[key] for key in SHAPE_FIELDS if key in sheet}


def demote_declaration(store, sheets: list[dict[str, Any]]) -> None:
    """A withdrawn structure is evidence against the shape it came from."""
    if not _learns(store):
        return
    shelf = registry_for(store)
    for sheet in sheets:
        signature = signature_for(sheet)
        pattern = sheet_pattern(sheet.get("sheet", ""))
        for row in shelf.list():
            if row.get("signature") == signature and row.get("sheet_pattern") == pattern:
                _reweigh(store, row, -1)


def _reweigh(store, template: dict[str, Any], delta: int) -> dict[str, Any]:
    return registry_for(store).adjust(template["id"], delta, WEIGHT_CEILING)


def disable_template(store, template_id: str) -> dict[str, Any]:
    shelf = registry_for(store)
    template = shelf.read(template_id)
    updated = {**template, "weight": 0, "disabled": True}
    shelf.overwrite(updated)
    return public_template(updated)


def public_template(record: dict[str, Any]) -> dict[str, Any]:
    item = {key: record.get(key) for key in PUBLIC_FIELDS}
    item["sheet"] = record.get("sheet") or record.get("sheet_pattern") or ""
    item["columns"] = len((record.get("declaration") or {}).get("columns") or [])
    return item
