from __future__ import annotations

import pytest
from buyer_agent.graph import build_buyer_graph
from commerce_core.contracts import RFQ, AcceptOffer, CounterOffer
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

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


async def _drive(graph, config, fake_services, max_steps=60):
    sessions = {}
    for _ in range(max_steps):
        snap = await graph.aget_state(config)
        if snap.next in (("await_approval",), ()):
            return snap
        if snap.next not in (("process_seller",),):
            return snap
        iv = snap.tasks[0].interrupts[0].value
        seller_id = iv["seller_id"]
        kind = iv["kind"]
        req = iv["request"]
        if seller_id not in sessions:
            sessions[seller_id] = await fake_services.a2a.open_session(
                fake_services.registry.endpoint(seller_id), "run-test"
            )
        session = sessions[seller_id]
        if kind == "rfq":
            rfq = RFQ.model_validate(req["payload"] if isinstance(req, dict) and "payload" in req else req)
            turn = await session.send_rfq(rfq, "run-test")
        elif kind == "counter":
            counter = CounterOffer(negotiation_round=2, target_unit_price_cents=25000, rationale="gate")
            turn = await session.send_counter(session.task_id or f"task-{seller_id}", "run-test", counter)
        elif kind == "accept":
            turn = await session.send_accept(session.task_id or f"task-{seller_id}", "run-test", AcceptOffer(offer_id=f"offer-{seller_id}-final-2", round=2, accepted_total_cents=1))
        else:
            break
        await graph.ainvoke(
            Command(resume={"offers": [o.model_dump(mode="json") for o in turn.offers], "task_id": turn.task_id, "context_id": turn.context_id}),
            config=config,
        )
    return await graph.aget_state(config)


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
    snap = await _drive(buyer_graph, config, fake_services)
    assert snap.values["stage"] == "awaiting_approval"
    assert snap.values["award"]["winner"]["seller_id"] == "circuitforge"
    assert len(snap.values["negotiations"]) == 3
    assert snap.values["order"] is None
    assert snap.next == ("await_approval",)
    assert all(len(n["rounds"]) >= 2 for n in snap.values["negotiations"])
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
    await _drive(buyer_graph, config, fake_services)
    assert "max_total_cents" not in fake_services.a2a.sent_rfqs[0].model_dump_json()
    assert "3400" not in fake_services.a2a.sent_rfq_texts[0]