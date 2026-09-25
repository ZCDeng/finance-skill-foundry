"""Bounded, idempotent completion receipts for editable financial explanations."""
from __future__ import annotations

from foundry.analysis import _hash, _new
from foundry.locking import exclusive

MAX_REPAIRS = 2
# 6: review round 3 inverted the amount gate (every item but a known non-amount is gated).
# 7: review round 4 gates quantity/area names that also name an amount (price_volume, revenue_by_area) and
#    counts structured_aggregate output for amounts outside revenue/profit/cost/expense.
COMPLETION_POLICY_VERSION = 7
# Issues that may remain while the draft waits for the manager (estimates, declared gaps, structure).
MANAGER_WAIT_ISSUES = {'requirement_unanswered', 'requirement_estimated', 'requested_source_missing'}
COVERAGE_COMPLETE = {'pass', 'pass_with_accepted_estimates'}
MANAGER_REASON_TEXT = {
    'estimate_requires_acceptance': '估算组合待经理确认是否按估算列示',
    'unavailable_declared': '声明为资料缺失的组合待经理确认',
    'estimate_factor_not_reproducible': '估算系数无法由归档单元格复算，需经理决定口径',
    'structure_pending_confirmation': '工作簿结构待经理确认',
}


def record_completion(analysis, draft, quality):
    from foundry.finance_requirement_support import with_input_gaps

    requirements = quality.get('requirements', {})
    requirements = with_input_gaps(analysis, requirements)
    requirement_id = requirements.get('requirements_id')
    runs = {run_id: analysis.get_run(run_id) for run_id in draft.get('run_ids', [])}
    run_hashes = {run_id: run.get('output_hash') for run_id, run in runs.items()}
    requirement = analysis._get('requirements', requirement_id) if requirement_id else None
    from foundry.finance_requirement_semantics import (
        run_has_equivalent_requirements, verified_requirement_fingerprint,
    )
    semantic_fingerprint = verified_requirement_fingerprint(analysis, requirement)
    candidates = {run_id: run for run_id, run in runs.items()
                  if requirement and (run.get('seq', -1) <= requirement['seq']
                      or run.get('requirements_id') != requirement_id
                      or (semantic_fingerprint and run.get('requirements_semantic_fingerprint') != semantic_fingerprint))}
    reused_runs = [run_id for run_id, run in candidates.items()
                   if run_has_equivalent_requirements(analysis, run, requirement)]
    stale_runs = [run_id for run_id in candidates if run_id not in reused_runs]
    issues = list(quality.get('issues', []))
    remaining = {item['id'] for item in requirements.get('items', []) if item['status'] != 'answered'}
    gaps = {item['id']: item['input_gap'] for item in requirements.get('items', []) if item.get('input_gap')}
    awaiting_input = (
        bool(remaining) and remaining <= gaps.keys()
        and not requirements.get('scope_changed') and not stale_runs
        and quality.get('checks', {}).get('numbers', {}).get('status') == 'pass'
        and all(issue.get('code') in {'requirement_unanswered', 'requested_source_missing'}
                and issue.get('requirement_item_id') in remaining for issue in issues)
    )
    if awaiting_input:
        issues.extend({'code': 'verified_input_gap', 'requirement_item_id': key,
                       'message': gaps[key]['next_action']} for key in sorted(remaining))
    # Only estimates, manager-declared gaps or a structure the manager must confirm are left: the
    # assistant stops instead of spending repairs on something only the manager can decide.
    waiting = {item['id']: item.get('awaiting_manager') or [] for item in requirements.get('items', [])
               if item.get('id') in remaining and item.get('awaiting_manager')}
    awaiting_manager = (
        not awaiting_input and bool(waiting) and remaining <= (waiting.keys() | gaps.keys())
        and not requirements.get('scope_changed') and not stale_runs
        and quality.get('checks', {}).get('numbers', {}).get('status') == 'pass'
        and all(issue.get('code') in MANAGER_WAIT_ISSUES and issue.get('requirement_item_id') in remaining
                for issue in issues)
    )
    manager_reasons = sorted({reason for reasons in waiting.values() for reason in reasons})
    if awaiting_manager:
        issues.extend({'code': 'awaiting_manager', 'requirement_item_id': key, 'reasons': waiting[key],
                       'message': '剩余事项需要经理处理：'
                       + '、'.join(MANAGER_REASON_TEXT.get(reason, reason) for reason in waiting[key])
                       + '。助手不再自动修补，本轮答复如实说明这些待经理处理的事项。'}
                      for key in sorted(waiting))
    if stale_runs:
        issues.append({'code': 'requirements_run_outdated', 'run_ids': sorted(stale_runs),
                       'message': '这些运行未绑定当前要求，且无法证明语义兼容。请按当前要求重新运行受影响的计算，再保存解释；已有草稿仍可编辑。'})
    # A new run or draft must not reset the repair budget for the same question.
    # A deliberate requirements revision starts a new completion scope.
    chain_key = _hash({'requirements_semantic_fingerprint': semantic_fingerprint} if semantic_fingerprint else
                      {'requirements_id': requirement_id} if requirement_id else
                      {'unscoped_run_hashes': sorted(run_hashes.values(), key=str)})
    issue_fingerprint = _hash(issues)
    input_key = _hash({'chain_key': chain_key, 'draft_id': draft['id'],
                       'draft_content_hash': draft['content_hash'], 'quality': quality,
                       'completion_policy_version': COMPLETION_POLICY_VERSION})
    with exclusive(analysis.task.lock_path, timeout=10):
        history = [row for row in analysis._list('completions') if row.get('chain_key') == chain_key]
        same = next((row for row in history if row.get('input_key') == input_key), None)
        if same:
            return same
        repairs = min(len(history), MAX_REPAIRS)
        unassessed = (not requirement_id
                      or not analysis._get('requirements', requirement_id).get('items')
                      or requirements.get('coverage', {}).get('status') in {None, 'not_assessed'})
        complete = (quality['status'] == 'pass' and not unassessed
                    and requirements.get('coverage', {}).get('status') in COVERAGE_COMPLETE
                    and requirements.get('provenance', {}).get('status') in COVERAGE_COMPLETE
                    and not stale_runs)
        stalled = bool(history) and history[-1].get('issue_fingerprint') == issue_fingerprint and not complete
        exhausted = len(history) >= MAX_REPAIRS
        status = ('complete' if complete else 'awaiting_input' if awaiting_input
                  else 'awaiting_manager' if awaiting_manager and not unassessed
                  else 'needs_requirements' if unassessed else 'needs_review' if stalled or exhausted else 'repair_available')
        stop_reason = ('complete' if complete else 'verified_input_gap' if awaiting_input
                       else ('estimate_requires_acceptance' if 'estimate_requires_acceptance' in manager_reasons
                             else 'manager_decision_required') if status == 'awaiting_manager'
                       else 'no_progress' if stalled else 'repair_budget_exhausted' if exhausted else None)
        actions = [{'code': issue.get('code'), 'message': issue.get('message'),
                    **({'requirement_item_id': issue['requirement_item_id']} if issue.get('requirement_item_id') else {}),
                    **({'run_ids': issue['run_ids']} if issue.get('run_ids') else {}),
                    **({'fixups': issue['fixups']} if issue.get('fixups') else {})}
                   for issue in issues]
        if unassessed:
            actions.insert(0, {'code': 'requirements_not_defined', 'message': '请先登记用户问题、分析范围和必答指标，再复核这份文稿。'})
        record = _new(analysis.task, draft_id=draft['id'], draft_content_hash=draft['content_hash'],
                      completion_policy_version=COMPLETION_POLICY_VERSION,
                      requirements_id=requirement_id, requirements_semantic_fingerprint=semantic_fingerprint,
                      reused_run_ids=sorted(reused_runs), run_hashes=run_hashes, chain_key=chain_key,
                      input_key=input_key, issue_fingerprint=issue_fingerprint,
                      status=status, repair_attempts=repairs, max_repairs=MAX_REPAIRS,
                      response_status=('ended_with_limitations' if awaiting_input or status == 'awaiting_manager'
                                       else 'complete' if complete else 'needs_review'),
                      original_requirements_completed=bool(requirements.get('original_requirements_completed')) and complete,
                      repair_allowed=status in {'repair_available','needs_requirements'} and not exhausted and not stalled,
                      stop_reason=stop_reason,
                      **({'manager_reasons': manager_reasons} if status == 'awaiting_manager' else {}),
                      actions=actions, checks=quality.get('checks', {}))
        return analysis._write_locked(analysis._object_path('completions', record['id']), record)
