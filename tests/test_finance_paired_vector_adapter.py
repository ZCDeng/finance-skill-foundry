"""Public paired vectors retain declared identities through the native VMP path."""
from copy import deepcopy
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, localcontext
from fractions import Fraction
import json
from pathlib import Path

import pytest

from foundry.finance_service import FinanceStore
from foundry.finance_variance import price_quantity_bridge
from foundry.task import TaskStore
from tools import finance_professional_adapters as adapter


PUBLIC = Path(__file__).resolve().parent / 'fixtures/finance_evals/professional/public'


def public_case():
    return json.loads((PUBLIC / 'E01--row_order.json').read_text())


def replace(case, field, value):
    next(row for row in case['data'] if row['name'] == field)['value'] = value


def price_quantity(public):
    return next(d['rows'] for d in public['datasets'] if d['name'] == 'price_quantity')


@pytest.mark.parametrize('actual', ['B:48@18;A:72@12', 'A:72@12;B:48@18'])
def test_declared_products_and_source_locations_survive_independent_order(actual):
    case = public_case()
    replace(case, 'actual', actual)
    untouched = deepcopy(case)
    public, trace = adapter.adapt(case)
    basket = price_quantity(public)
    assert case == untouched
    assert trace['public_sha256'] == adapter.digest(case)
    assert trace['output_sha256'] == adapter.digest(public)
    assert trace['readiness']['route'] == 'native_volume_mix_price'
    assert trace['readiness']['acceptance_readiness'] == 'not_verified'
    assert [r['product'] for r in basket] == ['B', 'A'] + [p.split(':')[0] for p in actual.split(';')]
    assert {(r['scenario'], r['product']): (r['quantity'], r['price'], r['amount']) for r in basket} == {
        ('budget', 'B'): ('50', '20', '1000'), ('budget', 'A'): ('50', '10', '500'),
        ('actual', 'B'): ('48', '18', '864'), ('actual', 'A'): ('72', '12', '864'),
    }
    for row, transform in zip(basket, trace['transforms'], strict=True):
        source = case['data'][row['source_row'] - 1]
        assert source['name'] == row['source_field'] == row['scenario']
        assert source['value'][row['source_character_start']:row['source_character_end']] == row['source_literal']
        assert row['source_literal'] == f"{row['product']}:{row['quantity']}@{row['price']}"
        assert row['quantity_unit'] == '件'
        assert transform['input_fields'] == [row['scenario'], 'quantity_unit']
        assert transform['source_item'] == row['source_item']


def test_paired_schema_is_generic_and_never_substitutes_golden_values():
    case = public_case()
    case['case_id'] = 'E01--independent-public-vector'
    replace(case, 'budget', '产品乙:2.50@+8.4;产品甲:1e1@.25')
    replace(case, 'actual', '产品甲:11@.30;产品乙:3.5@9')
    public, _ = adapter.adapt(case)
    basket = price_quantity(public)
    assert [(r['product'], r['quantity'], r['price']) for r in basket] == [
        ('产品乙', '2.50', '+8.4'), ('产品甲', '1e1', '.25'),
        ('产品甲', '11', '.30'), ('产品乙', '3.5', '9'),
    ]
    assert [Decimal(r['amount']) for r in basket] == [Decimal('21'), Decimal('2.5'), Decimal('3.3'), Decimal('31.5')]


