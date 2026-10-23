import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from buyer_agent.graph import build_mediated_buyer_graph
from tests.support.fake_buyer import FakeServices
from commerce_core.contracts import RFQ


@pytest.fixture
def fake_services():
    return FakeServices()


@pytest.fixture
def mediated_graph():
    return build_mediated_buyer_graph(checkpointer=MemorySaver())


def cfg(fake_services, tid):
    return {"configurable": {"thread_id": tid, "services": fake_services}}


@pytest.mark.asyncio
async def test_mediated_graph_pauses_with_seller_call_reason(mediated_graph, fake_services):
    g = mediated_graph
    c = cfg(fake_services, "run-sc")
    await g.ainvoke(
        {"messages": [HumanMessage(content="Buy 12 Nimbus NC-700 ANC headsets, budget $3400, 14 days, 24mo warranty, 30d returns.")], "stage": "new"},
        config=c,
    )
    snap = await g.aget_state(c)
    assert snap.next == ("pause_seller_call",)
    iv = snap.tasks[0].interrupts[0].value
    assert iv["reason"] == "seller_call"
    assert iv["kind"] == "rfq"
    assert iv["seller_id"] in {"northwind-audio", "circuitforge", "aurora-supply"}


@pytest.mark.asyncio
async def test_mediated_graph_resumes_and_reaches_approval(mediated_graph, fake_services):
    g = mediated_graph
    c = cfg(fake_services, "run-sc2")
    await g.ainvoke(
        {"messages": [HumanMessage(content="Buy 12 Nimbus NC-700 ANC headsets, budget $3400, 14 days, 24mo warranty, 30d returns.")], "stage": "new"},
        config=c,
    )
    for _ in range(3):
        snap = await g.aget_state(c)
        if snap.next == ("await_approval",):
            break
        assert snap.next == ("pause_seller_call",)
        iv = snap.tasks[0].interrupts[0].value
        assert iv["reason"] == "seller_call"
        seller_id = iv["seller_id"]
        req = iv["request"]
        rfq = RFQ.model_validate(req["payload"] if isinstance(req, dict) and "payload" in req else req)
        from commerce_core.contracts import CounterOffer
        session = await fake_services.a2a.open_session(fake_services.registry.endpoint(seller_id), "run-sc2")
        turn = await session.send_counter(
            f"task-{seller_id}", "run-sc2",
            CounterOffer(negotiation_round=2, target_unit_price_cents=25000, rationale="gate"),
        )
        await g.ainvoke(
            Command(resume={"offers": [o.model_dump(mode="json") for o in turn.offers], "task_id": turn.task_id, "context_id": turn.context_id}),
            config=c,
        )
    snap = await g.aget_state(c)
    assert snap.next == ("await_approval",)
    assert snap.tasks[0].interrupts[0].value["reason"] == "order_approval"