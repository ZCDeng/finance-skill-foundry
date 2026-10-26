"""A localized aging identifier migration must not reuse prior calculation identity."""
from foundry.finance_service import FINANCE_CALCULATION_VERSION, _reproducibility_status


def test_aging_identifier_migration_has_a_new_calculation_epoch():
    assert FINANCE_CALCULATION_VERSION == 4


def test_prior_epoch_difference_is_unverified_and_current_epoch_difference_is_failure():
    previous = [{'calculation_version': 3, 'output_hash': 'localized-label-output'}]
    assert _reproducibility_status(previous, 'canonical-identifier-output') == 'unverified'
    previous.append({'calculation_version': FINANCE_CALCULATION_VERSION,
                     'output_hash': 'canonical-identifier-output'})
    assert _reproducibility_status(previous, 'canonical-identifier-output') == 'reproducible'
    assert _reproducibility_status(previous, 'different-current-output') == 'non_reproducible'
