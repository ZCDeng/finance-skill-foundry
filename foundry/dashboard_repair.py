"""Propose a portable replacement for an algorithm on a manager's failed carry.

The source task is evidence: replay happens in a disposable copy. A successful
proposal creates a target run, never a card or an acceptance. The manager's
carry operation decides when to use that verified run.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from foundry.analysis import _hash
from foundry.dashboard_recompute import NotRerun, new_month, recipe_of, run_again, same_names, validate_period_move
from foundry.errors import FoundryError
from foundry.task import TaskStore

ENGINES = frozenset({"sql", "structured_aggregate", "python", "shell"})
CALCULATION_FIELDS = frozenset({"sql", "parameters", "parameter_metadata", "aggregate_plan", "code", "period_binding"})
# Context is supplied by the server even when an assistant sends its usual complete spec.
CONTEXT_FIELDS = frozenset({"bindings", "scope"})
SPEC_FIELDS = (
    "question", "engine", "sql", "parameters", "parameter_metadata", "aggregate_plan", "code", "period_binding",
    "relationships", "metrics", "grain", "assumptions", "missing_inputs", "conversion_rules", "result_role",
    "max_rows", "timeout_seconds", "result_file",
)


def _attempt(store):
    attempt = store._carry_attempt()
    if not attempt or not attempt.get("failed"):
        raise FoundryError("先由经理发起看板带入，才可读取或修复其中被拦下的计算")
    return attempt


def _requested(attempt, spec):
    if not isinstance(spec, dict):
        raise FoundryError("dashboard repair spec must be an object")
    pending = list(dict.fromkeys(item["run_id"] for item in attempt["failed"]))
    run_id = spec.get("run_id")
    if run_id is not None and run_id not in pending:
        raise FoundryError("这次计算不在经理带入记录的待修复范围内")
    return [run_id] if run_id else pending


def _context(store, attempt, run_id):
    plan = (attempt.get("plans") or {}).get(run_id) or {}
    bindings = plan.get("bindings")
    if not isinstance(bindings, dict) or not bindings or not all(bindings.values()):
        raise FoundryError("待修复计算缺少当前资料绑定，先补齐同名资料后重新带入")
    # Check this before opening another task: a carry does not widen an assistant's snapshot ceiling.
    store._authorize(bindings)
    for dataset_id in bindings.values():
        store.analysis.read_dataset(dataset_id)
    _current_target(store, attempt, bindings)
    source = type(store)(store.task.store.get(attempt["from_task_id"]), actor="manager")
    board = source._read("dashboards", attempt["source_board_id"])
    if (source._dashboard() or {}).get("id") != board["id"]:
        raise FoundryError("原看板已更新，请经理重新带入后修复")
    if not any(card["run_id"] == run_id and card["id"] in {
        item["card_id"] for item in attempt["failed"] if item["run_id"] == run_id
    } for card in board["cards"]):
        raise FoundryError("待修复计算与原看板记录不一致")
    run = source.analysis.get_run(run_id)
    if run.get("execution_status") != "succeeded":
        raise FoundryError("原计算没有成功结果，无法验证原月等价")
    revision = source.analysis.get_analysis(run["analysis_id"])
    if (revision.get("engine") or "sql") not in ENGINES:
        raise FoundryError("这类计算需重新确认财务口径，不能作为期间参数修复")
    return source, run, revision, deepcopy(bindings)


def _current_target(store, attempt, bindings):
    from foundry.finance_readiness import _task_period

    datasets = [store.analysis.read_dataset(dataset_id) for dataset_id in bindings.values()]
    newest = same_names(store)
    if any(newest(dataset) != dataset["id"] for dataset in datasets):
        raise FoundryError("目标资料已更新，请经理重新带入后修复")
    fallback = _task_period(store.analysis, store.allowed) or store.task.meta().get("period")
    try:
        current = new_month(store, list(bindings.values()), fallback)
    except NotRerun as exc:
        raise FoundryError(str(exc)) from exc
    if not current or current != attempt.get("target_period"):
        raise FoundryError("目标期间已变化，请经理重新带入后修复")


def _spec(revision):
    spec = {key: deepcopy(revision[key]) for key in SPEC_FIELDS if revision.get(key) is not None}
    spec["engine"] = revision.get("engine") or "sql"
    if spec["engine"] == "structured_aggregate":
        for key in ("sql", "parameters", "parameter_metadata", "relationships"):
            spec.pop(key, None)
    elif spec["engine"] == "sql":
        spec.pop("aggregate_plan", None)
    return spec


def read(store, spec):
    """Expose only the recipes that a manager's persisted failed carry authorizes."""
    attempt = _attempt(store)
    repairs = []
    for run_id in _requested(attempt, spec):
        _, _, revision, bindings = _context(store, attempt, run_id)
        failed = [item for item in attempt["failed"] if item["run_id"] == run_id]
        repairs.append({
            "run_id": run_id, "revision_id": revision["id"], "engine": revision.get("engine") or "sql",
            "card_ids": [item["card_id"] for item in failed], "titles": [item["title"] for item in failed],
            "spec": _spec(revision), "bindings": bindings,
        })
    return {"attempt_id": attempt["id"], "from_task_id": attempt["from_task_id"],
            "target_period": attempt["target_period"], "repairs": repairs}


