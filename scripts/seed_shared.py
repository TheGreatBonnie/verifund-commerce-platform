"""Seed the shared seller database from the YAML seller profiles."""

from __future__ import annotations

import json
from pathlib import Path

from commerce_core.pricing import load_policy
from google.protobuf.json_format import MessageToDict
from seller_agent.card import build_agent_card
from seller_agent.shared_store import (
    OrgScopedStore,
    canonical_json_bytes,
    sha256_hex,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

TOOL_ALLOWLIST = [
    "commerce.catalog.search",
    "commerce.quote",
    "commerce.negotiate",
    "commerce.order",
    "commerce.agreement.review",
]


def _policy_hash(policy, seller_id: str) -> str:
    payload = {
        "seller_id": seller_id,
        "name": policy.name,
        "tagline": policy.tagline,
        "categories": list(policy.categories),
        "products": [p.model_dump(mode="json") for p in policy.catalog()],
    }
    return sha256_hex(canonical_json_bytes(payload))


async def seed_seller_rows(
    engine: AsyncEngine,
    *,
    seller_id: str,
    agent_id: str,
    organization_id: str,
    profile_path: Path | str,
    public_base_url: str = "http://127.0.0.1:9200",
) -> int:
    policy = load_policy(profile_path)
    store = OrgScopedStore(
        engine, organization_id=organization_id, agent_id=agent_id)
    await store.import_products(
        [p.model_dump(mode="json") for p in policy.catalog()],
        replace=True,
    )
    card = build_agent_card(
        policy, f"{public_base_url.rstrip('/')}/{seller_id}", tenant=agent_id)
    card_hash = sha256_hex(canonical_json_bytes(MessageToDict(card)))
    policy_hash = _policy_hash(policy, seller_id)
    async with engine.begin() as conn:
        await conn.execute(text(
            """INSERT INTO seller_configs
                   (agent_id, organization_id, seller_id, name, tagline,
                    instructions, max_discount_bps, autonomy_mode,
                    tool_allowlist_json, policy_version, policy_hash, card_hash,
                    config_version, status)
               VALUES (:a, :o, :s, :n, :t, :ins, 1000, 'policy_bounded',
                       :tools, 1, :ph, :ch, 1, 'active')
               ON CONFLICT(agent_id) DO UPDATE SET
                 organization_id = :o, seller_id = :s, name = :n,
                 tagline = :t, instructions = :ins,
                 tool_allowlist_json = :tools, policy_hash = :ph,
                 card_hash = :ch, status = 'active',
                 updated_at = datetime('now')"""
        ), {
            "a": agent_id,
            "o": organization_id,
            "s": seller_id,
            "n": policy.name,
            "t": policy.tagline,
            "ins": "",
            "tools": json.dumps(TOOL_ALLOWLIST),
            "ph": policy_hash,
            "ch": card_hash,
        })
    return len(policy.catalog())
