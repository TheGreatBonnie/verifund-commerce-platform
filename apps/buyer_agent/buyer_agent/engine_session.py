from __future__ import annotations

from datetime import datetime

from commerce_core.contracts import Mandate, Offer
from commerce_core.negotiation.mandates import rfq_text_safe
from commerce_core.negotiation.trust import verify_offer_binding


class BuyerNegotiationSessionEngine:
    def rfq_text_safe(self, text: str, mandate: Mandate) -> bool:
        return rfq_text_safe(text, mandate.max_total_cents)

    def trusted_offer(
        self,
        offer: Offer,
        *,
        mandate: Mandate,
        expected_seller_id: str,
        expected_request_id: str,
        validated_rating: float,
        validated_sustainability: bool,
        now_utc: datetime | None = None,
    ) -> tuple[Offer | None, str | None]:
        trusted, reject = verify_offer_binding(
            offer,
            expected_seller_id=expected_seller_id,
            expected_request_id=expected_request_id,
            expected_sku=mandate.product_sku,
            validated_rating=validated_rating,
            validated_sustainability=validated_sustainability,
            now_utc=now_utc,
        )
        if reject is None:
            return trusted, None
        return None, reject.reason
