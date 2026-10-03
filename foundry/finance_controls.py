"""Tie-out controls over archived workbook snapshots: does a total equal what it totals.

A control compares two sums of cells, each read from an archived, task-bound
snapshot: the detail rows of a table against its 合计 row (``subtotal``), or a
figure in one place against the same figure somewhere else, across sheets or
workbooks (``tie_out``). The software finds and reports a difference; it never
picks which side is right. Deciding that is the manager's (see the plan's PR C).

Controls come from two places. ``suggest_controls`` reads a workbook's own
合计 rows and offers one control per additive column; a suggestion is only a
preview until it is saved and the manager confirms it. A control can also be
declared, by the manager or the assistant, between any two ranges. Only a
confirmed control counts toward the close.

Every result is bound to the snapshot hashes it read. A control whose snapshot
has left the task or changed is ``stale``, never an old green.
"""

from __future__ import annotations

import io
import re
import zipfile
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries

from foundry.analysis_data import archived_numeric_parser, read_exact_numerics
from foundry.errors import FoundryError

KINDS = frozenset({"subtotal", "tie_out"})
PROPOSED = "proposed"
CONFIRMED = "confirmed"
RETIRED = "retired"
STATES = frozenset({PROPOSED, CONFIRMED, RETIRED})
ORIGINS = frozenset({"suggested", "declared"})

PASS = "pass"
BREAK = "break"
ERROR = "error"
STALE = "stale"

MAX_ROWS = 5000
MAX_COLUMNS = 60
MAX_CELLS = 20000
MAX_SUGGESTIONS = 400
# A unit conversion, never a coefficient: 元 ↔ 千元 ↔ 万元 ↔ 百万元 ↔ 亿元.
UNIT_SCALES = frozenset(Decimal(10) ** exponent for exponent in range(-8, 9))

TOTAL_LABELS = ("合计", "总计", "小计")
# A column whose header names a rate, a share, an average or a duration does not add up.
NON_ADDITIVE_MARKERS = (
    "率", "比例", "比重", "占比", "单价", "均价", "平均", "人均", "单方", "天数", "周转",
    "系数", "指数", "评价", "评级", "%", "％", "/", "／", "期限", "进度", "账期", "（天）", "(天)",
    "较", "均值", "pct",
)
# Under a weighted total (加权合计, 合计/加权) only a column that names an amount is a sum.
AMOUNT_MARKERS = ("元", "金额", "规模", "现金", "收入", "成本", "费用", "余额", "利润", "账单", "实收", "应收", "应付", "实付")
_PARENTHETICAL = re.compile(r"[（(][^（()）]*[)）]")
_SPACE = re.compile(r"\s+")


def clean_control(spec: Any) -> dict[str, Any]:
    """The fields that decide a control, validated; everything else is dropped."""
    if not isinstance(spec, dict):
        raise FoundryError("control must be an object")
    kind = spec.get("kind") or "tie_out"
    if kind not in KINDS:
        raise FoundryError("control kind must be subtotal or tie_out")
    label = _text(spec.get("label"), "control label", maximum=200)
    left = _side(spec.get("left"), "left")
    right = _side(spec.get("right"), "right")
    if kind == "subtotal" and (left["dataset_id"], left["sheet"]) != (right["dataset_id"], right["sheet"]):
        raise FoundryError("a subtotal control compares rows of one sheet; use tie_out across sheets")
    tolerance = _decimal(spec.get("tolerance", "0"), "control tolerance")
    if tolerance < 0:
        raise FoundryError("control tolerance cannot be negative")
    return {
        "kind": kind,
        "label": label,
        "left": left,
        "right": right,
        "tolerance": _format(tolerance),
        "unit": _text(spec.get("unit") or "", "control unit", required=False, maximum=20),
        "note": _text(spec.get("note") or "", "control note", required=False, maximum=2000),
    }


def dataset_ids(control: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys([control["left"]["dataset_id"], control["right"]["dataset_id"]]))


def control_key(control: dict[str, Any]) -> tuple:
    """What makes two controls the same check, whatever they are called."""
    return tuple(
        (side["dataset_id"], side["sheet"], side["range"], side["scale"])
        for side in (control["left"], control["right"])
    )


