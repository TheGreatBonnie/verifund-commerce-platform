from dataclasses import dataclass

from commerce_core.contracts import Mandate, Offer

WEIGHTS = {
    "price": 0.45,
    "delivery": 0.15,
    "warranty": 0.10,
    "rating": 0.10,
    "returns": 0.05,
    "sustainability": 0.05,
    "confidence": 0.10,
}


def hard_constraint_failures(mandate: Mandate, offer: Offer) -> list[str]:
    failures = []
    if offer.total_cents > mandate.max_total_cents:
        failures.append(
            f"budget: {offer.total_cents} exceeds {mandate.max_total_cents}"
        )
    if offer.delivery_days > mandate.deadline_days:
        failures.append(f"delivery: {offer.delivery_days} days exceeds deadline")
    if offer.warranty_months < mandate.min_warranty_months:
        failures.append(
            f"warranty: {offer.warranty_months} months is below minimum"
        )
    if offer.returns_days < mandate.min_returns_days:
        failures.append(f"returns: {offer.returns_days} days is below minimum")
    if offer.terms.stock_confidence < 1.0 and not offer.terms.split_shipment:
        failures.append("stock: insufficient on-hand stock and no split commitment")
    return failures


def score_offer(
    mandate: Mandate,
    offer: Offer,
    *,
    price_floor_total_cents: int | None = None,
) -> float:
    # Price is scored against the spread from the cheapest eligible offer to
    # the buyer's ceiling, so it discriminates among qualified offers instead
    # of saturating for everything under budget. The cheapest eligible offer
    # takes full marks; an offer at the ceiling takes none.
    floor = (
        offer.total_cents
        if price_floor_total_cents is None
        else price_floor_total_cents
    )
    span = max(1, mandate.max_total_cents - floor)
    price = max(
        0.0,
        min(100.0, (mandate.max_total_cents - offer.total_cents) / span * 100.0),
    )
    delivery = max(
        0.0,
        100.0
        * (1 - (offer.delivery_days - 1) / max(1, mandate.deadline_days - 1)),
    )
    warranty = 70.0 + 30.0 * min(
        1.0,
        (offer.warranty_months - mandate.min_warranty_months)
        / max(1, 36 - mandate.min_warranty_months),
    )
    rating = offer.seller_rating / 5.0 * 100.0
    returns = 70.0 + 30.0 * min(
        1.0,
        (offer.returns_days - mandate.min_returns_days)
        / max(1, 45 - mandate.min_returns_days),
    )
    sustainability = 100.0 if offer.terms.sustainability_certified else 0.0
    confidence = offer.terms.stock_confidence * 100.0
    return round(
        price * WEIGHTS["price"]
        + delivery * WEIGHTS["delivery"]
        + warranty * WEIGHTS["warranty"]
        + rating * WEIGHTS["rating"]
        + returns * WEIGHTS["returns"]
        + sustainability * WEIGHTS["sustainability"]
        + confidence * WEIGHTS["confidence"],
        2,
    )


@dataclass(frozen=True)
class ScoredOffer:
    offer: Offer
    score: float


def rank_offers(mandate: Mandate, offers: list[Offer]) -> list[ScoredOffer]:
    eligible = [
        offer for offer in offers if not hard_constraint_failures(mandate, offer)
    ]
    if not eligible:
        return []
    floor = min(offer.total_cents for offer in eligible)
    scored = [
        ScoredOffer(
            offer=offer,
            score=score_offer(
                mandate, offer, price_floor_total_cents=floor
            ),
        )
        for offer in eligible
    ]
    return sorted(
        scored,
        key=lambda item: (
            -item.score,
            item.offer.total_cents,
            item.offer.delivery_days,
        ),
    )
