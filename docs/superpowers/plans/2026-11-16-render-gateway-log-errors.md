# Render Gateway Log Errors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two errors in the Render gateway logs — the `ValueError: 'outside_mandate' is not a valid RejectReason` that aborts buyer runs, and the `registry poll failed: 502 Bad Gateway` that fires on every instance restart.

**Architecture:** A seller that will not auto-accept returns `OPERATOR_REQUIRED` with a free-form reason code (`outside_mandate`, `auto_accept_disabled`). The buyer forwarded that string straight into the `RejectReason` enum, which raised and killed the whole buyer run. The fix is a shared coercion helper plus a branch in the buyer graph that escalates instead of rejecting. Separately, the buyer polled the registry over its own public URL inside the ASGI lifespan, before uvicorn had bound the socket, so Render's edge answered 502; the fix moves the poll into a background poller that retries until the registry actually answers.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, SQLAlchemy (async), httpx, respx, pytest (`asyncio_mode = "auto"`).

**Spec:** This plan is derived from the root-cause analysis in `docs/superpowers/plans/2026-11-16-render-gateway-log-errors.md` (this file) against the design intent recorded in `docs/workflow.md:183-209` and `docs/superpowers/specs/2026-10-30-verifund-agreement-management-design.md:149,394`.

## Global Constraints

- Backend code lands on the **`deploy/render`** branch. The console needs no code change for these fixes — it already carries the `seller_operator_required` label (`apps/console/features/chat/verifund-tools.tsx:162`) and renders an arbitrary `sellerDecision` record (`apps/console/features/agreements/AgreementSummary.tsx:58`). **No console change is in this plan.**
- `RejectReason` (`packages/verifund_contracts/verifund_contracts/models.py:82`) is a closed five-value enum. The control plane's `RejectRequest.reason_code` is typed `RejectReason`, so an unknown code can never be forwarded — it must be mapped.
- `docs/workflow.md:190`: "`OPERATOR_REQUIRED` keeps the agreement in `PENDING_SELLER` for a human seller operator." A seller escalation must never reject the agreement.
- `VerifundModel` is `extra="forbid"` (`packages/verifund_contracts/verifund_contracts/models.py:13-14`). Request bodies sent to the control plane must match the model exactly.
- The control plane requires an `Idempotency-Key` **header** (`apps/verifund_control_plane/verifund_control_plane/agreements/routes.py:216`) and an `X-Seller-Token` **header** (`:214`).
- Line length 100, target `py312` (`pyproject.toml` `[tool.ruff]`).
- Test command: `uv run pytest`. Lint: `uv run ruff check .`.

## Out of Scope

The instance restarts (SIGKILL with no traceback, `/health` passing right up to the kill) are most likely an OOM: all six sub-apps share one 512 MB Render free container, each with its own default SQLAlchemy pool. This plan does **not** change that architecture. It is recorded here as the open hypothesis. See "Open Hypothesis" at the end.

---

### Task 1: Coerce an unknown reject reason instead of raising

The crash is `settlement_client.py:268` doing `RejectReason(reason_code)` with a caller-supplied string. A shared helper in the contracts package makes the coercion total.

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/models.py:82-87`
- Modify: `apps/buyer_agent/buyer_agent/settlement_client.py:252-274`
- Modify: `apps/buyer_agent/buyer_agent/settlement_flow.py:560-566`
- Test: `tests/unit/test_verifund_contracts.py`
- Test: `tests/unit/test_buyer_settlement_client.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `verifund_contracts.coerce_reject_reason(value: object, *, default: RejectReason = RejectReason.OTHER) -> RejectReason`. Exported by `from verifund_contracts.models import *` (`packages/verifund_contracts/verifund_contracts/__init__.py:3`).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_verifund_contracts.py`:

```python
from verifund_contracts import RejectReason, coerce_reject_reason


def test_coerce_reject_reason_maps_a_known_code():
    assert coerce_reject_reason("out_of_stock") is RejectReason.OUT_OF_STOCK


def test_coerce_reject_reason_maps_an_unknown_seller_code_to_other():
    assert coerce_reject_reason("outside_mandate") is RejectReason.OTHER
    assert coerce_reject_reason("auto_accept_disabled") is RejectReason.OTHER
    assert coerce_reject_reason("version_provenance_failed") is RejectReason.OTHER


