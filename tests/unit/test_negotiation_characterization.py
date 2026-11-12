from datetime import UTC, datetime, timedelta

from commerce_core.contracts import Offer, OfferLineItem, OfferStatus, OfferTerms


def make_offer(*, total_cents: int = 226800, valid_until: datetime | None = None) -> Offer:
    return Offer(
        offer_id="offer-1",
        request_id="rfq-1",
        seller_id="seller-a",
        seller_name="Seller A",
        seller_rating=4.5,
        task_id="task-1",
        context_id="run-1",
        line_items=[
            OfferLineItem(
                sku="MM-WIRELESS-HEADPHONES",
                name="Wireless Headphones",
                quantity=12,
                unit_price_cents=18900,
                list_unit_price_cents=19900,
                warranty_addon_cents=0,
            )
        ],
        subtotal_cents=226800,
        shipping_cents=0,
        tax_cents=0,
        fees_cents=0,
        total_cents=total_cents,
        delivery_days=7,
        warranty_months=12,
        returns_days=30,
        valid_until=valid_until or (datetime.now(UTC) + timedelta(days=1)),
        terms=OfferTerms(sustainability_certified=True, stock_confidence=1.0),
        status=OfferStatus.PROPOSED,
        round=1,
    )


def test_offer_totals_validate_current_contract():
    offer = make_offer()
    assert offer.total_cents == 226800
    assert offer.subtotal_cents == 12 * 18900


def test_offer_rejects_mismatched_total():
    try:
        make_offer(total_cents=1)
    except ValueError as exc:
        assert "total_cents" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def rfq_text_safe_current(text: str, max_total_cents: int) -> bool:
    if not text:
        return False
    budget_dollars = f"{max_total_cents // 100}"
    budget_cents = str(max_total_cents)
    return "max_total_cents" not in text and budget_dollars not in text and budget_cents not in text


def test_budget_safety_rejects_disclosed_budget():
    assert rfq_text_safe_current("Quote 12 units", 340000) is True
    assert rfq_text_safe_current("Budget is 3400 dollars", 340000) is False
    assert rfq_text_safe_current("max_total_cents 340000", 340000) is False
