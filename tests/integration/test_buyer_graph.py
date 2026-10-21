from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from buyer_agent.graph import build_buyer_graph
from tests.support.fake_buyer import FakeServices


@pytest.fixture
def fake_services() -> FakeServices:
    return FakeServices()


@pytest.fixture
def buyer_graph():
    return build_buyer_graph(checkpointer=MemorySaver())


@pytest.fixture
def demo_brief() -> str:
    return (
        "Buy 12 Nimbus NC-700 ANC headsets in black for our team. "
        "Our total budget is $3,400, delivery must be within 14 days, "
        "warranty at least 24 months, returns at least 30 days, and "
        "sustainability is preferred. A human must approve the order."
    )


async def test_graph_fans_out_and_ranks_circuitforge_first(
    buyer_graph, fake_services, demo_brief
):
    config = {
        "configurable": {
            "thread_id": "run-test",
            "services": fake_services,
        }
    }
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]},
        config=config,
    )
    snapshot = await buyer_graph.aget_state(config)
    assert snapshot.values["stage"] == "awaiting_approval"
    assert snapshot.values["award"]["winner"]["seller_id"] == "circuitforge"
    assert len(snapshot.values["negotiations"]) == 3
    assert snapshot.values["order"] is None
    assert snapshot.next == ("await_approval",)
    assert all(len(n["rounds"]) >= 2 for n in snapshot.values["negotiations"])
    assert "max_total_cents" not in fake_services.a2a.sent_rfqs[0].model_dump_json()
    assert "3400" not in fake_services.a2a.sent_rfq_texts[0]


async def test_rfq_text_never_leaks_budget(
    buyer_graph, fake_services, demo_brief
):
    config = {
        "configurable": {
            "thread_id": "run-budget",
            "services": fake_services,
        }
    }
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]},
        config=config,
    )
    for rfq in fake_services.a2a.sent_rfqs:
        serialized = rfq.model_dump_json()
        assert "max_total_cents" not in serialized
        assert "3400" not in serialized
        assert "$3,400" not in (rfq.message or "")
