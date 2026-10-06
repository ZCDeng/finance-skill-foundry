"""What kind of evidence stands behind each number and statement a draft uses, and how much the draft can bear.

Twelve labels, assigned only from records the server holds (claims and their basis, the facts of cited runs,
requirement locations, evidence recipe results, consistency results, revision comparison, row declarations and
dataset freshness). Prose is never read for them, and labels or a posture a caller sends are never read either.

    fact_source_reported        来源原文     a source fact or a cell a recipe matched to the original sheet
    fact_provider_standardized  标准化数据   the finance engine's mapped totals, a verified snapshot aggregate,
                                             or a system source refresh
    derived_calculation         派生计算     a recorded SQL or server calculation the cited value matches (a script's
                                             output only when a passing source recipe backs it)
    management_claim            管理层说法   a statement a source text makes (a consistency assertion with a text source)
    analyst_interpretation      分析判断     professional judgment, or an assertion with no source text
    assumption_user_provided    用户假设     written in as an assumption (also when it cites a fact: the writer's
                                             basis is kept, and the claim counts as an item of its own)
    assumption_inferred         推断假设     a result row read as an estimate from its own fields or words,
                                             with no requirement declaring it
    estimate                    估算         declared an estimate by the requirements, or a factor recipe
    stale_source                过期来源     an older run of the same calculation, or a run or source whose dataset
                                             is superseded or as of a date before the period closes
    contradicted_source         矛盾来源     a recipe mismatch, a claim that differs from its fact or run, a group
                                             that does not close, a consistency mismatch, a revision regression
    missing_required_source     缺必需来源   a required fact not cited, a cited fact that no longer exists, an
                                             unanswered requirement, a source check not done or not readable
    unknown                     未知         a number in the text bound to nothing, a claim naming no basis or source,
                                             script output no source recipe backs, or a recipe that only proves
                                             a free coefficient

The label shown is contradicted_source, else missing_required_source, else stale_source, else the base label;
``base_label`` always keeps what the evidence is, so a stale or contradicted label never erases provenance.

Evidence posture (rules_version 1). Counted over the labelled items; a claim and the fact it cites are one item,
labelled by the worse of the two, except an assumption or judgment claim, which is an item of its own:

    无法支持 unsupported      any contradicted_source or missing_required_source
    假设主导 assumption_led   else, user assumptions, inferred assumptions and estimates are at least half the items
    初步     preliminary      else, any stale_source or unknown, nothing labelled at all, or the coverage or
                              provenance check has not passed (not assessed is not passed)
    研究级   research_grade   else, any assumption, estimate, analyst interpretation or management claim
    可决策   decision_grade   everything is source, standardized or derived, and those checks passed

The posture classifies the evidence a draft cites. It is not a status: it is never merged into status,
status_dimensions, checks, the close headline or completion, and it adds no issue. 可决策 says the numbers are
source-backed, not that the manager approved anything.

Dataset freshness compares only declared periods and dates (never the machine clock) with the task period,
the period of the latest requirements scope:

    source_stale     资料过期   superseded by a published refresh or a newer upload of the same name (unless the
                                two declare different periods), or the file covers the task period but is as of a
                                date before the period closes
    period_mismatch  期间不符   the declared period is not the task period (a dated file of another period is a
                                mismatch, not stale), or an as-of-only file is dated before or after it
    unknown          未声明     no task period, or the file declares neither period nor as-of date
    current          当前       otherwise
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

RULES_VERSION = "1"

LABELS = {
    "fact_source_reported": "来源原文",
    "fact_provider_standardized": "标准化数据",
    "derived_calculation": "派生计算",
    "management_claim": "管理层说法",
    "analyst_interpretation": "分析判断",
    "assumption_user_provided": "用户假设",
    "assumption_inferred": "推断假设",
    "estimate": "估算",
    "stale_source": "过期来源",
    "contradicted_source": "矛盾来源",
    "missing_required_source": "缺必需来源",
    "unknown": "未知",
}
POSTURES = {
    "decision_grade": "可决策",
    "research_grade": "研究级",
    "preliminary": "初步",
    "assumption_led": "假设主导",
    "unsupported": "无法支持",
}
FRESHNESS = {
    "current": "当前",
    "source_stale": "资料过期",
    "period_mismatch": "期间不符",
    "unknown": "未声明",
}

CONTRADICTED, MISSING, STALE = "contradicted_source", "missing_required_source", "stale_source"
# Worst first: the order the shown label is chosen in.
PROBLEMS = (CONTRADICTED, MISSING, STALE)
ASSUMED = ("assumption_user_provided", "assumption_inferred", "estimate")
JUDGED = (*ASSUMED, "analyst_interpretation", "management_claim")
PASSED_CHECKS = {"pass", "pass_with_accepted_estimates"}
# A claim that says the number is assumed or judged keeps that basis even when it cites a fact.
OWN_BASIS = {
    "user_assumption": ("assumption_user_provided", "claim_assumption", "按假设写入，没有来源可核对"),
    "professional_judgment": ("analyst_interpretation", "claim_judgment", "专业判断，需要复核"),
}

_PERIOD = re.compile(r"(\d{4})\s*[-./年]\s*(\d{1,2})\s*月?")
_COMPACT_PERIOD = re.compile(r"(\d{4})(\d{2})")
_YEAR = re.compile(r"(\d{4})\s*年?")
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


# --- periods and dates --------------------------------------------------------------------------------------


def as_of_date(value: Any) -> str | None:
    """A declared YYYY-MM-DD date, or None. Nothing is defaulted."""
    text = str(value or "").strip()
    match = _DATE.fullmatch(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def period_span(value: Any) -> tuple[str, str, str] | None:
    """(first day, last day, kind) of a declared month, year, date or ``A:B`` range; None if it is not one."""
    text = str(value or "").strip()
    if not text:
        return None
    if ":" in text:
        start, _, end = text.partition(":")
        first, last = period_span(start), period_span(end)
        if first is None or last is None or first[0] > last[1]:
            return None
        return first[0], last[1], "range"
    day = as_of_date(text)
    if day:
        return day, day, "as_of"
    match = _PERIOD.fullmatch(text) or _COMPACT_PERIOD.fullmatch(text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            return None
        last = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}", "month"
    match = _YEAR.fullmatch(text)
    if match:
        return f"{match.group(1)}-01-01", f"{match.group(1)}-12-31", "annual"
    return None


def _reason(code: str, text: str) -> dict[str, str]:
    return {"code": code, "text": text}


def dataset_freshness(
    *,
    period: str | None,
    as_of: str | None,
    period_kind: str | None,
    task_period: str | None,
    superseded: bool,
) -> dict[str, Any]:
    """Whether one file speaks for the task period: current, source_stale, period_mismatch or unknown."""
    stale: list[dict[str, str]] = []
    mismatch: list[dict[str, str]] = []
    if superseded:
        stale.append(_reason("superseded", "已被更新的版本取代（同名重新上传或已发布的刷新）"))
    task = period_span(task_period)
    own = period_span(period) if period else None
    unknown: list[dict[str, str]] = []
    if task is None:
        unknown.append(_reason("no_task_period", "分析期间还没确认，无法判断时效")
                       if not str(task_period or "").strip()
                       else _reason("task_period_unreadable", f"分析期间「{task_period}」不是年月格式，无法比较"))
    elif period and own is None:
        unknown.append(_reason("period_unreadable", f"资料期间「{period}」不是年月格式，无法比较"))
    elif not own and not as_of:
        unknown.append(_reason("no_dataset_period", "资料没有声明期间或截至日"))
    else:
        start, end, _kind = task
        covers = bool(own) and own[0] <= start and end <= own[1]
        if own and not covers:
            mismatch.append(_reason("period_differs", f"资料期间 {period} 与分析期间 {task_period} 不同"))
        if as_of and own:
            # A dated extract of the right period that stops before the period closes is incomplete. A file of
            # another period (last month's baseline) is a period mismatch, never stale for that alone; that it
            # stops before its own period closes is said beside the mismatch.
            if covers and as_of < end:
                stale.append(_reason("as_of_before_period_end", f"截至日 {as_of} 早于期末 {end}"))
            elif not covers and as_of < own[1]:
                mismatch.append(_reason("as_of_before_own_period_end", f"截至日 {as_of} 早于该资料期末 {own[1]}，资料本身可能不完整"))
        elif as_of:
            # An as-of-only file (a balance at a date) names a point: before the period is another period,
            # inside it before the close is incomplete, after it is a later point.
            if as_of < start:
                mismatch.append(_reason("as_of_before_period", f"截至日 {as_of} 在分析期间 {task_period} 之前"))
            elif as_of < end:
                stale.append(_reason("as_of_before_period_end", f"截至日 {as_of} 早于期末 {end}"))
            elif as_of > end and period_kind == "as_of":
                mismatch.append(_reason("as_of_after_period", f"截至日 {as_of} 在分析期间 {task_period} 之后"))
    if stale:
        return {"state": "source_stale", "reasons": [*stale, *mismatch]}
    if mismatch:
        return {"state": "period_mismatch", "reasons": mismatch}
    if unknown:
        return {"state": "unknown", "reasons": unknown}
    return {"state": "current", "reasons": []}


# --- labels ------------------------------------------------------------------------------------------------


def _cell(value: Any) -> tuple[str, int, str] | None:
    if not isinstance(value, dict):
        return None
    run_id, row, column = value.get("run_id"), value.get("row"), value.get("column")
    if not isinstance(run_id, str) or isinstance(row, bool) or not isinstance(row, int) or not isinstance(column, str):
        return None
    return run_id, row, column


def _same_number(left: Any, right: Any) -> bool:
    if left == right:
        return True
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except InvalidOperation:
        return False


def _run_value(run: dict | None, row: int, column: str) -> tuple[bool, Any]:
    """The cell a calculation claim names, as the run stored it; (False, None) when it is not there."""
    rows = ((run or {}).get("result") or {}).get("rows")
    if isinstance(rows, list) and 0 <= row < len(rows) and isinstance(rows[row], dict) and column in rows[row]:
        return True, rows[row][column]
    return False, None


def _where(location: Any) -> str:
    if isinstance(location, dict) and location.get("sheet") and location.get("range"):
        return f"{location['sheet']}!{location['range']}"
    return ""


def _source_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("dataset_id"), str):
            continue
        item = {key: ref[key] for key in ("dataset_id", "source_hash", "sheet", "range", "paragraph")
                if ref.get(key) not in (None, "")}
        if item not in clean:
            clean.append(item)
    return clean


def _scope_period(scope: Any) -> str | None:
    """The fact's period: its own, or the one every side of a comparison shares."""
    if not isinstance(scope, dict):
        return None
    if isinstance(scope.get("period"), str) and scope["period"].strip():
        return scope["period"].strip()
    nested = {value.get("period") for value in scope.values() if isinstance(value, dict) and value.get("period")}
    return next(iter(nested)) if len(nested) == 1 and isinstance(next(iter(nested)), str) else None


