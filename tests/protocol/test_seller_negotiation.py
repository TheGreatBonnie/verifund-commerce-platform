from datetime import UTC, datetime, timedelta

from a2a.types.a2a_pb2 import Role, SendMessageRequest, TaskState
from commerce_core.a2a_parts import make_message
from commerce_core.contracts import (
    RFQ,
    CounterOffer,
    RFQConstraints,
    RFQPreferences,
)
from commerce_core.extension import wrap_payload

from tests.support.a2a import (
    collect_stream,
    first_task_id,
    last_offer,
    task_state,
)


def make_rfq() -> RFQ:
    return RFQ(
        request_id="rfq-1",
        run_id="run-1",
        category="consumer-electronics",
        product_hint="Nimbus NC-700",
        quantity=12,
        required_by=datetime.now(UTC) + timedelta(days=14),
        constraints=RFQConstraints(
            min_warranty_months=24,
            min_returns_days=30,
            color="black",
        ),
        preferences=RFQPreferences(sustainability=True),
    )


def rfq_message():
    return make_message(
        role=Role.ROLE_USER,
        text="Please quote 12 units.",
        context_id="run-1",
        envelope=wrap_payload("rfq", make_rfq()),
    )


async def start_rfq(seller_session):
    client, _ = seller_session
    events = await collect_stream(client, SendMessageRequest(message=rfq_message()))
    return last_offer(events), events


async def test_rfq_offer_and_counter(seller_session):
    client, _ = seller_session
    events = await collect_stream(
        client, SendMessageRequest(message=rfq_message())
    )
    task_id = first_task_id(events)
    offer = last_offer(events)
    assert offer["status"] == "proposed"
    assert offer["round"] == 1
    assert offer["total_cents"] == 363600
    assert task_state(events) == TaskState.TASK_STATE_INPUT_REQUIRED

    counter = CounterOffer(
        negotiation_round=2,
        target_unit_price_cents=28790,
        requested_changes={},
        rationale="Can you improve the unit price?",
    )
    message = make_message(
        role=Role.ROLE_USER,
        text="Counter.",
        context_id="run-1",
        task_id=task_id,
        envelope=wrap_payload("counter_offer", counter),
    )
    events = await collect_stream(
        client, SendMessageRequest(message=message)
    )
    second = last_offer(events)
    assert second["round"] == 2
    assert second["total_cents"] < offer["total_cents"]


async def test_task_ids_are_stable_and_context_is_shared(seller_session):
    _offer, events = await start_rfq(seller_session)
    task_id = first_task_id(events)
    client, _ = seller_session
    counter = CounterOffer(
        negotiation_round=2,
        target_unit_price_cents=28790,
        requested_changes={},
        rationale="Can you improve the unit price?",
    )
    message = make_message(
        role=Role.ROLE_USER,
        text="Counter.",
        context_id="run-1",
        task_id=task_id,
        envelope=wrap_payload("counter_offer", counter),
    )
    events = await collect_stream(
        client, SendMessageRequest(message=message)
    )
    second = last_offer(events)
    assert second["task_id"] == task_id
    assert second["context_id"] == "run-1"
