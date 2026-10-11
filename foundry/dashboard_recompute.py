"""看板换资料重算: a card's calculation run again on newer files of the same name (notes/claude-dashboards-borrowing-plan-20261010.md, 八 3b).

A card names a run, and the run names the files it read. Two things move a card to a new run:

- **In the task**: a file it read has a newer version, the rule 待重算 already uses (finance_controls.superseded_snapshots):
  the corrected file added again under its name, a published source refresh, or next month's pack confirmed under the
  same sheet names. ``recompute`` runs the same calculation on the newest version.
- **From another task**: last month's task holds the board. ``carry`` runs each card's calculation on this task's
  files of the same names and puts the cards on this task's board.

Either way the card lands on the new run waiting for the manager to accept it again, with what it showed before, what
it shows now and whether that is a change worth a look (``recomputed``). Nothing is accepted for the manager.

What is run again, and how:

- finance scenarios (回款健康, driver models), management P&L metrics and variances: a new context with the files
  swapped (scopes and policies kept), the same scenario inputs or spec, run again;
- SQL and structured aggregates: a new revision of the same analysis on the new files, run;
- scripts: the same code on the new files.

When the new files declare another month than the calculation was for, the month moves with them: month scopes,
the rows a card names by its period, and a scenario's 已过月数 when it was that month's. A calculation that names
the old month anywhere else (SQL, a plan, code, a spec) is not run, nor one that rests on what belongs to the old
context (adjustments, another task's account map) or on a cutoff date (receivables aging, 13-week cash). The card
stays where it was and says why (``recompute_failed``), and is not tried again until its files change again.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from foundry.dashboards import WHAT_IF, matching_rows, normalize_select
from foundry.errors import FoundryError
from foundry.task import now_iso

RERUN_SCENARIOS = frozenset({"collection_health", "driver_model"})
SCRIPT_ENGINES = frozenset({"python", "shell"})
QUERY_ENGINES = frozenset({"sql", "structured_aggregate"})
# A figure that moved a tenth (a rate, a point), or changed sign, is a change worth a look; a level that moved always is.
CHANGE_SHARE = Decimal("0.10")
CHANGE_POINTS = Decimal("1")
POINT_UNITS = frozenset({"%", "百分点"})
# A finance ratio metric keeps its rate as a fraction (0.8732) beside the money unit it was taken from.
FRACTION_COLUMNS = frozenset({"ratio", "ratio_exact"})
LEVEL_WORDS = {"red": "红", "orange": "橙", "yellow": "黄", "green": "绿", "unknown": "无法判断"}
SUFFIX = re.compile(r"（按 [^）]* 重算）$")


class NotRerun(Exception):
    """Why a card's calculation is not run again, in the manager's words."""


# -- months ----------------------------------------------------------------------------------------------------------

_MONTH_FORMS = (
    (re.compile(r"^(\d{4})-(\d{1,2})$"), "{y}-{m:02d}"),
    (re.compile(r"^(\d{4})(\d{2})$"), "{y}{m:02d}"),
    (re.compile(r"^(\d{4})/(\d{1,2})$"), "{y}/{m:02d}"),
    (re.compile(r"^(\d{4})\.(\d{1,2})$"), "{y}.{m:02d}"),
    (re.compile(r"^(\d{4})年(\d{1,2})月$"), "{y}年{m}月"),
)


def month_of(text: Any) -> str | None:
    """``YYYY-MM`` of a value that names one month and nothing else, in the forms a pack writes it; else None."""
    if not isinstance(text, str):
        return None
    for pattern, _ in _MONTH_FORMS:
        found = pattern.fullmatch(text.strip())
        if found and 1 <= int(found.group(2)) <= 12:
            return f"{int(found.group(1)):04d}-{int(found.group(2)):02d}"
    return None


def moved_text(text: Any, move: tuple[str, str] | None) -> Any:
    """The same month form, one month moved: 「2026-08」→「2026-09」, 「2026年8月」→「2026年9月」. Anything else as it was."""
    if not move or month_of(text) != move[0]:
        return text
    year, month = (int(part) for part in move[1].split("-"))
    for pattern, form in _MONTH_FORMS:
        found = pattern.fullmatch(text.strip())
        if found:
            if form.endswith("月") and found.group(2).startswith("0"):
                form = "{y}年{m:02d}月"
            return form.format(y=year, m=month)
    return text


def month_spellings(month: str) -> list[str]:
    year, number = month.split("-")
    return [month, f"{year}{number}", f"{year}/{number}", f"{year}.{number}", f"{year}年{int(number)}月", f"{year}年{number}月"]


def _names_month(value: Any, month: str) -> bool:
    text = json.dumps(value, ensure_ascii=False)
    return any(spelling in text for spelling in month_spellings(month))


def _scope_month(scopes: list[dict]) -> str | None:
    """The one month the scopes are for; None when they name none or disagree."""
    months = {month_of((scope or {}).get("period")) for scope in scopes if (scope or {}).get("period")}
    months.discard(None)
    return months.pop() if len(months) == 1 else None


_DATED = re.compile(r"\d{4}\s*[-/.年]\s*\d{1,2}")


def _ranged(period: Any) -> bool:
    """A period that names months but not one month: 「2026-01:2026-08」, 「2026年1-8月」."""
    return isinstance(period, str) and month_of(period) is None and bool(_DATED.search(period))


def _moved_scope(scope: Any, move: tuple[str, str] | None) -> Any:
    if not move or not isinstance(scope, dict) or not scope.get("period"):
        return scope
    if month_of(scope["period"]) is None:
        if move[0] in str(scope["period"]):
            raise NotRerun(f"期间写的是区间「{scope['period']}」，换到 {move[1]} 要你重新设定期间")
        return scope
    return {**scope, "period": moved_text(scope["period"], move)}


# -- files -----------------------------------------------------------------------------------------------------------

def _order(row: dict) -> tuple:
    return (row.get("seq", 0), str(row.get("created_at") or ""), row["id"])


def newest_versions(store) -> Callable[[str], str | None]:
    """In the task: the newest version of a file a newer one replaced (the rule 待重算 uses), or None when it is current."""
    from foundry.finance_controls import refreshed_snapshots, superseded_snapshots

    datasets = store.analysis.published_datasets()
    allowed = store.allowed
    visible = [row for row in datasets if allowed is None or row["id"] in allowed]
    replaced = superseded_snapshots(store.task, visible, allowed=allowed)
    refreshed = refreshed_snapshots(store.task, allowed)
    by_id = {row["id"]: row for row in visible}
    latest: dict[str, dict] = {}
    for row in visible:
        name = str(row.get("name") or "").strip()
        if name and (name not in latest or _order(latest[name]) < _order(row)):
            latest[name] = row

    def newest(old: str) -> str | None:
        current, seen = old, set()
        while current in replaced and current not in seen:
            seen.add(current)
            newers = [by_id[item] for item in refreshed.get(current, ()) if item in by_id]
            if newers:
                current = max(newers, key=_order)["id"]
                continue
            named = latest.get(str((by_id.get(current) or {}).get("name") or "").strip())
            if not named or named["id"] == current:
                break
            current = named["id"]
        return current if current != old else None

    return newest


def same_names(store) -> Callable[[dict], str | None]:
    """In another task: this task's current file of the same name as the given one, or None."""
    from foundry.finance_controls import superseded_snapshots

    datasets = store.analysis.published_datasets()
    replaced = superseded_snapshots(store.task, datasets)
    latest: dict[str, dict] = {}
    for row in datasets:
        name = str(row.get("name") or "").strip()
        if name and row["id"] not in replaced and (name not in latest or _order(latest[name]) < _order(row)):
            latest[name] = row
    return lambda dataset: (latest.get(str(dataset.get("name") or "").strip()) or {}).get("id")


