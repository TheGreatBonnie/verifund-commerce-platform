from __future__ import annotations


async def publish_agent(client, agent, card) -> None:
    await client.post(
        "/v1/agents",
        json={
            "agent_id": agent["id"],
            "name": agent.get("name", agent["id"]),
            "card_url": card["card_url"],
            "skills": card.get("skills", []),
            "card_json": card.get("card_json", {}),
            "organization_id": agent["organization_id"],
            "published": True,
        },
    )


async def publish_seller(client, *, seller_id: str, card_url: str,
                         organization_id: str | None,
                         admin_token: str) -> None:
    """Project an activated seller into the marketplace registry.

    The registry fetches the seller card and public catalog from ``card_url``
    and stores the catalog listings that back ``GET /v1/products``.
    ``POST /v1/sellers`` is admin-only, so the bearer token is required.
    """
    response = await client.post(
        "/v1/sellers",
        headers={"authorization": f"Bearer {admin_token}"},
        json={
            "seller_id": seller_id,
            "card_url": card_url,
            "organization_id": organization_id,
        },
    )
    response.raise_for_status()


async def unpublish_agent(client, agent_id) -> None:
    await client.post(
        "/v1/agents",
        json={
            "agent_id": agent_id,
            "card_url": "",
            "card_json": {},
            "organization_id": None,
            "published": False,
        },
    )
