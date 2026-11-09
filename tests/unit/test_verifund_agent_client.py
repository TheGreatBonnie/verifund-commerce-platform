from __future__ import annotations

import httpx
import pytest
from verifund_agent.client import BuyerAPIError, BuyerInternalClient


def _client_with(handler) -> BuyerInternalClient:
    client = BuyerInternalClient("http://buyer", internal_token="internal")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.parametrize(
    "body",
    [
        {
            "detail": {
                "code": "offer_expired",
                "message": "offer has expired",
                "retryable": False,
            }
        },
        {
            "error": {
                "code": "offer_expired",
                "message": "offer has expired",
                "retryable": False,
            }
        },
    ],
)
async def test_buyer_client_preserves_domain_error_code(body) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json=body)

    client = _client_with(handler)
    try:
        with pytest.raises(BuyerAPIError) as excinfo:
            await client._request("POST", "/internal/runs/run-1/settlement/agreement", json={})
    finally:
        await client.close()

    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "offer_expired"
    assert excinfo.value.retryable is False
    assert "expired" in str(excinfo.value)


async def test_buyer_client_keeps_server_errors_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = _client_with(handler)
    try:
        with pytest.raises(BuyerAPIError) as excinfo:
            await client._request("GET", "/internal/runs/run-1/settlement")
    finally:
        await client.close()

    assert excinfo.value.status_code == 500
    assert excinfo.value.code is None
    assert excinfo.value.retryable is True
