from datetime import UTC, datetime, timedelta

from commerce_core.contracts import (
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    Preferences,
)
from commerce_core.negotiation.mandates import (
    budget_allows,
    hard_constraint_failures,
    rfq_text_safe,
)


def mandate(max_total_cents: int = 340000) -> Mandate:
    return Mandate(
        run_id="run-1",
        category="consumer-electronics",
        product_hint="Headphones",
        product_sku="SKU",
        quantity=12,
        max_total_cents=max_total_cents,
        deadline_days=14,
        min_warranty_months=12,
        min_returns_days=30,
        preferences=Preferences(sustainability=False, color="black"),
    )


def offer(
    *,
    total_cents: int = 2400,
    sku: str = "SKU",
    warranty: int = 12,
    returns: int = 30,
    shipping_cents: int = 0,
    subtotal_cents: int = 2400,
):
    return Offer(
        offer_id="o1",
        request_id="r1",
        seller_id="s1",
        seller_name="S1",
        seller_rating=4.0,
        line_items=[OfferLineItem(sku=sku, name="I", quantity=12, unit_price_cents=200, list_unit_price_cents=220)],
        subtotal_cents=subtotal_cents,
        shipping_cents=shipping_cents,
        total_cents=total_cents,
        delivery_days=7,
        warranty_months=warranty,
        returns_days=returns,
        valid_until=datetime.now(UTC) + timedelta(days=1),
        terms=OfferTerms(),
        status=OfferStatus.PROPOSED,
        round=1,
    )


def over_budget_offer():
    # Keep Offer model totals valid (total == subtotal + shipping) while exceeding budget.
    return offer(total_cents=340001, subtotal_cents=2400, shipping_cents=337601)


def test_rfq_text_safe_blocks_budget_disclosure():
    assert rfq_text_safe("Please quote 12 units", 340000) is True
    assert rfq_text_safe("budget 3400", 340000) is False
    assert rfq_text_safe("max_total_cents=340000", 340000) is False
    assert rfq_text_safe("", 340000) is False


def test_budget_allows_and_hard_constraints():
    m = mandate()
    assert budget_allows(340000, m.max_total_cents) is True
    assert budget_allows(340001, m.max_total_cents) is False
    assert hard_constraint_failures(m, offer()) == []
    assert hard_constraint_failures(m, over_budget_offer()) == ["over_budget"]
    assert "sku_mismatch" in hard_constraint_failures(m, offer(sku="OTHER"))
    assert "warranty_too_short" in hard_constraint_failures(m, offer(warranty=6))