def test_coerce_reject_reason_maps_a_missing_code_to_the_default():
    assert coerce_reject_reason(None) is RejectReason.OTHER
    assert coerce_reject_reason("  ") is RejectReason.OTHER
    assert coerce_reject_reason(None, default=RejectReason.TERMS_MISMATCH) is (
        RejectReason.TERMS_MISMATCH
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -k coerce_reject_reason`
Expected: FAIL — `ImportError: cannot import name 'coerce_reject_reason' from 'verifund_contracts'`

- [ ] **Step 3: Write the implementation**

In `packages/verifund_contracts/verifund_contracts/models.py`, immediately after the `RejectReason` class (after line 87):

```python
def coerce_reject_reason(
    value: object, *, default: RejectReason = RejectReason.OTHER
) -> RejectReason:
    """Map a free-form rejection reason onto a known ``RejectReason``.

    Sellers report their own reason codes (``outside_mandate``,
    ``auto_accept_disabled``, ``version_provenance_failed``) and the control
    plane only accepts the codes in ``RejectReason``. An unknown code must
    never raise: it degrades to ``default``.
    """
    if isinstance(value, RejectReason):
        return value
    raw = str(value).strip() if value is not None else ""
    if not raw:
        return default
    try:
        return RejectReason(raw)
    except ValueError:
        return default
```

In `apps/buyer_agent/buyer_agent/settlement_client.py`, change the `reject` method's body (line 268) from:

```python
                reason_code=RejectReason(reason_code),
```

to:

```python
                reason_code=coerce_reject_reason(reason_code),
```

and add `coerce_reject_reason` to the existing `from verifund_contracts import (...)` block at the top of the file.

In `apps/buyer_agent/buyer_agent/settlement_flow.py`, replace `_reject_reason` (lines 560-566) with:

```python
def _reject_reason(error: dict[str, Any] | None) -> RejectReason:
    details = (error or {}).get("details") or {}
    raw = details.get("reason_code") or (error or {}).get("reason_code")
    if not raw:
        return RejectReason.TERMS_MISMATCH
    return coerce_reject_reason(raw)
```

and add `coerce_reject_reason` to that module's `verifund_contracts` import.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -k coerce_reject_reason`
Expected: PASS (3 passed)

- [ ] **Step 5: Add the client-level regression test**

Add to `tests/unit/test_buyer_settlement_client.py`:

```python
@respx.mock
async def test_reject_maps_an_unknown_seller_reason_code_to_other():
    route = respx.post("http://control/transactions/vf_1/reject").mock(
        return_value=Response(200, json={"state": "CANCELED"})
    )
    client = BuyerSettlementClient(
        "http://control", ops_token="ops-token", actor="buyer-agent"
    )
    await client.reject(
        "vf_1",
        seller_id="northwind-audio",
        agreement_hash="a" * 64,
        reason_code="outside_mandate",
        note="Outside the seller mandate.",
        seller_task_id="seller-task-1",
        rejected_at="2026-10-27T12:00:00Z",
    )
    assert route.calls[0].request.content is not None
    assert b'"reason_code":"other"' in route.calls[0].request.content
```

If the reject endpoint is not `POST /transactions/{id}/reject`, read
`packages/verifund_contracts/verifund_contracts/client.py` `reject()` and use the URL it actually calls.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_buyer_settlement_client.py tests/unit/test_verifund_contracts.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add packages/verifund_contracts/verifund_contracts/models.py \
  apps/buyer_agent/buyer_agent/settlement_client.py \
  apps/buyer_agent/buyer_agent/settlement_flow.py \
  tests/unit/test_verifund_contracts.py \
  tests/unit/test_buyer_settlement_client.py
git commit -m "fix(buyer): coerce an unknown seller reject reason instead of raising

A seller that will not auto-accept returns OPERATOR_REQUIRED with its own
free-form reason code (outside_mandate, auto_accept_disabled). The buyer
forwarded that string straight into the RejectReason enum, which raised
ValueError and aborted the whole buyer run.

Add coerce_reject_reason() to the contracts package and use it on both
paths that reject an agreement, so an unknown code degrades to 'other'."
```

---

### Task 2: Escalate a seller decision instead of rejecting the agreement

`report_seller_review` (`apps/buyer_agent/buyer_agent/graph.py:1345`) treats every non-`ACCEPTED` decision as a rejection. `OPERATOR_REQUIRED` and `CHANGES_REQUESTED` are not rejections: per `docs/workflow.md:190` the agreement stays `PENDING_SELLER` for a human.

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/graph.py:1345-1399`
- Modify: `apps/buyer_agent/buyer_agent/agreement_service.py:196-239`
- Test: `tests/unit/test_buyer_seller_review.py` (new)

**Interfaces:**
- Consumes: `coerce_reject_reason` from Task 1.
- Produces: `report_seller_review` returns `stage` of `"agreed"`, `"rejected"`, `"operator_required"`, or `"changes_requested"`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_buyer_seller_review.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from buyer_agent.graph import report_seller_review

BASE_DECISION = {
    "party": "seller",
    "status": "OPERATOR_REQUIRED",
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


class Store:
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self.settlement = self

    async def save_agreement(self, run_id, agreement):
        self.saved.append({"run_id": run_id, "agreement": agreement})


def services() -> SimpleNamespace:
    settlement = Settlement()
    agreements = Agreements()
    store = Store()
    return SimpleNamespace(
        settlement=settlement,
        agreements=agreements,
        store=SimpleNamespace(settlement=store),
        _settlement=settlement,
        _agreements=agreements,
    )


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


async def test_operator_required_does_not_reject_the_agreement():
    value = services()
    result = await report_seller_review(state("OPERATOR_REQUIRED"), {"configurable": {}})
    assert value._settlement.rejects == []
    assert result["stage"] == "operator_required"


async def test_changes_requested_does_not_reject_the_agreement():
    value = services()
    result = await report_seller_review(state("CHANGES_REQUESTED"), {"configurable": {}})
    assert value._settlement.rejects == []
    assert result["stage"] == "changes_requested"


async def test_operator_required_records_the_seller_decision():
    value = services()
    await report_seller_review(state("OPERATOR_REQUIRED"), {"configurable": {}})
    assert len(value._agreements.decisions) == 1
    assert value._agreements.decisions[0]["agreement_id"] == "agr-1"


async def test_rejected_still_rejects_with_a_coerced_reason_code():
    value = services()
    result = await report_seller_review(
        state("REJECTED", "outside_mandate"), {"configurable": {}}
    )
    assert len(value._settlement.rejects) == 1
    assert value._settlement.rejects[0]["reason_code"] == "other"
    assert result["stage"] == "rejected"


async def test_accepted_still_accepts():
    value = services()
    result = await report_seller_review(state("ACCEPTED"), {"configurable": {}})
    assert len(value._settlement.accepts) == 1
    assert value._settlement.rejects == []
    assert result["stage"] == "agreed"
```

If `report_seller_review` reads its services from a different place than
`config["configurable"]`, read `_services(config)` at
`apps/buyer_agent/buyer_agent/graph.py` and shape the test's `config` dict
and the `SimpleNamespace` to match it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_buyer_seller_review.py`
Expected: FAIL — `test_operator_required_does_not_reject_the_agreement` fails because `settlement.reject` was called.

- [ ] **Step 3: Write the implementation**

In `apps/buyer_agent/buyer_agent/graph.py`, replace the body of `report_seller_review` (lines 1345-1399) with:

```python
async def report_seller_review(state: BuyerState, config: dict) -> dict:
    services = _services(config)
    settlement = state.get("settlement") or {}
    run_id = str(state.get("run_id") or "")
    decision = AgreementReviewResult.model_validate(
        state.get("seller_decision") or {}
    )
    agreement = settlement.get("agreement") or {}
    status = decision.status
    if status == AgreementReviewDecision.ACCEPTED:
        projection = await services.settlement.accept(
            str(settlement.get("transaction_id") or ""),
            seller_id=str(agreement["seller_id"]),
            agreement_hash=str(agreement["agreement_hash"]),
            accepted_total_cents=int(agreement["amount_cents"]),
            seller_task_id=str(decision.task_id),
            accepted_at=decision.reviewed_at.isoformat().replace("+00:00", "Z"),
        )
        stage = "agreed"
        agreement_status = "PENDING_BUYER"
    elif status == AgreementReviewDecision.REJECTED:
        projection = await services.settlement.reject(
            str(settlement.get("transaction_id") or ""),
            seller_id=str(agreement["seller_id"]),
            agreement_hash=str(agreement["agreement_hash"]),
            reason_code=coerce_reject_reason(decision.reason_code).value,
            note=str(decision.note or ""),
            seller_task_id=str(decision.task_id),
            rejected_at=decision.reviewed_at.isoformat().replace("+00:00", "Z"),
        )
        stage = "rejected"
        agreement_status = "REJECTED"
    else:
        # OPERATOR_REQUIRED and CHANGES_REQUESTED are escalations, not
        # rejections: the agreement stays PENDING_SELLER for a human. The
        # control plane records the flag and keeps the agreement open, so
        # rejecting here would cancel a transaction the seller only asked to
        # escalate.
        projection = {}
        stage = (
            "operator_required"
            if status == AgreementReviewDecision.OPERATOR_REQUIRED
            else "changes_requested"
        )
        agreement_status = None
        await _record_escalated_decision(
            services, str(agreement.get("agreement_id") or ""), decision, run_id
        )
    updated = {
        **settlement,
        "state": projection.get("state") or settlement.get("state"),
        "funding_state": projection.get("state") or settlement.get("funding_state"),
    }
    # Keep the buyer's cached agreement in sync with the control plane so the
    # Verifund agent's sync_agreement reads the post-review status instead of
    # the stale PENDING_SELLER value captured at agreement creation.
    agreement_dict = settlement.get("agreement")
    if isinstance(agreement_dict, dict) and agreement_status:
        with contextlib.suppress(Exception):
            await services.store.settlement.save_agreement(
                run_id,
                {**agreement_dict, "status": agreement_status},
            )
    await _upsert(services, run_id, stage=stage)
    return {
        "seller_decision": decision.model_dump(mode="json"),
        "settlement": updated,
        "stage": stage,
    }
```

Add the helper above `report_seller_review`:

```python
async def _record_escalated_decision(
    services: Any, agreement_id: str, decision: Any, run_id: str
) -> None:
    """Record an escalated seller decision on the control plane.

    Best effort: the escalation is already visible to the operator through
    the Verifund agent, so a failure here must not abort the buyer run.
    """
    if not agreement_id:
        return
    agreements = getattr(services, "agreements", None)
    if agreements is None:
        return
    try:
        await agreements.record_seller_decision(agreement_id, decision)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "could not record the escalated seller decision for %s: %s",
            agreement_id,
            exc,
        )
```

Add `coerce_reject_reason` to the module's `verifund_contracts` import, and make sure `logging` is imported at module level (add it if it is not).

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_buyer_seller_review.py`
Expected: PASS (5 passed)

- [ ] **Step 5: Fix the seller-decision payload the escalation depends on**

`apps/buyer_agent/buyer_agent/agreement_service.py:220-239` builds a body that the control plane rejects: it sends `verified_offer_hash` where `SellerAgreementDecisionRequest` expects `offer_hash`, it puts `idempotency_key` in the body instead of the header, and it omits `actor_id`. `VerifundModel` is `extra="forbid"`, so the request fails validation.

Replace the payload construction (lines 220-239) with:

```python
    payload = {
        "agreement_version": getattr(result, "agreement_version", None),
        "agreement_hash": getattr(result, "agreement_hash", None),
        "decision": status_map.get(status_value, status_value),
        "actor_type": getattr(result, "actor_type", "SELLER_AGENT"),
        "actor_id": getattr(result, "actor_id", None)
        or getattr(result, "seller_id", None)
        or "seller-agent",
        "authority_ref": getattr(result, "authority_ref", None),
        "authority_snapshot": getattr(result, "authority_snapshot", {}) or {},
        "offer_hash": getattr(result, "offer_hash", None),
        "verified_change_request_id": getattr(
            result, "verified_change_request_id", None
        ),
        "note": getattr(result, "note", "") or "",
    }
    return await self.client.record_seller_decision(
        agreement_id,
        payload,
        seller_token=seller_token,
        idempotency_key=f"seller-decision:{agreement_id}:"
        f"{getattr(result, 'agreement_version', 0)}",
    )
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_buyer_seller_review.py tests/unit/test_buyer_settlement_client.py tests/unit/test_buyer_settlement_flow.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/buyer_agent/buyer_agent/graph.py \
  apps/buyer_agent/buyer_agent/agreement_service.py \
  tests/unit/test_buyer_seller_review.py
git commit -m "fix(buyer): escalate a seller decision instead of rejecting it

OPERATOR_REQUIRED and CHANGES_REQUESTED mean the agreement stays
PENDING_SELLER for a human; the buyer treated both as a rejection. For a
seller escalation that meant rejecting the agreement and cancelling the
transaction the seller only asked to escalate.

Branch on the seller decision status, record an escalated decision on the
control plane on a best-effort basis, and fix the seller-decision payload
the control plane was rejecting on field names and the idempotency header."
```

---

### Task 3: Keep the escalated decision in the orchestrator's view

The orchestrator drops any seller decision that is not `ACCEPTED` or `REJECTED`, so the console is handed `seller_decision: null` for an escalation and cannot show the operator what was asked.

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/verifund.py:87-102`
- Test: `tests/unit/test_orchestrator_verifund.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_review_summary(value) -> dict | None` now returns a summary for `OPERATOR_REQUIRED` and `CHANGES_REQUESTED`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_orchestrator_verifund.py`:

```python
def test_review_summary_keeps_an_escalated_seller_decision():
    from orchestrator_agent.verifund import _review_summary

    summary = _review_summary(
        {
            "status": "OPERATOR_REQUIRED",
            "agreement_version": 1,
            "agreement_hash": "a" * 64,
        }
    )
    assert summary is not None
    assert summary["status"] == "OPERATOR_REQUIRED"


def test_review_summary_drops_an_unknown_seller_decision():
    from orchestrator_agent.verifund import _review_summary

    assert _review_summary({"status": "NOT_A_DECISION"}) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_orchestrator_verifund.py -k review_summary`
Expected: FAIL — `summary` is `None` for `OPERATOR_REQUIRED`.

- [ ] **Step 3: Write the implementation**

In `apps/orchestrator_agent/orchestrator_agent/verifund.py`, change `_review_summary` (lines 92-96) to:

```python
    status = value.get("status")
    if status not in {
        AgreementReviewDecision.ACCEPTED.value,
        AgreementReviewDecision.REJECTED.value,
        AgreementReviewDecision.OPERATOR_REQUIRED.value,
        AgreementReviewDecision.CHANGES_REQUESTED.value,
    }:
        return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_orchestrator_verifund.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/verifund.py \
  tests/unit/test_orchestrator_verifund.py
git commit -m "fix(orchestrator): keep an escalated seller decision in the view

_review_summary returned None for anything but ACCEPTED and REJECTED, so
an operator escalation reached the console with seller_decision: null and
the operator could not see what was asked."
```

---

### Task 4: Poll the registry only once the registry can answer

The buyer polls `https://gateway-795m.onrender.com/registry/v1/sellers` — its own public URL — from inside the ASGI lifespan, before uvicorn binds the socket. Render's edge answers 502 and the poll fails. The poll also blocks startup.

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/registry_client.py:147-179`
- Modify: `apps/buyer_agent/buyer_agent/server.py:49-76`
- Test: `tests/unit/test_registry_client.py`
- Test: `tests/unit/test_buyer_registry_poller.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `RegistryClient.refresh_registry() -> bool` — polls once, returns whether the registry answered, does not log.
- Produces: `RegistryClient.poll_registry() -> dict[str, SellerEndpoint]` — unchanged public behaviour (logs the failure, returns the endpoint map).
- Produces: `run_registry_poller(registry_client, *, poll_interval, sleep=asyncio.sleep) -> None` in `apps/buyer_agent/buyer_agent/server.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_registry_client.py`:

```python
async def test_refresh_registry_reports_whether_the_registry_answered():
    registry = RegistryClient(
        registry_url="http://registry.test",
        allowed_card_hosts=("127.0.0.1",),
        client=httpx.AsyncClient(),
    )
    try:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://registry.test/v1/sellers").mock(
                return_value=httpx.Response(502)
            )
            assert await registry.refresh_registry() is False
            mock.get("http://registry.test/v1/sellers").mock(
                return_value=httpx.Response(200, json={"sellers": []})
            )
            assert await registry.refresh_registry() is True
    finally:
        await registry.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_registry_client.py -k refresh_registry`
Expected: FAIL — `AttributeError: 'RegistryClient' object has no attribute 'refresh_registry'`

- [ ] **Step 3: Write the implementation**

In `apps/buyer_agent/buyer_agent/registry_client.py`, replace `poll_registry` (lines 147-179) with:

```python
    async def poll_registry(self) -> dict[str, SellerEndpoint]:
        """Fetch GET /v1/sellers, validate cards, atomically swap _endpoints.

        On registry failure (HTTP error, bad JSON) keep the last known map.
        """
        import logging
        if not await self.refresh_registry():
            logging.getLogger(__name__).warning(
                "registry poll failed: %s", self.last_error
            )
        return self._endpoints

    async def refresh_registry(self) -> bool:
        """Poll the registry once and report whether it answered.

        Returns True when the registry answered (even if some seller cards
        failed to validate) and False when the poll failed, in which case the
        last known endpoint map is kept. Unlike ``poll_registry`` this does
        not log: a caller that retries on a schedule decides how loudly a
        failure is worth.
        """
        import logging
        try:
            response = await self.http.get(f"{self.registry_url}/v1/sellers")
            response.raise_for_status()
            entries = response.json().get("sellers", [])
        except (httpx.HTTPError, ValueError) as exc:
            self.last_error = exc
            return False
        new_endpoints: dict[str, SellerEndpoint] = {}
        for entry in entries:
            seller_id, card_url = entry["seller_id"], entry["card_url"]
            self.fetch_calls += 1
            fetched = await self._fetch_valid_card(seller_id, card_url)
            if fetched is None:
                continue
            resolved_card_url, card = fetched
            token = self._token_cache.get(seller_id) or await self._exchange_token(seller_id)
            if not token:
                continue
            metadata = card_commerce_metadata(card)
            new_endpoints[seller_id] = SellerEndpoint(
                seller_id=seller_id, name=card.name, card_url=resolved_card_url, card=card,
                token=token, rating=float(metadata["rating"]),
                sustainability_certified=bool(metadata["sustainability_certified"]),
            )
        self._token_cache = {k: v for k, v in self._token_cache.items() if k in new_endpoints}
        self._endpoints = new_endpoints
        self.last_error = None
        return True
```

Add `self.last_error: Exception | None = None` to `__init__` (after line 68).

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_registry_client.py`
Expected: PASS

- [ ] **Step 5: Write the failing poller test**

Create `tests/unit/test_buyer_registry_poller.py`:

```python
from __future__ import annotations

from buyer_agent.server import run_registry_poller


class Registry:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def refresh_registry(self) -> bool:
        self.calls += 1
        if self.calls <= self.failures:
            return False
        return True


async def test_poller_retries_until_the_registry_answers():
    registry = Registry(failures=2)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) > 4:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_registry_poller(registry, poll_interval=30.0, sleep=sleep)
    assert registry.calls == 3
    assert slept[:2] == [1.0, 2.0]


async def test_poller_settles_into_the_poll_interval_once_answered():
    registry = Registry(failures=0)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) > 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_registry_poller(registry, poll_interval=30.0, sleep=sleep)
    assert slept == [30.0, 30.0]
