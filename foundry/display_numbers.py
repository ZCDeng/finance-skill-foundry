"""How a figure is written in the words a run shows: one rule for every backend display string.

Amounts and percentages read at two places, rounded half away from zero, with thousands grouped, the same as the
frontend's decimalToFixed (app/src/lib/figures.ts). Only display strings use this; stored values, fact values and
the numbers a draft is checked against keep their exact digits.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

# Enough working precision that quantizing any finite amount a run can hold is exact.
DISPLAY_PRECISION = 100
_PLACES = Decimal("0.01")


def display_amount(value: Decimal) -> str:
    """An amount at two places, half away from zero, thousands grouped: 8072.5449 reads 8,072.54."""
    with localcontext() as context:
        context.prec = DISPLAY_PRECISION
        shown = value.quantize(_PLACES, rounding=ROUND_HALF_UP)
        # -0.004 rounds to zero and reads 0.00, never -0.00.
        return format(shown.copy_abs() if shown.is_zero() else shown, ",f")


def display_percent(ratio: Decimal) -> str:
    """A ratio as a percentage at two places: 0.94531 reads 94.53%."""
    with localcontext() as context:
        context.prec = DISPLAY_PRECISION
        return f"{display_amount(ratio * 100)}%"
