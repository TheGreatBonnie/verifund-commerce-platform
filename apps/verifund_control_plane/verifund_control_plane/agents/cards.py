from __future__ import annotations

from typing import Any

from verifund_control_plane.agents.registry_sync import publish_agent  # noqa: F401  (re-export)

SKILL_META: dict[str, dict[str, str]] = {
    "commerce.catalog.search": {
        "name": "Product Discovery",
        "description": "Search the seller's product catalog.",
    },
    "commerce.inventory.check": {
        "name": "Inventory Check",
        "description": "Check product availability in real time.",
    },
    "commerce.quote": {
        "name": "Quotation Generation",
        "description": "Return seller-approved quotations.",
    },
    "commerce.negotiate": {
        "name": "Pricing Negotiation",
        "description": "Negotiate offers within approved policies.",
    },
    "commerce.agreement.review": {
        "name": "Agreement Review",
        "description": "Review commercial agreements against stored offers.",
    },
    "commerce.order": {
        "name": "Order Management",
        "description": "Create idempotent orders for approved purchases.",
    },
}


def allowlist_to_skills(allowlist: list[str]) -> list[dict[str, Any]]:
    """Project the tool allowlist onto card skill declarations.

    Advertised skills are derived from the allowlist — never editable
    independently (spec O4).
    """
    return [
        {"id": skill_id, "tags": ["commerce"], **SKILL_META[skill_id]}
        for skill_id in allowlist
        if skill_id in SKILL_META
    ]


def build_seller_card(*, profile: dict | None, agent_name: str, agent_id: str,
                      allowlist: list[str], base_url: str, seller_id: str) -> dict:
    tagline = (profile or {}).get("tagline") or "Verifund seller agent"
    return {
        "name": agent_name,
        "description": tagline,
        "version": "1.0.0",
        "provider": {"organization": agent_name, "url": base_url},
        "capabilities": {"streaming": True, "push_notifications": False},
        "skills": allowlist_to_skills(allowlist),
        "supportedInterfaces": [
            {
                "url": f"{base_url}/{seller_id}/a2a",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
                "tenant": agent_id,
            }
        ],
        "iconUrl": f"{base_url}/favicon.ico",
    }

