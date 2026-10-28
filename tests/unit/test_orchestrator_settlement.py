from __future__ import annotations

import json

import httpx
import respx

from orchestrator_agent import mediation

REF = {
    "run_id": "run-1",
    "transaction_id": "vf_1",
    "seller_id": "northwind-audio",
    "purpose": "seller_accept",
}
ENVELOPE = {
    "schema": "https://marketmesh.example/extensions/commerce/v1/schemas/accept-offer.json",
    "schema_version": "1.0",
    "payload": {
        "offer_id": "offer-1",
        "round": 1,
        "accepted_total_cents": 123400,
        "accepted_by_buyer_task": "run-1",
        "settlement_transaction_id": "vf_1",
        "agreement_hash": "a" * 64,
    },
}


@respx.mock
async def test_resolve_settlement_token_uses_the_internal_header():
    route = respx.post("http://buyer/internal/settlement/seller-token").mock(
        return_value=httpx.Response(
            200,
            json={
                "seller_token": "v1.secret",
                "expires_at": "2099-10-30T12:00:00Z",
            },
        )
    )
    token = await mediation._resolve_settlement_token(
        "http://buyer", "internal-token", REF, timeout_seconds=5.0
    )
    assert token == "v1.secret"
    request = route.calls[0].request
    assert request.headers["x-marketmesh-internal-token"] == "internal-token"
    assert json.loads(request.content)["transaction_id"] == "vf_1"


def test_inject_settlement_token_does_not_mutate_the_source():
    injected = mediation._inject_settlement_token(ENVELOPE, "v1.secret")
    assert injected["payload"]["settlement_token"] == "v1.secret"
    assert "settlement_token" not in ENVELOPE["payload"]


def test_redact_settlement_removes_token_fields_and_values():
    value = {
        "payload": {"settlement_token": "v1.secret", "offer_id": "offer-1"},
        "note": "token v1.secret must not leak",
    }
    redacted = mediation._redact_settlement(value, "v1.secret")
    assert redacted["payload"]["settlement_token"] == "[REDACTED]"
    assert "v1.secret" not in json.dumps(redacted)


@respx.mock
async def test_mediate_seller_call_injects_and_redacts_the_token(monkeypatch):
    captured: list = []

    async def fake_send(base_url, message, token=None):
        captured.append((base_url, message, token))
        return []

    monkeypatch.setattr(mediation, "_a2a_send", fake_send)
    respx.post("http://buyer/internal/settlement/seller-token").mock(
        return_value=httpx.Response(
            200,
            json={
                "seller_token": "v1.secret",
                "expires_at": "2099-10-30T12:00:00Z",
            },
        )
    )

    result = await mediation.mediate_seller_call(
        buyer_task_id="run-1",
        seller_card_url="http://seller/.well-known/agent-card.json",
        buyer_a2a_url="http://buyer-a2a",
        seller_request=ENVELOPE,
        seller_id="northwind-audio",
        settlement_secret_ref=REF,
        buyer_internal_url="http://buyer",
        buyer_internal_token="internal-token",
    )

    from commerce_core.a2a_parts import first_envelope

    sent = first_envelope(captured[0][1])
    assert sent is not None
    assert sent["payload"]["settlement_token"] == "v1.secret"
    assert result["resumed"] is True
    assert "v1.secret" not in json.dumps(result)
    assert (
        result["seller_communication"]["request"]["payload"]["settlement_token"]
        == "[REDACTED]"
    )


async def test_mediate_seller_call_keeps_legacy_requests_unmodified(monkeypatch):
    captured: list = []

    async def fake_send(base_url, message, token=None):
        captured.append((base_url, message, token))
        return []

    monkeypatch.setattr(mediation, "_a2a_send", fake_send)
    result = await mediation.mediate_seller_call(
        buyer_task_id="run-1",
        seller_card_url="http://seller/.well-known/agent-card.json",
        buyer_a2a_url="http://buyer-a2a",
        seller_request=ENVELOPE,
        seller_id="northwind-audio",
    )
    from commerce_core.a2a_parts import first_envelope

    sent = first_envelope(captured[0][1])
    assert sent is not None
    assert "settlement_token" not in sent["payload"]
    assert result["resumed"] is True


@respx.mock
async def test_token_resolution_failure_aborts_before_the_seller_call(monkeypatch):
    called: list = []

    async def fake_send(base_url, message, token=None):
        called.append(base_url)
        return []

    monkeypatch.setattr(mediation, "_a2a_send", fake_send)
    respx.post("http://buyer/internal/settlement/seller-token").mock(
        return_value=httpx.Response(409, json={"detail": "expired"})
    )
    result = await mediation.mediate_seller_call(
        buyer_task_id="run-1",
        seller_card_url="http://seller/.well-known/agent-card.json",
        buyer_a2a_url="http://buyer-a2a",
        seller_request=ENVELOPE,
        seller_id="northwind-audio",
        settlement_secret_ref=REF,
        buyer_internal_url="http://buyer",
        buyer_internal_token="internal-token",
    )
    assert "error" in result
    assert "v1.secret" not in json.dumps(result)
    assert called == []
