import pytest


def test_northwind_ladder_ends_at_final_price(northwind_policy):
    assert northwind_policy.initial_unit_price_cents == 30300
    assert northwind_policy.next_price_options(30300) == [29200, 28100]
    assert northwind_policy.next_price_options(29200) == [28100]
    assert northwind_policy.next_price_options(28100) == [28100]


def test_circuitforge_warranty_add_on(circuitforge_policy):
    quote = circuitforge_policy.quote(
        quantity=12,
        unit_price_cents=26312,
        warranty_months=24,
    )
    assert quote.unit_price_cents == 26912
    assert quote.total_cents == 322944


def test_aurora_split_shipment_stock_confidence(aurora_policy):
    quote = aurora_policy.quote(
        quantity=12,
        unit_price_cents=28333,
        warranty_months=24,
        allow_split=True,
    )
    assert quote.split_shipment is True
    assert quote.delivery_days == 10
    assert 0 < quote.stock_confidence < 1


def test_aurora_initial_quote_has_no_split_commitment(aurora_policy):
    quote = aurora_policy.quote(
        quantity=12,
        unit_price_cents=30900,
        warranty_months=24,
        allow_split=False,
    )
    assert quote.split_shipment is False
    assert quote.stock_confidence == pytest.approx(8 / 12)


def test_policy_rejects_price_below_floor(northwind_policy):
    with pytest.raises(ValueError, match="floor"):
        northwind_policy.quote(
            quantity=12, unit_price_cents=27899, warranty_months=36
        )
