from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from buyer_agent import console_api, settlement_api
from buyer_agent.settlement import SettlementCoordinator
from fastapi import FastAPI
from verifund_contracts import VerifundError

from tests.support.award_flow import award_payload


class Settings:
    console_api_token = "console-token"
    internal_api_token = "internal-token"
    verifund_agent_internal_token = "agent-internal"
    verifund_mode = "fake"


def projection(state: str = "FUNDED") -> dict:
    return {
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "state": state,
        "last_seq": 5,
        "amount_cents": 123400,
        "currency": "USD",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "agreement_hash": "a" * 64,
        "agreement_version": 1,
        "seller_decision": None,
        "approval": None,
        "cancellation": None,
        "funding": {"status": "captured", "capture_id": "CAP-1"},
        "purchase_order": None,
        "evidence": None,
        "verification": None,
        "payout": None,
        "receipt_available": False,
        "deadlines": {"evidence": None, "inspection": None},
        "allowed_actions": ["release"],
        "updated_at": "2026-10-27T12:00:00Z",
    }


class Store:
    def __init__(self, cached=None) -> None:
        self.cached = cached
        self.saved: list[dict] = []
        self.secret = {
            "transaction_id": "vf_1",
            "run_id": "run-1",
            "seller_id": "northwind-audio",
            "purpose": "settlement",
            "seller_token": "v1.secret",
            "expires_at": "2099-10-30T12:00:00Z",
        }

    async def get_projection(self, run_id):
        return self.cached

    async def save_projection(self, run_id, value):
        previous = int((self.cached or {}).get("last_seq") or 0)
        advanced = int(value.get("last_seq") or 0) > previous
        self.cached = value
        self.saved.append(value)
        return advanced

    async def get_secret_by_transaction(self, transaction_id):
        return self.secret if transaction_id == "vf_1" else None


class Agreements:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def view(self, run_id):
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement": {},
            "projection": await self.store.get_projection(run_id),
        }


class Client:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail_state = False

    async def get_state(self, transaction_id, *, actor=None):
        self.calls.append(("state", transaction_id, actor))
        if self.fail_state:
            raise RuntimeError("control plane down")
        return projection()

    async def release(self, transaction_id, request, *, actor=None):
        self.calls.append(("release", transaction_id, request, actor))
        return projection("PAYOUT_PENDING")

    async def flag_review(self, transaction_id, request, *, actor=None):
        self.calls.append(("flag_review", transaction_id, request, actor))
        return projection("REVIEW_REQUIRED")

    async def retry_payout(self, transaction_id, *, actor=None):
        self.calls.append(("retry_payout", transaction_id, actor))
        return projection("RELEASED")

    async def cancel(self, transaction_id, request, *, actor=None):
        self.calls.append(("cancel", transaction_id, request, actor))
        return projection("CANCELED")

    async def get_receipt(self, transaction_id, *, actor=None):
        self.calls.append(("receipt", transaction_id, actor))
        return {"payload": {}, "signature": "sig", "kid": "k1", "verified": True}

    async def get_evidence(self, transaction_id, evidence_id, *, actor=None):
        self.calls.append(("evidence", transaction_id, evidence_id, actor))
        return b"manifest", "text/plain", "manifest.txt"


class Trace:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def get_run(self, run_id):
        return {
            "run_id": run_id,
            "stage": "funded",
            "mandate_json": {},
            "award_json": {},
            "order_json": None,
            "error": None,
            "created_at": "2026-10-27T12:00:00Z",
            "updated_at": "2026-10-27T12:00:00Z",
        }

    async def record(
        self, run_id, *, direction, method, payload, **_kwargs
    ) -> None:
        self.events.append(
            {
                "run_id": run_id,
                "direction": direction,
                "method": method,
                "payload": payload,
            }
        )


class Snapshot:
    def __init__(self, next_nodes) -> None:
        self.next = next_nodes