def _execute(store, spec, bindings, scope):
    spec = {**deepcopy(spec), "bindings": bindings, "scope": scope}
    engine = spec.pop("engine")
    if engine in {"python", "shell"}:
        return store.analysis.run_script({**spec, "language": engine}, session_id=store.session_id,
                                         context_revision=store.context_revision, allowed=store.allowed)
    revision = store.analysis.save_analysis({**spec, "engine": engine}, session_id=store.session_id,
                                            context_revision=store.context_revision)
    return store.analysis.run_analysis(revision["id"], session_id=store.session_id,
                                       context_revision=store.context_revision, allowed=store.allowed)


def _result(run):
    result = run.get("result") or {}
    if run.get("execution_status") != "succeeded" or result.get("truncated"):
        raise FoundryError("原月计算未成功或结果被截断，无法验证等价")
    return {"columns": result.get("columns"), "rows": result.get("rows")}


def _shadow(source, root):
    """Copy the source evidence into a new store; never run against the source task itself."""
    tasks = TaskStore(Path(root) / "var")
    destination = tasks.tasks_dir / source.task.id
    # Analysis paths never follow links. Reject them here as well rather than copying linked external material.
    if any(path.is_symlink() for path in source.task.root.rglob("*")):
        raise FoundryError("原任务包含符号链接，不能制作原月回放副本")
    shutil.copytree(source.task.root, destination)
    return type(source)(tasks.get(source.task.id), actor="manager")


def propose(store, spec):
    """Verify an algorithm upgrade on old frozen inputs, then propose its current-month run."""
    attempt = _attempt(store)
    run_ids = _requested(attempt, spec)
    if not spec.get("run_id") or len(run_ids) != 1:
        raise FoundryError("dashboard repair needs one pending run_id")
    run_id = run_ids[0]
    source, original, revision, bindings = _context(store, attempt, run_id)
    replacement = spec.get("spec")
    if not isinstance(replacement, dict):
        raise FoundryError("dashboard repair needs a replacement calculation spec")
    engine = revision.get("engine") or "sql"
    if replacement.get("engine", engine) != engine:
        raise FoundryError("dashboard repair must preserve the original engine")
    original_spec = _spec(revision)
    unexpected = {key for key in set(replacement) - CALCULATION_FIELDS - CONTEXT_FIELDS - {"engine"}
                  if key not in original_spec or replacement[key] != original_spec[key]}
    if unexpected:
        raise FoundryError("dashboard repair may only change calculation fields: " + ", ".join(sorted(unexpected)))
    candidate = {**original_spec, **{key: deepcopy(value) for key, value in replacement.items()
                                     if key in CALCULATION_FIELDS}}
    if not candidate.get("period_binding"):
        raise FoundryError("修复须显式声明 period_binding，把本期绑定到已确认期间")
    expected = _result(original)
    with TemporaryDirectory(prefix="foundry-dashboard-replay-") as temporary:
        shadow = _shadow(source, temporary)
        replay = _execute(shadow, candidate, deepcopy(revision["bindings"]), deepcopy(revision.get("scope") or {}))
        actual = _result(replay)
        if actual != expected:
            raise FoundryError("修复计算的原月回放与历史结果不一致，请保留原公式后仅调整期间绑定")
        try:
            recipe = recipe_of(shadow, replay, elsewhere=True)
            move = validate_period_move(recipe, attempt["target_period"])
            target_run, _ = run_again(store, recipe, bindings, move, elsewhere=True)
        except NotRerun as exc:
            raise FoundryError(str(exc)) from exc
        _result(target_run)
        baseline = {
            "verified": True, "source_run_id": original["id"], "source_analysis_id": revision["id"],
            "source_run_hash": original["_integrity_hash"], "source_result_hash": _hash(expected),
            "replayed_result_hash": _hash(actual), "replayed_code_hash": replay.get("code_hash"),
            "source_input_hashes": deepcopy(original.get("input_hashes") or {}),
            "source_period": (replay.get("resolved_period") or {}).get("period"),
        }
    return store._write("dashboard_repairs", bindings=bindings, attempt_id=attempt["id"],
                        source_board_id=attempt["source_board_id"], source_run_id=run_id,
                        source_task_id=attempt["from_task_id"], resolved_period=attempt["target_period"],
                        run_id=target_run["id"], baseline=baseline)


def verified_repair(store, attempt, source_run_id, bindings):
    """A verified proposal applies only to this carry, source board, month and frozen target inputs."""
    store._authorize(bindings)
    for record in reversed(store._list("dashboard_repairs")):
        if (record.get("attempt_id") != attempt["id"] or record.get("source_board_id") != attempt["source_board_id"]
                or record.get("source_task_id") != attempt["from_task_id"]
                or record.get("source_run_id") != source_run_id or record.get("bindings") != bindings
                or record.get("resolved_period") != attempt["target_period"]):
            continue
        baseline = record.get("baseline") or {}
        if (baseline.get("verified") is not True
                or not baseline.get("source_result_hash")
                or baseline.get("source_result_hash") != baseline.get("replayed_result_hash")):
            continue
        try:
            _current_target(store, attempt, bindings)
        except (FoundryError, NotRerun):
            return None
        run = store.analysis.get_run(record["run_id"])
        if (run.get("bindings") == bindings and run.get("execution_status") == "succeeded"
                and (run.get("resolved_period") or {}).get("period") == attempt["target_period"]):
            return run
    return None
