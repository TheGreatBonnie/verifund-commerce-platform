from inspect import signature
from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_mediation_reuses_seller_task_and_returns_seller_ids(monkeypatch):
    from orchestrator_agent import mediation

    sent = []

    class Event:
        task = SimpleNamespace(id="seller-task-7", context_id="seller-context-4", artifacts=[])

        def WhichOneof(self, _):
            return "task"

    async def fake_send(base_url, message, token=None):
        sent.append((base_url, message))
        return [Event()] if len(sent) == 1 else []

    monkeypatch.setattr(mediation, "_a2a_send", fake_send)
    result = await mediate_seller_call(
        buyer_task_id="buyer-run-2",
        seller_card_url="http://seller/.well-known/agent-card.json",
        buyer_a2a_url="http://buyer",
        seller_task_id="seller-task-7",
        seller_context_id="seller-context-4",
        seller_request={"schema": "counter", "payload": {}},
    )

    assert "error" not in result
    assert sent[0][1].task_id == "seller-task-7"
    assert sent[0][1].context_id == "seller-context-4"
    assert result["seller_result"]["task_id"] == "seller-task-7"
    assert result["seller_result"]["context_id"] == "seller-context-4"


@pytest.mark.asyncio
async def test_orchestrator_tool_binds_configured_buyer_url(monkeypatch):
    from orchestrator_agent import agent
    from orchestrator_agent.settings import Settings

    observed = {}

    async def fake_mediate(**kwargs):
        observed.update(kwargs)
        return {"resumed": True}

    monkeypatch.setattr(agent, "mediate_seller_call", fake_mediate)
    mediation_tool = agent._build_mediation_tool(
        Settings(buyer_a2a_url="http://buyer-configured")
    )
    assert "buyer_a2a_url" not in signature(mediation_tool.func).parameters
    await mediation_tool.func(
        buyer_task_id="buyer-run",
        seller_card_url="http://seller/.well-known/agent-card.json",
    )
    assert observed["buyer_a2a_url"] == "http://buyer-configured"
