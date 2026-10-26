"""Comparison metadata cannot contradict a native bridge's row-side identity."""
from copy import deepcopy

import pytest

from foundry.finance_requirements import _price_quantity_requirement_matches
from test_finance_native_drafts import native_case


@pytest.mark.parametrize('method', ['quantity_then_price', 'base_weights_with_interaction'])
@pytest.mark.parametrize('side', ['actual', 'baseline'])
@pytest.mark.parametrize('location', ['comparison', 'row', 'scope', 'invalid_scope'])
def test_native_bridge_rejects_conflicting_scenario_identity(tmp_path, method, side, location):
    _, _, requirements, original_run, prepared = native_case(tmp_path, method=method,
        dimensions={'method': method, 'actual_scenario': 'actual', 'baseline_scenario': 'budget'})
    run = deepcopy(original_run)
    row = run['result']['rows'][0]
    group = next(g for g in prepared['evidence_groups'] if g['group_type'] == 'price_quantity_bridge')
    item = requirements['items'][0]
    assert _price_quantity_requirement_matches(item, run, row, group)
    key = side + '_scenario'
    wrong = 'budget' if side == 'actual' else 'actual'
    if location == 'comparison':
        run['result']['comparison'][key] = wrong
    elif location == 'row':
        row[key] = wrong
    else:
        row[side + '_scope'] = {'scenario': wrong} if location == 'scope' else 'invalid'
    assert not _price_quantity_requirement_matches(item, run, row, group)