def rebind(bindings: dict[str, str], read_old, read_new, find: Callable[[dict], str | None]) -> tuple[dict, list[str]]:
    """Each alias on its new file, and the names of the files there is none for. A whole workbook kept beside its
    tables follows them to the workbook they now come from."""
    old = {alias: read_old(value) for alias, value in bindings.items()}
    new = {alias: find(dataset) for alias, dataset in old.items()}
    for alias, dataset in old.items():
        if new[alias] or dataset.get("kind") != "workbook":
            continue
        follows = {(read_new(new[other]).get("metadata") or {}).get("derived_from")
                   for other, table in old.items()
                   if new[other] and (table.get("metadata") or {}).get("derived_from") == dataset["id"]}
        follows.discard(None)
        if len(follows) == 1:
            new[alias] = follows.pop()
    missing = [str(old[alias].get("name") or alias) for alias, value in new.items() if not value]
    return new, missing


def other_months(store, ids: list[str], month: str) -> list[str]:
    """The names of the files among ``ids`` that declare a month other than ``month``."""
    from foundry.finance_readiness import _snapshot_period

    names = []
    for dataset_id in ids:
        try:
            dataset = store.analysis.read_dataset(dataset_id)
        except FoundryError:
            continue
        declared = month_of(_snapshot_period(dataset))
        if declared and declared != month:
            names.append(str(dataset.get("name") or dataset_id))
    return sorted(set(names))