```

Add `import asyncio` and `import pytest` to the top of the file.

- [ ] **Step 6: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_buyer_registry_poller.py`
Expected: FAIL — `ImportError: cannot import name 'run_registry_poller'`

- [ ] **Step 7: Write the implementation**

In `apps/buyer_agent/buyer_agent/server.py`, add at module level (after the imports):

```python
async def run_registry_poller(
    registry_client: Any,
    *,
    poll_interval: float,
    sleep: Any = asyncio.sleep,
) -> None:
    """Poll the registry until it answers, then on the normal cadence.

    The registry is served by this same process, so its socket is not bound
    until the ASGI startup completes: the first poll cannot land and the
    edge answers 502. Retry on a short backoff until the registry answers
    instead of failing the poll outright.
    """
    logger = logging.getLogger(__name__)
    delay = 1.0
    failures = 0
    while True:
        if await registry_client.refresh_registry():
            failures = 0
            delay = 1.0
            await sleep(poll_interval)
            continue
        failures += 1
        if failures >= 3:
            logger.warning("registry poll failed %d times in a row", failures)
        else:
            logger.info("registry not reachable yet; retrying in %.1fs", delay)
        await sleep(delay)
        delay = min(delay * 2, poll_interval)
```

Then replace the registry block in the lifespan (lines 57-68 of `server.py`) with:

