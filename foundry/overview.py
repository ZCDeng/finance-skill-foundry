"""总览 and 成果库: what every task holds, read in one process.

The desktop used to compose both from one foundry process per task (electron reads.ts), so a store
with twenty tasks started forty. These commands read the same stores the per-task commands read and
decide nothing of their own: a task's month-close line is finance_close_status's, a 收缴率 run's
口径 status is the run's, a draft's review state is the draft's.

    overview         every active task's close status, and what holds it, as one list of to-dos
    library          every version and file the non-trashed tasks produced (成果库), unsorted
    library-detail   one draft's text, the runs and files it rests on, and the task's other versions
    workbook-output-path  where a 写回 Excel copy was filed, by its id, checked against its digest
    dashboard-snapshot-path  where a 看板快照 was filed, by its id, checked against its digest

Read-only. A task that cannot be read is reported on its own row with its error rather than failing
the whole page: one broken task must not hide the others' to-dos.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from foundry.errors import FoundryError

COMMANDS = {"overview", "library", "library-detail", "workbook-output-path", "dashboard-snapshot-path"}

# What a block's blocking items are, in the overview's words; the page groups to-dos by this.
BLOCK_KIND = {
    "scope": "scope",
    "source": "source",
    "structure": "structure",
    "controls": "controls",
    "exceptions": "exceptions",
    "review": "review",
}


def add_parsers(sub) -> None:
    sub.add_parser("overview", help="总览: every active task's month-close status and what is waiting on the manager")
    sub.add_parser("library", help="成果库: every draft, export, chart, 写回 Excel copy, 看板快照 and 收缴率 run, unsorted")
    p = sub.add_parser("library-detail", help="one draft's text, what it rests on, and the task's other versions")
    p.add_argument("--draft", required=True)
    p = sub.add_parser("workbook-output-path", help="where a 写回 Excel copy was filed, by its id")
    p.add_argument("--output", required=True)
    p = sub.add_parser("dashboard-snapshot-path", help="where a 看板快照 was filed, by its id")
    p.add_argument("--snapshot", required=True)


def dispatch(args) -> bool:
    if args.cmd not in COMMANDS:
        return False
    if args.session:
        raise FoundryError(f"{args.cmd} is the desktop's own view and does not take a session")
    from foundry.task import TaskStore

    store = TaskStore(Path(args.var))
    if args.cmd == "overview":
        result: Any = overview(store)
    elif args.cmd == "library":
        result = library(store)
    else:
        if not args.task:
            raise FoundryError(f"{args.cmd} needs an explicit --task")
        task = store.get(args.task)
        if args.cmd == "library-detail":
            result = library_detail(task, args.draft)
        elif args.cmd == "dashboard-snapshot-path":
            from foundry.dashboard_snapshot import snapshot_path

            result = {"path": str(snapshot_path(task, args.snapshot))}
        else:
            result = {"path": str(workbook_output_path(task, args.output))}
    from foundry.analysis_data import json_value

    print(json.dumps(json_value(result), ensure_ascii=False, allow_nan=False))
    return True


def _task_row(task, pack_version) -> dict:
    from foundry.cli import _sample_fields

    return {**task.meta(), "windows": len(task.windows()), **_sample_fields(task, pack_version)}


def _pack_version():
    from foundry.cli import _pack_version as version

    return version()


# --- 总览 ---------------------------------------------------------------------------------------


def overview(store) -> dict:
    """Every active task, real ones first (newest period first), each with its close line and to-dos."""
    pack = _pack_version()
    rows = []
    for task in store.list("active"):
        # A task whose windows or sample marker cannot be read is one error row, not a failed 总览:
        # the row falls back to the metadata `store.list` already read.
        row = {**task.meta(), "windows": 0}
        try:
            row = _task_row(task, pack)
            rows.append({"task": row, **_task_overview(task, row)})
        except FoundryError as exc:
            rows.append({"task": row, "error": str(exc), "todo": []})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            rows.append({"task": row, "error": f"读取失败：{exc}", "todo": []})
    rows.sort(key=_overview_order)
    todo = sum(len(row["todo"]) for row in rows)
    return {"schema_version": 1, "tasks": rows, "todo_count": todo}


def _overview_order(row: dict) -> tuple:
    task = row["task"]
    # Real tasks first, newest period first, then newest created; examples last.
    return (task.get("sample") is not None, _negated(task.get("period") or ""), _negated(task.get("created_at") or ""))


def _negated(text: str) -> tuple:
    return tuple(-ord(char) for char in text)


def _task_overview(task, row: dict) -> dict:
    if row.get("sample") and row.get("sample_ready") is False:
        # The reference task is still being built in the background; its store is half written.
        return {"building": True, "todo": []}
    from foundry.finance_service import FinanceStore
    from foundry.structure_records import MANAGER

    from foundry.analysis import AnalysisStore

    finance = FinanceStore(task, actor=MANAGER)
    analysis = AnalysisStore(task)
    status = finance.finance_close_status({})
    board = finance._dashboard() or {}
    runs = analysis._list("runs")
    revisions = analysis._list("revisions")
    datasets = analysis.published_datasets()
    drafts = analysis._list("drafts")
    return {
        "headline": status["headline"],
        # Each block's rows as the 月结 page lists them (the digest's hint aside): 总览 writes each step's line from them.
        "blocks": [{"key": block["key"], "label": block["label"], "state": block["state"],
                    "items": [{key: value for key, value in item.items() if key != "hint"} for item in block["items"]]}
                   for block in status["blocks"]],
        "conclusion": {key: status["conclusion"][key] for key in ("level", "text")},
        "todo": close_todo(task, status),
        "dashboard": _dashboard_overview(finance),
        "work": _step_work(runs, revisions, board, drafts, datasets),
        "health": _health_overview(finance),
        "tried": _tried(task, board),
        "active_at": _active_at(task, row, (runs, revisions, drafts, datasets, analysis._list("requirements"),
                                            finance._list("dashboards"), finance._list("contexts"))),
    }


def _active_at(task, row: dict, records: tuple) -> str:
    """When the task was last worked on: made or restored, a file added, the scope saved, a version, run, draft or
    board saved, or a conversation opened or moved on. 总览 opens on the task worked on last."""
    stamps = [row.get("created_at"), row.get("restored_at")]
    for listed in records:
        stamps.extend(record.get("created_at") for record in listed)
    for session in task.sessions():
        stamps.extend((session.get("opened_at"), session.get("context_updated_at")))
    return max((stamp for stamp in stamps if isinstance(stamp, str) and stamp), default="")


def _role(run: dict) -> str:
    """The role a run declares, first one set, as businessResults.ts explicitRole reads it."""
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    for value in (run.get("result_role"), run.get("run_role"), run.get("activity_role"), result.get("result_role"), result.get("role")):
        if value is not None:
            return str(value).lower()
    return ""


def _step_work(runs: list[dict], revisions: list[dict], board: dict, drafts: list[dict], datasets: list[dict]) -> dict:
    """What 总览 needs to place 财务分析, 经营分析 and 汇报 as the task's own steps do (steps.ts stepStates): each run
    as much as runPresentationRole and isCollectionHealthRun read of it, the board's cards, and how many drafts. The
    rules stay in steps.ts; this is only what they read, so 总览 and the steps never disagree. Each run also carries the
    question it answered, for the step's line."""
    questions = {revision["id"]: revision.get("question") for revision in revisions}
    digests = []
    for run in runs:
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        digests.append({
            "execution_status": run.get("execution_status"),
            "engine": run.get("engine"),
            "role": _role(run),
            "columns": [str(column.get("name")) for column in result.get("columns") or [] if isinstance(column, dict)],
            "rows": bool(result.get("rows")),
            "outputs": bool(run.get("outputs")) or bool(run.get("output_hash")),
            "scenario_kind": result.get("scenario_kind"),
            "analysis_id": run.get("analysis_id"),
            "label": str(run.get("question") or questions.get(run.get("analysis_id")) or ""),
        })
    cards = [{"state": card.get("state"), "kind": card.get("kind")} for card in board.get("cards", [])]
    return {"runs": digests, "cards": cards, "drafts": len(drafts), "datasets": len(datasets)}