class _Entry:
    """One labelled item while it is being built: a base, problem reasons by kind, sources."""

    def __init__(self, key: dict[str, Any]):
        self.key = key
        self.base: str | None = None
        self.base_reasons: list[dict[str, str]] = []
        self.problems: dict[str, list[dict[str, str]]] = {code: [] for code in PROBLEMS}
        self.refs: list[dict[str, Any]] = []
        self.as_of: str | None = None
        self.period: str | None = None

    def set_base(self, label: str, reason: dict[str, str]) -> None:
        if self.base is None:
            self.base = label
            self.base_reasons.append(reason)

    def problem(self, label: str, reason: dict[str, str]) -> None:
        if reason not in self.problems[label]:
            self.problems[label].append(reason)

    def output(self) -> dict[str, Any]:
        base = self.base or "unknown"
        shown = next((code for code in PROBLEMS if self.problems[code]), base)
        reasons = [reason for code in PROBLEMS for reason in self.problems[code]] + self.base_reasons
        entry: dict[str, Any] = {
            "key": self.key,
            "label": shown,
            "text": LABELS[shown],
            "base_label": base,
            "reasons": reasons,
            "source_refs": _source_refs(self.refs),
        }
        if self.as_of:
            entry["as_of"] = self.as_of
        if self.period:
            entry["period"] = self.period
        return entry


