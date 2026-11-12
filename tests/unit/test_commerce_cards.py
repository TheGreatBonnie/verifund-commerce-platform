"""Agent card fetches must work against an HTTPS deployment.

The guard started life as a prototype check for the local Docker stack,
where every service was reached over plain HTTP on a local hostname. A
deployed gateway publishes its cards over HTTPS, so the scheme check has
to allow that while still refusing hosts outside the allowlist.
"""

from __future__ import annotations

import httpx
import pytest
from commerce_core.cards import fetch_agent_card

CARD = {
    "name": "Northwind Audio",
    "version": "1.0.0",
    "supportedInterfaces": [
        {
            "url": "https://gw.example.com/sellers/northwind-audio/a2a",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ],
    "capabilities": {"streaming": True},
    "skills": [{"id": "commerce.quote", "name": "Quote an item"}],
    "securitySchemes": {
        "bearer": {"httpAuthSecurityScheme": {"scheme": "bearer"}}
    },
}


def _client() -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=CARD)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_agent_card_accepts_https_for_allowlisted_host() -> None:
    card = await fetch_agent_card(
        "https://gw.example.com/sellers/northwind-audio/.well-known/agent-card.json",
        client=_client(),
        allowed_hosts=("gw.example.com",),
    )

    assert card.name == "Northwind Audio"


async def test_fetch_agent_card_rejects_host_outside_allowlist() -> None:
    with pytest.raises(ValueError, match="allowed"):
        await fetch_agent_card(
            "https://evil.example.net/.well-known/agent-card.json",
            client=_client(),
            allowed_hosts=("gw.example.com",),
        )


async def test_fetch_agent_card_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="allowed"):
        await fetch_agent_card(
            "file:///etc/passwd",
            client=_client(),
            allowed_hosts=("gw.example.com",),
        )


async def test_fetch_agent_card_still_allows_http() -> None:
    card = await fetch_agent_card(
        "http://127.0.0.1:9201/.well-known/agent-card.json",
        client=_client(),
        allowed_hosts=("127.0.0.1",),
    )

    assert card.name == "Northwind Audio"
