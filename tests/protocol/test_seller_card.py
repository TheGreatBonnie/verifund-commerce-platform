import httpx
from commerce_core.cards import parse_agent_card, validate_agent_card


async def test_card_is_valid(seller_server):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{seller_server}/.well-known/agent-card.json"
        )
    assert response.status_code == 200
    card = parse_agent_card(response.json())
    assert validate_agent_card(card) == []
    assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
    assert card.supported_interfaces[0].url == f"{seller_server}/a2a"
    assert card.supported_interfaces[0].protocol_version == "1.0"
    assert card.capabilities.streaming is True


async def test_a2a_requires_bearer(seller_server):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{seller_server}/a2a",
            headers={"A2A-Version": "1.0"},
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "GetTask",
                "params": {"id": "x"},
            },
        )
    assert response.status_code == 401


async def test_a2a_requires_version_header(seller_server):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{seller_server}/a2a",
            headers={"Authorization": "Bearer test-seller-token"},
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "m1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "hello"}],
                    }
                },
            },
        )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32009


async def test_card_is_public(seller_server):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{seller_server}/.well-known/agent-card.json"
        )
    assert "authorization" not in response.request.headers