class _Labeler:
    def __init__(self, *, facts, evidence_groups, issues, requirements, recipe_results, consistency_results,
                 runs, older_runs, row_estimates, datasets):
        self.facts = {fact["id"]: fact for fact in facts if isinstance(fact, dict) and isinstance(fact.get("id"), str)}
        self.by_cell = {}
        for fact in self.facts.values():
            cell = _cell(fact)
            if cell:
                self.by_cell.setdefault(cell, fact)
        self.issues = [issue for issue in issues if isinstance(issue, dict)]
        self.runs = runs
        self.older_runs = older_runs
        self.row_estimates = row_estimates
        self.datasets = datasets
        self.locations: dict[tuple, list[tuple[dict, dict]]] = {}
        for item in (requirements or {}).get("items") or []:
            for location in item.get("locations") or [] if isinstance(item, dict) else []:
                cell = _cell(location)
                if cell:
                    self.locations.setdefault(cell, []).append((item, location))
        self.recipes: dict[tuple, list[dict]] = {}
        for result in recipe_results:
            cell = _cell((result or {}).get("claim")) if isinstance(result, dict) else None
            if cell:
                self.recipes.setdefault(cell, []).append(result)
        self.group_problems: dict[str, list[tuple[str, dict[str, str]]]] = {}
        for group in evidence_groups:
            if not isinstance(group, dict):
                continue
            closure = (group.get("closure") or {}).get("status") if isinstance(group.get("closure"), dict) else None
            found = []
            if closure in {"closure_mismatch", "scope_mismatch", "unit_mismatch"}:
                words = {"closure_mismatch": "加总对不上", "scope_mismatch": "范围不一致", "unit_mismatch": "单位不一致"}[closure]
                found.append((CONTRADICTED, _reason("group_not_closed", f"所在计算依据组没有闭合：{words}")))
            if group.get("status") == "partial":
                found.append((MISSING, _reason("group_partial", "所在计算依据组有科目只在一侧有来源行，比较不完整")))
            for member in group.get("members") or []:
                if found and isinstance(member, dict) and isinstance(member.get("fact_id"), str):
                    self.group_problems.setdefault(member["fact_id"], []).extend(found)
        self.cells: dict[tuple, _Entry] = {}

    # Cells: one entry per cited or located cell, shared by the claims that cite it.

    def cell(self, cell: tuple[str, int, str]) -> _Entry:
        if cell in self.cells:
            return self.cells[cell]
        fact = self.by_cell.get(cell)
        run_id, row, column = cell
        key: dict[str, Any] = {"kind": "fact", "fact_id": fact["id"]} if fact else {"kind": "location"}
        entry = _Entry({**key, "run_id": run_id, "row": row, "column": column})
        run = self.runs.get(run_id)
        self._locations(entry, cell)
        coefficient_only = self._recipes(entry, cell)
        self._row_estimate(entry, cell)
        self._engine(entry, run, fact, coefficient_only=coefficient_only)
        if fact:
            for label, reason in self.group_problems.get(fact["id"], []):
                entry.problem(label, reason)
            entry.period = _scope_period(fact.get("scope"))
        self._run_freshness(entry, run)
        self.cells[cell] = entry
        return entry

    def _locations(self, entry: _Entry, cell: tuple) -> None:
        located = self.locations.get(cell, [])
        bases = {(location.get("evidence") or {}).get("evidence_basis") for _item, location in located}
        if any(location.get("status") == "estimated" for _item, location in located) or "estimate" in bases:
            entry.set_base("estimate", _reason("requirement_estimate", "分析要求把这一格声明为估算，经理确认前不算已回答"))
        elif "source_value" in bases:
            entry.set_base("fact_source_reported", _reason("requirement_source_value", "要求核对：与原表单元格一致"))
        elif bases & {"engine_closed", "engine_output", "aggregate_output"}:
            entry.set_base("fact_provider_standardized", _reason("requirement_engine", "要求核对：财务引擎或服务端汇总的结果"))
        elif "source_calculation" in bases:
            entry.set_base("derived_calculation", _reason("requirement_source_calculation", "要求核对：按原表单元格计算一致"))
        for _item, location in located:
            if location.get("status") == "missing_data":
                reason = (location.get("evidence") or {}).get("not_counted_reason")
                words = {"comparison_partial": "该科目只有一侧有来源行，比较不完整",
                         "evidence_incomplete": "证据缺项、口径或单位不一致，或复算不闭合"}.get(reason, "计算依据不完整")
                entry.problem(MISSING, _reason("requirement_evidence_incomplete", words))

    def _recipes(self, entry: _Entry, cell: tuple) -> bool:
        """Sets the base a passing source or estimate recipe proves; True when a passing recipe only
        proved a free coefficient, which traces nothing to the source."""
        coefficient_only = False
        for result in self.recipes.get(cell, []):
            where = _where(result.get("location"))
            entry.refs.extend(result.get("source_refs") or [])
            status, evidence_class = result.get("status"), result.get("evidence_class")
            for ref in result.get("source_refs") or []:
                self._dataset_freshness(entry, ref.get("dataset_id") if isinstance(ref, dict) else None)
            if status == "mismatch":
                entry.problem(CONTRADICTED, _reason("recipe_mismatch", f"来源复算与引用值不一致{f'（{where}）' if where else ''}"))
            elif status != "pass":
                entry.problem(MISSING, _reason("recipe_unreadable", f"来源区域读不出{f'（{where}）' if where else ''}"))
            elif evidence_class == "estimate":
                entry.set_base("estimate", _reason("recipe_estimate", "来源复算：按系数推算的估算"))
            elif evidence_class == "source_value":
                entry.set_base("fact_source_reported", _reason("recipe_source_value", f"来源复算：与原表{where or '单元格'}一致"))
            elif evidence_class == "source_calculation":
                entry.set_base("derived_calculation", _reason("recipe_source_calculation", f"来源复算：按原表{where or '单元格'}计算一致"))
            elif evidence_class == "coefficient_unbound":
                coefficient_only = True
        return coefficient_only

    def _row_estimate(self, entry: _Entry, cell: tuple) -> None:
        sources = self.row_estimates.get((cell[0], cell[1])) or []
        if any(isinstance(source, dict) and source.get("source") == "declared" for source in sources):
            entry.set_base("estimate", _reason("row_declared_estimate", "分析要求把这一行声明为估算"))
            return
        fields = [str(source.get("field")) for source in sources if isinstance(source, dict) and source.get("field")]
        if fields:
            entry.set_base("assumption_inferred", _reason(
                "row_reads_as_estimate", f"结果行自己的字段或文字表明是估算（{'、'.join(dict.fromkeys(fields))}），没有要求声明"))

    def _engine(self, entry: _Entry, run: dict | None, fact: dict | None, *, coefficient_only: bool = False) -> None:
        if not run or run.get("execution_status") != "succeeded":
            entry.set_base("unknown", _reason("run_unavailable", "引用的计算不在本稿内或没有成功"))
            return
        if not fact:
            # The same words validate_explanation's unknown_fact uses for a cell with no fact.
            entry.set_base("unknown", _reason("no_fact", "引用位置没有可核验的数值事实"))
        bindings = run.get("bindings") or {}
        hashes = run.get("source_hashes") or {}
        entry.refs.extend({"dataset_id": dataset_id, "source_hash": hashes.get(alias)}
                          for alias, dataset_id in sorted(bindings.items()))
        engine = run.get("engine")
        if engine == "finance":
            entry.set_base("fact_provider_standardized", _reason("engine_finance", "财务引擎按科目映射汇总的结果"))
        elif engine == "structured_aggregate" and ((run.get("result") or {}).get("provenance") or {}).get("status") == "verified":
            entry.set_base("fact_provider_standardized", _reason("engine_aggregate", "服务端按快照分组汇总，来源行已核对"))
        elif coefficient_only:
            entry.set_base("unknown", _reason("recipe_coefficient", "来源复算用了自定义系数，只证明了乘法关系，没有追到原表"))
        elif engine in {"python", "shell"}:
            # A script's output is not re-executed or traced on the server; only a passing source recipe
            # (handled above) says where its number comes from.
            entry.set_base("unknown", _reason("run_script", "只有脚本输出，没有通过的来源复算，没有追到原表"))
        elif any((self.datasets.get(dataset_id) or {}).get("standardized") for dataset_id in bindings.values()):
            entry.set_base("derived_calculation", _reason("run_on_refresh", "由一次计算从系统刷新的标准化资料得出，引用值与结果一致"))
        else:
            entry.set_base("derived_calculation", _reason("run_calculation", "由一次计算得出，引用值与结果一致"))

    def _run_freshness(self, entry: _Entry, run: dict | None) -> None:
        if not run:
            return
        if run.get("id") in self.older_runs:
            entry.problem(STALE, _reason("older_run", "引用的是旧一版计算结果，同一计算之后又算过"))
        as_of = set()
        for dataset_id in (run.get("bindings") or {}).values():
            info = self._dataset_freshness(entry, dataset_id)
            if info and info.get("as_of"):
                as_of.add(info["as_of"])
        if len(as_of) == 1:
            entry.as_of = next(iter(as_of))

    def _dataset_freshness(self, entry: _Entry, dataset_id: Any) -> dict | None:
        info = self.datasets.get(dataset_id) if isinstance(dataset_id, str) else None
        if info and (info.get("freshness") or {}).get("state") == "source_stale":
            why = "；".join(reason["text"] for reason in info["freshness"].get("reasons") or [])
            entry.problem(STALE, _reason("dataset_stale", f"读的资料「{info.get('name') or '资料'}」已过期：{why}"))
        return info

    # Claims, then everything that is not a cell.

    def claim(self, index: int, claim: Any) -> dict[str, Any]:
        if not isinstance(claim, dict):
            entry = _Entry({"kind": "claim", "claim_index": index})
            entry.set_base("unknown", _reason("claim_no_basis", "引用没有写明依据类型"))
            return entry.output()
        basis = claim.get("basis")
        key: dict[str, Any] = {"kind": "claim", "claim_index": index, "basis": basis if isinstance(basis, str) else None}
        fact = self.facts.get(claim.get("fact_id")) if isinstance(claim.get("fact_id"), str) else None
        # As validate_explanation binds them: a known fact_id, else a calculation claim's own cell.
        cell = (fact["run_id"], fact["row"], fact["column"]) if fact else _cell(claim) if basis == "calculation" else None
        if cell:
            shared = self.cell(cell)
            entry = _Entry({**key, **{k: v for k, v in shared.key.items() if k != "kind"}})
            if basis in OWN_BASIS:
                # The writer said this number is assumed or judged: that is what it is, whatever the cell is.
                label, code, words = OWN_BASIS[basis]
                entry.set_base(label, _reason(code, words))
            else:
                entry.base, entry.base_reasons = shared.base, list(shared.base_reasons)
            entry.problems = {code: list(reasons) for code, reasons in shared.problems.items()}
            entry.refs, entry.as_of, entry.period = list(shared.refs), shared.as_of, shared.period
            if fact and any(claim.get(name) != fact.get(name) for name in ("run_id", "row", "column", "value")):
                entry.problem(CONTRADICTED, _reason("fact_claim_mismatch", "引用的数和事实记录不一致"))
            if not fact:
                # This claim's own value against the run's cell, as validate_explanation compares it.
                found, actual = _run_value(self.runs.get(cell[0]), cell[1], cell[2])
                if found and not _same_number(actual, claim.get("value")):
                    entry.problem(CONTRADICTED, _reason("claim_value_mismatch", "引用的数与计算结果不一致"))
            return entry.output()
        entry = _Entry(key)
        dataset_id = claim.get("dataset_id") if isinstance(claim.get("dataset_id"), str) else None
        if dataset_id:
            entry.key["dataset_id"] = dataset_id
            if isinstance(claim.get("paragraph"), int) and not isinstance(claim.get("paragraph"), bool):
                entry.key["paragraph"] = claim["paragraph"]
            info = self._dataset_freshness(entry, dataset_id) or {}
            entry.refs.append({"dataset_id": dataset_id, "source_hash": info.get("source_hash") or claim.get("source_hash"),
                               "paragraph": entry.key.get("paragraph")})
            entry.as_of, entry.period = info.get("as_of"), info.get("period") or None
        if basis == "calculation":
            entry.set_base("unknown", _reason("no_fact", "引用位置没有可核验的数值事实"))
        elif basis in {"source_fact", "external_reference"} and dataset_id:
            if (self.datasets.get(dataset_id) or {}).get("standardized"):
                entry.set_base("fact_provider_standardized", _reason("claim_refresh", "引用的是系统刷新的标准化资料"))
            else:
                paragraph = entry.key.get("paragraph")
                entry.set_base("fact_source_reported", _reason(
                    "claim_source", f"引用资料原文{f'第 {paragraph} 段' if paragraph else ''}"))
        elif basis == "source_fact":
            entry.set_base("unknown", _reason("claim_no_source", "说是来源事实，但没有指明出自哪份资料"))
        elif basis == "external_reference":
            entry.set_base("unknown", _reason("claim_external", "外部资料没有存进任务，无法核对原文"))
        elif basis in OWN_BASIS:
            label, code, words = OWN_BASIS[basis]
            entry.set_base(label, _reason(code, words))
        else:
            entry.set_base("unknown", _reason("claim_no_basis", "引用没有写明依据类型"))
        return entry.output()

    def missing_fact(self, fact_id: str) -> dict[str, Any]:
        entry = _Entry({"kind": "fact", "fact_id": fact_id})
        entry.problem(MISSING, _reason("fact_missing", "引用的事实不在当前计算结果里"))
        return entry.output()

    def requirement(self, item: dict, failures: set[str]) -> dict[str, Any] | None:
        label = item.get("label") or item.get("metric") or item.get("id")
        entry = _Entry({"kind": "requirement", "requirement_item_id": item.get("id")})
        if item.get("status") not in {"answered", "estimated"}:
            entry.problem(MISSING, _reason("requirement_unanswered", f"「{label}」还没有回答"))
        if item.get("provenance_status") == "failed" or item.get("id") in failures:
            entry.problem(MISSING, _reason("requirement_source_failed", f"「{label}」下钻读取来源失败"))
        elif item.get("provenance_status") == "pending":
            entry.problem(MISSING, _reason("requirement_source_pending", f"「{label}」的指定来源核查没有完成"))
        if not any(entry.problems.values()):
            return None
        return entry.output()

    def assertion(self, result: dict) -> dict[str, Any]:
        entry = _Entry({"kind": "assertion", "rule_id": result.get("rule_id")})
        source = result.get("assertion_source") if isinstance(result.get("assertion_source"), dict) else None
        if source:
            reference = source.get("reference") if isinstance(source.get("reference"), dict) else {}
            entry.refs.append(reference)
            entry.set_base("management_claim", _reason("assertion_source", "资料原文里的说法，已按数字核对"))
            self._dataset_freshness(entry, reference.get("dataset_id"))
        else:
            entry.set_base("analyst_interpretation", _reason("assertion_written", "文稿自己的说法，没有原文出处"))
        label = result.get("label") or result.get("rule_id") or "一致性说法"
        if result.get("status") == "mismatch":
            entry.problem(CONTRADICTED, _reason("consistency_mismatch", f"说法与数字不符：{label}"))
        elif result.get("status") != "pass":
            entry.problem(MISSING, _reason("consistency_unreadable", f"核对「{label}」要用的数字读不出"))
        return entry.output()

    def revision(self, issue: dict) -> dict[str, Any]:
        entry = _Entry({"kind": "revision", "run_id": issue.get("new_run_id"), "column": issue.get("column"),
                        "business_key": issue.get("business_key")})
        entry.set_base("derived_calculation", _reason("revision_run", "修订后引用的计算结果"))
        entry.problem(CONTRADICTED, _reason(
            "revision_regression", f"同一来源和口径的数在修订后变了：{issue.get('old_value')} → {issue.get('new_value')}"))
        return entry.output()

    def number(self, issue: dict) -> dict[str, Any]:
        entry = _Entry({"kind": "number", "text": issue.get("text"), "position": issue.get("position")})
        entry.set_base("unknown", _reason("uncited_number", f"正文数字「{issue.get('text')}」没有绑定到事实或引用"))
        return entry.output()


