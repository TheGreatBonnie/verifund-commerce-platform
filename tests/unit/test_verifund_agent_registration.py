from __future__ import annotations

import json

import httpx
import pytest
import respx
from verifund_agent.register import card_url_from_env, main, register


def test_card_url_defaults_from_the_agent_url(monkeypatch):
    monkeypatch.delenv("VERIFUND_AGENT_CARD_URL", raising=False)
    monkeypatch.setenv("VERIFUND_AGENT_URL", "http://agent:9301/")
    assert (
        card_url_from_env()
        == "http://agent:9301/.well-known/agent-card.json"
    )


@respx.mock
async def test_register_posts_the_card_url_with_admin_auth():
    route = respx.post("http://registry/v1/agents").mock(
        return_value=httpx.Response(
            201,
            json={
                "agent_id": "verifund",
                "card_url": "http://agent:9301/.well-known/agent-card.json",
            },
        )
    )
    row = await register(
        registry_url="http://registry/",
        admin_token="admin",
        agent_id="verifund",
        card_url="http://agent:9301/.well-known/agent-card.json",
        timeout_seconds=1,
        interval_seconds=0,
    )
    assert row["agent_id"] == "verifund"
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer admin"
    assert json.loads(request.read()) == {
        "agent_id": "verifund",
        "card_url": "http://agent:9301/.well-known/agent-card.json",
    }


@respx.mock
async def test_register_retries_a_transient_registry_error():
    route = respx.post("http://registry/v1/agents")
    route.side_effect = [
        httpx.Response(503, text="registry starting"),
        httpx.Response(201, json={"agent_id": "verifund"}),
    ]
    row = await register(
        registry_url="http://registry",
        admin_token="admin",
        agent_id="verifund",
        card_url="http://agent:9301/.well-known/agent-card.json",
        timeout_seconds=1,
        interval_seconds=0,
    )
    assert row["agent_id"] == "verifund"
    assert route.call_count == 2


@respx.mock
async def test_register_fails_fast_when_the_card_is_invalid():
    respx.post("http://registry/v1/agents").mock(
        return_value=httpx.Response(400, text="missing streaming")
    )
    with pytest.raises(RuntimeError, match="missing streaming"):
        await register(
            registry_url="http://registry",
            admin_token="admin",
            agent_id="verifund",
            card_url="http://agent:9301/.well-known/agent-card.json",
            timeout_seconds=1,
            interval_seconds=0,
        )


def test_main_requires_the_registry_admin_token(monkeypatch, capsys):
    monkeypatch.delenv("REGISTRY_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    assert main([]) == 1
    assert "REGISTRY_ADMIN_TOKEN" in capsys.readouterr().err

