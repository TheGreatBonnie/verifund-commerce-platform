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
