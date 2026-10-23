import pytest
from orchestrator_agent.mediation import mediate_seller_call


@pytest.mark.asyncio
async def test_mediate_returns_error_when_buyer_unreachable():
    result = await mediate_seller_call(
        buyer_task_id="nonexistent",
        seller_card_url="http://127.0.0.1:9201/.well-known/agent-card.json",
        buyer_a2a_url="http://127.0.0.1:9999",
        seller_request={"schema": "x", "payload": {}},
    )
    assert "error" in result