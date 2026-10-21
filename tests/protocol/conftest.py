import pytest

from commerce_core.cards import fetch_agent_card
from tests.support.a2a import make_client
from tests.support.servers import seller_server

__all__ = ["seller_server", "seller_session"]


@pytest.fixture
async def seller_session(seller_server):
    card = await fetch_agent_card(
        f"{seller_server}/.well-known/agent-card.json"
    )
    client = await make_client(card, "test-seller-token")
    try:
        yield client, card
    finally:
        await client.close()
