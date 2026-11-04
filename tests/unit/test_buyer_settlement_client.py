from __future__ import annotations

import respx
from buyer_agent.settlement_client import BuyerSettlementClient
from httpx import Response


@respx.mock
async def test_client_uses_ops_token_and_actor():
    route = respx.get("http://control/transactions/vf_1/state").mock(
        return_value=Response(
            200,
            json={
                "transaction_id": "vf_1",
                "run_id": "run-1",
                "state": "AWARDED",
                "last_seq": 1,
                "amount_cents": 123400,
                "currency": "USD",
                "buyer_id": "demo-buyer",
                "seller_id": "northwind-audio",
                "agreement_hash": "a" * 64,
                "agreement_version": 1,
                "seller_decision": None,
                "approval": None,
                "cancellation": None,
                "funding": None,
                "purchase_order": None,
                "evidence": None,
                "verification": None,
                "payout": None,
                "receipt_available": False,
                "deadlines": {"evidence": None, "inspection": None},
                "allowed_actions": [],
                "updated_at": "2026-10-27T12:00:00Z",
            },
        )
    )
    client = BuyerSettlementClient(
        "http://control", ops_token="ops-token", actor="buyer-agent"
    )
    state = await client.get_state("vf_1")
    assert state["state"] == "AWARDED"
    assert route.calls[0].request.headers["authorization"] == "Bearer ops-token"
    assert route.calls[0].request.headers["x-verifund-actor"] == "buyer-agent"


@respx.mock
async def test_buyer_review_posts_the_hash_bound_decision():
    route = respx.post(
        "http://control/transactions/vf_1/buyer-review"
    ).mock(
        return_value=Response(
            200,
            json={
                "transaction_id": "vf_1",
                "run_id": "run-1",
                "state": "AWARDED",
                "last_seq": 2,
                "amount_cents": 123400,
                "currency": "USD",
                "buyer_id": "demo-buyer",
                "seller_id": "northwind-audio",
                "agreement_hash": "a" * 64,
                "agreement_version": 1,
                "buyer_agent_review": {
                    "status": "accepted",
                    "agreement_version": 1,
                    "agreement_hash": "a" * 64,
                    "task_id": "buyer-task-1",
                    "reviewed_at": "2026-10-27T12:00:00Z",
                },
                "seller_decision": None,
                "approval": None,
                "cancellation": None,
                "funding": None,
                "purchase_order": None,
                "evidence": None,
                "verification": None,
                "payout": None,
                "receipt_available": False,
                "deadlines": {"evidence": None, "inspection": None},
                "allowed_actions": [],
                "updated_at": "2026-10-27T12:00:00Z",
            },
        )
    )
    client = BuyerSettlementClient(
        "http://control", ops_token="ops-token", actor="buyer-agent"
    )
    projection = await client.buyer_review(
        "vf_1",
        buyer_id="demo-buyer",
        agreement_version=1,
        agreement_hash="a" * 64,
        decision="accepted",
        buyer_task_id="buyer-task-1",
        reviewed_at="2026-10-27T12:00:00Z",
        idempotency_key="buyer-review:vf_1:1",
    )
    assert projection["buyer_agent_review"]["status"] == "accepted"
    request = route.calls[0].request
    assert request.headers["idempotency-key"] == "buyer-review:vf_1:1"
    assert request.headers["x-verifund-actor"] == "buyer-agent"


@respx.mock
async def test_seller_token_endpoint_requires_the_stored_transaction():
    route = respx.post("http://control/transactions/vf_1/seller-token").mock(
        return_value=Response(
            200,
            json={
                "seller_token": "v1.new",
                "expires_at": "2026-10-30T12:00:00Z",
            },
        )
    )
    client = BuyerSettlementClient(
        "http://control", ops_token="ops-token", actor="buyer-agent"
    )
    response = await client.reissue_seller_token(
        transaction_id="vf_1",
        run_id="run-1",
        seller_id="northwind-audio",
        purpose="purchase_order",
    )
    assert response["seller_token"] == "v1.new"
    assert route.calls[0].request.headers["authorization"] == "Bearer ops-token"