@pytest.mark.parametrize('precision,rounding', [(6, ROUND_DOWN), (28, ROUND_HALF_EVEN), (80, ROUND_UP)])
@pytest.mark.parametrize('quantity,price', [
    ('1.234567890123456', '1.234567890123456'),
    ('1.234567890123456789012345678901234567890123456',
     '9.876543210987654321098765432109876543210987654'),
])
def test_paired_amounts_are_exact_under_different_ambient_contexts(precision, rounding, quantity, price):
    case = public_case()
    for side in ('budget', 'actual'):
        replace(case, side, f'long-decimal-product:{quantity}@{price}')
    expected = Fraction(Decimal(quantity)) * Fraction(Decimal(price))
    with localcontext() as context:
        context.prec = precision
        context.rounding = rounding
        public, _ = adapter.adapt(case)
        assert (context.prec, context.rounding) == (precision, rounding)
        basket = price_quantity(public)
        assert all(Fraction(Decimal(row['amount'])) == expected for row in basket)
        assert all((row['quantity'], row['price']) == (quantity, price) for row in basket)
        result = price_quantity_bridge(basket, {'method': 'volume_mix_price'})['rows'][0]
        assert result['applicability'] == 'comparable', result
        assert result['comparison_status'] == 'complete'
        assert Fraction(Decimal(result['actual'])) == expected
        assert result['actual'] == result['baseline']
        assert Decimal(result['total_variance']) == Decimal(result['residual']) == 0


@pytest.mark.parametrize('field', ['budget', 'actual', 'quantity_unit'])
def test_missing_paired_field_is_a_controlled_rejection(field):
    case = public_case()
    case['data'] = [row for row in case['data'] if row['name'] != field]
    with pytest.raises(ValueError, match='paired product'):
        adapter.adapt(case)


@pytest.mark.parametrize('field,value', [
    ('budget', ''), ('actual', 'missing'), ('actual', 'A:72@12;'),
    ('actual', ':72@12;B:48@18'), ('actual', ' :72@12;B:48@18'),
    ('actual', 'A:72;B:48@18'), ('actual', 'A:72@@12;B:48@18'),
    ('actual', 'A:missing@12;B:48@18'), ('actual', 'A:72@NaN;B:48@18'),
    ('actual', 'A:Infinity@12;B:48@18'), ('actual', 'A:72@-Infinity;B:48@18'),
    ('actual', 'A:7_2@12;B:48@18'), ('actual', 'A:72@12;A:48@18'),
    ('budget', 'B:50@20;B:50@10'), ('actual', 'A:72@12'),
    ('actual', 'A:72@12;C:48@18'), ('quantity_unit', ''), ('quantity_unit', 'missing'),
])
def test_invalid_paired_vectors_never_return_partial_or_invented_rows(field, value):
    case = public_case()
    replace(case, field, value)
    with pytest.raises(ValueError, match='paired product'):
        adapter.adapt(case)


def test_mixed_vector_schemas_are_not_silently_prioritized():
    case = public_case()
    case['data'].append({'name': 'budget_prices', 'value': '99,99'})
    with pytest.raises(ValueError, match='paired product'):
        adapter.adapt(case)


@pytest.mark.parametrize('actual', ['B:48@18;A:72@12', 'A:72@12;B:48@18'])
def test_exact_public_vectors_reach_native_service_with_expected_decomposition(tmp_path, actual):
    case = public_case()
    replace(case, 'actual', actual)
    public, _ = adapter.adapt(case)
    path = tmp_path / 'paired-public-basket.json'
    path.write_text(json.dumps(price_quantity(public), ensure_ascii=False))
    service = FinanceStore(TaskStore(tmp_path / 'var').create(title='Public paired vector verification'))
    dataset = service.analysis.add_dataset(path, name='price_quantity')
    context = service.save_context({'bindings': {'source': dataset['id']},
                                   'scopes': {'source': {'currency': 'CNY', 'unit': '元'}}})
    run = service.explain_variance({'context_id': context['id'], 'kind': 'price_quantity',
                                   'method': 'volume_mix_price', 'actual_scenario': 'actual',
                                   'baseline_scenario': 'budget'})
    assert run['execution_status'] == 'succeeded', run.get('error')
    assert len(run['result']['rows']) == 1
    result = run['result']['rows'][0]
    expected = {'actual': '1728', 'baseline': '1500', 'total_variance': '228',
                'volume_contribution': '300', 'mix_contribution': '-120',
                'price_contribution': '48', 'residual': '0'}
    assert {key: result[key] for key in expected} == expected
    assert result['comparison_status'] == 'complete'
    assert result['applicability'] == 'comparable'
    assert len(result['source_rows']) == 4
