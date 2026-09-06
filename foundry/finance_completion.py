"""Bounded, idempotent completion receipts for editable financial explanations."""
from __future__ import annotations

from foundry.analysis import _hash, _new
from foundry.locking import exclusive

MAX_REPAIRS = 2
COMPLETION_POLICY_VERSION = 2


def record_completion(analysis, draft, quality):
    requirements = quality.get('requirements', {})
    requirement_id = requirements.get('requirements_id')
    runs = {run_id: analysis.get_run(run_id) for run_id in draft.get('run_ids', [])}
    run_hashes = {run_id: run.get('output_hash') for run_id, run in runs.items()}
    requirement = analysis._get('requirements', requirement_id) if requirement_id else None
    stale_runs = [run_id for run_id, run in runs.items()
                  if requirement and run.get('seq', -1) <= requirement['seq']]
    issues = list(quality.get('issues', []))
    if stale_runs:
        issues.append({'code': 'requirements_run_outdated', 'run_ids': sorted(stale_runs),
                       'message': '这些运行早于本次要求版本。请按当前要求重新运行受影响的计算，再保存解释；已有草稿仍可编辑。'})
    # A new run or draft must not reset the repair budget for the same question.
    # A deliberate requirements revision starts a new completion scope.
    chain_key = _hash({'requirements_id': requirement_id} if requirement_id else
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
                    and requirements.get('coverage', {}).get('status') == 'pass'
                    and requirements.get('provenance', {}).get('status') == 'pass'
                    and not stale_runs)
        stalled = bool(history) and history[-1].get('issue_fingerprint') == issue_fingerprint and not complete
        exhausted = len(history) >= MAX_REPAIRS
        status = 'complete' if complete else 'needs_requirements' if unassessed else 'needs_review' if stalled or exhausted else 'repair_available'
        actions = [{'code': issue.get('code'), 'message': issue.get('message'),
                    **({'requirement_item_id': issue['requirement_item_id']} if issue.get('requirement_item_id') else {}),
                    **({'run_ids': issue['run_ids']} if issue.get('run_ids') else {})}
                   for issue in issues]
        if unassessed:
            actions.insert(0, {'code': 'requirements_not_defined', 'message': '请先登记用户问题、分析范围和必答指标，再复核这份文稿。'})
        record = _new(analysis.task, draft_id=draft['id'], draft_content_hash=draft['content_hash'],
                      completion_policy_version=COMPLETION_POLICY_VERSION,
                      requirements_id=requirement_id, run_hashes=run_hashes, chain_key=chain_key,
                      input_key=input_key, issue_fingerprint=issue_fingerprint,
                      status=status, repair_attempts=repairs, max_repairs=MAX_REPAIRS,
                      repair_allowed=status in {'repair_available','needs_requirements'} and not exhausted and not stalled,
                      stop_reason='complete' if complete else 'no_progress' if stalled else 'repair_budget_exhausted' if exhausted else None,
                      actions=actions, checks=quality.get('checks', {}))
        return analysis._write_locked(analysis._object_path('completions', record['id']), record)
