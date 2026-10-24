import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from buyer_agent.graph import build_buyer_graph
from tests.support.fake_buyer import FakeServices
from commerce_core.contracts import RFQ, CounterOffer, AcceptOffer


@pytest.fixture
def fake_services():
    return FakeServices()


@pytest.fixture
def buyer_graph():
    return build_buyer_graph(checkpointer=MemorySaver())


def cfg(fake_services, tid):
    return {"configurable": {"thread_id": tid, "services": fake_services}}


@pytest.mark.asyncio
async def test_mediated_graph_pauses_with_seller_call_reason(buyer_graph, fake_services):
    g = buyer_graph
    c = cfg(fake_services, "run-sc")
    await g.ainvoke(
        {"messages": [HumanMessage(content="Buy 12 Nimbus NC-700 ANC headsets, budget $3400, 14 days, 24mo warranty, 30d returns.")], "stage": "new"},
        config=c,
    )
    snap = await g.aget_state(c)
    assert snap.next == ("process_seller",)
    iv = snap.tasks[0].interrupts[0].value
    assert iv["reason"] == "seller_call"
    assert iv["kind"] == "rfq"
    assert iv["seller_id"] in {"northwind-audio", "circuitforge", "aurora-supply"}


@pytest.mark.asyncio
async def test_malformed_seller_offer_does_not_crash_checkpointed_graph(buyer_graph, fake_services):
    g = buyer_graph
    c = cfg(fake_services, "run-malformed-offer")
    await g.ainvoke(
        {"messages": [HumanMessage(content="Buy 12 Nimbus NC-700 ANC headsets, budget $3400, 14 days, 24mo warranty, 30d returns.")], "stage": "new"},
        config=c,
    )
    first = (await g.aget_state(c)).tasks[0].interrupts[0].value

    await g.ainvoke(
        Command(resume={"offers": [{"offer_id": "broken"}], "task_id": "seller-task", "context_id": "seller-context"}),
        config=c,
    )

    resumed = await g.aget_state(c)
    assert resumed.next == ("process_seller",)
    next_pause = resumed.tasks[0].interrupts[0].value
    assert next_pause["reason"] == "seller_call"
    assert next_pause["seller_id"] != first["seller_id"]


@pytest.mark.asyncio
async def test_mediated_graph_reaches_approval(buyer_graph, fake_services):
    g = buyer_graph
    c = cfg(fake_services, "run-sc2")
    await g.ainvoke(
        {"messages": [HumanMessage(content="Buy 12 Nimbus NC-700 ANC headsets, budget $3400, 14 days, 24mo warranty, 30d returns.")], "stage": "new"},
        config=c,
    )
    max_steps = 40
    sessions = {}
    for _ in range(max_steps):
        snap = await g.aget_state(c)
        if snap.next == ("await_approval",):
            break
        if snap.next not in (("process_seller",),):
            break
        iv = snap.tasks[0].interrupts[0].value
        assert iv["reason"] == "seller_call"
        seller_id = iv["seller_id"]
        kind = iv["kind"]
        req = iv["request"]
        if seller_id not in sessions:
            sessions[seller_id] = await fake_services.a2a.open_session(fake_services.registry.endpoint(seller_id), "run-sc2")
        session = sessions[seller_id]
        if kind == "rfq":
            rfq = RFQ.model_validate(req["payload"] if isinstance(req, dict) and "payload" in req else req)
            turn = await session.send_rfq(rfq, "run-sc2")
        elif kind == "counter":
            assert iv["seller_task_id"] == session.task_id
            assert iv["seller_context_id"] == "run-sc2"
            counter = CounterOffer(negotiation_round=2, target_unit_price_cents=25000, rationale="gate")
            turn = await session.send_counter(session.task_id or f"task-{seller_id}", "run-sc2", counter)
        elif kind == "accept":
            assert iv["seller_task_id"] == session.task_id
            assert iv["seller_context_id"] == "run-sc2"
            from commerce_core.contracts import AcceptOffer
            turn = await session.send_accept(session.task_id or f"task-{seller_id}", "run-sc2", AcceptOffer(offer_id=f"offer-{seller_id}-final-2", round=2, accepted_total_cents=1))
        else:
            break
        await g.ainvoke(
            Command(resume={"offers": [o.model_dump(mode="json") for o in turn.offers], "task_id": turn.task_id, "context_id": turn.context_id, "order": getattr(turn, "order", None)}),
            config=c,
        )
    snap = await g.aget_state(c)
    assert snap.next == ("await_approval",), f"got {snap.next} stage={snap.values.get('stage')}"
    assert snap.tasks[0].interrupts[0].value["reason"] == "order_approval"