def label_evidence(
    *,
    claims: list[Any],
    fact_ids: list[Any],
    facts: list[dict],
    evidence_groups: list[dict],
    issues: list[dict],
    requirements: dict,
    recipe_results: list[dict],
    consistency_results: list[dict],
    runs: dict[str, dict],
    older_runs: set[str] | frozenset[str],
    row_estimates: dict[tuple[str, int], list[dict]],
    datasets: dict[str, dict],
    source_read_failures: Any = (),
) -> list[dict[str, Any]]:
    """The labels in a fixed order: claims by index, facts by fact_id, located cells, then requirement items,
    consistency assertions, revision regressions and uncited numbers in the order their records hold them."""
    labeler = _Labeler(facts=facts, evidence_groups=evidence_groups, issues=issues, requirements=requirements,
                       recipe_results=recipe_results, consistency_results=consistency_results, runs=runs,
                       older_runs=older_runs, row_estimates=row_estimates, datasets=datasets)
    labels = [labeler.claim(index, claim) for index, claim in enumerate(claims)]

    referenced: dict[str, None] = {}
    unknown_ids: dict[str, None] = {}
    for fact_id in fact_ids:
        if isinstance(fact_id, str) and fact_id in labeler.facts:
            referenced.setdefault(fact_id)
        elif isinstance(fact_id, str):
            unknown_ids.setdefault(fact_id)
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        fact = labeler.facts.get(claim.get("fact_id")) if isinstance(claim.get("fact_id"), str) else None
        if fact is None and claim.get("basis") == "calculation":
            fact = labeler.by_cell.get(_cell(claim))
        if fact:
            referenced.setdefault(fact["id"])
    required = {issue.get("fact_id") for issue in labeler.issues if issue.get("code") == "missing_required_fact"}
    located = {labeler.by_cell[cell]["id"] for cell in labeler.locations if cell in labeler.by_cell}
    for fact_id in sorted({*referenced, *located, *(fact_id for fact_id in required if fact_id in labeler.facts)}):
        fact = labeler.facts[fact_id]
        entry = labeler.cell((fact["run_id"], fact["row"], fact["column"]))
        if fact_id in required and fact_id not in referenced:
            entry.problem(MISSING, _reason("required_fact_uncited", "重要结果事实还没在文稿里引用"))
        labels.append(entry.output())
    labels.extend(labeler.missing_fact(fact_id) for fact_id in sorted(unknown_ids))
    for cell in sorted(labeler.locations, key=lambda cell: (cell[0], cell[1], cell[2])):
        if cell not in labeler.by_cell:
            labels.append(labeler.cell(cell).output())

    from foundry.finance_requirements import _source_read_failures

    # Read as the requirements check reads them: a list of objects naming an item; anything else is nothing.
    failures = set(_source_read_failures(source_read_failures))
    for item in (requirements or {}).get("items") or []:
        if isinstance(item, dict):
            entry = labeler.requirement(item, failures)
            if entry:
                labels.append(entry)
    labels.extend(labeler.assertion(result) for result in consistency_results if isinstance(result, dict))
    labels.extend(labeler.revision(issue) for issue in labeler.issues if issue.get("code") == "revision_numeric_regression")
    labels.extend(labeler.number(issue) for issue in labeler.issues if issue.get("code") == "uncited_number")
    return labels


