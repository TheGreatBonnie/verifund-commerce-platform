from __future__ import annotations

import pytest
from buyer_agent.registry_client import RegistryClient
from tests.support.cards import build_test_card
from google.protobuf import json_format
import httpx
import respx


async def test_poll_registry_replaces_map_and_keeps_old_on_failure(tmp_path):
    base = json_format.MessageToDict(build_test_card(), preserving_proto_field_name=False)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://registry.test/v1/sellers").mock(
            return_value=httpx.Response(200, json={"sellers": [{"seller_id": "northwind-audio", "card_url": "http://127.0.0.1:9201/.well-known/agent-card.json"}]})
        )
        mock.get("http://127.0.0.1:9201/.well-known/agent-card.json").mock(
            return_value=httpx.Response(200, json=base)
        )
        mock.post("http://cp.test/v1/internal/agent-token").mock(
            return_value=httpx.Response(200, json={"agent_id": "agent_northwind-audio", "token": "tok-a", "scopes": ["a2a:call"]})
        )
        registry = RegistryClient(registry_url="http://registry.test", allowed_card_hosts=("127.0.0.1",), control_plane_url="http://cp.test", buyer_internal_token="dev-buyer-internal", client=httpx.AsyncClient())
        try:
            endpoints = await registry.poll_registry()
            assert "northwind-audio" in endpoints
            mock.get("http://registry.test/v1/sellers").mock(return_value=httpx.Response(500))
            endpoints2 = await registry.poll_registry()
            assert endpoints2 == endpoints
        finally:
            await registry.close()

async def test_poll_registry_exchanges_per_seller_token():
    base = json_format.MessageToDict(build_test_card(), preserving_proto_field_name=False)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://registry.test/v1/sellers").mock(return_value=httpx.Response(200, json={"sellers": [{"seller_id": "seller-a", "card_url": "http://127.0.0.1:9201/.well-known/agent-card.json"}]}))
        mock.get("http://127.0.0.1:9201/.well-known/agent-card.json").mock(return_value=httpx.Response(200, json=base))
        mock.post("http://cp.test/v1/internal/agent-token").mock(return_value=httpx.Response(200, json={"agent_id": "agent_seller-a", "token": "vf_agent_raw", "scopes": ["a2a:call"]}))
        registry = RegistryClient(registry_url="http://registry.test", allowed_card_hosts=("127.0.0.1",), control_plane_url="http://cp.test", buyer_internal_token="dev-buyer-internal", client=httpx.AsyncClient())
        try:
            endpoints = await registry.poll_registry()
            assert endpoints["seller-a"].token == "vf_agent_raw"
            assert registry._token_cache["seller-a"] == "vf_agent_raw"
        finally:
            await registry.close()

def test_settings_has_no_seller_tokens():
    from buyer_agent.settings import Settings
    s = Settings(_env_file=None)
    assert not hasattr(s, "seller_tokens")