def evaluate_control(analysis: Any, control: dict[str, Any], *, cache: dict | None = None) -> dict[str, Any]:
    """Sum both sides and compare. Never raises for a bad snapshot; says so in the result."""
    cache = {} if cache is None else cache
    sides = {}
    for name in ("left", "right"):
        side = control[name]
        try:
            sides[name] = _sum_side(analysis, side, cache)
        except _Stale as exc:
            return _result(control, STALE, reason=str(exc))
        except FoundryError as exc:
            return _result(control, ERROR, reason=str(exc))
    left, right = sides["left"], sides["right"]
    for name, side in sides.items():
        if side["text_cells"]:
            return _result(control, ERROR, reason=f"{side['sheet']}!{side['range']} 里有 {side['text_cells']} 个文字单元格，不能当作空白跳过",
                           left=_public_side(left), right=_public_side(right))
    difference = left["value"] - right["value"]
    tolerance = Decimal(control["tolerance"])
    # A stored double carries noise past its 15th significant digit; that is not a difference at all.
    noise = Decimal("1e-12") * max(abs(left["value"]), abs(right["value"]))
    status = PASS if abs(difference) <= max(tolerance, noise) else BREAK
    return _result(
        control,
        status,
        left=_public_side(left),
        right=_public_side(right),
        difference=_format(difference),
        # A hint for the reader, never a pass: shown figures rounded to their last digit could
        # account for a gap this small. Whole numbers carry no such rounding.
        within_rounding=status == BREAK and abs(difference) <= _display_rounding(left) + _display_rounding(right),
    )


def _display_rounding(side: dict[str, Any]) -> Decimal:
    if side["places"] <= 0:
        return Decimal(0)
    half_unit = Decimal(5) * Decimal(10) ** (-side["places"] - 1) * Decimal(side["scale"])
    # A few cells can all round the same way; across many, independent roundings grow with
    # the square root of the count (three standard deviations), not with the count.
    cells = Decimal(side["cells"])
    return half_unit * min(cells, max(Decimal(1), 3 * cells.sqrt()))


def suggest_controls(analysis: Any, dataset: dict[str, Any], data: bytes) -> list[dict[str, Any]]:
    """One subtotal control per additive column under each 合计 row of a workbook.

    Detail rows are the unbroken run of rows directly above the total that carry
    numbers; a blank row, a header, or another total ends the run. A column is
    offered only if the total and every detail row hold a number in it and its
    header does not name a rate, share, average or duration.
    """
    del analysis
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    found: list[dict[str, Any]] = []
    try:
        for sheet in book.sheetnames:
            page = book[sheet]
            if (page.max_row or 0) > MAX_ROWS or (page.max_column or 0) > MAX_COLUMNS:
                continue
            rows = [list(row) for row in page.iter_rows(values_only=True)]
            found.extend(_sheet_suggestions(dataset, sheet, rows))
            if len(found) >= MAX_SUGGESTIONS:
                break
    finally:
        book.close()
    return found[:MAX_SUGGESTIONS]


def _sheet_suggestions(dataset: dict[str, Any], sheet: str, rows: list[list[Any]]) -> list[dict[str, Any]]:
    out = []
    for index, row in enumerate(rows):
        label = _leading_text(row)
        if not _is_plain_total(label):
            continue
        weighted = "加权" in label
        start = index
        while start - 1 >= 0 and _is_detail(rows[start - 1]):
            start -= 1
        details = rows[start:index]
        if len(details) < 2:
            continue
        # 「其中：」 rows break a parent down; summing them with it counts the parent twice.
        if any(_leading_text(item).startswith(("其中", "含：", "包括")) for item in details):
            continue
        header = rows[start - 1] if start - 1 >= 0 else []
        for col, total in enumerate(row):
            if not _is_number(total):
                continue
            if not all(col < len(item) and _is_number(item[col]) for item in details):
                continue
            title = _header_text(header, col)
            if not title or any(marker in title for marker in NON_ADDITIVE_MARKERS):
                continue
            if weighted and not any(marker in title for marker in AMOUNT_MARKERS):
                continue
            letter = get_column_letter(col + 1)
            side = {"dataset_id": dataset["id"], "source_hash": dataset["source_hash"], "sheet": sheet, "scale": "1"}
            out.append({
                "kind": "subtotal",
                "label": f"{sheet} · {title}：分项合计 = {label}",
                "left": {**side, "range": f"{letter}{start + 1}:{letter}{index}"},
                "right": {**side, "range": f"{letter}{index + 1}"},
                "tolerance": "0",
                "unit": "",
                "note": "",
            })
    return out


class _Stale(FoundryError):
    """The snapshot a control was bound to is no longer the task's."""