# --- posture -----------------------------------------------------------------------------------------------


def _identity(entry: dict[str, Any], position: int) -> tuple:
    """A claim and the fact or cell it cites are one item, unless the claim says its number is assumed or
    judged: then it is an item of its own, so the assumption is never folded into the fact."""
    key = entry.get("key") or {}
    if key.get("kind") == "claim" and key.get("basis") in OWN_BASIS:
        return ("entry", position)
    if key.get("fact_id"):
        return ("fact", key["fact_id"])
    if key.get("kind") in {"claim", "location"} and key.get("run_id") is not None and key.get("column") is not None:
        return ("cell", key["run_id"], key.get("row"), key["column"])
    return ("entry", position)


def label_counts(labels: list[dict[str, Any]]) -> dict[str, int]:
    """How many items carry each shown label, worst label per item, in the label order."""
    items: dict[tuple, str] = {}
    for position, entry in enumerate(labels):
        identity = _identity(entry, position)
        label = entry.get("label")
        held = items.get(identity)
        if held is None or (label in PROBLEMS and (held not in PROBLEMS or PROBLEMS.index(label) < PROBLEMS.index(held))):
            items[identity] = label
    return {code: count for code in LABELS if (count := sum(1 for label in items.values() if label == code))}


def _check_gaps(checks: dict[str, Any]) -> list[dict[str, str]]:
    coverage = ((checks or {}).get("coverage") or {}).get("status")
    provenance = ((checks or {}).get("provenance") or {}).get("status")
    if coverage in (None, "not_assessed") and provenance in (None, "not_assessed"):
        return [_reason("requirements_not_set", "还没有设置分析要求，问题覆盖和来源追溯没有核对")]
    gaps = []
    if coverage not in PASSED_CHECKS:
        gaps.append(_reason("coverage_not_passed", "问题覆盖还有缺口"))
    if provenance not in PASSED_CHECKS:
        gaps.append(_reason("provenance_not_passed", "来源追溯还有缺口"))
    return gaps


