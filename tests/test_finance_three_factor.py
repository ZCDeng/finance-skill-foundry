"""Independent contracts for the fixed volume -> mix -> price basket bridge."""

from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
from random import Random

import pytest

from foundry.errors import FoundryError
from foundry.finance_variance import price_quantity_bridge


METHOD = {"method": "volume_mix_price"}
AMOUNTS = (
    "actual", "baseline", "total_variance", "volume_contribution",
    "mix_contribution", "price_contribution", "residual",
    "actual_volume", "baseline_volume",
)


def basket():
    """E01's four observations, independent of a model-generated answer."""
    return [
        {
            "ledger": "L1", "organization": "O1", "period": "2026-09",
            "currency": "CNY", "unit": "yuan", "quantity_unit": "item",
            "product": product, "scenario": scenario,
            "quantity": quantity, "price": price, "amount": amount,
            "source": {"dataset_id": "sales", "row_index": index,
                       "source_hash": "frozen-sales"},
        }
        for index, (scenario, product, quantity, price, amount) in enumerate([
            ("budget", "A", "50", "10", "500"),
            ("budget", "B", "50", "20", "1000"),
            ("actual", "A", "72", "12", "864"),
            ("actual", "B", "48", "18", "864"),
        ])
    ]


def result(rows=None, **spec):
    return price_quantity_bridge(basket() if rows is None else rows, {**METHOD, **spec})


def numeric(row, key):
    return Decimal(row[key])


def test_e01_fixed_order_closes_with_entire_basket_evidence():
    out = result()
    assert out["method"] == "volume_mix_price"
    assert len(out["rows"]) == 1
    row = out["rows"][0]
    assert {key: numeric(row, key) for key in AMOUNTS} == {
        "actual": Decimal(1728), "baseline": Decimal(1500),
        "total_variance": Decimal(228), "volume_contribution": Decimal(300),
        "mix_contribution": Decimal(-120), "price_contribution": Decimal(48),
        "residual": Decimal(0), "actual_volume": Decimal(120),
        "baseline_volume": Decimal(100),
    }
    assert "product" not in out["columns"]
    assert "product" not in row
    assert row["quantity_unit"] == "item"
    assert row["currency"] == "CNY" and row["unit"] == "yuan"
    assert row["comparison_status"] == "complete"
    assert row["applicability"] == "comparable"
    assert row["amount_basis"] == "reported_amount"
    assert {ref["row_index"] for ref in row["source_rows"]} == {0, 1, 2, 3}
    assert not out["diagnostics"]


def test_e01_is_invariant_to_input_order_and_product_dimension_selection():
    expected = result()
    assert result(list(reversed(basket()))) == expected
    assert result(dimensions=[]) == expected
    assert result(dimensions=["product"]) == expected


def test_observed_quantity_and_price_can_compute_without_reported_amount():
    rows = basket()
    for row in rows:
        del row["amount"]
    row = result(rows)["rows"][0]
    assert numeric(row, "total_variance") == 228
    assert row["amount_basis"] == "quantity_times_price"
    assert len(row["source_rows"]) == 4


def test_partly_reported_amounts_still_validate_every_declared_amount():
    rows = basket()
    del rows[0]["amount"]
    assert result(rows)["rows"][0]["amount_basis"] == "quantity_times_price"
    rows[1]["amount"] = "1001"
    out = result(rows)
    assert "price_quantity_amount_mismatch" in out["rows"][0]["reason_codes"]
    assert out["rows"][0]["total_variance"] is None


@pytest.mark.parametrize("field,value,reason", [
    ("quantity", "0", "volume_mix_price_nonpositive_quantity"),
    ("quantity", "-1", "volume_mix_price_nonpositive_quantity"),
    ("quantity", None, "price_quantity_missing"),
    ("quantity", "NaN", "volume_mix_price_invalid_number"),
    ("price", None, "price_quantity_missing"),
    ("price", "", "price_quantity_missing"),
    ("price", "Infinity", "volume_mix_price_invalid_number"),
    ("price", "-1", "volume_mix_price_negative_price"),
    ("amount", "1001", "price_quantity_amount_mismatch"),
    ("amount", "invalid", "volume_mix_price_invalid_number"),
    ("product", None, "volume_mix_price_product_missing"),
    ("product", "", "volume_mix_price_product_missing"),
    ("product", [], "volume_mix_price_product_missing"),
    ("quantity_unit", None, "volume_mix_price_quantity_unit_missing"),
    ("quantity_unit", "kg", "volume_mix_price_quantity_unit_mismatch"),
])
def test_inapplicable_baskets_keep_diagnostics_and_all_evidence(field, value, reason):
    rows = basket()
    rows[0][field] = value
    out = result(rows)
    assert len(out["rows"]) == 1
    row = out["rows"][0]
    assert row["applicability"] == "not_comparable"
    assert row["comparison_status"] == "incomplete"
    assert all(row[key] is None for key in AMOUNTS)
    assert reason in row["reason_codes"]
    assert reason in {diagnostic["code"] for diagnostic in out["diagnostics"]}
    assert {ref["row_index"] for ref in row["source_rows"]} == {0, 1, 2, 3}