```python
            registry_client = getattr(services, "registry", None)
            if registry_client is not None:
                poll_interval = getattr(settings, "buyer_registry_poll_seconds", 30)
                poll_task = asyncio.create_task(
                    run_registry_poller(
                        registry_client,
                        poll_interval=poll_interval,
                    )
                )
```

Remove the blocking `await registry_client.poll_registry()` so the app starts serving immediately. Add `import asyncio`, `import logging` and `Any` to the imports if they are missing.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_buyer_registry_poller.py tests/unit/test_registry_client.py`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add apps/buyer_agent/buyer_agent/registry_client.py \
  apps/buyer_agent/buyer_agent/server.py \
  tests/unit/test_registry_client.py \
  tests/unit/test_buyer_registry_poller.py
git commit -m "fix(buyer): poll the registry once it can answer

The buyer polled its own public registry URL from inside the ASGI
lifespan, before uvicorn had bound the socket, so Render's edge answered
502 on every instance restart and the poll blocked startup.

Move the poll into a background poller that retries with a short backoff
until the registry actually answers, then settles into the normal cadence."
```

---

### Task 5: Align `render.yaml` with the live deployment

`render.yaml` no longer describes the running service. The service is not blueprint-managed (`blueprintId` is `null`), so the file is only used when a service is created from it — and it would create a broken one.