def new_month(store, ids: list[str], fallback: Any = None) -> str | None:
    """The month the new files declare, when they agree; else the fallback's (the task's period, from another task)."""
    from foundry.finance_readiness import _snapshot_period

    months = set()
    for dataset_id in ids:
        try:
            months.add(month_of(_snapshot_period(store.analysis.read_dataset(dataset_id))))
        except FoundryError:
            continue
    months.discard(None)
    if len(months) == 1:
        return months.pop()
    return month_of(fallback) if not months else None


# -- calculations ----------------------------------------------------------------------------------------------------

def recipe_of(source, run: dict, *, elsewhere: bool) -> dict:
    """What ``run`` calculated, as it can be saved again on other files. ``elsewhere``: for another task."""
    revision = source.analysis.get_analysis(run["analysis_id"])
    engine = revision.get("engine") or "sql"
    if engine == "finance":
        context = source._read("contexts", run["finance_context_id"])
        spec = {key: value for key, value in (revision.get("finance_spec") or {}).items()
                if key not in {"context_id", "definition_id", "parent_id", "scenario_id"}}
        if spec.get("adjustment_ids"):
            raise NotRerun("这次计算用了调整分录，调整属于上一版口径，换资料要你重新确认")
        if elsewhere and context.get("account_map_id"):
            raise NotRerun("这次计算用了科目映射，映射在原任务里，带不过来")
        recipe = {
            "engine": "finance", "operation": revision["operation"], "spec": spec, "revision_id": revision["id"],
            "context": {key: context.get(key) for key in ("id", "name", "scopes", "policies", "account_map_id")},
            "bindings": dict(context["bindings"]),
        }
        if revision["operation"] == "scenario":
            scenario = source._read("scenarios", revision["finance_spec"]["scenario_id"])
            if scenario["kind"] not in RERUN_SCENARIOS or scenario.get("actual_cutoff"):
                raise NotRerun("这类结果按截止日计算，换资料要你重新指定截止日")
            recipe["scenario"] = {"kind": scenario["kind"], "label": scenario["label"], "inputs": scenario["inputs"]}
        elif revision["operation"] not in {"metric", "variance"}:
            raise NotRerun("这类结果还不能换资料重算")
        return recipe
    if revision.get("topic"):
        # A script drawn in place of 回款健康 while the workbook's structure waited: next month runs it on the engine.
        raise NotRerun("这张卡来自回款健康的脚本草稿，确认表结构后让助手用财务引擎重算")
    if engine in QUERY_ENGINES or engine in SCRIPT_ENGINES:
        return {"engine": engine, "revision": revision, "revision_id": revision["id"], "bindings": dict(revision["bindings"])}
    raise NotRerun("这类结果还不能换资料重算")


def recipe_month(recipe: dict) -> str | None:
    """The month the calculation was for: its context's month scopes, or the analysis's own scope."""
    if recipe["engine"] == "finance":
        return _scope_month(list(((recipe["context"].get("scopes")) or {}).values()))
    return month_of(((recipe["revision"].get("scope")) or {}).get("period"))


def month_move(recipe: dict, new: str | None) -> tuple[str, str] | None:
    """The calculation's month to the new files' month, or None when it stays. A period written as a range is not moved:
    the manager sets it again (a calculation over 1–8 月 on September's files would say 1–8 月 of 1–9 月's figures)."""
    old = recipe_month(recipe)
    if not new or old == new:
        return None
    if old:
        return old, new
    periods = ([(scope or {}).get("period") for scope in ((recipe["context"].get("scopes")) or {}).values()]
               if recipe["engine"] == "finance" else [((recipe["revision"].get("scope")) or {}).get("period")])
    for period in periods:
        if _ranged(period) and not _names_month(period, new):
            raise NotRerun(f"期间写的是区间「{period}」，换到 {new} 要你重新设定期间")
    return None


