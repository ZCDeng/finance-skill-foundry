"""E30 target conflict as a pure check. Ledger C. Not an original-model pass."""
import pytest

from foundry.errors import FoundryError
from foundry.finance_scenarios import assess_target_feasibility


def test_public_target_conflict_keeps_the_negative_remainder_and_names_the_bound():
    result = assess_target_feasibility("100", "120", "0")
    assert result["remaining_target"] == "-20"
    assert result["actual_ytd"] == "120"
    assert result["feasible"] is False
    assert result["infeasible_reason"] == "remaining_target_below_minimum"
    assert result["bound_violation"] == "20"
    assert result["monthly_allocation"] is None
    assert result["clamped"] is False


def test_a_negative_remainder_above_the_floor_is_not_banned_or_clamped():
    result = assess_target_feasibility("100", "130", "-50")
    assert result["remaining_target"] == "-30"
    assert result["feasible"] is True
    assert result["infeasible_reason"] is None
    assert result["bound_violation"] == "0"
    assert result["monthly_allocation"] is None


def test_month_count_and_weights_do_not_create_an_allocation():
    result = assess_target_feasibility(
        "100", "120", "0", periods_remaining=4, weights=["1", "1", "1", "1"], cutoff="2026-09-30")
    assert result["monthly_allocation"] is None
    assert result["allocation_status"] == "not_allocated"
    assert "do not authorize" in result["allocation_withheld_because"]


def test_non_numeric_target_is_rejected():
    with pytest.raises(FoundryError, match="year_target"):
        assess_target_feasibility("later", "120", "0")
