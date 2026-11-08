from __future__ import annotations

from commerce_core.contracts import OfferStatus

from seller_agent.planner import SellerDecision


class SellerNegotiationEngine:
    def validate_decision(
        self,
        decision: SellerDecision,
        *,
        allowed_prices: list[int],
        allowed_warranty_months: list[int],
        floor_unit_price_cents: int,
    ) -> bool:
        if decision.action not in {"propose", "counter", "accept", "reject"}:
            return False
        if decision.warranty_months not in allowed_warranty_months:
            return False
        if decision.unit_price_cents < floor_unit_price_cents:
            return False
        if decision.action in {"propose", "counter"}:
            return decision.unit_price_cents in allowed_prices
        return True

    def status_for_offer(
        self,
        *,
        round: int,
        max_rounds: int,
        unit_price_cents: int,
        floor_unit_price_cents: int,
        next_prices: list[int],
    ) -> OfferStatus:
        if round >= max_rounds:
            return OfferStatus.FINAL
        if unit_price_cents == floor_unit_price_cents:
            return OfferStatus.FINAL
        if next_prices == [unit_price_cents]:
            return OfferStatus.FINAL
        return OfferStatus.PROPOSED