def _months_elapsed(inputs: dict, move: tuple[str, str] | None) -> tuple[dict, list[str]]:
    """A scenario's 已过月数 moved with the month when it was that month's; the words for what moved."""
    if not move or not isinstance(inputs.get("entities"), list):
        return inputs, []
    old, new = int(move[0][5:]), int(move[1][5:])
    said: list[str] = []
    entities = []
    for entity in inputs["entities"]:
        values = (entity or {}).get("values") if isinstance(entity, dict) else None
        if isinstance(values, dict) and values.get("months_elapsed") == old and not isinstance(values["months_elapsed"], bool):
            entity = {**entity, "values": {**values, "months_elapsed": new}}
            said.append(f"已过月数 {old} → {new}")
        entities.append(entity)
    return {**inputs, "entities": entities}, sorted(set(said))


def manual_inputs(inputs: Any) -> list[str]:
    """The figures a scenario was given by hand, carried as they were; 已过月数 is said where it moves."""
    from foundry.collection_metrics import INPUT_LABELS

    names: set[str] = set()
    for entity in (inputs or {}).get("entities") or [] if isinstance(inputs, dict) else []:
        for key, value in ((entity or {}).get("values") or {}).items() if isinstance(entity, dict) else []:
            if key != "months_elapsed" and isinstance(value, (int, float, str)) and not isinstance(value, bool):
                names.add(INPUT_LABELS.get(key, key))
    return sorted(names)


def run_again(target, recipe: dict, bindings: dict[str, str], move: tuple[str, str] | None, *, elsewhere: bool) -> tuple[dict, list[str]]:
    """Save the calculation again on ``bindings`` in ``target`` and run it. Returns the run and what moved with the month."""
    if move:
        # The month moves where it is a scope or a 已过月数; anywhere else it is written into the calculation.
        written = ({key: recipe["revision"].get(key) for key in ("sql", "aggregate_plan", "parameters", "code")}
                   if recipe["engine"] != "finance" else {"spec": recipe["spec"], "scenario": recipe.get("scenario")})
        if _names_month(written, move[0]):
            raise NotRerun(f"计算里写着 {move[0]}，换到 {move[1]} 会算错，要你重新计算")
    said: list[str] = []
    if recipe["engine"] == "finance":
        context = recipe["context"]
        scopes = {alias: _moved_scope(scope, move) for alias, scope in (context.get("scopes") or {}).items()}
        name = SUFFIX.sub("", str(context.get("name") or "财务分析口径"))
        name = f"{name}（按 {move[1] if move else '新资料'} 重算）"[:200]
        saved = target.save_context({
            "name": name, "bindings": bindings, "scopes": scopes, "policies": context.get("policies") or {},
            **({} if elsewhere else {"account_map_id": context.get("account_map_id"), "parent_id": context["id"]}),
        })
        spec = dict(recipe["spec"])
        if recipe["operation"] == "scenario":
            inputs, said = _months_elapsed(recipe["scenario"]["inputs"], move)
            scenario = target.save_scenario({"context_id": saved["id"], "kind": recipe["scenario"]["kind"],
                                             "label": recipe["scenario"]["label"], "inputs": inputs})
            return target.run_scenario({**spec, "scenario_id": scenario["id"],
                                        **({} if elsewhere else {"parent_id": recipe["revision_id"]})}), said
        spec = {**spec, "context_id": saved["id"], **({} if elsewhere else {"parent_id": recipe["revision_id"]})}
        if recipe["operation"] == "metric":
            return target.run_metric(spec), said
        return target.explain_variance(spec), said
    revision = recipe["revision"]
    scope = _moved_scope(revision.get("scope") or {}, move)
    if recipe["engine"] in SCRIPT_ENGINES:
        return target.analysis.run_script({
            "code": revision["code"], "language": revision["engine"], "bindings": bindings, "question": revision["question"],
            "timeout_seconds": revision.get("timeout_seconds", 30), "assumptions": revision.get("assumptions", []),
            "result_file": revision.get("result_file"), "result_role": revision.get("result_role"), "scope": scope,
        }, session_id=target.session_id, context_revision=target.context_revision, allowed=target.allowed), said
    spec = {key: revision.get(key) for key in (
        "question", "engine", "sql", "aggregate_plan", "parameters", "parameter_metadata", "relationships", "metrics",
        "grain", "assumptions", "missing_inputs", "conversion_rules", "result_role", "max_rows", "timeout_seconds")
        if revision.get(key) is not None}
    if spec.get("engine") != "structured_aggregate":
        spec.pop("aggregate_plan", None)
    else:
        spec.pop("sql", None)
        spec.pop("parameters", None)
        spec.pop("parameter_metadata", None)
        spec.pop("relationships", None)
    saved = target.analysis.save_analysis({**spec, "bindings": bindings, "scope": scope,
                                          **({} if elsewhere else {"parent_id": revision["id"]})},
                                         session_id=target.session_id, context_revision=target.context_revision)
    return target.analysis.run_analysis(saved["id"], session_id=target.session_id,
                                        context_revision=target.context_revision, allowed=target.allowed), said