def test_new_product_is_not_silently_zero_filled():
    rows = basket()
    rows[-1]["product"] = "new-C"
    row = result(rows, missing_groups_as_zero=True)["rows"][0]
    assert row["total_variance"] is None
    assert "volume_mix_price_unmatched_products" in row["reason_codes"]
    assert len(row["source_rows"]) == 4


def test_duplicate_product_observations_require_explicit_preaggregation():
    rows = basket()
    rows.append({**rows[0], "source": {"dataset_id": "sales", "row_index": 4}})
    row = result(rows)["rows"][0]
    assert row["total_variance"] is None
    assert "volume_mix_price_duplicate_product" in row["reason_codes"]
    assert len(row["source_rows"]) == 5


@pytest.mark.parametrize("field,value", [("currency", "USD"), ("unit", "wan_yuan")])
def test_cross_currency_or_amount_unit_cannot_be_combined(field, value):
    rows = basket()
    for row in rows:
        if row["scenario"] == "actual":
            row[field] = value
    out = result(rows)
    assert len(out["rows"]) == 2
    assert all(row["applicability"] == "not_comparable" for row in out["rows"])
    assert all(row["total_variance"] is None for row in out["rows"])
    assert sum(len(row["source_rows"]) for row in out["rows"]) == 4


@pytest.mark.parametrize("field", ["currency", "unit"])
def test_missing_monetary_basis_never_becomes_comparable(field):
    rows = basket()
    for row in rows:
        del row[field]
    row = result(rows)["rows"][0]
    assert "volume_mix_price_monetary_basis_missing" in row["reason_codes"]
    assert row["total_variance"] is None


def test_single_product_matches_legacy_quantity_then_price():
    rows = basket()[::2]
    rows[0].update(quantity="10", price="10", amount="100")
    rows[1].update(quantity="12", price="11", amount="132")
    new = result(rows)["rows"][0]
    old = price_quantity_bridge(rows, {"method": "quantity_then_price"})["rows"][0]
    assert numeric(new, "mix_contribution") == 0
    assert numeric(new, "volume_contribution") == Decimal(old["quantity_contribution"])
    assert numeric(new, "price_contribution") == Decimal(old["price_contribution"])
    assert new["total_variance"] == old["total_variance"]


def test_quantity_rescaling_preserves_amount_bridge_but_keeps_declared_unit():
    rows = basket()
    for row in rows:
        row["quantity"] = str(Decimal(row["quantity"]) * 1000)
        row["price"] = str(Decimal(row["price"]) / 1000)
        row["quantity_unit"] = "millipiece"
    scaled = result(rows)["rows"][0]
    original = result()["rows"][0]
    for key in AMOUNTS[:7]:
        assert numeric(scaled, key) == numeric(original, key)
    assert numeric(scaled, "actual_volume") == 120000
    assert scaled["quantity_unit"] == "millipiece"


def test_nonterminating_mix_uses_shared_bridge_levels_without_filling_residual():
    rows = basket()
    for row, quantity, price in zip(rows, ("1", "2", "2", "2"), ("1", "2", "1.25", "2.5")):
        row.update(quantity=quantity, price=price, amount=str(Decimal(quantity) * Decimal(price)))
    row = result(rows)["rows"][0]
    # Independent rational oracle: delta V=1, baseline average price=5/3,
    # actual-volume baseline-mix amount=20/3; actual-quantity old-price amount=6.
    expected = {"volume_contribution": Fraction(5, 3),
                "mix_contribution": Fraction(-2, 3), "price_contribution": Fraction(3, 2)}
    with localcontext() as ctx:
        ctx.prec = 200
        for key, rational in expected.items():
            exact = Decimal(rational.numerator) / Decimal(rational.denominator)
            assert abs(numeric(row, key) - exact) < Decimal("1e-70")
        assert sum(numeric(row, key) for key in expected) == numeric(row, "total_variance")
    assert numeric(row, "residual") == 0