def evidence_posture(labels: list[dict[str, Any]], checks: dict[str, Any] | None) -> dict[str, Any]:
    counts = label_counts(labels)
    total = sum(counts.values())

    def lines(codes) -> list[dict[str, str]]:
        return [_reason(code, f"{LABELS[code]} {counts[code]} 项") for code in codes if counts.get(code)]

    assumed = sum(counts.get(code, 0) for code in ASSUMED)
    if counts.get(CONTRADICTED) or counts.get(MISSING):
        level, drivers = "unsupported", lines((CONTRADICTED, MISSING))
    elif total and assumed * 2 >= total:
        level = "assumption_led"
        drivers = [_reason("assumption_share", f"假设和估算占 {assumed}/{total} 项"), *lines(ASSUMED)]
    else:
        gaps = [] if total else [_reason("no_evidence", "文稿没有引用任何数字或依据")]
        gaps += lines((STALE, "unknown")) + _check_gaps(checks or {})
        if gaps:
            level, drivers = "preliminary", gaps
        elif any(counts.get(code) for code in JUDGED):
            level, drivers = "research_grade", lines(JUDGED)
        else:
            level = "decision_grade"
            drivers = [_reason("source_backed", "引用的数字都出自来源原文、标准化数据或系统记录的计算，问题覆盖和来源追溯已核对")]
    return {"level": level, "text": POSTURES[level], "counts": counts, "drivers": drivers, "rules_version": RULES_VERSION}


# --- the draft entry point -----------------------------------------------------------------------------------


EVIDENCE_FIELDS = ("evidence_labels", "evidence_posture", "dataset_freshness")


def draft_evidence(
    analysis,
    check: dict[str, Any],
    *,
    claims: list[Any],
    fact_ids: list[Any],
    runs: dict[str, dict],
    evidence_report: dict[str, Any],
    consistency_report: dict[str, Any],
    source_read_failures: Any = (),
    allowed: set[str] | None = None,
) -> dict[str, Any]:
    """Labels, posture and cited-dataset freshness for one assembled explanation check.

    The draft save path and the preview path both call this with the same records, so a preview and the
    draft it saves agree.
    """
    return draft_evidence_basis(
        analysis, check, claims=claims, fact_ids=fact_ids, runs=runs, evidence_report=evidence_report,
        consistency_report=consistency_report, source_read_failures=source_read_failures, allowed=allowed,
        basis=False,
    )[0]