Differences against the live environment (`GET /v1/services/srv-dbqvs2ifngtc73eft8b0/env-vars`):

| Key | `render.yaml` | Live |
|---|---|---|
| host in every `*_URL` | `https://gateway.onrender.com` (404) | `https://gateway-795m.onrender.com` |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.us-central1.nebius.com/v1/` | `https://api.tokenfactory.eu-north1.nebius.com/v1/` |
| `NEBIUS_MODEL` | `deepseek-ai/DeepSeek-V4-Flash-0731` | `MiniMaxAI/MiniMax-M3` |
| `BUYER_LLM_MODEL` | absent | `MiniMaxAI/MiniMax-M3` |
| `BUYER_A2A_URL` | absent | `https://gateway-795m.onrender.com/buyer` |
| `VERIFUND_AGENT_CARD_URL` | absent | `https://gateway-795m.onrender.com/verifund-agent/.well-known/agent-card.json` |
| `VERIFUND_CONSOLE_BASE_URL` | absent | `https://verifund-console.vercel.app` |
| `ALLOWED_CARD_HOSTS` | `["gateway.onrender.com", ...]` | `["gateway-795m.onrender.com", ...]` |
| `*_CHECKPOINT_URL` | absent | the Postgres checkpoint URLs |

**Files:**
- Modify: `render.yaml`

