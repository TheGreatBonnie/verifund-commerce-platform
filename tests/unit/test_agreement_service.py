from datetime import UTC, datetime, timedelta

import pytest
from verifund_contracts.models import (
    AwardRequest,
    RemedyPolicy,
    RemedyTerms,
)
from verifund_control_plane.agreements.service import AgreementService


def _award():
    from commerce_core.binding import binding_from_award, offer_hash
    base = {
        "run_id": "run-1", "buyer_id": "buyer-1", "seller_id": "seller-1",
        "offer_id": "offer-1", "request_id": "rfq-1",
        "buyer_display_name": "Buyer", "seller_display_name": "Seller",
        "currency": "USD", "amount_cents": 51600, "shipping_cents": 2500,
        "tax_cents": 3600, "fees_cents": 500, "quantity": 10,
        "line_items": [__import__("verifund_contracts.models", fromlist=["AwardLineItem"]).AwardLineItem(
            sku="SKU-1", name="Sensor", quantity=10,
            unit_price_cents=4200, warranty_addon_cents=300)],
        "delivery_days": 5, "warranty_months": 12, "returns_days": 30,
        "offer_round": 2, "offer_hash": "a" * 64,
        "offer_valid_until": datetime.now(UTC) + timedelta(hours=1),
        "remedies": RemedyTerms(non_delivery=RemedyPolicy.CANCEL_AND_REFUND,
                             late_delivery=RemedyPolicy.CANCEL_AND_REFUND,
                             damaged_goods=RemedyPolicy.REFUND_OR_REPLACEMENT),
    }
    tmp = AwardRequest.model_validate(base)
    oh = offer_hash(binding_from_award(tmp.model_dump(mode="json")))
    base["offer_hash"] = oh
    return AwardRequest.model_validate(base)


@pytest.mark.asyncio
async def test_create_and_seller_accept(tmp_path):
    from verifund_control_plane.agreements.repository import AgreementRepository
    from verifund_control_plane.agreements.tokens import ApprovalTokenService
    from verifund_control_plane.db import configure_sqlite, create_engine
    from verifund_control_plane.settings import Settings
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await configure_sqlite(engine)
    repo = AgreementRepository(engine)
    async with engine.begin() as conn:
        await repo.create_schema(conn)
    svc = AgreementService(repo=repo, token_service=ApprovalTokenService("secret-32-chars-minimum-xxxxxxxx"),
                           settings=Settings(), clock=lambda: datetime.now(UTC))
    award = _award()
    now = datetime.now(UTC)
    async with repo.transaction() as conn:
        agr = await svc.create_from_award(conn, award, "txn-1", "run-1", now)
    assert agr.status.value == "PENDING_SELLER"
    # seller accept
    from verifund_contracts.models import AgreementDecision as AD
    async with repo.transaction() as conn:
        agr2 = await svc.record_seller_decision(
            conn, agr.agreement_id, decision=AD.ACCEPT, actor_type="SELLER_AGENT",
            actor_id="seller-1", authority_ref="seller-mandate:seller-1:1",
            authority_snapshot={}, agreement_version=1, agreement_hash=agr.current_version_record.agreement_hash,
            verified_offer_hash=award.offer_hash, note="", idempotency_key="k1", now=now,
        )
    assert agr2.status.value == "PENDING_BUYER"
    await engine.dispose()