# -- what a card shows -----------------------------------------------------------------------------------------------

def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def shown(card: dict, run: dict) -> dict:
    """What the card shows of ``run``, kept beside the card so a later run can say what changed."""
    rows = (run.get("result") or {}).get("rows") or []
    select = card["select"]
    found = [row for _, row in matching_rows(rows, select.get("match") or {})]
    if card["kind"] == "figure":
        row = found[0] if len(found) == 1 else {}
        value = row.get(select.get("column"))
        display = row.get("display_value") if select.get("column") == "value" and row.get("display_value") else value
        rate = "fraction" if select.get("column") in FRACTION_COLUMNS else "points" if row.get("unit") in POINT_UNITS else None
        return {"value": None if value is None else str(value), "display": None if display is None else str(display),
                "level": row.get("level"), "unit": row.get("unit"), "rate": rate}
    if card["kind"] == "goal":
        return _goal_shown(select, rows, found, run)
    if card["kind"] in WHAT_IF:
        # A scenario or a sensitivity grid is judged by where its entity stands against the line: the grid's framed
        # cell is that same figure.
        row = next((row for row in found if row.get("metric_key") == "collection_gap"), {})
        return {"value": None if row.get("value") is None else str(row["value"]),
                "display": row.get("display_value"), "level": row.get("level"), "unit": row.get("unit")}
    if card["kind"] == "rank":
        column, label = select["column"], select["label"]
        ranked = [(str(row[label]), _number(row.get(column))) for row in found
                  if _number(row.get(column)) is not None and row.get(label) not in (None, "")]
        ranked.sort(key=lambda item: item[1], reverse=select.get("order", "desc") == "desc")
        # The leaders with their ties: a third place shared by four is four leaders, whatever order the rows came in.
        third = ranked[min(2, len(ranked) - 1)][1] if ranked else None
        ahead = (lambda value: value >= third) if select.get("order", "desc") == "desc" else (lambda value: value <= third)
        reference = _number((select.get("reference") or {}).get("value"))
        worse = (lambda value: value < reference) if select.get("order") == "asc" else (lambda value: value > reference)
        return {"labels": [name for name, _ in ranked[:select.get("limit", 10)]],
                "leaders": sorted(name for name, value in ranked if third is not None and ahead(value)),
                "beyond": sorted(name for name, value in ranked if worse(value)) if reference is not None else None}
    lines = {row.get("metric"): row for row in found}
    profit = lines.get("profit") or {}
    return {"profit": [None if profit.get(key) is None else str(profit.get(key)) for key in ("baseline", "actual")],
            "steps": {metric: None if (lines.get(metric) or {}).get("contribution") is None else str(lines[metric]["contribution"])
                      for metric in ("revenue", "cost", "expense")}}


def _goal_shown(select: dict, rows: list, found: list, run: dict) -> dict:
    """A goal card's answer as it reads (foundry/what_if.py): the amount or the rate it works back to, and what it says of
    it. A month's revenue moves that amount without moving the line, and a target leaves the line out of it."""
    from foundry import what_if
    from foundry.figure_text import js_text, split_display

    entity = found[0].get("entity") if found else None
    lines = what_if.lines_of(rows, entity)
    try:
        view = (what_if.goal_budget(lines, js_text(entity)) if select.get("goal") == "budget"
                else what_if.goal_collection(lines, js_text(entity), select.get("target"), (run.get("result") or {}).get("params") or {}))
    except (KeyError, TypeError, ValueError):
        return {"value": None, "display": None, "level": None, "unit": None, "part": None}
    figure, unit = split_display(view["value"])
    return {"value": figure.replace(",", ""), "display": view["value"], "level": None,
            "unit": "百分点" if unit == "个百分点" else unit or None, "part": view["part"]}


def _sign(value: Decimal | None) -> int:
    return 0 if value is None or value == 0 else (1 if value > 0 else -1)


