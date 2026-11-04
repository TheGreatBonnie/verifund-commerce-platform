from datetime import UTC, datetime

from commerce_core.contracts import (
    AcceptOffer,
    ApprovalReceipt,
    PurchaseOrderRequest,
    ShippingAddress,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def test_old_accept_offer_payload_still_validates():
    offer = AcceptOffer.model_validate(
        {
            "offer_id": "offer-1",
            "round": 1,
            "accepted_total_cents": 123400,
        }
    )
    assert offer.settlement_transaction_id is None
    assert offer.agreement_hash is None
    assert offer.settlement_token is None


def test_new_accept_offer_payload_validates():
    offer = AcceptOffer(
        offer_id="offer-1",
        round=1,
        accepted_total_cents=123400,
        settlement_transaction_id="vf_1",
        agreement_hash=HASH,
        settlement_token="v1.payload.signature",
    )
    assert offer.settlement_transaction_id == "vf_1"


def test_old_purchase_order_payload_still_validates():
    po = PurchaseOrderRequest.model_validate(
        {
            "request_id": "po-1",
            "run_id": "run-1",
            "offer_id": "offer-1",
            "seller_id": "northwind-audio",
            "quantity": 12,
            "shipping_address": {
                "name": "Demo Buyer",
                "line1": "1 Market Street",
                "city": "San Francisco",
                "region": "CA",
                "postal_code": "94105",
                "country": "US",
            },
            "approval": {
                "approval_id": "apr-1",
                "approved_by": "Demo Buyer",
                "approved_at": NOW.isoformat(),
            },
            "idempotency_key": "run-1:offer-1",
            "expected_total_cents": 123400,
        }
    )
    assert po.settlement_transaction_id is None
    assert po.agreement_hash is None
    assert po.settlement_token is None


def test_new_purchase_order_payload_validates():
    po = PurchaseOrderRequest(
        request_id="po-1",
        run_id="run-1",
        offer_id="offer-1",
        seller_id="northwind-audio",
        quantity=12,
        shipping_address=ShippingAddress(
            name="Demo Buyer",
            line1="1 Market Street",
            city="San Francisco",
            region="CA",
            postal_code="94105",
            country="US",
        ),
        approval=ApprovalReceipt(
            approval_id="apr-1",
            approved_by="Demo Buyer",
            approved_at=NOW,
        ),
        idempotency_key="run-1:offer-1",
        expected_total_cents=123400,
        settlement_transaction_id="vf_1",
        agreement_hash=HASH,
        settlement_token="v1.payload.signature",
    )
    assert po.agreement_hash == HASH
