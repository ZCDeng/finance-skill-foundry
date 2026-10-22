"""A failed carry is recoverable without losing the manager's cards or its history."""
import json

import pytest

from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def fixture(tmp_path, *, partial=False):
    tasks = TaskStore(tmp_path / 'var')
    source = FinanceStore(tasks.create(title='八月', period='2026-08'), actor='manager')
    target = FinanceStore(tasks.create(title='九月', period='2026-09'), actor='manager')
    for store, period in [(source, '2026-08'), (target, '2026-09')]:
        path = tmp_path / f'{period}.json'
        path.write_text(json.dumps([{'metric': str(i), 'amount': '100', 'period': period} for i in range(9)]))
        data = store.analysis.add_dataset(path, name='kpi', metadata={'period': period})
        if store is source:
            bindings = {'kpi': data['id']}
    revision = source.analysis.save_analysis({'question': '收入', 'bindings': bindings,
        'sql': "select metric, amount, '2026-08' as period from kpi"})
    old_run = source.analysis.run_analysis(revision['id'])
    good = None
    if partial:
        good_rev = source.analysis.save_analysis({'question': '收入', 'bindings': bindings,
            'sql': 'select metric, amount, $current as period from kpi', 'scope': {'period': '2026-08'},
            'parameters': {'current': '2026-08'}, 'period_binding': {'mode': 'current', 'parameters': ['current']}})
        good = source.analysis.run_analysis(good_rev['id'])
    board = source.dashboard_save({'cards': [{'kind': 'figure', 'title': f'卡{i}',
        'run_id': (good if partial and i == 0 else old_run)['id'], 'state': 'accepted',
        'select': {'match': {'metric': str(i)}, 'column': 'amount'}} for i in range(9)]})
    return tasks, source, target, old_run, board


def test_preflight_counts_executable_cards_without_creating_runs(tmp_path):
    tasks, source, target, run, board = fixture(tmp_path)
    out = target.dashboard_carry({}, tasks=tasks)
    offer = next(item for item in out['offers'] if item['task_id'] == source.task.id)
    assert offer['ready'] == 0
    assert offer['target_period'] == '2026-09'
    assert offer['blocked'][0]['run_id'] == run['id']
    assert len(offer['blocked'][0]['card_ids']) == 9
    assert not list((target.analysis.root / 'runs').glob('*.json'))
    assert source.dashboard_read({})['dashboard'] == board


def test_preflight_uses_the_same_confirmed_period_contract_as_execution(tmp_path):
    from foundry.finance_requirements import save_requirements

    tasks, source, target, run, _ = fixture(tmp_path, partial=True)
    save_requirements(target.analysis, {'question': '全年', 'scope': {'period': '2026-01:2026-09'},
        'items': [{'id': 'revenue', 'metric': 'revenue'}]})
    out = target.dashboard_carry({}, tasks=tasks)
    offer = next(item for item in out['offers'] if item['task_id'] == source.task.id)
    # Every result in this fixture was calculated as a single month; a range needs a fresh scope decision.
    assert offer['ready'] == 0


def test_failed_nine_card_carry_persists_after_reopening(tmp_path):
    tasks, source, target, run, board = fixture(tmp_path)
    out = target.dashboard_carry({'from_task_id': source.task.id}, tasks=tasks)
    assert len(out['failed']) == 9 and out['carried'] == []
    reopened = FinanceStore(target.task, actor='manager').dashboard_read({})
    assert reopened['carry_attempt']['from_task_id'] == source.task.id
    assert {row['run_id'] for row in reopened['carry_attempt']['failed']} == {run['id']}
    assert len(reopened['carry_attempt']['failed']) == 9
    assert source.dashboard_read({})['dashboard'] == board


def test_partial_carry_can_retry_remaining_cards_without_overwriting_acceptance(tmp_path):
    tasks, source, target, run, old_board = fixture(tmp_path, partial=True)
    first = target.dashboard_carry({'from_task_id': source.task.id}, tasks=tasks)
    assert len(first['carried']) == 1 and len(first['failed']) == 8
    accepted = target.dashboard_save({'parent_id': first['dashboard']['id'],
        'cards': [{**first['dashboard']['cards'][0], 'state': 'accepted'}]})
    # An unchanged failure may be retried, but the already accepted result must not be run or replaced.
    retry = target.dashboard_carry({'from_task_id': source.task.id}, tasks=tasks)
    assert retry['carried'] == [] and len(retry['failed']) == 8
    assert retry['dashboard'] == accepted
    assert source.dashboard_read({})['dashboard'] == old_board
    with pytest.raises(FoundryError):
        target.dashboard_carry({'from_task_id': target.task.id}, tasks=tasks)


@pytest.mark.parametrize('partial', [False, True])
def test_verified_upgrade_resumes_only_failed_cards_and_keeps_history(tmp_path, partial):
    tasks, source, target, run, old_board = fixture(tmp_path, partial=partial)
    first = target.dashboard_carry({'from_task_id': source.task.id}, tasks=tasks)
    accepted = None
    if partial:
        accepted = target.dashboard_save({'parent_id': first['dashboard']['id'],
            'cards': [{**first['dashboard']['cards'][0], 'state': 'accepted'}]})['cards'][0]
    recipes = target.dashboard_repair_read({'run_id': run['id']})['repairs']
    assert len(recipes) == 1
    proposal = target.dashboard_repair_propose({'run_id': run['id'], 'spec': {
        'sql': 'select metric, amount, $period as period from kpi', 'parameters': {'period': '2026-08'},
        'period_binding': {'mode': 'current', 'parameters': ['period']}}})
    assert proposal['baseline']['verified'] is True
    assert len((target._dashboard() or {}).get('cards', [])) == int(partial)
    carried = target.dashboard_carry({'from_task_id': source.task.id}, tasks=tasks)
    assert carried['failed'] == [] and len(carried['carried']) == 9 - int(partial)
    cards = carried['dashboard']['cards']
    assert len(cards) == len({card['id'] for card in cards}) == 9
    if partial:
        assert cards[0] == accepted
    new = [card for card in cards if card['id'] in carried['carried']]
    assert all(card['state'] == 'pinned' and card['accepted'] is None for card in new)
    assert {card['run_id'] for card in new} == {proposal['run_id']}
    assert 'carry_attempt' not in target.dashboard_read({})
    assert source.dashboard_read({})['dashboard'] == old_board
    with pytest.raises(FoundryError, match='already has cards'):
        target.dashboard_carry({'from_task_id': source.task.id}, tasks=tasks)
