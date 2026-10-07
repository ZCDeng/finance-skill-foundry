from decimal import Decimal

import pytest

from foundry.display_numbers import display_amount, display_percent


@pytest.mark.parametrize(("value", "shown"), [
    ("8072.5449", "8,072.54"),
    ("8072.545", "8,072.55"),
    ("-8072.545", "-8,072.55"),
    ("1234567890123456789.005", "1,234,567,890,123,456,789.01"),
    ("10", "10.00"),
    ("-0.004", "0.00"),
    ("0", "0.00"),
])
def test_display_amount_two_places_half_up_grouped(value, shown):
    assert display_amount(Decimal(value)) == shown


@pytest.mark.parametrize(("ratio", "shown"), [
    ("0.94531", "94.53%"),
    ("0.000049", "0.00%"),
    ("-0.0333", "-3.33%"),
    ("12.5", "1,250.00%"),
])
def test_display_percent_two_places(ratio, shown):
    assert display_percent(Decimal(ratio)) == shown