def _sum_side(analysis: Any, side: dict[str, Any], cache: dict) -> dict[str, Any]:
    values, texts = _numerics(analysis, side, cache)
    min_col, min_row, max_col, max_row = range_boundaries(side["range"])
    total = Decimal(0)
    numeric = 0
    text_cells = 0
    places = 0
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            coordinate = f"{get_column_letter(col)}{row}"
            value = values.get(coordinate)
            if value is None:
                text_cells += coordinate in texts
                continue
            total += value
            numeric += 1
            places = max(places, -value.as_tuple().exponent if value.as_tuple().exponent < 0 else 0)
    cells = (max_row - min_row + 1) * (max_col - min_col + 1)
    if not numeric:
        raise FoundryError(f"{side['sheet']}!{side['range']} 没有数值单元格")
    scale = Decimal(side["scale"])
    return {**side, "value": total * scale, "raw": total, "cells": numeric, "text_cells": text_cells,
            "blank_cells": cells - numeric - text_cells, "places": places}


def _numerics(analysis: Any, side: dict[str, Any], cache: dict) -> dict[str, Decimal]:
    if "__published" not in cache:
        rows = analysis.state().get("datasets") or []
        cache["__published"] = {row["id"] for row in rows}
        cache["__superseded"] = superseded_snapshots(analysis.task, rows)
        cache["__datasets"] = {}
    dataset_id = side["dataset_id"]
    if dataset_id not in cache["__published"]:
        raise _Stale("资料已不在任务里")
    if dataset_id in cache["__superseded"]:
        raise _Stale("资料已有更新的版本")
    if dataset_id not in cache["__datasets"]:
        try:
            cache["__datasets"][dataset_id] = analysis.read_dataset(dataset_id)
        except FoundryError as exc:
            raise _Stale("资料快照不可用") from exc
    dataset = cache["__datasets"][dataset_id]
    if dataset.get("source_hash") != side["source_hash"]:
        raise _Stale("资料快照已变化")
    key = (dataset_id, side["sheet"])
    if key in cache:
        return cache[key]
    if not str(dataset.get("source_file") or "").endswith(".xlsx"):
        raise FoundryError("勾稽控制只读 Excel 工作簿资料")
    data = snapshot_bytes(analysis, dataset)
    try:
        values = read_exact_numerics(data, side["sheet"], archived_numeric_parser(dataset, data))
        texts = _text_cells(data, side["sheet"])
    except (FoundryError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise FoundryError(f"读不到工作表 {side['sheet']}") from exc
    cache[key] = (values, texts)
    return values, texts


def snapshot_bytes(analysis: Any, dataset: dict[str, Any]) -> bytes:
    """The archived bytes, checked against the hash they were filed under at the moment they are used."""
    from foundry.analysis import _hash_bytes

    folder = analysis._inside(analysis.root / "datasets" / dataset["id"])
    data = analysis._inside(folder / dataset["source_file"]).read_bytes()
    if _hash_bytes(data) != dataset["source_hash"]:
        raise _Stale("资料快照完整性校验失败")
    return data


def _text_cells(data: bytes, sheet: str) -> set[str]:
    """Coordinates that hold text. A 「1,200」 typed as text is not a blank; skipping it would pass a short total."""
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if sheet not in book.sheetnames:
            raise FoundryError(f"no worksheet: {sheet}")
        found = set()
        for row in book[sheet].iter_rows():
            for cell in row:
                value = getattr(cell, "value", None)
                if isinstance(value, str) and value.strip() and getattr(cell, "coordinate", None):
                    found.add(cell.coordinate)
        return found
    finally:
        book.close()


def superseded_snapshots(task: Any, datasets: list[dict[str, Any]] | None = None) -> set[str]:
    """Snapshots a newer one has replaced: by a published source refresh, or by a later upload under the same name.

    A month pack is updated by adding the corrected file again. The old snapshot stays in
    the task for runs that read it, but a control on it no longer speaks for the pack.
    """
    from foundry.analysis import AnalysisStore
    from foundry.source_refresh import SourceRefreshService

    replaced = {
        row["prior_snapshot_id"]
        for row in SourceRefreshService(task).batches()
        if row.get("publication_status") == "published"
        and row.get("prior_snapshot_id") and row.get("dataset_id") and row["dataset_id"] != row["prior_snapshot_id"]
    }
    rows = AnalysisStore(task).state()["datasets"] if datasets is None else datasets
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        held = latest.get(name)
        if held is not None and (held.get("seq", 0), held["created_at"]) < (row.get("seq", 0), row["created_at"]):
            replaced.add(held["id"])
            latest[name] = row
        elif held is not None:
            replaced.add(row["id"])
        else:
            latest[name] = row
    return replaced


def _result(control: dict[str, Any], status: str, **fields: Any) -> dict[str, Any]:
    return {
        "status": status,
        "tolerance": control["tolerance"],
        "source_hashes": {side["dataset_id"]: side["source_hash"] for side in (control["left"], control["right"])},
        **fields,
    }


def _public_side(side: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": side["dataset_id"],
        "sheet": side["sheet"],
        "range": side["range"],
        "scale": side["scale"],
        "value": _format(side["value"]),
        "cells": side["cells"],
        "text_cells": side["text_cells"],
        "blank_cells": side["blank_cells"],
    }


def _side(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise FoundryError(f"control {name} must be an object")
    range_ref = _text(value.get("range"), f"control {name} range", maximum=40).replace("$", "").upper()
    try:
        min_col, min_row, max_col, max_row = range_boundaries(range_ref)
    except ValueError as exc:
        raise FoundryError(f"control {name} range must be a bounded A1 reference") from exc
    if None in {min_col, min_row, max_col, max_row} or max_row < min_row or max_col < min_col:
        raise FoundryError(f"control {name} range must be a bounded A1 reference")
    if (max_row - min_row + 1) * (max_col - min_col + 1) > MAX_CELLS:
        raise FoundryError(f"control {name} range is too large")
    scale = _decimal(value.get("scale", "1"), f"control {name} scale")
    if scale not in UNIT_SCALES:
        raise FoundryError(f"control {name} scale must be a unit conversion (a power of ten)")
    return {
        "dataset_id": _text(value.get("dataset_id"), f"control {name} dataset_id", maximum=64),
        "source_hash": _text(value.get("source_hash"), f"control {name} source_hash", maximum=128),
        "sheet": _text(value.get("sheet"), f"control {name} sheet", maximum=120),
        "range": range_ref,
        "scale": _format(scale),
    }


def _leading_text(row: list[Any]) -> str:
    for value in row:
        if value is None:
            continue
        if isinstance(value, str):
            text = _SPACE.sub("", value.replace("　", ""))
            if text:
                return text
            continue
        return ""
    return ""


def _is_total(label: str) -> bool:
    if not label or len(label) > 24 or "校验" in label or label.startswith(("注", "说明", "备注")):
        return False
    if "计提" in label and not label.startswith(TOTAL_LABELS):
        return False  # 「按组合计提」 is not a total
    return label.startswith(TOTAL_LABELS) or "合计" in label or "总计" in label


def _is_plain_total(label: str) -> bool:
    """A total of everything above it. 「管理费用合计」 totals a category whose first row nothing marks, so it is not offered."""
    if not _is_total(label):
        return False
    bare = _PARENTHETICAL.sub("", label)
    return bare.startswith(TOTAL_LABELS) or bare in {"加权合计"}


def _is_detail(row: list[Any]) -> bool:
    label = _leading_text(row)
    if _is_total(label):
        return False
    return any(_is_number(value) for value in row)


def _header_text(header: list[Any], col: int) -> str:
    value = header[col] if col < len(header) else None
    return _SPACE.sub("", str(value).replace("　", "")) if isinstance(value, str) else ""


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _text(value: Any, label: str, *, required: bool = True, maximum: int = 200) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise FoundryError(f"{label} must be text")
    text = value.strip()
    if required and not text:
        raise FoundryError(f"{label} is required")
    if len(text) > maximum:
        raise FoundryError(f"{label} is too long")
    return text


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise FoundryError(f"{label} must be a number")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise FoundryError(f"{label} must be a number") from exc
    if not number.is_finite():
        raise FoundryError(f"{label} must be finite")
    return number


def _format(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


# ---- Dispositions: what the manager decided about a difference (PR C) ---------------------

CORRECTED = "corrected"
WAIVED = "waived"
PENDING_EXTERNAL = "pending_external"
DECISIONS = frozenset({CORRECTED, WAIVED, PENDING_EXTERNAL})
DECISION_LABELS = {CORRECTED: "修正资料后重新导入", WAIVED: "接受差异并说明", PENDING_EXTERNAL: "待外部确认"}


def clean_disposition(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise FoundryError("disposition must be an object")
    decision = spec.get("decision")
    if decision not in DECISIONS:
        raise FoundryError("disposition decision must be corrected, waived or pending_external")
    reason = _text(spec.get("reason") or "", "disposition reason", required=False, maximum=4000)
    if decision in {WAIVED, PENDING_EXTERNAL} and not reason:
        raise FoundryError("accepting a difference or sending it out for confirmation requires a reason")
    counterparty = _text(spec.get("counterparty") or "", "disposition counterparty", required=False, maximum=200)
    if decision == PENDING_EXTERNAL and not counterparty:
        raise FoundryError("a difference sent out for confirmation must name who confirms it")
    return {
        "decision": decision,
        "reason": reason,
        "counterparty": counterparty,
        "evidence": _text(spec.get("evidence") or "", "disposition evidence", required=False, maximum=2000),
        "decided_by_name": _text(spec.get("decided_by_name") or "", "decided_by_name", required=False, maximum=80),
    }


def applies_to(disposition: dict[str, Any], result: dict[str, Any] | None) -> bool:
    """A decision is about one difference read from particular bytes. Another difference is a new question."""
    if not result or result.get("status") not in {BREAK, ERROR}:
        return False
    return (
        disposition.get("status") == result.get("status")
        and disposition.get("difference") == result.get("difference")
        and disposition.get("source_hashes") == result.get("source_hashes")
    )


def control_issue(row: dict[str, Any], disposition: dict[str, Any] | None, *, require_second_review: bool) -> dict[str, Any] | None:
    """What a confirmed control's latest result asks of the manager, and whether it holds the close.

    Only a reviewed (where review is required) acceptance clears a difference. A difference
    that changed since it was decided is open again; the old decision is shown, not applied.
    """
    if row.get("state") != CONFIRMED:
        return None
    result = row.get("result")
    if result is None:
        return {"state": "not_run", "blocking": True}
    status = result.get("status")
    if status == PASS:
        return None
    if status == STALE:
        return {"state": "stale", "blocking": True}
    if disposition is None:
        return {"state": "open", "blocking": True}
    if not applies_to(disposition, result):
        return {"state": "open", "blocking": True, "outdated_disposition": disposition}
    decision = disposition["decision"]
    if decision == WAIVED:
        if require_second_review and not disposition.get("reviewed_at"):
            return {"state": "awaiting_review", "blocking": True, "disposition": disposition}
        return {"state": "waived", "blocking": False, "disposition": disposition}
    if decision == PENDING_EXTERNAL:
        return {"state": "pending_external", "blocking": True, "disposition": disposition}
    return {"state": "awaiting_reimport", "blocking": True, "disposition": disposition}


def confirmation_sheet(rows: list[dict[str, Any]], names: dict[str, str]) -> dict[str, str]:
    """A one-page list of differences for whoever compiled the books: where, what we read, what we ask.

    Markdown to send, and tab-separated rows that paste into Excel as a table.
    """
    lines = ["# 勾稽差异确认", "", "以下差异由系统按原始资料逐格复算得出，请确认采用口径或说明原因。", ""]
    table = [["序号", "控制", "左侧取数", "左侧金额", "右侧取数", "右侧金额", "差额", "状态", "说明"]]
    for index, row in enumerate(rows, start=1):
        result = row.get("result") or {}
        left, right = result.get("left") or {}, result.get("right") or {}
        where = lambda side: f"{names.get(side.get('dataset_id', ''), '资料')} · {side.get('sheet', '')}!{side.get('range', '')}"
        issue = row.get("issue") or {}
        note = (issue.get("disposition") or {}).get("reason") or ""
        state = {"open": "待处理", "pending_external": "待外部确认", "awaiting_reimport": "待重新导入",
                 "awaiting_review": "待复核", "stale": "资料已更新"}.get(issue.get("state", ""), issue.get("state", ""))
        lines += [
            f"## {index}. {row['control']['label']}",
            "",
            f"- 左侧：{where(left)}，合计 {left.get('value', '—')}",
            f"- 右侧：{where(right)}，合计 {right.get('value', '—')}",
            f"- 差额：{result.get('difference', '—')}{'（显示舍入可能造成）' if result.get('within_rounding') else ''}",
            f"- 状态：{state}" + (f"；{note}" if note else ""),
            "",
        ]
        table.append([str(index), row["control"]["label"], where(left), left.get("value", ""), where(right),
                      right.get("value", ""), result.get("difference", ""), state, note])
    tsv = "\n".join("\t".join(str(cell).replace("\t", " ").replace("\n", " ") for cell in line) for line in table)
    return {"markdown": "\n".join(lines).rstrip() + "\n", "tsv": tsv + "\n"}
