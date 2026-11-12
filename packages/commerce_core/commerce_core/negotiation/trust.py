from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from commerce_core.contracts import Offer
from commerce_core.negotiation.money import validate_offer_amounts


@dataclass(frozen=True)
class TrustReject:
    code: str
    reason: str
    retryable: bool = False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def verify_offer_binding(
    offer: Offer,
    *,
    expected_seller_id: str,
    expected_request_id: str,
    expected_sku: str | None,
    validated_rating: float,
    validated_sustainability: bool,
    now_utc: datetime | None = None,
) -> tuple[Offer | None, TrustReject | None]:
    now = _as_utc(now_utc or datetime.now(UTC))
    if offer.seller_id != expected_seller_id:
        return None, TrustReject("binding_mismatch", "offer seller_id does not match validated card")
    if offer.request_id != expected_request_id:
        return None, TrustReject("binding_mismatch", "offer request_id does not match request")
    if expected_sku and any(item.sku != expected_sku for item in offer.line_items):
        return None, TrustReject("binding_mismatch", "offer SKU does not match requested product")
    ok, reason = validate_offer_amounts(offer)
    if not ok:
        return None, TrustReject("binding_mismatch", reason or "offer totals are invalid")
    if _as_utc(offer.valid_until) <= now:
        return None, TrustReject("offer_expired", "offer is expired")
    trusted = offer.model_copy(
        update={
            "seller_rating": validated_rating,
            "terms": offer.terms.model_copy(
                update={"sustainability_certified": validated_sustainability}
            ),
        }
    )
    return trusted, None
