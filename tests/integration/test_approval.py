from __future__ import annotations

import pytest
from buyer_agent.graph import build_buyer_graph
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from tests.support.fake_buyer import FakeServices
from commerce_core.contracts import RFQ, CounterOffer, AcceptOffer, PurchaseOrderRequest


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


async def _drive_to_approval(graph, cfg, fake_services, max_steps=60):
    sessions = {}
    for _ in range(max_steps):
        snap = await graph.aget_state(cfg)
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
                fake_services.registry.endpoint(seller_id), cfg["configurable"]["thread_id"]
            )
        session = sessions[seller_id]
        if kind == "rfq":
            rfq = RFQ.model_validate(req["payload"] if isinstance(req, dict) and "payload" in req else req)
            turn = await session.send_rfq(rfq, cfg["configurable"]["thread_id"])
        elif kind == "counter":
            counter = CounterOffer(negotiation_round=2, target_unit_price_cents=25000, rationale="gate")
            turn = await session.send_counter(session.task_id or f"task-{seller_id}", cfg["configurable"]["thread_id"], counter)
        elif kind == "accept":
            turn = await session.send_accept(session.task_id or f"task-{seller_id}", cfg["configurable"]["thread_id"], AcceptOffer(offer_id=f"offer-{seller_id}-final-2", round=2, accepted_total_cents=1))
        else:
            break
        await graph.ainvoke(
            Command(resume={"offers": [o.model_dump(mode="json") for o in turn.offers], "task_id": turn.task_id, "context_id": turn.context_id}),
            config=cfg,
        )
    return await graph.aget_state(cfg)


async def _drive_order(graph, cfg, fake_services, max_steps=20):
    sessions = {}
    for _ in range(max_steps):
        snap = await graph.aget_state(cfg)
        if snap.next in ((), ("finalize",)):
            # finalize may run; check stage
            if snap.values.get("stage") in ("ordered", "rejected", "no_award"):
                return snap
        if snap.next not in (("place_order",),):
            if snap.values.get("stage") in ("ordered", "rejected"):
                return snap
            break
        iv = snap.tasks[0].interrupts[0].value
        seller_id = iv["seller_id"]
        kind = iv["kind"]
        award = (await graph.aget_state(cfg)).values.get("award") or {}
        winner = award.get("winner") or {}
        if seller_id not in sessions:
            sessions[seller_id] = await fake_services.a2a.open_session(fake_services.registry.endpoint(seller_id), cfg["configurable"]["thread_id"])
        session = sessions[seller_id]
        if kind == "accept":
            from commerce_core.contracts import AcceptOffer
            turn = await session.send_accept(session.task_id or f"task-{seller_id}", cfg["configurable"]["thread_id"], AcceptOffer(offer_id=winner.get("offer_id", ""), round=winner.get("round", 1), accepted_total_cents=winner.get("total_cents", 0)))
            await graph.ainvoke(
                Command(resume={"offers": [o.model_dump(mode="json") for o in turn.offers], "task_id": turn.task_id, "context_id": turn.context_id}),
                config=cfg,
            )
            continue
        # order
        from commerce_core.contracts import ApprovalReceipt
        from datetime import datetime, UTC
        import uuid
        turn = await session.send_order(
            PurchaseOrderRequest(
                request_id=f"po-{cfg['configurable']['thread_id']}-{seller_id}",
                run_id=cfg["configurable"]["thread_id"],
                offer_id=winner.get("offer_id", ""),
                seller_id=seller_id,
                quantity=winner.get("line_items", [{}])[0].get("quantity", 12) if winner.get("line_items") else 12,
                shipping_address=__import__("buyer_agent.graph", fromlist=["_shipping_address"])._shipping_address(),
                approval=ApprovalReceipt(approval_id=str(uuid.uuid4()), approved_by="Demo Buyer", approved_at=datetime.now(UTC), note="ok"),
                idempotency_key=f"{cfg['configurable']['thread_id']}:{winner.get('offer_id','')}",
                expected_total_cents=winner.get("total_cents", 0),
            ),
            cfg["configurable"]["thread_id"],
        )
        order = turn.order
        await graph.ainvoke(
            Command(resume={"order": order.model_dump(mode="json") if order else None, "offers": [], "task_id": turn.task_id, "context_id": turn.context_id}),
            config=cfg,
        )
    return await graph.aget_state(cfg)


async def test_reject_creates_no_order(buyer_graph, demo_brief, fake_services):
    cfg = config(fake_services, "run-reject")
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]}, config=cfg
    )
    await _drive_to_approval(buyer_graph, cfg, fake_services)
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
    assert len(fake_services.a2a.cancel_calls) == 0


async def test_copilotkit_cancel_sentinel_is_a_rejection(
    buyer_graph, demo_brief, fake_services
):
    cfg = config(fake_services, "run-cancel")
    await buyer_graph.ainvoke(
        {"messages": [HumanMessage(content=demo_brief)]}, config=cfg
    )
    await _drive_to_approval(buyer_graph, cfg, fake_services)
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
    await _drive_to_approval(buyer_graph, cfg, fake_services)
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
    # drive the mediated order pause
    await _drive_order(buyer_graph, cfg, fake_services)
    result = await buyer_graph.aget_state(cfg)
    assert result.values["order"]["seller_id"] == "circuitforge"
    assert result.values["order"]["status"] == "confirmed"
    assert fake_services.a2a.accept_calls == 1
    # mediated: order was placed via the orchestrator (test-simulated), not by the buyer graph directly