def _health_overview(finance) -> dict | None:
    """The newest 回款健康's 风险雷达, counted by light: 经营分析's line on 总览. The same run 本月三句话's 风险 reads."""
    from foundry.month_brief import _latest_health

    run = _latest_health(finance)
    if run is None:
        return None
    levels: dict[str, int] = {}
    for row in run["result"]["rows"]:
        if isinstance(row, dict) and row.get("metric_key") == "risk_score" and row.get("scenario") == "本期" and row.get("level"):
            levels[str(row["level"])] = levels.get(str(row["level"]), 0) + 1
    return {"run_id": run["id"], "levels": levels}


# What 总览's 还没试过 can point at, as the task's own records show it was used. 点一个数看来源 and 汇报模式 leave no
# record on a task; the desktop keeps those in its preferences (electron/preferences.ts tried).
FEATURES = ("source", "scenario", "goal", "billing", "present", "snapshot", "recompute")


def _tried(task, board: dict) -> list[str]:
    """The features this task's records show were used: a 回款情景 or 倒推 card on the board, a 收费明细 added, the board
    exported to one page, a card run again on newer files or carried from last month."""
    from foundry.billing_detail import BillingDetailStore
    from foundry.dashboard_snapshot import snapshots

    cards = [card for card in board.get("cards", []) if card.get("state") != "explore"]
    used = {
        "scenario": any(card.get("kind") == "scenario" for card in cards),
        "goal": any(card.get("kind") in ("goal", "sensitivity") for card in cards),
        "billing": bool(BillingDetailStore(task).list()),
        "snapshot": bool(snapshots(task)),
        "recompute": any(card.get("recomputed") for card in cards),
    }
    return [feature for feature in FEATURES if used.get(feature)]


