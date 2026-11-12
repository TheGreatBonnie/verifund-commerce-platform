from __future__ import annotations

PAYLOAD_NAMES = (
    "rfq",
    "offer",
    "counter_offer",
    "accept_offer",
    "purchase_order",
    "order",
    "commerce_error",
    "negotiation_history",
)


def is_known_payload(name: str) -> bool:
    return name in PAYLOAD_NAMES