- [ ] **Step 1: Update the file**

Replace every `https://gateway.onrender.com` with `https://gateway-795m.onrender.com`. Set `NEBIUS_BASE_URL` to `https://api.tokenfactory.eu-north1.nebius.com/v1/`. Set `NEBIUS_MODEL` and `BUYER_LLM_MODEL` to `MiniMaxAI/MiniMax-M3`. Set `ALLOWED_CARD_HOSTS` to `["gateway-795m.onrender.com", "127.0.0.1", "localhost"]`. Add `BUYER_A2A_URL`, `VERIFUND_AGENT_CARD_URL` and `VERIFUND_CONSOLE_BASE_URL` with the live values, and add the `*_CHECKPOINT_URL` keys with `sync: false`.

- [ ] **Step 2: Verify the file still parses and points at the live host**

Run:

```bash
uv run python -c "import yaml,sys; d=yaml.safe_load(open('render.yaml')); print(d['services'][0]['name'])"
```

Expected: prints `gateway`

Run:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://gateway-795m.onrender.com/health
```

Expected: `200`

- [ ] **Step 3: Commit**

```bash
git add render.yaml
git commit -m "fix(deploy): align render.yaml with the live gateway

The file still described the pre-rename host (gateway.onrender.com now
404s), the old Nebius endpoint and model, and none of the Postgres
checkpoint URLs the service actually uses. Creating a service from it
would have produced a gateway that could not reach the registry, the
control plane or its checkpoints."
```

---

## Final Verification

- [ ] Run the whole backend suite: `uv run pytest` — expect no failures.
- [ ] Run the linter: `uv run ruff check .` — expect no findings.
- [ ] Confirm the branch: `git branch --show-current` is `deploy/render`.
- [ ] Confirm the pre-existing uncommitted `.scratchpad/verifund-multi-tenancy-todos.md` deletion was NOT committed: `git show --stat HEAD~4..HEAD` must not list it.
- [ ] Push: `git push origin deploy/render`.

## Open Hypothesis (not fixed here)

The instance restarts (SIGKILL, no Python traceback, `/health` returning 200 right up to the kill, no deploy in flight) are most likely an OOM kill: six sub-apps share one 512 MB Render free container and each opens its own default SQLAlchemy pool against the `marketmesh` Postgres. Confirming this needs either an interactive `render ssh` into the live instance to read `/sys/fs/cgroup/memory.events`, or splitting the gateway into one Render service per sub-app. Both were deliberately left out of this plan.

## Execution Notes

What actually differed from the plan above, and why.

1. **`AgreementReviewDecision` values are lowercase.** The enum members are `ACCEPTED`/`REJECTED`/`OPERATOR_REQUIRED`/`CHANGES_REQUESTED` but their *values* are `accepted`/`rejected`/`operator_required`/`changes_requested`. The plan's test fixtures used the member names; the wire format is the lowercase value.
2. **The seller-decision body needed more than a field rename.** Beyond `verified_offer_hash` → `offer_hash`, the body also carried `task_id`, `context_id` and `idempotency_key`, which `SellerAgreementDecisionRequest` forbids (`extra="forbid"`). The idempotency key belongs in the `Idempotency-Key` header the route reads, so it was moved there. Five validation errors, all fixed.
3. **A sixth commit was needed: refresh the cached agreement.** The Verifund agent routes to the seller operator on the `seller_operator_required` flag the control plane sets (`apps/verifund_agent/verifund_agent/graph.py:206`). The buyer's cached agreement never carried it, so after recording an escalation the agent looped back to awaiting a seller review it already had. The buyer now refreshes its cached agreement from the control plane after recording the decision.
4. **Two pre-existing lint errors were fixed** in `tests/unit/test_registry_client.py` (unsorted imports, unused `pytest` import) because that file was already being modified. Repo lint is otherwise unchanged at 122 pre-existing errors, none in the files this plan touches.
5. **The poller test expectations were corrected.** The first draft asserted a call/sleep sequence that did not match the backoff the implementation actually produces; the implementation was right and the expectations were wrong. The corrected tests assert the backoff (`1.0`, `2.0`, …) and the settled cadence (`30.0`).
6. **`render.yaml` was verified against the live service programmatically**, not by eye: every one of the 34 live service env vars is covered by the blueprint and every value the blueprint pins matches the live value.

### Commits (all on `deploy/render`)

```
50b8df5 fix(buyer): coerce an unknown seller reject reason instead of raising
ebf9c0a fix(buyer): escalate a seller decision instead of rejecting it
b7f5a4c fix(orchestrator): keep an escalated seller decision in the view
e69ad63 fix(buyer): poll the registry once it can answer
97fd378 fix(deploy): align render.yaml with the live gateway
e286fee fix(buyer): carry the operator flag into the cached agreement
```