def close_todo(task, status: dict) -> list[dict]:
    """One task's 等你处理: what blocks its close, the 收费明细 waiting on the manager, and the sign-off once the rest is
    clear. 本月三句话 (foundry/month_brief.py) reads the same list."""
    todo = []
    for block in status["blocks"]:
        for item in block["items"]:
            if item.get("blocking"):
                todo.append({"kind": BLOCK_KIND.get(block["key"], block["key"]), "text": item["text"],
                             **({"target": item["target"]} if item.get("target") else {})})
    todo.extend(_collection_todo(task))
    if status["headline"]["state"] == "ready_for_review":
        # Everything the system checks is clear: what is left is the manager's own sign-off.
        todo.append({"kind": "signoff", "text": "系统检查已通过，等你复核文稿", "target": "drafts"})
    return todo


def _dashboard_overview(finance) -> dict:
    """The cards on the task's board that were last run again on newer files or carried from last month, with what
    changed (dashboard_recompute). The page counts this month's for its one line; it decides nothing here."""
    board = finance._dashboard() or {}
    rows = []
    for card in board.get("cards", []):
        said = card.get("recomputed")
        if card.get("state") == "explore" or not said:
            continue
        rows.append({"card_id": card["id"], "title": card["title"], "at": said["at"], "changed": bool(said.get("changed")),
                     "change": said.get("change") or "", "state": card["state"], "kind": card["kind"],
                     "carried_from": (said.get("carried_from") or {}).get("title")})
    return {"recomputed": rows}


def _collection_todo(task) -> list[dict]:
    """收费明细 and 收缴率口径 waiting on the manager. Nothing when the task has no detail tables."""
    from foundry.billing_detail import BillingDetailStore

    billing = BillingDetailStore(task)
    details = billing.list()
    if not details:
        return []
    items = [{"kind": "collection", "text": f"收费明细「{meta['name']}」的列还没确认", "target": "billing"}
             for meta in details if not meta.get("confirmation")]
    caliber = billing.caliber()
    if caliber.get("proposed"):
        items.append({"kind": "collection", "text": f"收缴率口径有一版建议（第 {caliber['proposed']['version']} 版）等你确认",
                      "target": "billing"})
    elif not caliber.get("confirmed") and billing.runs():
        items.append({"kind": "collection", "text": "收缴率还在按默认口径试算，口径未确认", "target": "billing"})
    return items


# --- 成果库 -------------------------------------------------------------------------------------


