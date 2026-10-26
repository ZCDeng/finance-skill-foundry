"""Read-only proof for the harness's final text delivery boundary."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re

from foundry.errors import FoundryError
from foundry.finance_completion_operations import _operation_path, _read_operation_path
from foundry.finance_controls import superseded_snapshots
from foundry.finance_requirements import latest_requirements
from foundry.finance_saved_delivery import saved_delivery


# Finite disclosure vocabulary shared with the runtime fallback. These names
# cannot confer native identity or prove any check fact without server evidence.
_PUBLIC_NATIVE_CHECK_IDS = (
    'opening_balance_sheet', 'revenue_receivables_cash', 'ppe_rollforward', 'payables_rollforward',
    'debt_financing', 'equity_rollforward', 'cash_reconciliation', 'cash_flow_indirect_bridge',
    'closing_balance_sheet', 'nonnegative_operating_balances', 'restricted_cash_bounds', 'cash_sufficiency',
)
_PUBLIC_NAMED_CHECK = re.compile(r'\b(?:' + '|'.join(_PUBLIC_NATIVE_CHECK_IDS) + r')\b', re.I)
_PUBLIC_CHECK_ASSERTION = re.compile(r'\b(?:error|alert|pass|passed|passing|fail|failed|failing|'
                                     r'status|severity|difference|differences)\b|'
                                     r'(?<![A-Za-z0-9_])diffs?(?![A-Za-z0-9_])|通过|失败|差异|差额|等级', re.I)


def _public_text_result(text, *, issues=(), bindings=None):
    """Project only affected lines; never invent an opposite financial fact."""
    verified = bindings is not None
    from foundry.finance_claim_semantics import qualification_assertion_lines

    positions = {issue['position'] for issue in issues}
    qualification_positions = qualification_assertion_lines(text)
    neutral = ('模型检查摘要存在与当前运行不符的表述，正在按各项规则和等级继续核对。' if verified
               else '模型检查摘要尚未核实，正在依据当前运行继续核对。')
    lines, offset = [], 0
    for line in text.splitlines(keepends=True):
        affected = any(offset <= pos < offset + len(line) for pos in positions)
        qualification_line = any(offset <= pos < offset + len(line) for pos in qualification_positions)
        # This is a disclosure filter when authority is missing, not a truth
        # predicate. Only the shared source-bound checker proves contradiction.
        if not verified:
            affected = bool(re.search(r'model[_ ]checks?|模型(?:联动)?(?:检查|核查)|'
                                     r'blocks_evidence|\bseverity\b', line, re.I)
                            or _PUBLIC_NAMED_CHECK.search(line) and _PUBLIC_CHECK_ASSERTION.search(line)
                            or qualification_line)
        line_neutral = (('事实资格摘要存在与当前运行元数据不符的表述，正在核对来源绑定与金额资格。' if verified
                         else '事实资格摘要尚未核实，正在依据当前运行继续核对。')
                        if qualification_line else neutral)
        lines.append(line_neutral + ('\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else '')
                     if affected else line)
        offset += len(line)
    delivered = ''.join(lines)
    return {'schema_version': 1, 'verified': verified,
            'status': 'contradicted' if issues else 'unchanged' if verified else 'unverifiable',
            'reason': 'native_check_claim_contradiction' if issues else 'native_checks_current' if verified
                      else 'native_check_proof_not_current',
            'raw_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'delivered_text': delivered, 'delivered_text_sha256': hashlib.sha256(delivered.encode()).hexdigest(),
            'issues': list(issues), 'bindings': bindings}


def verify_public_text(service, spec):
    """Read-only native evidence proof, composed with the runtime's request proof.

    request_key/call_id/nonce are correlations, not server attestations of SDK
    events. The trusted runtime must capture actual tools/result and recheck its
    current request, inbox generation and capture before and after this call.
    verified means current native authority, never whole-prose correctness.
    """
    from foundry.finance_claim_semantics import (CLAIM_SEMANTICS_VERSION, model_check_claim_issues, native_model_checks,
                                                 qualification_assertion_lines, qualification_claim_report)
    from foundry.finance_driver_templates import OUTPUT_SEMANTICS
    from foundry.finance_professional import cell_evidence_eligibility, requirement_rule_identity
    from foundry.finance_requirement_semantics import run_has_equivalent_requirements

    text = spec.get('text', '') if isinstance(spec, dict) else ''
    text = text if isinstance(text, str) else ''
    denied = _public_text_result(text)
    try:
        if (not service.session_id or service.allowed is None or not isinstance(spec, dict)
                or set(spec) != {'request_key', 'nonce', 'text', 'capture'}
                or any(not isinstance(spec[key], str) or not spec[key] for key in ('request_key', 'nonce', 'text'))):
            return denied
        capture = spec['capture']
        fields = {'session_id', 'tool_name', 'call_id', 'task_id', 'run_id', 'requirements_id',
                  'output_hash', 'template_id', 'scenario_id', 'context_revision'}
        if (not isinstance(capture, dict) or set(capture) != fields
                or any(not isinstance(capture[key], str) or not capture[key] for key in fields - {'context_revision'})
                or capture['tool_name'] not in {'finance_scenario_run', 'prepare_explanation'}
                or capture['session_id'] != service.session_id or capture['task_id'] != service.task.id):
            return denied
        session = next(row for row in service.task.sessions() if row['session_id'] == service.session_id)
        if (session.get('role') != 'analysis' or session.get('task_id') != service.task.id
                or set(session.get('snapshot_ids', [])) != service.allowed
                or session.get('context_revision') != service.context_revision):
            return denied
        revision = capture['context_revision']
        if not (revision is None and capture['tool_name'] == 'prepare_explanation') and (
                type(revision) is not int or revision != service.context_revision):
            return denied
        analysis, cache = service.analysis, {}
        run = analysis.verified_run(capture['run_id'], service.allowed, cache)
        service._authorize(run.get('bindings'))
        authority = native_model_checks({run['id']: run})
        result = run.get('result') or {}
        if (not authority or run.get('task_id') != service.task.id or run.get('session_id') != service.session_id
                or run.get('context_revision') != service.context_revision
                or any(run.get(key) != capture[key] for key in ('requirements_id', 'output_hash'))
                or any(result.get(key) != capture[key] for key in ('template_id', 'scenario_id'))
                or result.get('template_version') != 1
                or result.get('model_checks') != (result.get('driver_model') or {}).get('model_checks')):
            return denied
        # Match the native execution gate: an inaccessible new obligation must
        # not make an older visible requirement current again.
        current = latest_requirements(analysis)
        service._authorize_current(current)
        if (not current or current['id'] != capture['requirements_id']
                or not run_has_equivalent_requirements(analysis, run, current, allowed=service.allowed, cache=cache)):
            return denied
        service._authorize(current.get('bindings'))
        if set(run['bindings'].values()) & superseded_snapshots(
                service.task, analysis.published_datasets(), allowed=service.allowed):
            return denied
        identity = requirement_rule_identity(analysis, current, allowed=service.allowed)
        if (not identity or identity.get('professional_status') != 'supported'
                or (run.get('requirements_rule_identity') or {}).get('rule_fingerprint') != identity['rule_fingerprint']):
            return denied
        rows = [row for row in result.get('rows', []) if row.get('metric_key') in OUTPUT_SEMANTICS]
        if (len(rows) != len(OUTPUT_SEMANTICS) or {row['metric_key'] for row in rows} != set(OUTPUT_SEMANTICS)
                or any(not cell_evidence_eligibility(run, row, 'value', analysis=analysis)[
                'counts_as_amount_evidence'] for row in rows)):
            return denied
        issues = model_check_claim_issues(text, runs=[run])
        if qualification_assertion_lines(text):
            from foundry.finance_explanations import _facts_for_run
            catalog = _facts_for_run(run, {"absolute": "0"}, analysis=analysis)
            qualification = qualification_claim_report(text, facts=catalog, runs=[run])
            if qualification['unverifiable_positions']:
                return denied
            issues.extend(qualification['issues'])
        # Re-read mutable authority after the potentially expensive source proof.
        # No write lock or durable SDK request registry is introduced here.
        if (session != next(row for row in service.task.sessions() if row['session_id'] == service.session_id)
                or current != latest_requirements(analysis)
                or identity != requirement_rule_identity(analysis, current, allowed=service.allowed)
                or run != analysis.get_run(run['id'])
                or set(run['bindings'].values()) & superseded_snapshots(
                    service.task, analysis.published_datasets(), allowed=service.allowed)):
            return denied
        for alias, dataset_id in run['bindings'].items():
            dataset = analysis.read_dataset(dataset_id)
            if (dataset['data_hash'] != run['input_hashes'][alias]
                    or dataset['source_hash'] != run['source_hashes'][alias]):
                return denied
        return _public_text_result(text, issues=issues, bindings={
            **{key: capture[key] for key in fields - {'tool_name', 'context_revision'}},
            'request_key': spec['request_key'], 'nonce': spec['nonce'],
            'context_revision': service.context_revision, 'claim_semantics_version': CLAIM_SEMANTICS_VERSION,
            'authority': 'server_current_native_checks',
            'request_authority': 'runtime_must_verify_current_request_and_capture'})
    except (FoundryError, OSError, KeyError, TypeError, ValueError, StopIteration):
        return denied


def verify_delivery(service, spec):
    """Recheck the exact runtime save; never settle, refresh, or create a receipt.

    The runtime supplies the original complete public save result, not a model
    claim about it. The ordinary reader views and saved_delivery remain the
    authority for professional approval, source freshness and completion status.
    Refusals expose no inaccessible object identifiers.
    """
    denied = {'verified': False, 'reason': 'delivery_proof_not_current'}
    try:
        if (not service.session_id or service.allowed is None or not isinstance(spec, dict)
                or set(spec) != {'request_key', 'call_id', 'saved_result'}):
            return denied
        saved = spec['saved_result']
        if not isinstance(saved, dict) or saved.get('task_id') != service.task.id:
            return denied
        supplied_operation = saved['completion_operation']
        operation = _read_operation_path(service.task, _operation_path(service.task, supplied_operation['id']))
        deadline = datetime.fromisoformat(operation['deadline_at'].replace('Z', '+00:00'))
        if deadline.tzinfo is None or datetime.now(timezone.utc) >= deadline:
            return denied
        if (operation['session_id'] != service.session_id or operation['request_key'] != spec['request_key']
                or operation['task_id'] != service.task.id
                or operation['current_revision'] != supplied_operation['current_revision']):
            return denied
        attempt = next(row for row in operation['revisions']
                       if row['revision'] == operation['current_revision'])
        if (attempt['status'] != 'settled' or attempt['call_id'] != spec['call_id']
                or attempt['draft_id'] != saved['id'] or attempt['completion_id'] != saved['completion']['id']
                or attempt['draft_content_hash'] != saved['content_hash']):
            return denied
        if operation['status'] in {'timed_out', 'cancelled', 'failed'}:
            return denied
        analysis, cache = service.analysis, {}
        current = latest_requirements(analysis, service.allowed)
        if current is None or current['id'] != saved.get('requirements_id'):
            return denied
        stored = analysis.get_draft(saved['id'])
        service._authorize_draft(stored)
        if analysis.draft_snapshots(stored) & superseded_snapshots(
                service.task, analysis.published_datasets(), allowed=service.allowed):
            return denied
        # A prior save cannot replace a later visible draft or receipt.
        visible = [draft for draft in analysis._list('drafts')
                   if analysis.draft_readable(draft, service.allowed)]
        if not visible or visible[-1]['id'] != saved['id']:
            return denied
        receipts = [receipt for receipt in analysis._list('completions')
                    if receipt.get('draft_id') == saved['id']]
        if not receipts or receipts[-1]['id'] != saved['completion']['id']:
            return denied
        run_ids = stored.get('run_ids')
        if (not isinstance(run_ids, list) or not run_ids or len(set(run_ids)) != len(run_ids)
                or run_ids != saved.get('run_ids')):
            return denied
        run_hashes = {}
        for run_id in run_ids:
            run = analysis.verified_run(run_id, service.allowed, cache)
            service._authorize(run.get('bindings', {}))
            if run.get('task_id') != service.task.id or run.get('execution_status') != 'succeeded':
                return denied
            run_hashes[run_id] = {'record_hash': run.get('_integrity_hash'),
                                  'output_hash': run.get('output_hash')}
        delivery = saved_delivery(service, saved, cache=cache)
        if (delivery['delivery_contract'].get('completion_status') == 'unverified'
                or delivery['delivery_contract'] != saved.get('delivery_contract')
                or delivery['final_response'] != saved.get('final_response')):
            return denied
        if datetime.now(timezone.utc) >= deadline:
            return denied
        return {'verified': True, 'final_response': delivery['final_response'], 'bindings': {
            'session_id': service.session_id, 'task_id': service.task.id,
            'request_key': spec['request_key'], 'call_id': spec['call_id'],
            'draft_id': stored['id'], 'draft_content_hash': stored['content_hash'],
            'requirements_id': current['id'], 'receipt_id': receipts[-1]['id'],
            'completion_status': delivery['delivery_contract']['completion_status'],
            'run_ids': run_ids, 'run_hashes': run_hashes, 'deadline_at': operation['deadline_at'],
        }}
    except (FoundryError, OSError, KeyError, TypeError, ValueError, StopIteration):
        return denied
