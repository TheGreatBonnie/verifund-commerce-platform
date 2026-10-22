import pytest
from commerce_core.cards import fetch_agent_card

from tests.support.a2a import make_client
from tests.support.servers import seller_runtime, seller_server
from tests.support.session import SellerSession

__all__ = ["seller_runtime", "seller_server", "seller_session"]


@pytest.fixture
async def seller_session(seller_runtime):
    base_url, app = seller_runtime
    card = await fetch_agent_card(f"{base_url}/.well-known/agent-card.json")
    client = await make_client(card, "test-seller-token")
    try:
        yield SellerSession(
            client=client,
            card=card,
            store=app.state.store,
            base_url=base_url,
        )
    finally:
        await client.close()