class Graph:
    def __init__(self, paused=True) -> None:
        self.paused = paused
        self.resumed: list = []

    async def aget_state(self, config):
        return Snapshot(("await_release",) if self.paused else ())

    async def ainvoke(self, command, config):
        self.resumed.append(command)
        return {
            "__interrupt__": [
                SimpleNamespace(
                    value={
                        "reason": "settlement_release",
                        "transaction_id": "vf_1",
                        "settlement_secret_ref": {"seller_id": "northwind-audio"},
                    }
                )
            ]
        }


def services(*, cached=None, client=None, paused=True):
    store = Store(cached=cached)
    client = client or Client()
    graph = Graph(paused=paused)
    value = SimpleNamespace(
        settings=Settings(),
        settlement=client,
        store=SimpleNamespace(settlement=store, trace=Trace()),
        coordinator=SettlementCoordinator(),
        trace=Trace(),
        agreements=Agreements(store),
    )
    return value, store, client, graph


def build(*, cached=None, client=None, paused=True):
    value, store, client, graph = services(
        cached=cached, client=client, paused=paused
    )
    app = FastAPI()
    app.state.settings = value.settings
    app.state.services = value
    app.state.executor = SimpleNamespace(graph=graph)
    app.include_router(console_api.router)
    app.include_router(settlement_api.router)
    return app, store, client, graph


@pytest.fixture
async def api():
    app, store, client, graph = build(cached=projection())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://buyer"
    ) as http:
        yield http, app, store, client, graph


CONSOLE = {"x-marketmesh-console-token": "console-token"}


async def test_settlement_routes_require_the_console_token(api):
    http, *_ = api
    refused = await http.get("/api/runs/run-1/settlement")
    assert refused.status_code == 401
    refused_release = await http.post(
        "/api/runs/run-1/settlement/release", json={}
    )
    assert refused_release.status_code == 401


