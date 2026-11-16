from __future__ import annotations

from types import SimpleNamespace

from buyer_agent.agreement_service import BuyerAgreementService
from buyer_agent.graph import report_seller_review
from verifund_contracts import (
    AgreementDecision,
    AgreementReviewResult,
    SellerAgreementDecisionRequest,
)

BASE_DECISION = {
    "party": "seller",
    "status": "operator_required",
    "run_id": "run-1",
    "transaction_id": "vf_1",
    "agreement_version": 1,
    "agreement_hash": "a" * 64,
    "offer_hash": "b" * 64,
    "actor_type": "SELLER_AGENT",
    "actor_id": "northwind-audio",
    "task_id": "seller-task-1",
    "context_id": "ctx-1",
    "reviewed_at": "2026-10-27T12:00:00Z",
    "reason_code": "outside_mandate",
    "note": "Outside the seller mandate.",
}


class Settlement:
    def __init__(self) -> None:
        self.accepts: list[dict] = []
        self.rejects: list[dict] = []

    async def accept(self, transaction_id, **kwargs):
        self.accepts.append({"transaction_id": transaction_id, **kwargs})
        return {"state": "AGREED"}

    async def reject(self, transaction_id, **kwargs):
        self.rejects.append({"transaction_id": transaction_id, **kwargs})
        return {"state": "CANCELED"}


class Agreements:
    def __init__(self) -> None:
        self.decisions: list[dict] = []

    async def record_seller_decision(self, agreement_id, result):
        self.decisions.append({"agreement_id": agreement_id, "result": result})
        return {"status": "PENDING_SELLER", "version": 1}

    async def get_agreement(self, agreement_id):
        return {
            "agreement_id": agreement_id,
            "status": "PENDING_SELLER",
            "seller_operator_required": True,
        }


class SettlementStore:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    async def save_agreement(self, run_id, agreement):
        self.saved.append({"run_id": run_id, "agreement": agreement})


class Services:
    def __init__(self) -> None:
        self.settlement = Settlement()
        self.agreements = Agreements()
        self.store = SimpleNamespace(settlement=SettlementStore())


def state(status: str, reason_code: str | None = None) -> dict:
    decision = {**BASE_DECISION, "status": status}
    if reason_code is not None:
        decision["reason_code"] = reason_code
    return {
        "run_id": "run-1",
        "seller_decision": decision,
        "settlement": {
            "transaction_id": "vf_1",
            "agreement": {
                "agreement_id": "agr-1",
                "seller_id": "northwind-audio",
                "agreement_hash": "a" * 64,
                "amount_cents": 123400,
            },
            "state": "AWARDED",
        },
    }


def config(services: Services) -> dict:
    return {"configurable": {"services": services}}


async def test_operator_required_does_not_reject_the_agreement():
    services = Services()
    result = await report_seller_review(
        state("operator_required"), config(services)
    )
    assert services.settlement.rejects == []
    assert result["stage"] == "operator_required"


async def test_changes_requested_does_not_reject_the_agreement():
    services = Services()
    result = await report_seller_review(
        state("changes_requested"), config(services)
    )
    assert services.settlement.rejects == []
    assert result["stage"] == "changes_requested"


async def test_operator_required_records_the_seller_decision():
    services = Services()
    await report_seller_review(state("operator_required"), config(services))
    assert len(services.agreements.decisions) == 1
    assert services.agreements.decisions[0]["agreement_id"] == "agr-1"


async def test_escalation_keeps_the_agreement_pending():
    services = Services()
    result = await report_seller_review(
        state("operator_required"), config(services)
    )
    assert result["settlement"]["state"] == "AWARDED"
    saved = services.store.settlement.saved
    assert len(saved) == 1
    assert saved[0]["agreement"]["status"] == "PENDING_SELLER"
    assert saved[0]["agreement"]["seller_operator_required"] is True


async def test_rejected_still_rejects_with_a_coerced_reason_code():
    services = Services()
    result = await report_seller_review(
        state("rejected", "outside_mandate"), config(services)
    )
    assert len(services.settlement.rejects) == 1
    assert services.settlement.rejects[0]["reason_code"] == "other"
    assert result["stage"] == "rejected"


async def test_accepted_still_accepts():
    services = Services()
    result = await report_seller_review(state("accepted"), config(services))
    assert len(services.settlement.accepts) == 1
    assert services.settlement.rejects == []
    assert result["stage"] == "agreed"


async def test_the_escalated_decision_body_matches_the_control_plane_contract():
    captured: dict = {}

    class Client:
        async def get_agreement(self, agreement_id):
            return {"agreement_id": agreement_id, "transaction_id": "vf_1"}

        async def record_seller_decision(
            self, agreement_id, payload, *, seller_token=None, idempotency_key=None
        ):
            captured["payload"] = payload
            captured["idempotency_key"] = idempotency_key
            return {"status": "PENDING_SELLER", "version": 1}

    service = BuyerAgreementService(client=Client())
    decision = AgreementReviewResult.model_validate(BASE_DECISION)
    await service.record_seller_decision("agr-1", decision)

    request = SellerAgreementDecisionRequest.model_validate(captured["payload"])
    assert request.decision == AgreementDecision.OPERATOR_REQUIRED
    assert request.offer_hash == "b" * 64
    assert request.actor_id == "northwind-audio"
    assert captured["idempotency_key"] == "seller-decision:agr-1:1"
