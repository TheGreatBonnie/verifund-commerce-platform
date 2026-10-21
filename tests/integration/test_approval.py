from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

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


def config(fake_services, thread_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
            "services": fake_services,
        }
    }


async def test_reject_creates_no_order(buyer_graph, demo_brief, fake_services):
    cfg = config(fake_services, "run-reject")
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]}, config=cfg
    )
    snapshot = await buyer_graph.aget_state(cfg)
    assert snapshot.next == ("await_approval",)
    interrupt = snapshot.tasks[0].interrupts[0]
    assert interrupt.value["reason"] == "order_approval"

    await buyer_graph.ainvoke(
        Command(
            resume={
                "approved": False,
                "approved_by": "Demo Buyer",
                "note": "Too expensive",
            }
        ),
        config=cfg,
    )
    result = await buyer_graph.aget_state(cfg)
    assert result.values["order"] is None
    assert result.values["stage"] == "rejected"
    assert fake_services.a2a.order_calls == 0
    assert len(fake_services.a2a.cancel_calls) == 3


async def test_copilotkit_cancel_sentinel_is_a_rejection(
    buyer_graph, demo_brief, fake_services
):
    cfg = config(fake_services, "run-cancel")
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]}, config=cfg
    )
    await buyer_graph.ainvoke(
        Command(resume={"__agui_cancelled__": True, "interrupt_id": "x"}),
        config=cfg,
    )
    result = await buyer_graph.aget_state(cfg)
    assert result.values["order"] is None
    assert result.values["stage"] == "rejected"


async def test_approve_accepts_then_orders(
    buyer_graph, demo_brief, fake_services
):
    cfg = config(fake_services, "run-approve")
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]}, config=cfg
    )
    await buyer_graph.ainvoke(
        Command(
            resume={
                "approved": True,
                "approved_by": "Demo Buyer",
                "note": "Approved for the team",
            }
        ),
        config=cfg,
    )
    result = await buyer_graph.aget_state(cfg)
    assert result.values["order"]["seller_id"] == "circuitforge"
    assert result.values["order"]["status"] == "confirmed"
    assert fake_services.a2a.accept_calls == 1
    assert fake_services.a2a.order_calls == 1
    assert len(fake_services.a2a.cancel_calls) == 2
