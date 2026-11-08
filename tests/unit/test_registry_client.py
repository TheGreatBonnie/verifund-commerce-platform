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
        registry = RegistryClient(registry_url="http://registry.test", allowed_card_hosts=("127.0.0.1",), seller_tokens={"northwind-audio": "tok-a"}, client=httpx.AsyncClient())
        try:
            endpoints = await registry.poll_registry()
            assert "northwind-audio" in endpoints
            mock.get("http://registry.test/v1/sellers").mock(return_value=httpx.Response(500))
            endpoints2 = await registry.poll_registry()
            assert endpoints2 == endpoints
        finally:
            await registry.close()