def change(card: dict, before: dict, after: dict) -> tuple[bool, str]:
    """Whether the card moved enough to look at, and the words for how it moved."""
    if card["kind"] == "figure" or card["kind"] in WHAT_IF:
        if card["kind"] == "goal" and before.get("part") and after.get("part") and before["part"] != after["part"]:
            # Short of the goal, at it, past it: the figure is the gap's size, so the words say which side it is on.
            return True, f"{before['part']} → {after['part']}"
        if before.get("level") and after.get("level") and before["level"] != after["level"]:
            return True, f"级别 {LEVEL_WORDS.get(before['level'], before['level'])} → {LEVEL_WORDS.get(after['level'], after['level'])}"
        old, new = _number(before.get("value")), _number(after.get("value"))
        if old is None or new is None:
            moved = before.get("display") != after.get("display")
            return moved, "数变了" if moved else "没有变化"
        if _sign(old) and _sign(new) and _sign(old) != _sign(new):
            return True, "由正转负" if _sign(new) < 0 else "由负转正"
        rate = after.get("rate") or ("points" if after.get("unit") in POINT_UNITS else None)
        if rate:
            # A rate moves in points: 82.1% to 83.0% is +0.9 个百分点, not +1.1%; a fraction 0.80 to 0.81 is +1.00.
            points = (new - old) * (100 if rate == "fraction" else 1)
            return abs(points) >= CHANGE_POINTS, f"{'+' if points > 0 else ''}{points.quantize(Decimal('0.01'))} 个百分点"
        if old == 0:
            return new != 0, "由零变为非零" if new != 0 else "没有变化"
        share = (new - old) / abs(old)
        words = f"变动 {'+' if share > 0 else ''}{(share * 100).quantize(Decimal('0.1'))}%"
        return abs(share) >= CHANGE_SHARE, words
    if card["kind"] == "rank":
        # How many are past the line, not who: one crossing each way leaves the line where it was.
        if before.get("beyond") is not None and len(before["beyond"]) != len(after.get("beyond") or []):
            label = (card["select"].get("reference") or {}).get("label") or "参考线"
            side = "低于" if card["select"].get("order") == "asc" else "高于"
            return True, f"{side}{label}的：{len(before['beyond'])} 个 → {len(after['beyond'] or [])} 个"
        old, new = set(before.get("leaders") or []), set(after.get("leaders") or [])
        if old != new:
            came, went = sorted(new - old), sorted(old - new)
            names = lambda rows: "、".join(rows[:2]) + ("等" if len(rows) > 2 else "")  # noqa: E731
            return True, f"{names(came)}排进前三" if came else f"{names(went)}退出前三"
        return False, "前三名没有变化"
    for metric, word in (("revenue", "收入"), ("cost", "成本"), ("expense", "费用")):
        old, new = _number((before.get("steps") or {}).get(metric)), _number((after.get("steps") or {}).get(metric))
        if _sign(old) and _sign(new) and _sign(old) != _sign(new):
            return True, f"{word}的影响{'由正转负' if _sign(new) < 0 else '由负转正'}"
    return False, "各项影响的方向没有变化"


def moved_select(select: dict, move: tuple[str, str] | None) -> dict:
    """The rows a card names, in the new month when the card named its rows by their month."""
    if not move:
        return select
    return {**select, "match": {column: moved_text(text, move) for column, text in (select.get("match") or {}).items()}}


# -- the board -------------------------------------------------------------------------------------------------------

def moved_card(card: dict, old_run: dict | None, new_run: dict, move: tuple[str, str] | None, *, before: dict | None,
               said: list[str], manual: list[str], carried: dict | None) -> dict:
    """The card on the new run, waiting for the manager again. Raises NotRerun when the new run has no such rows."""
    try:
        select = normalize_select(card["kind"], moved_select(card["select"], move), new_run)
    except FoundryError:
        raise NotRerun("新结果里找不到这张卡读的那几行") from None
    moved = {**card, "run_id": new_run["id"], "select": select,
             "state": "explore" if card["state"] == "explore" else "pinned", "accepted": None, "recompute_failed": None}
    after = shown(moved, new_run)
    before = before if before is not None else (shown(card, old_run) if old_run else None)
    changed, words = change(moved, before, after) if before else (False, "")
    moved["recomputed"] = {
        "at": now_iso(), "from_run_id": card["run_id"], "was_accepted": card["state"] == "accepted",
        "months": list(move) if move else None, "before": before, "after": after, "changed": changed, "change": words,
        "adjusted": said, "manual": manual, "carried_from": carried,
    }
    return moved


def failed(card: dict, reason: str, bindings: dict[str, str]) -> dict:
    return {**card, "recompute_failed": {"at": now_iso(), "reason": reason, "bindings": dict(sorted(bindings.items()))}}