async def test_get_settlement_refreshes_and_caches_the_projection(api):
    http, _, store, client, _ = api
    response = await http.get("/api/runs/run-1/settlement", headers=CONSOLE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "FUNDED"
    assert body["settlement_unavailable"] is False
    assert store.saved[-1]["state"] == "FUNDED"
    assert client.calls[-1] == ("state", "vf_1", "console:reviewer")


async def test_internal_settlement_can_refresh_the_cached_projection():
    cached = projection("FUNDING_PENDING")
    cached["last_seq"] = 4
    app, store, client, _ = build(cached=cached)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://buyer"
    ) as http:
        response = await http.get(
            "/internal/runs/run-1/settlement?refresh=true",
            headers={"x-verifund-agent-token": "agent-internal"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["projection"]["state"] == "FUNDED"
    assert client.calls[-1] == ("state", "vf_1", "console:reviewer")
    assert store.saved[-1]["state"] == "FUNDED"


async def test_get_settlement_records_one_trace_event_per_advance():
    cached = projection("FUNDED")
    cached["last_seq"] = 4
    app, _, _, _ = build(cached=cached)
    trace = app.state.services.trace
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://buyer"
    ) as http:
        first = await http.get(
            "/api/runs/run-1/settlement", headers=CONSOLE
        )
        assert first.status_code == 200
        assert len(trace.events) == 1
        assert trace.events[0]["method"] == "settlement_status"
        assert trace.events[0]["payload"]["last_seq"] == 5

        second = await http.get(
            "/api/runs/run-1/settlement", headers=CONSOLE
        )
        assert second.status_code == 200
        assert len(trace.events) == 1


async def test_get_settlement_falls_back_to_the_cached_projection():
    client = Client()
    client.fail_state = True
    app, _, _, _ = build(cached=projection("VERIFICATION_PENDING"), client=client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://buyer"
    ) as http:
        response = await http.get(
            "/api/runs/run-1/settlement", headers=CONSOLE
        )
    assert response.status_code == 200
    assert response.json()["state"] == "VERIFICATION_PENDING"
    assert response.json()["settlement_unavailable"] is True


async def test_release_uses_the_reviewer_actor_and_resumes_the_graph(api):
    http, _, store, client, graph = api
    response = await http.post(
        "/api/runs/run-1/settlement/release",
        headers=CONSOLE,
        json={"released_by": "demo-reviewer", "note": "docs verified"},
    )
    assert response.status_code == 200, response.text
    call = client.calls[-1]
    assert call[0] == "release"
    assert call[2].released_by == "demo-reviewer"
    assert call[3] == "console:reviewer"
    assert response.json()["settlement"]["state"] == "PAYOUT_PENDING"
    assert graph.resumed
    assert store.saved[-1]["state"] == "PAYOUT_PENDING"


async def test_review_supports_flag_and_retry(api):
    http, _, _, client, _ = api
    flagged = await http.post(
        "/api/runs/run-1/settlement/review",
        headers=CONSOLE,
        json={"action": "flag_review", "reason": "tracking_mismatch", "note": "check"},
    )
    assert flagged.status_code == 200
    assert client.calls[-1][0] == "flag_review"
    assert client.calls[-1][2].reason == "tracking_mismatch"

    retried = await http.post(
        "/api/runs/run-1/settlement/review",
        headers=CONSOLE,
        json={"action": "retry_payout"},
    )
    assert retried.status_code == 200
    assert client.calls[-1] == ("retry_payout", "vf_1", "console:reviewer")
    assert retried.json()["settlement"]["state"] == "RELEASED"


async def test_get_run_includes_settlement_only_with_a_valid_console_token(api):
    http, *_ = api
    without = await http.get("/api/runs/run-1")
    assert without.status_code == 401

    with_token = await http.get("/api/runs/run-1", headers=CONSOLE)
    assert with_token.status_code == 200
    assert with_token.json()["settlement"]["transaction_id"] == "vf_1"


async def test_receipt_and_evidence_proxy_the_control_plane(api):
    http, _, _, client, _ = api
    receipt = await http.get(
        "/api/runs/run-1/settlement/receipt", headers=CONSOLE
    )
    assert receipt.status_code == 200
    assert receipt.json()["verified"] is True

    evidence = await http.get(
        "/api/runs/run-1/settlement/evidence/ev_1", headers=CONSOLE
    )
    assert evidence.status_code == 200
    assert evidence.content == b"manifest"
    assert "manifest.txt" in evidence.headers["content-disposition"]
    assert client.calls[-1] == ("evidence", "vf_1", "ev_1", "console:reviewer")


async def test_internal_seller_token_endpoint_validates_binding(api):
    http, *_ = api
    body = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "seller_id": "northwind-audio",
        "purpose": "purchase_order",
    }
    refused = await http.post("/internal/settlement/seller-token", json=body)
    assert refused.status_code == 401

    headers = {"x-marketmesh-internal-token": "internal-token"}
    wrong_run = await http.post(
        "/internal/settlement/seller-token",
        headers=headers,
        json={**body, "run_id": "run-2"},
    )
    assert wrong_run.status_code == 403

    response = await http.post(
        "/internal/settlement/seller-token", headers=headers, json=body
    )
    assert response.status_code == 200
    assert response.json() == {
        "seller_token": "v1.secret",
        "expires_at": "2099-10-30T12:00:00Z",
    }


async def test_advance_returns_409_without_a_pending_interrupt():
    app, _, _, _ = build(cached=projection(), paused=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://buyer"
    ) as http:
        response = await http.post(
            "/api/runs/run-1/settlement/advance",
            headers=CONSOLE,
            json={"action": "refresh"},
        )
    assert response.status_code == 409


class ExpiredAgreements:
    async def create_agreement(self, run_id, request):
        raise VerifundError(
            "offer_expired",
            "offer has expired",
            status_code=409,
            retryable=False,
        )


async def test_internal_agreement_create_preserves_the_domain_error():
    app, *_ = build(cached=projection())
    app.state.services.agreements = ExpiredAgreements()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://buyer"
    ) as http:
        response = await http.post(
            "/internal/runs/run-1/settlement/agreement",
            headers={"x-verifund-agent-token": "agent-internal"},
            json={
                "award": award_payload(),
                "buyer_task_id": "buyer-task-1",
                "buyer_context_id": "run-1",
                "idempotency_key": "agreement:run-1:offer-1",
            },
        )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "offer_expired"
    assert detail["retryable"] is False