def library(store) -> list[dict]:
    """成果库's rows for every task not in the trash, in the shape the desktop's GalleryRow names.

    Unsorted: the desktop orders them (reads.ts newestFirst), as it did when it composed them.
    """
    from foundry.analysis import AnalysisStore
    from foundry.analysis_deliverables import list_analysis_deliverables

    pack = _pack_version()
    rows: list[dict] = []
    for task in store.list("all"):
        if task.lifecycle_status() == "trashed":
            continue
        row = _task_row(task, pack)
        for entry in task.deliverables():
            rows.append({"type": "deliverable", "key": f"deliverable:{task.id}:{entry['seq']}", "at": entry["at"],
                         "task": row, "row": entry})
        analysis = AnalysisStore(task)
        listed = list_analysis_deliverables(analysis)
        for draft in listed["drafts"]:
            rows.append({"type": "draft", "key": f"draft:{draft['draft_id']}", "at": draft["created_at"], "task": row,
                         "draft": draft})
        for exported in listed["exports"]:
            rows.append({"type": "export", "key": f"export:{exported['export_id']}", "at": exported["created_at"],
                         "task": row, "exported": exported})
        names = {dataset["id"]: dataset.get("name") or "资料" for dataset in analysis.published_datasets()}
        for chart in _charts(task):
            rows.append({"type": "chart", "key": f"chart:{chart['id']}", "at": chart["created_at"], "task": row,
                         "chart": {"id": chart["id"], "label": chart.get("label") or "归档图", "run_id": chart.get("run_id"),
                                   "created_at": chart["created_at"],
                                   "datasets": sorted({names.get(value, "资料") for value in (chart.get("bindings") or {}).values()})}})
        for output in _workbook_outputs(task):
            rows.append({"type": "workbook", "key": f"workbook:{output['id']}", "at": output["created_at"], "task": row,
                         "output": {"id": output["id"], "filename": output.get("filename") or "", "sha256": output["sha256"],
                                    "created_at": output["created_at"], "dataset": names.get(output.get("dataset_id"), "资料"),
                                    "applied": _count(output.get("applied")), "kept": _count(output.get("kept"))}})
        for snapshot in _dashboard_snapshots(task):
            rows.append({"type": "dashboard", "key": f"dashboard:{snapshot['id']}", "at": snapshot["created_at"], "task": row,
                         "snapshot": {"id": snapshot["id"], "format": snapshot["format"], "filename": snapshot.get("filename") or "",
                                      "sha256": snapshot["sha256"], "created_at": snapshot["created_at"], "title": snapshot.get("title") or "经营看板",
                                      "cards": [card["title"] for card in snapshot.get("cards", [])], "beyond": snapshot.get("beyond", []),
                                      "left_out": snapshot.get("left_out") or {"pinned": [], "scenario": []}}})
        for run in _collection_runs(task):
            rows.append({"type": "collection", "key": f"collection:{run['id']}", "at": run["created_at"], "task": row,
                         "run": run})
    return rows


def _count(value: Any) -> int:
    if isinstance(value, (list, tuple, dict)):
        return len(value)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _charts(task) -> list[dict]:
    from foundry.finance_service import FinanceStore

    return FinanceStore(task).chart_deliverable_list({})["charts"]


def _workbook_outputs(task) -> list[dict]:
    from foundry.analysis import AnalysisStore

    analysis = AnalysisStore(task)
    folder = analysis._inside(analysis.root / "finance" / "workbook_outputs")
    if not folder.is_dir():
        return []
    records = [analysis._read(path) for path in sorted(folder.glob("*.json"))]
    return sorted(records, key=lambda record: (record.get("seq", 0), record["created_at"]))


def _dashboard_snapshots(task) -> list[dict]:
    from foundry.dashboard_snapshot import snapshots

    return snapshots(task)


def _collection_runs(task) -> list[dict]:
    from foundry.billing_detail import BillingDetailStore

    return BillingDetailStore(task).runs()


