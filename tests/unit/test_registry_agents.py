from __future__ import annotations

import httpx
import respx
from a2a.types.a2a_pb2 import AgentCard
from commerce_core.cards import validate_generic_agent_card
from google.protobuf import json_format
from registry.api import create_app
from registry.settings import Settings
from registry.store import RegistryStore
from sqlalchemy.ext.asyncio import create_async_engine

VERIFUND_CARD = {
    "name": "Verifund",
    "description": "Agreement and settlement control for MarketMesh.",
    "version": "1.0.0",
    "capabilities": {"streaming": True},
    "supportedInterfaces": [
        {
            "url": "http://127.0.0.1:9301/a2a",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ],
    "skills": [
        {"id": "verifund.agreement.create", "name": "Create agreement"},
        {"id": "verifund.transaction.status", "name": "Transaction status"},
        {"id": "verifund.transaction.fund", "name": "Fund transaction"},
        {"id": "verifund.evidence.review", "name": "Review evidence"},
        {"id": "verifund.transaction.release", "name": "Release transaction"},
        {"id": "verifund.receipt.get", "name": "Get receipt"},
    ],
    "securitySchemes": {"bearer": {"httpAuthSecurityScheme": {"scheme": "bearer"}}},
}


def card(data: dict | None = None) -> AgentCard:
    value = AgentCard()
    json_format.ParseDict(data or VERIFUND_CARD, value)
    return value


def test_generic_card_accepts_verifund_without_a_commerce_extension() -> None:
    assert validate_generic_agent_card(card()) == []


def test_generic_card_still_requires_a2a_shape() -> None:
    broken = {**VERIFUND_CARD, "capabilities": {"streaming": False}}
    assert "streaming is required" in validate_generic_agent_card(card(broken))
    no_skills = {**VERIFUND_CARD, "skills": []}
    assert any("skill" in error for error in validate_generic_agent_card(card(no_skills)))


async def test_agent_store_is_separate_from_sellers(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}")
    store = RegistryStore(engine)
    await store.create_schema()
    await store.upsert_agent(
        agent_id="verifund",
        name="Verifund",
        card_url="http://127.0.0.1:9301/.well-known/agent-card.json",
        skills=["verifund.agreement.create"],
        card_json=VERIFUND_CARD,
        card_hash="a" * 64,
        healthy=True,
        error=None,
    )
    assert [row["agent_id"] for row in await store.list_agents()] == ["verifund"]
    assert await store.list_sellers() == []
    agent = await store.get_agent("verifund")
    assert agent is not None
    assert agent["name"] == "Verifund"
    assert [row["agent_id"] for row in await store.list_agents(skill="verifund.agreement.create")] == ["verifund"]
    assert await store.list_agents(skill="verifund.unknown") == []
    await engine.dispose()


@respx.mock
async def test_agent_routes_register_refresh_and_discover(tmp_path):
    card_url = "http://127.0.0.1:9301/.well-known/agent-card.json"
    respx.get(card_url).mock(
        return_value=httpx.Response(200, json=VERIFUND_CARD)
    )
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}",
        admin_token="admin",
        allowed_card_hosts=("127.0.0.1",),
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):  # noqa: SIM117
        async with httpx.AsyncClient(transport=transport, base_url="http://registry") as http:
            refused = await http.post("/v1/agents", json={"card_url": card_url})
            assert refused.status_code == 401

            created = await http.post(
                "/v1/agents",
                headers={"authorization": "Bearer admin"},
                json={"card_url": card_url},
            )
            assert created.status_code == 201, created.text
            assert created.json()["agent_id"] == "verifund"
            assert "commerce" not in created.json()["skills"][0]

            listed = await http.get("/v1/agents", headers={"authorization": "Bearer admin"})
            assert listed.json()["agents"][0]["agent_id"] == "verifund"

            found = await http.post(
                "/v1/agents/discover",
                headers={"authorization": "Bearer admin"},
                json={"skill": "verifund.transaction.fund"},
            )
            assert found.status_code == 200
            assert found.json()["agents"][0]["agent_id"] == "verifund"

            missing = await http.post(
                "/v1/agents/discover",
                headers={"authorization": "Bearer admin"},
                json={"skill": "verifund.unknown"},
            )
            assert missing.json() == {"agents": []}

            refreshed = await http.post(
                "/v1/agents/verifund/refresh",
                headers={"authorization": "Bearer admin"},
            )
            assert refreshed.status_code == 200
            assert refreshed.json()["healthy"] is True
