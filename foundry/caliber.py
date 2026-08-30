from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from foundry.catalog import sql_identifier
from foundry.errors import LockRefused

AUX_COLUMNS = ["dim_id", "dim_name", "member_id", "member_name"]
MAP_COLUMNS = ["source_account_code", "analysis_node_id", "analysis_node_name"]
UNITS_COLUMNS = ["unit_id", "unit_name"]
MASTER_TABLES = frozenset({"coa", "aux", "map", "units"})
MAP_SPLITS = frozenset({"analysis_node", "analysis_node_id", "map"})
UNMAPPED_NODE = "__unmapped__"
CONFLICT_NODE = "__conflict__"
MATCH_FULL = "全辅助命中"
MATCH_PARTIAL = "部分辅助"
MATCH_ACCOUNT = "仅科目"
MATCH_NONE = "未对照"
MATCH_CONFLICT = "冲突"
MATCH_SOURCE = "源表行"
MATCH_SPLIT = "源表拆开"
_MATCH_BY_PRIORITY = {2: MATCH_FULL, 1: MATCH_PARTIAL, 0: MATCH_ACCOUNT}


def _cell(row: tuple[Any, ...], index: int) -> str:
    if index < 0 or index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def units_as_aux_rows(headers: list[str], rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    unit_id = headers.index("unit_id")
    unit_name = headers.index("unit_name")
    converted: list[tuple[Any, ...]] = []
    for row in rows:
        member_id = _cell(row, unit_id)
        if not member_id:
            continue
        converted.append(("unit", "unit", member_id, _cell(row, unit_name) or member_id))
    return converted


def filter_map_rows(
    headers: list[str],
    rows: list[tuple[Any, ...]],
    coa_codes: set[str],
) -> tuple[list[tuple[Any, ...]], list[str]]:
    account_i = headers.index("source_account_code")
    node_i = headers.index("analysis_node_id")
    dim_i = headers.index("dim_id") if "dim_id" in headers else -1
    member_i = headers.index("member_id") if "member_id" in headers else -1
    kept: list[tuple[Any, ...]] = []
    orphans: list[str] = []
    seen: dict[tuple[str, str, str], str] = {}
    for row in rows:
        account = _cell(row, account_i)
        if account not in coa_codes:
            if account:
                orphans.append(account)
            continue
        key = (account, _cell(row, dim_i), _cell(row, member_i))
        node = _cell(row, node_i)
        prior = seen.get(key)
        if prior is not None and prior != node:
            raise LockRefused(f"map conflict for {account}")
        seen[key] = node
        kept.append(row)
    return kept, orphans


@dataclass(frozen=True)
class MapEntry:
    account: str
    dim_id: str
    member_id: str
    node_id: str
    node_name: str


@dataclass(frozen=True)
class CutLine:
    node_id: str
    node_name: str
    account: str
    dims: tuple[tuple[str, str], ...]
    amount: Decimal
    match: str
    conflict_nodes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapCut:
    claimed: Decimal
    recomputed: Decimal
    unmapped: Decimal
    conflict: Decimal
    nodes: list[tuple[str, str, Decimal]]
    lines: list[CutLine]


def parse_map_entries(headers: list[str], rows: list[tuple[Any, ...]]) -> list[MapEntry]:
    account_i = headers.index("source_account_code")
    node_i = headers.index("analysis_node_id")
    name_i = headers.index("analysis_node_name")
    dim_i = headers.index("dim_id") if "dim_id" in headers else -1
    member_i = headers.index("member_id") if "member_id" in headers else -1
    return [
        MapEntry(
            account=_cell(row, account_i),
            dim_id=_cell(row, dim_i),
            member_id=_cell(row, member_i),
            node_id=_cell(row, node_i),
            node_name=_cell(row, name_i) or _cell(row, node_i),
        )
        for row in rows
        if _cell(row, account_i)
    ]


def fact_dims(headers: list[str], row: tuple[Any, ...]) -> list[tuple[str, str]]:
    index = {name: i for i, name in enumerate(headers)}
    dims: list[tuple[str, str]] = []
    if "unit_id" in index and _cell(row, index["unit_id"]):
        dims.append(("unit", _cell(row, index["unit_id"])))
    if "dim_id" in index and "member_id" in index and _cell(row, index["member_id"]):
        dims.append((_cell(row, index["dim_id"]) or "unit", _cell(row, index["member_id"])))
    return dims


def match_priority(entry: MapEntry, account: str, given: list[tuple[str, str]]) -> int | None:
    if entry.account != account:
        return None
    given_set = set(given)
    if entry.dim_id and entry.member_id:
        if (entry.dim_id, entry.member_id) in given_set:
            return 2
        return None
    if entry.dim_id or entry.member_id:
        dim_hit = bool(entry.dim_id) and any(dim == entry.dim_id for dim, _ in given)
        member_hit = bool(entry.member_id) and any(member == entry.member_id for _, member in given)
        if dim_hit or member_hit:
            return 1
        return None
    return 0


def rank_matches(
    entries: list[MapEntry], account: str, given: list[tuple[str, str]]
) -> tuple[int, list[MapEntry]] | None:
    scored: dict[int, list[MapEntry]] = {}
    for entry in entries:
        priority = match_priority(entry, account, given)
        if priority is None:
            continue
        scored.setdefault(priority, []).append(entry)
    if not scored:
        return None
    priority = max(scored)
    return priority, scored[priority]


def resolve_node(entries: list[MapEntry], account: str, given: list[tuple[str, str]]) -> MapEntry | None:
    ranked = rank_matches(entries, account, given)
    if ranked is None:
        return None
    _priority, winners = ranked
    nodes = {item.node_id for item in winners}
    if len(nodes) > 1:
        raise LockRefused(f"map conflict for {account}")
    return winners[0]


def format_aux(dims: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> str:
    if not dims:
        return "—"
    return ", ".join(f"{dim}/{member}" for dim, member in dims)


def _account_optional(headers: list[str], row: tuple[Any, ...]) -> str:
    try:
        return _account(headers, row)
    except LockRefused:
        return ""


def _amount(headers: list[str], row: tuple[Any, ...]) -> Decimal:
    if "amount" not in headers:
        raise LockRefused("fact table has no amount")
    value = row[headers.index("amount")]
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _account(headers: list[str], row: tuple[Any, ...]) -> str:
    if "account_code" in headers:
        return _cell(row, headers.index("account_code"))
    if "source_account_code" in headers:
        return _cell(row, headers.index("source_account_code"))
    raise LockRefused("fact table has no account_code")


def cut_fact_by_map(
    fact_headers: list[str],
    fact_rows: list[tuple[Any, ...]],
    map_headers: list[str],
    map_rows: list[tuple[Any, ...]],
) -> MapCut:
    entries = parse_map_entries(map_headers, map_rows)
    totals: dict[str, list[Any]] = {}
    lines: list[CutLine] = []
    claimed = Decimal("0")
    unmapped = Decimal("0")
    conflict = Decimal("0")
    for row in fact_rows:
        amount = _amount(fact_headers, row)
        claimed += amount
        account = _account(fact_headers, row)
        dims = tuple(fact_dims(fact_headers, row))
        ranked = rank_matches(entries, account, list(dims))
        if ranked is None:
            unmapped += amount
            lines.append(
                CutLine(UNMAPPED_NODE, "未对照", account, dims, amount, MATCH_NONE)
            )
            continue
        priority, winners = ranked
        node_ids = {item.node_id for item in winners}
        if len(node_ids) > 1:
            conflict += amount
            lines.append(
                CutLine(
                    CONFLICT_NODE,
                    "冲突",
                    account,
                    dims,
                    amount,
                    MATCH_CONFLICT,
                    tuple(sorted(node_ids)),
                )
            )
            continue
        hit = winners[0]
        bucket = totals.setdefault(hit.node_id, [hit.node_name, Decimal("0")])
        bucket[1] += amount
        lines.append(
            CutLine(
                hit.node_id,
                hit.node_name,
                account,
                dims,
                amount,
                _MATCH_BY_PRIORITY[priority],
            )
        )
    nodes = [(node_id, str(name), total) for node_id, (name, total) in sorted(totals.items())]
    recomputed = sum(item[2] for item in nodes) + unmapped + conflict
    return MapCut(
        claimed=claimed,
        recomputed=recomputed,
        unmapped=unmapped,
        conflict=conflict,
        nodes=nodes,
        lines=lines,
    )


def fact_schedule_lines(headers: list[str], rows: list[tuple[Any, ...]]) -> list[CutLine]:
    if "amount" not in headers:
        return []
    totals: dict[tuple[str, tuple[tuple[str, str], ...]], Decimal] = {}
    order: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for row in rows:
        key = (_account_optional(headers, row), tuple(fact_dims(headers, row)))
        if key not in totals:
            order.append(key)
            totals[key] = Decimal("0")
        totals[key] += _amount(headers, row)
    return [
        CutLine("", "", account, dims, totals[(account, dims)], MATCH_SOURCE) for account, dims in order
    ]


def fact_split_lines(headers: list[str], rows: list[tuple[Any, ...]], split_by: str) -> list[CutLine]:
    if split_by not in headers or "amount" not in headers:
        return []
    index = headers.index(split_by)
    totals: dict[tuple[str, str, tuple[tuple[str, str], ...]], Decimal] = {}
    order: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
    for row in rows:
        node = _cell(row, index)
        key = (node, _account_optional(headers, row), tuple(fact_dims(headers, row)))
        if key not in totals:
            order.append(key)
            totals[key] = Decimal("0")
        totals[key] += _amount(headers, row)
    return [
        CutLine(node, node, account, dims, totals[(node, account, dims)], MATCH_SPLIT)
        for node, account, dims in order
    ]


def table_key(name: str) -> str:
    """The identifier a table id actually lands under in the catalog.

    ``write_table`` routes every CREATE through ``sql_identifier``, so the
    operator's ``ar-2024-08`` is the catalog's ``ar_2024_08``. Comparisons
    between what a question or a follow-up names and what the window holds go
    through this, or a table that IS in the window reads as absent and the
    brief asserts not-in-this-window about data it is sitting on.
    """
    return sql_identifier(name)


def fact_table_ids(required_table_ids: list[str]) -> list[str]:
    """Every named (non-master) table a question declares, as catalog ids.

    A question answers from one named table; ``coa``/``aux``/``map``/``units``
    only shape the cut. More than one entry here means the question has no
    defined calculation, so callers refuse it instead of picking one.
    """
    return [table_key(table) for table in required_table_ids if table_key(table) not in MASTER_TABLES]


def fact_table_id(required_table_ids: list[str]) -> str | None:
    tables = fact_table_ids(required_table_ids)
    return tables[0] if tables else None


def source_table_id(required_table_ids: list[str]) -> str:
    """The single table a conclusion or a follow-up computes from.

    ``emit_brief`` and ``query_locked`` must agree on this table or a leader
    re-asking a question that IS in the brief gets a number the brief never
    claimed, stamped 稿外追问. One selector, both callers -- including the
    refusal when a caller names two fact tables, so a two-table follow-up can
    never answer from the first one and archive that as the whole story.
    """
    if not required_table_ids:
        raise LockRefused("required_table_ids is required")
    facts = fact_table_ids(required_table_ids)
    if len(facts) > 1:
        raise LockRefused(
            f"names more than one named table: {', '.join(facts)}; "
            "一问一表，没有定义跨表口径，拆成每表一问再报"
        )
    return facts[0] if facts else table_key(required_table_ids[0])


def format_cut(cut: MapCut) -> str:
    parts = [f"{node_id}={_num(amount)}" for node_id, _name, amount in cut.nodes]
    if cut.unmapped:
        parts.append(f"未对照={_num(cut.unmapped)}")
    if cut.conflict:
        parts.append(f"冲突={_num(cut.conflict)}")
    return ", ".join(parts) if parts else "未对照=0"


def _num(value: Decimal | float | int) -> int | str:
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    if decimal == decimal.to_integral_value():
        return int(decimal)
    return format(decimal.normalize(), "f")


def as_number(value: Decimal | float | int) -> int | str:
    return _num(value)
