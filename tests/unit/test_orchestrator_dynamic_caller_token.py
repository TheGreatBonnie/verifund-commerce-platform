from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import respx
from orchestrator_agent import mediation
from orchestrator_agent.settings import Settings


def test_settings_has_no_static_seller_tokens():
    settings = Settings(_env_file=None)
    assert not hasattr(settings, "seller_northwind_token")
    assert not hasattr(settings, "seller_circuitforge_token")
    assert not hasattr(settings, "seller_aurora_token")
    assert not hasattr(settings, "seller_summit_tech_token")
    assert hasattr(settings, "verifund_control_plane_url")


@respx.mock
async def test_resolve_caller_token_exchanges_via_control_plane():
    respx.post("http://cp.test/v1/internal/buyer-token").mock(
        return_value=httpx.Response(
            200,
            json={
                "agent_id": "agent_marketmesh_buyer",
                "token": "vf_agent_from_cp",
                "scopes": ["a2a:call"],
            },
        )
    )
    token = await mediation._resolve_caller_token(
        "http://cp.test", "dev-buyer-internal"
    )
    assert token == "vf_agent_from_cp"


async def test_mediate_uses_dynamic_caller_token(monkeypatch):
    from commerce_core.a2a_parts import first_envelope

    captured = []

    async def fake_send(base_url, message, token=None):
        captured.append((base_url, message, token))
        return []

    monkeypatch.setattr(mediation, "_a2a_send", fake_send)

    async def fake_resolve(*args, **kwargs):
        return "vf_agent_dynamic"

    # The mediation path must prefer the dynamic resolver when no explicit token is given
    monkeypatch.setattr(
        mediation, "_resolve_caller_token", fake_resolve
    )

    result = await mediation.mediate_seller_call(
        buyer_task_id="run-1",
        seller_card_url="http://seller/.well-known/agent-card.json",
        buyer_a2a_url="http://buyer-a2a",
        seller_request={"schema": "x", "payload": {}},
        seller_id="33a492070e344199803b6d0f4331cee0",
        control_plane_url="http://cp.test",
        buyer_internal_token="dev-buyer-internal",
    )
    assert "error" not in result
    # captured[0] is the seller send
    assert captured[0][2] == "vf_agent_dynamic"