def test_fixed_seed_baskets_match_independent_rational_three_factor_oracle():
    rng = Random(20261023)
    for _ in range(50):
        rows = basket()
        for row in rows:
            row["quantity"] = str(Decimal(rng.randint(1, 10000)) / 10)
            row["price"] = str(Decimal(rng.randint(0, 10000)) / 100)
            row["amount"] = str(Decimal(row["quantity"]) * Decimal(row["price"]))
        qb = [Fraction(row["quantity"]) for row in rows[:2]]
        pb = [Fraction(row["price"]) for row in rows[:2]]
        qa = [Fraction(row["quantity"]) for row in rows[2:]]
        pa = [Fraction(row["price"]) for row in rows[2:]]
        vb, va = sum(qb), sum(qa)
        mb, ma = [q / vb for q in qb], [q / va for q in qa]
        expected = {
            "volume_contribution": (va - vb) * sum(m * p for m, p in zip(mb, pb)),
            "mix_contribution": va * sum((a - b) * p for a, b, p in zip(ma, mb, pb)),
            "price_contribution": va * sum(m * (a - b) for m, a, b in zip(ma, pa, pb)),
        }
        row = result(rows)["rows"][0]
        with localcontext() as ctx:
            ctx.prec = 200
            for key, fraction in expected.items():
                oracle = Decimal(fraction.numerator) / Decimal(fraction.denominator)
                assert abs(numeric(row, key) - oracle) < Decimal("1e-65")
            assert sum(numeric(row, key) for key in expected) == numeric(row, "total_variance")
        assert numeric(row, "residual") == 0


def test_empty_selection_is_explicitly_unavailable():
    out = result(actual_filters={"period": "1900-01"}, baseline_filters={"period": "1900-01"})
    assert not out["rows"]
    assert out["diagnostics"][0]["code"] == "volume_mix_price_no_observations"


def test_each_explicit_basket_dimension_stays_separate():
    rows = basket()
    for row in rows:
        row["region"] = "north"
    extra = deepcopy(rows)
    for row in extra:
        row["region"] = "south"
        row["source"]["row_index"] += 4
    out = result(rows + extra, dimensions=["product", "region"])
    assert len(out["rows"]) == 2
    assert {row["region"] for row in out["rows"]} == {"north", "south"}
    assert all(numeric(row, "total_variance") == 228 for row in out["rows"])
    assert all(len(row["source_rows"]) == 4 for row in out["rows"])


def test_periods_remain_separate_without_explicit_side_filters():
    rows = basket()
    for row in rows:
        if row["scenario"] == "budget":
            row["period"] = "2026-08"
    assert all(row["total_variance"] is None for row in result(rows)["rows"])
    out = result(rows, actual_filters={"period": "2026-09"},
                 baseline_filters={"period": "2026-08"})
    assert len(out["rows"]) == 1
    assert numeric(out["rows"][0], "total_variance") == 228
    assert out["rows"][0]["actual_scope"]["period"] == "2026-09"
    assert out["rows"][0]["baseline_scope"]["period"] == "2026-08"


def test_same_scenario_period_filters_and_custom_fields_work():
    rows = basket()
    for row in rows:
        row["period"] = "2026-08" if row["scenario"] == "budget" else "2026-09"
        row["kind"] = "actual"
        row["sku"] = row.pop("product")
        row["q_unit"] = row.pop("quantity_unit")
    out = result(rows, actual_scenario="actual", baseline_scenario="actual",
                 actual_filters={"period": "2026-09"}, baseline_filters={"period": "2026-08"},
                 field_map={"scenario": "kind", "product": "sku"}, quantity_unit_field="q_unit")
    assert numeric(out["rows"][0], "total_variance") == 228


@pytest.mark.parametrize("spec", [{"field_map": []}, {"quantity_unit_field": []},
                                   {"field_map": {"product": []}}, {"actual_filters": []}])
def test_invalid_field_configuration_is_a_domain_error(spec):
    with pytest.raises(FoundryError):
        result(**spec)