def workbook_output_path(task, output_id: str) -> Path:
    """A 写回 Excel copy's file, from its id alone, refused when its bytes no longer match the record."""
    from foundry.analysis import AnalysisStore

    if not isinstance(output_id, str) or len(output_id) != 32 or any(char not in "0123456789abcdef" for char in output_id):
        raise FoundryError(f"not a workbook output id: {output_id}")
    analysis = AnalysisStore(task)
    record_path = analysis._inside(analysis.root / "finance" / "workbook_outputs" / f"{output_id}.json")
    if not record_path.is_file():
        raise FoundryError(f"no workbook output {output_id} on task {task.id}")
    record = analysis._read(record_path)
    target = analysis._inside(analysis.root / str(record.get("artifact_path") or ""))
    if target.suffix != ".xlsx" or not target.is_file() or target.is_symlink():
        raise FoundryError(f"workbook output {output_id} is missing from task {task.id}")
    if hashlib.sha256(target.read_bytes()).hexdigest() != record.get("sha256"):
        raise FoundryError("workbook output integrity check failed; its bytes differ from its record")
    return target.resolve()


# --- one version, opened in 成果库 --------------------------------------------------------------

CHECKS = (("execution", "执行状态"), ("numeric_citation", "数值引用"), ("source_validation", "来源核验"),
          ("professional_review", "经理复核"))


def library_detail(task, draft_id: str) -> dict:
    """What 成果库's side panel shows for one draft: its text, its checks, what it rests on, its siblings.

    `rests_on` names each run the draft cites and the files that run read, by name and the first twelve
    characters of their digest: the same placing the 月结 page gives a source. `versions` is every draft of
    the task, revision order, for choosing one to compare against.
    """
    from foundry.analysis import AnalysisStore

    analysis = AnalysisStore(task)
    drafts = analysis._list("drafts")
    position = {row["id"]: index + 1 for index, row in enumerate(drafts)}
    draft = next((row for row in drafts if row["id"] == draft_id), None)
    if draft is None:
        raise FoundryError(f"no draft {draft_id} on task {task.id}")
    datasets = {row["id"]: row for row in analysis.published_datasets()}
    runs = {row["id"]: row for row in analysis._list("runs")}
    analyses = {row["id"]: row for row in analysis._list("revisions")}
    rests_on = []
    for run_id in draft.get("run_ids") or []:
        run = runs.get(run_id)
        if run is None:
            rests_on.append({"run_id": run_id, "label": "计算记录已不在", "missing": True, "datasets": []})
            continue
        label = run.get("question") or (analyses.get(run.get("analysis_id")) or {}).get("question") or "计算"
        rests_on.append({
            "run_id": run_id,
            "label": label,
            "seq": run.get("seq"),
            "created_at": run.get("created_at"),
            "execution_status": run.get("execution_status"),
            "datasets": [_dataset_line(datasets.get(value), value) for value in (run.get("bindings") or {}).values()],
        })
    dimensions = ((draft.get("explanation_check") or {}).get("status_dimensions") or {})
    checks = [{"key": key, "label": (dimensions.get(key) or {}).get("label") or label,
               "status": (dimensions.get(key) or {}).get("status") or "not_configured"} for key, label in CHECKS]
    requirements = None
    if draft.get("requirements_id"):
        found = next((row for row in analysis._list("requirements") if row.get("id") == draft["requirements_id"]), None)
        if found is not None:
            requirements = {"seq": found.get("seq"), "scope": found.get("scope") or {}}
    return {
        "schema_version": 1,
        "task_id": task.id,
        "draft": {
            "draft_id": draft["id"],
            "revision": position[draft["id"]],
            "title": draft.get("title", ""),
            "created_at": draft["created_at"],
            "review_status": draft.get("review_status"),
            "publication_status": draft.get("publication_status"),
            "parent_id": draft.get("parent_id"),
            "body": draft.get("body") or "",
        },
        "checks": checks,
        "rests_on": rests_on,
        "requirements": requirements,
        "versions": [{"draft_id": row["id"], "revision": position[row["id"]], "title": row.get("title", ""),
                      "created_at": row["created_at"]} for row in drafts],
    }


def _dataset_line(dataset: dict | None, dataset_id: str) -> dict:
    if dataset is None:
        return {"id": dataset_id, "name": "资料已不在", "hash": ""}
    digest = str(dataset.get("source_hash") or "")
    return {"id": dataset_id, "name": dataset.get("name") or "资料", "hash": digest[:12]}
