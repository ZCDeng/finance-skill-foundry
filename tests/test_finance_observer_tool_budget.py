"""An unconfigured legacy evaluator still obeys the frozen 80-tool ceiling."""
import pytest

from test_verify_finance_evals_observer import run_observer


@pytest.mark.parametrize('configured_limit', [None, 80, 2])
def test_tool_limit_rejects_before_dispatch_or_start_record(tmp_path, configured_limit):
    limit = configured_limit if configured_limit is not None else 80
    case = run_observer(tmp_path, tool_attempts=limit + 1,
                        tool_limit=configured_limit)['cases'][0]
    starts = [event for event in case['deadline']['events'] if event['phase'] == 'tool_start']
    rejected = [event for event in case['deadline']['events']
                if event['phase'] == 'admission_rejected' and event.get('reason') == 'tool_limit']
    assert len(starts) == limit
    assert len(rejected) == 1
    assert len(case['calls']) == limit
    assert case['completed'] is False
    assert f'tool turn limit exceeded: {limit}' in case['error']
    assert case['deadline']['max_tool_turns'] == limit


def test_exact_tool_limit_does_not_reject_last_admission(tmp_path):
    case = run_observer(tmp_path, tool_attempts=80)['cases'][0]
    assert len(case['calls']) == 80
    assert not any(event.get('reason') == 'tool_limit' for event in case['deadline']['events'])