def draft_evidence_basis(
    analysis,
    check: dict[str, Any],
    *,
    claims: list[Any],
    fact_ids: list[Any],
    runs: dict[str, dict],
    evidence_report: dict[str, Any],
    consistency_report: dict[str, Any],
    source_read_failures: Any = (),
    allowed: set[str] | None = None,
    basis: bool = True,
    cache: dict | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """draft_evidence's fields, and the basis a draft keeps so a reader with another snapshot ceiling can read
    them (evidence_in_view); without ``basis`` (a preview) the basis is empty and no file outside ``allowed``
    is read. ``cache`` as for AnalysisStore.run_in_view.

    This is the only function here that reads the store: the run history (for newer runs of the same
    calculation), the requirements version the check was made against (its scope is the task period), dataset
    freshness and row declarations.
    Everything it decides is decided by the pure functions above, from what the basis holds and the draft's
    own records.
    """
    from foundry.finance_close_status import _run_key
    from foundry.finance_readiness import dataset_currency, dataset_replacements
    from foundry.finance_requirements import latest_requirements

    # The version the check was made against (check_requirements files it), not one saved since: a reader that reads
    # a cited run otherwise declares its rows again by that version (AnalysisStore._row_estimates_in_view).
    requirements = check.get("requirements")
    if isinstance(requirements, dict) and "requirements_id" in requirements:
        checked_id = requirements["requirements_id"]
        latest = analysis._get("requirements", checked_id) if isinstance(checked_id, str) else None
    else:
        latest = latest_requirements(analysis)
    task_period = ((latest or {}).get("scope") or {}).get("period")
    newest: dict[str, tuple] = {}
    every: dict[str, list[tuple]] = {}

    def order(run: dict) -> tuple:
        return run.get("seq", 0), str(run.get("created_at") or ""), str(run.get("id") or "")

    def calculation(run: dict) -> str:
        # A public metric or variance call files a new revision each time, so for the finance engine the
        # same operation, spec and context is the same calculation whichever revision carried it.
        if run.get("engine") == "finance" and run.get("code_hash"):
            return f"finance:{run['code_hash']}"
        return _run_key(run)

    # Only the order, id and files of each run are kept: a task's runs together can be large.
    root = analysis._inside(analysis.root / "runs")
    for path in sorted(root.glob("*.json")) if root.exists() else []:
        run = analysis._read(path)
        if run.get("execution_status") != "succeeded":
            continue
        key = calculation(run)
        every.setdefault(key, []).append((order(run), tuple(sorted({str(value) for value in (run.get("bindings") or {}).values()}))))
        if (allowed is None or set((run.get("bindings") or {}).values()) <= allowed) and (
                key not in newest or order(run) > newest[key][0]):
            newest[key] = (order(run), run.get("id"))
    older = {run_id for run_id, run in runs.items()
             if run.get("execution_status") == "succeeded" and newest.get(calculation(run), (None, run_id))[1] != run_id}
    # For each cited run, the files each newer run of its calculation reads, whoever may read them.
    newer_runs = {
        run_id: sorted({files for at, files in every.get(calculation(run), []) if at > order(run)})
        for run_id, run in sorted(runs.items()) if run.get("execution_status") == "succeeded"
    }

    recipe_results = [result for result in (evidence_report or {}).get("results") or [] if isinstance(result, dict)]
    dataset_ids = {dataset_id for run in runs.values() for dataset_id in (run.get("bindings") or {}).values()}
    dataset_ids |= {claim["dataset_id"] for claim in claims if isinstance(claim, dict) and isinstance(claim.get("dataset_id"), str)}
    dataset_ids |= {ref["dataset_id"] for result in recipe_results for ref in result.get("source_refs") or []
                    if isinstance(ref, dict) and isinstance(ref.get("dataset_id"), str)}
    consistency_results = [result for result in (consistency_report or {}).get("results") or [] if isinstance(result, dict)]
    for result in consistency_results:
        source = result.get("assertion_source")
        reference = source.get("reference") if isinstance(source, dict) else None
        if isinstance(reference, dict) and isinstance(reference.get("dataset_id"), str):
            dataset_ids.add(reference["dataset_id"])
    periods: dict[str, str] = {}
    datasets = dataset_currency(analysis, sorted(dataset_ids), task_period=task_period, allowed=allowed, periods=periods)

    row_estimates = declared_row_estimates(analysis, runs, latest, allowed, cache=cache)

    fields = _evidence_fields(check, claims=claims, fact_ids=fact_ids, runs=runs, recipe_results=recipe_results,
                              consistency_results=consistency_results, older=older, row_estimates=row_estimates,
                              datasets=datasets, source_read_failures=source_read_failures)
    if not basis:
        return fields, {}
    # Whoever may read them: the basis is for every reader. An unreadable file is unknown whatever replaced it.
    replaced_by = dataset_replacements(analysis, [dataset_id for dataset_id, info in datasets.items()
                                                  if not _has_reason(info, "dataset_unreadable")], periods=periods)
    kept = {
        "schema_version": 1,
        "task_period": task_period.strip() if isinstance(task_period, str) else "",
        "row_estimates": [[run_id, row, sources] for (run_id, row), sources in sorted(row_estimates.items())],
        "datasets": datasets,
        # Every newer file and run there was, whoever may read them, and which of them this save counted.
        "replaced_by": replaced_by,
        "superseded": sorted(dataset_id for dataset_id in replaced_by if _has_reason(datasets[dataset_id], "superseded")),
        "newer_runs": newer_runs,
        "older_runs": sorted(older),
    }
    return fields, kept


def declared_row_estimates(analysis, runs: dict[str, dict], latest: dict | None, allowed: set[str] | None, *,
                           cache: dict | None = None) -> dict[tuple[str, int], list[dict]]:
    """The estimate sources of each cited run row that reads as an estimate: its row declarations as a reader whose
    snapshot ceiling is ``allowed`` reads the run (AnalysisStore.run_in_view), with ``latest``'s estimates added.
    ``cache`` as for run_in_view."""
    from foundry.result_semantics import declared_run

    cache = {} if cache is None else cache
    row_estimates: dict[tuple[str, int], list[dict]] = {}
    for run_id, run in runs.items():
        # Only a declaration is read here: a run without one reads none whoever reads it.
        if isinstance(run.get("row_declarations"), dict):
            run = analysis.run_in_view(run, allowed, cache=cache)
        declaration = declared_run(analysis, run, latest).get("row_declarations")
        for row in (declaration or {}).get("rows") or [] if isinstance(declaration, dict) else []:
            if isinstance(row, dict) and row.get("estimate") and isinstance(row.get("row"), int):
                row_estimates[(run_id, row["row"])] = list(row.get("estimate_sources") or [])
    return row_estimates


def _has_reason(info: dict[str, Any], code: str) -> bool:
    return any(isinstance(reason, dict) and reason.get("code") == code
               for reason in (info.get("freshness") or {}).get("reasons") or [])


def _evidence_fields(check: dict[str, Any], *, claims, fact_ids, runs, recipe_results, consistency_results, older,
                     row_estimates, datasets, source_read_failures) -> dict[str, Any]:
    labels = label_evidence(
        claims=list(claims or []), fact_ids=list(fact_ids or []), facts=list(check.get("facts") or []),
        evidence_groups=list(check.get("evidence_groups") or []), issues=list(check.get("issues") or []),
        requirements=check.get("requirements") or {}, recipe_results=recipe_results,
        consistency_results=consistency_results,
        runs=runs, older_runs=older, row_estimates=row_estimates, datasets=datasets,
        source_read_failures=source_read_failures,
    )
    return {
        "evidence_labels": labels,
        "evidence_posture": evidence_posture(labels, check.get("checks") or {}),
        "dataset_freshness": {
            dataset_id: {
                **{key: info.get(key) for key in ("name", "as_of", "as_of_source", "period", "period_kind", "freshness")},
                "state": (info.get("freshness") or {}).get("state") or "unknown",
            }
            for dataset_id, info in datasets.items()
        },
    }


def evidence_in_view(draft: dict[str, Any], check: dict[str, Any], allowed: set[str] | None, *,
                     runs: Callable[[], dict[str, dict]], force: bool = False,
                     row_estimates: list | None = None,
                     refreshed: Callable[[], dict[str, set[str]]] | None = None) -> dict[str, Any] | None:
    """A stored draft's labels, posture and freshness as a reader whose snapshot ceiling is ``allowed`` (None:
    every file) reads them, or None when they stand as saved.

    A cited file is stale when a newer file replaces it, and a cited run older when a newer run of the same
    calculation succeeded; whoever saved the draft counted the newer files and runs they could read. A reader
    counts the ones it may read: the draft reads as that reader would have saved it at the time, so a newer
    file outside a session decides nothing it reads, and one the saver could not read but the reader can
    still counts. Whether a newer file replaces an older one, or a newer run reruns an older one, depends on
    the two alone (save a refresh filed against a third file, below), which is why counting by ceiling is enough.
    Everything else stands as saved (the task period, estimates, the check itself), save the row estimates of a
    cited run that reads pinned to another requirements version (AnalysisStore._row_estimates_in_view):
    ``row_estimates``, when given, replace the basis's and the fields are read again. ``draft`` must carry
    ``evidence_basis``; ``runs`` loads the draft's runs, only when the fields are read again. ``force`` reads them
    again even then: the check itself is not the one saved (a revision read without the parent it may not read).
    A refresh the reader may read can have replaced a cited file through a batch it may not read (P, then H
    outside the reader, then S filed against H): ``refreshed``, given for a session, loads the refreshes filed
    before the draft as the reader reads them (finance_controls.refreshed_snapshots), so S replaces P for it as it
    would had H never been published.
    """
    from foundry.finance_readiness import currency_freshness

    def readable(files) -> bool:
        return allowed is None or set(files) <= allowed

    basis = draft["evidence_basis"]
    superseded = {dataset_id for dataset_id, newer in (basis.get("replaced_by") or {}).items()
                  if any(readable([file]) for file in newer)}
    # Read along the batches only where every newer file is one the reader may not read: S, filed against such an H,
    # replaces P as the reader would have saved it.
    through = [dataset_id for dataset_id, newer in (basis.get("replaced_by") or {}).items()
               if newer and dataset_id not in superseded] if refreshed is not None and allowed is not None else []
    if through:
        replaced = refreshed()
        superseded |= {dataset_id for dataset_id in through
                       if any(readable([file]) for file in replaced.get(dataset_id, ()))}
    older = {run_id for run_id, readings in (basis.get("newer_runs") or {}).items()
             if any(readable(files) for files in readings)}
    saved = set(basis.get("superseded") or [])
    if (not force and row_estimates is None and superseded == saved
            and older == set(basis.get("older_runs") or [])):
        return None
    datasets = {
        dataset_id: ({**info, "freshness": currency_freshness(info, task_period=basis.get("task_period") or "",
                                                              superseded=dataset_id in superseded)}
                     if (dataset_id in superseded) != (dataset_id in saved) else info)
        for dataset_id, info in (basis.get("datasets") or {}).items()
    }
    return _evidence_fields(
        check, claims=draft.get("claims") or [], fact_ids=draft.get("fact_ids") or [], runs=runs(),
        recipe_results=[result for result in (draft.get("evidence_report") or {}).get("results") or []
                        if isinstance(result, dict)],
        consistency_results=[result for result in (draft.get("consistency_report") or {}).get("results") or []
                             if isinstance(result, dict)],
        older=older,
        row_estimates={(run_id, row): list(sources) for run_id, row, sources in
                       (basis.get("row_estimates") or [] if row_estimates is None else row_estimates)},
        datasets=datasets, source_read_failures=draft.get("source_read_failures") or [],
    )
