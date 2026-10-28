# Verifund Transaction Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone Verifund transaction-control subsystem and a separately registered Verifund A2A agent that assembles an agreement from the Buyer award, coordinates Buyer-agent and Seller-agent approval through the orchestrator, then leads funding, evidence review, payout approval, and receipt delivery in CopilotKit chat. Preserve the existing `VERIFUND_MODE=off` demo unchanged.

**Architecture:** A new FastAPI control plane (`apps/verifund_control_plane`, port `9300`) owns agreement versions/hashes, transaction state, the held-funds ledger, evidence, PayPal calls, webhooks, payout, receipts, and audit. A separate Verifund A2A service (`apps/verifund_agent`, port `9301`) assembles the agreement from the exact Buyer award and calls authenticated buyer settlement APIs; it never receives the control-plane ops token or PayPal credentials. The orchestrator coordinates sequential A2A reviews: Buyer validates the terms against its award/mandate, then Seller accepts or rejects the same version/hash. It resumes the original Buyer task with each exact result; Buyer records its review and Seller decision through its own control-plane client. Agent assent is distinct from the human's funding HITL. The registry gains generic-agent discovery without changing seller catalog discovery. The Transaction Room remains a synchronized detail view.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2 (`extra="forbid"`), SQLAlchemy async + aiosqlite, httpx, LangGraph 1.x, PayPal Sandbox Orders v2 / Payments v1 Payouts / webhook verification, Next.js 15 + React 19 + TanStack Query + Vitest + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-27-verifund-control-plane-design.md`

## Global Constraints

- `VERIFUND_MODE` is `off`, `fake`, or `sandbox`; the default is `off`. `off` must keep every existing test, demo, and graph edge unchanged.
- No runtime import, call, dependency, schema copy, or file reference to `verifund-platform-backend`. The new subsystem is independent.
- Control-plane routes are unprefixed (`GET /transactions/{id}/state`). Only PayPal's own REST paths contain `/v1`.
- All money is integer USD cents. No floats in money paths. Capture and payout must equal the agreement amount and currency.
- The control plane is the only authority for agreement versions/hashes, transaction state, money, payout, and receipts. Verifund may assemble proposal terms only from the Buyer award; the buyer records all agent decisions. The orchestrator relays A2A messages but never approves or mutates settlement state.
- Seller transaction tokens are transaction-, seller-, and hash-bound HMAC tokens. They never appear in graph state, checkpoints, A2A task history, traces, logs, AG-UI state, browser bundles, or orchestrator LLM context.
- `VERIFUND_OPS_TOKEN` stays server-side at the buyer edge. The console keeps using `BUYER_CONSOLE_API_TOKEN`.
- The Verifund A2A service authenticates to buyer internal settlement routes with `VERIFUND_AGENT_INTERNAL_TOKEN` and serves `/a2a` with `VERIFUND_AGENT_A2A_TOKEN`; it never receives `VERIFUND_OPS_TOKEN`, PayPal credentials, seller tokens, or `REGISTRY_ADMIN_TOKEN`.
- Seller marketplace discovery remains seller-specific. Verifund uses generic agent-card registry records/endpoints and is not registered as a seller or required to expose a catalog.
- Buyer-agent review and Seller-agent acceptance are separate A2A decisions bound to one transaction ID, agreement version, and hash; both must accept before human funding HITL is shown. Human funding approval and payout release are separate structured HITL decisions. Free-form chat text never authorizes a state change.
- Buyer-agent validation and Seller-agent acceptance are separate hash-bound A2A decisions; both must accept the same agreement version before the human funding HITL is shown. Agent approval never authorizes a payment.
- Verifund assembles terms only from the Buyer award; the control plane validates/canonicalizes/hashes each version. Changed terms invalidate prior agent decisions and require both reviews again.
- Evidence verification remains deterministic in the control plane; the Verifund agent summarizes its result and evidence references.
- One control-plane process, SQLite WAL, `busy_timeout=5000`, optimistic `version` guards, and no multi-worker uvicorn.
- The agreement hash is `sha256(canonical_json(agreement))` with sorted keys, compact separators, UTF-8, and integer cents.
- Evidence bytes are content-addressed at `data/evidence/<sha256>`; the database stores metadata only.
- Existing ports: console `3000`, orchestrator `9000`, buyer `9100`, registry `9105`, sellers `9201-9204`, control plane `9300`, Verifund A2A agent `9301`.
- Tests use `uv run pytest`; console checks use `pnpm run typecheck` and `pnpm run test`. Commit after every task with a conventional message.
- Do not claim a step passed without running the command and reading the output.

## File Structure

### New workspace units

**`packages/verifund_contracts/`** — shared public contract; no service logic.

| File | Responsibility |
|---|---|
| `pyproject.toml` | Workspace package metadata and dependencies |
| `verifund_contracts/__init__.py` | Public re-exports |
| `verifund_contracts/models.py` | Enums, requests, projections, events, receipts, errors |
| `verifund_contracts/client.py` | Buyer-side typed HTTP client and `VerifundError` |

**`apps/verifund_control_plane/`** — authoritative money and state service.

| File | Responsibility |
|---|---|
| `pyproject.toml`, `verifund_control_plane/__main__.py` | Package and `python -m verifund_control_plane` entry point |
| `settings.py` | All env vars, sandbox startup validation, payout-email map |
| `app.py` | FastAPI factory, lifespan, routers, exception handlers, reconciler startup |
| `errors.py` | Error codes, envelopes, HTTP mapping |
| `db.py` | Async engine, SQLite pragmas, busy translation |
| `domain.py` | States, transitions, canonical JSON, agreement hash, ledger helpers, actions |
| `repository.py` | SQLAlchemy Core tables and all persistence operations, including hash-bound Buyer/Seller agreement reviews |
| `service.py` | Award/accept/reject/approve/fund/PO/evidence/verify/release/payout use cases |
| `policy.py` | Pure verification policy and override rules |
| `tokens.py` | Seller transaction tokens and signed checkout/return links |
| `receipts.py` | Receipt payload, hash, HMAC signature, verification |
| `evidence.py` | Content-addressed evidence storage and validation |
| `audit.py` | Audit log helper used by service transitions |
| `reconciler.py` | In-process sweeps and periodic task |
| `paypal/port.py` | `PaymentPort` protocol and result dataclasses |
| `paypal/fake.py` | SQLite-backed fake orders/payouts and scenario knobs |
| `paypal/sandbox.py` | Real Sandbox Orders/Capture/Payouts/webhook REST adapter |
| `paypal/webhooks.py` | Signature verification, dedupe, dispatch, retry state |
| `api/ops.py` | Unprefixed ops routes and bearer auth |
| `api/seller.py` | Seller token auth, seller projection, evidence routes |
| `api/checkout.py` | Fake checkout, PayPal return/cancel links |
| `api/webhooks.py` | `POST /webhooks/paypal` fake/sandbox intake |
| `api/health.py` | `/health`, `/ready`, `/metrics` |

**`apps/verifund_agent/`** — registered A2A workflow adapter; no money or
settlement-state authority.

| File | Responsibility |
|---|---|
| `verifund_agent/card.py` | Agent Card with the six Verifund skills and bearer security |
| `verifund_agent/service.py`, `executor.py` | Structured A2A task dispatch, decision binding, and task lifecycle |
| `verifund_agent/auth.py`, `client.py` | `/a2a` bearer auth and authenticated buyer-internal settlement client |
| `verifund_agent/settings.py`, `server.py`, `__main__.py` | Port `9301`, isolated credentials, health/readiness, server entrypoint |
| `verifund_agent/register.py` | One-shot registry admin registration CLI; never loaded by the runtime server |

### Existing runtime changes

| Area | Files |
|---|---|
| Contracts | `packages/commerce_core/commerce_core/contracts.py` |
| Buyer | `settings.py`, `services.py`, `settlement.py`, `settlement_store.py`, `settlement_api.py`, `agreement_service.py`, `review.py`, `coordinator.py`, `graph.py`, `executor.py`, `console_api.py`, `trace.py`, `server.py` |
| Orchestrator | `mediation.py`, `agent.py`, `settings.py`, `verifund.py` |
| Registry | `api.py`, `store.py`, `settings.py` — generic-agent registration/discovery separate from seller catalog routes |
| Seller | `settings.py`, `settlement.py`, `evidence_outbox.py`, `graph.py`, `executor.py`, `order_service.py`, `store.py`, `service.py`, `server.py`, `card.py`, `agreement.py` |
| Console | `lib/types.ts`, `lib/api.ts`, `lib/stages.ts`, `lib/config.ts`, `features/runs/use-run.ts`, `features/deal-room/hooks/*`, `features/deal-room/components/*`, `features/chat/chat.tsx`, `features/chat/verifund-tools.tsx`, `app/api/runs/**`, `app/globals.css`, `package.json`, `e2e/verifund.spec.ts` |
| Ops | `scripts/config.py`, `scripts/dev.py`, `scripts/run_demo.py`, new `scripts/verifund_*.py`, `scripts/check_standalone.py`, `tests/test_standalone.py`, `pyproject.toml`, `Dockerfile.python`, `docker-compose.yml`, `.env.example`, `Makefile`, `.gitignore`, `README.md`, `docs/verifund-paypal-sandbox.md`, old MarketMesh spec |

### Test layout

- `tests/support/verifund.py` — control-plane harness, mutable clock, award/funding helpers.
- `tests/unit/test_verifund_*.py` — domain, tokens, receipts, evidence, policy, PayPal, webhooks, reconciler.
- `tests/integration/test_verifund_*.py` — full lifecycle, auth, buyer proxy, seller validation.
- `tests/protocol/test_settlement_contracts.py` — old/new payload compatibility.
- `apps/console/features/deal-room/components/*.test.tsx` — Transaction Room unit tests.
- `apps/console/e2e/verifund.spec.ts` — fake-mode browser flow.
- `tests/unit/test_registry_agents.py`, `tests/unit/test_verifund_agent_*.py`, and `tests/integration/test_verifund_agent.py` — generic discovery, structured A2A tasks, registration, buyer proxy, and failure behavior.
- `tests/unit/test_verifund_dev_config.py` and `tests/unit/test_verifund_packaging.py` — local stack wiring and packaging.
- `apps/console/features/chat/verifund-tools.test.tsx` and `chat.test.tsx` — HITL binding, checkout handoff, evidence/status, receipt rendering, and mode gating.

---

## Phase 0 — Contracts, workspace, and standalone guard

### Task 1: Create `verifund_contracts` and register the workspace package

**Files:**
- Create: `packages/verifund_contracts/pyproject.toml`
- Create: `packages/verifund_contracts/verifund_contracts/__init__.py`
- Create: `packages/verifund_contracts/verifund_contracts/models.py`
- Create: `packages/verifund_contracts/verifund_contracts/client.py`
- Modify: `pyproject.toml:38-51`
- Test: `tests/unit/test_verifund_contracts.py`

**Interfaces:**
- Produces: `AwardRequest`, `AwardResponse`, `BuyerAgreementReviewRequest`, `AgreementReviewDecision`, `AgreementReviewProjection`, `AcceptRequest`, `RejectRequest`, `ApproveRequest`, `CancelRequest`, `FundRequest`, `FundResponse`, `PurchaseOrderReport`, `ReleaseRequest`, `FlagReviewRequest`, `SellerTokenRequest`, `SellerTokenResponse`, `TransactionProjection` (including `buyer_agent_review`), `SellerProjection`, `EvidenceItem`, `EvidenceList`, `ReceiptResponse`, `TransactionEvent`, `VerifundClient`, `VerifundError`, `TransactionState`, `RejectReason`, `CancelReason`, `EvidenceKind`, `ReviewReason`, `VerifundErrorCode`.
- Consumes: nothing.

- [ ] **Step 1: Write failing contract tests**

`tests/unit/test_verifund_contracts.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx
from pydantic import ValidationError

from verifund_contracts import (
    AwardRequest,
    CancelReason,
    RejectRequest,
    TransactionProjection,
    VerifundClient,
    VerifundError,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award_payload(**overrides):
    payload = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }
    payload.update(overrides)
    return payload


def test_award_rejects_non_matching_total():
    with pytest.raises(ValidationError):
        AwardRequest(**award_payload(amount_cents=123401))


def test_award_accepts_matching_total():
    request = AwardRequest(**award_payload())
    assert request.amount_cents == 123400


def test_reject_reason_must_be_known():
    with pytest.raises(ValidationError):
        RejectRequest(
            seller_id="northwind-audio",
            agreement_hash="a" * 64,
            reason_code="made_up",
            seller_task_id="task-1",
            rejected_at=NOW,
        )


def test_projection_round_trip_has_no_extra_fields():
    projection = TransactionProjection(
        transaction_id="vf_1",
        run_id="run-1",
        state="AWARDED",
        last_seq=1,
        amount_cents=123400,
        currency="USD",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        agreement_hash="a" * 64,
        agreement_version=1,
        seller_decision=None,
        buyer_agent_review=None,
        approval=None,
        cancellation=None,
        funding=None,
        purchase_order=None,
        evidence=None,
        verification=None,
        payout=None,
        receipt_available=False,
        deadlines={"evidence": None, "inspection": None},
        allowed_actions=["cancel"],
        updated_at=NOW,
    )
    assert projection.model_dump()["state"] == "AWARDED"


@respx.mock
async def test_client_sends_ops_headers_and_raises_structured_error():
    route = respx.post("http://control/awards").mock(
        return_value=httpx.Response(
            409,
            json={
                "error": {
                    "code": "hash_mismatch",
                    "message": "hash mismatch",
                    "retryable": False,
                    "details": {},
                    "request_id": "req-1",
                }
            },
        )
    )
    client = VerifundClient("http://control", ops_token="ops-token")
    with pytest.raises(VerifundError) as raised:
        await client.award(
            AwardRequest(**award_payload()),
            actor="buyer-agent",
            idempotency_key="award:run-1:offer-1",
        )
    assert raised.value.code == "hash_mismatch"
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer ops-token"
    assert request.headers["x-verifund-actor"] == "buyer-agent"
    assert request.headers["idempotency-key"] == "award:run-1:offer-1"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifund_contracts'`.

- [ ] **Step 3: Create the package metadata**

`packages/verifund_contracts/pyproject.toml`:

```toml
[project]
name = "verifund-contracts"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.10,<3",
  "httpx>=0.27,<1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["verifund_contracts"]
```

Modify root `pyproject.toml`:

```toml
[tool.uv.workspace]
members = [
  "packages/commerce_core",
  "packages/verifund_contracts",
  "apps/registry",
  "apps/seller_agent",
  "apps/buyer_agent",
  "apps/orchestrator_agent",
  "apps/verifund_control_plane",
]

[tool.uv.sources]
marketmesh-commerce-core = { workspace = true }
verifund-contracts = { workspace = true }
```

Do not create `apps/verifund_control_plane` in this task; add its member entry in Task 4 after the directory exists. For now add only `packages/verifund_contracts` and the `verifund-contracts` source.

- [ ] **Step 4: Implement the shared models**

`packages/verifund_contracts/verifund_contracts/models.py`:

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VerifundModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransactionState(StrEnum):
    AWARDED = "AWARDED"
    AGREED = "AGREED"
    FUNDING_PENDING = "FUNDING_PENDING"
    FUNDED = "FUNDED"
    FULFILLMENT_PENDING = "FULFILLMENT_PENDING"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    RELEASE_PERMITTED = "RELEASE_PERMITTED"
    PAYOUT_PENDING = "PAYOUT_PENDING"
    RELEASED = "RELEASED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"


class EvidenceKind(StrEnum):
    SHIPMENT_MANIFEST = "shipment_manifest"
    DELIVERY_CONFIRMATION = "delivery_confirmation"
    INVOICE = "invoice"
    OTHER = "other"


class RejectReason(StrEnum):
    TERMS_MISMATCH = "terms_mismatch"
    OUT_OF_STOCK = "out_of_stock"
    CANNOT_FULFILL = "cannot_fulfill"
    VERIFICATION_FAILED = "verification_failed"
    OTHER = "other"


class AgreementReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CancelReason(StrEnum):
    BUYER_REJECTED = "buyer_rejected"
    BUYER_CANCELLED = "buyer_cancelled"
    REVIEWER_CANCELLED = "reviewer_cancelled"
    FUNDING_EXPIRED = "funding_expired"


class ReviewReason(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    INVALID_EVIDENCE_HASH = "invalid_evidence_hash"
    SELLER_MISMATCH = "seller_mismatch"
    AGREEMENT_MISMATCH = "agreement_mismatch"
    TRACKING_MISMATCH = "tracking_mismatch"
    DELIVERY_IN_FUTURE = "delivery_in_future"
    INSPECTION_NOT_ELAPSED = "inspection_not_elapsed"
    FUNDING_MISMATCH = "funding_mismatch"
    EVIDENCE_DEADLINE_MISSED = "evidence_deadline_missed"
    LEDGER_INCOMPLETE = "ledger_incomplete"
    MANUAL_FLAG = "manual_flag"
    LATE_CAPTURE = "late_capture"


class VerifundErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INVALID_REQUEST = "invalid_request"
    INVALID_STATE = "invalid_state"
    HASH_MISMATCH = "hash_mismatch"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_SCOPE_DENIED = "token_scope_denied"
    EVIDENCE_TOO_LARGE = "evidence_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_AMBIGUOUS = "provider_ambiguous"
    INTERNAL = "internal"


class AwardLineItem(VerifundModel):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)
    warranty_addon_cents: int = Field(default=0, ge=0)


class AwardRequest(VerifundModel):
    run_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    currency: str = Field(default="USD", pattern="^USD$")
    amount_cents: int = Field(gt=0)
    shipping_cents: int = Field(ge=0)
    quantity: int = Field(gt=0)
    line_items: list[AwardLineItem] = Field(min_length=1)
    delivery_days: int = Field(ge=0)
    warranty_months: int = Field(ge=0)
    returns_days: int = Field(ge=0)

    @model_validator(mode="after")
    def _totals_must_match(self) -> AwardRequest:
        line_quantity = sum(item.quantity for item in self.line_items)
        if line_quantity != self.quantity:
            raise ValueError("quantity must equal the sum of line-item quantities")
        line_total = sum(
            (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
            for item in self.line_items
        )
        if line_total + self.shipping_cents != self.amount_cents:
            raise ValueError("amount_cents must equal line items plus shipping")
        return self


class AwardResponse(VerifundModel):
    transaction_id: str
    state: TransactionState
    agreement_hash: str
    seller_token: str
    expires_at: datetime


class AcceptRequest(VerifundModel):
    seller_id: str
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    accepted_total_cents: int = Field(gt=0)
    seller_task_id: str = Field(min_length=1)
    accepted_at: datetime


class BuyerAgreementReviewRequest(VerifundModel):
    buyer_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    decision: AgreementReviewDecision
    reason_code: str | None = None
    note: str = ""
    buyer_task_id: str = Field(min_length=1)
    reviewed_at: datetime


class RejectRequest(VerifundModel):
    seller_id: str
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    reason_code: RejectReason
    note: str = ""
    seller_task_id: str = Field(min_length=1)
    rejected_at: datetime


class ApproveRequest(VerifundModel):
    approval_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    note: str = ""
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")


class CancelRequest(VerifundModel):
    reason_code: CancelReason
    note: str = ""

    @model_validator(mode="after")
    def _reject_reconciler_only_reason(self) -> CancelRequest:
        if self.reason_code == CancelReason.FUNDING_EXPIRED:
            raise ValueError("funding_expired is set by the reconciler")
        return self


class FundRequest(VerifundModel):
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    return_url: str
    cancel_url: str


class FundResponse(VerifundModel):
    transaction_id: str
    state: TransactionState
    checkout_url: str
    expires_at: datetime


class PurchaseOrderLineItem(VerifundModel):
    sku: str
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)
    warranty_addon_cents: int = Field(default=0, ge=0)


class PurchaseOrderReport(VerifundModel):
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    seller_order_id: str
    offer_id: str
    quantity: int = Field(gt=0)
    total_cents: int = Field(gt=0)
    currency: str = Field(default="USD", pattern="^USD$")
    tracking_number: str
    carrier: str
    reserved_at: datetime
    eta: datetime
    line_items: list[PurchaseOrderLineItem] = Field(min_length=1)


class ReleaseRequest(VerifundModel):
    released_by: str = Field(min_length=1)
    note: str = ""
    override: bool = False


class FlagReviewRequest(VerifundModel):
    reason: str = Field(min_length=1)
    note: str = ""


class VerifyRequest(VerifundModel):
    note: str = ""


class SellerTokenRequest(VerifundModel):
    run_id: str
    transaction_id: str
    seller_id: str
    purpose: str


class SellerTokenResponse(VerifundModel):
    seller_token: str
    expires_at: datetime


class SellerDecisionProjection(VerifundModel):
    status: str
    reported_at: datetime
    reason_code: RejectReason | None = None
    note: str | None = None


class AgreementReviewProjection(VerifundModel):
    status: AgreementReviewDecision
    agreement_version: int
    agreement_hash: str
    task_id: str
    reviewed_at: datetime
    reason_code: str | None = None
    note: str | None = None


class ApprovalProjection(VerifundModel):
    approved_by: str
    approved_at: datetime
    note: str | None = None


class CancellationProjection(VerifundModel):
    reason_code: str
    note: str | None = None
    at: datetime


class FundingProjection(VerifundModel):
    status: str
    provider_order_id: str | None = None
    capture_id: str | None = None
    payer_action_url: str | None = None
    completed_at: datetime | None = None


class PurchaseOrderProjection(VerifundModel):
    seller_order_id: str
    tracking_number: str | None = None
    carrier: str | None = None
    eta: datetime | None = None


class EvidenceSummary(VerifundModel):
    required: list[str]
    received: list[str]
    complete: bool
    deadline: datetime | None = None
    items: list[EvidenceItem]


class VerificationProjection(VerifundModel):
    status: str
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime | None = None
    override_allowed: bool = False


class PayoutProjection(VerifundModel):
    status: str
    batch_id: str | None = None
    item_id: str | None = None
    amount_cents: int | None = None
    updated_at: datetime | None = None


class EvidenceItem(VerifundModel):
    evidence_id: str
    kind: str
    sha256: str
    media_type: str
    size_bytes: int
    original_filename: str
    note: str | None = None
    created_at: datetime


class EvidenceList(VerifundModel):
    items: list[EvidenceItem]


class TransactionProjection(VerifundModel):
    transaction_id: str
    run_id: str
    state: TransactionState
    last_seq: int
    amount_cents: int
    currency: str
    buyer_id: str
    seller_id: str
    agreement_hash: str
    agreement_version: int
    buyer_agent_review: AgreementReviewProjection | None = None
    seller_decision: SellerDecisionProjection | None = None
    approval: ApprovalProjection | None = None
    cancellation: CancellationProjection | None = None
    funding: FundingProjection | None = None
    purchase_order: PurchaseOrderProjection | None = None
    evidence: EvidenceSummary | None = None
    verification: VerificationProjection | None = None
    payout: PayoutProjection | None = None
    receipt_available: bool = False
    deadlines: dict[str, datetime | None]
    allowed_actions: list[str] = Field(default_factory=list)
    updated_at: datetime


class SellerProjection(VerifundModel):
    transaction_id: str
    run_id: str
    state: TransactionState
    seller_id: str
    amount_cents: int
    currency: str
    agreement_hash: str
    agreement_version: int
    quantity: int
    line_items: list[AwardLineItem]
    delivery_days: int
    warranty_months: int
    returns_days: int
    purchase_order: PurchaseOrderProjection | None = None
    evidence: EvidenceSummary | None = None
    deadlines: dict[str, datetime | None]
    allowed_actions: list[str] = Field(default_factory=list)
    updated_at: datetime


class ReceiptPayload(VerifundModel):
    receipt_version: int = 1
    transaction_id: str
    agreement_hash: str
    amount_cents: int
    currency: str
    buyer_id: str
    seller_id: str
    capture_id: str
    payout_item_id: str
    evidence_hashes: list[str]
    released_at: datetime


class ReceiptResponse(VerifundModel):
    payload: ReceiptPayload
    payload_hash: str
    signature: str
    kid: str
    verified: bool


class TransactionEvent(VerifundModel):
    seq: int
    type: str
    payload: dict[str, Any]
    actor: str
    created_at: datetime


class ErrorDetail(VerifundModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorEnvelope(VerifundModel):
    error: ErrorDetail
```

Create `EvidenceItem` before `EvidenceSummary` to avoid forward references. The final file must define `EvidenceItem` before `EvidenceSummary`; reorder in the actual file.

`packages/verifund_contracts/verifund_contracts/__init__.py`:

```python
from verifund_contracts.client import VerifundClient, VerifundError
from verifund_contracts.models import *  # noqa: F403
```

- [ ] **Step 5: Implement the typed client**

`packages/verifund_contracts/verifund_contracts/client.py`:

```python
from __future__ import annotations

from typing import Any

import httpx

from verifund_contracts.models import (
    AcceptRequest,
    ApproveRequest,
    AwardRequest,
    AwardResponse,
    CancelRequest,
    ErrorEnvelope,
    EvidenceItem,
    FundRequest,
    FundResponse,
    PurchaseOrderReport,
    ReceiptResponse,
    RejectRequest,
    ReleaseRequest,
    SellerProjection,
    SellerTokenRequest,
    SellerTokenResponse,
    TransactionEvent,
    TransactionProjection,
    FlagReviewRequest,
)


class VerifundError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 0,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}
        self.request_id = request_id


class VerifundClient:
    def __init__(
        self,
        base_url: str,
        *,
        ops_token: str,
        actor: str = "buyer-agent",
        httpx_client: httpx.AsyncClient | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ops_token = ops_token
        self.actor = actor
        self._client = httpx_client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = httpx_client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        actor: str | None = None,
        idempotency_key: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers = {
            "authorization": f"Bearer {self.ops_token}",
            "x-verifund-actor": actor or self.actor,
        }
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        response = await self._client.request(
            method,
            self.base_url + path,
            headers=headers,
            json=body,
            params=params,
        )
        if response.status_code >= 400:
            try:
                envelope = ErrorEnvelope.model_validate(response.json())
                detail = envelope.error
            except Exception:  # noqa: BLE001
                raise VerifundError(
                    "internal",
                    f"control plane returned HTTP {response.status_code}",
                    status_code=response.status_code,
                ) from None
            raise VerifundError(
                detail.code,
                detail.message,
                status_code=response.status_code,
                retryable=detail.retryable,
                details=detail.details,
                request_id=detail.request_id,
            )
        if response.status_code == 204:
            return None
        return response.json()

    async def award(
        self,
        request: AwardRequest,
        *,
        actor: str,
        idempotency_key: str,
    ) -> AwardResponse:
        return AwardResponse.model_validate(
            await self._request(
                "POST", "/awards", body=request.model_dump(mode="json"),
                actor=actor, idempotency_key=idempotency_key,
            )
        )

    async def get_transaction(self, transaction_id: str, *, actor: str = "buyer-agent") -> dict:
        return await self._request("GET", f"/transactions/{transaction_id}", actor=actor)

    async def get_state(self, transaction_id: str, *, actor: str = "buyer-agent") -> TransactionProjection:
        return TransactionProjection.model_validate(
            await self._request("GET", f"/transactions/{transaction_id}/state", actor=actor)
        )

    async def list_transactions(self, *, run_id: str | None = None, state: str | None = None) -> list[dict]:
        params = {k: v for k, v in {"run_id": run_id, "state": state}.items() if v}
        return await self._request("GET", "/transactions", actor="buyer-agent", params=params)

    async def accept(self, transaction_id: str, request: AcceptRequest, *, actor: str, idempotency_key: str | None = None) -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/accept", body=request.model_dump(mode="json"), actor=actor, idempotency_key=idempotency_key)

    async def reject(self, transaction_id: str, request: RejectRequest, *, actor: str, idempotency_key: str | None = None) -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/reject", body=request.model_dump(mode="json"), actor=actor, idempotency_key=idempotency_key)

    async def approve(self, transaction_id: str, request: ApproveRequest, *, actor: str, idempotency_key: str | None = None) -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/approve", body=request.model_dump(mode="json"), actor=actor, idempotency_key=idempotency_key)

    async def fund(self, transaction_id: str, request: FundRequest, *, actor: str, idempotency_key: str | None = None) -> FundResponse:
        return FundResponse.model_validate(await self._request("POST", f"/transactions/{transaction_id}/fund", body=request.model_dump(mode="json"), actor=actor, idempotency_key=idempotency_key))

    async def refresh_funding(self, transaction_id: str, *, actor: str = "buyer-agent") -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/funding/refresh", body={}, actor=actor)

    async def purchase_order(self, transaction_id: str, request: PurchaseOrderReport, *, actor: str, idempotency_key: str | None = None) -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/purchase-order", body=request.model_dump(mode="json"), actor=actor, idempotency_key=idempotency_key)

    async def verify(self, transaction_id: str, *, actor: str = "buyer-agent") -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/verify", body={}, actor=actor)

    async def release(self, transaction_id: str, request: ReleaseRequest, *, actor: str) -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/release", body=request.model_dump(mode="json"), actor=actor)

    async def payout(self, transaction_id: str, *, actor: str = "buyer-agent") -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/payout", body={}, actor=actor)

    async def refresh_payout(self, transaction_id: str, *, actor: str = "buyer-agent") -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/payout/refresh", body={}, actor=actor)

    async def cancel(self, transaction_id: str, request: CancelRequest, *, actor: str) -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/cancel", body=request.model_dump(mode="json"), actor=actor)

    async def flag_review(self, transaction_id: str, request: FlagReviewRequest, *, actor: str) -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/flag-review", body=request.model_dump(mode="json"), actor=actor)

    async def seller_token(self, transaction_id: str, request: SellerTokenRequest, *, actor: str = "buyer-agent") -> SellerTokenResponse:
        return SellerTokenResponse.model_validate(
            await self._request(
                "POST",
                f"/transactions/{transaction_id}/seller-token",
                body=request.model_dump(mode="json"),
                actor=actor,
            )
        )

    async def revoke_seller_token(self, transaction_id: str, *, actor: str = "buyer-agent") -> dict:
        return await self._request("POST", f"/transactions/{transaction_id}/seller-token/revoke", body={}, actor=actor)

    async def events(self, transaction_id: str, *, after_seq: int = 0) -> list[TransactionEvent]:
        rows = await self._request("GET", f"/transactions/{transaction_id}/events", actor="buyer-agent", params={"after_seq": after_seq})
        return [TransactionEvent.model_validate(row) for row in rows]

    async def receipt(self, transaction_id: str, *, actor: str = "buyer-agent") -> ReceiptResponse:
        return ReceiptResponse.model_validate(await self._request("GET", f"/transactions/{transaction_id}/receipt", actor=actor))

    async def list_evidence(self, transaction_id: str, *, actor: str = "buyer-agent") -> list[EvidenceItem]:
        rows = await self._request(
            "GET",
            f"/transactions/{transaction_id}/evidence",
            actor=actor,
        )
        return [EvidenceItem.model_validate(row) for row in rows]

    async def get_evidence(
        self, transaction_id: str, evidence_id: str, *, actor: str = "buyer-agent"
    ) -> tuple[bytes, str, str]:
        response = await self._client.get(
            f"{self.base_url}/transactions/{transaction_id}/evidence/{evidence_id}",
            headers={
                "authorization": f"Bearer {self.ops_token}",
                "x-verifund-actor": actor,
            },
        )
        if response.status_code >= 400:
            raise VerifundError(
                "not_found", "evidence not found", status_code=response.status_code
            )
        disposition = response.headers.get("content-disposition", "")
        filename = "evidence"
        if 'filename="' in disposition:
            filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
        return (
            response.content,
            response.headers.get("content-type", "application/octet-stream"),
            filename,
        )

    async def seller_projection(self, transaction_id: str, token: str) -> SellerProjection:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}",
            headers={"authorization": f"Bearer {token}"},
        )
        if response.status_code >= 400:
            raise VerifundError("unauthorized", "seller token rejected", status_code=response.status_code)
        return SellerProjection.model_validate(response.json())
```

Remove the unused `json` import. Ensure all model imports are used. Keep `AcceptRequest` etc.

- [ ] **Step 6: Run the contract tests**

Run: `uv lock && uv sync --all-packages && uv run pytest tests/unit/test_verifund_contracts.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock packages/verifund_contracts tests/unit/test_verifund_contracts.py
git commit -m "feat(verifund): add shared contracts package and typed client"
```

---

### Task 1A: Add agreement projections, review envelopes, and HITL decisions

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/models.py`
- Create: `packages/verifund_contracts/verifund_contracts/a2a.py`
- Modify: `packages/verifund_contracts/verifund_contracts/client.py`
- Modify: `packages/verifund_contracts/verifund_contracts/__init__.py`
- Test: `tests/unit/test_verifund_a2a_contracts.py`

**Interfaces:**
- Produces: `AgreementProjection`, `BuyerAgreementRequest`, `BuyerAgreementResponse`, `FundingApprovalDecision`, `ReleaseApprovalDecision`, `AgreementReviewRequest`, `AgreementReviewResult`, `VerifundTaskRequest`, `VerifundTaskResult`, `VerifundSkill`, the A2A schema constants, and the `wrap_*`/`parse_*` envelope helpers; `AwardResponse.agreement`, `AwardResponse.agreement_version`, and `VerifundClient.buyer_review`.
- `AgreementProjection.canonical_payload()` excludes only `agreement_hash`; `created_at` is stored as an ISO-8601 string so the buyer, Verifund, and control plane hash the identical bytes.
- `FundingApprovalDecision` and `ReleaseApprovalDecision` are the only structured human-authorization inputs. `ReleaseApprovalDecision` requires a note when `override` is true.
- `AgreementReviewRequest.party` is `buyer` or `seller`; `AgreementReviewResult.party` must match it. A result that does not echo the same transaction, version, and hash is rejected by `parse_agreement_review_result`.

- [ ] **Step 1: Write the failing contract tests**

`tests/unit/test_verifund_a2a_contracts.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx
from pydantic import ValidationError

from verifund_contracts import (
    AGREEMENT_REVIEW_REQUEST_SCHEMA,
    AgreementProjection,
    AgreementReviewRequest,
    AgreementReviewResult,
    AwardRequest,
    AwardResponse,
    BuyerAgreementRequest,
    BuyerAgreementResponse,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
    VerifundClient,
    VerifundSkill,
    VerifundTaskRequest,
    parse_agreement_review_result,
    parse_verifund_task_request,
    wrap_agreement_review_request,
    wrap_verifund_task_request,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def agreement_payload(**overrides):
    payload = {
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "shipping_cents": 3400,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "created_at": "2026-10-27T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def projection(**overrides) -> AgreementProjection:
    body = agreement_payload(**overrides)
    probe = AgreementProjection.model_construct(
        **body, agreement_hash="0" * 64
    )
    return AgreementProjection(
        **body, agreement_hash=probe.recompute_hash()
    )


def test_agreement_projection_hash_binds_every_term() -> None:
    item = projection()
    assert item.agreement_hash == item.recompute_hash()
    tampered = agreement_payload(amount_cents=123401)
    probe = AgreementProjection.model_construct(
        **tampered, agreement_hash=item.agreement_hash
    )
    assert probe.recompute_hash() != item.agreement_hash
    with pytest.raises(ValidationError):
        AgreementProjection(**tampered, agreement_hash=item.agreement_hash)


def test_award_response_requires_the_agreement_projection() -> None:
    with pytest.raises(ValidationError):
        AwardResponse(
            transaction_id="vf_1",
            state="AWARDED",
            agreement_hash=HASH,
            seller_token="v1.token",
            expires_at=NOW,
        )


def test_funding_and_release_decisions_are_hash_bound() -> None:
    funding = FundingApprovalDecision(
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        approved=True,
        approved_by="demo-reviewer",
        note="looks good",
        decided_at=NOW,
        idempotency_key="fund:run-1:vf_1",
    )
    assert funding.agreement_hash == HASH
    with pytest.raises(ValidationError):
        FundingApprovalDecision(
            **{
                **funding.model_dump(),
                "agreement_hash": "not-a-hash",
            }
        )
    with pytest.raises(ValidationError):
        ReleaseApprovalDecision(
            run_id="run-1",
            transaction_id="vf_1",
            agreement_version=1,
            agreement_hash=HASH,
            approved=True,
            released_by="demo-reviewer",
            note="",
            override=True,
            decided_at=NOW,
            idempotency_key="release:run-1:vf_1",
        )


def test_agreement_review_envelope_round_trips_and_rejects_a_changed_hash() -> None:
    request = AgreementReviewRequest(
        party="seller",
        run_id="run-1",
        transaction_id="vf_1",
        agreement=projection(),
        seller_task_id="seller-task-1",
        seller_context_id="run-1",
        requested_at=NOW,
        idempotency_key="review:vf_1:1",
    )
    envelope = wrap_agreement_review_request(request)
    assert envelope["schema"] == AGREEMENT_REVIEW_REQUEST_SCHEMA
    assert envelope["schema_version"] == "1.0"

    decision = AgreementReviewResult(
        party="seller",
        status="accepted",
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=request.agreement.agreement_hash,
        task_id="seller-task-1",
        context_id="run-1",
        reviewed_at=NOW,
    )
    assert parse_agreement_review_result(
        {
            "schema": AGREEMENT_REVIEW_REQUEST_SCHEMA,
            "schema_version": "1.0",
            "payload": decision.model_dump(mode="json"),
        },
        expected_party="seller",
        expected_transaction_id="vf_1",
        expected_version=1,
        expected_hash=request.agreement.agreement_hash,
    ).status == "accepted"

    with pytest.raises(ValueError):
        parse_agreement_review_result(
            {
                "schema": AGREEMENT_REVIEW_REQUEST_SCHEMA,
                "schema_version": "1.0",
                "payload": decision.model_dump(mode="json"),
            },
            expected_party="seller",
            expected_transaction_id="vf_1",
            expected_version=1,
            expected_hash="b" * 64,
        )


def test_verifund_task_envelope_round_trips_and_requires_known_skill() -> None:
    request = VerifundTaskRequest(
        skill=VerifundSkill.TRANSACTION_FUND,
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        payload={"approval": {"approved": True}},
        idempotency_key="fund:run-1:vf_1",
    )
    envelope = wrap_verifund_task_request(request)
    assert parse_verifund_task_request(envelope).skill == "verifund.transaction.fund"
    with pytest.raises(ValidationError):
        VerifundTaskRequest(
            skill="verifund.unknown",
            run_id="run-1",
            idempotency_key="x",
            payload={},
        )


def test_buyer_agreement_contracts_carry_the_secret_reference_only() -> None:
    request = BuyerAgreementRequest(
        award=AwardRequest(
            run_id="run-1",
            buyer_id="demo-buyer",
            seller_id="northwind-audio",
            offer_id="offer-1",
            amount_cents=123400,
            shipping_cents=3400,
            quantity=12,
            line_items=[
                {
                    "sku": "NC-700",
                    "name": "Nimbus NC-700 ANC Headset",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                }
            ],
            delivery_days=7,
            warranty_months=24,
            returns_days=30,
        ),
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        idempotency_key="agreement:run-1:offer-1",
    )
    assert request.award.run_id == "run-1"
    response = BuyerAgreementResponse(
        transaction_id="vf_1",
        state="AWARDED",
        agreement=projection(),
        agreement_version=1,
        agreement_hash=projection().agreement_hash,
        seller_token_ref="run:run-1:transaction:vf_1",
    )
    dumped = response.model_dump(mode="json")
    assert "seller_token" not in dumped
    assert dumped["seller_token_ref"] == "run:run-1:transaction:vf_1"


@respx.mock
async def test_client_posts_buyer_review_with_actor_and_idempotency() -> None:
    route = respx.post(
        "http://control/transactions/vf_1/buyer-review"
    ).mock(return_value=httpx.Response(200, json={}))
    client = VerifundClient("http://control", ops_token="ops-token")
    await client.buyer_review(
        "vf_1",
        {
            "buyer_id": "demo-buyer",
            "agreement_version": 1,
            "agreement_hash": HASH,
            "decision": "accepted",
            "buyer_task_id": "buyer-task-1",
            "reviewed_at": NOW.isoformat(),
        },
        actor="buyer-agent",
        idempotency_key="buyer-review:vf_1:1",
    )
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer ops-token"
    assert request.headers["x-verifund-actor"] == "buyer-agent"
    assert request.headers["idempotency-key"] == "buyer-review:vf_1:1"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_a2a_contracts.py -v`
Expected: FAIL with `ImportError` for `AgreementProjection`, `FundingApprovalDecision`, and the A2A helpers.

- [ ] **Step 3: Add the shared models**

Append to `packages/verifund_contracts/verifund_contracts/models.py`:

```python
import hashlib
import json


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AgreementProjection(VerifundModel):
    agreement_version: int = Field(ge=1)
    transaction_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    currency: str = Field(default="USD", pattern="^USD$")
    amount_cents: int = Field(gt=0)
    quantity: int = Field(gt=0)
    line_items: list[AwardLineItem] = Field(min_length=1)
    shipping_cents: int = Field(ge=0)
    delivery_days: int = Field(ge=0)
    warranty_months: int = Field(ge=0)
    returns_days: int = Field(ge=0)
    created_at: str = Field(min_length=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"agreement_hash"})

    def recompute_hash(self) -> str:
        return sha256_hex(canonical_json(self.canonical_payload()))

    @model_validator(mode="after")
    def _hash_must_match(self) -> AgreementProjection:
        if self.recompute_hash() != self.agreement_hash:
            raise ValueError("agreement hash does not match canonical payload")
        return self


class BuyerAgreementRequest(VerifundModel):
    award: AwardRequest
    buyer_task_id: str = Field(min_length=1)
    buyer_context_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class BuyerAgreementResponse(VerifundModel):
    transaction_id: str = Field(min_length=1)
    state: TransactionState
    agreement: AgreementProjection
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    seller_token_ref: str = Field(min_length=1)
    seller_token_expires_at: datetime | None = None

    @model_validator(mode="after")
    def _binding_must_match(self) -> BuyerAgreementResponse:
        if self.agreement.transaction_id != self.transaction_id:
            raise ValueError("agreement transaction does not match response")
        if self.agreement.agreement_version != self.agreement_version:
            raise ValueError("agreement version does not match response")
        if self.agreement.agreement_hash != self.agreement_hash:
            raise ValueError("agreement hash does not match response")
        return self


class FundingApprovalDecision(VerifundModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    approved: bool
    approved_by: str = Field(min_length=1)
    note: str = ""
    decided_at: datetime
    idempotency_key: str = Field(min_length=1)


class ReleaseApprovalDecision(VerifundModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    approved: bool
    released_by: str = Field(min_length=1)
    note: str = ""
    override: bool = False
    decided_at: datetime
    idempotency_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def _override_requires_a_note(self) -> ReleaseApprovalDecision:
        if self.override and not self.note.strip():
            raise ValueError("an override release requires a note")
        return self
```

Add `agreement: AgreementProjection` and `agreement_version: int = Field(ge=1)` to `AwardResponse` immediately after `agreement_hash`.

- [ ] **Step 4: Add the A2A envelope module**

`packages/verifund_contracts/verifund_contracts/a2a.py`:

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from verifund_contracts.models import (
    AgreementProjection,
    AgreementReviewDecision,
    TransactionState,
    VerifundModel,
)

VERIFUND_SCHEMA_BASE = "https://marketmesh.example/extensions/verifund/v1/schemas"
AGREEMENT_REVIEW_REQUEST_SCHEMA = f"{VERIFUND_SCHEMA_BASE}/agreement-review-request.json"
AGREEMENT_REVIEW_RESULT_SCHEMA = f"{VERIFUND_SCHEMA_BASE}/agreement-review-result.json"
VERIFUND_TASK_REQUEST_SCHEMA = f"{VERIFUND_SCHEMA_BASE}/task-request.json"
VERIFUND_TASK_RESULT_SCHEMA = f"{VERIFUND_SCHEMA_BASE}/task-result.json"


class VerifundSkill(StrEnum):
    AGREEMENT_CREATE = "verifund.agreement.create"
    TRANSACTION_STATUS = "verifund.transaction.status"
    TRANSACTION_FUND = "verifund.transaction.fund"
    EVIDENCE_REVIEW = "verifund.evidence.review"
    TRANSACTION_RELEASE = "verifund.transaction.release"
    RECEIPT_GET = "verifund.receipt.get"


class AgreementReviewRequest(VerifundModel):
    party: Literal["buyer", "seller"]
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement: AgreementProjection
    buyer_task_id: str | None = None
    buyer_context_id: str | None = None
    seller_task_id: str | None = None
    seller_context_id: str | None = None
    requested_at: datetime
    idempotency_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def _party_task_is_present(self) -> AgreementReviewRequest:
        if self.party == "buyer" and not (
            self.buyer_task_id and self.buyer_context_id
        ):
            raise ValueError("buyer review requires buyer task and context ids")
        if self.party == "seller" and not (
            self.seller_task_id and self.seller_context_id
        ):
            raise ValueError("seller review requires seller task and context ids")
        return self


class AgreementReviewResult(VerifundModel):
    party: Literal["buyer", "seller"]
    status: AgreementReviewDecision
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    task_id: str = Field(min_length=1)
    context_id: str = Field(min_length=1)
    reviewed_at: datetime
    reason_code: str | None = None
    note: str = ""


class VerifundTaskRequest(VerifundModel):
    skill: VerifundSkill
    run_id: str = Field(min_length=1)
    transaction_id: str | None = None
    agreement_version: int | None = Field(default=None, ge=1)
    agreement_hash: str | None = Field(
        default=None, pattern="^[0-9a-f]{64}$"
    )
    actor: str = "orchestrator"
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)


class VerifundTaskResult(VerifundModel):
    skill: VerifundSkill
    status: Literal["completed", "input_required", "failed"]
    run_id: str = Field(min_length=1)
    transaction_id: str | None = None
    agreement_version: int | None = None
    agreement_hash: str | None = None
    state: TransactionState | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    retryable: bool = False
    next_action: str | None = None


def _wrap(schema: str, model: VerifundModel) -> dict[str, Any]:
    return {
        "schema": schema,
        "schema_version": "1.0",
        "payload": model.model_dump(mode="json"),
    }


def _unwrap(
    envelope: dict[str, Any], expected_schema: str
) -> dict[str, Any]:
    if envelope.get("schema") != expected_schema:
        raise ValueError(f"unexpected schema: {envelope.get('schema')}")
    if envelope.get("schema_version") != "1.0":
        raise ValueError(
            f"unsupported schema version: {envelope.get('schema_version')}"
        )
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("envelope payload must be an object")
    return payload


def wrap_agreement_review_request(request: AgreementReviewRequest) -> dict[str, Any]:
    return _wrap(AGREEMENT_REVIEW_REQUEST_SCHEMA, request)


def parse_agreement_review_request(envelope: dict[str, Any]) -> AgreementReviewRequest:
    return AgreementReviewRequest.model_validate(
        _unwrap(envelope, AGREEMENT_REVIEW_REQUEST_SCHEMA)
    )


def wrap_agreement_review_result(result: AgreementReviewResult) -> dict[str, Any]:
    return _wrap(AGREEMENT_REVIEW_RESULT_SCHEMA, result)


def parse_agreement_review_result(
    envelope: dict[str, Any],
    *,
    expected_party: str,
    expected_transaction_id: str,
    expected_version: int,
    expected_hash: str,
) -> AgreementReviewResult:
    result = AgreementReviewResult.model_validate(
        _unwrap(envelope, AGREEMENT_REVIEW_RESULT_SCHEMA)
    )
    if result.party != expected_party:
        raise ValueError(f"expected a {expected_party} review result")
    if result.transaction_id != expected_transaction_id:
        raise ValueError("review result transaction does not match")
    if result.agreement_version != expected_version:
        raise ValueError("review result version does not match")
    if result.agreement_hash != expected_hash:
        raise ValueError("review result hash does not match")
    return result


def wrap_verifund_task_request(request: VerifundTaskRequest) -> dict[str, Any]:
    return _wrap(VERIFUND_TASK_REQUEST_SCHEMA, request)


def parse_verifund_task_request(envelope: dict[str, Any]) -> VerifundTaskRequest:
    return VerifundTaskRequest.model_validate(
        _unwrap(envelope, VERIFUND_TASK_REQUEST_SCHEMA)
    )


def wrap_verifund_task_result(result: VerifundTaskResult) -> dict[str, Any]:
    return _wrap(VERIFUND_TASK_RESULT_SCHEMA, result)


def parse_verifund_task_result(envelope: dict[str, Any]) -> VerifundTaskResult:
    return VerifundTaskResult.model_validate(
        _unwrap(envelope, VERIFUND_TASK_RESULT_SCHEMA)
    )
```

- [ ] **Step 5: Add `buyer_review()` and re-exports**

In `client.py`, import `BuyerAgreementReviewRequest` and `TransactionProjection`, then add:

```python
    async def buyer_review(
        self,
        transaction_id: str,
        request: BuyerAgreementReviewRequest,
        *,
        actor: str,
        idempotency_key: str | None = None,
    ) -> TransactionProjection:
        return TransactionProjection.model_validate(
            await self._request(
                "POST",
                f"/transactions/{transaction_id}/buyer-review",
                body=request.model_dump(mode="json"),
                actor=actor,
                idempotency_key=idempotency_key,
            )
        )
```

`__init__.py` must re-export the A2A helpers:

```python
from verifund_contracts.a2a import *  # noqa: F403
from verifund_contracts.client import VerifundClient, VerifundError
from verifund_contracts.models import *  # noqa: F403
```

- [ ] **Step 6: Run the contract tests**

Run: `uv run pytest tests/unit/test_verifund_contracts.py tests/unit/test_verifund_a2a_contracts.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/verifund_contracts/verifund_contracts/{models.py,a2a.py,client.py,__init__.py} tests/unit/test_verifund_a2a_contracts.py
git commit -m "feat(verifund): bind agreement reviews and HITL decisions to one hash"
```

---

### Task 2: Add optional settlement fields to A2A contracts

**Files:**
- Modify: `packages/commerce_core/commerce_core/contracts.py:159-164,183-193`
- Test: `tests/protocol/test_settlement_contracts.py`

**Interfaces:**
- Produces: `AcceptOffer.settlement_transaction_id: str | None`, `AcceptOffer.agreement_hash: str | None`, `AcceptOffer.settlement_token: str | None`; the same three optional fields on `PurchaseOrderRequest`.
- Consumes: nothing.

- [ ] **Step 1: Write failing compatibility tests**

`tests/protocol/test_settlement_contracts.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/protocol/test_settlement_contracts.py -v`
Expected: FAIL with `ValidationError` for the new fields (`extra_forbidden`).

- [ ] **Step 3: Add the optional fields**

Modify `AcceptOffer` so it ends with:

```python
    settlement_transaction_id: str | None = None
    agreement_hash: str | None = None
    settlement_token: str | None = None
```

Modify `PurchaseOrderRequest` so it ends with the same three fields.

Do not change any default, validator, or existing field. Old JSON must validate because all three default to `None`.

- [ ] **Step 4: Run protocol and existing contract tests**

Run: `uv run pytest tests/protocol/test_settlement_contracts.py tests/unit/test_contracts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/contracts.py tests/protocol/test_settlement_contracts.py
git commit -m "feat(commerce): add optional settlement fields to A2A contracts"
```

---

### Task 3: Replace the word ban with a parent-backend guard

**Files:**
- Modify: `scripts/check_standalone.py` (replace whole file)
- Modify: `tests/test_standalone.py`
- Test: `tests/test_standalone.py`

**Interfaces:**
- Produces: `scan_text(name: str, text: str) -> list[str]`, `FORBIDDEN_IMPORTS`, `FORBIDDEN_PATH_FRAGMENTS`, `main() -> int`.
- Consumes: nothing.

- [ ] **Step 1: Write failing guard tests**

Replace `tests/test_standalone.py`:

```python
import subprocess
import sys
from pathlib import Path

from scripts.check_standalone import scan_text

ROOT = Path(__file__).resolve().parents[1]


def test_repository_has_no_parent_backend_references():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_standalone.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_guard_allows_verifund_names():
    assert scan_text(
        "apps/verifund_control_plane/app.py",
        "from verifund_contracts.models import AwardRequest\n"
        "import verifund_control_plane.settings\n",
    ) == []


def test_guard_rejects_parent_imports():
    assert scan_text(
        "apps/buyer_agent/settlement.py",
        "from verifund.platform import money\n",
    )
    assert scan_text(
        "apps/buyer_agent/settlement.py",
        "from verifund_platform_backend.services import capture\n",
    )
    assert scan_text(
        "apps/buyer_agent/settlement.py",
        "import src.verifund.ledger\n",
    )


def test_guard_rejects_parent_paths():
    assert scan_text(
        "Makefile",
        "PYTHONPATH=../verifund-platform-backend\n",
    )


def test_guard_ignores_binary_and_generated_paths():
    assert scan_text("data/verifund.db", "verifund-platform-backend") == []
    assert scan_text("apps/console/.next/trace", "verifund-platform-backend") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_standalone.py -v`
Expected: FAIL (`scan_text` does not exist) and the repository guard fails on legitimate `verifund` text.

- [ ] **Step 3: Replace the guard**

`scripts/check_standalone.py`:

```python
"""Reject runtime references to the parent Verifund backend."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORTS = (
    re.compile(r"^\s*(from|import)\s+verifund(\.|\s|$)"),
    re.compile(r"^\s*(from|import)\s+verifund_platform_backend(\.|\s|$)"),
    re.compile(r"^\s*(from|import)\s+src\.verifund(\.|\s|$)"),
)
FORBIDDEN_PATH_FRAGMENTS = (
    "verifund-platform-backend",
    "../verifund-platform-backend",
    "/verifund-platform-backend/",
)
SKIP_PREFIXES = (
    "docs/",
    "data/",
    "apps/console/.next/",
    "apps/console/node_modules/",
    ".venv/",
    "uv.lock",
)
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
    ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".woff",
    ".woff2", ".ttf", ".zip", ".gz",
}


def scan_text(name: str, text: str) -> list[str]:
    if name.startswith(SKIP_PREFIXES) or Path(name).suffix.lower() in BINARY_SUFFIXES:
        return []
    findings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in FORBIDDEN_IMPORTS:
            if pattern.search(line):
                findings.append(f"{name}:{line_number}: parent backend import")
        for fragment in FORBIDDEN_PATH_FRAGMENTS:
            if fragment in line:
                findings.append(f"{name}:{line_number}: parent backend path")
    return findings


def main() -> int:
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        text=True,
    ).splitlines()
    findings: list[str] = []
    for name in files:
        path = Path(name)
        if not path.is_file():
            continue
        if name.startswith(SKIP_PREFIXES) or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        findings.extend(scan_text(name, text))
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the guard suite**

Run: `uv run pytest tests/test_standalone.py -v && uv run python scripts/check_standalone.py`
Expected: PASS and no output from the script.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_standalone.py tests/test_standalone.py
git commit -m "chore: guard against parent backend imports instead of banning verifund"
```

---

## Phase 1 — Control plane

### Task 4: Control-plane package, settings, DB, errors, and health app

**Files:**
- Create: `apps/verifund_control_plane/pyproject.toml`
- Create: `apps/verifund_control_plane/verifund_control_plane/__init__.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/__main__.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/settings.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/db.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/errors.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/api/__init__.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/api/health.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Modify: `pyproject.toml` (add `apps/verifund_control_plane` member)
- Test: `tests/unit/test_verifund_settings.py`

**Interfaces:**
- Produces: `Settings`, `Settings.validate_for_mode()`, `create_app(settings=None, *, clock=None) -> FastAPI`, `VerifundError`, `error_response`, `create_engine`, `configure_sqlite`.
- Consumes: `VerifundErrorCode` from Task 1.

- [ ] **Step 1: Write failing settings and health tests**

`tests/unit/test_verifund_settings.py`:

```python
from datetime import UTC, datetime

import httpx
import pytest

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def sandbox_settings(**overrides):
    values = {
        "mode": "sandbox",
        "ops_token": "x" * 40,
        "seller_token_secret": "s" * 40,
        "link_secret": "l" * 40,
        "receipt_keys": {"test-1": "r" * 40},
        "receipt_active_kid": "test-1",
        "paypal_api_base": "https://api-m.sandbox.paypal.com",
        "paypal_client_id": "client",
        "paypal_client_secret": "secret",
        "paypal_webhook_id": "wh-1",
        "seller_payout_emails": {
            "northwind-audio": "northwind@example.test",
            "circuitforge": "circuitforge@example.test",
            "aurora-supply": "aurora@example.test",
            "summit-tech": "summit@example.test",
        },
        "public_base_url": "https://verifund.example.test",
    }
    values.update(overrides)
    return Settings(**values)


def test_default_mode_is_off():
    assert Settings().mode == "off"


def test_sandbox_rejects_default_ops_token():
    with pytest.raises(ValueError, match="VERIFUND_OPS_TOKEN"):
        sandbox_settings(ops_token="dev-verifund-ops").validate_for_mode()


def test_sandbox_rejects_live_paypal_host():
    with pytest.raises(ValueError, match="sandbox"):
        sandbox_settings(paypal_api_base="https://api-m.paypal.com").validate_for_mode()


def test_sandbox_requires_payout_email():
    with pytest.raises(ValueError, match="payout"):
        sandbox_settings(seller_payout_emails={}).validate_for_mode()


def test_sandbox_accepts_valid_settings():
    sandbox_settings().validate_for_mode()


async def test_health_and_ready(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/health")).json()["status"] == "ok"
            assert (await client.get("/ready")).status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifund_control_plane'`.

- [ ] **Step 3: Create the package and entry point**

`apps/verifund_control_plane/pyproject.toml`:

```toml
[project]
name = "verifund-control-plane"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "verifund-contracts",
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "pydantic-settings>=2.6,<3",
  "sqlalchemy[asyncio]>=2.0,<3",
  "aiosqlite>=0.20,<1",
  "httpx>=0.27,<1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["verifund_control_plane"]

[tool.uv.sources]
verifund-contracts = { workspace = true }
```

Root `pyproject.toml` workspace members now include:

```toml
  "apps/verifund_control_plane",
```

`apps/verifund_control_plane/verifund_control_plane/__init__.py` is empty.

`apps/verifund_control_plane/verifund_control_plane/__main__.py`:

```python
from __future__ import annotations

import uvicorn

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings


def main() -> None:
    settings = Settings()
    settings.validate_for_mode()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        workers=1,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Implement settings**

`apps/verifund_control_plane/verifund_control_plane/settings.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRETS = {
    "dev-verifund-ops",
    "dev-verifund-seller-token-secret",
    "dev-verifund-link-secret",
    "dev-verifund-fake-webhook",
    "dev-1",
}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True, case_sensitive=False
    )

    mode: Literal["off", "fake", "sandbox"] = Field(
        default="off", validation_alias="VERIFUND_MODE"
    )
    service_name: str = "verifund-control-plane"
    host: str = Field(default="127.0.0.1", validation_alias="HOST")
    port: int = Field(default=9300, validation_alias="VERIFUND_PORT")
    public_base_url: str = Field(
        default="http://127.0.0.1:9300", validation_alias="VERIFUND_PUBLIC_BASE_URL"
    )
    console_base_url: str = Field(
        default="http://127.0.0.1:3000", validation_alias="VERIFUND_CONSOLE_BASE_URL"
    )
    allow_public_bind: bool = Field(
        default=False, validation_alias="VERIFUND_ALLOW_PUBLIC_BIND"
    )

    ops_token: str = Field(
        default="dev-verifund-ops", validation_alias="VERIFUND_OPS_TOKEN"
    )
    seller_token_secret: str = Field(
        default="dev-verifund-seller-token-secret",
        validation_alias="VERIFUND_SELLER_TOKEN_SECRET",
    )
    link_secret: str = Field(
        default="dev-verifund-link-secret", validation_alias="VERIFUND_LINK_SECRET"
    )
    receipt_keys: dict[str, str] = Field(
        default_factory=lambda: {"dev-1": "dev-verifund-receipt-key"},
        validation_alias="VERIFUND_RECEIPT_KEYS",
    )
    receipt_active_kid: str = Field(
        default="dev-1", validation_alias="VERIFUND_RECEIPT_ACTIVE_KID"
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/verifund.db",
        validation_alias="VERIFUND_DATABASE_URL",
    )
    evidence_dir: Path = Field(
        default=Path("./data/evidence"), validation_alias="VERIFUND_EVIDENCE_DIR"
    )
    max_evidence_bytes: int = Field(
        default=25_000_000, validation_alias="VERIFUND_MAX_EVIDENCE_BYTES"
    )

    seller_token_ttl_hours: int = Field(
        default=72, validation_alias="VERIFUND_SELLER_TOKEN_TTL_HOURS"
    )
    checkout_link_ttl_minutes: int = Field(
        default=30, validation_alias="VERIFUND_CHECKOUT_LINK_TTL_MINUTES"
    )
    return_link_ttl_hours: int = Field(
        default=24, validation_alias="VERIFUND_RETURN_LINK_TTL_HOURS"
    )
    evidence_deadline_hours: int = Field(
        default=72, validation_alias="VERIFUND_EVIDENCE_DEADLINE_HOURS"
    )
    inspection_window_hours: int = Field(
        default=24, validation_alias="VERIFUND_INSPECTION_WINDOW_HOURS"
    )
    funding_timeout_hours: int = Field(
        default=24, validation_alias="VERIFUND_FUNDING_TIMEOUT_HOURS"
    )
    payout_alert_hours: int = Field(
        default=1, validation_alias="VERIFUND_PAYOUT_ALERT_HOURS"
    )

    paypal_env: str = Field(default="sandbox", validation_alias="PAYPAL_ENV")
    paypal_api_base: str = Field(
        default="https://api-m.sandbox.paypal.com", validation_alias="PAYPAL_API_BASE"
    )
    paypal_client_id: str = Field(default="", validation_alias="PAYPAL_CLIENT_ID")
    paypal_client_secret: str = Field(
        default="", validation_alias="PAYPAL_CLIENT_SECRET"
    )
    paypal_webhook_id: str = Field(
        default="", validation_alias="PAYPAL_WEBHOOK_ID"
    )
    paypal_platform_email: str = Field(
        default="", validation_alias="PAYPAL_PLATFORM_EMAIL"
    )
    paypal_buyer_email: str = Field(
        default="", validation_alias="PAYPAL_BUYER_EMAIL"
    )
    seller_payout_emails: dict[str, str] = Field(
        default_factory=dict, validation_alias="VERIFUND_SELLER_PAYOUT_EMAILS"
    )

    reconciler_enabled: bool = Field(
        default=True, validation_alias="VERIFUND_RECONCILER_ENABLED"
    )
    reconciler_pending_seconds: int = Field(
        default=30, validation_alias="VERIFUND_RECONCILER_PENDING_SECONDS"
    )
    reconciler_deadline_seconds: int = Field(
        default=60, validation_alias="VERIFUND_RECONCILER_DEADLINE_SECONDS"
    )
    reconciler_receipt_seconds: int = Field(
        default=300, validation_alias="VERIFUND_RECONCILER_RECEIPT_SECONDS"
    )
    fake_webhook_secret: str = Field(
        default="dev-verifund-fake-webhook",
        validation_alias="VERIFUND_FAKE_WEBHOOK_SECRET",
    )

    @property
    def is_sandbox(self) -> bool:
        return self.mode == "sandbox"

    @property
    def is_fake(self) -> bool:
        return self.mode == "fake"

    def payout_email_for(self, seller_id: str) -> str | None:
        return self.seller_payout_emails.get(seller_id)

    def require_strong_secret(self, name: str, value: str) -> None:
        if len(value.encode("utf-8")) < 32 or value in DEFAULT_SECRETS:
            raise ValueError(f"{name} must be at least 32 bytes and not a default")

    @model_validator(mode="after")
    def _validate_base(self) -> Settings:
        if self.mode == "off":
            return self
        if self.receipt_active_kid not in self.receipt_keys:
            raise ValueError("VERIFUND_RECEIPT_ACTIVE_KID must exist in VERIFUND_RECEIPT_KEYS")
        host = self.host.strip()
        if host not in LOOPBACK_HOSTS and not self.allow_public_bind:
            raise ValueError("non-loopback HOST requires VERIFUND_ALLOW_PUBLIC_BIND=1")
        return self

    def validate_for_mode(self) -> None:
        if self.mode != "sandbox":
            return
        self.require_strong_secret("VERIFUND_OPS_TOKEN", self.ops_token)
        self.require_strong_secret("VERIFUND_SELLER_TOKEN_SECRET", self.seller_token_secret)
        self.require_strong_secret("VERIFUND_LINK_SECRET", self.link_secret)
        if self.receipt_active_kid in DEFAULT_SECRETS:
            raise ValueError("VERIFUND_RECEIPT_ACTIVE_KID must not be a default")
        self.require_strong_secret(
            "VERIFUND_RECEIPT_KEYS value", self.receipt_keys[self.receipt_active_kid]
        )
        if not self.paypal_client_id or not self.paypal_client_secret:
            raise ValueError("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are required")
        if not self.paypal_webhook_id:
            raise ValueError("PAYPAL_WEBHOOK_ID is required")
        if not self.paypal_api_base.startswith("https://api-m.sandbox.paypal.com"):
            raise ValueError("PAYPAL_API_BASE must be the PayPal sandbox host")
        if urlsplit(self.paypal_api_base).hostname == "api-m.paypal.com":
            raise ValueError("live PayPal is not supported; use the sandbox host")
        if not self.public_base_url.startswith("https://"):
            raise ValueError("VERIFUND_PUBLIC_BASE_URL must be HTTPS in sandbox mode")
        if not self.seller_payout_emails:
            raise ValueError("VERIFUND_SELLER_PAYOUT_EMAILS is required for sandbox")
        payout_emails = list(self.seller_payout_emails.values())
        if len(payout_emails) != len(set(payout_emails)):
            raise ValueError("seller payout emails must be unique")
        disallowed = {self.paypal_platform_email, self.paypal_buyer_email} - {""}
        if disallowed.intersection(payout_emails):
            raise ValueError("seller payout emails must not be platform/buyer accounts")
```

- [ ] **Step 5: Implement DB and errors**

`apps/verifund_control_plane/verifund_control_plane/db.py`:

```python
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from verifund_control_plane.errors import VerifundError


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        connect_args={"timeout": 5.0},
        pool_pre_ping=True,
    )


async def configure_sqlite(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA busy_timeout=5000")


@asynccontextmanager
async def transaction(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    try:
        async with engine.begin() as conn:
            yield conn
    except OperationalError as exc:
        message = str(exc).lower()
        if "database is locked" in message or "database table is locked" in message:
            raise VerifundError("internal", "SQLite is busy; retry shortly", status_code=503, retryable=True) from exc
        raise
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise VerifundError("internal", "SQLite is busy; retry shortly", status_code=503, retryable=True) from exc
        raise
```

`apps/verifund_control_plane/verifund_control_plane/errors.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from verifund_contracts.models import ErrorDetail, ErrorEnvelope, VerifundErrorCode


class VerifundError(Exception):
    def __init__(
        self,
        code: str | VerifundErrorCode,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}
        self.request_id = request_id


def error_response(
    error: VerifundError, request: Request | None = None
) -> JSONResponse:
    request_id = error.request_id or (
        request.headers.get("x-request-id") if request is not None else None
    )
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            details=error.details,
            request_id=request_id,
        )
    )
    headers = {"retry-after": "1"} if error.retryable else None
    return JSONResponse(
        status_code=error.status_code,
        content=envelope.model_dump(mode="json"),
        headers=headers,
    )


async def verifund_error_handler(request: Request, exc: VerifundError) -> JSONResponse:
    return error_response(exc, request)
```

- [ ] **Step 6: Implement the app and health router**

`apps/verifund_control_plane/verifund_control_plane/api/health.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "verifund-control-plane"}


@router.get("/ready")
async def ready(request: Request) -> dict:
    engine = request.app.state.engine
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ready", "service": "verifund-control-plane"}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> str:
    repo = request.app.state.repo
    count = await repo.count_transactions()
    return (
        "# HELP verifund_transactions Number of transactions.\n"
        "# TYPE verifund_transactions gauge\n"
        f"verifund_transactions {count}\n"
    )
```

`apps/verifund_control_plane/verifund_control_plane/app.py` (first slice; later tasks mount more routers):

```python
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Callable

from fastapi import FastAPI

from verifund_control_plane.api import health
from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.errors import VerifundError, verifund_error_handler
from verifund_control_plane.settings import Settings


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    settings.validate_for_mode()
    now = clock or (lambda: datetime.now(UTC))
    engine = create_engine(settings.database_url)
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await configure_sqlite(engine)
        if hasattr(app.state, "repo"):
            await app.state.repo.create_schema()
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Verifund Control Plane", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.clock = now
    app.add_exception_handler(VerifundError, verifund_error_handler)
    app.include_router(health.router)
    return app
```

Task 6 adds `app.state.repo` and the schema creation. Until then `/metrics` would fail; tests only hit health/ready.

- [ ] **Step 7: Run the settings/health tests**

Run: `uv lock && uv sync --all-packages && uv run pytest tests/unit/test_verifund_settings.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock apps/verifund_control_plane tests/unit/test_verifund_settings.py
git commit -m "feat(verifund): scaffold control plane settings, db, and health app"
```

---

### Task 5: Domain state machine, canonical hashing, and ledger rules

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/domain.py`
- Test: `tests/unit/test_verifund_domain.py`

**Interfaces:**
- Produces: `ALLOWED_TRANSITIONS`, `TERMINAL_STATES`, `REVIEWABLE_STATES`, `NON_OVERRIDABLE_REASONS`, `canonical_json`, `agreement_hash`, `build_agreement`, `validate_award`, `validate_agreement_review`, `record_buyer_review`, `record_seller_decision`, `capture_ledger_entries`, `payout_ledger_entries`, `allowed_actions`, `stage_for_state`, `TransactionRecord`, `assert_transition`.
- Consumes: `AwardRequest`, `TransactionState`, `ReviewReason` from Task 1.

- [ ] **Step 1: Write failing domain tests**

`tests/unit/test_verifund_domain.py`:

```python
from datetime import UTC, datetime

import pytest

from verifund_contracts import (
    AwardRequest,
    CancelReason,
    ReviewReason,
    TransactionState,
)
from verifund_control_plane.domain import (
    ALLOWED_TRANSITIONS,
    NON_OVERRIDABLE_REASONS,
    agreement_hash,
    allowed_actions,
    assert_transition,
    build_agreement,
    capture_ledger_entries,
    payout_ledger_entries,
    stage_for_state,
    validate_award,
)
from verifund_control_plane.errors import VerifundError

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award() -> AwardRequest:
    return AwardRequest(
        run_id="run-1",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        offer_id="offer-1",
        currency="USD",
        amount_cents=123400,
        shipping_cents=3400,
        quantity=12,
        line_items=[
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        delivery_days=7,
        warranty_months=24,
        returns_days=30,
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TransactionState.AWARDED, TransactionState.AGREED),
        (TransactionState.AWARDED, TransactionState.CANCELED),
        (TransactionState.AGREED, TransactionState.FUNDING_PENDING),
        (TransactionState.FUNDING_PENDING, TransactionState.FUNDED),
        (TransactionState.FUNDED, TransactionState.FULFILLMENT_PENDING),
        (TransactionState.FULFILLMENT_PENDING, TransactionState.VERIFICATION_PENDING),
        (TransactionState.VERIFICATION_PENDING, TransactionState.RELEASE_PERMITTED),
        (TransactionState.VERIFICATION_PENDING, TransactionState.REVIEW_REQUIRED),
        (TransactionState.RELEASE_PERMITTED, TransactionState.PAYOUT_PENDING),
        (TransactionState.PAYOUT_PENDING, TransactionState.RELEASED),
        (TransactionState.PAYOUT_PENDING, TransactionState.FAILED),
        (TransactionState.REVIEW_REQUIRED, TransactionState.PAYOUT_PENDING),
        (TransactionState.REVIEW_REQUIRED, TransactionState.CANCELED),
        (TransactionState.CANCELED, TransactionState.REVIEW_REQUIRED),
        (TransactionState.FAILED, TransactionState.REVIEW_REQUIRED),
        (TransactionState.RELEASED, TransactionState.REVIEW_REQUIRED),
    ],
)
def test_allowed_transitions(current, target):
    assert target in ALLOWED_TRANSITIONS[current]


def test_illegal_transition_returns_conflict():
    with pytest.raises(VerifundError) as raised:
        assert_transition(TransactionState.AWARDED, TransactionState.RELEASED)
    assert raised.value.code == "invalid_state"
    assert raised.value.status_code == 409


def test_agreement_hash_is_stable_and_order_independent():
    agreement = build_agreement("vf_1", award(), NOW)
    reordered = dict(reversed(list(agreement.items())))
    assert agreement_hash(agreement) == agreement_hash(reordered)
    assert len(agreement_hash(agreement)) == 64


def test_build_agreement_excludes_shipping_address_and_secrets():
    agreement = build_agreement("vf_1", award(), NOW)
    assert "shipping_address" not in agreement
    assert "card" not in agreement
    assert agreement["amount_cents"] == 123400
    assert agreement["created_at"] == "2026-10-27T12:00:00Z"


def test_validate_award_rejects_total_mismatch():
    request = award().model_copy(update={"amount_cents": 123401})
    with pytest.raises(VerifundError) as raised:
        validate_award(request)
    assert raised.value.code == "invalid_request"


def test_ledger_entries_balance():
    capture = capture_ledger_entries("txn-1", 123400)
    assert sum(entry["debit_cents"] for entry in capture) == 123400
    assert sum(entry["credit_cents"] for entry in capture) == 123400
    payout = payout_ledger_entries("txn-1", 123400)
    assert sum(entry["debit_cents"] for entry in payout) == 123400
    assert sum(entry["credit_cents"] for entry in payout) == 123400


def test_non_overridable_reasons_match_spec():
    assert NON_OVERRIDABLE_REASONS == {
        ReviewReason.FUNDING_MISMATCH,
        ReviewReason.LEDGER_INCOMPLETE,
        ReviewReason.LATE_CAPTURE,
    }


def test_allowed_actions_are_actor_specific():
    assert "upload_evidence" in allowed_actions(TransactionState.FUNDED, "seller")
    assert "release" not in allowed_actions(TransactionState.FUNDED, "seller")
    assert "release" in allowed_actions(TransactionState.RELEASE_PERMITTED, "buyer")
    assert "refund" not in allowed_actions(TransactionState.RELEASED, "buyer")


def test_stage_mapping():
    assert stage_for_state(TransactionState.REVIEW_REQUIRED) == "review_required"
    assert stage_for_state(TransactionState.CANCELED) == "canceled"
    assert stage_for_state(TransactionState.RELEASED) == "released"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_domain.py -v`
Expected: FAIL with `ModuleNotFoundError` for `verifund_control_plane.domain`.

- [ ] **Step 3: Implement the domain module**

`apps/verifund_control_plane/verifund_control_plane/domain.py`:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from verifund_contracts.models import (
    AwardRequest,
    CancelReason,
    ReviewReason,
    TransactionState,
)

from verifund_control_plane.errors import VerifundError

TERMINAL_STATES = {
    TransactionState.RELEASED,
    TransactionState.CANCELED,
    TransactionState.FAILED,
}
NON_TERMINAL_STATES = set(TransactionState) - TERMINAL_STATES

ALLOWED_TRANSITIONS: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.AWARDED: frozenset(
        {TransactionState.AGREED, TransactionState.CANCELED, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.AGREED: frozenset(
        {TransactionState.FUNDING_PENDING, TransactionState.CANCELED, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.FUNDING_PENDING: frozenset(
        {TransactionState.FUNDED, TransactionState.FAILED, TransactionState.CANCELED, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.FUNDED: frozenset(
        {TransactionState.FULFILLMENT_PENDING, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.FULFILLMENT_PENDING: frozenset(
        {TransactionState.VERIFICATION_PENDING, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.VERIFICATION_PENDING: frozenset(
        {TransactionState.RELEASE_PERMITTED, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.RELEASE_PERMITTED: frozenset(
        {TransactionState.PAYOUT_PENDING, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.PAYOUT_PENDING: frozenset(
        {TransactionState.RELEASED, TransactionState.FAILED, TransactionState.REVIEW_REQUIRED}
    ),
    TransactionState.RELEASED: frozenset({TransactionState.REVIEW_REQUIRED}),
    TransactionState.REVIEW_REQUIRED: frozenset(
        {
            TransactionState.RELEASE_PERMITTED,
            TransactionState.PAYOUT_PENDING,
            TransactionState.RELEASED,
            TransactionState.CANCELED,
        }
    ),
    TransactionState.CANCELED: frozenset({TransactionState.REVIEW_REQUIRED}),
    TransactionState.FAILED: frozenset({TransactionState.REVIEW_REQUIRED}),
}

NON_OVERRIDABLE_REASONS = {
    ReviewReason.FUNDING_MISMATCH,
    ReviewReason.LEDGER_INCOMPLETE,
    ReviewReason.LATE_CAPTURE,
}
REQUIRED_EVIDENCE = ("shipment_manifest", "delivery_confirmation")
EVIDENCE_UPLOAD_STATES = {
    TransactionState.FUNDED,
    TransactionState.FULFILLMENT_PENDING,
    TransactionState.VERIFICATION_PENDING,
}
CAPTURELESS_CANCEL_STATES = {
    TransactionState.AWARDED,
    TransactionState.AGREED,
    TransactionState.FUNDING_PENDING,
    TransactionState.REVIEW_REQUIRED,
}

STAGE_BY_STATE: dict[TransactionState, str] = {
    TransactionState.AWARDED: "awarded",
    TransactionState.AGREED: "agreed",
    TransactionState.FUNDING_PENDING: "funding_pending",
    TransactionState.FUNDED: "funded",
    TransactionState.FULFILLMENT_PENDING: "fulfillment_pending",
    TransactionState.VERIFICATION_PENDING: "verification_pending",
    TransactionState.RELEASE_PERMITTED: "release_permitted",
    TransactionState.PAYOUT_PENDING: "payout_pending",
    TransactionState.RELEASED: "released",
    TransactionState.REVIEW_REQUIRED: "review_required",
    TransactionState.CANCELED: "canceled",
    TransactionState.FAILED: "failed",
}


@dataclass
class TransactionRecord:
    transaction_id: str
    run_id: str
    buyer_id: str
    seller_id: str
    offer_id: str
    state: TransactionState
    version: int
    last_seq: int
    amount_cents: int
    currency: str
    agreement_id: str
    agreement_hash: str
    agreement_version: int
    seller_decision: dict[str, Any] | None
    approval: dict[str, Any] | None
    funding: dict[str, Any] | None
    purchase_order: dict[str, Any] | None
    evidence_summary: dict[str, Any] | None
    verification: dict[str, Any] | None
    payout: dict[str, Any] | None
    receipt: dict[str, Any] | None
    deadlines: dict[str, Any]
    last_error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


def assert_transition(current: TransactionState, target: TransactionState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise VerifundError(
            "invalid_state",
            f"cannot transition from {current.value} to {target.value}",
            status_code=409,
        )


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def agreement_hash(agreement: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(agreement))


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_agreement(
    transaction_id: str, award: AwardRequest, created_at: datetime
) -> dict[str, Any]:
    return {
        "agreement_version": 1,
        "transaction_id": transaction_id,
        "run_id": award.run_id,
        "buyer_id": award.buyer_id,
        "seller_id": award.seller_id,
        "offer_id": award.offer_id,
        "currency": award.currency,
        "amount_cents": award.amount_cents,
        "quantity": award.quantity,
        "line_items": [
            {
                "sku": item.sku,
                "name": item.name,
                "quantity": item.quantity,
                "unit_price_cents": item.unit_price_cents,
                "warranty_addon_cents": item.warranty_addon_cents,
            }
            for item in award.line_items
        ],
        "shipping_cents": award.shipping_cents,
        "delivery_days": award.delivery_days,
        "warranty_months": award.warranty_months,
        "returns_days": award.returns_days,
        "created_at": _iso(created_at),
    }


def validate_award(award: AwardRequest) -> None:
    line_quantity = sum(item.quantity for item in award.line_items)
    line_total = sum(
        (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
        for item in award.line_items
    )
    if line_quantity != award.quantity:
        raise VerifundError("invalid_request", "quantity does not match line items")
    if line_total + award.shipping_cents != award.amount_cents:
        raise VerifundError("invalid_request", "amount does not match line items plus shipping")
    if award.currency != "USD":
        raise VerifundError("invalid_request", "only USD is supported")


def capture_ledger_entries(transaction_id: str, amount_cents: int) -> list[dict[str, Any]]:
    return [
        {
            "transaction_id": transaction_id,
            "operation": "capture",
            "account": "platform_cash",
            "debit_cents": amount_cents,
            "credit_cents": 0,
        },
        {
            "transaction_id": transaction_id,
            "operation": "capture",
            "account": "held_funds",
            "debit_cents": 0,
            "credit_cents": amount_cents,
        },
    ]


def payout_ledger_entries(transaction_id: str, amount_cents: int) -> list[dict[str, Any]]:
    return [
        {
            "transaction_id": transaction_id,
            "operation": "payout",
            "account": "held_funds",
            "debit_cents": amount_cents,
            "credit_cents": 0,
        },
        {
            "transaction_id": transaction_id,
            "operation": "payout",
            "account": "seller_paid",
            "debit_cents": 0,
            "credit_cents": amount_cents,
        },
    ]


def allowed_actions(state: TransactionState, actor: str) -> list[str]:
    if actor == "seller":
        return ["upload_evidence"] if state in EVIDENCE_UPLOAD_STATES else []
    actions: dict[TransactionState, list[str]] = {
        TransactionState.AWARDED: [
            "report_accept", "report_reject", "cancel", "flag_review", "reissue_seller_token"
        ],
        TransactionState.AGREED: [
            "approve", "cancel", "flag_review", "reissue_seller_token"
        ],
        TransactionState.FUNDING_PENDING: [
            "refresh_funding", "cancel", "flag_review"
        ],
        TransactionState.FUNDED: ["report_purchase_order", "flag_review"],
        TransactionState.FULFILLMENT_PENDING: [
            "verify", "flag_review", "reissue_seller_token"
        ],
        TransactionState.VERIFICATION_PENDING: [
            "verify", "flag_review", "reissue_seller_token"
        ],
        TransactionState.RELEASE_PERMITTED: ["release", "flag_review"],
        TransactionState.PAYOUT_PENDING: ["refresh_payout", "flag_review"],
        TransactionState.REVIEW_REQUIRED: [
            "release", "retry_payout", "cancel", "flag_review"
        ],
        TransactionState.RELEASED: ["receipt"],
        TransactionState.CANCELED: [],
        TransactionState.FAILED: [],
    }
    return actions[state]


def stage_for_state(state: TransactionState) -> str:
    return STAGE_BY_STATE[state]
```

`CancelReason` is imported but unused in domain; remove it. The plan code must be clean. Remove `CancelReason` from imports.

- [ ] **Step 4: Run the domain tests**

Run: `uv run pytest tests/unit/test_verifund_domain.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/domain.py tests/unit/test_verifund_domain.py
git commit -m "feat(verifund): add state machine, agreement hashing, and ledger rules"
```

### Task 6: Control-plane schema, transaction persistence, agreement reviews, events, and idempotency

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Test: `tests/unit/test_verifund_repository.py`

**Interfaces:**
- Produces: `Repository`, `EventInput`, `AuditInput`, `AgreementReviewInput`, `Repository.transaction()`, `create_schema`, `insert_transaction`, `get_transaction`, `list_transactions`, `count_transactions`, `transition`, `update_transaction`, `append_event`, `record_agreement_review`, `get_agreement_reviews`, `get_idempotency`, `put_idempotency`, `audit`; append-only `agreement_reviews` rows keyed by transaction, version/hash, party, and idempotency key.
- Consumes: `TransactionRecord`, `assert_transition`, `TransactionState` from Task 5.

- [ ] **Step 1: Write failing repository tests**

`tests/unit/test_verifund_repository.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from verifund_contracts import TransactionState
from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import AuditInput, EventInput, Repository

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def record() -> TransactionRecord:
    return TransactionRecord(
        transaction_id="vf_1",
        run_id="run-1",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        offer_id="offer-1",
        state=TransactionState.AWARDED,
        version=1,
        last_seq=0,
        amount_cents=123400,
        currency="USD",
        agreement_id="agr_1",
        agreement_hash="a" * 64,
        agreement_version=1,
        seller_decision=None,
        approval=None,
        funding=None,
        purchase_order=None,
        evidence_summary=None,
        verification=None,
        payout=None,
        receipt=None,
        deadlines={"funding": (NOW + timedelta(hours=24)).isoformat()},
        last_error=None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
async def repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}")
    await configure_sqlite(engine)
    repository = Repository(engine)
    await repository.create_schema()
    try:
        yield repository
    finally:
        await engine.dispose()


async def test_insert_and_read_transaction(repo):
    txn = record()
    async with repo.transaction() as conn:
        await repo.insert_transaction(
            conn,
            txn,
            agreement={"agreement_version": 1, "amount_cents": 123400},
            events=[EventInput("award_created", {"run_id": "run-1"}, "buyer-agent")],
            audit=AuditInput("buyer-agent", "award_created"),
        )
    loaded = await repo.get_transaction("vf_1")
    assert loaded.state == TransactionState.AWARDED
    assert loaded.last_seq == 1
    events = await repo.events("vf_1")
    assert events[0]["type"] == "award_created"
    assert events[0]["seq"] == 1


async def test_transition_enforces_version_and_state(repo):
    async with repo.transaction() as conn:
        await repo.insert_transaction(conn, record(), agreement={}, events=[])
    async with repo.transaction() as conn:
        updated = await repo.transition(
            conn,
            "vf_1",
            expected_version=1,
            expected_state=TransactionState.AWARDED,
            new_state=TransactionState.AGREED,
            changes={"approval": {"approved_by": "demo"}},
            events=[EventInput("seller_accepted", {}, "buyer-agent")],
        )
    assert updated.state == TransactionState.AGREED
    assert updated.version == 2
    assert updated.last_seq == 1

    with pytest.raises(VerifundError) as raised:
        async with repo.transaction() as conn:
            await repo.transition(
                conn,
                "vf_1",
                expected_version=1,
                expected_state=TransactionState.AWARDED,
                new_state=TransactionState.CANCELED,
            )
    assert raised.value.code == "conflict"
    assert raised.value.status_code == 409


async def test_illegal_transition_is_invalid_state(repo):
    async with repo.transaction() as conn:
        await repo.insert_transaction(conn, record(), agreement={}, events=[])
    with pytest.raises(VerifundError) as raised:
        async with repo.transaction() as conn:
            await repo.transition(
                conn,
                "vf_1",
                expected_version=1,
                expected_state=TransactionState.AWARDED,
                new_state=TransactionState.RELEASED,
            )
    assert raised.value.code == "invalid_state"


async def test_idempotency_replays_and_rejects_body_change(repo):
    async with repo.transaction() as conn:
        await repo.put_idempotency(conn, "award", "key-1", "hash-1", {"ok": True})
    replayed = await repo.get_idempotency("award", "key-1", "hash-1")
    assert replayed == {"ok": True}
    with pytest.raises(VerifundError) as raised:
        await repo.get_idempotency("award", "key-1", "hash-2")
    assert raised.value.code == "conflict"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: verifund_control_plane.repository`.

- [ ] **Step 3: Implement the tables and core repository**

`apps/verifund_control_plane/verifund_control_plane/repository.py`:

```python
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, AsyncIterator

from sqlalchemy import (
    JSON, Column, Integer, MetaData, String, Table, UniqueConstraint, select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from verifund_contracts import TransactionState
from verifund_control_plane.db import configure_sqlite, transaction
from verifund_control_plane.domain import TransactionRecord, assert_transition
from verifund_control_plane.errors import VerifundError


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dt(value: str | None) -> datetime:
    if not value:
        raise ValueError("missing timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class EventInput:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    actor: str = "system"


@dataclass(frozen=True)
class AuditInput:
    actor: str
    action: str
    note: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class Repository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.metadata = MetaData()
        self._define_tables()

    def _define_tables(self) -> None:
        self.transactions = Table(
            "transactions", self.metadata,
            Column("transaction_id", String, primary_key=True),
            Column("run_id", String, nullable=False, index=True),
            Column("buyer_id", String, nullable=False),
            Column("seller_id", String, nullable=False, index=True),
            Column("offer_id", String, nullable=False),
            Column("state", String, nullable=False, index=True),
            Column("version", Integer, nullable=False),
            Column("last_seq", Integer, nullable=False),
            Column("amount_cents", Integer, nullable=False),
            Column("currency", String, nullable=False),
            Column("agreement_id", String, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("agreement_version", Integer, nullable=False),
            Column("buyer_agent_review", JSON, nullable=True),
            Column("seller_decision", JSON, nullable=True),
            Column("approval", JSON, nullable=True),
            Column("funding", JSON, nullable=True),
            Column("purchase_order", JSON, nullable=True),
            Column("evidence_summary", JSON, nullable=True),
            Column("verification", JSON, nullable=True),
            Column("payout", JSON, nullable=True),
            Column("receipt", JSON, nullable=True),
            Column("deadlines", JSON, nullable=False),
            Column("last_error", JSON, nullable=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.agreements = Table(
            "agreements", self.metadata,
            Column("agreement_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("version", Integer, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.agreement_reviews = Table(
            "agreement_reviews", self.metadata,
            Column("review_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("agreement_version", Integer, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("party", String, nullable=False),
            Column("decision", String, nullable=False),
            Column("task_id", String, nullable=False),
            Column("reason_code", String, nullable=True),
            Column("note", String, nullable=False),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("reviewed_at", String, nullable=False),
        )
        self.events = Table(
            "transaction_events", self.metadata,
            Column("transaction_id", String, nullable=False, primary_key=True),
            Column("seq", Integer, nullable=False, primary_key=True),
            Column("type", String, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("actor", String, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.ledger = Table(
            "ledger_entries", self.metadata,
            Column("entry_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("operation", String, nullable=False),
            Column("account", String, nullable=False),
            Column("debit_cents", Integer, nullable=False),
            Column("credit_cents", Integer, nullable=False),
            Column("currency", String, nullable=False),
            Column("provider_ref", String, nullable=True),
            Column("created_at", String, nullable=False),
        )
        self.evidence = Table(
            "evidence", self.metadata,
            Column("evidence_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("seller_id", String, nullable=False),
            Column("kind", String, nullable=False),
            Column("sha256", String, nullable=False),
            Column("media_type", String, nullable=False),
            Column("size_bytes", Integer, nullable=False),
            Column("original_filename", String, nullable=False),
            Column("note", String, nullable=True),
            Column("captured_at", String, nullable=True),
            Column("created_at", String, nullable=False),
            UniqueConstraint("transaction_id", "sha256", name="uq_evidence_txn_sha"),
        )
        self.provider_operations = Table(
            "provider_operations", self.metadata,
            Column("operation_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("kind", String, nullable=False),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("provider_id", String, nullable=True),
            Column("status", String, nullable=False),
            Column("request", JSON, nullable=False),
            Column("response", JSON, nullable=True),
            Column("attempts", Integer, nullable=False, default=0),
            Column("last_error", String, nullable=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.webhook_events = Table(
            "webhook_events", self.metadata,
            Column("event_id", String, primary_key=True),
            Column("event_type", String, nullable=False),
            Column("resource_id", String, nullable=True),
            Column("payload", JSON, nullable=False),
            Column("payload_hash", String, nullable=False),
            Column("mode", String, nullable=False),
            Column("verified", Integer, nullable=False),
            Column("status", String, nullable=False),
            Column("attempts", Integer, nullable=False, default=0),
            Column("last_error", String, nullable=True),
            Column("received_at", String, nullable=False),
            Column("processed_at", String, nullable=True),
        )
        self.payout_items = Table(
            "payout_items", self.metadata,
            Column("item_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("batch_id", String, nullable=False),
            Column("sender_item_id", String, nullable=False, unique=True),
            Column("seller_email", String, nullable=False),
            Column("amount_cents", Integer, nullable=False),
            Column("currency", String, nullable=False),
            Column("status", String, nullable=False),
            Column("raw", JSON, nullable=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.idempotency = Table(
            "idempotency_keys", self.metadata,
            Column("scope", String, nullable=False, primary_key=True),
            Column("key", String, nullable=False, primary_key=True),
            Column("request_hash", String, nullable=False),
            Column("response", JSON, nullable=False),
            Column("status_code", Integer, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.seller_tokens = Table(
            "seller_tokens", self.metadata,
            Column("jti_hash", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("seller_id", String, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("scopes", JSON, nullable=False),
            Column("expires_at", String, nullable=False),
            Column("revoked_at", String, nullable=True),
            Column("created_at", String, nullable=False),
        )
        self.checkout_links = Table(
            "checkout_links", self.metadata,
            Column("jti", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("kind", String, nullable=False),
            Column("expires_at", String, nullable=False),
            Column("used_at", String, nullable=True),
            Column("created_at", String, nullable=False),
        )
        self.receipts = Table(
            "receipts", self.metadata,
            Column("transaction_id", String, primary_key=True),
            Column("payload", JSON, nullable=False),
            Column("payload_hash", String, nullable=False),
            Column("signature", String, nullable=False),
            Column("kid", String, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.audit_log = Table(
            "audit_log", self.metadata,
            Column("audit_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("actor", String, nullable=False),
            Column("action", String, nullable=False),
            Column("note", String, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.reconciler_runs = Table(
            "reconciler_runs", self.metadata,
            Column("run_id", String, primary_key=True),
            Column("started_at", String, nullable=False),
            Column("finished_at", String, nullable=True),
            Column("stats", JSON, nullable=False),
            Column("error", String, nullable=True),
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with transaction(self.engine) as conn:
            yield conn

    def _record(self, row: Any) -> TransactionRecord:
        return TransactionRecord(
            transaction_id=row.transaction_id,
            run_id=row.run_id,
            buyer_id=row.buyer_id,
            seller_id=row.seller_id,
            offer_id=row.offer_id,
            state=TransactionState(row.state),
            version=row.version,
            last_seq=row.last_seq,
            amount_cents=row.amount_cents,
            currency=row.currency,
            agreement_id=row.agreement_id,
            agreement_hash=row.agreement_hash,
            agreement_version=row.agreement_version,
            seller_decision=row.seller_decision,
            approval=row.approval,
            funding=row.funding,
            purchase_order=row.purchase_order,
            evidence_summary=row.evidence_summary,
            verification=row.verification,
            payout=row.payout,
            receipt=row.receipt,
            deadlines=row.deadlines,
            last_error=row.last_error,
            created_at=_dt(row.created_at),
            updated_at=_dt(row.updated_at),
        )

    async def count_transactions(self) -> int:
        async with self.engine.connect() as conn:
            result = await conn.execute(select(self.transactions.c.transaction_id))
            return len(result.all())

    async def get_transaction(
        self, transaction_id: str, conn: AsyncConnection | None = None
    ) -> TransactionRecord:
        statement = select(self.transactions).where(
            self.transactions.c.transaction_id == transaction_id
        )
        if conn is not None:
            row = (await conn.execute(statement)).first()
        else:
            async with self.engine.connect() as own_conn:
                row = (await own_conn.execute(statement)).first()
        if row is None:
            raise VerifundError("not_found", "transaction not found", status_code=404)
        return self._record(row)

    async def list_transactions(
        self,
        *,
        run_id: str | None = None,
        state: str | None = None,
        seller_id: str | None = None,
        limit: int = 100,
    ) -> list[TransactionRecord]:
        statement = select(self.transactions).order_by(
            self.transactions.c.created_at.desc()
        ).limit(max(1, min(limit, 500)))
        if run_id:
            statement = statement.where(self.transactions.c.run_id == run_id)
        if state:
            statement = statement.where(self.transactions.c.state == state)
        if seller_id:
            statement = statement.where(self.transactions.c.seller_id == seller_id)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [self._record(row) for row in rows]

    async def insert_transaction(
        self,
        conn: AsyncConnection,
        txn: TransactionRecord,
        *,
        agreement: dict[str, Any],
        events: list[EventInput],
        audit: AuditInput | None = None,
    ) -> None:
        await conn.execute(
            self.transactions.insert().values(
                transaction_id=txn.transaction_id,
                run_id=txn.run_id,
                buyer_id=txn.buyer_id,
                seller_id=txn.seller_id,
                offer_id=txn.offer_id,
                state=txn.state.value,
                version=txn.version,
                last_seq=len(events),
                amount_cents=txn.amount_cents,
                currency=txn.currency,
                agreement_id=txn.agreement_id,
                agreement_hash=txn.agreement_hash,
                agreement_version=txn.agreement_version,
                seller_decision=txn.seller_decision,
                approval=txn.approval,
                funding=txn.funding,
                purchase_order=txn.purchase_order,
                evidence_summary=txn.evidence_summary,
                verification=txn.verification,
                payout=txn.payout,
                receipt=txn.receipt,
                deadlines=txn.deadlines,
                last_error=txn.last_error,
                created_at=_iso(txn.created_at),
                updated_at=_iso(txn.updated_at),
            )
        )
        await conn.execute(
            self.agreements.insert().values(
                agreement_id=txn.agreement_id,
                transaction_id=txn.transaction_id,
                version=txn.agreement_version,
                payload=agreement,
                agreement_hash=txn.agreement_hash,
                created_at=_iso(txn.created_at),
            )
        )
        for seq, event in enumerate(events, start=1):
            await conn.execute(
                self.events.insert().values(
                    transaction_id=txn.transaction_id,
                    seq=seq,
                    type=event.type,
                    payload=event.payload,
                    actor=event.actor,
                    created_at=_iso(txn.created_at),
                )
            )
        if audit is not None:
            await self.audit(conn, txn.transaction_id, audit)

    async def transition(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        *,
        expected_version: int,
        expected_state: TransactionState,
        new_state: TransactionState,
        changes: dict[str, Any] | None = None,
        events: list[EventInput] | None = None,
        ledger_entries: list[dict[str, Any]] | None = None,
        audit: AuditInput | None = None,
    ) -> TransactionRecord:
        current = await self.get_transaction(transaction_id, conn)
        if current.version != expected_version or current.state != expected_state:
            raise VerifundError("conflict", "transaction changed; reload and retry", status_code=409)
        assert_transition(expected_state, new_state)
        return await self._write(
            conn, current, new_state, changes or {}, events or [], ledger_entries or [], audit
        )

    async def update_transaction(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        *,
        expected_version: int,
        changes: dict[str, Any],
        events: list[EventInput] | None = None,
        ledger_entries: list[dict[str, Any]] | None = None,
        audit: AuditInput | None = None,
    ) -> TransactionRecord:
        current = await self.get_transaction(transaction_id, conn)
        if current.version != expected_version:
            raise VerifundError("conflict", "transaction changed; reload and retry", status_code=409)
        return await self._write(
            conn, current, current.state, changes, events or [], ledger_entries or [], audit
        )

    async def _write(
        self,
        conn: AsyncConnection,
        current: TransactionRecord,
        new_state: TransactionState,
        changes: dict[str, Any],
        events: list[EventInput],
        ledger_entries: list[dict[str, Any]],
        audit: AuditInput | None,
    ) -> TransactionRecord:
        now = datetime.now(UTC)
        new_version = current.version + 1
        new_seq = current.last_seq + len(events)
        values = {
            **changes,
            "state": new_state.value,
            "version": new_version,
            "last_seq": new_seq,
            "updated_at": _iso(now),
        }
        result = await conn.execute(
            self.transactions.update()
            .where(
                self.transactions.c.transaction_id == current.transaction_id,
                self.transactions.c.version == current.version,
                self.transactions.c.state == current.state.value,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise VerifundError("conflict", "transaction changed; reload and retry", status_code=409)
        for offset, event in enumerate(events, start=1):
            await conn.execute(
                self.events.insert().values(
                    transaction_id=current.transaction_id,
                    seq=current.last_seq + offset,
                    type=event.type,
                    payload=event.payload,
                    actor=event.actor,
                    created_at=_iso(now),
                )
            )
        for entry in ledger_entries:
            await conn.execute(
                self.ledger.insert().values(
                    entry_id=f"le_{uuid.uuid4().hex}",
                    transaction_id=current.transaction_id,
                    operation=entry["operation"],
                    account=entry["account"],
                    debit_cents=int(entry["debit_cents"]),
                    credit_cents=int(entry["credit_cents"]),
                    currency=current.currency,
                    provider_ref=entry.get("provider_ref"),
                    created_at=_iso(now),
                )
            )
        if audit is not None:
            await self.audit(conn, current.transaction_id, audit)
        return await self.get_transaction(current.transaction_id, conn)

    async def append_event(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        *,
        expected_version: int,
        event: EventInput,
    ) -> TransactionRecord:
        return await self.update_transaction(
            conn,
            transaction_id,
            expected_version=expected_version,
            changes={},
            events=[event],
        )

    async def events(self, transaction_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        statement = (
            select(self.events)
            .where(self.events.c.transaction_id == transaction_id)
            .where(self.events.c.seq > after_seq)
            .order_by(self.events.c.seq)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [
            {
                "seq": row.seq,
                "type": row.type,
                "payload": row.payload,
                "actor": row.actor,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def get_idempotency(
        self, scope: str, key: str, request_hash: str
    ) -> dict[str, Any] | None:
        statement = select(self.idempotency).where(
            self.idempotency.c.scope == scope, self.idempotency.c.key == key
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(statement)).first()
        if row is None:
            return None
        if row.request_hash != request_hash:
            raise VerifundError("conflict", "idempotency key reused with a different body", status_code=409)
        return row.response

    async def put_idempotency(
        self,
        conn: AsyncConnection,
        scope: str,
        key: str,
        request_hash: str,
        response: dict[str, Any],
        status_code: int = 200,
    ) -> None:
        statement = sqlite_insert(self.idempotency).values(
            scope=scope,
            key=key,
            request_hash=request_hash,
            response=response,
            status_code=status_code,
            created_at=_iso(datetime.now(UTC)),
        ).on_conflict_do_nothing(index_elements=["scope", "key"])
        await conn.execute(statement)

    async def audit(
        self, conn: AsyncConnection, transaction_id: str, audit: AuditInput
    ) -> None:
        await conn.execute(
            self.audit_log.insert().values(
                audit_id=f"aud_{uuid.uuid4().hex}",
                transaction_id=transaction_id,
                actor=audit.actor,
                action=audit.action,
                note=audit.note,
                payload=audit.payload,
                created_at=_iso(datetime.now(UTC)),
            )
        )
```

Modify `app.py` to create the repository:

```python
from verifund_control_plane.repository import Repository
...
repo = Repository(engine)
...
app.state.repo = repo
```

Place `repo = Repository(engine)` after `engine = create_engine(...)`, and `app.state.repo = repo` with the other state assignments. The lifespan already calls `repo.create_schema()` when present.

- [ ] **Step 4: Run the repository tests and health test**

Run: `uv run pytest tests/unit/test_verifund_repository.py tests/unit/test_verifund_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_verifund_repository.py
git commit -m "feat(verifund): add schema, transaction transitions, events, and idempotency"
```

---

### Task 7: Evidence metadata, provider operations, webhooks, payouts, tokens, links, and receipts persistence

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_verifund_repository_aux.py`

**Interfaces:**
- Produces repository methods: `add_evidence`, `list_evidence`, `get_evidence`, `create_provider_operation`, `update_provider_operation`, `get_provider_operation`, `list_started_operations`, `insert_webhook_event`, `mark_webhook_event`, `list_webhook_events`, `get_webhook_event`, `upsert_payout_item`, `get_payout_item`, `list_payout_items`, `save_seller_token`, `revoke_seller_tokens`, `get_seller_token`, `create_checkout_link`, `get_checkout_link`, `consume_checkout_link`, `save_receipt`, `get_receipt`, `save_reconciler_run`, `list_reconciler_runs`, `ledger_balances`, `ledger_entries`.
- Consumes: tables from Task 6.

- [ ] **Step 1: Write failing auxiliary repository tests**

`tests/unit/test_verifund_repository_aux.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from verifund_contracts import EvidenceItem, TransactionState
from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.repository import Repository

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}")
    await configure_sqlite(engine)
    repository = Repository(engine)
    await repository.create_schema()
    try:
        yield repository
    finally:
        await engine.dispose()


def evidence(sha: str = "b" * 64) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_1",
        kind="shipment_manifest",
        sha256=sha,
        media_type="application/json",
        size_bytes=10,
        original_filename="manifest.json",
        note=None,
        created_at=NOW,
    )


async def test_evidence_dedupes_by_transaction_and_sha(repo):
    async with repo.transaction() as conn:
        first, created = await repo.add_evidence(conn, "vf_1", "northwind-audio", evidence())
        second, created_again = await repo.add_evidence(conn, "vf_1", "northwind-audio", evidence())
    assert created is True
    assert created_again is False
    assert first.evidence_id == second.evidence_id
    assert len(await repo.list_evidence("vf_1")) == 1


async def test_webhook_event_dedupe(repo):
    async with repo.transaction() as conn:
        assert await repo.insert_webhook_event(
            conn, "evt-1", "PAYMENT.CAPTURE.COMPLETED", "cap-1",
            "hash", {"id": "evt-1"}, "fake", False,
        ) is True
        assert await repo.insert_webhook_event(
            conn, "evt-1", "PAYMENT.CAPTURE.COMPLETED", "cap-1",
            "hash", {"id": "evt-1"}, "fake", False,
        ) is False
    await repo.mark_webhook_event("evt-1", "processed")
    assert (await repo.get_webhook_event("evt-1"))["status"] == "processed"


async def test_seller_token_revoke_and_checkout_consume(repo):
    expires = NOW + timedelta(hours=72)
    async with repo.transaction() as conn:
        await repo.save_seller_token(conn, "jti-1", "vf_1", "northwind-audio", "a" * 64, ["txn:read"], expires)
        await repo.create_checkout_link(conn, "link-1", "vf_1", "checkout", expires)
    assert (await repo.get_seller_token("jti-1"))["revoked_at"] is None
    async with repo.transaction() as conn:
        await repo.revoke_seller_tokens(conn, "vf_1", NOW)
    assert (await repo.get_seller_token("jti-1"))["revoked_at"] is not None
    assert await repo.consume_checkout_link("link-1", NOW) is True
    assert await repo.consume_checkout_link("link-1", NOW) is False


async def test_payout_receipt_and_ledger(repo):
    async with repo.transaction() as conn:
        await repo.upsert_payout_item(
            conn, "item-1", "vf_1", "batch-1", "txn-vf_1", "seller@example.test",
            123400, "USD", "SUCCESS", {"status": "SUCCESS"},
        )
        await repo.save_receipt(conn, "vf_1", {"receipt_version": 1}, "hash", "sig", "kid-1")
        await conn.execute(
            repo.ledger.insert().values(
                entry_id="le-1", transaction_id="vf_1", operation="capture",
                account="held_funds", debit_cents=0, credit_cents=123400,
                currency="USD", provider_ref=None, created_at=NOW.isoformat(),
            )
        )
    assert (await repo.get_payout_item("item-1"))["status"] == "SUCCESS"
    assert (await repo.get_receipt("vf_1"))["kid"] == "kid-1"
    assert (await repo.ledger_balances("vf_1"))["held_funds"] == 123400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'add_evidence'`.

- [ ] **Step 3: Add the auxiliary repository methods**

Append to `Repository`:

```python
    async def add_evidence(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        seller_id: str,
        item: EvidenceItem,
    ) -> tuple[EvidenceItem, bool]:
        statement = sqlite_insert(self.evidence).values(
            evidence_id=item.evidence_id,
            transaction_id=transaction_id,
            seller_id=seller_id,
            kind=item.kind,
            sha256=item.sha256,
            media_type=item.media_type,
            size_bytes=item.size_bytes,
            original_filename=item.original_filename,
            note=item.note,
            captured_at=None,
            created_at=_iso(item.created_at),
        ).on_conflict_do_nothing(index_elements=["transaction_id", "sha256"])
        result = await conn.execute(statement)
        if result.rowcount == 1:
            return item, True
        existing = await self.get_evidence_by_sha(transaction_id, item.sha256, conn)
        return existing, False

    async def get_evidence_by_sha(
        self, transaction_id: str, sha256: str, conn: AsyncConnection | None = None
    ) -> EvidenceItem:
        statement = select(self.evidence).where(
            self.evidence.c.transaction_id == transaction_id,
            self.evidence.c.sha256 == sha256,
        )
        if conn is not None:
            row = (await conn.execute(statement)).first()
        else:
            async with self.engine.connect() as own_conn:
                row = (await own_conn.execute(statement)).first()
        if row is None:
            raise VerifundError("not_found", "evidence not found", status_code=404)
        return self._evidence(row)

    def _evidence(self, row: Any) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=row.evidence_id,
            kind=row.kind,
            sha256=row.sha256,
            media_type=row.media_type,
            size_bytes=row.size_bytes,
            original_filename=row.original_filename,
            note=row.note,
            created_at=_dt(row.created_at),
        )

    async def list_evidence(self, transaction_id: str) -> list[EvidenceItem]:
        statement = select(self.evidence).where(
            self.evidence.c.transaction_id == transaction_id
        ).order_by(self.evidence.c.created_at)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [self._evidence(row) for row in rows]

    async def get_evidence(self, transaction_id: str, evidence_id: str) -> EvidenceItem:
        statement = select(self.evidence).where(
            self.evidence.c.transaction_id == transaction_id,
            self.evidence.c.evidence_id == evidence_id,
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(statement)).first()
        if row is None:
            raise VerifundError("not_found", "evidence not found", status_code=404)
        return self._evidence(row)

    async def create_provider_operation(
        self,
        conn: AsyncConnection,
        operation_id: str,
        transaction_id: str,
        kind: str,
        idempotency_key: str,
        request: dict[str, Any],
    ) -> None:
        now = _iso(datetime.now(UTC))
        await conn.execute(
            self.provider_operations.insert().values(
                operation_id=operation_id,
                transaction_id=transaction_id,
                kind=kind,
                idempotency_key=idempotency_key,
                provider_id=None,
                status="started",
                request=request,
                response=None,
                attempts=0,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
        )

    async def update_provider_operation(
        self,
        operation_id: str,
        *,
        status: str,
        provider_id: str | None = None,
        response: dict[str, Any] | None = None,
        last_error: str | None = None,
        increment_attempts: bool = False,
    ) -> None:
        values: dict[str, Any] = {
            "status": status,
            "provider_id": provider_id,
            "response": response,
            "last_error": last_error,
            "updated_at": _iso(datetime.now(UTC)),
        }
        statement = self.provider_operations.update().where(
            self.provider_operations.c.operation_id == operation_id
        ).values(**values)
        if increment_attempts:
            statement = statement.values(attempts=self.provider_operations.c.attempts + 1)
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def get_provider_operation(self, operation_id: str) -> dict[str, Any]:
        statement = select(self.provider_operations).where(
            self.provider_operations.c.operation_id == operation_id
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(statement)).first()
        if row is None:
            raise VerifundError("not_found", "provider operation not found", status_code=404)
        return dict(row._mapping)

    async def list_started_operations(self, limit: int = 100) -> list[dict[str, Any]]:
        statement = select(self.provider_operations).where(
            self.provider_operations.c.status == "started"
        ).limit(limit)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [dict(row._mapping) for row in rows]

    async def insert_webhook_event(
        self,
        conn: AsyncConnection,
        event_id: str,
        event_type: str,
        resource_id: str | None,
        payload_hash: str,
        payload: dict[str, Any],
        mode: str,
        verified: bool,
    ) -> bool:
        statement = sqlite_insert(self.webhook_events).values(
            event_id=event_id,
            event_type=event_type,
            resource_id=resource_id,
            payload=payload,
            payload_hash=payload_hash,
            mode=mode,
            verified=1 if verified else 0,
            status="pending",
            attempts=0,
            last_error=None,
            received_at=_iso(datetime.now(UTC)),
            processed_at=None,
        ).on_conflict_do_nothing(index_elements=["event_id"])
        result = await conn.execute(statement)
        return result.rowcount == 1

    async def mark_webhook_event(
        self, event_id: str, status: str, *, last_error: str | None = None
    ) -> None:
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "status": status,
            "last_error": last_error,
            "attempts": self.webhook_events.c.attempts + 1,
            "processed_at": _iso(now) if status in {"processed", "unmatched"} else None,
        }
        async with self.engine.begin() as conn:
            await conn.execute(
                self.webhook_events.update().where(
                    self.webhook_events.c.event_id == event_id
                ).values(**values)
            )

    async def get_webhook_event(self, event_id: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.webhook_events).where(
                    self.webhook_events.c.event_id == event_id
                )
            )).first()
        if row is None:
            raise VerifundError("not_found", "webhook event not found", status_code=404)
        return dict(row._mapping)

    async def list_webhook_events(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        statement = select(self.webhook_events).order_by(
            self.webhook_events.c.received_at
        ).limit(limit)
        if status:
            statement = statement.where(self.webhook_events.c.status == status)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [dict(row._mapping) for row in rows]

    async def upsert_payout_item(
        self,
        conn: AsyncConnection,
        item_id: str,
        transaction_id: str,
        batch_id: str,
        sender_item_id: str,
        seller_email: str,
        amount_cents: int,
        currency: str,
        status: str,
        raw: dict[str, Any],
    ) -> None:
        now = _iso(datetime.now(UTC))
        statement = sqlite_insert(self.payout_items).values(
            item_id=item_id,
            transaction_id=transaction_id,
            batch_id=batch_id,
            sender_item_id=sender_item_id,
            seller_email=seller_email,
            amount_cents=amount_cents,
            currency=currency,
            status=status,
            raw=raw,
            created_at=now,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=["item_id"],
            set_={"status": status, "raw": raw, "updated_at": now},
        )
        await conn.execute(statement)

    async def get_payout_item(self, item_id: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.payout_items).where(self.payout_items.c.item_id == item_id)
            )).first()
        if row is None:
            raise VerifundError("not_found", "payout item not found", status_code=404)
        return dict(row._mapping)

    async def list_payout_items(self, transaction_id: str) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(
                select(self.payout_items).where(
                    self.payout_items.c.transaction_id == transaction_id
                ).order_by(self.payout_items.c.created_at)
            )).all()
        return [dict(row._mapping) for row in rows]

    async def save_seller_token(
        self,
        conn: AsyncConnection,
        jti_hash: str,
        transaction_id: str,
        seller_id: str,
        agreement_hash: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> None:
        await conn.execute(
            self.seller_tokens.insert().values(
                jti_hash=jti_hash,
                transaction_id=transaction_id,
                seller_id=seller_id,
                agreement_hash=agreement_hash,
                scopes=scopes,
                expires_at=_iso(expires_at),
                revoked_at=None,
                created_at=_iso(datetime.now(UTC)),
            )
        )

    async def revoke_seller_tokens(
        self, conn: AsyncConnection, transaction_id: str, now: datetime
    ) -> None:
        await conn.execute(
            self.seller_tokens.update().where(
                self.seller_tokens.c.transaction_id == transaction_id,
                self.seller_tokens.c.revoked_at.is_(None),
            ).values(revoked_at=_iso(now))
        )

    async def get_seller_token(self, jti_hash: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.seller_tokens).where(
                    self.seller_tokens.c.jti_hash == jti_hash
                )
            )).first()
        if row is None:
            raise VerifundError("unauthorized", "seller token is not recognized", status_code=401)
        return dict(row._mapping)

    async def create_checkout_link(
        self,
        conn: AsyncConnection,
        jti: str,
        transaction_id: str,
        kind: str,
        expires_at: datetime,
    ) -> None:
        await conn.execute(
            self.checkout_links.insert().values(
                jti=jti,
                transaction_id=transaction_id,
                kind=kind,
                expires_at=_iso(expires_at),
                used_at=None,
                created_at=_iso(datetime.now(UTC)),
            )
        )

    async def get_checkout_link(self, jti: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.checkout_links).where(self.checkout_links.c.jti == jti)
            )).first()
        if row is None:
            raise VerifundError("not_found", "checkout link not found", status_code=404)
        return dict(row._mapping)

    async def consume_checkout_link(self, jti: str, now: datetime) -> bool:
        async with self.engine.begin() as conn:
            result = await conn.execute(
                self.checkout_links.update().where(
                    self.checkout_links.c.jti == jti,
                    self.checkout_links.c.used_at.is_(None),
                ).values(used_at=_iso(now))
            )
            return result.rowcount == 1

    async def save_receipt(
        self,
        conn: AsyncConnection,
        transaction_id: str,
        payload: dict[str, Any],
        payload_hash: str,
        signature: str,
        kid: str,
    ) -> None:
        statement = sqlite_insert(self.receipts).values(
            transaction_id=transaction_id,
            payload=payload,
            payload_hash=payload_hash,
            signature=signature,
            kid=kid,
            created_at=_iso(datetime.now(UTC)),
        ).on_conflict_do_update(
            index_elements=["transaction_id"],
            set_={
                "payload": payload,
                "payload_hash": payload_hash,
                "signature": signature,
                "kid": kid,
            },
        )
        await conn.execute(statement)

    async def get_receipt(self, transaction_id: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.receipts).where(
                    self.receipts.c.transaction_id == transaction_id
                )
            )).first()
        if row is None:
            raise VerifundError("not_found", "receipt not available", status_code=404)
        return dict(row._mapping)

    async def save_reconciler_run(
        self,
        run_id: str,
        started_at: datetime,
        finished_at: datetime | None,
        stats: dict[str, Any],
        error: str | None = None,
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.reconciler_runs.insert().values(
                    run_id=run_id,
                    started_at=_iso(started_at),
                    finished_at=_iso(finished_at) if finished_at else None,
                    stats=stats,
                    error=error,
                )
            )

    async def list_reconciler_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(
                select(self.reconciler_runs).order_by(
                    self.reconciler_runs.c.started_at.desc()
                ).limit(limit)
            )).all()
        return [dict(row._mapping) for row in rows]

    async def ledger_balances(self, transaction_id: str) -> dict[str, int]:
        rows = await self.ledger_entries(transaction_id)
        balances = {"held_funds": 0, "platform_cash": 0, "seller_paid": 0}
        for row in rows:
            account = row["account"]
            if account == "platform_cash":
                balances[account] += row["debit_cents"] - row["credit_cents"]
            else:
                balances[account] += row["credit_cents"] - row["debit_cents"]
        return balances

    async def ledger_entries(self, transaction_id: str) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(
                select(self.ledger).where(
                    self.ledger.c.transaction_id == transaction_id
                ).order_by(self.ledger.c.created_at)
            )).all()
        return [dict(row._mapping) for row in rows]
```

- [ ] **Step 4: Run the auxiliary repository tests**

Run: `uv run pytest tests/unit/test_verifund_repository.py tests/unit/test_verifund_repository_aux.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py tests/unit/test_verifund_repository_aux.py
git commit -m "feat(verifund): persist evidence, webhooks, payouts, tokens, and receipts"
```

---

### Task 8: Seller transaction tokens, signed links, and receipt signing

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/tokens.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/receipts.py`
- Test: `tests/unit/test_verifund_tokens.py`
- Test: `tests/unit/test_verifund_receipts.py`

**Interfaces:**
- Produces: `SellerTokenService.issue(transaction_id, seller_id, agreement_hash, scopes=None) -> IssuedToken`, `verify(token, required_scope=None) -> SellerClaims`, `SellerClaims.txn`, `.seller_id`, `.agreement_hash`, `.jti_hash`, `.expires_at`; `LinkSigner.issue(kind, transaction_id, ttl) -> IssuedLink`, `verify(token, expected_kind) -> LinkClaims`; `ReceiptSigner.sign(payload) -> SignedReceipt`, `.verify(payload, payload_hash, signature, kid) -> bool`.
- Consumes: `canonical_json` and `sha256_hex` from Task 5.

- [ ] **Step 1: Write failing token tests**

`tests/unit/test_verifund_tokens.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tokens import LinkSigner, SellerTokenService

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
SECRET = "s" * 40


def service(now=NOW):
    return SellerTokenService(SECRET, ttl_hours=72, clock=lambda: now)


def test_seller_token_round_trip_and_binding():
    issued = service().issue("vf_1", "northwind-audio", "a" * 64)
    claims = service().verify(issued.token, required_scope="evidence:write")
    assert claims.txn == "vf_1"
    assert claims.seller_id == "northwind-audio"
    assert claims.agreement_hash == "a" * 64
    assert claims.expires_at == NOW + timedelta(hours=72)


def test_seller_token_expires():
    issued = service().issue("vf_1", "northwind-audio", "a" * 64)
    later = SellerTokenService(SECRET, ttl_hours=72, clock=lambda: NOW + timedelta(hours=73))
    with pytest.raises(VerifundError) as raised:
        later.verify(issued.token)
    assert raised.value.code == "token_expired"


def test_seller_token_scope_is_enforced():
    issued = service().issue("vf_1", "northwind-audio", "a" * 64, scopes=["txn:read"])
    with pytest.raises(VerifundError) as raised:
        service().verify(issued.token, required_scope="evidence:write")
    assert raised.value.code == "token_scope_denied"


def test_seller_token_rejects_tampering():
    issued = service().issue("vf_1", "northwind-audio", "a" * 64)
    parts = issued.token.split(".")
    tampered = ".".join([parts[0], parts[1], parts[2][:-3] + "abc"])
    with pytest.raises(VerifundError) as raised:
        service().verify(tampered)
    assert raised.value.code == "unauthorized"


def test_link_signer_round_trip_and_kind():
    signer = LinkSigner(SECRET, checkout_ttl_minutes=30, return_ttl_hours=24, clock=lambda: NOW)
    link = signer.issue("checkout", "vf_1")
    claims = signer.verify(link.token, expected_kind="checkout")
    assert claims.transaction_id == "vf_1"
    with pytest.raises(VerifundError):
        signer.verify(link.token, expected_kind="return")
```

`tests/unit/test_verifund_receipts.py`:

```python
from datetime import UTC, datetime

from verifund_control_plane.receipts import ReceiptSigner, build_receipt_payload

NOW = datetime(2026, 10, 27, 12, 34, 56, tzinfo=UTC)
KEYS = {"old-1": "o" * 40, "new-2": "n" * 40}


def payload():
    return build_receipt_payload(
        transaction_id="vf_1",
        agreement_hash="a" * 64,
        amount_cents=123400,
        currency="USD",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        capture_id="CAP-1",
        payout_item_id="PAYOUT-1",
        evidence_hashes=["b" * 64],
        released_at=NOW,
    )


def test_receipt_signs_and_verifies_with_active_kid():
    signer = ReceiptSigner(KEYS, "new-2")
    signed = signer.sign(payload())
    assert signed.kid == "new-2"
    assert len(signed.payload_hash) == 64
    assert signer.verify(signed.payload, signed.payload_hash, signed.signature, signed.kid)


def test_old_key_still_verifies():
    old = ReceiptSigner(KEYS, "old-1").sign(payload())
    assert ReceiptSigner(KEYS, "new-2").verify(
        old.payload, old.payload_hash, old.signature, old.kid
    )


def test_tampered_payload_fails_verification():
    signed = ReceiptSigner(KEYS, "new-2").sign(payload())
    tampered = dict(signed.payload)
    tampered["amount_cents"] = 1
    assert not ReceiptSigner(KEYS, "new-2").verify(
        tampered, signed.payload_hash, signed.signature, signed.kid
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_tokens.py tests/unit/test_verifund_receipts.py -v`
Expected: FAIL with missing modules.

- [ ] **Step 3: Implement tokens**

`apps/verifund_control_plane/verifund_control_plane/tokens.py`:

```python
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from verifund_contracts import TransactionState

from verifund_control_plane.domain import canonical_json, sha256_hex
from verifund_control_plane.errors import VerifundError


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@dataclass(frozen=True)
class SellerClaims:
    txn: str
    seller_id: str
    agreement_hash: str
    scopes: tuple[str, ...]
    jti: str
    jti_hash: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    jti_hash: str
    expires_at: datetime


class SellerTokenService:
    def __init__(
        self,
        secret: str,
        *,
        ttl_hours: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._secret = secret.encode("utf-8")
        self._ttl = timedelta(hours=ttl_hours)
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue(
        self,
        transaction_id: str,
        seller_id: str,
        agreement_hash: str,
        *,
        scopes: tuple[str, ...] | list[str] = ("txn:read", "evidence:write"),
    ) -> IssuedToken:
        now = self._clock()
        expires = now + self._ttl
        jti = secrets.token_urlsafe(24)
        claims = {
            "typ": "seller_txn",
            "txn": transaction_id,
            "seller_id": seller_id,
            "agreement_hash": agreement_hash,
            "scope": list(scopes),
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": jti,
        }
        body = _b64url(canonical_json(claims))
        signature = _b64url(
            hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
        )
        return IssuedToken(
            token=f"v1.{body}.{signature}",
            jti=jti,
            jti_hash=sha256_hex(jti.encode("utf-8")),
            expires_at=expires,
        )

    def verify(self, token: str, *, required_scope: str | None = None) -> SellerClaims:
        try:
            version, body, signature = token.split(".")
            if version != "v1":
                raise ValueError("unsupported token version")
            expected = _b64url(
                hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(signature, expected):
                raise ValueError("bad signature")
            claims: dict[str, Any] = json.loads(_unb64url(body))
            if claims.get("typ") != "seller_txn":
                raise ValueError("wrong token type")
            issued_at = datetime.fromtimestamp(int(claims["iat"]), tz=UTC)
            expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise VerifundError("unauthorized", "seller token is invalid", status_code=401) from exc
        if expires_at <= self._clock():
            raise VerifundError("token_expired", "seller token has expired", status_code=401)
        scopes = tuple(claims.get("scope", ()))
        if required_scope is not None and required_scope not in scopes:
            raise VerifundError("token_scope_denied", "seller token scope denied", status_code=403)
        jti = str(claims["jti"])
        return SellerClaims(
            txn=str(claims["txn"]),
            seller_id=str(claims["seller_id"]),
            agreement_hash=str(claims["agreement_hash"]),
            scopes=scopes,
            jti=jti,
            jti_hash=sha256_hex(jti.encode("utf-8")),
            issued_at=issued_at,
            expires_at=expires_at,
        )


@dataclass(frozen=True)
class LinkClaims:
    kind: str
    transaction_id: str
    jti: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedLink:
    token: str
    jti: str
    expires_at: datetime


class LinkSigner:
    def __init__(
        self,
        secret: str,
        *,
        checkout_ttl_minutes: int,
        return_ttl_hours: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._secret = secret.encode("utf-8")
        self._checkout_ttl = timedelta(minutes=checkout_ttl_minutes)
        self._return_ttl = timedelta(hours=return_ttl_hours)
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue(self, kind: str, transaction_id: str) -> IssuedLink:
        if kind not in {"checkout", "return", "cancel"}:
            raise ValueError(f"unsupported link kind: {kind}")
        now = self._clock()
        ttl = self._checkout_ttl if kind == "checkout" else self._return_ttl
        expires = now + ttl
        jti = secrets.token_urlsafe(24)
        claims = {
            "typ": kind,
            "txn": transaction_id,
            "exp": int(expires.timestamp()),
            "jti": jti,
        }
        body = _b64url(canonical_json(claims))
        signature = _b64url(
            hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
        )
        return IssuedLink(token=f"v1.{body}.{signature}", jti=jti, expires_at=expires)

    def verify(self, token: str, *, expected_kind: str) -> LinkClaims:
        try:
            version, body, signature = token.split(".")
            if version != "v1":
                raise ValueError("unsupported token version")
            expected = _b64url(
                hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(signature, expected):
                raise ValueError("bad signature")
            claims: dict[str, Any] = json.loads(_unb64url(body))
            expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise VerifundError("unauthorized", "link is invalid", status_code=401) from exc
        if claims.get("typ") != expected_kind:
            raise VerifundError("forbidden", "link kind mismatch", status_code=403)
        if expires_at <= self._clock():
            raise VerifundError("token_expired", "link has expired", status_code=401)
        return LinkClaims(
            kind=expected_kind,
            transaction_id=str(claims["txn"]),
            jti=str(claims["jti"]),
            expires_at=expires_at,
        )
```

`TransactionState` import is unused; remove it.

- [ ] **Step 4: Implement receipts**

`apps/verifund_control_plane/verifund_control_plane/receipts.py`:

```python
from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from verifund_contracts import ReceiptPayload

from verifund_control_plane.domain import canonical_json, sha256_hex


@dataclass(frozen=True)
class SignedReceipt:
    payload: dict[str, Any]
    payload_hash: str
    signature: str
    kid: str


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def build_receipt_payload(
    *,
    transaction_id: str,
    agreement_hash: str,
    amount_cents: int,
    currency: str,
    buyer_id: str,
    seller_id: str,
    capture_id: str,
    payout_item_id: str,
    evidence_hashes: list[str],
    released_at: datetime,
) -> dict[str, Any]:
    payload = ReceiptPayload(
        transaction_id=transaction_id,
        agreement_hash=agreement_hash,
        amount_cents=amount_cents,
        currency=currency,
        buyer_id=buyer_id,
        seller_id=seller_id,
        capture_id=capture_id,
        payout_item_id=payout_item_id,
        evidence_hashes=evidence_hashes,
        released_at=released_at,
    )
    return payload.model_dump(mode="json")


class ReceiptSigner:
    def __init__(self, keys: dict[str, str], active_kid: str) -> None:
        self._keys = dict(keys)
        self._active_kid = active_kid
        if active_kid not in self._keys:
            raise ValueError("active receipt kid is not configured")

    def _signature(self, kid: str, payload_hash: str) -> str:
        key = self._keys[kid].encode("utf-8")
        digest = hmac.new(key, payload_hash.encode("ascii"), hashlib.sha256).digest()
        return _b64url(digest)

    def sign(self, payload: dict[str, Any]) -> SignedReceipt:
        payload_hash = sha256_hex(canonical_json(payload))
        return SignedReceipt(
            payload=payload,
            payload_hash=payload_hash,
            signature=self._signature(self._active_kid, payload_hash),
            kid=self._active_kid,
        )

    def verify(
        self,
        payload: dict[str, Any],
        payload_hash: str,
        signature: str,
        kid: str,
    ) -> bool:
        if kid not in self._keys:
            return False
        actual_hash = sha256_hex(canonical_json(payload))
        if not hmac.compare_digest(actual_hash, payload_hash):
            return False
        expected = self._signature(kid, actual_hash)
        return hmac.compare_digest(expected, signature)
```

- [ ] **Step 5: Run token and receipt tests**

Run: `uv run pytest tests/unit/test_verifund_tokens.py tests/unit/test_verifund_receipts.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tokens.py apps/verifund_control_plane/verifund_control_plane/receipts.py tests/unit/test_verifund_tokens.py tests/unit/test_verifund_receipts.py
git commit -m "feat(verifund): add seller tokens, signed links, and receipt signing"
```

### Task 9: Award, acceptance, rejection, approval, cancellation, and ops read API

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/domain.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Test: `tests/unit/test_verifund_service.py`

**Interfaces:**
- Produces: `VerifundService(repo, settings, clock, tokens)`, `award`, `list_transactions`, `get_transaction`, `projection`, `record_buyer_review`, `accept`, `reject`, `approve`, `cancel`, `events`; `POST /transactions/{id}/buyer-review`; ops bearer auth with actor and idempotency headers. `award` returns the canonical `AgreementProjection` and its version alongside the seller token; `AGREED` requires both buyer review and seller acceptance for the current hash.
- Consumes: repository, domain, tokens, and contracts from Tasks 1-8 and `AgreementProjection` from Task 1A.

- [ ] **Step 1: Write failing service and API tests**

The tests must prove that either review can be recorded first, `AGREED` is not
entered until Buyer review and Seller acceptance both accept the current hash,
and a Buyer-agent rejection cancels without a ledger entry. Replays with the
same idempotency key return the stored decision; stale versions/hashes conflict.

`tests/unit/test_verifund_service.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings
from verifund_contracts import AgreementProjection

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops"}
ACTOR = {"x-verifund-actor": "buyer-agent"}
HASH = "a" * 64


def award_payload() -> dict:
    return {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def create_award(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/awards",
        json=award_payload(),
        headers={
            **OPS,
            **ACTOR,
            "idempotency-key": "award:run-1:offer-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_ops_auth_is_required(api):
    response = await api.get("/transactions")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_award_creates_transaction_token_and_agreement(api):
    body = await create_award(api)
    assert body["transaction_id"].startswith("vf_")
    assert body["state"] == "AWARDED"
    assert len(body["agreement_hash"]) == 64
    assert body["seller_token"].startswith("v1.")
    assert body["expires_at"].startswith("2026-10-30T12:00:00")
    assert body["agreement_version"] == 1
    assert body["agreement"]["agreement_version"] == 1
    assert body["agreement"]["transaction_id"] == body["transaction_id"]
    assert body["agreement"]["amount_cents"] == 123400
    assert body["agreement"]["agreement_hash"] == body["agreement_hash"]


async def test_award_projection_hash_matches_the_canonical_terms(api):
    body = await create_award(api)
    projection = AgreementProjection.model_validate(body["agreement"])
    assert projection.recompute_hash() == body["agreement_hash"]
    assert projection.canonical_payload()["created_at"].endswith("Z")


async def test_award_is_idempotent(api):
    first = await create_award(api)
    second = await create_award(api)
    assert first["transaction_id"] == second["transaction_id"]
    txns = (await api.get("/transactions", headers=OPS)).json()
    assert len(txns) == 1


async def test_accept_requires_hash_and_seller(api):
    award = await create_award(api)
    bad = await api.post(
        f"/transactions/{award['transaction_id']}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": HASH,
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR},
    )
    assert bad.status_code == 409
    assert bad.json()["error"]["code"] == "hash_mismatch"

    buyer_review = await api.post(
        f"/transactions/{award['transaction_id']}/buyer-review",
        json={
            "buyer_id": "demo-buyer",
            "agreement_version": 1,
            "agreement_hash": award["agreement_hash"],
            "decision": "accepted",
            "buyer_task_id": "buyer-review-task-1",
            "reviewed_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR, "idempotency-key": "buyer-review:run-1:v1"},
    )
    assert buyer_review.status_code == 200
    assert buyer_review.json()["state"] == "AWARDED"

    accepted = await api.post(
        f"/transactions/{award['transaction_id']}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR},
    )
    assert accepted.status_code == 200
    assert accepted.json()["state"] == "AGREED"
    assert accepted.json()["buyer_agent_review"]["status"] == "accepted"
    assert accepted.json()["seller_decision"]["status"] == "accepted"

    replay = await api.post(
        f"/transactions/{award['transaction_id']}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR},
    )
    assert replay.status_code == 200
    assert replay.json()["state"] == "AGREED"


async def test_rejection_cancels_without_ledger(api):
    award = await create_award(api)
    response = await api.post(
        f"/transactions/{award['transaction_id']}/reject",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "reason_code": "out_of_stock",
            "note": "SKU unavailable",
            "seller_task_id": "task-1",
            "rejected_at": NOW.isoformat(),
        },
        headers={**OPS, **ACTOR, "idempotency-key": "reject:vf_1:task-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "CANCELED"
    assert body["cancellation"]["reason_code"] == "seller_rejected"
    events = (
        await api.get(f"/transactions/{award['transaction_id']}/events", headers=OPS)
    ).json()
    assert [event["type"] for event in events][-2:] == [
        "seller_rejected",
        "canceled",
    ]


async def test_approval_binds_hash_and_cancel_before_capture(api):
    award = await create_award(api)
    txid = award["transaction_id"]
    accepted = {
        "seller_id": "northwind-audio",
        "agreement_hash": award["agreement_hash"],
        "accepted_total_cents": 123400,
        "seller_task_id": "task-1",
        "accepted_at": NOW.isoformat(),
    }
    await api.post(f"/transactions/{txid}/accept", json=accepted, headers={**OPS, **ACTOR})
    approved = await api.post(
        f"/transactions/{txid}/approve",
        json={
            "approval_id": "apr-1",
            "approved_by": "demo-reviewer",
            "approved_at": NOW.isoformat(),
            "note": "approved",
            "agreement_hash": award["agreement_hash"],
        },
        headers={**OPS, **ACTOR},
    )
    assert approved.status_code == 200
    assert approved.json()["state"] == "AGREED"
    assert approved.json()["approval"]["approved_by"] == "demo-reviewer"

    canceled = await api.post(
        f"/transactions/{txid}/cancel",
        json={"reason_code": "buyer_rejected", "note": "not acceptable"},
        headers={**OPS, "x-verifund-actor": "console:reviewer"},
    )
    assert canceled.status_code == 200
    assert canceled.json()["state"] == "CANCELED"
    assert canceled.json()["cancellation"]["reason_code"] == "buyer_rejected"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_service.py -v`
Expected: FAIL with `ModuleNotFoundError: verifund_control_plane.service` or 404 for `/awards`.

- [ ] **Step 3: Add `cancellation` and in-transaction idempotency lookup**

Add a `cancellation` field to `TransactionRecord` immediately after `approval`:

```python
    cancellation: dict[str, Any] | None
```

Add a `cancellation` column to the `transactions` table immediately after `approval`:

```python
            Column("cancellation", JSON, nullable=True),
```

Include `cancellation` in `insert_transaction` values, in `_record`, and in any dataclass construction. Add this repository method:

```python
    async def get_idempotency_on(
        self,
        conn: AsyncConnection,
        scope: str,
        key: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        row = (
            await conn.execute(
                select(self.idempotency).where(
                    self.idempotency.c.scope == scope,
                    self.idempotency.c.key == key,
                )
            )
        ).first()
        if row is None:
            return None
        if row.request_hash != request_hash:
            raise VerifundError(
                "conflict",
                "idempotency key reused with a different body",
                status_code=409,
            )
        return row.response
```

- [ ] **Step 4: Implement the service core**

`apps/verifund_control_plane/verifund_control_plane/service.py`:

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from verifund_contracts import (
    AcceptRequest,
    AgreementProjection,
    ApproveRequest,
    AwardRequest,
    AwardResponse,
    CancelRequest,
    CancelReason,
    EvidenceItem,
    EvidenceSummary,
    RejectRequest,
    TransactionProjection,
    TransactionState,
)
from verifund_control_plane.domain import (
    REQUIRED_EVIDENCE,
    TransactionRecord,
    agreement_hash,
    allowed_actions,
    build_agreement,
    canonical_json,
    sha256_hex,
    validate_award,
)
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import AuditInput, EventInput, Repository
from verifund_control_plane.settings import Settings
from verifund_control_plane.tokens import SellerTokenService

Mutation = Callable[[Any], Awaitable[dict[str, Any]]]


class VerifundService:
    def __init__(
        self,
        *,
        repo: Repository,
        settings: Settings,
        clock: Callable[[], datetime],
        tokens: SellerTokenService,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.clock = clock
        self.tokens = tokens

    def _now(self) -> datetime:
        return self.clock()

    def _iso(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    async def _replay(
        self, scope: str, key: str | None, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not key:
            return None
        return await self.repo.get_idempotency(
            scope, key, sha256_hex(canonical_json(body))
        )

    async def _mutate(
        self,
        *,
        scope: str,
        key: str | None,
        body: dict[str, Any],
        operation: Mutation,
    ) -> dict[str, Any]:
        request_hash = sha256_hex(canonical_json(body))
        cached = await self._replay(scope, key, body)
        if cached is not None:
            return cached
        async with self.repo.transaction() as conn:
            if key:
                cached = await self.repo.get_idempotency_on(
                    conn, scope, key, request_hash
                )
                if cached is not None:
                    return cached
            result = await operation(conn)
            if key:
                await self.repo.put_idempotency(
                    conn, scope, key, request_hash, result
                )
            return result

    @staticmethod
    def _pick(
        value: dict[str, Any] | None, fields: tuple[str, ...]
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        return {key: value[key] for key in fields if key in value}

    async def _projection(
        self,
        record: TransactionRecord,
        actor: str,
        *,
        items: list[EvidenceItem] | None = None,
    ) -> TransactionProjection:
        evidence_items = items or []
        received = sorted({item.kind for item in evidence_items})
        deadlines = {
            key: (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                if isinstance(value, str)
                else value
            )
            for key, value in (record.deadlines or {}).items()
        }
        summary = EvidenceSummary(
            required=list(REQUIRED_EVIDENCE),
            received=received,
            complete=all(kind in received for kind in REQUIRED_EVIDENCE),
            deadline=deadlines.get("evidence"),
            items=evidence_items,
        )
        return TransactionProjection(
            transaction_id=record.transaction_id,
            run_id=record.run_id,
            state=record.state,
            last_seq=record.last_seq,
            amount_cents=record.amount_cents,
            currency=record.currency,
            buyer_id=record.buyer_id,
            seller_id=record.seller_id,
            agreement_hash=record.agreement_hash,
            agreement_version=record.agreement_version,
            seller_decision=self._pick(
                record.seller_decision,
                ("status", "reported_at", "reason_code", "note"),
            ),
            approval=self._pick(
                record.approval, ("approved_by", "approved_at", "note")
            ),
            cancellation=self._pick(
                record.cancellation, ("reason_code", "note", "at")
            ),
            funding=self._pick(
                record.funding,
                (
                    "status",
                    "provider_order_id",
                    "capture_id",
                    "payer_action_url",
                    "completed_at",
                ),
            ),
            purchase_order=self._pick(
                record.purchase_order,
                ("seller_order_id", "tracking_number", "carrier", "eta"),
            ),
            evidence=summary,
            verification=self._pick(
                record.verification,
                ("status", "reasons", "checked_at", "override_allowed"),
            ),
            payout=self._pick(
                record.payout,
                ("status", "batch_id", "item_id", "amount_cents", "updated_at"),
            ),
            receipt_available=record.receipt is not None,
            deadlines=deadlines,
            allowed_actions=allowed_actions(record.state, actor),
            updated_at=record.updated_at,
        )

    async def _projection_for(
        self, transaction_id: str, actor: str
    ) -> TransactionProjection:
        record = await self.repo.get_transaction(transaction_id)
        items = await self.repo.list_evidence(transaction_id)
        return await self._projection(record, actor, items=items)

    async def award(
        self, request: AwardRequest, *, actor: str, idempotency_key: str | None
    ) -> dict[str, Any]:
        validate_award(request)
        if self.settings.is_sandbox and not self.settings.payout_email_for(
            request.seller_id
        ):
            raise VerifundError(
                "invalid_request",
                f"no payout email configured for {request.seller_id}",
                status_code=400,
            )
        now = self._now()
        transaction_id = f"vf_{uuid.uuid4().hex}"
        agreement = build_agreement(transaction_id, request, now)
        digest = agreement_hash(agreement)
        record = TransactionRecord(
            transaction_id=transaction_id,
            run_id=request.run_id,
            buyer_id=request.buyer_id,
            seller_id=request.seller_id,
            offer_id=request.offer_id,
            state=TransactionState.AWARDED,
            version=1,
            last_seq=0,
            amount_cents=request.amount_cents,
            currency=request.currency,
            agreement_id=f"agr_{uuid.uuid4().hex}",
            agreement_hash=digest,
            agreement_version=1,
            seller_decision=None,
            approval=None,
            cancellation=None,
            funding=None,
            purchase_order=None,
            evidence_summary=None,
            verification=None,
            payout=None,
            receipt=None,
            deadlines={"funding": None, "evidence": None, "inspection": None},
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        issued = self.tokens.issue(
            transaction_id, request.seller_id, digest
        )
        projection = AgreementProjection(
            **agreement,
            agreement_hash=digest,
        )
        response = {
            "transaction_id": transaction_id,
            "state": TransactionState.AWARDED.value,
            "agreement_hash": digest,
            "agreement_version": projection.agreement_version,
            "agreement": projection.model_dump(mode="json"),
            "seller_token": issued.token,
            "expires_at": self._iso(issued.expires_at),
        }

        async def operation(conn):
            await self.repo.insert_transaction(
                conn,
                record,
                agreement=agreement,
                events=[
                    EventInput(
                        "award_created",
                        {
                            "run_id": request.run_id,
                            "seller_id": request.seller_id,
                            "amount_cents": request.amount_cents,
                        },
                        actor,
                    )
                ],
                audit=AuditInput(actor, "award_created"),
            )
            await self.repo.save_seller_token(
                conn,
                issued.jti_hash,
                transaction_id,
                request.seller_id,
                digest,
                ["txn:read", "evidence:write"],
                issued.expires_at,
            )
            return response

        return await self._mutate(
            scope="award",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def list_transactions(
        self,
        *,
        actor: str,
        run_id: str | None = None,
        state: str | None = None,
        seller_id: str | None = None,
    ) -> list[dict[str, Any]]:
        records = await self.repo.list_transactions(
            run_id=run_id, state=state, seller_id=seller_id
        )
        result = []
        for record in records:
            items = await self.repo.list_evidence(record.transaction_id)
            result.append(
                (
                    await self._projection(record, actor, items=items)
                ).model_dump(mode="json")
            )
        return result

    async def get_transaction(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        return (
            await self._projection_for(transaction_id, actor)
        ).model_dump(mode="json")

    async def events(
        self, transaction_id: str, *, after_seq: int = 0
    ) -> list[dict[str, Any]]:
        await self.repo.get_transaction(transaction_id)
        return await self.repo.events(transaction_id, after_seq=after_seq)

    def _check_hash(self, record: TransactionRecord, digest: str) -> None:
        if record.agreement_hash != digest:
            raise VerifundError(
                "hash_mismatch",
                "agreement hash does not match the stored agreement",
                status_code=409,
            )

    async def accept(
        self,
        transaction_id: str,
        request: AcceptRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)
        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            if record.seller_id != request.seller_id:
                raise VerifundError(
                    "forbidden", "seller does not own this transaction", status_code=403
                )
            self._check_hash(record, request.agreement_hash)
            if request.accepted_total_cents != record.amount_cents:
                raise VerifundError(
                    "invalid_request", "accepted total does not match", status_code=400
                )
            if record.state == TransactionState.AGREED:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state != TransactionState.AWARDED:
                raise VerifundError(
                    "invalid_state", "transaction is not awaiting acceptance", status_code=409
                )
            changes = {
                "seller_decision": {
                    "status": "accepted",
                    "reported_at": self._iso(request.accepted_at),
                    "seller_task_id": request.seller_task_id,
                    "agreement_hash": request.agreement_hash,
                }
            }
            events = [
                EventInput(
                    "seller_accepted",
                    {"seller_task_id": request.seller_task_id},
                    actor,
                )
            ]
            if (record.buyer_agent_review or {}).get("status") == "accepted":
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=record.version,
                    expected_state=TransactionState.AWARDED,
                    new_state=TransactionState.AGREED,
                    changes=changes,
                    events=events,
                    audit=AuditInput(actor, "seller_accepted"),
                )
            else:
                updated = await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=record.version,
                    changes=changes,
                    events=events,
                    audit=AuditInput(actor, "seller_accepted_waiting_for_buyer_review"),
                )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"accept:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def reject(
        self,
        transaction_id: str,
        request: RejectRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)
        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            if record.seller_id != request.seller_id:
                raise VerifundError(
                    "forbidden", "seller does not own this transaction", status_code=403
                )
            self._check_hash(record, request.agreement_hash)
            if record.state == TransactionState.CANCELED and (
                record.cancellation or {}
            ).get("reason_code") == "seller_rejected":
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state != TransactionState.AWARDED:
                raise VerifundError(
                    "invalid_state", "transaction is not awaiting acceptance", status_code=409
                )
            cancellation = {
                "reason_code": "seller_rejected",
                "seller_reason_code": request.reason_code.value,
                "note": request.note,
                "at": self._iso(request.rejected_at),
                "seller_task_id": request.seller_task_id,
            }
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=record.version,
                expected_state=TransactionState.AWARDED,
                new_state=TransactionState.CANCELED,
                changes={
                    "seller_decision": {
                        "status": "rejected",
                        "reported_at": self._iso(request.rejected_at),
                        "reason_code": request.reason_code.value,
                        "note": request.note,
                        "seller_task_id": request.seller_task_id,
                    },
                    "cancellation": cancellation,
                },
                events=[
                    EventInput(
                        "seller_rejected",
                        {
                            "reason_code": request.reason_code.value,
                            "seller_task_id": request.seller_task_id,
                        },
                        actor,
                    ),
                    EventInput("canceled", cancellation, actor),
                ],
                audit=AuditInput(
                    actor, "seller_rejected", note=request.note
                ),
            )
            await self.repo.revoke_seller_tokens(conn, transaction_id, self._now())
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"reject:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def approve(
        self,
        transaction_id: str,
        request: ApproveRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)
        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            self._check_hash(record, request.agreement_hash)
            if (record.approval or {}).get("approval_id") == request.approval_id:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state != TransactionState.AGREED:
                raise VerifundError(
                    "invalid_state", "transaction is not awaiting approval", status_code=409
                )
            deadline = self._now() + timedelta(
                hours=self.settings.funding_timeout_hours
            )
            updated = await self.repo.update_transaction(
                conn,
                transaction_id,
                expected_version=record.version,
                changes={
                    "approval": {
                        "approval_id": request.approval_id,
                        "approved_by": request.approved_by,
                        "approved_at": self._iso(request.approved_at),
                        "note": request.note,
                    },
                    "deadlines": {
                        **(record.deadlines or {}),
                        "funding": self._iso(deadline),
                    },
                },
                events=[
                    EventInput(
                        "buyer_approved",
                        {
                            "approval_id": request.approval_id,
                            "approved_by": request.approved_by,
                        },
                        actor,
                    )
                ],
                audit=AuditInput(
                    actor,
                    "buyer_approved",
                    note=request.note,
                    payload={"approval_id": request.approval_id},
                ),
            )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"approve:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    async def cancel(
        self,
        transaction_id: str,
        request: CancelRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)
        allowed_states = {
            TransactionState.AWARDED,
            TransactionState.AGREED,
            TransactionState.FUNDING_PENDING,
            TransactionState.REVIEW_REQUIRED,
        }
        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            if record.state == TransactionState.CANCELED:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state not in allowed_states:
                raise VerifundError(
                    "invalid_state", "transaction cannot be canceled", status_code=409
                )
            funding = record.funding or {}
            if funding.get("status") in {"captured", "refunded"} or funding.get(
                "capture_id"
            ):
                raise VerifundError(
                    "forbidden",
                    "captured funds cannot be canceled; flag review instead",
                    status_code=403,
                )
            if record.state == TransactionState.REVIEW_REQUIRED:
                balances = await self.repo.ledger_balances(transaction_id)
                if balances.get("held_funds", 0) != 0:
                    raise VerifundError(
                        "forbidden", "ledger has captured funds", status_code=403
                    )
            cancellation = {
                "reason_code": request.reason_code.value,
                "note": request.note,
                "at": self._iso(self._now()),
            }
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=record.version,
                expected_state=record.state,
                new_state=TransactionState.CANCELED,
                changes={"cancellation": cancellation},
                events=[EventInput("canceled", cancellation, actor)],
                audit=AuditInput(actor, "canceled", note=request.note),
            )
            await self.repo.revoke_seller_tokens(conn, transaction_id, self._now())
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"cancel:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )
```

- [ ] **Step 5: Implement the ops router**

`apps/verifund_control_plane/verifund_control_plane/api/ops.py`:

```python
from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request

from verifund_contracts import (
    AcceptRequest,
    ApproveRequest,
    AwardRequest,
    CancelRequest,
    RejectRequest,
)
from verifund_control_plane.errors import VerifundError

router = APIRouter(prefix="")


def _service(request: Request):
    return request.app.state.service


def _settings(request: Request):
    return request.app.state.settings


async def require_ops(request: Request) -> None:
    expected = _settings(request).ops_token
    provided = request.headers.get("authorization", "")
    if not provided.startswith("Bearer ") or not secrets.compare_digest(
        provided.removeprefix("Bearer "), expected
    ):
        raise VerifundError("unauthorized", "ops token is required", status_code=401)


def actor(request: Request) -> str:
    return request.headers.get("x-verifund-actor", "buyer-agent")


def idempotency_key(request: Request) -> str | None:
    return request.headers.get("idempotency-key")


@router.post("/awards", status_code=201, dependencies=[Depends(require_ops)])
async def create_award(body: AwardRequest, request: Request) -> dict[str, Any]:
    return await _service(request).award(
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.get("/transactions", dependencies=[Depends(require_ops)])
async def list_transactions(
    request: Request,
    run_id: str | None = None,
    state: str | None = None,
    seller_id: str | None = None,
) -> list[dict[str, Any]]:
    return await _service(request).list_transactions(
        actor=actor(request),
        run_id=run_id,
        state=state,
        seller_id=seller_id,
    )


@router.get("/transactions/{transaction_id}", dependencies=[Depends(require_ops)])
async def get_transaction(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).get_transaction(
        transaction_id, actor=actor(request)
    )


@router.get(
    "/transactions/{transaction_id}/state", dependencies=[Depends(require_ops)]
)
async def get_state(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).get_transaction(
        transaction_id, actor=actor(request)
    )


@router.get(
    "/transactions/{transaction_id}/events", dependencies=[Depends(require_ops)]
)
async def get_events(
    transaction_id: str, request: Request, after_seq: int = 0
) -> list[dict[str, Any]]:
    return await _service(request).events(transaction_id, after_seq=after_seq)


@router.post(
    "/transactions/{transaction_id}/accept", dependencies=[Depends(require_ops)]
)
async def accept(
    transaction_id: str, body: AcceptRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).accept(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/reject", dependencies=[Depends(require_ops)]
)
async def reject(
    transaction_id: str, body: RejectRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).reject(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/approve", dependencies=[Depends(require_ops)]
)
async def approve(
    transaction_id: str, body: ApproveRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).approve(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/cancel", dependencies=[Depends(require_ops)]
)
async def cancel(
    transaction_id: str, body: CancelRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).cancel(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )
```

- [ ] **Step 6: Wire the service and router into the app**

In `app.py`, import `ops`, `SellerTokenService`, and `VerifundService`. Create after the repository:

```python
    tokens = SellerTokenService(
        settings.seller_token_secret,
        ttl_hours=settings.seller_token_ttl_hours,
        clock=now,
    )
    service = VerifundService(
        repo=repo, settings=settings, clock=now, tokens=tokens
    )
```

Assign:

```python
    app.state.tokens = tokens
    app.state.service = service
```

Include the router:

```python
    app.include_router(ops.router)
```

- [ ] **Step 7: Run the service tests**

Run: `uv run pytest tests/unit/test_verifund_service.py tests/unit/test_verifund_domain.py tests/unit/test_verifund_repository.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/{domain.py,repository.py,service.py,app.py} apps/verifund_control_plane/verifund_control_plane/api/ops.py tests/unit/test_verifund_service.py
git commit -m "feat(verifund): add award, acceptance, approval, cancel, and ops reads"
```

---

### Task 10: Evidence storage, verification policy, and seller API

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/evidence.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/policy.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Test: `tests/unit/test_verifund_evidence.py`
- Test: `tests/unit/test_verifund_policy.py`
- Test: `tests/integration/test_verifund_seller_api.py`

**Interfaces:**
- Produces: `EvidenceStore(root, max_bytes)`, `.put(...) -> EvidenceItem`, `.read(sha256) -> bytes`, `.verify(sha256) -> bool`; `PolicyResult`, `.evaluate(...)`; `seller.router`; `service.add_evidence`, `service.seller_projection`.
- Consumes: ops auth and service from Task 9.

- [ ] **Step 1: Write failing evidence and policy tests**

`tests/unit/test_verifund_evidence.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.evidence import EvidenceStore

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "evidence", max_bytes=32)


async def test_put_is_content_addressed_and_idempotent(store):
    first = await store.put(
        transaction_id="vf_1",
        seller_id="northwind-audio",
        kind="shipment_manifest",
        media_type="application/json",
        original_filename="manifest.json",
        data=b'{"tracking_number":"TRK-1"}',
        note=None,
        captured_at=None,
    )
    second = await store.put(
        transaction_id="vf_1",
        seller_id="northwind-audio",
        kind="shipment_manifest",
        media_type="application/json",
        original_filename="manifest-copy.json",
        data=b'{"tracking_number":"TRK-1"}',
        note=None,
        captured_at=None,
    )
    assert first.sha256 == second.sha256
    assert first.evidence_id != second.evidence_id
    assert (store.root / first.sha256).read_bytes() == b'{"tracking_number":"TRK-1"}'
    assert store.verify(first.sha256)


async def test_put_rejects_oversized_and_unsupported(store):
    with pytest.raises(VerifundError) as raised:
        await store.put(
            transaction_id="vf_1",
            seller_id="northwind-audio",
            kind="shipment_manifest",
            media_type="application/json",
            original_filename="big.json",
            data=b"x" * 33,
            note=None,
            captured_at=None,
        )
    assert raised.value.code == "evidence_too_large"

    with pytest.raises(VerifundError) as raised:
        await store.put(
            transaction_id="vf_1",
            seller_id="northwind-audio",
            kind="shipment_manifest",
            media_type="application/zip",
            original_filename="x.zip",
            data=b"x",
            note=None,
            captured_at=None,
        )
    assert raised.value.code == "unsupported_media_type"


async def test_put_rejects_unknown_kind(store):
    with pytest.raises(VerifundError) as raised:
        await store.put(
            transaction_id="vf_1",
            seller_id="northwind-audio",
            kind="made_up",
            media_type="text/plain",
            original_filename="x.txt",
            data=b"x",
            note=None,
            captured_at=None,
        )
    assert raised.value.code == "invalid_request"
```

`tests/unit/test_verifund_policy.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from verifund_contracts import EvidenceItem, ReviewReason, TransactionState
from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.policy import evaluate

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64
DELIVERED = NOW - timedelta(hours=30)


def record() -> TransactionRecord:
    return TransactionRecord(
        transaction_id="vf_1",
        run_id="run-1",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        offer_id="offer-1",
        state=TransactionState.VERIFICATION_PENDING,
        version=5,
        last_seq=10,
        amount_cents=123400,
        currency="USD",
        agreement_id="agr_1",
        agreement_hash=HASH,
        agreement_version=1,
        seller_decision={"status": "accepted", "reported_at": NOW.isoformat()},
        approval={"approved_by": "demo", "approved_at": NOW.isoformat()},
        cancellation=None,
        funding={
            "status": "captured",
            "capture_id": "CAP-1",
            "capture_amount_cents": 123400,
            "capture_currency": "USD",
        },
        purchase_order={
            "seller_order_id": "MM-1",
            "tracking_number": "TRK-1",
            "carrier": "Northwind Logistics",
            "eta": (NOW + timedelta(days=2)).isoformat(),
        },
        evidence_summary=None,
        verification=None,
        payout=None,
        receipt=None,
        deadlines={
            "evidence": (NOW + timedelta(hours=24)).isoformat(),
            "inspection": None,
        },
        last_error=None,
        created_at=NOW,
        updated_at=NOW,
    )


async def seed(store: EvidenceStore, delivered_at: datetime, tracking="TRK-1"):
    manifest = {
        "tracking_number": tracking,
        "carrier": "Northwind Logistics",
        "shipped_at": (delivered_at - timedelta(days=1)).isoformat(),
        "seller_id": "northwind-audio",
        "agreement_hash": HASH,
        "line_items": [],
    }
    delivery = {
        "delivered_at": delivered_at.isoformat(),
        "recipient": "Demo Buyer",
    }
    items = []
    for kind, payload in (
        ("shipment_manifest", manifest),
        ("delivery_confirmation", delivery),
    ):
        items.append(
            await store.put(
                transaction_id="vf_1",
                seller_id="northwind-audio",
                kind=kind,
                media_type="application/json",
                original_filename=f"{kind}.json",
                data=json.dumps(payload).encode(),
                note=None,
                captured_at=None,
            )
        )
    return items


async def test_policy_passes_after_inspection_window(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    items = await seed(store, DELIVERED)
    result = evaluate(
        record(),
        items,
        store,
        NOW,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 123400, "platform_cash": 123400, "seller_paid": 0},
    )
    assert result.passed
    assert result.reasons == ()


async def test_future_inspection_window_waits(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    items = await seed(store, NOW - timedelta(hours=1))
    result = evaluate(
        record(),
        items,
        store,
        NOW,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 123400, "platform_cash": 123400, "seller_paid": 0},
    )
    assert not result.passed
    assert result.waiting
    assert result.reasons == (ReviewReason.INSPECTION_NOT_ELAPSED,)


async def test_policy_reports_missing_evidence_tracking_and_ledger(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    items = await seed(store, NOW - timedelta(hours=30), tracking="OTHER")
    item_record = record()
    item_record.purchase_order = {
        "seller_order_id": "MM-1",
        "tracking_number": "TRK-1",
    }
    result = evaluate(
        item_record,
        items[:1],
        store,
        NOW,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 1, "platform_cash": 1, "seller_paid": 0},
    )
    assert ReviewReason.MISSING_EVIDENCE in result.reasons
    assert ReviewReason.TRACKING_MISMATCH in result.reasons
    assert ReviewReason.LEDGER_INCOMPLETE in result.reasons
    assert not result.override_allowed


async def test_funding_mismatch_is_not_overridable(tmp_path: Path):
    store = EvidenceStore(tmp_path / "evidence", max_bytes=10_000)
    items = await seed(store, DELIVERED)
    item_record = record()
    item_record.funding = {
        "status": "captured",
        "capture_id": "CAP-1",
        "capture_amount_cents": 120000,
        "capture_currency": "USD",
    }
    result = evaluate(
        item_record,
        items,
        store,
        NOW,
        inspection_window_hours=24,
        ledger_balances={"held_funds": 123400, "platform_cash": 123400, "seller_paid": 0},
    )
    assert ReviewReason.FUNDING_MISMATCH in result.reasons
    assert not result.override_allowed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_evidence.py tests/unit/test_verifund_policy.py -v`
Expected: FAIL with missing modules.

- [ ] **Step 3: Implement the evidence store**

`apps/verifund_control_plane/verifund_control_plane/evidence.py`:

```python
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from verifund_contracts import EvidenceItem, EvidenceKind

from verifund_control_plane.errors import VerifundError

ALLOWED_MEDIA_TYPES = {
    "application/json",
    "text/plain",
    "application/pdf",
    "image/png",
    "image/jpeg",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EvidenceStore:
    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, sha256: str) -> Path:
        if not SHA256_PATTERN.match(sha256):
            raise VerifundError(
                "invalid_request", "invalid evidence hash", status_code=400
            )
        return self.root / sha256

    async def put(
        self,
        *,
        transaction_id: str,
        seller_id: str,
        kind: str,
        media_type: str,
        original_filename: str,
        data: bytes,
        note: str | None,
        captured_at: datetime | None,
    ) -> EvidenceItem:
        try:
            EvidenceKind(kind)
        except ValueError as exc:
            raise VerifundError(
                "invalid_request", f"unsupported evidence kind: {kind}", status_code=400
            ) from exc
        if media_type not in ALLOWED_MEDIA_TYPES:
            raise VerifundError(
                "unsupported_media_type",
                f"unsupported media type: {media_type}",
                status_code=415,
            )
        if not data:
            raise VerifundError(
                "invalid_request", "evidence file is empty", status_code=400
            )
        if len(data) > self.max_bytes:
            raise VerifundError(
                "evidence_too_large",
                f"evidence exceeds {self.max_bytes} bytes",
                status_code=413,
            )
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        if not path.exists():
            await asyncio.to_thread(self._write_atomic, path, data)
        return EvidenceItem(
            evidence_id=f"ev_{uuid.uuid4().hex}",
            kind=kind,
            sha256=digest,
            media_type=media_type,
            size_bytes=len(data),
            original_filename=original_filename or "evidence",
            note=note,
            created_at=datetime.now().astimezone(),
        )

    def _write_atomic(self, path: Path, data: bytes) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def read(self, sha256: str) -> bytes:
        path = self._path(sha256)
        if not path.exists():
            raise VerifundError(
                "not_found", "evidence content is missing", status_code=404
            )
        return path.read_bytes()

    def verify(self, sha256: str) -> bool:
        path = self._path(sha256)
        if not path.exists():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == sha256
```

- [ ] **Step 4: Implement the verification policy**

`apps/verifund_control_plane/verifund_control_plane/policy.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from verifund_contracts import EvidenceItem, ReviewReason

from verifund_control_plane.domain import NON_OVERRIDABLE_REASONS, TransactionRecord
from verifund_control_plane.evidence import EvidenceStore

OVERRIDABLE_REASONS = frozenset(ReviewReason) - NON_OVERRIDABLE_REASONS


@dataclass(frozen=True)
class PolicyResult:
    passed: bool
    waiting: bool
    evidence_complete: bool
    reasons: tuple[ReviewReason, ...]
    override_allowed: bool
    inspection_deadline: datetime | None = None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load(store: EvidenceStore, item: EvidenceItem) -> dict[str, Any] | None:
    try:
        value = json.loads(store.read(item.sha256))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def evaluate(
    record: TransactionRecord,
    items: list[EvidenceItem],
    store: EvidenceStore,
    now: datetime,
    *,
    inspection_window_hours: int,
    ledger_balances: dict[str, int],
) -> PolicyResult:
    reasons: list[ReviewReason] = []
    by_kind: dict[str, EvidenceItem] = {}
    for item in items:
        by_kind.setdefault(item.kind, item)
        if not store.verify(item.sha256):
            reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)

    required = {"shipment_manifest", "delivery_confirmation"}
    complete = required.issubset(by_kind)
    if not complete:
        reasons.append(ReviewReason.MISSING_EVIDENCE)

    manifest = (
        _load(store, by_kind["shipment_manifest"])
        if "shipment_manifest" in by_kind
        else None
    )
    delivery = (
        _load(store, by_kind["delivery_confirmation"])
        if "delivery_confirmation" in by_kind
        else None
    )
    if ("shipment_manifest" in by_kind and manifest is None) or (
        "delivery_confirmation" in by_kind and delivery is None
    ):
        reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)

    funding = record.funding or {}
    if (
        funding.get("status") != "captured"
        or funding.get("capture_amount_cents") != record.amount_cents
        or funding.get("capture_currency") != record.currency
    ):
        reasons.append(ReviewReason.FUNDING_MISMATCH)

    if ledger_balances.get("held_funds", 0) != record.amount_cents:
        reasons.append(ReviewReason.LEDGER_INCOMPLETE)

    purchase_order = record.purchase_order or {}
    if manifest is not None:
        if manifest.get("seller_id") not in {None, record.seller_id}:
            reasons.append(ReviewReason.SELLER_MISMATCH)
        if manifest.get("agreement_hash") not in {None, record.agreement_hash}:
            reasons.append(ReviewReason.AGREEMENT_MISMATCH)
        tracking = manifest.get("tracking_number")
        if purchase_order.get("tracking_number") and tracking != purchase_order.get(
            "tracking_number"
        ):
            reasons.append(ReviewReason.TRACKING_MISMATCH)

    inspection_deadline: datetime | None = None
    if delivery is not None:
        delivered_at = _parse_time(delivery.get("delivered_at"))
        if delivered_at is None:
            reasons.append(ReviewReason.INVALID_EVIDENCE_HASH)
        elif delivered_at > now:
            reasons.append(ReviewReason.DELIVERY_IN_FUTURE)
        else:
            inspection_deadline = delivered_at + timedelta(
                hours=inspection_window_hours
            )
            if inspection_deadline > now:
                reasons.append(ReviewReason.INSPECTION_NOT_ELAPSED)

    evidence_deadline = _parse_time((record.deadlines or {}).get("evidence"))
    if evidence_deadline is not None and now > evidence_deadline:
        reasons.append(ReviewReason.EVIDENCE_DEADLINE_MISSED)

    existing = record.verification or {}
    if "manual_flag" in (existing.get("reasons") or []):
        reasons.append(ReviewReason.MANUAL_FLAG)

    unique = tuple(dict.fromkeys(reasons))
    waiting = (
        complete
        and inspection_deadline is not None
        and inspection_deadline > now
        and set(unique) <= {ReviewReason.INSPECTION_NOT_ELAPSED}
    )
    return PolicyResult(
        passed=not unique,
        waiting=waiting,
        evidence_complete=complete,
        reasons=unique,
        override_allowed=bool(unique) and set(unique) <= OVERRIDABLE_REASONS,
        inspection_deadline=inspection_deadline,
    )
```

- [ ] **Step 5: Extend the repository for agreements and captured timestamps**

Add to `Repository`:

```python
    async def get_agreement(self, transaction_id: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.agreements).where(
                        self.agreements.c.transaction_id == transaction_id
                    )
                )
            ).first()
        if row is None:
            raise VerifundError("not_found", "agreement not found", status_code=404)
        return row.payload
```

Change `add_evidence` to accept `captured_at: datetime | None = None` and write:

```python
            captured_at=_iso(captured_at) if captured_at else None,
```

- [ ] **Step 6: Add evidence methods and seller projection to the service**

In `service.py`, add imports:

```python
from verifund_contracts import EvidenceItem, EvidenceKind, SellerProjection, AwardLineItem
from verifund_control_plane.domain import EVIDENCE_UPLOAD_STATES
from verifund_control_plane.evidence import EvidenceStore
```

Add `evidence_store` to the constructor:

```python
        evidence_store: EvidenceStore,
```

Store `self.evidence_store = evidence_store`.

Append these methods:

```python
    async def add_evidence(
        self,
        transaction_id: str,
        *,
        seller_id: str,
        agreement_hash: str,
        kind: str,
        media_type: str,
        original_filename: str,
        data: bytes,
        note: str | None,
        captured_at: datetime | None,
        actor: str,
    ) -> EvidenceItem:
        record = await self.repo.get_transaction(transaction_id)
        if record.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this transaction", status_code=403
            )
        if record.agreement_hash != agreement_hash:
            raise VerifundError(
                "hash_mismatch", "seller token hash is stale", status_code=409
            )
        if record.state not in EVIDENCE_UPLOAD_STATES:
            raise VerifundError(
                "invalid_state",
                "evidence cannot be uploaded in the current state",
                status_code=409,
            )
        item = await self.evidence_store.put(
            transaction_id=transaction_id,
            seller_id=seller_id,
            kind=kind,
            media_type=media_type,
            original_filename=original_filename,
            data=data,
            note=note,
            captured_at=captured_at,
        )
        new_state = record.state
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state not in EVIDENCE_UPLOAD_STATES:
                raise VerifundError(
                    "invalid_state",
                    "evidence cannot be uploaded in the current state",
                    status_code=409,
                )
            stored, created = await self.repo.add_evidence(
                conn,
                transaction_id,
                seller_id,
                item,
                captured_at=captured_at,
            )
            if not created:
                return stored
            event = EventInput(
                "evidence_received",
                {
                    "evidence_id": stored.evidence_id,
                    "kind": stored.kind,
                    "sha256": stored.sha256,
                },
                actor,
            )
            if current.state == TransactionState.FULFILLMENT_PENDING:
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.VERIFICATION_PENDING,
                    changes={},
                    events=[event],
                    audit=AuditInput(actor, "evidence_received"),
                )
                new_state = updated.state
            else:
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={},
                    events=[event],
                    audit=AuditInput(actor, "evidence_received"),
                )
        if new_state == TransactionState.VERIFICATION_PENDING:
            await self.verify_if_ready(transaction_id, actor="system")
        return stored

    async def seller_projection(
        self, transaction_id: str, *, seller_id: str
    ) -> SellerProjection:
        record = await self.repo.get_transaction(transaction_id)
        if record.seller_id != seller_id:
            raise VerifundError(
                "forbidden", "seller does not own this transaction", status_code=403
            )
        agreement = await self.repo.get_agreement(transaction_id)
        items = await self.repo.list_evidence(transaction_id)
        received = sorted({item.kind for item in items})
        deadlines = {
            key: (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                if isinstance(value, str)
                else value
            )
            for key, value in (record.deadlines or {}).items()
        }
        return SellerProjection(
            transaction_id=record.transaction_id,
            run_id=record.run_id,
            state=record.state,
            seller_id=record.seller_id,
            amount_cents=record.amount_cents,
            currency=record.currency,
            agreement_hash=record.agreement_hash,
            agreement_version=record.agreement_version,
            quantity=agreement["quantity"],
            line_items=[
                AwardLineItem.model_validate(item)
                for item in agreement["line_items"]
            ],
            delivery_days=agreement["delivery_days"],
            warranty_months=agreement["warranty_months"],
            returns_days=agreement["returns_days"],
            purchase_order=self._pick(
                record.purchase_order,
                ("seller_order_id", "tracking_number", "carrier", "eta"),
            ),
            evidence=EvidenceSummary(
                required=list(REQUIRED_EVIDENCE),
                received=received,
                complete=all(kind in received for kind in REQUIRED_EVIDENCE),
                deadline=deadlines.get("evidence"),
                items=items,
            ),
            deadlines=deadlines,
            allowed_actions=allowed_actions(record.state, "seller"),
            updated_at=record.updated_at,
        )

    async def verify_if_ready(self, transaction_id: str, *, actor: str) -> None:
        record = await self.repo.get_transaction(transaction_id)
        if record.state != TransactionState.VERIFICATION_PENDING:
            return
        items = await self.repo.list_evidence(transaction_id)
        received = {item.kind for item in items}
        if not {"shipment_manifest", "delivery_confirmation"}.issubset(received):
            return
        await self.verify(transaction_id, actor=actor)
```

Implement the full `verify` method in Task 10, including state transitions, even though its ops route is added in Task 13. This keeps the policy and the transition it drives in one task. Task 13 only adds the route and the remaining ops actions.

Append `verify`:

```python
    async def verify(self, transaction_id: str, *, actor: str) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state in {TransactionState.RELEASE_PERMITTED, TransactionState.REVIEW_REQUIRED}:
            return (await self._projection_for(transaction_id, "buyer")).model_dump(mode="json")
        items = await self.repo.list_evidence(transaction_id)
        if record.state == TransactionState.FULFILLMENT_PENDING:
            if not items:
                return (await self._projection_for(transaction_id, "buyer")).model_dump(mode="json")
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                if current.state == TransactionState.FULFILLMENT_PENDING:
                    await self.repo.transition(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        expected_state=TransactionState.FULFILLMENT_PENDING,
                        new_state=TransactionState.VERIFICATION_PENDING,
                        changes={},
                        audit=AuditInput(actor, "verification_started"),
                    )
            record = await self.repo.get_transaction(transaction_id)
        if record.state != TransactionState.VERIFICATION_PENDING:
            raise VerifundError(
                "invalid_state", "transaction is not awaiting verification", status_code=409
            )
        balances = await self.repo.ledger_balances(transaction_id)
        result = evaluate(
            record,
            items,
            self.evidence_store,
            self._now(),
            inspection_window_hours=self.settings.inspection_window_hours,
            ledger_balances=balances,
        )
        if result.waiting:
            deadline = result.inspection_deadline or (
                self._now()
                + timedelta(hours=self.settings.inspection_window_hours)
            )
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={
                        "verification": {
                            "status": "pending",
                            "reasons": [reason.value for reason in result.reasons],
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                        },
                        "deadlines": {
                            **(current.deadlines or {}),
                            "inspection": self._iso(deadline),
                        },
                    },
                )
            return (await self._projection_for(transaction_id, "buyer")).model_dump(mode="json")
        deadline = datetime.fromisoformat(
            str((record.deadlines or {}).get("evidence")).replace("Z", "+00:00")
        ) if (record.deadlines or {}).get("evidence") else None
        if not result.evidence_complete and deadline is not None and self._now() <= deadline:
            return (await self._projection_for(transaction_id, "buyer")).model_dump(mode="json")
        reasons = list(result.reasons)
        if not result.evidence_complete and deadline is not None and self._now() > deadline:
            reasons.append(ReviewReason.EVIDENCE_DEADLINE_MISSED)
        if result.passed:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=TransactionState.VERIFICATION_PENDING,
                    new_state=TransactionState.RELEASE_PERMITTED,
                    changes={
                        "verification": {
                            "status": "passed",
                            "reasons": [],
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                        }
                    },
                    events=[
                        EventInput("verification_passed", {}, actor),
                        EventInput("release_permitted", {}, actor),
                    ],
                    audit=AuditInput(actor, "verification_passed"),
                )
            return (await self._projection(updated, "buyer", items=items)).model_dump(mode="json")
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=TransactionState.VERIFICATION_PENDING,
                new_state=TransactionState.REVIEW_REQUIRED,
                changes={
                    "verification": {
                        "status": "failed",
                        "reasons": [reason.value for reason in reasons],
                        "checked_at": self._iso(self._now()),
                        "override_allowed": result.override_allowed,
                    }
                },
                events=[
                    EventInput(
                        "verification_failed",
                        {"reasons": [reason.value for reason in reasons]},
                        actor,
                    ),
                    EventInput("review_required", {}, actor),
                ],
                audit=AuditInput(
                    actor,
                    "verification_failed",
                    payload={"reasons": [reason.value for reason in reasons]},
                ),
            )
        return (await self._projection(updated, "buyer", items=items)).model_dump(mode="json")
```

- [ ] **Step 7: Implement the seller API**

`apps/verifund_control_plane/verifund_control_plane/api/seller.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from verifund_contracts import EvidenceList
from verifund_control_plane.errors import VerifundError

router = APIRouter(prefix="/seller")


def _service(request: Request):
    return request.app.state.service


async def authenticate(request: Request, transaction_id: str, scope: str):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise VerifundError("unauthorized", "seller token is required", status_code=401)
    claims = request.app.state.tokens.verify(
        header.removeprefix("Bearer "), required_scope=scope
    )
    if claims.txn != transaction_id:
        raise VerifundError(
            "forbidden", "seller token is for another transaction", status_code=403
        )
    stored = await request.app.state.repo.get_seller_token(claims.jti_hash)
    if stored.get("revoked_at"):
        raise VerifundError(
            "unauthorized", "seller token has been revoked", status_code=401
        )
    if stored["seller_id"] != claims.seller_id:
        raise VerifundError("unauthorized", "seller token mismatch", status_code=401)
    record = await request.app.state.repo.get_transaction(transaction_id)
    if record.seller_id != claims.seller_id:
        raise VerifundError("forbidden", "seller does not own transaction", status_code=403)
    if record.agreement_hash != claims.agreement_hash:
        raise VerifundError(
            "hash_mismatch", "seller token agreement hash is stale", status_code=409
        )
    return claims


@router.get("/transactions/{transaction_id}")
async def get_seller_transaction(transaction_id: str, request: Request) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "txn:read")
    return (
        await _service(request).seller_projection(
            transaction_id, seller_id=claims.seller_id
        )
    ).model_dump(mode="json")


@router.get("/transactions/{transaction_id}/evidence")
async def list_evidence(transaction_id: str, request: Request) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "txn:read")
    await _service(request).seller_projection(
        transaction_id, seller_id=claims.seller_id
    )
    items = await request.app.state.repo.list_evidence(transaction_id)
    return EvidenceList(items=items).model_dump(mode="json")


@router.post("/transactions/{transaction_id}/evidence", status_code=201)
async def upload_evidence(
    transaction_id: str,
    request: Request,
    kind: str = Form(...),
    file: UploadFile = File(...),
    note: str | None = Form(None),
    captured_at: datetime | None = Form(None),
) -> dict[str, Any]:
    claims = await authenticate(request, transaction_id, "evidence:write")
    data = await file.read(request.app.state.settings.max_evidence_bytes + 1)
    item = await _service(request).add_evidence(
        transaction_id,
        seller_id=claims.seller_id,
        agreement_hash=claims.agreement_hash,
        kind=kind,
        media_type=file.content_type or "application/octet-stream",
        original_filename=file.filename or "evidence",
        data=data,
        note=note,
        captured_at=captured_at,
        actor=f"seller:{claims.seller_id}",
    )
    return item.model_dump(mode="json")


@router.get("/transactions/{transaction_id}/evidence/{evidence_id}")
async def download_evidence(
    transaction_id: str, evidence_id: str, request: Request
) -> Response:
    claims = await authenticate(request, transaction_id, "txn:read")
    await _service(request).seller_projection(
        transaction_id, seller_id=claims.seller_id
    )
    item = await request.app.state.repo.get_evidence(transaction_id, evidence_id)
    return Response(
        content=request.app.state.evidence_store.read(item.sha256),
        media_type=item.media_type,
        headers={
            "content-disposition": f'attachment; filename="{item.original_filename}"'
        },
    )
```

- [ ] **Step 8: Add ops evidence reads**

Append to `api/ops.py`:

```python
from fastapi import Response
from verifund_contracts import EvidenceList


@router.get(
    "/transactions/{transaction_id}/evidence", dependencies=[Depends(require_ops)]
)
async def list_evidence(transaction_id: str, request: Request) -> dict[str, Any]:
    await _service(request).repo.get_transaction(transaction_id)
    items = await _service(request).repo.list_evidence(transaction_id)
    return EvidenceList(items=items).model_dump(mode="json")


@router.get(
    "/transactions/{transaction_id}/evidence/{evidence_id}",
    dependencies=[Depends(require_ops)],
)
async def download_evidence(
    transaction_id: str, evidence_id: str, request: Request
) -> Response:
    item = await _service(request).repo.get_evidence(transaction_id, evidence_id)
    return Response(
        content=request.app.state.evidence_store.read(item.sha256),
        media_type=item.media_type,
        headers={
            "content-disposition": f'attachment; filename="{item.original_filename}"'
        },
    )
```

- [ ] **Step 9: Wire evidence and the seller router into the app**

In `app.py`, create:

```python
    evidence_store = EvidenceStore(
        settings.evidence_dir, max_bytes=settings.max_evidence_bytes
    )
```

Pass `evidence_store=evidence_store` to `VerifundService` and assign:

```python
    app.state.evidence_store = evidence_store
```

Import `seller` and include:

```python
    app.include_router(seller.router)
```

Emit a warning in sandbox mode if `settings.public_base_url` has no public path, but do not fail.

- [ ] **Step 10: Add the seller API integration tests**

`tests/integration/test_verifund_seller_api.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


def payload(run_id="run-1", offer_id="offer-1") -> dict:
    return {
        "run_id": run_id,
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": offer_id,
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def award(client, run_id="run-1", offer_id="offer-1") -> dict:
    response = await client.post(
        "/awards",
        json=payload(run_id, offer_id),
        headers={**OPS, "idempotency-key": f"award:{run_id}:{offer_id}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_seller_can_read_only_its_transaction(api):
    first = await award(api)
    second = await award(api, "run-2", "offer-2")
    headers = {"authorization": f"Bearer {first['seller_token']}"}
    read = await api.get(
        f"/seller/transactions/{first['transaction_id']}", headers=headers
    )
    assert read.status_code == 200
    body = read.json()
    assert body["amount_cents"] == 123400
    assert body["line_items"][0]["sku"] == "NC-700"
    assert body["allowed_actions"] == []

    wrong = await api.get(
        f"/seller/transactions/{second['transaction_id']}", headers=headers
    )
    assert wrong.status_code == 403


async def test_seller_cannot_upload_before_funding(api):
    award_body = await award(api)
    response = await api.post(
        f"/seller/transactions/{award_body['transaction_id']}/evidence",
        headers={"authorization": f"Bearer {award_body['seller_token']}"},
        data={"kind": "shipment_manifest"},
        files={"file": ("manifest.json", b'{"tracking_number":"TRK-1"}', "application/json")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"
```

- [ ] **Step 11: Run evidence, policy, seller, and service tests**

Run: `uv run pytest tests/unit/test_verifund_evidence.py tests/unit/test_verifund_policy.py tests/integration/test_verifund_seller_api.py tests/unit/test_verifund_service.py -v`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/{evidence.py,policy.py,service.py,repository.py,app.py} apps/verifund_control_plane/verifund_control_plane/api/{seller.py,ops.py} tests/unit/test_verifund_evidence.py tests/unit/test_verifund_policy.py tests/integration/test_verifund_seller_api.py
git commit -m "feat(verifund): add evidence storage, policy verification, and seller API"
```

---

### Task 11: PaymentPort, fake adapter, funding, and fake checkout

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/paypal/__init__.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/paypal/port.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/paypal/fake.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/api/checkout.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Test: `tests/unit/test_verifund_fake_payments.py`
- Test: `tests/integration/test_verifund_funding.py`

**Interfaces:**
- Produces: `OrderResult`, `CaptureResult`, `PayoutResult`, `PaymentPort`; `FakePaymentPort(repo, *, scenario, clock)`; `service.fund`, `service.refresh_funding`, `service.apply_capture`; `checkout.router` (fake checkout plus signed `/return/{token}` and `/cancel/{token}` redirects).
- Consumes: service, tokens, links, repository, and settings from Tasks 4-10.

- [ ] **Step 1: Write failing fake-payment and funding tests**

`tests/unit/test_verifund_fake_payments.py`:

```python
from datetime import UTC, datetime

import pytest

from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.fake import FakePaymentPort
from verifund_control_plane.repository import Repository

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


class Txn:
    transaction_id = "vf_1"
    amount_cents = 123400
    currency = "USD"
    seller_id = "northwind-audio"
    run_id = "run-1"


@pytest.fixture
async def repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}")
    await configure_sqlite(engine)
    repository = Repository(engine)
    await repository.create_schema()
    try:
        yield repository
    finally:
        await engine.dispose()


async def test_fake_order_and_capture(repo):
    port = FakePaymentPort(repo, scenario="success", clock=lambda: NOW)
    order = await port.create_order(
        Txn(),
        return_url="http://test/checkout/fake/token",
        cancel_url="http://test/cancel/token",
        idempotency_key="fund:vf_1:v1",
    )
    assert order.status == "CREATED"
    assert order.payer_action_url == "http://test/checkout/fake/token"

    capture = await port.capture_order(order.order_id, idempotency_key="capture:vf_1")
    assert capture.status == "COMPLETED"
    assert capture.amount_cents == 123400

    loaded = await port.get_order(order.order_id)
    assert loaded.captures[0].capture_id == capture.capture_id


async def test_fake_scenarios(repo):
    failed = FakePaymentPort(repo, scenario="order_create_failed", clock=lambda: NOW)
    with pytest.raises(VerifundError) as raised:
        await failed.create_order(
            Txn(),
            return_url="http://test/checkout/fake/token",
            cancel_url="http://test/cancel/token",
            idempotency_key="fund:vf_1:v1",
        )
    assert raised.value.code == "provider_unavailable"

    mismatch = FakePaymentPort(repo, scenario="amount_mismatch", clock=lambda: NOW)
    order = await mismatch.create_order(
        Txn(),
        return_url="http://test/checkout/fake/token",
        cancel_url="http://test/cancel/token",
        idempotency_key="fund:vf_1:v2",
    )
    capture = await mismatch.capture_order(order.order_id, idempotency_key="capture:vf_1")
    assert capture.amount_cents == 123500
```

`tests/integration/test_verifund_funding.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


def award_payload() -> dict:
    return {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def agreed(client) -> dict:
    award = (
        await client.post(
            "/awards",
            json=award_payload(),
            headers={**OPS, "idempotency-key": "award:run-1:offer-1"},
        )
    ).json()
    txid = award["transaction_id"]
    await client.post(
        f"/transactions/{txid}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers=OPS,
    )
    await client.post(
        f"/transactions/{txid}/approve",
        json={
            "approval_id": "apr-1",
            "approved_by": "demo-reviewer",
            "approved_at": NOW.isoformat(),
            "agreement_hash": award["agreement_hash"],
        },
        headers=OPS,
    )
    return award


async def fund(client, award) -> dict:
    response = await client.post(
        f"/transactions/{award['transaction_id']}/fund",
        json={
            "agreement_hash": award["agreement_hash"],
            "return_url": "http://127.0.0.1:3000/runs/run-1",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers={**OPS, "idempotency-key": f"fund:{award['transaction_id']}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_fund_returns_checkout_and_capture_funds(api):
    award = await agreed(api)
    financed = await fund(api, award)
    assert financed["state"] == "FUNDING_PENDING"
    assert "/checkout/fake/" in financed["checkout_url"]

    page = await api.get(financed["checkout_url"].replace("http://test", ""))
    assert page.status_code == 200
    assert "1234.00" in page.text

    approved = await api.post(
        financed["checkout_url"].replace("http://test", ""),
        data={"action": "approve"},
        follow_redirects=False,
    )
    assert approved.status_code == 303

    state = (
        await api.get(
            f"/transactions/{award['transaction_id']}/state", headers=OPS
        )
    ).json()
    assert state["state"] == "FUNDED"
    assert state["funding"]["status"] == "captured"
    assert state["funding"]["capture_id"].startswith("FAKE-CAP-")


async def test_fund_is_idempotent(api):
    award = await agreed(api)
    first = await fund(api, award)
    second = await fund(api, award)
    assert first["checkout_url"] == second["checkout_url"]
    state = (
        await api.get(f"/transactions/{award['transaction_id']}/state", headers=OPS)
    ).json()
    assert state["funding"]["provider_order_id"] == state["funding"].get(
        "provider_order_id"
    )


async def test_fund_rejects_external_return_url(api):
    award = await agreed(api)
    response = await api.post(
        f"/transactions/{award['transaction_id']}/fund",
        json={
            "agreement_hash": award["agreement_hash"],
            "return_url": "https://evil.example/steal",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers=OPS,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


async def test_checkout_cancel_no_ledger(api):
    award = await agreed(api)
    financed = await fund(api, award)
    canceled = await api.post(
        financed["checkout_url"].replace("http://test", ""),
        data={"action": "cancel"},
        follow_redirects=False,
    )
    assert canceled.status_code == 303
    state = (
        await api.get(f"/transactions/{award['transaction_id']}/state", headers=OPS)
    ).json()
    assert state["state"] == "CANCELED"
    assert state["cancellation"]["reason_code"] == "buyer_cancelled"


async def _issue_link(app, transaction_id: str, kind: str):
    link = app.state.links.issue(kind, transaction_id)
    async with app.state.repo.transaction() as conn:
        await app.state.repo.create_checkout_link(
            conn, link.jti, transaction_id, kind, link.expires_at
        )
    return link


async def test_paypal_return_redirects_to_the_console_run(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        console_base_url="http://console.test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            award = await agreed(client)
            financed = await fund(client, award)
            await client.post(
                financed["checkout_url"].replace("http://test", ""),
                data={"action": "approve"},
                follow_redirects=False,
            )
            link = await _issue_link(
                app, award["transaction_id"], "return"
            )
            response = await client.get(
                f"/return/{link.token}", follow_redirects=False
            )
            assert response.status_code == 303
            assert response.headers["location"] == (
                "http://console.test/runs/run-1?funding=complete"
            )


async def test_paypal_cancel_cancels_pending_funding(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        console_base_url="http://console.test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            award = await agreed(client)
            await fund(client, award)
            link = await _issue_link(
                app, award["transaction_id"], "cancel"
            )
            response = await client.get(
                f"/cancel/{link.token}", follow_redirects=False
            )
            assert response.status_code == 303
            assert response.headers["location"] == (
                "http://console.test/runs/run-1?funding=canceled"
            )
            state = (
                await client.get(
                    f"/transactions/{award['transaction_id']}/state",
                    headers=OPS,
                )
            ).json()
            assert state["state"] == "CANCELED"
            assert state["cancellation"]["reason_code"] == "buyer_cancelled"


async def test_capture_amount_mismatch_requires_review(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        fake_payment_scenario="amount_mismatch",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            award = await agreed(client)
            financed = await fund(client, award)
            await client.post(
                financed["checkout_url"].replace("http://test", ""),
                data={"action": "approve"},
                follow_redirects=False,
            )
            state = (
                await client.get(
                    f"/transactions/{award['transaction_id']}/state", headers=OPS
                )
            ).json()
            assert state["state"] == "REVIEW_REQUIRED"
            assert "funding_mismatch" in state["verification"]["reasons"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_fake_payments.py tests/integration/test_verifund_funding.py -v`
Expected: FAIL with missing payment modules and no `/fund` route.

- [ ] **Step 3: Add the payment port**

`apps/verifund_control_plane/verifund_control_plane/paypal/__init__.py` is empty.

`apps/verifund_control_plane/verifund_control_plane/paypal/port.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from verifund_control_plane.domain import TransactionRecord


@dataclass(frozen=True)
class CaptureResult:
    order_id: str
    capture_id: str
    status: str
    amount_cents: int
    currency: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: str
    payer_action_url: str | None = None
    captures: tuple[CaptureResult, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PayoutResult:
    batch_id: str
    item_id: str
    status: str
    amount_cents: int
    currency: str
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentPort(Protocol):
    async def create_order(
        self,
        txn: TransactionRecord,
        *,
        return_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> OrderResult: ...

    async def capture_order(
        self, order_id: str, *, idempotency_key: str
    ) -> CaptureResult: ...

    async def get_order(self, order_id: str) -> OrderResult: ...

    async def create_payout(
        self,
        txn: TransactionRecord,
        *,
        seller_email: str,
        batch_id: str,
        item_id: str,
    ) -> PayoutResult: ...

    async def get_payout_item(self, item_id: str) -> PayoutResult: ...

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> bool: ...
```

- [ ] **Step 4: Add fake-order persistence**

In `repository.py`, add this table in `_define_tables`:

```python
        self.fake_orders = Table(
            "fake_orders",
            self.metadata,
            Column("order_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, index=True),
            Column("status", String, nullable=False),
            Column("amount_cents", Integer, nullable=False),
            Column("currency", String, nullable=False),
            Column("payer_action_url", String, nullable=True),
            Column("capture_id", String, nullable=True),
            Column("capture_status", String, nullable=True),
            Column("capture_amount_cents", Integer, nullable=True),
            Column("capture_currency", String, nullable=True),
            Column("raw", JSON, nullable=False),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
```

Append to `Repository`:

```python
    async def save_fake_order(
        self,
        conn: AsyncConnection,
        *,
        order_id: str,
        transaction_id: str,
        status: str,
        amount_cents: int,
        currency: str,
        payer_action_url: str | None,
        raw: dict[str, Any],
    ) -> None:
        now = _iso(datetime.now(UTC))
        await conn.execute(
            self.fake_orders.insert().values(
                order_id=order_id,
                transaction_id=transaction_id,
                status=status,
                amount_cents=amount_cents,
                currency=currency,
                payer_action_url=payer_action_url,
                capture_id=None,
                capture_status=None,
                capture_amount_cents=None,
                capture_currency=None,
                raw=raw,
                created_at=now,
                updated_at=now,
            )
        )

    async def get_fake_order(self, order_id: str) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.fake_orders).where(
                        self.fake_orders.c.order_id == order_id
                    )
                )
            ).first()
        if row is None:
            raise VerifundError("not_found", "fake order not found", status_code=404)
        return dict(row._mapping)

    async def update_fake_order(
        self, conn: AsyncConnection, order_id: str, **changes: Any
    ) -> None:
        await conn.execute(
            self.fake_orders.update()
            .where(self.fake_orders.c.order_id == order_id)
            .values(**changes, updated_at=_iso(datetime.now(UTC)))
        )
```

- [ ] **Step 5: Implement the fake adapter**

`apps/verifund_control_plane/verifund_control_plane/paypal/fake.py`:

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.port import (
    CaptureResult,
    OrderResult,
    PayoutResult,
)
from verifund_control_plane.repository import Repository


class FakePaymentPort:
    def __init__(
        self,
        repo: Repository,
        *,
        scenario: str = "success",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo = repo
        self.scenario = scenario
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> str:
        return self.clock().astimezone(UTC).isoformat().replace("+00:00", "Z")

    async def create_order(
        self,
        txn: TransactionRecord,
        *,
        return_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> OrderResult:
        if self.scenario == "order_create_failed":
            raise VerifundError(
                "provider_unavailable",
                "fake payment provider is unavailable",
                status_code=503,
                retryable=True,
            )
        order_id = f"FAKE-ORDER-{uuid.uuid4().hex[:16].upper()}"
        async with self.repo.transaction() as conn:
            await self.repo.save_fake_order(
                conn,
                order_id=order_id,
                transaction_id=txn.transaction_id,
                status="CREATED",
                amount_cents=txn.amount_cents,
                currency=txn.currency,
                payer_action_url=return_url,
                raw={"id": order_id, "status": "CREATED"},
            )
        return OrderResult(
            order_id=order_id,
            status="CREATED",
            payer_action_url=return_url,
            raw={"id": order_id, "status": "CREATED"},
        )

    async def capture_order(
        self, order_id: str, *, idempotency_key: str
    ) -> CaptureResult:
        order = await self.repo.get_fake_order(order_id)
        if order.get("capture_id"):
            return self._capture(order)
        if self.scenario == "capture_pending":
            status = "PENDING"
        elif self.scenario == "capture_declined":
            status = "DECLINED"
        else:
            status = "COMPLETED"
        amount = int(order["amount_cents"])
        if self.scenario == "amount_mismatch":
            amount += 100
        capture_id = f"FAKE-CAP-{uuid.uuid4().hex[:16].upper()}"
        async with self.repo.transaction() as conn:
            await self.repo.update_fake_order(
                conn,
                order_id,
                status="COMPLETED" if status == "COMPLETED" else status,
                capture_id=capture_id,
                capture_status=status,
                capture_amount_cents=amount,
                capture_currency=order["currency"],
                raw={"id": capture_id, "status": status, "amount": amount},
            )
        return CaptureResult(
            order_id=order_id,
            capture_id=capture_id,
            status=status,
            amount_cents=amount,
            currency=str(order["currency"]),
            raw={"id": capture_id, "status": status},
        )

    def _capture(self, order: dict[str, Any]) -> CaptureResult:
        return CaptureResult(
            order_id=str(order["order_id"]),
            capture_id=str(order["capture_id"]),
            status=str(order["capture_status"]),
            amount_cents=int(order["capture_amount_cents"]),
            currency=str(order["capture_currency"]),
            raw={"id": order["capture_id"], "status": order["capture_status"]},
        )

    async def get_order(self, order_id: str) -> OrderResult:
        order = await self.repo.get_fake_order(order_id)
        captures = (self._capture(order),) if order.get("capture_id") else ()
        return OrderResult(
            order_id=str(order["order_id"]),
            status=str(order["status"]),
            payer_action_url=order.get("payer_action_url"),
            captures=captures,
            raw=order.get("raw") or {},
        )

    async def create_payout(
        self,
        txn: TransactionRecord,
        *,
        seller_email: str,
        batch_id: str,
        item_id: str,
    ) -> PayoutResult:
        if self.scenario == "payout_failure":
            status = "FAILED"
        elif self.scenario == "payout_pending":
            status = "PENDING"
        else:
            status = "SUCCESS"
        async with self.repo.transaction() as conn:
            await self.repo.upsert_payout_item(
                conn,
                item_id,
                txn.transaction_id,
                batch_id,
                item_id,
                seller_email,
                txn.amount_cents,
                txn.currency,
                status,
                {"payout_item_id": item_id, "transaction_status": status},
            )
        return PayoutResult(
            batch_id=batch_id,
            item_id=item_id,
            status=status,
            amount_cents=txn.amount_cents,
            currency=txn.currency,
            raw={"payout_item_id": item_id, "transaction_status": status},
        )

    async def get_payout_item(self, item_id: str) -> PayoutResult:
        item = await self.repo.get_payout_item(item_id)
        return PayoutResult(
            batch_id=str(item["batch_id"]),
            item_id=str(item["item_id"]),
            status=str(item["status"]),
            amount_cents=int(item["amount_cents"]),
            currency=str(item["currency"]),
            raw=item.get("raw") or {},
        )

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> bool:
        raise VerifundError(
            "forbidden",
            "fake webhooks use the test header, not PayPal verification",
            status_code=400,
        )
```

- [ ] **Step 6: Add the fake scenario setting**

In `settings.py`, add:

```python
    fake_payment_scenario: str = Field(
        default="success", validation_alias="VERIFUND_FAKE_SCENARIO"
    )
```

- [ ] **Step 7: Implement fund, refresh, and capture in the service**

Extend imports in `service.py`:

```python
from verifund_contracts import FundRequest, FundResponse, ReviewReason
from verifund_control_plane.domain import capture_ledger_entries
from verifund_control_plane.paypal.port import CaptureResult, PaymentPort
from verifund_control_plane.tokens import LinkSigner
```

Add constructor parameters `payments: PaymentPort` and `links: LinkSigner`; assign.

Append:

```python
    def _validate_console_url(self, value: str) -> None:
        from urllib.parse import urlsplit

        allowed = urlsplit(self.settings.console_base_url)
        candidate = urlsplit(value)
        if not candidate.scheme or not candidate.netloc:
            raise VerifundError(
                "invalid_request", "return and cancel URLs must be absolute", status_code=400
            )
        if (candidate.scheme, candidate.netloc) != (allowed.scheme, allowed.netloc):
            raise VerifundError(
                "invalid_request",
                "return and cancel URLs must use the console origin",
                status_code=400,
            )

    def _funding_deadline(self, record: TransactionRecord) -> datetime:
        value = (record.deadlines or {}).get("funding")
        if value:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return self._now() + timedelta(hours=self.settings.funding_timeout_hours)

    async def fund(
        self,
        transaction_id: str,
        request: FundRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> FundResponse:
        body = request.model_dump(mode="json")
        scope = f"fund:{transaction_id}"
        cached = await self._replay(scope, idempotency_key, body)
        if cached is not None:
            return FundResponse.model_validate(cached)
        record = await self.repo.get_transaction(transaction_id)
        self._check_hash(record, request.agreement_hash)
        self._validate_console_url(request.return_url)
        self._validate_console_url(request.cancel_url)
        funding = record.funding or {}
        if record.state == TransactionState.FUNDING_PENDING and funding.get(
            "provider_order_id"
        ):
            return FundResponse(
                transaction_id=transaction_id,
                state=record.state,
                checkout_url=funding.get("checkout_url")
                or funding.get("payer_action_url")
                or "",
                expires_at=self._funding_deadline(record),
            )
        if record.state != TransactionState.AGREED:
            raise VerifundError(
                "invalid_state", "transaction is not ready for funding", status_code=409
            )
        if not record.approval:
            raise VerifundError(
                "invalid_state", "buyer approval is required", status_code=409
            )
        checkout_link = self.links.issue("checkout", transaction_id)
        return_link = self.links.issue("return", transaction_id)
        cancel_link = self.links.issue("cancel", transaction_id)
        if self.settings.is_fake:
            checkout_url = (
                f"{self.settings.public_base_url.rstrip('/')}"
                f"/checkout/fake/{checkout_link.token}"
            )
            provider_return = checkout_url
            provider_cancel = (
                f"{self.settings.public_base_url.rstrip('/')}"
                f"/cancel/{cancel_link.token}"
            )
        else:
            checkout_url = ""
            provider_return = (
                f"{self.settings.public_base_url.rstrip('/')}"
                f"/return/{return_link.token}"
            )
            provider_cancel = (
                f"{self.settings.public_base_url.rstrip('/')}"
                f"/cancel/{cancel_link.token}"
            )
        deadline = self._funding_deadline(record)
        operation_id = f"op_{uuid.uuid4().hex}"
        order_key = f"fund:{transaction_id}:v1"
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state == TransactionState.FUNDING_PENDING and (
                current.funding or {}
            ).get("provider_order_id"):
                return FundResponse(
                    transaction_id=transaction_id,
                    state=current.state,
                    checkout_url=(current.funding or {}).get("checkout_url")
                    or (current.funding or {}).get("payer_action_url")
                    or "",
                    expires_at=self._funding_deadline(current),
                )
            if current.state != TransactionState.AGREED:
                raise VerifundError(
                    "invalid_state",
                    "transaction is not ready for funding",
                    status_code=409,
                )
            await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=TransactionState.AGREED,
                new_state=TransactionState.FUNDING_PENDING,
                changes={
                    "funding": {"status": "creating"},
                    "deadlines": {
                        **(current.deadlines or {}),
                        "funding": self._iso(deadline),
                    },
                },
                events=[EventInput("funding_required", {}, actor)],
                audit=AuditInput(actor, "funding_started"),
            )
            await self.repo.create_provider_operation(
                conn,
                operation_id,
                transaction_id,
                "create_order",
                order_key,
                {
                    "return_url": provider_return,
                    "cancel_url": provider_cancel,
                    "amount_cents": current.amount_cents,
                    "currency": current.currency,
                },
            )
            for kind, link in (
                ("checkout", checkout_link),
                ("return", return_link),
                ("cancel", cancel_link),
            ):
                await self.repo.create_checkout_link(
                    conn, link.jti, transaction_id, kind, link.expires_at
                )
        try:
            order = await self.payments.create_order(
                record,
                return_url=provider_return,
                cancel_url=provider_cancel,
                idempotency_key=order_key,
            )
        except VerifundError as exc:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                if current.state == TransactionState.FUNDING_PENDING:
                    await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        changes={
                            "funding": {
                                "status": "create_failed",
                                "last_error": exc.message,
                            },
                            "last_error": {
                                "code": exc.code,
                                "message": exc.message,
                            },
                        },
                    )
            await self.repo.update_provider_operation(
                operation_id,
                status="failed",
                last_error=exc.message,
                increment_attempts=True,
            )
            raise
        payer_url = order.payer_action_url or checkout_url
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state == TransactionState.FUNDING_PENDING:
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={
                        "funding": {
                            "status": "pending",
                            "provider_order_id": order.order_id,
                            "payer_action_url": payer_url,
                            "checkout_url": payer_url,
                        }
                    },
                )
            response = FundResponse(
                transaction_id=transaction_id,
                state=TransactionState.FUNDING_PENDING,
                checkout_url=payer_url,
                expires_at=deadline,
            ).model_dump(mode="json")
            if idempotency_key:
                await self.repo.put_idempotency(
                    conn,
                    scope,
                    idempotency_key,
                    sha256_hex(canonical_json(body)),
                    response,
                )
        await self.repo.update_provider_operation(
            operation_id,
            status="completed",
            provider_id=order.order_id,
            response=order.raw,
        )
        return FundResponse.model_validate(response)

    async def refresh_funding(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state in {
            TransactionState.FUNDED,
            TransactionState.FULFILLMENT_PENDING,
            TransactionState.VERIFICATION_PENDING,
            TransactionState.RELEASE_PERMITTED,
            TransactionState.PAYOUT_PENDING,
            TransactionState.RELEASED,
        }:
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        if record.state != TransactionState.FUNDING_PENDING:
            raise VerifundError(
                "invalid_state", "transaction is not awaiting funding", status_code=409
            )
        order_id = (record.funding or {}).get("provider_order_id")
        if not order_id:
            raise VerifundError(
                "provider_unavailable",
                "funding order is not yet available",
                status_code=503,
                retryable=True,
            )
        order = await self.payments.get_order(str(order_id))
        for capture in order.captures:
            await self.apply_capture(transaction_id, capture, actor=actor)
        return (await self._projection_for(transaction_id, "buyer")).model_dump(
            mode="json"
        )

    async def apply_capture(
        self, transaction_id: str, capture: CaptureResult, *, actor: str
    ) -> None:
        record = await self.repo.get_transaction(transaction_id)
        funding = dict(record.funding or {})
        if funding.get("capture_id") == capture.capture_id and record.state in {
            TransactionState.FUNDED,
            TransactionState.REVIEW_REQUIRED,
            TransactionState.RELEASED,
            TransactionState.PAYOUT_PENDING,
        }:
            return
        funding.update(
            {
                "provider_order_id": capture.order_id,
                "capture_id": capture.capture_id,
                "capture_status": capture.status,
                "capture_amount_cents": capture.amount_cents,
                "capture_currency": capture.currency,
            }
        )
        if capture.status in {"REFUNDED", "REVERSED"}:
            if record.state in {
                TransactionState.CANCELED,
                TransactionState.FAILED,
                TransactionState.REVIEW_REQUIRED,
                TransactionState.RELEASED,
                TransactionState.PAYOUT_PENDING,
                TransactionState.RELEASE_PERMITTED,
            }:
                async with self.repo.transaction() as conn:
                    current = await self.repo.get_transaction(transaction_id, conn)
                    if current.state in {
                        TransactionState.CANCELED,
                        TransactionState.FAILED,
                        TransactionState.RELEASE_PERMITTED,
                        TransactionState.PAYOUT_PENDING,
                        TransactionState.RELEASED,
                    }:
                        await self.repo.transition(
                            conn,
                            transaction_id,
                            expected_version=current.version,
                            expected_state=current.state,
                            new_state=TransactionState.REVIEW_REQUIRED,
                            changes={
                                "funding": {**funding, "status": "reversed"},
                                "verification": {
                                    "status": "failed",
                                    "reasons": ["late_capture"],
                                    "checked_at": self._iso(self._now()),
                                    "override_allowed": False,
                                },
                            },
                            events=[
                                EventInput(
                                    "review_required",
                                    {"reason": "capture_reversed"},
                                    actor,
                                )
                            ],
                            audit=AuditInput(actor, "capture_reversed"),
                        )
            return
        if capture.status == "PENDING":
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={"funding": {**funding, "status": "pending"}},
                )
            return
        if capture.status != "COMPLETED":
            if record.state == TransactionState.FUNDING_PENDING:
                async with self.repo.transaction() as conn:
                    current = await self.repo.get_transaction(transaction_id, conn)
                    if current.state == TransactionState.FUNDING_PENDING:
                        await self.repo.transition(
                            conn,
                            transaction_id,
                            expected_version=current.version,
                            expected_state=current.state,
                            new_state=TransactionState.FAILED,
                            changes={
                                "funding": {**funding, "status": "declined"},
                                "last_error": {
                                    "code": "provider_rejected",
                                    "message": f"capture {capture.status.lower()}",
                                },
                            },
                            events=[EventInput("failed", {}, actor)],
                            audit=AuditInput(actor, "capture_declined"),
                        )
            return
        funds_match = (
            capture.amount_cents == record.amount_cents
            and capture.currency == record.currency
        )
        if record.state in {TransactionState.CANCELED, TransactionState.FAILED}:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.REVIEW_REQUIRED,
                    changes={
                        "funding": {**funding, "status": "captured"},
                        "verification": {
                            "status": "failed",
                            "reasons": ["late_capture"],
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                        },
                    },
                    events=[
                        EventInput("review_required", {"reason": "late_capture"}, actor)
                    ],
                    ledger_entries=capture_ledger_entries(
                        transaction_id, capture.amount_cents
                    ),
                    audit=AuditInput(actor, "late_capture"),
                )
            return
        if record.state != TransactionState.FUNDING_PENDING:
            return
        reasons = [] if funds_match else [ReviewReason.FUNDING_MISMATCH.value]
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state != TransactionState.FUNDING_PENDING:
                return
            if funds_match:
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.FUNDED,
                    changes={"funding": {**funding, "status": "captured"}},
                    events=[EventInput("funded", {}, actor)],
                    ledger_entries=capture_ledger_entries(
                        transaction_id, capture.amount_cents
                    ),
                    audit=AuditInput(actor, "funded"),
                )
            else:
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.REVIEW_REQUIRED,
                    changes={
                        "funding": {**funding, "status": "captured"},
                        "verification": {
                            "status": "failed",
                            "reasons": reasons,
                            "checked_at": self._iso(self._now()),
                            "override_allowed": False,
                        },
                    },
                    events=[
                        EventInput(
                            "review_required",
                            {"reasons": reasons},
                            actor,
                        )
                    ],
                    ledger_entries=capture_ledger_entries(
                        transaction_id, capture.amount_cents
                    ),
                    audit=AuditInput(actor, "funding_mismatch"),
                )
```

- [ ] **Step 8: Implement the fake checkout router**

`apps/verifund_control_plane/verifund_control_plane/api/checkout.py`:

```python
from __future__ import annotations

import html

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from verifund_contracts import CancelReason, CancelRequest, TransactionState
from verifund_control_plane.errors import VerifundError

router = APIRouter()


def _service(request: Request):
    return request.app.state.service


def _claims(
    request: Request, token: str, *, expected_kind: str = "checkout"
):
    return request.app.state.link_signer.verify(
        token, expected_kind=expected_kind
    )


def _redirect(request: Request, run_id: str, status: str) -> RedirectResponse:
    base = request.app.state.settings.console_base_url.rstrip("/")
    return RedirectResponse(
        url=f"{base}/runs/{run_id}?funding={status}", status_code=303
    )


@router.get("/checkout/fake/{token}", response_class=HTMLResponse)
async def checkout_page(token: str, request: Request) -> str:
    claims = _claims(request, token)
    record = await request.app.state.repo.get_transaction(claims.transaction_id)
    if record.state != TransactionState.FUNDING_PENDING:
        return (
            "<html><body><h1>Payment is not pending</h1>"
            f"<p>State: {html.escape(record.state.value)}</p></body></html>"
        )
    amount = f"{record.amount_cents / 100:,.2f}"
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Verifund fake checkout</title></head>
<body>
  <main>
    <h1>Verifund fake checkout</h1>
    <p>Seller: <strong>{html.escape(record.seller_id)}</strong></p>
    <p>Amount: <strong>USD {amount}</strong></p>
    <p>This page is a local fake. It collects no credentials.</p>
    <form method="post">
      <button type="submit" name="action" value="approve">Approve payment</button>
      <button type="submit" name="action" value="cancel">Cancel</button>
    </form>
  </main>
</body>
</html>"""


@router.post("/checkout/fake/{token}")
async def checkout_action(
    token: str, request: Request, action: str = Form(...)
) -> RedirectResponse:
    claims = _claims(request, token)
    service = _service(request)
    record = await request.app.state.repo.get_transaction(claims.transaction_id)
    if record.state != TransactionState.FUNDING_PENDING:
        return _redirect(request, record.run_id, record.state.value.lower())
    if action == "approve":
        order_id = (record.funding or {}).get("provider_order_id")
        if not order_id:
            raise VerifundError(
                "provider_unavailable", "funding order is not ready", status_code=503
            )
        capture = await request.app.state.payments.capture_order(
            str(order_id), idempotency_key=f"capture:{record.transaction_id}:v1"
        )
        await service.apply_capture(
            record.transaction_id, capture, actor="fake-checkout"
        )
        await request.app.state.repo.consume_checkout_link(
            claims.jti, request.app.state.clock()
        )
        current = await request.app.state.repo.get_transaction(
            record.transaction_id
        )
        status = "complete" if current.state == TransactionState.FUNDED else "failed"
        return _redirect(request, record.run_id, status)
    if action == "cancel":
        await service.cancel(
            record.transaction_id,
            CancelRequest(
                reason_code=CancelReason.BUYER_CANCELLED,
                note="fake checkout canceled",
            ),
            actor="fake-checkout",
            idempotency_key=f"cancel:{record.transaction_id}:checkout",
        )
        return _redirect(request, record.run_id, "canceled")
    raise VerifundError("invalid_request", "unknown checkout action", status_code=400)


@router.get("/return/{token}")
async def paypal_return(token: str, request: Request) -> RedirectResponse:
    claims = _claims(request, token, expected_kind="return")
    await request.app.state.repo.consume_checkout_link(
        claims.jti, request.app.state.clock()
    )
    try:
        await _service(request).refresh_funding(
            claims.transaction_id, actor="paypal-return"
        )
    except VerifundError:
        pass
    record = await request.app.state.repo.get_transaction(
        claims.transaction_id
    )
    funded_states = {
        TransactionState.FUNDED,
        TransactionState.FULFILLMENT_PENDING,
        TransactionState.VERIFICATION_PENDING,
        TransactionState.RELEASE_PERMITTED,
        TransactionState.PAYOUT_PENDING,
        TransactionState.RELEASED,
    }
    status = "complete" if record.state in funded_states else "pending"
    return _redirect(request, record.run_id, status)


@router.get("/cancel/{token}")
async def paypal_cancel(token: str, request: Request) -> RedirectResponse:
    claims = _claims(request, token, expected_kind="cancel")
    await request.app.state.repo.consume_checkout_link(
        claims.jti, request.app.state.clock()
    )
    service = _service(request)
    record = await request.app.state.repo.get_transaction(
        claims.transaction_id
    )
    if record.state == TransactionState.FUNDING_PENDING and not (
        record.funding or {}
    ).get("capture_id"):
        try:
            await service.cancel(
                claims.transaction_id,
                CancelRequest(
                    reason_code=CancelReason.BUYER_CANCELLED,
                    note="PayPal checkout canceled",
                ),
                actor="paypal-cancel",
                idempotency_key=f"cancel:{claims.transaction_id}:paypal",
            )
        except VerifundError:
            pass
    return _redirect(request, record.run_id, "canceled")
```

- [ ] **Step 9: Wire links, payments, and the checkout router**

In `app.py`, import `FakePaymentPort`, `LinkSigner`, `checkout`. Create:

```python
    links = LinkSigner(
        settings.link_secret,
        checkout_ttl_minutes=settings.checkout_link_ttl_minutes,
        return_ttl_hours=settings.return_link_ttl_hours,
        clock=now,
    )
    payments = FakePaymentPort(
        repo,
        scenario=settings.fake_payment_scenario,
        clock=now,
    )
```

Pass `payments=payments, links=links` to `VerifundService`. Assign:

```python
    app.state.links = links
    app.state.link_signer = links
    app.state.payments = payments
```

Include `checkout.router`. Task 12 replaces `FakePaymentPort` with a mode-aware `build_payment_port(settings, repo, clock)`.

- [ ] **Step 10: Run fake-payment, funding, and earlier tests**

Run: `uv run pytest tests/unit/test_verifund_fake_payments.py tests/integration/test_verifund_funding.py tests/unit/test_verifund_service.py tests/unit/test_verifund_evidence.py -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/{settings.py,repository.py,service.py,app.py} apps/verifund_control_plane/verifund_control_plane/paypal apps/verifund_control_plane/verifund_control_plane/api/checkout.py tests/unit/test_verifund_fake_payments.py tests/integration/test_verifund_funding.py
git commit -m "feat(verifund): add payment port, fake adapter, funding, and fake checkout"
```

---

### Task 12: PayPal Sandbox adapter and webhook intake

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/paypal/sandbox.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/paypal/webhooks.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/api/webhooks.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Test: `tests/unit/test_verifund_sandbox_paypal.py`
- Test: `tests/integration/test_verifund_webhooks.py`

**Interfaces:**
- Produces: `PayPalSandboxPaymentPort(...)`; `paypal.webhooks.dispatch(service, event)`; `webhooks.router`; repository `find_transaction_by_order_id`, `find_transaction_by_capture_id`; `service.apply_capture_by_order`.
- Consumes: `PaymentPort`, fake adapter, service, repository, and settings from Tasks 7-11.

- [ ] **Step 1: Write failing Sandbox adapter tests**

`tests/unit/test_verifund_sandbox_paypal.py`:

```python
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.sandbox import PayPalSandboxPaymentPort

TXN = SimpleNamespace(
    transaction_id="vf_1",
    amount_cents=123400,
    currency="USD",
    seller_id="northwind-audio",
    run_id="run-1",
)


def port(handler) -> PayPalSandboxPaymentPort:
    return PayPalSandboxPaymentPort(
        base_url="https://api-m.sandbox.paypal.com",
        client_id="client",
        client_secret="secret",
        webhook_id="WH-1",
        transport=httpx.MockTransport(handler),
    )


def token_response() -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": "tok", "expires_in": 3600}
    )


async def test_create_order_uses_request_id_and_payer_action():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            assert request.headers["authorization"].startswith("Basic ")
            return token_response()
        assert request.url.path == "/v2/checkout/orders"
        assert request.headers["paypal-request-id"] == "fund:vf_1:v1"
        assert request.headers["authorization"] == "Bearer tok"
        body = json.loads(request.content)
        assert body["intent"] == "CAPTURE"
        unit = body["purchase_units"][0]
        assert unit["custom_id"] == "vf_1"
        assert unit["amount"] == {"currency_code": "USD", "value": "1234.00"}
        context = body["payment_source"]["paypal"]["experience_context"]
        assert context["user_action"] == "PAY_NOW"
        assert context["return_url"] == "https://console.test/return/t"
        assert context["cancel_url"] == "https://console.test/cancel/t"
        return httpx.Response(
            201,
            json={
                "id": "ORDER-1",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [
                    {"rel": "self", "href": "https://api.test/orders/ORDER-1"},
                    {"rel": "payer-action", "href": "https://paypal.test/approve"},
                ],
            },
        )

    order = await port(handler).create_order(
        TXN,
        return_url="https://console.test/return/t",
        cancel_url="https://console.test/cancel/t",
        idempotency_key="fund:vf_1:v1",
    )
    assert order.order_id == "ORDER-1"
    assert order.status == "PAYER_ACTION_REQUIRED"
    assert order.payer_action_url == "https://paypal.test/approve"


async def test_capture_order_parses_amount():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        assert request.url.path == "/v2/checkout/orders/ORDER-1/capture"
        assert request.headers["paypal-request-id"] == "capture:vf_1:v1"
        return httpx.Response(
            201,
            json={
                "id": "ORDER-1",
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAP-1",
                                    "status": "COMPLETED",
                                    "amount": {
                                        "value": "1234.00",
                                        "currency_code": "USD",
                                    },
                                    "supplementary_data": {
                                        "related_ids": {"order_id": "ORDER-1"}
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
        )

    capture = await port(handler).capture_order(
        "ORDER-1", idempotency_key="capture:vf_1:v1"
    )
    assert capture.capture_id == "CAP-1"
    assert capture.status == "COMPLETED"
    assert capture.amount_cents == 123400
    assert capture.currency == "USD"


async def test_verify_webhook_posts_transmission_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        assert request.url.path == "/v1/notifications/verify-webhook-signature"
        body = json.loads(request.content)
        assert body["webhook_id"] == "WH-1"
        assert body["transmission_id"] == "t-1"
        assert body["transmission_sig"] == "sig"
        assert body["webhook_event"]["id"] == "WH-EVT-1"
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    raw = json.dumps({"id": "WH-EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"}).encode()
    verified = await port(handler).verify_webhook(
        {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://api.test/cert",
            "paypal-transmission-id": "t-1",
            "paypal-transmission-sig": "sig",
            "paypal-transmission-time": "2026-10-27T12:00:00Z",
        },
        raw,
    )
    assert verified is True


async def test_verify_webhook_returns_false_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        return httpx.Response(200, json={"verification_status": "FAILURE"})

    assert (
        await port(handler).verify_webhook({}, b'{"id":"WH-EVT-1"}') is False
    )


async def test_provider_errors_are_classified():
    def unavailable(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        return httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE"})

    with pytest.raises(VerifundError) as raised:
        await port(unavailable).get_order("ORDER-1")
    assert raised.value.code == "provider_unavailable"
    assert raised.value.retryable

    def rejected(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY"})

    with pytest.raises(VerifundError) as raised:
        await port(rejected).get_order("ORDER-1")
    assert raised.value.code == "provider_rejected"
    assert not raised.value.retryable


async def test_create_payout_resolves_provider_item_id():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        if request.url.path == "/v1/payments/payouts" and request.method == "POST":
            body = json.loads(request.content)
            header = body["sender_batch_header"]
            item = body["items"][0]
            assert header["sender_batch_id"] == "batch-vf_1"
            assert item["sender_item_id"] == "item-vf_1"
            assert item["receiver"] == "seller@example.test"
            assert item["amount"] == {"value": "1234.00", "currency": "USD"}
            return httpx.Response(
                201,
                json={
                    "batch_header": {
                        "payout_batch_id": "BATCH-1",
                        "batch_status": "PENDING",
                    }
                },
            )
        assert request.url.path == "/v1/payments/payouts/BATCH-1"
        return httpx.Response(
            200,
            json={
                "batch_header": {
                    "payout_batch_id": "BATCH-1",
                    "batch_status": "PENDING",
                },
                "items": [
                    {
                        "payout_item_id": "ITEM-1",
                        "transaction_status": "PENDING",
                        "payout_item": {
                            "sender_item_id": "item-vf_1",
                            "receiver": "seller@example.test",
                            "amount": {"value": "1234.00", "currency": "USD"},
                        },
                    }
                ],
            },
        )

    payout = await port(handler).create_payout(
        TXN,
        seller_email="seller@example.test",
        batch_id="batch-vf_1",
        item_id="item-vf_1",
    )
    assert payout.batch_id == "BATCH-1"
    assert payout.item_id == "ITEM-1"
    assert payout.status == "PENDING"
    assert payout.amount_cents == 123400
```

- [ ] **Step 2: Write failing webhook integration tests**

`tests/integration/test_verifund_webhooks.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}
FAKE = {"x-verifund-fake-webhook": "dev-verifund-fake-webhook"}


def award_payload() -> dict:
    return {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def awaiting_capture(client) -> tuple[dict, str]:
    award = (
        await client.post(
            "/awards",
            json=award_payload(),
            headers={**OPS, "idempotency-key": "award:run-1:offer-1"},
        )
    ).json()
    txid = award["transaction_id"]
    await client.post(
        f"/transactions/{txid}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers=OPS,
    )
    await client.post(
        f"/transactions/{txid}/approve",
        json={
            "approval_id": "apr-1",
            "approved_by": "demo-reviewer",
            "approved_at": NOW.isoformat(),
            "agreement_hash": award["agreement_hash"],
        },
        headers=OPS,
    )
    financed = await client.post(
        f"/transactions/{txid}/fund",
        json={
            "agreement_hash": award["agreement_hash"],
            "return_url": "http://127.0.0.1:3000/runs/run-1",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers={**OPS, "idempotency-key": f"fund:{txid}"},
    )
    assert financed.status_code == 200, financed.text
    state = (
        await client.get(f"/transactions/{txid}/state", headers=OPS)
    ).json()
    return award, state["funding"]["provider_order_id"]


def capture_event(event_id: str, order_id: str) -> dict:
    return {
        "id": event_id,
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAP-1",
            "status": "COMPLETED",
            "amount": {"value": "1234.00", "currency_code": "USD"},
            "supplementary_data": {"related_ids": {"order_id": order_id}},
        },
    }


async def test_capture_webhook_funds_transaction(api):
    award, order_id = await awaiting_capture(api)
    response = await api.post(
        "/webhooks/paypal",
        json=capture_event("WH-1", order_id),
        headers=FAKE,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "processed"

    state = (
        await api.get(f"/transactions/{award['transaction_id']}/state", headers=OPS)
    ).json()
    assert state["state"] == "FUNDED"
    assert state["funding"]["capture_id"] == "CAP-1"

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    balances = await repo.ledger_balances(award["transaction_id"])
    assert balances["held_funds"] == 123400

    stored = await repo.get_webhook_event("WH-1")
    assert stored["verified"] == 0
    assert stored["status"] == "processed"


async def test_duplicate_webhook_is_idempotent(api):
    award, order_id = await awaiting_capture(api)
    event = capture_event("WH-1", order_id)
    assert (await api.post("/webhooks/paypal", json=event, headers=FAKE)).status_code == 200
    duplicate = await api.post("/webhooks/paypal", json=event, headers=FAKE)
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    balances = await repo.ledger_balances(award["transaction_id"])
    assert balances["held_funds"] == 123400
    state = (
        await api.get(f"/transactions/{award['transaction_id']}/state", headers=OPS)
    ).json()
    assert state["funding"]["capture_id"] == "CAP-1"


async def test_fake_webhook_requires_test_secret(api):
    _, order_id = await awaiting_capture(api)
    response = await api.post(
        "/webhooks/paypal",
        json=capture_event("WH-1", order_id),
        headers={"x-verifund-fake-webhook": "wrong"},
    )
    assert response.status_code == 401


async def test_unknown_order_is_unmatched(api):
    response = await api.post(
        "/webhooks/paypal",
        json=capture_event("WH-2", "ORDER-DOES-NOT-EXIST"),
        headers=FAKE,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unmatched"

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    stored = await repo.get_webhook_event("WH-2")
    assert stored["status"] == "unmatched"


async def test_unknown_event_type_is_ignored(api):
    response = await api.post(
        "/webhooks/paypal",
        json={
            "id": "WH-3",
            "event_type": "CHECKOUT.ORDER.COMPLETED",
            "resource": {"id": "ORDER-1"},
        },
        headers=FAKE,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_sandbox_paypal.py tests/integration/test_verifund_webhooks.py -v`
Expected: FAIL with `ModuleNotFoundError: verifund_control_plane.paypal.sandbox` and 404 for `/webhooks/paypal`.

- [ ] **Step 4: Implement the Sandbox adapter**

`apps/verifund_control_plane/verifund_control_plane/paypal/sandbox.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Mapping

import httpx

from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.port import (
    CaptureResult,
    OrderResult,
    PayoutResult,
)

SANDBOX_HOST = "https://api-m.sandbox.paypal.com"


def _value(amount_cents: int) -> str:
    return f"{Decimal(amount_cents) / Decimal(100):.2f}"


def _cents(value: Any) -> int:
    return int((Decimal(str(value)) * 100).to_integral_value())


class PayPalSandboxPaymentPort:
    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        webhook_id: str,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if base_url.rstrip("/") != SANDBOX_HOST:
            raise VerifundError(
                "invalid_request",
                "only the PayPal sandbox host is allowed",
                status_code=400,
            )
        self.base_url = SANDBOX_HOST
        self.client_id = client_id
        self.client_secret = client_secret
        self.webhook_id = webhook_id
        self.timeout = timeout
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))
        self._token: str | None = None
        self._token_expires_at = datetime.min.replace(tzinfo=UTC)

    def _now(self) -> datetime:
        return self.clock().astimezone(UTC)

    def _checked(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 429 or response.status_code >= 500:
            raise VerifundError(
                "provider_unavailable",
                "PayPal is temporarily unavailable",
                status_code=503,
                retryable=True,
                details={"status": response.status_code},
            )
        if response.status_code >= 400:
            raise VerifundError(
                "provider_rejected",
                "PayPal rejected the request",
                status_code=502,
                details={"status": response.status_code},
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise VerifundError(
                "provider_ambiguous",
                "PayPal returned a non-JSON response",
                status_code=502,
                retryable=True,
            ) from exc
        if not isinstance(data, dict):
            raise VerifundError(
                "provider_ambiguous",
                "PayPal returned an unexpected payload",
                status_code=502,
                retryable=True,
            )
        return data

    async def _access_token(self) -> str:
        if self._token and self._now() < self._token_expires_at - timedelta(
            seconds=60
        ):
            return self._token
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport
        ) as client:
            response = await client.post(
                f"{self.base_url}/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"accept": "application/json"},
            )
        data = self._checked(response)
        token = data.get("access_token")
        if not token:
            raise VerifundError(
                "provider_unavailable",
                "PayPal did not return an access token",
                status_code=503,
                retryable=True,
            )
        self._token = str(token)
        expires_in = int(data.get("expires_in") or 300)
        self._token_expires_at = self._now() + timedelta(seconds=expires_in)
        return self._token

    async def _call(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        token = await self._access_token()
        headers = {
            "authorization": f"Bearer {token}",
            "accept": "application/json",
        }
        if idempotency_key:
            headers["paypal-request-id"] = idempotency_key
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport
        ) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=payload,
            )
        return self._checked(response)

    async def create_order(
        self,
        txn: TransactionRecord,
        *,
        return_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> OrderResult:
        data = await self._call(
            "POST",
            "/v2/checkout/orders",
            payload={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": txn.transaction_id,
                        "custom_id": txn.transaction_id,
                        "invoice_id": txn.transaction_id,
                        "description": f"Verifund {txn.transaction_id}",
                        "amount": {
                            "currency_code": txn.currency,
                            "value": _value(txn.amount_cents),
                        },
                    }
                ],
                "payment_source": {
                    "paypal": {
                        "experience_context": {
                            "user_action": "PAY_NOW",
                            "return_url": return_url,
                            "cancel_url": cancel_url,
                        }
                    }
                },
            },
            idempotency_key=idempotency_key,
        )
        links = data.get("links") or []
        payer_url = next(
            (
                link.get("href")
                for link in links
                if link.get("rel") in {"payer-action", "approve"}
            ),
            None,
        )
        return OrderResult(
            order_id=str(data["id"]),
            status=str(data.get("status") or "CREATED"),
            payer_action_url=payer_url,
            raw=data,
        )

    def _capture(
        self, data: dict[str, Any], *, fallback_order_id: str
    ) -> CaptureResult:
        captures: list[dict[str, Any]] = []
        for unit in data.get("purchase_units") or []:
            captures.extend(
                ((unit.get("payments") or {}).get("captures") or [])
            )
        if not captures:
            raise VerifundError(
                "provider_ambiguous",
                "PayPal response contains no capture",
                status_code=502,
                retryable=True,
                details={"order_id": fallback_order_id},
            )
        raw = captures[0]
        amount = raw.get("amount") or {}
        related = ((raw.get("supplementary_data") or {}).get("related_ids") or {})
        return CaptureResult(
            order_id=str(related.get("order_id") or fallback_order_id),
            capture_id=str(raw["id"]),
            status=str(raw.get("status") or "UNKNOWN"),
            amount_cents=_cents(amount.get("value", "0")),
            currency=str(amount.get("currency_code") or ""),
            raw=raw,
        )

    async def capture_order(
        self, order_id: str, *, idempotency_key: str
    ) -> CaptureResult:
        data = await self._call(
            "POST",
            f"/v2/checkout/orders/{order_id}/capture",
            payload={},
            idempotency_key=idempotency_key,
        )
        return self._capture(data, fallback_order_id=order_id)

    async def get_order(self, order_id: str) -> OrderResult:
        data = await self._call("GET", f"/v2/checkout/orders/{order_id}")
        captures: tuple[CaptureResult, ...] = ()
        if any(
            (unit.get("payments") or {}).get("captures")
            for unit in data.get("purchase_units") or []
        ):
            captures = (self._capture(data, fallback_order_id=order_id),)
        return OrderResult(
            order_id=str(data.get("id") or order_id),
            status=str(data.get("status") or "UNKNOWN"),
            captures=captures,
            raw=data,
        )

    async def create_payout(
        self,
        txn: TransactionRecord,
        *,
        seller_email: str,
        batch_id: str,
        item_id: str,
    ) -> PayoutResult:
        data = await self._call(
            "POST",
            "/v1/payments/payouts",
            payload={
                "sender_batch_header": {
                    "sender_batch_id": batch_id,
                    "email_subject": "You have a payment",
                    "email_message": "You received a payment from Verifund.",
                },
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "amount": {
                            "value": _value(txn.amount_cents),
                            "currency": txn.currency,
                        },
                        "receiver": seller_email,
                        "note": f"Verifund {txn.transaction_id}",
                        "sender_item_id": item_id,
                    }
                ],
            },
            idempotency_key=batch_id,
        )
        header = data.get("batch_header") or {}
        provider_batch = str(header.get("payout_batch_id") or batch_id)
        batch = await self._call(
            "GET", f"/v1/payments/payouts/{provider_batch}"
        )
        match = next(
            (
                candidate
                for candidate in batch.get("items") or []
                if str((candidate.get("payout_item") or {}).get("sender_item_id"))
                == item_id
            ),
            None,
        )
        if match is None:
            raise VerifundError(
                "provider_ambiguous",
                "PayPal payout item is not available yet",
                status_code=503,
                retryable=True,
                details={"batch_id": provider_batch},
            )
        item = match.get("payout_item") or {}
        amount = item.get("amount") or {}
        return PayoutResult(
            batch_id=provider_batch,
            item_id=str(match["payout_item_id"]),
            status=str(
                match.get("transaction_status")
                or header.get("batch_status")
                or "PENDING"
            ),
            amount_cents=_cents(amount.get("value", "0")),
            currency=str(amount.get("currency_code") or txn.currency),
            raw={"batch_header": header, "item": match},
        )

    async def get_payout_item(self, item_id: str) -> PayoutResult:
        data = await self._call(
            "GET", f"/v1/payments/payouts-item/{item_id}"
        )
        item = data.get("payout_item") or {}
        amount = item.get("amount") or {}
        return PayoutResult(
            batch_id=str(data.get("payout_batch_id") or ""),
            item_id=str(data.get("payout_item_id") or item_id),
            status=str(
                data.get("transaction_status")
                or data.get("status")
                or "UNKNOWN"
            ),
            amount_cents=_cents(amount.get("value", "0")),
            currency=str(amount.get("currency_code") or "USD"),
            raw=data,
        )

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> bool:
        try:
            event = json.loads(raw_body)
        except ValueError:
            return False
        try:
            data = await self._call(
                "POST",
                "/v1/notifications/verify-webhook-signature",
                payload={
                    "auth_algo": headers.get("paypal-auth-algo", ""),
                    "cert_url": headers.get("paypal-cert-url", ""),
                    "transmission_id": headers.get(
                        "paypal-transmission-id", ""
                    ),
                    "transmission_sig": headers.get(
                        "paypal-transmission-sig", ""
                    ),
                    "transmission_time": headers.get(
                        "paypal-transmission-time", ""
                    ),
                    "webhook_id": self.webhook_id,
                    "webhook_event": event,
                },
            )
        except VerifundError as exc:
            if exc.code == "provider_rejected":
                return False
            raise
        return data.get("verification_status") == "SUCCESS"
```

- [ ] **Step 5: Implement webhook dispatch**

`apps/verifund_control_plane/verifund_control_plane/paypal/webhooks.py`:

```python
from __future__ import annotations

from decimal import Decimal
from typing import Any

from verifund_control_plane.paypal.port import CaptureResult

CAPTURE_EVENTS = {
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.PENDING",
    "PAYMENT.CAPTURE.DECLINED",
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.REVERSED",
}
REFUND_EVENTS = {
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.REVERSED",
}


def capture_order_id(resource: dict[str, Any]) -> str | None:
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    value = related.get("order_id")
    return str(value) if value else None


def _up_capture_id(resource: dict[str, Any]) -> str | None:
    for link in resource.get("links") or []:
        if link.get("rel") == "up" and link.get("href"):
            return str(link["href"]).rstrip("/").rsplit("/", 1)[-1]
    return None


def _cents(value: Any) -> int:
    return int((Decimal(str(value)) * 100).to_integral_value())


def parse_capture(
    resource: dict[str, Any], *, order_id: str, capture_id: str | None = None,
    status: str | None = None,
) -> CaptureResult:
    amount = resource.get("amount") or {}
    return CaptureResult(
        order_id=order_id,
        capture_id=capture_id or str(resource.get("id") or ""),
        status=status or str(resource.get("status") or "UNKNOWN"),
        amount_cents=_cents(amount.get("value", "0")),
        currency=str(amount.get("currency_code") or ""),
        raw=resource,
    )


async def dispatch(service, event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    resource = event.get("resource") or {}
    if event_type not in CAPTURE_EVENTS:
        return "ignored"
    order_id = capture_order_id(resource)
    if order_id:
        capture = parse_capture(resource, order_id=order_id)
        applied = await service.apply_capture_by_order(
            order_id, capture, actor="webhook:paypal"
        )
        return "processed" if applied else "unmatched"
    if event_type in REFUND_EVENTS:
        capture_id = _up_capture_id(resource)
        if not capture_id:
            return "unmatched"
        record = await service.repo.find_transaction_by_capture_id(capture_id)
        if record is None:
            return "unmatched"
        order_id = str(
            (record.funding or {}).get("provider_order_id") or ""
        )
        capture = parse_capture(
            resource,
            order_id=order_id,
            capture_id=capture_id,
            status="REFUNDED" if event_type.endswith("REFUNDED") else "REVERSED",
        )
        await service.apply_capture(
            record.transaction_id, capture, actor="webhook:paypal"
        )
        return "processed"
    return "unmatched"
```

- [ ] **Step 6: Add repository lookup helpers**

Append to `Repository`:

```python
    async def find_transaction_by_order_id(
        self, order_id: str
    ) -> TransactionRecord | None:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.transactions).where(
                        self.transactions.c.funding.is_not(None)
                    )
                )
            ).all()
        for row in rows:
            if str((row.funding or {}).get("provider_order_id") or "") == order_id:
                return self._record(row)
        return None

    async def find_transaction_by_capture_id(
        self, capture_id: str
    ) -> TransactionRecord | None:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(self.transactions).where(
                        self.transactions.c.funding.is_not(None)
                    )
                )
            ).all()
        for row in rows:
            if str((row.funding or {}).get("capture_id") or "") == capture_id:
                return self._record(row)
        return None

    async def find_payout_transaction(self, batch_id: str) -> str | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(self.payout_items).where(
                        self.payout_items.c.batch_id == batch_id
                    )
                )
            ).first()
        return str(row.transaction_id) if row is not None else None
```

- [ ] **Step 7: Add `apply_capture_by_order` to the service**

Append to `VerifundService`:

```python
    async def apply_capture_by_order(
        self, order_id: str, capture: CaptureResult, *, actor: str
    ) -> bool:
        record = await self.repo.find_transaction_by_order_id(order_id)
        if record is None:
            return False
        await self.apply_capture(record.transaction_id, capture, actor=actor)
        return True
```

- [ ] **Step 8: Implement the webhook router**

`apps/verifund_control_plane/verifund_control_plane/api/webhooks.py`:

```python
from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import APIRouter, Request

from verifund_control_plane.domain import sha256_hex
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.webhooks import dispatch

router = APIRouter()


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    raw = await request.body()
    if settings.is_fake:
        provided = request.headers.get("x-verifund-fake-webhook", "")
        if not settings.fake_webhook_secret or not secrets.compare_digest(
            provided, settings.fake_webhook_secret
        ):
            raise VerifundError(
                "unauthorized", "fake webhook secret is required", status_code=401
            )
        verified = False
    else:
        verified = await request.app.state.payments.verify_webhook(
            request.headers, raw
        )
        if not verified:
            raise VerifundError(
                "unauthorized",
                "PayPal webhook signature is invalid",
                status_code=401,
            )
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise VerifundError(
            "invalid_request", "webhook body is not JSON", status_code=400
        ) from exc
    event_id = str(payload.get("id") or "")
    event_type = str(payload.get("event_type") or "")
    if not event_id or not event_type:
        raise VerifundError(
            "invalid_request", "webhook event id and type are required", status_code=400
        )
    resource = payload.get("resource") or {}
    resource_id = resource.get("id")
    repo = request.app.state.repo
    async with repo.transaction() as conn:
        created = await repo.insert_webhook_event(
            conn,
            event_id,
            event_type,
            str(resource_id) if resource_id else None,
            sha256_hex(raw),
            payload,
            settings.mode,
            verified,
        )
    if not created:
        return {"status": "duplicate", "verified": verified}
    try:
        status = await dispatch(request.app.state.service, payload)
    except VerifundError as exc:
        await repo.mark_webhook_event(
            event_id, "failed", last_error=exc.message
        )
        raise
    except Exception as exc:
        await repo.mark_webhook_event(
            event_id, "failed", last_error=type(exc).__name__
        )
        raise VerifundError(
            "internal", "webhook processing failed", status_code=500
        ) from exc
    await repo.mark_webhook_event(event_id, status)
    return {"status": status, "verified": verified}
```

- [ ] **Step 9: Make the payment port mode-aware and mount the router**

In `app.py`, import:

```python
from verifund_control_plane.paypal.fake import FakePaymentPort
from verifund_control_plane.paypal.sandbox import PayPalSandboxPaymentPort
```

Replace the unconditional `FakePaymentPort(...)` with:

```python
    if settings.is_sandbox:
        payments = PayPalSandboxPaymentPort(
            base_url=settings.paypal_api_base,
            client_id=settings.paypal_client_id,
            client_secret=settings.paypal_client_secret,
            webhook_id=settings.paypal_webhook_id,
            clock=now,
        )
    else:
        payments = FakePaymentPort(
            repo,
            scenario=settings.fake_payment_scenario,
            clock=now,
        )
```

Import `webhooks` and include:

```python
    app.include_router(webhooks.router)
```

- [ ] **Step 10: Run the PayPal and webhook tests**

Run: `uv run pytest tests/unit/test_verifund_sandbox_paypal.py tests/integration/test_verifund_webhooks.py tests/unit/test_verifund_fake_payments.py tests/integration/test_verifund_funding.py -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/paypal/{sandbox.py,webhooks.py} apps/verifund_control_plane/verifund_control_plane/api/webhooks.py apps/verifund_control_plane/verifund_control_plane/{repository.py,service.py,app.py} tests/unit/test_verifund_sandbox_paypal.py tests/integration/test_verifund_webhooks.py
git commit -m "feat(verifund): add PayPal sandbox adapter and verified webhook intake"
```

---

### Task 13: Purchase order, verification, release, payout, receipt, and seller-token ops

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Test: `tests/integration/test_verifund_lifecycle.py`

**Interfaces:**
- Produces: `service.report_purchase_order`, `service.verify`, `service.flag_review`, `service.release`, `service.retry_payout`, `service.refresh_payout`, `service.get_receipt`, `service.reissue_seller_token`, `service.revoke_seller_token`; all remaining ops routes.
- Consumes: `PaymentPort`, `ReceiptSigner`, `payout_ledger_entries`, `build_receipt_payload`, and all earlier tasks.

- [ ] **Step 1: Write the failing lifecycle and review tests**

`tests/integration/test_verifund_lifecycle.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
import pytest

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


def award_payload() -> dict:
    return {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def award(client) -> dict:
    response = await client.post(
        "/awards",
        json=award_payload(),
        headers={**OPS, "idempotency-key": "award:run-1:offer-1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def accept(client, award_body: dict) -> None:
    response = await client.post(
        f"/transactions/{award_body['transaction_id']}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award_body["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
        },
        headers=OPS,
    )
    assert response.status_code == 200, response.text


async def approve(client, award_body: dict) -> None:
    response = await client.post(
        f"/transactions/{award_body['transaction_id']}/approve",
        json={
            "approval_id": "apr-1",
            "approved_by": "demo-reviewer",
            "approved_at": NOW.isoformat(),
            "note": "approved",
            "agreement_hash": award_body["agreement_hash"],
        },
        headers=OPS,
    )
    assert response.status_code == 200, response.text


async def fund_and_capture(client, award_body: dict) -> None:
    txid = award_body["transaction_id"]
    funded = await client.post(
        f"/transactions/{txid}/fund",
        json={
            "agreement_hash": award_body["agreement_hash"],
            "return_url": "http://127.0.0.1:3000/runs/run-1",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers={**OPS, "idempotency-key": f"fund:{txid}"},
    )
    assert funded.status_code == 200, funded.text
    checkout_url = funded.json()["checkout_url"]
    path = urlsplit(checkout_url).path
    page = await client.get(path)
    assert page.status_code == 200
    approved = await client.post(
        path, data={"action": "approve"}, follow_redirects=False
    )
    assert approved.status_code == 303


def purchase_order(award_body: dict) -> dict:
    return {
        "agreement_hash": award_body["agreement_hash"],
        "seller_order_id": "MM-1",
        "offer_id": "offer-1",
        "quantity": 12,
        "total_cents": 123400,
        "currency": "USD",
        "tracking_number": "TRK-1",
        "carrier": "Northwind Logistics",
        "reserved_at": NOW.isoformat(),
        "eta": (NOW + timedelta(days=7)).isoformat(),
        "line_items": [
            {
                "sku": "NC-700",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
    }


async def upload(
    client, award_body: dict, kind: str, payload: dict
) -> httpx.Response:
    return await client.post(
        f"/seller/transactions/{award_body['transaction_id']}/evidence",
        headers={
            "authorization": f"Bearer {award_body['seller_token']}"
        },
        data={"kind": kind},
        files={
            "file": (
                f"{kind}.json",
                json.dumps(payload).encode(),
                "application/json",
            )
        },
    )


async def test_fake_lifecycle_reaches_released_with_receipt(api):
    award_body = await award(api)
    txid = award_body["transaction_id"]
    await accept(api, award_body)
    await approve(api, award_body)
    await fund_and_capture(api, award_body)

    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "FUNDED"

    reported = await api.post(
        f"/transactions/{txid}/purchase-order",
        json=purchase_order(award_body),
        headers={**OPS, "idempotency-key": f"po:{txid}"},
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["state"] == "FULFILLMENT_PENDING"

    manifest = {
        "tracking_number": "TRK-1",
        "carrier": "Northwind Logistics",
        "shipped_at": (NOW - timedelta(days=2)).isoformat(),
        "seller_id": "northwind-audio",
        "agreement_hash": award_body["agreement_hash"],
        "line_items": [{"sku": "NC-700", "quantity": 12}],
    }
    uploaded = await upload(api, award_body, "shipment_manifest", manifest)
    assert uploaded.status_code == 201, uploaded.text
    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "VERIFICATION_PENDING"

    delivery = {
        "delivered_at": (NOW - timedelta(hours=30)).isoformat(),
        "recipient": "Demo Buyer",
    }
    uploaded = await upload(api, award_body, "delivery_confirmation", delivery)
    assert uploaded.status_code == 201, uploaded.text
    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "RELEASE_PERMITTED"
    assert state["verification"]["status"] == "passed"

    released = await api.post(
        f"/transactions/{txid}/release",
        json={
            "released_by": "demo-reviewer",
            "note": "Evidence verified",
            "override": False,
        },
        headers=OPS,
    )
    assert released.status_code == 200, released.text
    assert released.json()["state"] == "RELEASED"
    assert released.json()["payout"]["status"] == "SUCCESS"

    receipt = await api.get(f"/transactions/{txid}/receipt", headers=OPS)
    assert receipt.status_code == 200, receipt.text
    body = receipt.json()
    assert body["verified"] is True
    assert body["payload"]["transaction_id"] == txid
    assert body["payload"]["payout_item_id"] == f"item_{txid}"
    assert len(body["payload"]["evidence_hashes"]) == 2

    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["receipt_available"] is True

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    balances = await repo.ledger_balances(txid)
    assert balances == {
        "held_funds": 0,
        "platform_cash": 123400,
        "seller_paid": 123400,
    }


async def test_purchase_order_mismatch_is_rejected(api):
    award_body = await award(api)
    txid = award_body["transaction_id"]
    await accept(api, award_body)
    await approve(api, award_body)
    await fund_and_capture(api, award_body)

    body = purchase_order(award_body)
    body["total_cents"] = 120000
    response = await api.post(
        f"/transactions/{txid}/purchase-order",
        json=body,
        headers={**OPS, "idempotency-key": f"po:{txid}"},
    )
    assert response.status_code == 409
    state = (await api.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "FUNDED"


async def test_release_override_requires_note_and_allows_manual_flag(api):
    award_body = await award(api)
    txid = award_body["transaction_id"]
    await accept(api, award_body)
    await approve(api, award_body)
    await fund_and_capture(api, award_body)

    flagged = await api.post(
        f"/transactions/{txid}/flag-review",
        json={"reason": "manual_check", "note": "look closer"},
        headers={**OPS, "x-verifund-actor": "console:reviewer"},
    )
    assert flagged.status_code == 200, flagged.text
    assert flagged.json()["state"] == "REVIEW_REQUIRED"
    assert flagged.json()["verification"]["override_allowed"] is True

    refused = await api.post(
        f"/transactions/{txid}/release",
        json={
            "released_by": "demo-reviewer",
            "note": "",
            "override": False,
        },
        headers={**OPS, "x-verifund-actor": "console:reviewer"},
    )
    assert refused.status_code == 403

    released = await api.post(
        f"/transactions/{txid}/release",
        json={
            "released_by": "demo-reviewer",
            "note": "checked evidence manually",
            "override": True,
        },
        headers={**OPS, "x-verifund-actor": "console:reviewer"},
    )
    assert released.status_code == 200, released.text
    assert released.json()["state"] == "RELEASED"


async def test_seller_token_reissue_revokes_old_token(api):
    award_body = await award(api)
    txid = award_body["transaction_id"]
    old_token = award_body["seller_token"]

    reissued = await api.post(
        f"/transactions/{txid}/seller-token",
        json={
            "run_id": "run-1",
            "transaction_id": txid,
            "seller_id": "northwind-audio",
            "purpose": "purchase_order",
        },
        headers=OPS,
    )
    assert reissued.status_code == 200, reissued.text
    new_token = reissued.json()["seller_token"]
    assert new_token != old_token

    stale = await api.get(
        f"/seller/transactions/{txid}",
        headers={"authorization": f"Bearer {old_token}"},
    )
    assert stale.status_code == 401

    current = await api.get(
        f"/seller/transactions/{txid}",
        headers={"authorization": f"Bearer {new_token}"},
    )
    assert current.status_code == 200

    revoked = await api.post(
        f"/transactions/{txid}/seller-token/revoke", headers=OPS
    )
    assert revoked.status_code == 200
    gone = await api.get(
        f"/seller/transactions/{txid}",
        headers={"authorization": f"Bearer {new_token}"},
    )
    assert gone.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_verifund_lifecycle.py -v`
Expected: FAIL with 404 for `/purchase-order`, `/release`, `/flag-review`, `/seller-token`, and `/receipt`.

- [ ] **Step 3: Add purchase-order, review, and seller-token service methods**

Extend the imports in `service.py`:

```python
from verifund_contracts import (
    FlagReviewRequest,
    PurchaseOrderReport,
    ReceiptResponse,
    ReleaseRequest,
    SellerTokenResponse,
)
from verifund_control_plane.domain import (
    NON_OVERRIDABLE_REASONS,
    payout_ledger_entries,
)
from verifund_control_plane.paypal.port import PayoutResult
from verifund_control_plane.receipts import (
    ReceiptSigner,
    build_receipt_payload,
)
```

Add `receipts: ReceiptSigner` to the constructor and assign `self.receipts = receipts`.

Append:

```python
    def _validate_purchase_order(
        self,
        record: TransactionRecord,
        agreement: dict[str, Any],
        request: PurchaseOrderReport,
    ) -> None:
        if (
            request.total_cents != record.amount_cents
            or request.currency != record.currency
            or request.offer_id != record.offer_id
        ):
            raise VerifundError(
                "conflict",
                "purchase order total, currency, or offer does not match",
                status_code=409,
            )
        if request.quantity != sum(
            item.quantity for item in request.line_items
        ):
            raise VerifundError(
                "invalid_request",
                "purchase order quantity does not match line items",
                status_code=400,
            )
        expected = sorted(
            (
                item["sku"],
                item["quantity"],
                item["unit_price_cents"],
                item["warranty_addon_cents"],
            )
            for item in agreement["line_items"]
        )
        actual = sorted(
            (
                item.sku,
                item.quantity,
                item.unit_price_cents,
                item.warranty_addon_cents,
            )
            for item in request.line_items
        )
        if expected != actual:
            raise VerifundError(
                "conflict",
                "purchase order line items do not match the agreement",
                status_code=409,
            )

    async def report_purchase_order(
        self,
        transaction_id: str,
        request: PurchaseOrderReport,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        body = request.model_dump(mode="json")
        cached = await self._replay(
            f"purchase-order:{transaction_id}", idempotency_key, body
        )
        if cached is not None:
            return cached
        items = await self.repo.list_evidence(transaction_id)

        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            self._check_hash(record, request.agreement_hash)
            existing = record.purchase_order or {}
            settled_states = {
                TransactionState.FULFILLMENT_PENDING,
                TransactionState.VERIFICATION_PENDING,
                TransactionState.RELEASE_PERMITTED,
                TransactionState.PAYOUT_PENDING,
                TransactionState.RELEASED,
                TransactionState.REVIEW_REQUIRED,
            }
            if (
                existing.get("seller_order_id") == request.seller_order_id
                and record.state in settled_states
            ):
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state != TransactionState.FUNDED:
                raise VerifundError(
                    "invalid_state",
                    "transaction is not ready for a purchase order",
                    status_code=409,
                )
            agreement = await self.repo.get_agreement(transaction_id)
            self._validate_purchase_order(record, agreement, request)
            deadline = self._now() + timedelta(
                hours=self.settings.evidence_deadline_hours
            )
            snapshot = {
                "seller_order_id": request.seller_order_id,
                "offer_id": request.offer_id,
                "quantity": request.quantity,
                "total_cents": request.total_cents,
                "currency": request.currency,
                "tracking_number": request.tracking_number,
                "carrier": request.carrier,
                "reserved_at": self._iso(request.reserved_at),
                "eta": self._iso(request.eta),
                "line_items": [
                    item.model_dump(mode="json")
                    for item in request.line_items
                ],
            }
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=record.version,
                expected_state=TransactionState.FUNDED,
                new_state=TransactionState.FULFILLMENT_PENDING,
                changes={
                    "purchase_order": snapshot,
                    "deadlines": {
                        **(record.deadlines or {}),
                        "evidence": self._iso(deadline),
                    },
                },
                events=[
                    EventInput(
                        "purchase_order_reported",
                        {
                            "seller_order_id": request.seller_order_id,
                            "tracking_number": request.tracking_number,
                        },
                        actor,
                    )
                ],
                audit=AuditInput(actor, "purchase_order_reported"),
            )
            if items:
                updated = await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=updated.version,
                    expected_state=TransactionState.FULFILLMENT_PENDING,
                    new_state=TransactionState.VERIFICATION_PENDING,
                    changes={},
                    audit=AuditInput(actor, "verification_started"),
                )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        result = await self._mutate(
            scope=f"purchase-order:{transaction_id}",
            key=idempotency_key,
            body=body,
            operation=operation,
        )
        if result["state"] == TransactionState.VERIFICATION_PENDING.value:
            await self.verify_if_ready(transaction_id, actor=actor)
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        return result

    async def flag_review(
        self,
        transaction_id: str,
        request: FlagReviewRequest,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        items = await self.repo.list_evidence(transaction_id)

        async def operation(conn):
            record = await self.repo.get_transaction(transaction_id, conn)
            if record.state == TransactionState.REVIEW_REQUIRED:
                return (
                    await self._projection(record, "buyer", items=items)
                ).model_dump(mode="json")
            if record.state in {
                TransactionState.CANCELED,
                TransactionState.FAILED,
                TransactionState.RELEASED,
            }:
                raise VerifundError(
                    "invalid_state",
                    "terminal transactions cannot be flagged",
                    status_code=409,
                )
            reasons = list(
                (record.verification or {}).get("reasons") or []
            )
            if "manual_flag" not in reasons:
                reasons.append("manual_flag")
            updated = await self.repo.transition(
                conn,
                transaction_id,
                expected_version=record.version,
                expected_state=record.state,
                new_state=TransactionState.REVIEW_REQUIRED,
                changes={
                    "verification": {
                        "status": "failed",
                        "reasons": reasons,
                        "checked_at": self._iso(self._now()),
                        "override_allowed": True,
                    }
                },
                events=[
                    EventInput(
                        "review_required",
                        {"reasons": reasons, "note": request.note},
                        actor,
                    )
                ],
                audit=AuditInput(
                    actor,
                    "manual_flag",
                    note=request.note,
                    payload={"reason": request.reason},
                ),
            )
            return (
                await self._projection(updated, "buyer", items=items)
            ).model_dump(mode="json")

        return await self._mutate(
            scope=f"flag-review:{transaction_id}",
            key=idempotency_key,
            body=request.model_dump(mode="json"),
            operation=operation,
        )

    def _seller_token_states(self) -> set[TransactionState]:
        return {
            TransactionState.AWARDED,
            TransactionState.AGREED,
            TransactionState.FUNDING_PENDING,
            TransactionState.FUNDED,
            TransactionState.FULFILLMENT_PENDING,
            TransactionState.VERIFICATION_PENDING,
        }

    async def reissue_seller_token(
        self,
        transaction_id: str,
        request: SellerTokenRequest,
        *,
        actor: str,
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if (
            record.run_id != request.run_id
            or record.seller_id != request.seller_id
            or transaction_id != request.transaction_id
        ):
            raise VerifundError(
                "forbidden",
                "seller token request does not match the transaction",
                status_code=403,
            )
        if record.state not in self._seller_token_states():
            raise VerifundError(
                "forbidden",
                "seller token cannot be reissued after release authorization",
                status_code=403,
            )
        issued = self.tokens.issue(
            transaction_id, record.seller_id, record.agreement_hash
        )
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.version != record.version:
                raise VerifundError(
                    "conflict", "transaction changed; retry", status_code=409
                )
            await self.repo.revoke_seller_tokens(
                conn, transaction_id, self._now()
            )
            await self.repo.save_seller_token(
                conn,
                issued.jti_hash,
                transaction_id,
                record.seller_id,
                record.agreement_hash,
                ["txn:read", "evidence:write"],
                issued.expires_at,
            )
            await self.repo.audit(
                conn,
                transaction_id,
                AuditInput(
                    actor,
                    "seller_token_reissued",
                    payload={"purpose": request.purpose},
                ),
            )
        return SellerTokenResponse(
            seller_token=issued.token, expires_at=issued.expires_at
        ).model_dump(mode="json")

    async def revoke_seller_token(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        async with self.repo.transaction() as conn:
            await self.repo.get_transaction(transaction_id, conn)
            await self.repo.revoke_seller_tokens(
                conn, transaction_id, self._now()
            )
            await self.repo.audit(
                conn,
                transaction_id,
                AuditInput(actor, "seller_token_revoked"),
            )
        return {"revoked": True}
```

- [ ] **Step 4: Add release, payout, and receipt service methods**

Append:

```python
    async def release(
        self,
        transaction_id: str,
        request: ReleaseRequest,
        *,
        actor: str,
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state in {
            TransactionState.PAYOUT_PENDING,
            TransactionState.RELEASED,
        }:
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        if record.state == TransactionState.REVIEW_REQUIRED:
            if not request.override or not request.note.strip():
                raise VerifundError(
                    "forbidden",
                    "override and a note are required in review",
                    status_code=403,
                )
            verification = record.verification or {}
            reasons = verification.get("reasons") or []
            non_overridable = {
                reason.value for reason in NON_OVERRIDABLE_REASONS
            }
            if not verification.get("override_allowed") or any(
                reason in non_overridable for reason in reasons
            ):
                raise VerifundError(
                    "forbidden",
                    "review reasons cannot be overridden",
                    status_code=403,
                )
        elif record.state != TransactionState.RELEASE_PERMITTED:
            raise VerifundError(
                "invalid_state",
                "transaction is not ready for release",
                status_code=409,
            )
        funding = record.funding or {}
        if funding.get("status") != "captured" or not funding.get("capture_id"):
            raise VerifundError(
                "invalid_state", "captured funds are required", status_code=409
            )
        balances = await self.repo.ledger_balances(transaction_id)
        if balances.get("held_funds", 0) != record.amount_cents:
            raise VerifundError(
                "invalid_state",
                "held funds do not match the agreement amount",
                status_code=409,
            )
        operation_id = f"op_{uuid.uuid4().hex}"
        batch_id = f"batch_{transaction_id}"
        sender_item_id = f"item_{transaction_id}"
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state in {
                TransactionState.PAYOUT_PENDING,
                TransactionState.RELEASED,
            }:
                return (
                    await self._projection(current, "buyer")
                ).model_dump(mode="json")
            now = self._now()
            payout = {
                "status": "pending",
                "batch_id": batch_id,
                "item_id": None,
                "amount_cents": current.amount_cents,
                "updated_at": self._iso(now),
                "operation_id": operation_id,
                "sender_item_id": sender_item_id,
            }
            await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=current.state,
                new_state=TransactionState.PAYOUT_PENDING,
                changes={"payout": payout},
                events=[
                    EventInput(
                        "release_authorized",
                        {
                            "released_by": request.released_by,
                            "override": request.override,
                        },
                        actor,
                    ),
                    EventInput("payout_pending", {}, actor),
                ],
                audit=AuditInput(
                    actor,
                    "release_authorized",
                    note=request.note,
                    payload={"override": request.override},
                ),
            )
            await self.repo.create_provider_operation(
                conn,
                operation_id,
                transaction_id,
                "create_payout",
                batch_id,
                {
                    "sender_item_id": sender_item_id,
                    "amount_cents": current.amount_cents,
                    "currency": current.currency,
                },
            )
        await self._execute_payout(
            transaction_id,
            operation_id=operation_id,
            batch_id=batch_id,
            sender_item_id=sender_item_id,
            actor=actor,
        )
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def _execute_payout(
        self,
        transaction_id: str,
        *,
        operation_id: str,
        batch_id: str,
        sender_item_id: str,
        actor: str,
    ) -> None:
        record = await self.repo.get_transaction(transaction_id)
        seller_email = self.settings.payout_email_for(
            record.seller_id
        ) or f"{record.seller_id}@example.test"
        try:
            result = await self.payments.create_payout(
                record,
                seller_email=seller_email,
                batch_id=batch_id,
                item_id=sender_item_id,
            )
        except VerifundError as exc:
            await self.repo.update_provider_operation(
                operation_id,
                status="failed",
                last_error=exc.message,
                increment_attempts=True,
            )
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(
                    transaction_id, conn
                )
                if current.state == TransactionState.PAYOUT_PENDING:
                    await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        changes={
                            "payout": {
                                **(current.payout or {}),
                                "status": "create_failed",
                                "last_error": exc.message,
                                "updated_at": self._iso(self._now()),
                            }
                        },
                        audit=AuditInput(
                            actor,
                            "payout_create_failed",
                            payload={"code": exc.code},
                        ),
                    )
            return
        await self.repo.update_provider_operation(
            operation_id,
            status="completed",
            provider_id=result.item_id,
            response=result.raw,
        )
        await self.apply_payout(transaction_id, result, actor=actor)

    async def apply_payout(
        self, transaction_id: str, result: PayoutResult, *, actor: str
    ) -> None:
        record = await self.repo.get_transaction(transaction_id)
        status = result.status.upper()
        current_payout = record.payout or {}
        payout = {
            **current_payout,
            "status": result.status,
            "batch_id": result.batch_id or current_payout.get("batch_id"),
            "item_id": result.item_id or current_payout.get("item_id"),
            "amount_cents": result.amount_cents,
            "updated_at": self._iso(self._now()),
        }
        seller_email = self.settings.payout_email_for(
            record.seller_id
        ) or f"{record.seller_id}@example.test"
        sender_item_id = str(
            current_payout.get("sender_item_id") or f"item_{transaction_id}"
        )
        if status in {"PENDING", "ONHOLD", "UNCLAIMED"}:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                if current.state == TransactionState.PAYOUT_PENDING:
                    await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        changes={"payout": payout},
                        events=[
                            EventInput(
                                "payout_pending",
                                {"status": result.status},
                                actor,
                            )
                        ],
                        audit=AuditInput(actor, "payout_pending"),
                    )
            return
        if status == "SUCCESS":
            if (
                result.amount_cents != record.amount_cents
                or result.currency != record.currency
            ):
                await self._payout_review(
                    transaction_id,
                    payout,
                    actor=actor,
                    reason="manual_flag",
                    note="payout amount or currency mismatch",
                )
                return
            balances = await self.repo.ledger_balances(transaction_id)
            items = await self.repo.list_evidence(transaction_id)
            signed = self.receipts.sign(
                build_receipt_payload(
                    transaction_id=transaction_id,
                    agreement_hash=record.agreement_hash,
                    amount_cents=record.amount_cents,
                    currency=record.currency,
                    buyer_id=record.buyer_id,
                    seller_id=record.seller_id,
                    capture_id=str(
                        (record.funding or {}).get("capture_id") or ""
                    ),
                    payout_item_id=result.item_id,
                    evidence_hashes=[item.sha256 for item in items],
                    released_at=self._now(),
                )
            )
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.upsert_payout_item(
                    conn,
                    result.item_id,
                    transaction_id,
                    result.batch_id,
                    sender_item_id,
                    seller_email,
                    result.amount_cents,
                    result.currency,
                    result.status,
                    result.raw,
                )
                if current.state == TransactionState.RELEASED:
                    return
                if balances.get("held_funds", 0) != current.amount_cents:
                    await self.repo.transition(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        expected_state=current.state,
                        new_state=TransactionState.REVIEW_REQUIRED,
                        changes={
                            "payout": payout,
                            "verification": {
                                "status": "failed",
                                "reasons": ["ledger_incomplete"],
                                "checked_at": self._iso(self._now()),
                                "override_allowed": False,
                            },
                        },
                        events=[
                            EventInput(
                                "review_required",
                                {"reason": "ledger_incomplete"},
                                actor,
                            )
                        ],
                        audit=AuditInput(actor, "ledger_incomplete"),
                    )
                    return
                if current.state not in {
                    TransactionState.PAYOUT_PENDING,
                    TransactionState.REVIEW_REQUIRED,
                }:
                    return
                await self.repo.transition(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.RELEASED,
                    changes={
                        "payout": payout,
                        "receipt": {
                            "kid": signed.kid,
                            "payload_hash": signed.payload_hash,
                            "signed_at": self._iso(self._now()),
                        },
                    },
                    events=[
                        EventInput(
                            "released",
                            {
                                "payout_item_id": result.item_id,
                                "amount_cents": result.amount_cents,
                            },
                            actor,
                        )
                    ],
                    ledger_entries=payout_ledger_entries(
                        transaction_id, current.amount_cents
                    ),
                    audit=AuditInput(
                        actor,
                        "released",
                        note=f"payout {result.item_id}",
                    ),
                )
                await self.repo.save_receipt(
                    conn,
                    transaction_id,
                    signed.payload,
                    signed.payload_hash,
                    signed.signature,
                    signed.kid,
                )
            return
        if status in {"FAILED", "BLOCKED", "DENIED", "RETURNED"}:
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(transaction_id, conn)
                await self.repo.upsert_payout_item(
                    conn,
                    result.item_id,
                    transaction_id,
                    result.batch_id,
                    sender_item_id,
                    seller_email,
                    result.amount_cents,
                    result.currency,
                    result.status,
                    result.raw,
                )
                if current.state == TransactionState.RELEASED:
                    await self.repo.transition(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        expected_state=current.state,
                        new_state=TransactionState.REVIEW_REQUIRED,
                        changes={
                            "payout": payout,
                            "verification": {
                                "status": "failed",
                                "reasons": ["manual_flag"],
                                "checked_at": self._iso(self._now()),
                                "override_allowed": False,
                            },
                        },
                        events=[
                            EventInput(
                                "review_required",
                                {"reason": "payout_returned"},
                                actor,
                            )
                        ],
                        audit=AuditInput(actor, "payout_returned"),
                    )
                elif current.state == TransactionState.PAYOUT_PENDING:
                    await self.repo.transition(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        expected_state=current.state,
                        new_state=TransactionState.FAILED,
                        changes={
                            "payout": payout,
                            "last_error": {
                                "code": "provider_rejected",
                                "message": f"payout {result.status.lower()}",
                            },
                        },
                        events=[
                            EventInput(
                                "failed",
                                {"status": result.status},
                                actor,
                            )
                        ],
                        audit=AuditInput(actor, "payout_failed"),
                    )
            return
        if status in {"REFUNDED", "REVERSED"}:
            await self._payout_review(
                transaction_id,
                payout,
                actor=actor,
                reason="manual_flag",
                note=f"payout {status.lower()}",
            )

    async def _payout_review(
        self,
        transaction_id: str,
        payout: dict[str, Any],
        *,
        actor: str,
        reason: str,
        note: str,
    ) -> None:
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state == TransactionState.REVIEW_REQUIRED:
                await self.repo.update_transaction(
                    conn,
                    transaction_id,
                    expected_version=current.version,
                    changes={"payout": payout},
                    audit=AuditInput(actor, "payout_review", note=note),
                )
                return
            await self.repo.transition(
                conn,
                transaction_id,
                expected_version=current.version,
                expected_state=current.state,
                new_state=TransactionState.REVIEW_REQUIRED,
                changes={
                    "payout": payout,
                    "verification": {
                        "status": "failed",
                        "reasons": [reason],
                        "checked_at": self._iso(self._now()),
                        "override_allowed": False,
                    },
                },
                events=[
                    EventInput(
                        "review_required", {"reason": note}, actor
                    )
                ],
                audit=AuditInput(actor, "payout_review", note=note),
            )

    async def retry_payout(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state == TransactionState.RELEASED:
            return (
                await self._projection_for(transaction_id, "buyer")
            ).model_dump(mode="json")
        if record.state not in {
            TransactionState.PAYOUT_PENDING,
            TransactionState.REVIEW_REQUIRED,
        }:
            raise VerifundError(
                "invalid_state",
                "transaction is not awaiting payout",
                status_code=409,
            )
        payout = record.payout or {}
        if not payout.get("operation_id") or not payout.get("batch_id"):
            raise VerifundError(
                "invalid_state",
                "payout has not been authorized by a reviewer",
                status_code=409,
            )
        if record.state == TransactionState.REVIEW_REQUIRED and payout.get(
            "status"
        ) not in {
            "pending",
            "create_failed",
            "PENDING",
            "ONHOLD",
            "UNCLAIMED",
            "FAILED",
            "BLOCKED",
            "DENIED",
            "RETURNED",
        }:
            raise VerifundError(
                "invalid_state",
                "transaction is not awaiting a payout retry",
                status_code=409,
            )
        if payout.get("item_id"):
            result = await self.payments.get_payout_item(
                str(payout["item_id"])
            )
            await self.apply_payout(transaction_id, result, actor=actor)
        else:
            await self._execute_payout(
                transaction_id,
                operation_id=str(payout["operation_id"]),
                batch_id=str(payout["batch_id"]),
                sender_item_id=str(
                    payout.get("sender_item_id")
                    or f"item_{transaction_id}"
                ),
                actor=actor,
            )
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def refresh_payout(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        record = await self.repo.get_transaction(transaction_id)
        if record.state not in {
            TransactionState.PAYOUT_PENDING,
            TransactionState.REVIEW_REQUIRED,
            TransactionState.RELEASED,
        }:
            raise VerifundError(
                "invalid_state",
                "transaction has no payout to refresh",
                status_code=409,
            )
        item_id = (record.payout or {}).get("item_id")
        if item_id:
            try:
                result = await self.payments.get_payout_item(str(item_id))
            except VerifundError as exc:
                if exc.code != "not_found":
                    raise
            else:
                await self.apply_payout(
                    transaction_id, result, actor=actor
                )
        return (
            await self._projection_for(transaction_id, "buyer")
        ).model_dump(mode="json")

    async def get_receipt(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]:
        await self.repo.get_transaction(transaction_id)
        data = await self.repo.get_receipt(transaction_id)
        verified = self.receipts.verify(
            data["payload"],
            data["payload_hash"],
            data["signature"],
            data["kid"],
        )
        return ReceiptResponse(
            payload=data["payload"],
            payload_hash=data["payload_hash"],
            signature=data["signature"],
            kid=data["kid"],
            verified=verified,
        ).model_dump(mode="json")
```

- [ ] **Step 5: Add the remaining ops routes**

Append to `api/ops.py`:

```python
from verifund_contracts import (
    FlagReviewRequest,
    PurchaseOrderReport,
    ReleaseRequest,
    SellerTokenRequest,
)


@router.post(
    "/transactions/{transaction_id}/purchase-order",
    dependencies=[Depends(require_ops)],
)
async def report_purchase_order(
    transaction_id: str, body: PurchaseOrderReport, request: Request
) -> dict[str, Any]:
    return await _service(request).report_purchase_order(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/verify",
    dependencies=[Depends(require_ops)],
)
async def verify(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).verify(
        transaction_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/flag-review",
    dependencies=[Depends(require_ops)],
)
async def flag_review(
    transaction_id: str, body: FlagReviewRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).flag_review(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/release",
    dependencies=[Depends(require_ops)],
)
async def release(
    transaction_id: str, body: ReleaseRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).release(
        transaction_id, body, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/payout",
    dependencies=[Depends(require_ops)],
)
async def retry_payout(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).retry_payout(
        transaction_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/payout/refresh",
    dependencies=[Depends(require_ops)],
)
async def refresh_payout(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    return await _service(request).refresh_payout(
        transaction_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/funding/refresh",
    dependencies=[Depends(require_ops)],
)
async def refresh_funding(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    return await _service(request).refresh_funding(
        transaction_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/seller-token",
    dependencies=[Depends(require_ops)],
)
async def reissue_seller_token(
    transaction_id: str, body: SellerTokenRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).reissue_seller_token(
        transaction_id, body, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/seller-token/revoke",
    dependencies=[Depends(require_ops)],
)
async def revoke_seller_token(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    return await _service(request).revoke_seller_token(
        transaction_id, actor=actor(request)
    )


@router.get(
    "/transactions/{transaction_id}/receipt",
    dependencies=[Depends(require_ops)],
)
async def get_receipt(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    return await _service(request).get_receipt(
        transaction_id, actor=actor(request)
    )
```

- [ ] **Step 6: Wire the receipt signer into the app**

In `app.py`, import:

```python
from verifund_control_plane.receipts import ReceiptSigner
```

Create after the repository:

```python
    receipts = ReceiptSigner(
        settings.receipt_keys, settings.receipt_active_kid
    )
```

Pass `receipts=receipts` to `VerifundService` and assign:

```python
    app.state.receipts = receipts
```

- [ ] **Step 7: Run the lifecycle and earlier tests**

Run: `uv run pytest tests/integration/test_verifund_lifecycle.py tests/integration/test_verifund_funding.py tests/integration/test_verifund_webhooks.py tests/unit/test_verifund_policy.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/{service.py,app.py} apps/verifund_control_plane/verifund_control_plane/api/ops.py tests/integration/test_verifund_lifecycle.py
git commit -m "feat(verifund): add purchase orders, release, payout, receipts, and token ops"
```

---

### Task 14: In-process reconciler, deadlines, recovery, and receipt backfill

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Test: `tests/unit/test_verifund_reconciler.py`
- Test: `tests/integration/test_verifund_reconciler.py`

**Interfaces:**
- Produces: `Reconciler.run_once()`, `Reconciler.start()`, `Reconciler.stop()`; `service.recover_operation`, `service.backfill_receipt`; `POST /reconciler/run`;`repository.find_started_operation`.
- Consumes: `Repository.list_transactions`, `list_started_operations`, `list_webhook_events`, `save_reconciler_run`, `PaymentPort`, `paypal.webhooks.dispatch`.

- [ ] **Step 1: Write failing reconciler unit tests**

`tests/unit/test_verifund_reconciler.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from verifund_control_plane.reconciler import Reconciler

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def record(
    transaction_id: str,
    state: str,
    *,
    funding: dict | None = None,
    payout: dict | None = None,
    updated_at: datetime | None = None,
    receipt: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        transaction_id=transaction_id,
        state=state,
        funding=funding,
        payout=payout,
        updated_at=updated_at or NOW,
        receipt=receipt,
        amount_cents=123400,
        deadlines={},
    )


class Repo:
    def __init__(self) -> None:
        self.transactions = {
            "FUNDING_PENDING": [
                record(
                    "vf_funding",
                    "FUNDING_PENDING",
                    funding={"provider_order_id": "ORDER-1"},
                ),
                record("vf_funding_new", "FUNDING_PENDING", funding={"status": "creating"}),
            ],
            "PAYOUT_PENDING": [
                record("vf_payout", "PAYOUT_PENDING", payout={"item_id": "ITEM-1"})
            ],
            "RELEASE_PERMITTED": [
                record("vf_stale", "RELEASE_PERMITTED", updated_at=NOW - timedelta(hours=3))
            ],
            "VERIFICATION_PENDING": [record("vf_verify", "VERIFICATION_PENDING")],
            "RELEASED": [
                record(
                    "vf_released",
                    "RELEASED",
                    payout={"item_id": "ITEM-1"},
                    receipt=None,
                )
            ],
        }
        self.webhooks = [
            {"event_id": "WH-1", "status": "failed", "payload": {"id": "WH-1"}},
            {"event_id": "WH-2", "status": "unmatched", "payload": {"id": "WH-2"}},
        ]
        self.operations = [
            {
                "operation_id": "op_1",
                "transaction_id": "vf_funding_new",
                "kind": "create_order",
                "status": "started",
                "created_at": (NOW - timedelta(minutes=5)).isoformat(),
            }
        ]
        self.runs: list[dict] = []

    async def list_transactions(self, *, state=None, limit=100):
        return list(self.transactions.get(state, []))

    async def list_webhook_events(self, *, status=None, limit=100):
        return [item for item in self.webhooks if item["status"] == status]

    async def list_started_operations(self, limit=100):
        return list(self.operations)

    async def find_started_operation(self, transaction_id, kind):
        for operation in self.operations:
            if (
                operation["transaction_id"] == transaction_id
                and operation["kind"] == kind
            ):
                return operation
        return None

    async def ledger_balances(self, transaction_id):
        return {"held_funds": 0, "platform_cash": 123400, "seller_paid": 123400}

    async def save_reconciler_run(
        self, run_id, started_at, finished_at, stats, error=None
    ):
        self.runs.append(
            {
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "stats": stats,
                "error": error,
            }
        )

    async def mark_webhook_event(self, event_id, status, *, last_error=None):
        for item in self.webhooks:
            if item["event_id"] == event_id:
                item["status"] = status

    async def update_provider_operation(self, operation_id, **kwargs):
        for operation in self.operations:
            if operation["operation_id"] == operation_id:
                operation.update(kwargs)


class Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.verify_state = "RELEASE_PERMITTED"

    async def refresh_funding(self, transaction_id, *, actor):
        self.calls.append(("refresh_funding", transaction_id))

    async def refresh_payout(self, transaction_id, *, actor):
        self.calls.append(("refresh_payout", transaction_id))

    async def recover_operation(self, operation, *, actor):
        self.calls.append(("recover_operation", operation["operation_id"]))
        return True

    async def verify(self, transaction_id, *, actor):
        self.calls.append(("verify", transaction_id))
        return {"state": self.verify_state}

    async def backfill_receipt(self, transaction_id, *, actor):
        self.calls.append(("backfill_receipt", transaction_id))
        return True


class Settings:
    reconciler_pending_seconds = 30
    payout_alert_hours = 1


async def test_run_once_sweeps_every_domain_and_records_a_run():
    repo = Repo()
    service = Service()
    dispatches: list[dict] = []

    async def dispatch(_service, event):
        dispatches.append(event)
        return "processed"

    reconciler = Reconciler(
        repo=repo,
        service=service,
        settings=Settings(),
        clock=lambda: NOW,
        webhook_dispatch=dispatch,
    )
    stats = await reconciler.run_once()

    assert ("refresh_funding", "vf_funding") in service.calls
    assert ("refresh_payout", "vf_payout") in service.calls
    assert ("verify", "vf_verify") in service.calls
    assert ("backfill_receipt", "vf_released") in service.calls
    assert ("recover_operation", "op_1") in service.calls
    assert [item["id"] for item in dispatches] == ["WH-1", "WH-2"]
    assert stats["stale_release_permitted"] == 1
    assert stats["receipts_backfilled"] == 1
    assert stats["webhooks_retried"] == 2
    assert stats["provider_intents_recovered"] == 1
    assert len(repo.runs) == 1
    assert repo.runs[0]["error"] is None


async def test_one_failing_sweep_does_not_stop_the_others():
    repo = Repo()
    service = Service()

    async def broken_funding(transaction_id, *, actor):
        raise RuntimeError("paypal down")

    service.refresh_funding = broken_funding  # type: ignore[method-assign]

    async def dispatch(_service, event):
        return "processed"

    reconciler = Reconciler(
        repo=repo,
        service=service,
        settings=Settings(),
        clock=lambda: NOW,
        webhook_dispatch=dispatch,
    )
    stats = await reconciler.run_once()

    assert stats["errors"] == 1
    assert stats["webhooks_retried"] == 2
    assert ("refresh_payout", "vf_payout") in service.calls
```

- [ ] **Step 2: Write the failing integration test**

`tests/integration/test_verifund_reconciler.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_reconciler_run_route_requires_ops_and_records_a_run(api):
    refused = await api.post("/reconciler/run")
    assert refused.status_code == 401

    response = await api.post("/reconciler/run", headers=OPS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["errors"] == 0
    assert "funding_checked" in body

    repo = api._transport.app.state.repo  # type: ignore[attr-defined]
    runs = await repo.list_reconciler_runs(limit=5)
    assert len(runs) == 1
    assert runs[0]["stats"]["errors"] == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py tests/integration/test_verifund_reconciler.py -v`
Expected: FAIL with `ModuleNotFoundError: verifund_control_plane.reconciler` and 404 for `/reconciler/run`.

- [ ] **Step 4: Add the reconciler settings and repository lookup**

Add to `Settings` after `reconciler_receipt_seconds`:

```python
    reconciler_interval_seconds: int = Field(
        default=30, validation_alias="VERIFUND_RECONCILER_INTERVAL_SECONDS"
    )
```

Append to `Repository`:

```python
    async def find_started_operation(
        self, transaction_id: str, kind: str
    ) -> dict[str, Any] | None:
        statement = select(self.provider_operations).where(
            self.provider_operations.c.transaction_id == transaction_id,
            self.provider_operations.c.kind == kind,
            self.provider_operations.c.status == "started",
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(statement)).first()
        return dict(row._mapping) if row is not None else None
```

- [ ] **Step 5: Implement provider recovery and receipt backfill in the service**

Append `recover_operation` to `VerifundService`:

```python
    async def recover_operation(
        self, operation: dict[str, Any], *, actor: str
    ) -> bool:
        kind = str(operation.get("kind") or "")
        transaction_id = str(operation.get("transaction_id") or "")
        operation_id = str(operation.get("operation_id") or "")
        if not transaction_id or not operation_id:
            return False
        record = await self.repo.get_transaction(transaction_id)
        if kind == "create_order":
            funding = record.funding or {}
            if (
                record.state != TransactionState.FUNDING_PENDING
                or funding.get("provider_order_id")
            ):
                return False
            request = operation.get("request") or {}
            order = await self.payments.create_order(
                record,
                return_url=str(request.get("return_url") or ""),
                cancel_url=str(request.get("cancel_url") or ""),
                idempotency_key=str(operation.get("idempotency_key") or ""),
            )
            payer_url = str(
                order.payer_action_url or request.get("return_url") or ""
            )
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(
                    transaction_id, conn
                )
                if current.state == TransactionState.FUNDING_PENDING:
                    await self.repo.update_transaction(
                        conn,
                        transaction_id,
                        expected_version=current.version,
                        changes={
                            "funding": {
                                **(current.funding or {}),
                                "status": "pending",
                                "provider_order_id": order.order_id,
                                "payer_action_url": payer_url,
                                "checkout_url": payer_url,
                            }
                        },
                        audit=AuditInput(actor, "funding_order_recovered"),
                    )
            await self.repo.update_provider_operation(
                operation_id,
                status="completed",
                provider_id=order.order_id,
                response=order.raw,
            )
            return True
        if kind == "create_payout":
            payout = record.payout or {}
            if record.state not in {
                TransactionState.PAYOUT_PENDING,
                TransactionState.REVIEW_REQUIRED,
            } or payout.get("item_id"):
                return False
            request = operation.get("request") or {}
            await self._execute_payout(
                transaction_id,
                operation_id=operation_id,
                batch_id=str(
                    payout.get("batch_id")
                    or operation.get("idempotency_key")
                    or f"batch_{transaction_id}"
                ),
                sender_item_id=str(
                    request.get("sender_item_id") or f"item_{transaction_id}"
                ),
                actor=actor,
            )
            return True
        return False
```

Append `backfill_receipt`:

```python
    async def backfill_receipt(
        self, transaction_id: str, *, actor: str
    ) -> bool:
        record = await self.repo.get_transaction(transaction_id)
        if record.state != TransactionState.RELEASED or record.receipt:
            return False
        item_id = str((record.payout or {}).get("item_id") or "")
        if not item_id:
            return False
        try:
            payout_item = await self.repo.get_payout_item(item_id)
        except VerifundError:
            return False
        items = await self.repo.list_evidence(transaction_id)
        signed = self.receipts.sign(
            build_receipt_payload(
                transaction_id=transaction_id,
                agreement_hash=record.agreement_hash,
                amount_cents=record.amount_cents,
                currency=record.currency,
                buyer_id=record.buyer_id,
                seller_id=record.seller_id,
                capture_id=str(
                    (record.funding or {}).get("capture_id") or ""
                ),
                payout_item_id=item_id,
                evidence_hashes=[item.sha256 for item in items],
                released_at=self._now(),
            )
        )
        async with self.repo.transaction() as conn:
            current = await self.repo.get_transaction(transaction_id, conn)
            if current.state != TransactionState.RELEASED or current.receipt:
                return False
            await self.repo.save_receipt(
                conn,
                transaction_id,
                signed.payload,
                signed.payload_hash,
                signed.signature,
                signed.kid,
            )
            await self.repo.update_transaction(
                conn,
                transaction_id,
                expected_version=current.version,
                changes={
                    "receipt": {
                        "kid": signed.kid,
                        "payload_hash": signed.payload_hash,
                        "signed_at": self._iso(self._now()),
                    }
                },
                audit=AuditInput(actor, "receipt_backfilled"),
            )
        return True
```

`payout_item` is read only for existence; if the row exists, the receipt is valid. Do not include unused local. Use `await self.repo.get_payout_item(item_id)` without assignment.

- [ ] **Step 6: Implement the reconciler**

`apps/verifund_control_plane/verifund_control_plane/reconciler.py`:

```python
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from verifund_control_plane.paypal.webhooks import dispatch as default_dispatch
from verifund_control_plane.service import VerifundService
from verifund_control_plane.settings import Settings


class Reconciler:
    def __init__(
        self,
        *,
        repo: Any,
        service: VerifundService,
        settings: Settings,
        clock: Callable[[], datetime],
        webhook_dispatch: Callable[[Any, dict[str, Any]], Awaitable[str]] | None = None,
    ) -> None:
        self.repo = repo
        self.service = service
        self.settings = settings
        self.clock = clock
        self.webhook_dispatch = webhook_dispatch or default_dispatch
        self._task: asyncio.Task | None = None

    def _now(self) -> datetime:
        return self.clock().astimezone(UTC)

    async def _safe(self, stats: dict[str, int], operation: Awaitable[None]) -> None:
        try:
            await operation
        except Exception:  # noqa: BLE001
            stats["errors"] += 1

    def _new_stats(self) -> dict[str, int]:
        return {
            "errors": 0,
            "funding_checked": 0,
            "payouts_checked": 0,
            "deadlines_checked": 0,
            "deadline_reviews": 0,
            "stale_release_permitted": 0,
            "webhooks_retried": 0,
            "receipts_backfilled": 0,
            "ledger_mismatches": 0,
            "provider_intents_started": 0,
            "provider_intents_recovered": 0,
        }

    async def run_once(self) -> dict[str, int]:
        run_id = f"rec_{uuid.uuid4().hex}"
        started_at = self._now()
        stats = self._new_stats()
        error: str | None = None
        try:
            await self._safe(stats, self._sweep_funding(stats))
            await self._safe(stats, self._sweep_payouts(stats))
            await self._safe(stats, self._sweep_deadlines(stats))
            await self._safe(stats, self._sweep_release_permitted(stats))
            await self._safe(stats, self._sweep_webhooks(stats))
            await self._safe(stats, self._sweep_receipts(stats))
            await self._safe(stats, self._sweep_ledger(stats))
            await self._safe(stats, self._sweep_provider_intents(stats))
        except Exception as exc:  # noqa: BLE001
            error = type(exc).__name__
            raise
        finally:
            await self.repo.save_reconciler_run(
                run_id, started_at, self._now(), stats, error
            )
        return stats

    async def _sweep_funding(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(state="FUNDING_PENDING"):
            funding = record.funding or {}
            if funding.get("provider_order_id"):
                await self.service.refresh_funding(
                    record.transaction_id, actor="reconciler"
                )
                stats["funding_checked"] += 1
                continue
            operation = await self.repo.find_started_operation(
                record.transaction_id, "create_order"
            )
            if operation is not None and await self.service.recover_operation(
                operation, actor="reconciler"
            ):
                stats["provider_intents_recovered"] += 1

    async def _sweep_payouts(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(state="PAYOUT_PENDING"):
            await self.service.refresh_payout(
                record.transaction_id, actor="reconciler"
            )
            stats["payouts_checked"] += 1

    async def _sweep_deadlines(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(
            state="VERIFICATION_PENDING"
        ):
            projection = await self.service.verify(
                record.transaction_id, actor="reconciler"
            )
            stats["deadlines_checked"] += 1
            if projection.get("state") == "REVIEW_REQUIRED":
                stats["deadline_reviews"] += 1

    async def _sweep_release_permitted(self, stats: dict[str, int]) -> None:
        cutoff = self._now() - timedelta(
            hours=self.settings.payout_alert_hours
        )
        for record in await self.repo.list_transactions(
            state="RELEASE_PERMITTED"
        ):
            if record.updated_at.astimezone(UTC) < cutoff:
                stats["stale_release_permitted"] += 1

    async def _sweep_webhooks(self, stats: dict[str, int]) -> None:
        seen: set[str] = set()
        for status in ("failed", "unmatched", "pending"):
            for event in await self.repo.list_webhook_events(status=status):
                if event["event_id"] in seen:
                    continue
                seen.add(event["event_id"])
                try:
                    outcome = await self.webhook_dispatch(
                        self.service, event["payload"]
                    )
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
                    continue
                await self.repo.mark_webhook_event(
                    event["event_id"], outcome
                )
                stats["webhooks_retried"] += 1

    async def _sweep_receipts(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(state="RELEASED"):
            if await self.service.backfill_receipt(
                record.transaction_id, actor="reconciler"
            ):
                stats["receipts_backfilled"] += 1

    async def _sweep_ledger(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(state="RELEASED"):
            balances = await self.repo.ledger_balances(record.transaction_id)
            if (
                balances.get("held_funds", 0) != 0
                or balances.get("seller_paid", 0) != record.amount_cents
            ):
                stats["ledger_mismatches"] += 1

    async def _sweep_provider_intents(self, stats: dict[str, int]) -> None:
        cutoff = self._now() - timedelta(
            seconds=self.settings.reconciler_pending_seconds
        )
        for operation in await self.repo.list_started_operations():
            started_at = operation.get("created_at")
            if started_at is not None:
                try:
                    parsed = datetime.fromisoformat(
                        str(started_at).replace("Z", "+00:00")
                    )
                except ValueError:
                    parsed = None
                if parsed is not None and parsed.astimezone(UTC) >= cutoff:
                    continue
            stats["provider_intents_started"] += 1
            if await self.service.recover_operation(
                operation, actor="reconciler"
            ):
                stats["provider_intents_recovered"] += 1
                continue
            await self.repo.update_provider_operation(
                str(operation["operation_id"]),
                status="failed",
                last_error="abandoned after crash",
                increment_attempts=True,
            )

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.settings.reconciler_interval_seconds)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
```

- [ ] **Step 7: Add the ops route and app lifespan wiring**

Append to `api/ops.py`:

```python
@router.post("/reconciler/run", dependencies=[Depends(require_ops)])
async def run_reconciler(request: Request) -> dict[str, Any]:
    return await request.app.state.reconciler.run_once()
```

In `app.py`, import `Reconciler` and create it after the service:

```python
    reconciler = Reconciler(
        repo=repo,
        service=service,
        settings=settings,
        clock=now,
    )
```

Assign `app.state.reconciler = reconciler`. Update the lifespan:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await configure_sqlite(engine)
        if hasattr(app.state, "repo"):
            await app.state.repo.create_schema()
        if (
            hasattr(app.state, "reconciler")
            and settings.mode != "off"
            and settings.reconciler_enabled
        ):
            app.state.reconciler.start()
        try:
            yield
        finally:
            if hasattr(app.state, "reconciler"):
                await app.state.reconciler.stop()
            await engine.dispose()
```

- [ ] **Step 8: Run the reconciler and lifecycle tests**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py tests/integration/test_verifund_reconciler.py tests/integration/test_verifund_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/{reconciler.py,settings.py,repository.py,service.py,app.py} apps/verifund_control_plane/verifund_control_plane/api/ops.py tests/unit/test_verifund_reconciler.py tests/integration/test_verifund_reconciler.py
git commit -m "feat(verifund): add in-process reconciler and receipt backfill"
```

---

## Phase 2 — Buyer integration and Transaction Room

### Task 15: Buyer settlement settings, secret store, and typed client

**Files:**
- Modify: `apps/buyer_agent/pyproject.toml`
- Modify: `apps/buyer_agent/buyer_agent/settings.py`
- Create: `apps/buyer_agent/buyer_agent/settlement_store.py`
- Create: `apps/buyer_agent/buyer_agent/settlement_client.py`
- Create: `apps/buyer_agent/buyer_agent/settlement.py`
- Modify: `apps/buyer_agent/buyer_agent/store.py`
- Modify: `apps/buyer_agent/buyer_agent/services.py`
- Test: `tests/unit/test_buyer_settlement_store.py`
- Test: `tests/unit/test_buyer_settlement_client.py`

**Interfaces:**
- Produces: `SettlementSettings` fields on buyer `Settings`; `SettlementStore` (`save_secret`, `get_secret`, `delete_secret`, `get_secret_by_transaction`, `save_projection(...) -> bool`, `get_projection`); `BuyerSettlementClient` (`award`, `buyer_review`, `accept`, `reject`, `approve`, `fund`, `refresh_funding`, `purchase_order`, `verify`, `release`, `flag_review`, `cancel`, `retry_payout`, `get_state`, `get_receipt`, `list_evidence`, `get_evidence`, `reissue_seller_token`, `revoke_seller_token`); `SettlementCoordinator` with `lock(run_id)`.
- Consumes: `verifund_contracts.VerifundClient` and models from Tasks 1 and 1A.

- [ ] **Step 1: Write failing buyer settlement store tests**

`tests/unit/test_buyer_settlement_store.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from buyer_agent.settlement_store import SettlementStore


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'buyer.db'}"
    )
    value = SettlementStore(engine)
    await value.create_schema()
    yield value
    await engine.dispose()


async def test_secret_round_trip_and_delete(store):
    await store.save_secret(
        run_id="run-1",
        transaction_id="vf_1",
        seller_id="northwind-audio",
        purpose="seller_accept",
        token="v1.secret",
        expires_at=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
    )
    secret = await store.get_secret("run-1", "vf_1", "seller_accept")
    assert secret is not None
    assert secret["seller_token"] == "v1.secret"
    assert secret["seller_id"] == "northwind-audio"

    await store.delete_secret("vf_1")
    assert await store.get_secret("run-1", "vf_1", "seller_accept") is None


async def test_projection_round_trip(store):
    assert (
        await store.save_projection(
            "run-1",
            {"transaction_id": "vf_1", "state": "AWARDED", "last_seq": 3},
        )
        is True
    )
    assert (await store.get_projection("run-1"))["state"] == "AWARDED"
    assert (
        await store.save_projection(
            "run-1",
            {"transaction_id": "vf_1", "state": "AGREED", "last_seq": 4},
        )
        is True
    )
    assert (await store.get_projection("run-1"))["state"] == "AGREED"
    assert (
        await store.save_projection(
            "run-1",
            {"transaction_id": "vf_1", "state": "AGREED", "last_seq": 4},
        )
        is False
    )
```

- [ ] **Step 2: Write failing buyer settlement client tests**

`tests/unit/test_buyer_settlement_client.py`:

```python
from __future__ import annotations

import respx
from httpx import Response

from buyer_agent.settlement_client import BuyerSettlementClient


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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_buyer_settlement_store.py tests/unit/test_buyer_settlement_client.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Add buyer settlement settings**

Add `verifund-contracts` to the buyer package dependencies and workspace sources:

```toml
dependencies = [
  "marketmesh-commerce-core",
  "verifund-contracts",
  ...
]

[tool.uv.sources]
marketmesh-commerce-core = { workspace = true }
verifund-contracts = { workspace = true }
```

Append to `apps/buyer_agent/buyer_agent/settings.py`:

```python
    verifund_mode: Literal["off", "fake", "sandbox"] = Field(
        default="off",
        validation_alias=AliasChoices("VERIFUND_MODE"),
    )
    verifund_url: str = Field(
        default="http://127.0.0.1:9300",
        validation_alias=AliasChoices("VERIFUND_URL", "BUYER_VERIFUND_URL"),
    )
    verifund_ops_token: str = Field(
        default="dev-verifund-ops",
        validation_alias=AliasChoices("VERIFUND_OPS_TOKEN", "BUYER_VERIFUND_OPS_TOKEN"),
    )
    verifund_timeout_seconds: float = Field(
        default=20.0,
        validation_alias=AliasChoices("VERIFUND_TIMEOUT_SECONDS"),
    )
    internal_api_token: str = Field(
        default="dev-buyer-internal",
        validation_alias=AliasChoices("BUYER_INTERNAL_TOKEN"),
    )
    console_base_url: str = Field(
        default="http://127.0.0.1:3000",
        validation_alias=AliasChoices("VERIFUND_CONSOLE_BASE_URL", "BUYER_CONSOLE_BASE_URL"),
    )
```

- [ ] **Step 5: Implement the SQLite secret/projection store**

`apps/buyer_agent/buyer_agent/settlement_store.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from commerce_core.db import configure_sqlite
from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from buyer_agent.settlement_store_base import isoformat


class SettlementStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.metadata = MetaData()
        self.secrets = Table(
            "run_secrets",
            self.metadata,
            Column("transaction_id", String, primary_key=True),
            Column("run_id", String, nullable=False, index=True),
            Column("seller_id", String, nullable=False),
            Column("purpose", String, nullable=False),
            Column("seller_token", String, nullable=False),
            Column("expires_at", String, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.projections = Table(
            "settlement_projections",
            self.metadata,
            Column("run_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("last_seq", Integer, nullable=False),
            Column("updated_at", String, nullable=False),
        )

    async def create_schema(self) -> None:
        await configure_sqlite(self.engine)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    async def save_secret(
        self,
        *,
        run_id: str,
        transaction_id: str,
        seller_id: str,
        purpose: str,
        token: str,
        expires_at: datetime,
    ) -> None:
        statement = sqlite_insert(self.secrets).values(
            transaction_id=transaction_id,
            run_id=run_id,
            seller_id=seller_id,
            purpose=purpose,
            seller_token=token,
            expires_at=isoformat(expires_at),
            created_at=isoformat(datetime.now(UTC)),
        ).on_conflict_do_update(
            index_elements=["transaction_id"],
            set_={
                "run_id": run_id,
                "seller_id": seller_id,
                "purpose": purpose,
                "seller_token": token,
                "expires_at": isoformat(expires_at),
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def get_secret(
        self, run_id: str, transaction_id: str, purpose: str
    ) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.secrets).where(
                    self.secrets.c.run_id == run_id,
                    self.secrets.c.transaction_id == transaction_id,
                    self.secrets.c.purpose == purpose,
                )
            )).first()
        return dict(row._mapping) if row is not None else None

    async def get_secret_by_transaction(
        self, transaction_id: str
    ) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.secrets).where(
                    self.secrets.c.transaction_id == transaction_id
                )
            )).first()
        return dict(row._mapping) if row is not None else None

    async def delete_secret(self, transaction_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.secrets.delete().where(
                    self.secrets.c.transaction_id == transaction_id
                )
            )

    async def save_projection(
        self, run_id: str, projection: dict[str, Any]
    ) -> bool:
        last_seq = int(projection.get("last_seq") or 0)
        statement = sqlite_insert(self.projections).values(
            run_id=run_id,
            transaction_id=str(projection["transaction_id"]),
            payload=projection,
            last_seq=last_seq,
            updated_at=isoformat(datetime.now(UTC)),
        ).on_conflict_do_update(
            index_elements=["run_id"],
            set_={
                "transaction_id": str(projection["transaction_id"]),
                "payload": projection,
                "last_seq": last_seq,
                "updated_at": isoformat(datetime.now(UTC)),
            },
            where=self.projections.c.last_seq < last_seq,
        )
        async with self.engine.begin() as conn:
            result = await conn.execute(statement)
        return result.rowcount == 1

    async def get_projection(self, run_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.projections).where(
                    self.projections.c.run_id == run_id
                )
            )).first()
        return dict(row.payload) if row is not None else None
```

Create `apps/buyer_agent/buyer_agent/settlement_store_base.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime


def isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
```

Also import `Integer` in `settlement_store.py` (`Column(Integer, ...)` needs `Integer`). Change the import line to include `Integer`.

- [ ] **Step 6: Implement the typed buyer client**

`apps/buyer_agent/buyer_agent/settlement_client.py`:

```python
from __future__ import annotations

from typing import Any

from verifund_contracts import (
    AcceptRequest,
    ApproveRequest,
    AwardRequest,
    BuyerAgreementReviewRequest,
    CancelRequest,
    FlagReviewRequest,
    FundRequest,
    PurchaseOrderReport,
    RejectReason,
    ReleaseRequest,
    RejectRequest,
    SellerTokenRequest,
    VerifundClient,
)


class BuyerSettlementClient:
    def __init__(
        self,
        base_url: str,
        *,
        ops_token: str,
        actor: str = "buyer-agent",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.actor = actor
        self._client = VerifundClient(
            base_url,
            ops_token=ops_token,
            actor=actor,
            timeout=timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.close()

    def _actor(self, actor: str | None) -> str:
        return actor or self.actor

    async def award(self, request: AwardRequest, *, idempotency_key: str) -> dict:
        response = await self._client.award(
            request, actor=self.actor, idempotency_key=idempotency_key
        )
        return response.model_dump(mode="json")

    async def buyer_review(
        self,
        transaction_id: str,
        *,
        buyer_id: str,
        agreement_version: int,
        agreement_hash: str,
        decision: str,
        buyer_task_id: str,
        reviewed_at: str,
        reason_code: str | None = None,
        note: str = "",
        idempotency_key: str,
    ) -> dict:
        projection = await self._client.buyer_review(
            transaction_id,
            BuyerAgreementReviewRequest(
                buyer_id=buyer_id,
                agreement_version=agreement_version,
                agreement_hash=agreement_hash,
                decision=decision,
                reason_code=reason_code,
                note=note,
                buyer_task_id=buyer_task_id,
                reviewed_at=reviewed_at,
            ),
            actor=self.actor,
            idempotency_key=idempotency_key,
        )
        return projection.model_dump(mode="json")

    async def accept(
        self,
        transaction_id: str,
        *,
        seller_id: str,
        agreement_hash: str,
        accepted_total_cents: int,
        seller_task_id: str,
        accepted_at: str,
    ) -> dict:
        return await self._client.accept(
            transaction_id,
            AcceptRequest(
                seller_id=seller_id,
                agreement_hash=agreement_hash,
                accepted_total_cents=accepted_total_cents,
                seller_task_id=seller_task_id,
                accepted_at=accepted_at,
            ),
            actor=self.actor,
        )

    async def reject(
        self,
        transaction_id: str,
        *,
        seller_id: str,
        agreement_hash: str,
        reason_code: str,
        note: str,
        seller_task_id: str,
        rejected_at: str,
    ) -> dict:
        return await self._client.reject(
            transaction_id,
            RejectRequest(
                seller_id=seller_id,
                agreement_hash=agreement_hash,
                reason_code=RejectReason(reason_code),
                note=note,
                seller_task_id=seller_task_id,
                rejected_at=rejected_at,
            ),
            actor=self.actor,
        )

    async def approve(
        self,
        transaction_id: str,
        *,
        approval_id: str,
        approved_by: str,
        approved_at: str,
        note: str,
        agreement_hash: str,
    ) -> dict:
        return await self._client.approve(
            transaction_id,
            ApproveRequest(
                approval_id=approval_id,
                approved_by=approved_by,
                approved_at=approved_at,
                note=note,
                agreement_hash=agreement_hash,
            ),
            actor=self.actor,
        )

    async def fund(
        self, transaction_id: str, request: FundRequest, *, idempotency_key: str
    ) -> dict:
        response = await self._client.fund(
            transaction_id,
            request,
            actor=self.actor,
            idempotency_key=idempotency_key,
        )
        return response.model_dump(mode="json")

    async def refresh_funding(self, transaction_id: str) -> dict:
        return await self._client.refresh_funding(
            transaction_id, actor=self.actor
        )

    async def purchase_order(
        self,
        transaction_id: str,
        report: PurchaseOrderReport,
        *,
        idempotency_key: str,
    ) -> dict:
        return await self._client.purchase_order(
            transaction_id,
            report,
            actor=self.actor,
            idempotency_key=idempotency_key,
        )

    async def verify(self, transaction_id: str, *, note: str = "") -> dict:
        return await self._client.verify(transaction_id, actor=self.actor)

    async def release(
        self,
        transaction_id: str,
        request: ReleaseRequest,
        *,
        actor: str | None = None,
    ) -> dict:
        return await self._client.release(
            transaction_id, request, actor=self._actor(actor)
        )

    async def flag_review(
        self,
        transaction_id: str,
        request: FlagReviewRequest,
        *,
        actor: str | None = None,
    ) -> dict:
        return await self._client.flag_review(
            transaction_id, request, actor=self._actor(actor)
        )

    async def cancel(
        self,
        transaction_id: str,
        request: CancelRequest,
        *,
        actor: str | None = None,
    ) -> dict:
        return await self._client.cancel(
            transaction_id, request, actor=self._actor(actor)
        )

    async def retry_payout(
        self, transaction_id: str, *, actor: str | None = None
    ) -> dict:
        return await self._client.payout(
            transaction_id, actor=self._actor(actor)
        )

    async def get_state(
        self, transaction_id: str, *, actor: str | None = None
    ) -> dict:
        projection = await self._client.get_state(
            transaction_id, actor=self._actor(actor)
        )
        return projection.model_dump(mode="json")

    async def get_receipt(
        self, transaction_id: str, *, actor: str | None = None
    ) -> dict:
        response = await self._client.receipt(
            transaction_id, actor=self._actor(actor)
        )
        return response.model_dump(mode="json")

    async def list_evidence(
        self, transaction_id: str, *, actor: str | None = None
    ) -> list[dict]:
        items = await self._client.list_evidence(
            transaction_id, actor=self._actor(actor)
        )
        return [item.model_dump(mode="json") for item in items]

    async def get_evidence(
        self,
        transaction_id: str,
        evidence_id: str,
        *,
        actor: str | None = None,
    ) -> tuple[bytes, str, str]:
        return await self._client.get_evidence(
            transaction_id, evidence_id, actor=self._actor(actor)
        )

    async def reissue_seller_token(
        self,
        *,
        transaction_id: str,
        run_id: str,
        seller_id: str,
        purpose: str,
    ) -> dict:
        response = await self._client.seller_token(
            transaction_id,
            SellerTokenRequest(
                run_id=run_id,
                transaction_id=transaction_id,
                seller_id=seller_id,
                purpose=purpose,
            ),
            actor=self.actor,
        )
        return response.model_dump(mode="json")

    async def revoke_seller_token(self, transaction_id: str) -> dict:
        return await self._client.revoke_seller_token(
            transaction_id, actor=self.actor
        )
```

`VerifundClient` in Task 1 must expose these exact methods and accept `timeout_seconds`. Update Task 1 if the signature differs: its constructor is `VerifundClient("http://control", ops_token="ops-token")`; add optional `timeout_seconds` keyword with default `20.0`, and `close()`. The `accept`, `reject`, `approve` signatures must accept the flattened keyword form shown here and build the request models.

- [ ] **Step 7: Add the coordinator and services wiring**

Create `apps/buyer_agent/buyer_agent/settlement.py`:

```python
from __future__ import annotations

import asyncio
from collections import defaultdict


class SettlementCoordinator:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock(self, run_id: str) -> asyncio.Lock:
        return self._locks[run_id]

    def is_locked(self, run_id: str) -> bool:
        return self._locks[run_id].locked()
```

Update `BuyerStore`:

```python
from buyer_agent.settlement_store import SettlementStore


class BuyerStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.trace = TraceStore(engine)
        self.settlement = SettlementStore(engine)

    async def create_schema(self) -> None:
        await self.trace.create_schema()
        await self.settlement.create_schema()
```

Update `BuyerServices`:

```python
from buyer_agent.settlement import SettlementCoordinator
from buyer_agent.settlement_client import BuyerSettlementClient


@dataclass
class BuyerServices:
    settings: Settings
    engine: AsyncEngine
    store: BuyerStore
    registry: RegistryClient
    a2a: SellerA2AClient
    settlement: BuyerSettlementClient | None = None
    coordinator: SettlementCoordinator | None = None

    @property
    def trace(self):
        return self.store.trace

    async def close(self) -> None:
        if self.settlement is not None:
            await self.settlement.close()
        await self.registry.close()
        await self.engine.dispose()
```

Update `build_services`:

```python
    coordinator = SettlementCoordinator()
    settlement = None
    if settings.verifund_mode != "off":
        settlement = BuyerSettlementClient(
            settings.verifund_url,
            ops_token=settings.verifund_ops_token,
            timeout_seconds=settings.verifund_timeout_seconds,
        )
    return BuyerServices(
        settings=settings,
        engine=engine,
        store=store,
        registry=registry,
        a2a=SellerA2AClient(store.trace),
        settlement=settlement,
        coordinator=coordinator,
    )
```

- [ ] **Step 8: Run the buyer settlement tests**

Run: `uv run pytest tests/unit/test_buyer_settlement_store.py tests/unit/test_buyer_settlement_client.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/buyer_agent/pyproject.toml apps/buyer_agent/buyer_agent/{settings.py,settlement_store.py,settlement_store_base.py,settlement_client.py,settlement.py,store.py,services.py} tests/unit/test_buyer_settlement_store.py tests/unit/test_buyer_settlement_client.py
git commit -m "feat(buyer): add settlement secret store and control-plane client"
```

---

### Task 16: Buyer settlement flow and graph nodes

**Chat-driven agreement review amendment:** the buyer graph must not directly
create the award or call the seller acceptance skill in settlement mode. After
ranking, it checkpoints the original Buyer A2A task with the exact award and
mandate, and returns `agreement_create_required` to the orchestrator. The
orchestrator calls Verifund `verifund.agreement.create`; Verifund assembles the
proposal from that award and asks the authenticated Buyer internal route to
validate and create the canonical control-plane agreement. The orchestrator
then resumes the original Buyer task with the canonical agreement, version,
and hash. The Buyer validates its mandate, records its own hash-bound review
with `POST /buyer-review`, and pauses for Seller review. The orchestrator sends
the same agreement to the Seller A2A agent, then resumes that original Buyer
task with the exact structured Seller response. The Buyer reports seller
acceptance/rejection through its own control-plane client. Only both agent
acceptances for the current hash proceed to the separate human funding HITL.
Rejection/counterproposal cannot reach funding approval; a counterproposal
creates a new version and repeats both reviews. In `VERIFUND_MODE=off`, keep
the existing approval-only path.

The snippets below describe the existing settlement nodes; implement them
with the checkpoint/resume protocol above, rather than directly invoking
seller acceptance from the Buyer graph.

**Files:**
- Create: `apps/buyer_agent/buyer_agent/settlement_flow.py`
- Modify: `apps/buyer_agent/buyer_agent/graph.py`
- Modify: `apps/buyer_agent/buyer_agent/executor.py`
- Test: `tests/unit/test_buyer_settlement_flow.py`
- Test: `tests/unit/test_buyer_settlement_routing.py`

**Interfaces:**
- Produces: `settlement_enabled`, `build_award_request`, `create_award`, `report_acceptance`, `report_rejection`, `report_approval`, `start_funding`, `refresh_funding`, `report_purchase_order`, `fetch_state`; graph nodes for award checkpoint/agreement creation, Buyer review checkpoint, Seller-result continuation, `report_approval`, `fund_settlement`, `settlement_place_order`, `await_release`; executor interrupt reasons `agreement_create_required`, `buyer_review_required`, `seller_review_required`, `funding_required`, and `settlement_release`.
- Consumes: `SettlementStore`, `BuyerSettlementClient`, `BuyerState`, `AcceptOffer`, `PurchaseOrderRequest`.

- [ ] **Step 1: Write failing settlement flow tests**

`tests/unit/test_buyer_settlement_flow.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from buyer_agent.settlement_flow import (
    build_award_request,
    create_award,
    report_acceptance,
    report_purchase_order,
    settlement_enabled,
    start_funding,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award_payload() -> dict:
    return {
        "winner": {
            "offer_id": "offer-1",
            "seller_id": "northwind-audio",
            "seller_name": "Northwind Audio",
            "currency": "USD",
            "line_items": [
                {
                    "sku": "NC-700",
                    "name": "Nimbus NC-700",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                    "warranty_addon_cents": 0,
                }
            ],
            "subtotal_cents": 120000,
            "shipping_cents": 3400,
            "total_cents": 123400,
            "delivery_days": 7,
            "warranty_months": 24,
            "returns_days": 30,
        }
    }


class Secrets:
    def __init__(self) -> None:
        self.saved: dict | None = None
        self.projection: dict | None = None

    async def save_secret(self, **kwargs):
        self.saved = kwargs

    async def save_projection(self, run_id, projection):
        self.projection = projection


class Client:
    def __init__(self) -> None:
        self.awards: list[dict] = []
        self.accepts: list[dict] = []
        self.orders: list[dict] = []
        self.funds: list[dict] = []

    async def award(self, request, *, idempotency_key):
        self.awards.append({"request": request, "key": idempotency_key})
        return {
            "transaction_id": "vf_1",
            "agreement_hash": "a" * 64,
            "seller_token": "v1.token",
            "expires_at": "2026-10-30T12:00:00Z",
            "state": "AWARDED",
        }

    async def get_state(self, transaction_id):
        return {
            "transaction_id": transaction_id,
            "state": "AWARDED",
            "last_seq": 1,
            "seller_id": "northwind-audio",
            "amount_cents": 123400,
            "agreement_hash": "a" * 64,
        }

    async def accept(self, transaction_id, **kwargs):
        self.accepts.append({"transaction_id": transaction_id, **kwargs})
        return {"state": "AGREED"}

    async def purchase_order(self, transaction_id, report, *, idempotency_key):
        self.orders.append(
            {
                "transaction_id": transaction_id,
                "report": report,
                "key": idempotency_key,
            }
        )
        return {"state": "FULFILLMENT_PENDING"}

    async def fund(self, transaction_id, request, *, idempotency_key):
        self.funds.append(
            {
                "transaction_id": transaction_id,
                "request": request,
                "key": idempotency_key,
            }
        )
        return {
            "transaction_id": transaction_id,
            "state": "FUNDING_PENDING",
            "checkout_url": "http://control/checkout/fake/token",
            "expires_at": "2026-10-28T12:00:00Z",
        }


def services(mode: str = "fake") -> SimpleNamespace:
    secrets = Secrets()
    client = Client()
    return SimpleNamespace(
        settings=SimpleNamespace(verifund_mode=mode, console_base_url="http://console"),
        settlement=client,
        store=SimpleNamespace(settlement=secrets),
    )


def test_settlement_enabled_only_outside_off_mode():
    assert settlement_enabled(services("fake")) is True
    assert settlement_enabled(services("off")) is False
    assert settlement_enabled(SimpleNamespace(settings=SimpleNamespace(verifund_mode="fake"), settlement=None)) is False


def test_build_award_request_maps_offer_totals():
    request = build_award_request("run-1", {"buyer_id": "demo-buyer"}, award_payload())
    assert request.amount_cents == 123400
    assert request.shipping_cents == 3400
    assert request.quantity == 12
    assert request.line_items[0].sku == "NC-700"


async def test_create_award_stores_the_seller_secret_and_projection():
    value = services()
    settlement = await create_award(
        value, "run-1", {"buyer_id": "demo-buyer"}, award_payload()
    )
    assert settlement["transaction_id"] == "vf_1"
    assert settlement["agreement_hash"] == "a" * 64
    assert value.store.settlement.saved["seller_token"] == "v1.token"
    assert value.store.settlement.saved["run_id"] == "run-1"
    assert value.store.settlement.projection["state"] == "AWARDED"
    assert value.settlement.awards[0]["key"] == "award:run-1:offer-1"


async def test_report_acceptance_uses_the_bound_hash_and_total():
    value = services()
    settlement = await create_award(
        value, "run-1", {"buyer_id": "demo-buyer"}, award_payload()
    )
    await report_acceptance(
        value, settlement, seller_task_id="seller-task-1", accepted_at=NOW
    )
    call = value.settlement.accepts[0]
    assert call["seller_id"] == "northwind-audio"
    assert call["agreement_hash"] == "a" * 64
    assert call["accepted_total_cents"] == 123400


async def test_start_funding_uses_console_return_and_cancel_urls():
    value = services()
    settlement = await create_award(
        value, "run-1", {"buyer_id": "demo-buyer"}, award_payload()
    )
    funded = await start_funding(value, "run-1", settlement)
    assert funded["state"] == "FUNDING_PENDING"
    request = value.settlement.funds[0]["request"]
    assert request.return_url == "http://console/runs/run-1"
    assert request.cancel_url == "http://console/runs/run-1"
    assert value.settlement.funds[0]["key"] == "fund:vf_1:v1"


async def test_purchase_order_report_carries_settlement_fields():
    value = services()
    settlement = await create_award(
        value, "run-1", {"buyer_id": "demo-buyer"}, award_payload()
    )
    order = {
        "order_id": "MM-1",
        "offer_id": "offer-1",
        "seller_id": "northwind-audio",
        "quantity": 12,
        "total_cents": 123400,
        "reserved_at": NOW.isoformat(),
        "eta": NOW.isoformat(),
        "tracking_number": "TRK-1",
        "fulfillment": {"carrier": "Northwind Logistics"},
        "line_items": award_payload()["winner"]["line_items"],
    }
    await report_purchase_order(value, "run-1", settlement, order)
    report = value.settlement.orders[0]["report"]
    assert report.seller_order_id == "MM-1"
    assert report.tracking_number == "TRK-1"
    assert report.total_cents == 123400
```

- [ ] **Step 2: Write failing routing tests**

`tests/unit/test_buyer_settlement_routing.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from buyer_agent.graph import (
    settlement_award_route,
    settlement_approval_route,
    settlement_funding_route,
    settlement_release_route,
)


def state(**fields):
    return {"run_id": "run-1", **fields}


def test_settlement_award_route_uses_off_mode_when_no_settlement():
    assert settlement_award_route(state(settlement=None)) == "off"
    assert settlement_award_route(state(settlement={"transaction_id": "vf_1"})) == "settlement"


def test_settlement_approval_route_requires_an_approved_decision():
    assert settlement_approval_route(state(approval={"approved": True}, settlement={"transaction_id": "vf_1"})) == "settlement"
    assert settlement_approval_route(state(approval={"approved": True}, settlement=None)) == "off"
    assert settlement_approval_route(state(approval={"approved": False}, settlement={"transaction_id": "vf_1"})) == "settlement"


def test_funding_route_waits_then_moves_to_order():
    assert settlement_funding_route(state(settlement={"funding_state": "FUNDING_PENDING"})) == "wait"
    assert settlement_funding_route(state(settlement={"funding_state": "FUNDED"})) == "order"
    assert settlement_funding_route(state(settlement={"funding_state": "FAILED"})) == "failed"


def test_release_route_is_terminal_only_after_release_or_review():
    assert settlement_release_route(state(settlement={"state": "RELEASED"})) == "done"
    assert settlement_release_route(state(settlement={"state": "REVIEW_REQUIRED"})) == "review"
    assert settlement_release_route(state(settlement={"state": "VERIFICATION_PENDING"})) == "wait"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_buyer_settlement_flow.py tests/unit/test_buyer_settlement_routing.py -v`
Expected: FAIL with `ModuleNotFoundError` and missing routing functions.

- [ ] **Step 4: Implement the settlement flow helpers**

`apps/buyer_agent/buyer_agent/settlement_flow.py`:

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from commerce_core.contracts import PurchaseOrderRequest
from verifund_contracts import (
    AwardLineItem,
    AwardRequest,
    CancelReason,
    CancelRequest,
    FundRequest,
    PurchaseOrderLineItem,
    PurchaseOrderReport,
    RejectReason,
    ReleaseRequest,
)


def settlement_enabled(services: Any) -> bool:
    settings = getattr(services, "settings", None)
    if getattr(settings, "verifund_mode", "off") == "off":
        return False
    return getattr(services, "settlement", None) is not None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_award_request(
    run_id: str, mandate: dict[str, Any], award: dict[str, Any]
) -> AwardRequest:
    winner = award["winner"]
    return AwardRequest(
        run_id=run_id,
        buyer_id=str(mandate.get("buyer_id") or "demo-buyer"),
        seller_id=winner["seller_id"],
        offer_id=winner["offer_id"],
        currency=winner.get("currency", "USD"),
        amount_cents=winner["total_cents"],
        shipping_cents=winner.get("shipping_cents", 0),
        quantity=sum(item["quantity"] for item in winner["line_items"]),
        line_items=[
            AwardLineItem(
                sku=item["sku"],
                name=item["name"],
                quantity=item["quantity"],
                unit_price_cents=item["unit_price_cents"],
                warranty_addon_cents=item.get("warranty_addon_cents", 0),
            )
            for item in winner["line_items"]
        ],
        delivery_days=winner["delivery_days"],
        warranty_months=winner["warranty_months"],
        returns_days=winner["returns_days"],
    )


async def create_award(
    services: Any,
    run_id: str,
    mandate: dict[str, Any],
    award: dict[str, Any],
) -> dict[str, Any] | None:
    if not settlement_enabled(services):
        return None
    request = build_award_request(run_id, mandate, award)
    response = await services.settlement.award(
        request, idempotency_key=f"award:{run_id}:{request.offer_id}"
    )
    expires_at = response["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    await services.store.settlement.save_secret(
        run_id=run_id,
        transaction_id=response["transaction_id"],
        seller_id=request.seller_id,
        purpose="settlement",
        token=response["seller_token"],
        expires_at=expires_at,
    )
    projection = await services.settlement.get_state(response["transaction_id"])
    await services.store.settlement.save_projection(run_id, projection)
    return {
        "transaction_id": response["transaction_id"],
        "agreement_hash": response["agreement_hash"],
        "seller_id": request.seller_id,
        "offer_id": request.offer_id,
        "amount_cents": request.amount_cents,
        "seller_token_expires_at": response["expires_at"],
        "state": "AWARDED",
        "projection": projection,
    }


async def ensure_seller_token(
    services: Any,
    run_id: str,
    settlement: dict[str, Any],
    *,
    threshold_hours: int = 24,
) -> dict[str, Any]:
    secret = await services.store.settlement.get_secret(
        run_id, settlement["transaction_id"], "settlement"
    )
    if secret is None:
        return settlement
    expires_at = secret["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if expires_at - datetime.now(UTC) > timedelta(hours=threshold_hours):
        return settlement
    response = await services.settlement.reissue_seller_token(
        transaction_id=settlement["transaction_id"],
        run_id=run_id,
        seller_id=settlement["seller_id"],
        purpose="settlement",
    )
    refreshed = response["expires_at"]
    if isinstance(refreshed, str):
        refreshed = datetime.fromisoformat(refreshed.replace("Z", "+00:00"))
    await services.store.settlement.save_secret(
        run_id=run_id,
        transaction_id=settlement["transaction_id"],
        seller_id=settlement["seller_id"],
        purpose="settlement",
        token=response["seller_token"],
        expires_at=refreshed,
    )
    return {
        **settlement,
        "seller_token_expires_at": response["expires_at"],
    }


async def report_acceptance(
    services: Any,
    settlement: dict[str, Any],
    *,
    seller_task_id: str,
    accepted_at: datetime,
) -> dict[str, Any]:
    return await services.settlement.accept(
        settlement["transaction_id"],
        seller_id=settlement["seller_id"],
        agreement_hash=settlement["agreement_hash"],
        accepted_total_cents=settlement["amount_cents"],
        seller_task_id=seller_task_id,
        accepted_at=_iso(accepted_at),
    )


def _reject_reason(error: dict[str, Any] | None) -> RejectReason:
    details = (error or {}).get("details") or {}
    raw = details.get("reason_code") or (error or {}).get("reason_code")
    try:
        return RejectReason(str(raw)) if raw else RejectReason.TERMS_MISMATCH
    except ValueError:
        return RejectReason.OTHER


async def report_rejection(
    services: Any,
    settlement: dict[str, Any],
    *,
    seller_task_id: str,
    rejected_at: datetime,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    return await services.settlement.reject(
        settlement["transaction_id"],
        seller_id=settlement["seller_id"],
        agreement_hash=settlement["agreement_hash"],
        reason_code=_reject_reason(error).value,
        note=str((error or {}).get("message") or "Seller declined the agreement"),
        seller_task_id=seller_task_id,
        rejected_at=_iso(rejected_at),
    )


async def report_approval(
    services: Any,
    settlement: dict[str, Any],
    approval: dict[str, Any],
) -> dict[str, Any]:
    if not approval.get("approved"):
        return await services.settlement.cancel(
            settlement["transaction_id"],
            CancelRequest(
                reason_code=CancelReason.BUYER_REJECTED,
                note=str(approval.get("note") or ""),
            ),
        )
    return await services.settlement.approve(
        settlement["transaction_id"],
        approval_id=str(uuid.uuid4()),
        approved_by=str(approval["approved_by"]),
        approved_at=_iso(datetime.now(UTC)),
        note=str(approval.get("note") or ""),
        agreement_hash=settlement["agreement_hash"],
    )


async def start_funding(
    services: Any, run_id: str, settlement: dict[str, Any]
) -> dict[str, Any]:
    console = str(services.settings.console_base_url).rstrip("/")
    request = FundRequest(
        agreement_hash=settlement["agreement_hash"],
        return_url=f"{console}/runs/{run_id}",
        cancel_url=f"{console}/runs/{run_id}",
    )
    return await services.settlement.fund(
        settlement["transaction_id"],
        request,
        idempotency_key=f"fund:{settlement['transaction_id']}:v1",
    )


async def refresh_funding(
    services: Any, settlement: dict[str, Any]
) -> dict[str, Any]:
    return await services.settlement.refresh_funding(
        settlement["transaction_id"]
    )


async def report_purchase_order(
    services: Any,
    run_id: str,
    settlement: dict[str, Any],
    order: dict[str, Any],
) -> dict[str, Any]:
    report = PurchaseOrderReport(
        agreement_hash=settlement["agreement_hash"],
        seller_order_id=str(order["order_id"]),
        offer_id=str(order["offer_id"]),
        quantity=int(order["quantity"]),
        total_cents=int(order["total_cents"]),
        currency=str(order.get("currency", "USD")),
        tracking_number=str(order["tracking_number"]),
        carrier=str((order.get("fulfillment") or {}).get("carrier") or "Unknown"),
        reserved_at=order["reserved_at"],
        eta=order["eta"],
        line_items=[
            PurchaseOrderLineItem(
                sku=item["sku"],
                quantity=item["quantity"],
                unit_price_cents=item["unit_price_cents"],
                warranty_addon_cents=item.get("warranty_addon_cents", 0),
            )
            for item in order["line_items"]
        ],
    )
    return await services.settlement.purchase_order(
        settlement["transaction_id"],
        report,
        idempotency_key=f"po:{settlement['transaction_id']}",
    )


async def fetch_state(services: Any, settlement: dict[str, Any]) -> dict[str, Any]:
    projection = await services.settlement.get_state(
        settlement["transaction_id"]
    )
    settlement["projection"] = projection
    settlement["state"] = projection["state"]
    return projection


async def release_transaction(
    services: Any,
    settlement: dict[str, Any],
    *,
    released_by: str,
    note: str,
    override: bool,
) -> dict[str, Any]:
    return await services.settlement.release(
        settlement["transaction_id"],
        ReleaseRequest(
            released_by=released_by, note=note, override=override
        ),
    )


def settle_with_secret_ref(
    settlement: dict[str, Any], run_id: str, purpose: str
) -> dict[str, str]:
    return {
        "run_id": run_id,
        "transaction_id": settlement["transaction_id"],
        "seller_id": settlement["seller_id"],
        "purpose": purpose,
    }
```

Note: `AcceptOffer` construction in graph uses `settlement_token` field; the token should not be in graph state. It can construct the request without token, and the orchestrator injects the token. But `AcceptOffer` requires `settlement_transaction_id`, `agreement_hash`, `settlement_token`. Set `settlement_token=""` or omit? The model optional; omit. Orchestrator injects before send. The seller will parse after injection. Good. In graph `AcceptOffer(... settlement_transaction_id=..., agreement_hash=...)`.

`PurchaseOrderRequest` doesn't have settlement fields? Task 2 adds them; yes.

- [ ] **Step 5: Add graph state, helper nodes, and routing**

In `graph.py`, add imports:

```python
from buyer_agent.settlement_flow import (
    create_award,
    ensure_seller_token,
    fetch_state,
    refresh_funding,
    report_acceptance,
    report_approval,
    report_purchase_order,
    report_rejection,
    settle_with_secret_ref,
    start_funding,
)
from verifund_contracts import (
    CancelReason,
    CancelRequest,
    FlagReviewRequest,
)
```

Add state fields:

```python
    settlement: dict | None
    settlement_receipt: dict | None
```

Add routing functions near `has_award`:

```python
def settlement_award_route(state: BuyerState) -> str:
    return "settlement" if state.get("settlement") else "off"


def settlement_accept_route(state: BuyerState) -> str:
    return "rejected" if state.get("stage") == "canceled" else "accepted"


def settlement_approval_route(state: BuyerState) -> str:
    approval = state.get("approval") or {}
    if state.get("settlement"):
        return "settlement"
    return "off" if approval.get("approved") else "rejected"


def settlement_funding_route(state: BuyerState) -> str:
    funding_state = (state.get("settlement") or {}).get("funding_state")
    if funding_state == "FUNDED":
        return "order"
    if funding_state in {"FAILED", "CANCELED"}:
        return "failed"
    return "wait"


def settlement_release_route(state: BuyerState) -> str:
    settlement_state = (state.get("settlement") or {}).get("state")
    if settlement_state == "RELEASED":
        return "done"
    if settlement_state == "REVIEW_REQUIRED":
        return "review"
    return "wait"
```

Add nodes:

```python
async def create_settlement_award(state, config):
    services = _services(config)
    run_id = state["run_id"]
    settlement = await create_award(
        services, run_id, state.get("mandate") or {}, state.get("award") or {}
    )
    if settlement is None:
        return {"settlement": None, "stage": "awaiting_approval"}
    await _upsert(services, run_id, stage="awarded")
    return {"settlement": settlement, "stage": "awarded"}


async def accept_settlement(state, config):
    services = _services(config)
    run_id = state["run_id"]
    settlement = state["settlement"]
    winner = (state.get("award") or {}).get("winner") or {}
    endpoint = services.registry.endpoint(winner["seller_id"])
    request = AcceptOffer(
        offer_id=winner["offer_id"],
        round=winner.get("round", 1),
        accepted_total_cents=winner["total_cents"],
        accepted_by_buyer_task=run_id,
        settlement_transaction_id=settlement["transaction_id"],
        agreement_hash=settlement["agreement_hash"],
    )
    resumed = interrupt(
        {
            "reason": "seller_call",
            "kind": "accept",
            "seller_id": winner["seller_id"],
            "card_url": endpoint.card_url,
            "request": wrap_payload("accept_offer", request),
            "settlement_secret_ref": settle_with_secret_ref(
                settlement, run_id, "seller_accept"
            ),
            "run_id": run_id,
            "context_id": run_id,
            "seller_task_id": None,
            "seller_context_id": run_id,
            "message": f"Acceptance required for {winner['seller_id']}.",
        }
    )
    turn = _turn_from_resume(resumed)
    seller_task_id = str(turn.get("task_id") or run_id)
    if turn.get("error"):
        await report_rejection(
            services,
            settlement,
            seller_task_id=seller_task_id,
            rejected_at=datetime.now(UTC),
            error=turn["error"],
        )
        await _upsert(services, run_id, stage="canceled")
        return {
            "stage": "canceled",
            "error": _error(turn["error"], code="seller_rejected"),
            "settlement": {**settlement, "state": "CANCELED"},
            "messages": [AIMessage(content="The seller declined the agreement.")],
        }
    await report_acceptance(
        services,
        settlement,
        seller_task_id=seller_task_id,
        accepted_at=datetime.now(UTC),
    )
    await _upsert(services, run_id, stage="agreed")
    return {
        "stage": "agreed",
        "settlement": {**settlement, "state": "AGREED"},
    }


async def report_settlement_approval(state, config):
    services = _services(config)
    run_id = state["run_id"]
    settlement = state["settlement"]
    approval = state.get("approval") or {}
    await report_approval(services, settlement, approval)
    if not approval.get("approved"):
        await _upsert(services, run_id, stage="rejected")
        return {
            "stage": "rejected",
            "settlement": {
                **settlement,
                "state": "CANCELED",
                "funding_state": "CANCELED",
            },
        }
    await _upsert(services, run_id, stage="approved")
    return {"stage": "approved", "settlement": {**settlement, "state": "FUNDING_PENDING"}}


async def fund_settlement(state, config):
    services = _services(config)
    run_id = state["run_id"]
    settlement = state["settlement"]
    funded = await start_funding(services, run_id, settlement)
    state_name = funded.get("state")
    if state_name == "FUNDING_PENDING":
        resumed = interrupt(
            {
                "reason": "funding_required",
                "message": "Complete the PayPal sandbox checkout.",
                "checkout_url": funded.get("checkout_url"),
                "transaction_id": settlement["transaction_id"],
                "expires_at": funded.get("expires_at"),
            }
        )
        if isinstance(resumed, dict) and resumed.get("action") == "cancel":
            await services.settlement.cancel(
                settlement["transaction_id"],
                CancelRequest(reason_code=CancelReason.BUYER_CANCELLED),
            )
            await _upsert(services, run_id, stage="canceled")
            return {
                "stage": "canceled",
                "settlement": {**settlement, "state": "CANCELED", "funding_state": "CANCELED"},
            }
        projection = await refresh_funding(services, settlement)
        state_name = projection.get("state")
        await _upsert(
            services,
            run_id,
            stage="funded" if state_name == "FUNDED" else "funding_pending",
        )
        return {
            "stage": "funded" if state_name == "FUNDED" else "funding_pending",
            "settlement": {
                **settlement,
                "state": state_name,
                "funding_state": state_name,
                "projection": projection,
            },
        }
    await _upsert(services, run_id, stage="funded" if state_name == "FUNDED" else "funding_pending")
    return {
        "stage": "funded" if state_name == "FUNDED" else "funding_pending",
        "settlement": {
            **settlement,
            "state": state_name,
            "funding_state": state_name,
        },
    }


async def settlement_place_order(state, config):
    services = _services(config)
    run_id = state["run_id"]
    settlement = await ensure_seller_token(
        services, run_id, state["settlement"]
    )
    approval = state.get("approval") or {}
    award = state.get("award") or {}
    winner = Offer.model_validate(award["winner"])
    endpoint = services.registry.endpoint(winner.seller_id)
    receipt = ApprovalReceipt(
        approval_id=str(uuid.uuid4()),
        approved_by=str(approval["approved_by"]),
        approved_at=datetime.now(UTC),
        note=approval.get("note") or None,
    )
    po = PurchaseOrderRequest(
        request_id=f"po-{run_id}-{winner.offer_id}",
        run_id=run_id,
        offer_id=winner.offer_id,
        seller_id=winner.seller_id,
        quantity=sum(item.quantity for item in winner.line_items),
        shipping_address=_shipping_address(),
        approval=receipt,
        idempotency_key=f"{run_id}:{winner.offer_id}",
        expected_total_cents=winner.total_cents,
        settlement_transaction_id=settlement["transaction_id"],
        agreement_hash=settlement["agreement_hash"],
    )
    resumed = interrupt(
        {
            "reason": "seller_call",
            "kind": "order",
            "seller_id": winner.seller_id,
            "card_url": endpoint.card_url,
            "request": wrap_payload("purchase_order", po),
            "settlement_secret_ref": settle_with_secret_ref(
                settlement, run_id, "purchase_order"
            ),
            "run_id": run_id,
            "context_id": run_id,
            "seller_task_id": None,
            "seller_context_id": run_id,
            "message": f"Order required for {winner.seller_id}.",
        }
    )
    turn = _turn_from_resume(resumed)
    order = turn.get("order")
    if order is None:
        for candidate in turn.get("orders", []) + turn.get("offers", []):
            if isinstance(candidate, dict) and candidate.get("order_id"):
                order = candidate
                break
    if order is None:
        error = turn.get("error") or "Order failed."
        await services.settlement.flag_review(
            settlement["transaction_id"],
            FlagReviewRequest(reason="order_failed", note=str(error)),
        )
        await _upsert(services, run_id, stage="review_required", error=str(error))
        return {
            "stage": "review_required",
            "order": None,
            "settlement": {**settlement, "state": "REVIEW_REQUIRED"},
            "error": _error(str(error), code="order_failed"),
        }
    projection = await report_purchase_order(
        services, run_id, settlement, order
    )
    await _upsert(
        services,
        run_id,
        stage="fulfilled",
        order=order if isinstance(order, dict) else order.model_dump(mode="json"),
    )
    return {
        "order": order if isinstance(order, dict) else order.model_dump(mode="json"),
        "stage": "fulfilled",
        "settlement": {
            **settlement,
            "state": projection.get("state", "FULFILLMENT_PENDING"),
            "projection": projection,
        },
        "trace": [{"type": "order_confirmed", "seller_id": winner.seller_id, "order_id": order.get("order_id")}],
    }


async def await_release(state, config):
    services = _services(config)
    run_id = state["run_id"]
    settlement = state["settlement"]
    projection = await fetch_state(services, settlement)
    state_name = projection["state"]
    if state_name == "RELEASED":
        receipt = None
        try:
            receipt = await services.settlement.get_receipt(
                settlement["transaction_id"]
            )
        except Exception:  # noqa: BLE001
            receipt = None
        await _upsert(services, run_id, stage="released")
        return {
            "stage": "released",
            "settlement": {**settlement, "state": state_name, "projection": projection},
            "settlement_receipt": receipt,
        }
    if state_name == "REVIEW_REQUIRED":
        await _upsert(services, run_id, stage="review_required")
        return {
            "stage": "review_required",
            "settlement": {**settlement, "state": state_name, "projection": projection},
        }
    interrupt(
        {
            "reason": "settlement_release",
            "message": "Waiting for evidence verification and reviewer release.",
            "transaction_id": settlement["transaction_id"],
            "state": state_name,
        }
    )
    projection = await fetch_state(services, settlement)
    await _upsert(services, run_id, stage=str(projection["state"]).lower())
    return {
        "stage": str(projection["state"]).lower(),
        "settlement": {
            **settlement,
            "state": projection["state"],
            "projection": projection,
        },
    }
```

Need imports `CancelReason`, `CancelRequest`, `FlagReviewRequest` in graph. Add from `verifund_contracts`.

- [ ] **Step 6: Wire the nodes and edges**

Add node wrappers in `build_buyer_graph`:

```python
    async def _settlement_award(state, config):
        return await create_settlement_award(state, config)

    async def _settlement_accept(state, config):
        return await accept_settlement(state, config)

    async def _settlement_approval(state, config):
        return await report_settlement_approval(state, config)

    async def _settlement_fund(state, config):
        return await fund_settlement(state, config)

    async def _settlement_order(state, config):
        return await settlement_place_order(state, config)

    async def _settlement_release(state, config):
        return await await_release(state, config)
```

Register the new nodes in the existing `for name, fn in [...]` list so they receive the same planner/services wrapper:

```python
        ("create_settlement_award", _settlement_award),
        ("accept_settlement", _settlement_accept),
        ("report_settlement_approval", _settlement_approval),
        ("fund_settlement", _settlement_fund),
        ("settlement_place_order", _settlement_order),
        ("await_release", _settlement_release),
```

Replace the legacy direct seller-call edge with the checkpoint/continuation
edges below. `create_settlement_award` pauses with `agreement_create_required`;
the orchestrator resumes it after Verifund creates the canonical agreement.
`buyer_review_checkpoint` pauses with the agreement for the Buyer A2A review.
After Buyer accepts, the orchestrator calls the Seller and resumes the original
Buyer task at `seller_review_continuation`, which reports the Seller result via
the Buyer client. Only that continuation may route to funding HITL.

```python
    builder.add_conditional_edges(
        "rank_offers",
        has_award,
        {"continue": "create_settlement_award", "stop": END},
    )
    builder.add_conditional_edges(
        "create_settlement_award",
        settlement_award_route,
        {"settlement": "buyer_review_checkpoint", "off": "await_approval"},
    )
    builder.add_conditional_edges(
        "buyer_review_checkpoint",
        buyer_review_route,
        {"accepted": "seller_review_checkpoint", "rejected": "finalize"},
    )
    builder.add_conditional_edges(
        "seller_review_continuation",
        seller_review_route,
        {"accepted": "await_approval", "rejected": "finalize"},
    )
    builder.add_conditional_edges(
        "await_approval",
        settlement_approval_route,
        {
            "settlement": "report_settlement_approval",
            "off": "place_order",
            "rejected": "cancel_losers",
        },
    )
    builder.add_conditional_edges(
        "report_settlement_approval",
        settlement_funding_route,
        {
            "order": "fund_settlement",
            "wait": "fund_settlement",
            "failed": "finalize",
        },
    )
    builder.add_conditional_edges(
        "fund_settlement",
        settlement_funding_route,
        {
            "order": "settlement_place_order",
            "wait": "fund_settlement",
            "failed": "finalize",
        },
    )
    builder.add_edge("settlement_place_order", "await_release")
    builder.add_conditional_edges(
        "await_release",
        settlement_release_route,
        {"done": "finalize", "review": "finalize", "wait": "await_release"},
    )
```

In the existing edge block, replace the `rank_offers` destination `"await_approval"` with `"create_settlement_award"` and remove the old `await_approval` edge. Add the new nodes to the node registration list:

```python
        ("create_settlement_award", _settlement_award),
        ("accept_settlement", _settlement_accept),
        ("report_settlement_approval", _settlement_approval),
        ("fund_settlement", _settlement_fund),
        ("settlement_place_order", _settlement_order),
        ("await_release", _settlement_release),
```

Update `await_approval` to include the settlement binding in its payload:

```python
    settlement = state.get("settlement") or {}
    payload = {
        "message": (
            f"Approve the award to {winner.get('seller_name', 'the selected seller')} "
            f"for ${winner.get('total_cents', 0) / 100:,.2f}?"
        ),
        "reason": "order_approval",
        "responseSchema": {
            "type": "object",
            "required": ["approved", "approved_by", "note"],
            "properties": {
                "approved": {"type": "boolean"},
                "approved_by": {"type": "string"},
                "note": {"type": "string"},
            },
        },
        "award": award,
        "settlement": (
            {
                "transaction_id": settlement.get("transaction_id"),
                "agreement_hash": settlement.get("agreement_hash"),
            }
            if settlement
            else None
        ),
    }
```

Update `finalize` with:

```python
    elif stage == "released":
        receipt = state.get("settlement_receipt") or {}
        payload = receipt.get("payload") or {}
        summary = (
            f"Funds released for transaction {payload.get('transaction_id', '')}. "
            f"Receipt verified: {receipt.get('verified', False)}."
        )
    elif stage == "review_required":
        summary = "Settlement is paused for reviewer resolution."
    elif stage == "canceled":
        summary = "The agreement was canceled before funding."
```

- [ ] **Step 7: Update the executor for new interrupts**

In `executor.py`, replace the interrupt response block with explicit branches. The `seller_call` response must forward the secret reference so the orchestrator can resolve the token:

```python
        if "__interrupt__" in result:
            interrupt_value = result["__interrupt__"][0].value
            reason = interrupt_value.get("reason", "order_approval")
            if reason == "seller_call":
                response = {
                    "status": "seller_call_required",
                    "reason": "seller_call",
                    "task_id": thread_id,
                    "seller_id": interrupt_value.get("seller_id"),
                    "card_url": interrupt_value.get("card_url"),
                    "kind": interrupt_value.get("kind"),
                    "request": interrupt_value.get("request"),
                    "seller_task_id": interrupt_value.get("seller_task_id"),
                    "seller_context_id": interrupt_value.get("seller_context_id"),
                    "settlement_secret_ref": interrupt_value.get(
                        "settlement_secret_ref"
                    ),
                    "message": interrupt_value.get("message", "Seller call required."),
                }
            elif reason == "funding_required":
                response = {
                    "status": "funding_required",
                    "reason": "funding_required",
                    "task_id": thread_id,
                    "transaction_id": interrupt_value.get("transaction_id"),
                    "checkout_url": interrupt_value.get("checkout_url"),
                    "expires_at": interrupt_value.get("expires_at"),
                    "message": interrupt_value.get(
                        "message", "Complete the PayPal checkout."
                    ),
                }
            elif reason == "settlement_release":
                response = {
                    "status": "release_pending",
                    "reason": "settlement_release",
                    "task_id": thread_id,
                    "transaction_id": interrupt_value.get("transaction_id"),
                    "settlement_state": interrupt_value.get("state"),
                    "message": interrupt_value.get(
                        "message", "Waiting for evidence verification and release."
                    ),
                }
            else:
                response = {
                    "status": "approval_required",
                    "reason": "order_approval",
                    "task_id": thread_id,
                    "message": interrupt_value.get(
                        "message", "Human approval required before placing the order."
                    ),
                    "award": result.get("award"),
                    "mandate": result.get("mandate"),
                }
```

The console API (Task 17) resumes `funding_required` and `settlement_release` directly through `app.state.executor.graph`; the A2A executor only needs to emit these statuses so an A2A caller can observe the pause.

- [ ] **Step 8: Run the buyer flow tests**

Run: `uv run pytest tests/unit/test_buyer_settlement_flow.py tests/unit/test_buyer_settlement_routing.py tests/unit/test_buyer_graph.py -v`
Expected: PASS. Update any existing buyer graph test that asserts `rank_offers -> await_approval` so it expects `create_settlement_award` and verifies the off-mode path still reaches `await_approval`.

- [ ] **Step 9: Commit**

```bash
git add apps/buyer_agent/buyer_agent/{settlement_flow.py,graph.py,executor.py} tests/unit/test_buyer_settlement_flow.py tests/unit/test_buyer_settlement_routing.py
git commit -m "feat(buyer): add settlement lifecycle graph and interrupts"
```

---

### Task 16A: Replace direct award creation with agreement review checkpoints

Task 16's temporary nodes call `create_award()` and `accept_settlement()` directly.
That cannot work once Verifund owns proposal assembly and the Seller owns its
own A2A review. This task replaces those bodies with the canonical graph
protocol:

```text
create_settlement_award       -> interrupt agreement_create_required
report_buyer_review           -> buyer validates award/mandate, records POST /buyer-review
await_seller_review           -> interrupt seller_review_required
report_seller_review          -> buyer reports Seller accept/reject through its client
await_funding_approval        -> interrupt funding_approval_required
report_settlement_approval    -> cancel or approve
fund_settlement               -> interrupt funding_required with checkout URL
settlement_place_order        -> seller order, evidence, verification
await_release                 -> interrupt settlement_release
```

`VERIFUND_MODE=off` still bypasses all settlement nodes and keeps the existing
approval-only path.

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/graph.py`
- Modify: `apps/buyer_agent/buyer_agent/executor.py`
- Modify: `apps/buyer_agent/buyer_agent/card.py`
- Modify: `apps/buyer_agent/buyer_agent/settlement.py`
- Test: `tests/unit/test_buyer_agreement_checkpoints.py`
- Test: `tests/unit/test_buyer_executor.py` (extend)

**Interfaces:**
- Produces: `AgreementProtocolError`, `agreement_mismatch_reason`, `buyer_review_route`, `seller_review_route`, `funding_approval_matches`, `create_settlement_award`, `report_buyer_review`, `await_seller_review`, `report_seller_review`, `await_funding_approval`; `BuyerState` fields `agreement`, `buyer_review`, `seller_decision`, `funding_approval`; buyer Agent Card skill `commerce.agreement.review`.
- Consumes: `AgreementProjection`, `AgreementReviewRequest`/`Result`, `FundingApprovalDecision`, `BuyerSettlementClient.buyer_review`, `AcceptRequest`/`RejectRequest` through the buyer client.
- Resume keys are exactly `agreement` (with `seller_token_ref`), `seller_decision`, and `funding_approval`. There is no `buyer_review_required` interrupt: the Buyer records its own review immediately after the canonical agreement resumes the task.

- [ ] **Step 1: Write failing checkpoint and routing tests**

`tests/unit/test_buyer_agreement_checkpoints.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewResult,
    FundingApprovalDecision,
)

from buyer_agent.graph import (
    AgreementProtocolError,
    agreement_mismatch_reason,
    buyer_review_route,
    funding_approval_matches,
    seller_review_route,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def agreement(**overrides) -> AgreementProjection:
    payload = {
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "shipping_cents": 3400,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "created_at": "2026-10-27T12:00:00Z",
    }
    payload.update(overrides)
    probe = AgreementProjection.model_construct(
        **payload, agreement_hash="0" * 64
    )
    return AgreementProjection(
        **payload, agreement_hash=probe.recompute_hash()
    )


def state(**overrides) -> dict:
    return {
        "run_id": "run-1",
        "award": {
            "winner": {
                "seller_id": "northwind-audio",
                "offer_id": "offer-1",
                "total_cents": 123400,
                "shipping_cents": 3400,
                "currency": "USD",
                "quantity": 12,
                "delivery_days": 7,
                "warranty_months": 24,
                "returns_days": 30,
                "line_items": [
                    {
                        "sku": "NC-700",
                        "name": "Nimbus NC-700 ANC Headset",
                        "quantity": 12,
                        "unit_price_cents": 10000,
                        "warranty_addon_cents": 0,
                    }
                ],
            }
        },
        "mandate": {"buyer_id": "demo-buyer"},
        **overrides,
    }


def test_agreement_mismatch_reason_binds_terms_to_the_award() -> None:
    assert agreement_mismatch_reason(agreement(), state()) is None
    assert (
        agreement_mismatch_reason(agreement(amount_cents=123401), state())
        == "terms_mismatch"
    )
    assert (
        agreement_mismatch_reason(agreement(seller_id="other"), state())
        == "terms_mismatch"
    )
    assert (
        agreement_mismatch_reason(agreement(buyer_id="other"), state())
        == "terms_mismatch"
    )


def test_review_routes_use_only_structured_decisions() -> None:
    assert buyer_review_route({"buyer_review": {"status": "accepted"}}) == "accepted"
    assert buyer_review_route({"buyer_review": {"status": "rejected"}}) == "rejected"
    assert seller_review_route({"seller_decision": {"status": "accepted"}}) == "accepted"
    assert seller_review_route({"seller_decision": {"status": "rejected"}}) == "rejected"
    assert buyer_review_route({}) == "rejected"
    assert seller_review_route({}) == "rejected"


def test_funding_approval_must_match_the_agreed_transaction() -> None:
    agreed = {
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "state": "AGREED",
    }
    approval = FundingApprovalDecision(
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        approved=True,
        approved_by="demo-reviewer",
        decided_at=NOW,
        idempotency_key="fund:vf_1:1",
    )
    assert funding_approval_matches(approval, agreed) is True
    stale = approval.model_copy(update={"agreement_hash": "b" * 64})
    assert funding_approval_matches(stale, agreed) is False
    not_agreed = {**agreed, "state": "AWARDED"}
    assert funding_approval_matches(approval, not_agreed) is False


def test_seller_review_rejects_a_stale_or_wrong_party_result() -> None:
    agreed = {
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
    }
    result = AgreementReviewResult(
        party="seller",
        status="accepted",
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        task_id="seller-task-1",
        context_id="run-1",
        reviewed_at=NOW,
    )
    # The graph validates by field before accepting; parse helpers are covered
    # in Task 1A. Here the structural route must treat a missing decision as a
    # rejection, never as consent.
    assert seller_review_route({"seller_decision": result.model_dump(mode="json")}) == "accepted"
    stale = result.model_copy(update={"agreement_hash": "c" * 64})
    assert seller_review_route(
        {
            "seller_decision": stale.model_dump(mode="json"),
            "settlement": {
                "agreement_hash": HASH,
                "agreement_version": 1,
            },
        }
    ) == "rejected"


def test_agreement_protocol_error_is_not_a_success_value() -> None:
    with pytest.raises(AgreementProtocolError):
        raise AgreementProtocolError("seller review hash mismatch")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_buyer_agreement_checkpoints.py tests/unit/test_buyer_executor.py -v`
Expected: FAIL with missing `AgreementProtocolError` and checkpoint helpers, and executor assertions for the new interrupt reasons.

- [ ] **Step 3: Add state fields, validation helpers, and routes**

In `apps/buyer_agent/buyer_agent/graph.py`, add imports:

```python
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewDecision,
    AgreementReviewResult,
    CancelReason,
    CancelRequest,
    FundingApprovalDecision,
    FlagReviewRequest,
)
```

Add `BuyerState` fields:

```python
    agreement: dict | None
    buyer_review: dict | None
    seller_decision: dict | None
    funding_approval: dict | None
```

Add near the existing routing helpers:

```python
class AgreementProtocolError(ValueError):
    """A structured agreement/review value does not match the run binding."""


def _qty_total(line_items: list[dict]) -> int:
    return sum(int(item["quantity"]) for item in line_items)


def _terms_total(line_items: list[dict]) -> int:
    return sum(
        (int(item["unit_price_cents"]) + int(item.get("warranty_addon_cents", 0)))
        * int(item["quantity"])
        for item in line_items
    )


def agreement_mismatch_reason(
    agreement: AgreementProjection, state: dict
) -> str | None:
    winner = (state.get("award") or {}).get("winner") or {}
    buyer_id = str((state.get("mandate") or {}).get("buyer_id") or "demo-buyer")
    expected = {
        "run_id": state["run_id"],
        "buyer_id": buyer_id,
        "seller_id": winner.get("seller_id"),
        "offer_id": winner.get("offer_id"),
        "currency": winner.get("currency", "USD"),
        "amount_cents": winner.get("total_cents"),
        "quantity": winner.get("quantity", _qty_total(winner.get("line_items", []))),
        "shipping_cents": winner.get("shipping_cents", 0),
        "delivery_days": winner.get("delivery_days"),
        "warranty_months": winner.get("warranty_months"),
        "returns_days": winner.get("returns_days"),
    }
    actual = agreement.model_dump(mode="json")
    for key, value in expected.items():
        if value is not None and actual.get(key) != value:
            return "terms_mismatch"
    expected_lines = [
        {
            "sku": item["sku"],
            "name": item["name"],
            "quantity": item["quantity"],
            "unit_price_cents": item["unit_price_cents"],
            "warranty_addon_cents": item.get("warranty_addon_cents", 0),
        }
        for item in winner.get("line_items", [])
    ]
    if actual.get("line_items") != expected_lines:
        return "terms_mismatch"
    if _terms_total(actual["line_items"]) + int(actual["shipping_cents"]) != int(
        actual["amount_cents"]
    ):
        return "terms_mismatch"
    return None


def buyer_review_route(state: dict) -> str:
    decision = (state.get("buyer_review") or {}).get("status")
    return "accepted" if decision == AgreementReviewDecision.ACCEPTED.value else "rejected"


def seller_review_route(state: dict) -> str:
    decision = (state.get("seller_decision") or {}).get("status")
    binding = state.get("settlement") or {}
    if (
        decision != AgreementReviewDecision.ACCEPTED.value
        or not binding
        or (state.get("seller_decision") or {}).get("agreement_hash")
        != binding.get("agreement_hash")
        or (state.get("seller_decision") or {}).get("agreement_version")
        != binding.get("agreement_version")
    ):
        return "rejected"
    return "accepted"


def funding_approval_matches(
    approval: FundingApprovalDecision, settlement: dict
) -> bool:
    return (
        settlement.get("state") == "AGREED"
        and approval.run_id == settlement.get("run_id", approval.run_id)
        and approval.transaction_id == settlement.get("transaction_id")
        and approval.agreement_version == settlement.get("agreement_version")
        and approval.agreement_hash == settlement.get("agreement_hash")
    )
```

- [ ] **Step 4: Replace the settlement node bodies**

Replace `create_settlement_award` and `accept_settlement` from Task 16 with:

```python
async def create_settlement_award(state, config):
    if not settlement_enabled(_services(config)):
        return {"settlement": None, "stage": "awaiting_approval"}
    services = _services(config)
    run_id = state["run_id"]
    award = build_award_request(
        run_id, state.get("mandate") or {}, state.get("award") or {}
    )
    resumed = interrupt(
        {
            "reason": "agreement_create_required",
            "message": "Create the canonical agreement with the Verifund agent.",
            "run_id": run_id,
            "buyer_task_id": state["task_id"],
            "buyer_context_id": state["context_id"],
            "award": award.model_dump(mode="json"),
        }
    )
    payload = resumed if isinstance(resumed, dict) else {}
    try:
        agreement = AgreementProjection.model_validate(payload.get("agreement"))
    except Exception as exc:  # noqa: BLE001
        raise AgreementProtocolError("canonical agreement is invalid") from exc
    if agreement.run_id != run_id or agreement.buyer_id != award.buyer_id:
        raise AgreementProtocolError("canonical agreement is bound to another run")
    settlement = {
        "run_id": run_id,
        "transaction_id": agreement.transaction_id,
        "agreement_version": agreement.agreement_version,
        "agreement_hash": agreement.agreement_hash,
        "agreement": agreement.model_dump(mode="json"),
        "seller_token_ref": str(
            payload.get("seller_token_ref")
            or f"run:{run_id}:transaction:{agreement.transaction_id}"
        ),
        "state": "AWARDED",
        "funding_state": "AWARDED",
    }
    await _upsert(services, run_id, stage="awarded")
    return {
        "agreement": agreement.model_dump(mode="json"),
        "settlement": settlement,
        "stage": "awarded",
    }


async def report_buyer_review(state, config):
    services = _services(config)
    settlement = state["settlement"]
    agreement = AgreementProjection.model_validate(state["agreement"])
    reason = agreement_mismatch_reason(agreement, state)
    decision = "accepted" if reason is None else "rejected"
    projection = await services.settlement.buyer_review(
        agreement.transaction_id,
        buyer_id=agreement.buyer_id,
        agreement_version=agreement.agreement_version,
        agreement_hash=agreement.agreement_hash,
        decision=decision,
        buyer_task_id=state["task_id"],
        reviewed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        reason_code=reason,
        note="" if reason is None else "Agreement does not match the award and mandate.",
        idempotency_key=(
            f"buyer-review:{agreement.transaction_id}:"
            f"{agreement.agreement_version}:{agreement.agreement_hash}"
        ),
    )
    review = {
        "status": decision,
        "agreement_version": agreement.agreement_version,
        "agreement_hash": agreement.agreement_hash,
        "task_id": state["task_id"],
        "reviewed_at": projection["buyer_agent_review"]["reviewed_at"],
        "reason_code": reason,
    }
    updated = {
        **settlement,
        "state": projection["state"],
        "funding_state": projection["state"],
    }
    if decision == "rejected":
        await services.settlement.cancel(
            agreement.transaction_id,
            CancelRequest(
                reason_code=CancelReason.BUYER_REJECTED,
                note="Agreement does not match the award and mandate.",
            ),
        )
        updated["state"] = "CANCELED"
        await _upsert(services, state["run_id"], stage="rejected")
        return {
            "buyer_review": review,
            "settlement": updated,
            "stage": "rejected",
        }
    await _upsert(services, state["run_id"], stage="buyer_reviewed")
    return {
        "buyer_review": review,
        "settlement": updated,
        "stage": "buyer_reviewed",
    }


async def await_seller_review(state, config):
    settlement = state["settlement"]
    agreement = AgreementProjection.model_validate(state["agreement"])
    resumed = interrupt(
        {
            "reason": "seller_review_required",
            "message": "Request the Seller agent agreement review.",
            "run_id": state["run_id"],
            "transaction_id": agreement.transaction_id,
            "agreement": agreement.model_dump(mode="json"),
            "seller_id": agreement.seller_id,
            "buyer_task_id": state["task_id"],
            "buyer_context_id": state["context_id"],
            "buyer_agent_review": state.get("buyer_review"),
            "seller_task_id": None,
            "seller_context_id": state["run_id"],
        }
    )
    payload = resumed if isinstance(resumed, dict) else {}
    try:
        decision = AgreementReviewResult.model_validate(payload.get("seller_decision"))
    except Exception as exc:  # noqa: BLE001
        raise AgreementProtocolError("seller review result is invalid") from exc
    if (
        decision.party != "seller"
        or decision.transaction_id != agreement.transaction_id
        or decision.agreement_version != agreement.agreement_version
        or decision.agreement_hash != agreement.agreement_hash
    ):
        raise AgreementProtocolError("seller review result does not match the agreement")
    return {"seller_decision": decision.model_dump(mode="json")}


async def report_seller_review(state, config):
    services = _services(config)
    settlement = state["settlement"]
    decision = AgreementReviewResult.model_validate(state["seller_decision"])
    if decision.status == AgreementReviewDecision.ACCEPTED:
        projection = await services.settlement.accept(
            settlement["transaction_id"],
            seller_id=settlement["agreement"]["seller_id"],
            agreement_hash=settlement["agreement_hash"],
            accepted_total_cents=settlement["agreement"]["amount_cents"],
            seller_task_id=decision.task_id,
            accepted_at=decision.reviewed_at.isoformat().replace("+00:00", "Z"),
        )
    else:
        projection = await services.settlement.reject(
            settlement["transaction_id"],
            seller_id=settlement["agreement"]["seller_id"],
            agreement_hash=settlement["agreement_hash"],
            reason_code=decision.reason_code or "terms_mismatch",
            note=decision.note,
            seller_task_id=decision.task_id,
            rejected_at=decision.reviewed_at.isoformat().replace("+00:00", "Z"),
        )
    updated = {
        **settlement,
        "state": projection["state"],
        "funding_state": projection["state"],
    }
    await _upsert(
        services,
        state["run_id"],
        stage="agreed" if decision.status == AgreementReviewDecision.ACCEPTED else "rejected",
    )
    return {
        "seller_decision": decision.model_dump(mode="json"),
        "settlement": updated,
        "stage": "agreed" if decision.status == AgreementReviewDecision.ACCEPTED else "rejected",
    }


async def await_funding_approval(state, config):
    services = _services(config)
    settlement = state["settlement"]
    projection = await fetch_state(services, settlement)
    if projection["state"] != "AGREED":
        raise AgreementProtocolError(
            f"funding approval requires AGREED, got {projection['state']}"
        )
    resumed = interrupt(
        {
            "reason": "funding_approval_required",
            "message": "Approve or reject funding for the agreed transaction.",
            "run_id": state["run_id"],
            "transaction_id": settlement["transaction_id"],
            "agreement_version": settlement["agreement_version"],
            "agreement_hash": settlement["agreement_hash"],
            "agreement": settlement["agreement"],
            "buyer_agent_review": projection.get("buyer_agent_review"),
            "seller_decision": projection.get("seller_decision"),
            "responseSchema": FundingApprovalDecision.model_json_schema(),
        }
    )
    payload = resumed if isinstance(resumed, dict) else {}
    try:
        approval = FundingApprovalDecision.model_validate(payload.get("funding_approval"))
    except Exception as exc:  # noqa: BLE001
        raise AgreementProtocolError("funding approval is invalid") from exc
    agreed = {**settlement, **projection, "state": projection["state"]}
    if not funding_approval_matches(approval, agreed):
        raise AgreementProtocolError("funding approval does not match the agreed transaction")
    return {
        "funding_approval": approval.model_dump(mode="json"),
        "approval": {
            "approved": approval.approved,
            "approved_by": approval.approved_by,
            "note": approval.note,
        },
        "settlement": {
            **settlement,
            "state": projection["state"],
            "projection": projection,
        },
    }
```

- [ ] **Step 5: Rewire the graph edges and node registry**

Replace the Task 16 edge block with:

```python
    builder.add_conditional_edges(
        "rank_offers",
        has_award,
        {"continue": "create_settlement_award", "stop": END},
    )
    builder.add_conditional_edges(
        "create_settlement_award",
        settlement_award_route,
        {"settlement": "report_buyer_review", "off": "await_approval"},
    )
    builder.add_conditional_edges(
        "report_buyer_review",
        buyer_review_route,
        {"accepted": "await_seller_review", "rejected": "finalize"},
    )
    builder.add_edge("await_seller_review", "report_seller_review")
    builder.add_conditional_edges(
        "report_seller_review",
        seller_review_route,
        {"accepted": "await_funding_approval", "rejected": "finalize"},
    )
    builder.add_conditional_edges(
        "await_funding_approval",
        settlement_approval_route,
        {"settlement": "report_settlement_approval", "off": "place_order", "rejected": "cancel_losers"},
    )
    builder.add_conditional_edges(
        "report_settlement_approval",
        settlement_funding_route,
        {"order": "fund_settlement", "wait": "fund_settlement", "failed": "finalize"},
    )
    builder.add_conditional_edges(
        "fund_settlement",
        settlement_funding_route,
        {"order": "settlement_place_order", "wait": "fund_settlement", "failed": "finalize"},
    )
    builder.add_edge("settlement_place_order", "await_release")
    builder.add_conditional_edges(
        "await_release",
        settlement_release_route,
        {"done": "finalize", "review": "finalize", "wait": "await_release"},
    )
```

Register:

```python
        ("create_settlement_award", create_settlement_award),
        ("report_buyer_review", report_buyer_review),
        ("await_seller_review", await_seller_review),
        ("report_seller_review", report_seller_review),
        ("await_funding_approval", await_funding_approval),
        ("report_settlement_approval", report_settlement_approval),
        ("fund_settlement", fund_settlement),
        ("settlement_place_order", settlement_place_order),
        ("await_release", await_release),
```

Do not register `accept_settlement`; delete the function. `await_approval` remains only for `VERIFUND_MODE=off`.

`settlement_award_route` becomes:

```python
def settlement_award_route(state: BuyerState) -> str:
    return "settlement" if state.get("settlement") else "off"
```

- [ ] **Step 6: Resume the buyer task from structured envelopes**

In `executor.py`, add the new resume-key mapping. Ensure these imports exist at
the top of the module:

```python
from langgraph.types import Command
from commerce_core.a2a_parts import first_envelope
```

When the incoming message contains a `verifund` envelope, the executor selects the key from the interrupt reason instead of the generic approval shape:

```python
AGREEMENT_REASONS = {
    "agreement_create_required": "agreement",
    "seller_review_required": "seller_decision",
    "funding_approval_required": "funding_approval",
}


def _resume_key(reason: str) -> str | None:
    return AGREEMENT_REASONS.get(reason)


def _agreement_resume_value(reason: str, envelope: dict) -> dict:
    payload = envelope.get("payload") or {}
    if reason == "agreement_create_required":
        return {
            "agreement": payload.get("agreement"),
            "seller_token_ref": payload.get("seller_token_ref"),
        }
    if reason == "seller_review_required":
        return {"seller_decision": payload}
    return {"funding_approval": payload}
```

In the existing `execute` method, before invoking the graph, inspect the current interrupt:

```python
        snapshot = await self.graph.aget_state(config)
        pending = getattr(snapshot, "interrupts", ()) or ()
        if pending:
            value = pending[0].value
            reason = str(value.get("reason", ""))
            envelope = first_envelope(message)
            if reason in AGREEMENT_REASONS and envelope is not None:
                resume = _agreement_resume_value(reason, envelope)
                result = await self.graph.ainvoke(
                    Command(resume=resume), config=config
                )
                return self._response(result, thread_id)
```

Map the new interrupts to task states in `_interrupt_response`:

```python
        if reason == "agreement_create_required":
            return {
                "status": "agreement_create_required",
                "reason": reason,
                "task_id": thread_id,
                "run_id": value.get("run_id"),
                "buyer_task_id": value.get("buyer_task_id"),
                "buyer_context_id": value.get("buyer_context_id"),
                "award": value.get("award"),
                "message": value.get("message"),
            }
        if reason == "seller_review_required":
            return {
                "status": "seller_review_required",
                "reason": reason,
                "task_id": thread_id,
                "run_id": value.get("run_id"),
                "transaction_id": value.get("transaction_id"),
                "agreement": value.get("agreement"),
                "seller_id": value.get("seller_id"),
                "buyer_agent_review": value.get("buyer_agent_review"),
                "message": value.get("message"),
            }
        if reason == "funding_approval_required":
            return {
                "status": "funding_approval_required",
                "reason": reason,
                "task_id": thread_id,
                "run_id": value.get("run_id"),
                "transaction_id": value.get("transaction_id"),
                "agreement_version": value.get("agreement_version"),
                "agreement_hash": value.get("agreement_hash"),
                "agreement": value.get("agreement"),
                "buyer_agent_review": value.get("buyer_agent_review"),
                "seller_decision": value.get("seller_decision"),
                "responseSchema": value.get("responseSchema"),
                "message": value.get("message"),
            }
```

Keep the existing `funding_required` and `settlement_release` branches. If the graph is not currently interrupted, a review envelope must fail with `status="failed"` and `reason="no_pending_review"`; never create a new task from an unsolicited review.

Add `commerce.agreement.review` to `build_buyer_agent_card`:

```python
        AgentSkill(
            id="commerce.agreement.review",
            name="Review a Verifund agreement",
            description=(
                "Resume a paused buyer task with the canonical agreement, "
                "validate it against the award and mandate, and return a "
                "hash-bound buyer-agent decision."
            ),
            tags=["commerce", "verifund", "agreement-review"],
            input_modes=["application/json"],
            output_modes=["application/json"],
        ),
```

- [ ] **Step 7: Run the checkpoint and executor tests**

Run: `uv run pytest tests/unit/test_buyer_agreement_checkpoints.py tests/unit/test_buyer_executor.py tests/unit/test_buyer_graph.py -v`
Expected: PASS. Off-mode graph tests must still show `rank_offers -> create_settlement_award -> await_approval`.

- [ ] **Step 8: Commit**

```bash
git add apps/buyer_agent/buyer_agent/{graph.py,executor.py,card.py,settlement.py} tests/unit/test_buyer_agreement_checkpoints.py tests/unit/test_buyer_executor.py
git commit -m "feat(buyer): require canonical agreement and bilateral review before funding"
```

---

### Task 17: Buyer settlement API, internal seller-token endpoint, and run projection

Add the console-facing settlement routes and the existing
`POST /internal/settlement/seller-token` route. The six authenticated
Verifund-agent internal routes are added by Task 17A; do not duplicate them
here. Do not add a Verifund endpoint for recording reviews: the resumed Buyer
A2A task records its own review through `POST /buyer-review`, and reports the
Seller's exact accept/reject response through the existing Buyer client. The
Buyer API must persist both decisions as append-only, hash-bound receipts and
expose them in the settlement projection. Keep the internal routes off the
public Next.js proxy.

**Files:**
- Create: `apps/buyer_agent/buyer_agent/settlement_api.py`
- Modify: `apps/buyer_agent/buyer_agent/console_api.py`
- Modify: `apps/buyer_agent/buyer_agent/server.py`
- Test: `tests/integration/test_buyer_settlement_api.py`

**Interfaces:**
- Produces: `console_authorized(request)`, `load_settlement_projection(request, run_id, actor=..., refresh=...)`; router routes `GET /api/runs/{run_id}/settlement`, `POST /api/runs/{run_id}/settlement/advance`, `POST /release`, `POST /review`, `POST /cancel`, `GET /receipt`, `GET /evidence/{evidence_id}`, `POST /internal/settlement/seller-token`.
- Consumes: `BuyerSettlementClient`, `SettlementStore`, `SettlementCoordinator`, `app.state.executor.graph`, `Command`, `ReleaseRequest`, `FlagReviewRequest`, `CancelRequest`.

- [ ] **Step 1: Write the failing buyer settlement API tests**

`tests/integration/test_buyer_settlement_api.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from buyer_agent import console_api, settlement_api
from buyer_agent.settlement import SettlementCoordinator


class Settings:
    console_api_token = "console-token"
    internal_api_token = "internal-token"
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
    assert without.status_code == 200
    assert "settlement" not in without.json()

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_buyer_settlement_api.py -v`
Expected: FAIL with `ModuleNotFoundError: buyer_agent.settlement_api` and 404s.

- [ ] **Step 3: Implement the settlement API**

`apps/buyer_agent/buyer_agent/settlement_api.py`:

```python
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from langgraph.types import Command
from pydantic import BaseModel, Field
from verifund_contracts import (
    CancelRequest,
    FlagReviewRequest,
    ReleaseRequest,
)

router = APIRouter()
REVIEWER = "console:reviewer"


class AdvanceBody(BaseModel):
    action: Literal["refresh"] = "refresh"


class ReleaseBody(BaseModel):
    released_by: str = Field(default=REVIEWER, min_length=1)
    note: str = ""
    override: bool = False


class ReviewBody(BaseModel):
    action: Literal["flag_review", "retry_payout"]
    reason: str = "manual_flag"
    note: str = ""


class CancelBody(BaseModel):
    reason_code: Literal[
        "buyer_rejected", "buyer_cancelled", "reviewer_cancelled"
    ]
    note: str = ""


class SellerTokenBody(BaseModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


def _services(request: Request) -> Any:
    return request.app.state.services


def _settlement_store(request: Request):
    store = getattr(_services(request), "store", None)
    return getattr(store, "settlement", None)


def console_authorized(request: Request) -> bool:
    expected = request.app.state.settings.console_api_token
    provided = request.headers.get("x-marketmesh-console-token", "")
    return bool(expected) and secrets.compare_digest(provided, expected)


def _require_console(request: Request) -> None:
    if not console_authorized(request):
        raise HTTPException(status_code=401, detail="unauthorized")


def _require_client(request: Request):
    client = getattr(_services(request), "settlement", None)
    store = _settlement_store(request)
    if client is None or store is None:
        raise HTTPException(status_code=503, detail="settlement unavailable")
    return client, store


async def load_settlement_projection(
    request: Request,
    run_id: str,
    *,
    actor: str = REVIEWER,
    refresh: bool = True,
) -> dict[str, Any] | None:
    services = _services(request)
    client = getattr(services, "settlement", None)
    store = _settlement_store(request)
    cached = await store.get_projection(run_id) if store is not None else None
    if client is None or store is None:
        return (
            {**cached, "settlement_unavailable": True} if cached else None
        )
    if not refresh:
        return {**cached, "settlement_unavailable": False} if cached else None
    if cached is None:
        return None
    try:
        projection = await client.get_state(
            cached["transaction_id"], actor=actor
        )
    except Exception:  # noqa: BLE001
        return {**cached, "settlement_unavailable": True}
    advanced = await store.save_projection(run_id, projection)
    if advanced:
        trace = getattr(services, "trace", None)
        recorder = getattr(trace, "record", None)
        if recorder is not None:
            await recorder(
                run_id,
                direction="internal",
                method="settlement_status",
                payload={
                    "transaction_id": projection["transaction_id"],
                    "state": projection["state"],
                    "last_seq": int(projection.get("last_seq") or 0),
                },
            )
    return {**projection, "settlement_unavailable": False}


async def _cached_transaction(request: Request, run_id: str) -> str:
    store = _settlement_store(request)
    cached = await store.get_projection(run_id) if store is not None else None
    if cached is None:
        raise HTTPException(status_code=404, detail="settlement not found")
    return str(cached["transaction_id"])


def _error(exc: Exception) -> HTTPException:
    status = getattr(exc, "status_code", 0) or 502
    return HTTPException(
        status_code=status,
        detail={
            "code": getattr(exc, "code", "settlement_unavailable"),
            "message": str(exc),
        },
    )


@asynccontextmanager
async def _run_lock(request: Request, run_id: str) -> AsyncIterator[None]:
    coordinator = getattr(_services(request), "coordinator", None)
    if coordinator is None:
        yield
        return
    if coordinator.is_locked(run_id):
        raise HTTPException(
            status_code=409, detail="settlement action already in progress"
        )
    async with coordinator.lock(run_id):
        yield


def _public_interrupt(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result or "__interrupt__" not in result:
        return None
    # The reference carries only run/transaction/seller IDs. The seller token
    # is resolved server-side by the orchestrator and never leaves the buyer.
    return dict(result["__interrupt__"][0].value)


async def _resume_graph(
    request: Request, run_id: str, value: dict[str, Any]
) -> dict[str, Any] | None:
    executor = getattr(request.app.state, "executor", None)
    graph = getattr(executor, "graph", None)
    if graph is None:
        return None
    config = {"configurable": {"thread_id": run_id}}
    snapshot = await graph.aget_state(config)
    if not getattr(snapshot, "next", None):
        return None
    return await graph.ainvoke(Command(resume=value), config=config)


async def _after_action(
    request: Request, run_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    store = _settlement_store(request)
    await store.save_projection(run_id, result)
    await _resume_graph(request, run_id, {"action": "refresh"})
    return {"run_id": run_id, "settlement": result}


@router.get("/api/runs/{run_id}/settlement")
async def get_settlement(run_id: str, request: Request) -> dict[str, Any]:
    _require_console(request)
    projection = await load_settlement_projection(request, run_id)
    if projection is None:
        if getattr(_services(request), "settlement", None) is None:
            raise HTTPException(
                status_code=503, detail="settlement unavailable"
            )
        raise HTTPException(status_code=404, detail="settlement not found")
    return projection


@router.post("/api/runs/{run_id}/settlement/advance")
async def advance_settlement(
    run_id: str, body: AdvanceBody, request: Request
) -> dict[str, Any]:
    _require_console(request)
    async with _run_lock(request, run_id):
        result = await _resume_graph(
            request, run_id, body.model_dump(mode="json")
        )
        if result is None:
            raise HTTPException(
                status_code=409, detail="no settlement interrupt is pending"
            )
        projection = await load_settlement_projection(request, run_id)
        return {
            "run_id": run_id,
            "settlement": projection,
            "interrupt": _public_interrupt(result),
        }


@router.post("/api/runs/{run_id}/settlement/release")
async def release_settlement(
    run_id: str, body: ReleaseBody, request: Request
) -> dict[str, Any]:
    _require_console(request)
    client, _ = _require_client(request)
    async with _run_lock(request, run_id):
        transaction_id = await _cached_transaction(request, run_id)
        try:
            result = await client.release(
                transaction_id,
                ReleaseRequest(
                    released_by=body.released_by,
                    note=body.note,
                    override=body.override,
                ),
                actor=REVIEWER,
            )
        except Exception as exc:  # noqa: BLE001
            raise _error(exc) from exc
        return await _after_action(request, run_id, result)


@router.post("/api/runs/{run_id}/settlement/review")
async def review_settlement(
    run_id: str, body: ReviewBody, request: Request
) -> dict[str, Any]:
    _require_console(request)
    client, _ = _require_client(request)
    async with _run_lock(request, run_id):
        transaction_id = await _cached_transaction(request, run_id)
        try:
            if body.action == "flag_review":
                result = await client.flag_review(
                    transaction_id,
                    FlagReviewRequest(reason=body.reason, note=body.note),
                    actor=REVIEWER,
                )
            else:
                result = await client.retry_payout(
                    transaction_id, actor=REVIEWER
                )
        except Exception as exc:  # noqa: BLE001
            raise _error(exc) from exc
        return await _after_action(request, run_id, result)


@router.post("/api/runs/{run_id}/settlement/cancel")
async def cancel_settlement(
    run_id: str, body: CancelBody, request: Request
) -> dict[str, Any]:
    _require_console(request)
    client, _ = _require_client(request)
    async with _run_lock(request, run_id):
        transaction_id = await _cached_transaction(request, run_id)
        try:
            result = await client.cancel(
                transaction_id,
                CancelRequest(reason_code=body.reason_code, note=body.note),
                actor=REVIEWER,
            )
        except Exception as exc:  # noqa: BLE001
            raise _error(exc) from exc
        return await _after_action(request, run_id, result)


@router.get("/api/runs/{run_id}/settlement/receipt")
async def get_receipt(run_id: str, request: Request) -> dict[str, Any]:
    _require_console(request)
    client, _ = _require_client(request)
    transaction_id = await _cached_transaction(request, run_id)
    try:
        return await client.get_receipt(transaction_id, actor=REVIEWER)
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.get("/api/runs/{run_id}/settlement/evidence/{evidence_id}")
async def get_evidence(
    run_id: str, evidence_id: str, request: Request
) -> Response:
    _require_console(request)
    client, _ = _require_client(request)
    transaction_id = await _cached_transaction(request, run_id)
    try:
        content, media_type, filename = await client.get_evidence(
            transaction_id, evidence_id, actor=REVIEWER
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "content-disposition": f'attachment; filename="{filename}"'
        },
    )


@router.post("/internal/settlement/seller-token")
async def get_seller_token(
    body: SellerTokenBody, request: Request
) -> dict[str, Any]:
    expected = request.app.state.settings.internal_api_token
    provided = request.headers.get("x-marketmesh-internal-token", "")
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
    store = _settlement_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="settlement unavailable")
    secret = await store.get_secret_by_transaction(body.transaction_id)
    if secret is None:
        raise HTTPException(status_code=404, detail="seller token not found")
    if (
        str(secret["run_id"]) != body.run_id
        or str(secret["seller_id"]) != body.seller_id
    ):
        raise HTTPException(status_code=403, detail="seller token mismatch")
    expires_at = datetime.fromisoformat(
        str(secret["expires_at"]).replace("Z", "+00:00")
    )
    if expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="seller token expired")
    return {
        "seller_token": secret["seller_token"],
        "expires_at": secret["expires_at"],
    }
```

- [ ] **Step 4: Merge the projection into `GET /api/runs/{run_id}` and wire the router**

In `console_api.py`, import:

```python
from buyer_agent.settlement_api import (
    console_authorized,
    load_settlement_projection,
)
```

Replace `get_run` with:

```python
@router.get("/api/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict:
    trace = getattr(_services(request), "trace", None)
    row = await trace.get_run(run_id) if trace is not None else None
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    payload = _run(row)
    if console_authorized(request):
        projection = await load_settlement_projection(request, run_id)
        if projection is not None:
            payload["settlement"] = projection
    return payload
```

In `server.py`, include the new router next to `console_api.router`:

```python
    app.include_router(console_api.router)
    app.include_router(settlement_api.router)
```

Import it:

```python
from buyer_agent import console_api, settlement_api
```

Assign the executor so settlement actions can resume the graph:

```python
    app.state.executor = executor
```

- [ ] **Step 5: Run the settlement API tests**

Run: `uv run pytest tests/integration/test_buyer_settlement_api.py -v`
Expected: PASS.

- [ ] **Step 6: Run the buyer test suite**

Run: `uv run pytest tests/unit tests/integration -k "buyer or settlement" -v`
Expected: PASS; existing off-mode buyer tests still pass.

- [ ] **Step 7: Commit**

```bash
git add apps/buyer_agent/buyer_agent/{settlement_api.py,console_api.py,server.py} tests/integration/test_buyer_settlement_api.py
git commit -m "feat(buyer): expose settlement API and internal seller-token endpoint"
```

---

### Task 17A: Buyer internal Verifund routes and agreement binding

The Verifund A2A service must never hold `VERIFUND_OPS_TOKEN`,
`SELLER_TRANSACTION_TOKEN_SECRET`, PayPal credentials, or the seller token.
The buyer exposes six authenticated internal routes that translate Verifund's
requests into its own control-plane client calls:

```text
GET  /internal/runs/{run_id}/settlement
POST /internal/runs/{run_id}/settlement/agreement
POST /internal/runs/{run_id}/settlement/approve-funding
POST /internal/runs/{run_id}/settlement/release
GET  /internal/runs/{run_id}/settlement/receipt
GET  /internal/runs/{run_id}/settlement/evidence/{evidence_id}
```

Every route requires `x-verifund-agent-token: $VERIFUND_AGENT_INTERNAL_TOKEN`
and verifies that the request's run, transaction, version, and hash match the
stored agreement. The routes are not mounted through Next.js and never return
the seller token or the ops token.

**Files:**
- Create: `apps/buyer_agent/buyer_agent/agreement_service.py`
- Modify: `apps/buyer_agent/buyer_agent/settlement_api.py`
- Modify: `apps/buyer_agent/buyer_agent/settlement_store.py`
- Modify: `apps/buyer_agent/buyer_agent/settings.py`
- Modify: `apps/buyer_agent/buyer_agent/services.py`
- Modify: `apps/buyer_agent/buyer_agent/server.py`
- Test: `tests/integration/test_buyer_verifund_api.py`

**Interfaces:**
- Produces: `BuyerAgreementService.create_agreement`, `view`, `approve_funding`, `release`, `receipt`, `evidence`; `SettlementStore.save_agreement`, `get_agreement`; `Settings.verifund_agent_internal_token`; the six internal routes.
- Consumes: `BuyerSettlementClient`, `SettlementStore`, `BuyerAgreementRequest`/`Response`, `FundingApprovalDecision`, `ReleaseApprovalDecision`, `ApproveRequest`, `FundRequest`, `CancelRequest`, and `ReleaseRequest`.

- [ ] **Step 1: Write the failing internal-route tests**

`tests/integration/test_buyer_verifund_api.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from buyer_agent import settlement_api

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64
HEADERS = {"x-verifund-agent-token": "agent-internal"}


def projection(state: str = "AWARDED") -> dict:
    return {
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "state": state,
        "last_seq": 4,
        "amount_cents": 123400,
        "currency": "USD",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "agreement_hash": HASH,
        "agreement_version": 1,
        "buyer_agent_review": {"status": "accepted"},
        "seller_decision": {"status": "accepted"},
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
    }


def agreement() -> dict:
    return {
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "shipping_cents": 3400,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "created_at": "2026-10-27T12:00:00Z",
        "agreement_hash": HASH,
    }


class Agreements:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.current = projection()

    async def create_agreement(self, run_id, request):
        self.calls.append(("create", run_id, request))
        return {
            "transaction_id": "vf_1",
            "state": "AWARDED",
            "agreement": agreement(),
            "agreement_version": 1,
            "agreement_hash": HASH,
            "seller_token_ref": "run:run-1:transaction:vf_1",
        }

    async def view(self, run_id):
        self.calls.append(("view", run_id))
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement": agreement(),
            "agreement_version": 1,
            "agreement_hash": HASH,
            "seller_token_ref": "run:run-1:transaction:vf_1",
            "projection": self.current,
        }

    async def approve_funding(self, run_id, decision):
        self.calls.append(("approve_funding", run_id, decision))
        return {
            "projection": projection("FUNDING_PENDING"),
            "checkout_url": "http://paypal.test/checkout/1",
            "expires_at": "2026-10-27T12:30:00Z",
        }

    async def release(self, run_id, decision):
        self.calls.append(("release", run_id, decision))
        return projection("PAYOUT_PENDING")

    async def receipt(self, run_id):
        self.calls.append(("receipt", run_id))
        return {"payload": {}, "signature": "sig", "kid": "k1", "verified": True}

    async def evidence(self, run_id, evidence_id):
        self.calls.append(("evidence", run_id, evidence_id))
        return b"manifest", "text/plain", "manifest.txt"


class Settings:
    verifund_agent_internal_token = "agent-internal"
    console_api_token = "console-token"
    internal_api_token = "internal-token"


class Store:
    async def get_projection(self, run_id):
        return projection()

    async def get_agreement(self, run_id):
        return agreement()


def build():
    services = SimpleNamespace(
        agreements=Agreements(),
        settings=Settings(),
        store=SimpleNamespace(settlement=Store()),
    )
    app = FastAPI()
    app.state.services = services
    app.state.settings = services.settings
    app.include_router(settlement_api.router)
    return app, services


@pytest.fixture
async def api():
    app, services = build()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://buyer") as http:
        yield http, services


async def test_internal_routes_require_the_agent_token(api):
    http, _ = api
    for path in (
        "/internal/runs/run-1/settlement",
        "/internal/runs/run-1/settlement/receipt",
    ):
        refused = await http.get(path)
        assert refused.status_code == 401
        wrong = await http.get(
            path, headers={"x-verifund-agent-token": "wrong"}
        )
        assert wrong.status_code == 401


async def test_agreement_route_rejects_a_run_mismatch(api):
    http, services = api
    body = {
        "award": {
            "run_id": "run-2",
            "buyer_id": "demo-buyer",
            "seller_id": "northwind-audio",
            "offer_id": "offer-1",
            "amount_cents": 123400,
            "shipping_cents": 3400,
            "quantity": 12,
            "line_items": [
                {
                    "sku": "NC-700",
                    "name": "Nimbus NC-700 ANC Headset",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                }
            ],
            "delivery_days": 7,
            "warranty_months": 24,
            "returns_days": 30,
        },
        "buyer_task_id": "buyer-task-1",
        "buyer_context_id": "run-1",
        "idempotency_key": "agreement:run-1:offer-1",
    }
    response = await http.post(
        "/internal/runs/run-1/settlement/agreement",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 403
    assert services.agreements.calls == []


async def test_agreement_route_returns_the_canonical_projection_without_a_token(api):
    http, services = api
    body = {
        "award": {
            "run_id": "run-1",
            "buyer_id": "demo-buyer",
            "seller_id": "northwind-audio",
            "offer_id": "offer-1",
            "amount_cents": 123400,
            "shipping_cents": 3400,
            "quantity": 12,
            "line_items": [
                {
                    "sku": "NC-700",
                    "name": "Nimbus NC-700 ANC Headset",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                }
            ],
            "delivery_days": 7,
            "warranty_months": 24,
            "returns_days": 30,
        },
        "buyer_task_id": "buyer-task-1",
        "buyer_context_id": "run-1",
        "idempotency_key": "agreement:run-1:offer-1",
    }
    response = await http.post(
        "/internal/runs/run-1/settlement/agreement",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 200, response.text
    dumped = response.json()
    assert dumped["seller_token_ref"] == "run:run-1:transaction:vf_1"
    assert "seller_token" not in dumped
    assert dumped["agreement"]["agreement_hash"] == HASH
    assert services.agreements.calls[0][0] == "create"


async def test_approve_funding_forwards_the_structured_decision(api):
    http, services = api
    body = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "approved": True,
        "approved_by": "demo-reviewer",
        "note": "approved",
        "decided_at": "2026-10-27T12:00:00Z",
        "idempotency_key": "fund:run-1:vf_1",
    }
    response = await http.post(
        "/internal/runs/run-1/settlement/approve-funding",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 200, response.text
    assert response.json()["checkout_url"].startswith("http://paypal.test/")
    call = services.agreements.calls[-1]
    assert call[0] == "approve_funding"
    assert call[2].approved is True


async def test_release_requires_an_override_note(api):
    http, _ = api
    body = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "approved": True,
        "released_by": "demo-reviewer",
        "note": "",
        "override": True,
        "decided_at": "2026-10-27T12:00:00Z",
        "idempotency_key": "release:run-1:vf_1",
    }
    response = await http.post(
        "/internal/runs/run-1/settlement/release",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 422


async def test_receipt_and_evidence_are_proxied(api):
    http, _ = api
    receipt = await http.get(
        "/internal/runs/run-1/settlement/receipt", headers=HEADERS
    )
    assert receipt.status_code == 200
    assert receipt.json()["verified"] is True

    evidence = await http.get(
        "/internal/runs/run-1/settlement/evidence/ev_1", headers=HEADERS
    )
    assert evidence.status_code == 200
    assert evidence.content == b"manifest"
    assert "manifest.txt" in evidence.headers["content-disposition"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_buyer_verifund_api.py -v`
Expected: FAIL with 404s and missing `verifund_agent_internal_token`.

- [ ] **Step 3: Add agreement storage and the internal token**

In `settlement_store.py`, add `Column("agreement", JSON, nullable=True)` to the
`run_settlement` table and include `agreement` in the insert/update values. Add:

```python
    async def save_agreement(self, run_id: str, agreement: dict[str, Any]) -> None:
        projection = await self.get_projection(run_id)
        if projection is None:
            raise ValueError(f"no settlement projection for {run_id}")
        await self.save_projection(run_id, {**projection, "agreement": agreement})

    async def get_agreement(self, run_id: str) -> dict[str, Any] | None:
        projection = await self.get_projection(run_id)
        return (projection or {}).get("agreement")
```

`save_projection` must preserve an existing `agreement` key when the incoming
projection does not carry one:

```python
    async def save_projection(
        self, run_id: str, projection: dict[str, Any]
    ) -> bool:
        previous = await self.get_projection(run_id)
        if previous and "agreement" in previous and "agreement" not in projection:
            projection = {**projection, "agreement": previous["agreement"]}
        ...
```

In `settings.py`, append:

```python
    verifund_agent_internal_token: str = Field(
        default="dev-verifund-agent-internal",
        validation_alias=AliasChoices("VERIFUND_AGENT_INTERNAL_TOKEN"),
    )
```

- [ ] **Step 4: Implement the buyer agreement service**

`apps/buyer_agent/buyer_agent/agreement_service.py`:

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from verifund_contracts import (
    AgreementProjection,
    ApproveRequest,
    BuyerAgreementRequest,
    BuyerAgreementResponse,
    CancelReason,
    CancelRequest,
    FundRequest,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
    ReleaseRequest,
)

from buyer_agent.settlement_client import BuyerSettlementClient
from buyer_agent.settlement_store import SettlementStore


class AgreementBindingError(Exception):
    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class BuyerAgreementService:
    def __init__(
        self,
        *,
        client: BuyerSettlementClient,
        store: SettlementStore,
        console_base_url: str,
    ) -> None:
        self.client = client
        self.store = store
        self.console_base_url = console_base_url.rstrip("/")

    async def create_agreement(
        self, run_id: str, request: BuyerAgreementRequest
    ) -> dict[str, Any]:
        award = request.award
        if award.run_id != run_id:
            raise AgreementBindingError("award does not belong to this run", status_code=403)
        response = await self.client.award(
            award, idempotency_key=request.idempotency_key
        )
        agreement = AgreementProjection.model_validate(response["agreement"])
        if agreement.run_id != run_id or agreement.transaction_id != response["transaction_id"]:
            raise AgreementBindingError("control plane returned a different run binding")
        await self.store.save_secret(
            run_id=run_id,
            transaction_id=agreement.transaction_id,
            seller_id=agreement.seller_id,
            purpose="settlement",
            token=response["seller_token"],
            expires_at=datetime.fromisoformat(
                response["expires_at"].replace("Z", "+00:00")
            ),
        )
        projection = await self.client.get_state(agreement.transaction_id)
        await self.store.save_projection(
            run_id, {**projection, "agreement": agreement.model_dump(mode="json")}
        )
        return BuyerAgreementResponse(
            transaction_id=agreement.transaction_id,
            state=projection["state"],
            agreement=agreement,
            agreement_version=agreement.agreement_version,
            agreement_hash=agreement.agreement_hash,
            seller_token_ref=f"run:{run_id}:transaction:{agreement.transaction_id}",
            seller_token_expires_at=datetime.fromisoformat(
                response["expires_at"].replace("Z", "+00:00")
            ),
        ).model_dump(mode="json")

    async def _binding(self, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        projection = await self.store.get_projection(run_id)
        agreement = await self.store.get_agreement(run_id)
        if projection is None or agreement is None:
            raise AgreementBindingError("settlement is not initialized", status_code=404)
        return projection, agreement

    @staticmethod
    def _require_binding(
        *,
        run_id: str,
        projection: dict[str, Any],
        transaction_id: str,
        agreement_version: int,
        agreement_hash: str,
    ) -> None:
        if str(projection.get("run_id")) != run_id:
            raise AgreementBindingError("run does not match the stored settlement", status_code=403)
        if str(projection.get("transaction_id")) != transaction_id:
            raise AgreementBindingError("transaction does not match", status_code=403)
        if int(projection.get("agreement_version") or 0) != agreement_version:
            raise AgreementBindingError("agreement version is stale", status_code=409)
        if str(projection.get("agreement_hash")) != agreement_hash:
            raise AgreementBindingError("agreement hash is stale", status_code=409)

    async def view(self, run_id: str) -> dict[str, Any]:
        projection, agreement = await self._binding(run_id)
        secret = await self.store.get_secret(run_id, projection["transaction_id"], "settlement")
        return {
            "run_id": run_id,
            "transaction_id": projection["transaction_id"],
            "agreement": agreement,
            "agreement_version": projection["agreement_version"],
            "agreement_hash": projection["agreement_hash"],
            "seller_token_ref": (
                f"run:{run_id}:transaction:{projection['transaction_id']}"
            ),
            "seller_token_expires_at": (secret or {}).get("expires_at"),
            "projection": projection,
        }

    async def approve_funding(
        self, run_id: str, decision: FundingApprovalDecision
    ) -> dict[str, Any]:
        projection, _ = await self._binding(run_id)
        self._require_binding(
            run_id=run_id,
            projection=projection,
            transaction_id=decision.transaction_id,
            agreement_version=decision.agreement_version,
            agreement_hash=decision.agreement_hash,
        )
        if not decision.approved:
            canceled = await self.client.cancel(
                decision.transaction_id,
                CancelRequest(reason_code=CancelReason.BUYER_REJECTED, note=decision.note),
                actor="buyer-agent",
            )
            await self.store.save_projection(run_id, canceled)
            return {"projection": canceled, "checkout_url": None, "expires_at": None}
        await self.client.approve(
            decision.transaction_id,
            approval_id=str(uuid.uuid4()),
            approved_by=decision.approved_by,
            approved_at=_iso(decision.decided_at),
            note=decision.note,
            agreement_hash=decision.agreement_hash,
        )
        funded = await self.client.fund(
            decision.transaction_id,
            FundRequest(
                agreement_hash=decision.agreement_hash,
                return_url=f"{self.console_base_url}/runs/{run_id}",
                cancel_url=f"{self.console_base_url}/runs/{run_id}",
            ),
            idempotency_key=f"{decision.idempotency_key}:fund",
        )
        refreshed = await self.client.get_state(decision.transaction_id)
        await self.store.save_projection(run_id, refreshed)
        return {
            "projection": refreshed,
            "checkout_url": funded["checkout_url"],
            "expires_at": funded["expires_at"],
        }

    async def release(
        self, run_id: str, decision: ReleaseApprovalDecision
    ) -> dict[str, Any]:
        projection, _ = await self._binding(run_id)
        self._require_binding(
            run_id=run_id,
            projection=projection,
            transaction_id=decision.transaction_id,
            agreement_version=decision.agreement_version,
            agreement_hash=decision.agreement_hash,
        )
        if not decision.approved:
            raise AgreementBindingError(
                "release rejection does not change control-plane state", status_code=409
            )
        result = await self.client.release(
            decision.transaction_id,
            ReleaseRequest(
                released_by=decision.released_by,
                note=decision.note,
                override=decision.override,
            ),
            actor="console:reviewer",
        )
        await self.store.save_projection(run_id, result)
        return result

    async def receipt(self, run_id: str) -> dict[str, Any]:
        projection, _ = await self._binding(run_id)
        return await self.client.get_receipt(
            projection["transaction_id"], actor="console:reviewer"
        )

    async def evidence(
        self, run_id: str, evidence_id: str
    ) -> tuple[bytes, str, str]:
        projection, _ = await self._binding(run_id)
        return await self.client.get_evidence(
            projection["transaction_id"],
            evidence_id,
            actor="console:reviewer",
        )
```

In `services.py`, build `BuyerAgreementService` next to `BuyerSettlementClient`
and expose it as `services.agreements`. In `server.py`, no router change is
needed because `settlement_api.router` is already included.

- [ ] **Step 5: Add the internal routes**

Append to `settlement_api.py`:

```python
from verifund_contracts import (
    BuyerAgreementRequest,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
)

from buyer_agent.agreement_service import AgreementBindingError


def verifund_agent_authorized(request: Request) -> bool:
    expected = request.app.state.settings.verifund_agent_internal_token
    provided = request.headers.get("x-verifund-agent-token", "")
    return bool(expected) and secrets.compare_digest(provided, expected)


def _require_verifund_agent(request: Request) -> None:
    if not verifund_agent_authorized(request):
        raise HTTPException(status_code=401, detail="unauthorized")


def _agreements(request: Request):
    value = getattr(_services(request), "agreements", None)
    if value is None:
        raise HTTPException(status_code=503, detail="agreement service unavailable")
    return value


def _binding_error(exc: AgreementBindingError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": "binding_mismatch", "message": str(exc)},
    )


@router.get("/internal/runs/{run_id}/settlement")
async def internal_get_settlement(run_id: str, request: Request) -> dict[str, Any]:
    _require_verifund_agent(request)
    try:
        return await _agreements(request).view(run_id)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/agreement")
async def internal_create_agreement(
    run_id: str, body: BuyerAgreementRequest, request: Request
) -> dict[str, Any]:
    _require_verifund_agent(request)
    if body.award.run_id != run_id:
        raise HTTPException(status_code=403, detail="run does not match the award")
    try:
        return await _agreements(request).create_agreement(run_id, body)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/approve-funding")
async def internal_approve_funding(
    run_id: str, body: FundingApprovalDecision, request: Request
) -> dict[str, Any]:
    _require_verifund_agent(request)
    if body.run_id != run_id:
        raise HTTPException(status_code=403, detail="run does not match the decision")
    try:
        return await _agreements(request).approve_funding(run_id, body)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/release")
async def internal_release(
    run_id: str, body: ReleaseApprovalDecision, request: Request
) -> dict[str, Any]:
    _require_verifund_agent(request)
    if body.run_id != run_id:
        raise HTTPException(status_code=403, detail="run does not match the decision")
    try:
        return await _agreements(request).release(run_id, body)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.get("/internal/runs/{run_id}/settlement/receipt")
async def internal_receipt(run_id: str, request: Request) -> dict[str, Any]:
    _require_verifund_agent(request)
    try:
        return await _agreements(request).receipt(run_id)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.get("/internal/runs/{run_id}/settlement/evidence/{evidence_id}")
async def internal_evidence(
    run_id: str, evidence_id: str, request: Request
) -> Response:
    _require_verifund_agent(request)
    try:
        content, media_type, filename = await _agreements(request).evidence(
            run_id, evidence_id
        )
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 6: Run the internal-route tests**

Run: `uv run pytest tests/integration/test_buyer_verifund_api.py tests/integration/test_buyer_settlement_api.py -v`
Expected: PASS. Verify no route in this module returns `seller_token` or `ops_token`.

- [ ] **Step 7: Run the buyer suite**

Run: `uv run pytest tests/unit tests/integration -k "buyer or settlement" -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/buyer_agent/buyer_agent/{agreement_service.py,settlement_api.py,settlement_store.py,settings.py,services.py,server.py} tests/integration/test_buyer_verifund_api.py
git commit -m "feat(buyer): expose authenticated internal routes for the Verifund agent"
```

---

### Task 18: Orchestrator settlement secret resolution, token injection, and redaction

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/settings.py`
- Modify: `apps/orchestrator_agent/orchestrator_agent/mediation.py`
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py`
- Test: `tests/unit/test_orchestrator_settlement.py`

**Interfaces:**
- Produces: `_resolve_settlement_token(settings, ref)`, `_inject_settlement_token(envelope, token)`, `_redact_settlement(value, token=None)`; `mediate_seller_call(..., settlement_secret_ref=None, buyer_internal_url=None, buyer_internal_token=None, buyer_internal_timeout_seconds=10.0)`.
- Consumes: buyer `POST /internal/settlement/seller-token`, `x-marketmesh-internal-token`, `AcceptOffer.settlement_token`, `PurchaseOrderRequest.settlement_token`.

- [ ] **Step 1: Write the failing orchestrator settlement tests**

`tests/unit/test_orchestrator_settlement.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_orchestrator_settlement.py -v`
Expected: FAIL with missing mediation helpers and unknown keyword `settlement_secret_ref`.

- [ ] **Step 3: Add the orchestrator settings**

Append to `apps/orchestrator_agent/orchestrator_agent/settings.py`:

```python
    buyer_internal_url: str = Field(
        default="http://127.0.0.1:9100",
        validation_alias=AliasChoices("BUYER_INTERNAL_URL"),
    )
    buyer_internal_token: str = Field(
        default="dev-buyer-internal",
        validation_alias=AliasChoices("BUYER_INTERNAL_TOKEN"),
    )
    buyer_internal_timeout_seconds: float = Field(
        default=10.0,
        validation_alias=AliasChoices("BUYER_INTERNAL_TIMEOUT_SECONDS"),
    )
```

- [ ] **Step 4: Implement token resolution, injection, and redaction**

In `mediation.py`, add imports:

```python
from copy import deepcopy
```

Add constants and helpers before `mediate_seller_call`:

```python
SETTLEMENT_TOKEN_KEYS = {
    "settlement_token",
    "seller_token",
    "authorization",
    "x-marketmesh-internal-token",
}


def _redact_settlement(value: Any, token: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if key.lower() in SETTLEMENT_TOKEN_KEYS
                else _redact_settlement(item, token)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_settlement(item, token) for item in value]
    if token and isinstance(value, str) and token in value:
        return value.replace(token, "[REDACTED]")
    return value


def _inject_settlement_token(
    envelope: dict[str, Any], token: str
) -> dict[str, Any]:
    injected = deepcopy(envelope)
    payload = injected.get("payload")
    if isinstance(payload, dict):
        payload["settlement_token"] = token
    else:
        injected["settlement_token"] = token
    return injected


async def _resolve_settlement_token(
    buyer_internal_url: str,
    buyer_internal_token: str,
    ref: dict[str, Any],
    *,
    timeout_seconds: float = 10.0,
) -> str:
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{buyer_internal_url.rstrip('/')}/internal/settlement/seller-token",
            headers={"x-marketmesh-internal-token": buyer_internal_token},
            json=ref,
        )
        response.raise_for_status()
        token = response.json().get("seller_token")
    if not isinstance(token, str) or not token:
        raise ValueError("buyer returned no seller token")
    return token
```

- [ ] **Step 5: Wire settlement resolution into `mediate_seller_call`**

Change the signature:

```python
async def mediate_seller_call(
    buyer_task_id: str,
    seller_card_url: str,
    buyer_a2a_url: str,
    seller_request: dict[str, Any] | None = None,
    seller_token: str | None = None,
    seller_id: str | None = None,
    seller_task_id: str | None = None,
    seller_context_id: str | None = None,
    settlement_secret_ref: dict[str, Any] | None = None,
    buyer_internal_url: str | None = None,
    buyer_internal_token: str | None = None,
    buyer_internal_timeout_seconds: float = 10.0,
) -> dict[str, Any]:
```

Inside the `try`, after `request_envelope = seller_request or {}`:

```python
        resolved_token: str | None = None
        if settlement_secret_ref:
            if not buyer_internal_url or not buyer_internal_token:
                raise ValueError(
                    "buyer internal settlement endpoint is not configured"
                )
            resolved_token = await _resolve_settlement_token(
                buyer_internal_url,
                buyer_internal_token,
                settlement_secret_ref,
                timeout_seconds=buyer_internal_timeout_seconds,
            )
            request_envelope = _inject_settlement_token(
                request_envelope, resolved_token
            )
```

Before returning, replace the `seller_communication` value with a redacted copy:

```python
        return {
            "resumed": True,
            "seller_result": _redact_settlement(seller_result, resolved_token),
            "buyer_response": _redact_settlement(buyer_response, resolved_token),
            "seller_communication": {
                "seller_id": seller_id,
                "seller_card_url": seller_card_url,
                "request": _redact_settlement(request_envelope, resolved_token),
                "response": _redact_settlement(seller_result, resolved_token),
            },
        }
```

In the `except`, keep the error message generic and never include the token:

```python
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: seller mediation failed"}
```

- [ ] **Step 6: Pass the secret reference through the orchestrator tool**

In `agent.py`, add the parameter to the tool:

```python
        settlement_secret_ref: dict | None = None,
```

Pass it to `_mediate_seller_call`:

```python
            settlement_secret_ref=settlement_secret_ref,
            buyer_internal_url=settings.buyer_internal_url,
            buyer_internal_token=settings.buyer_internal_token,
            buyer_internal_timeout_seconds=settings.buyer_internal_timeout_seconds,
```

Add to the instruction's mediation mapping list:

```text
- settlement_secret_ref = settlement_secret_ref, when present
```

Add this rule after the mapping list:

```text
Never log, repeat, or expose a seller token. Pass
settlement_secret_ref unchanged; the tool resolves the token
internally and returns only redacted data.
```

- [ ] **Step 7: Run the orchestrator settlement tests**

Run: `uv run pytest tests/unit/test_orchestrator_settlement.py -v`
Expected: PASS.

- [ ] **Step 8: Run the orchestrator suite**

Run: `uv run pytest tests/unit tests/integration -k orchestrator -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/{settings.py,mediation.py,agent.py} tests/unit/test_orchestrator_settlement.py
git commit -m "feat(orchestrator): resolve settlement seller tokens and redact them"
```

---

## Phase 3 — Seller integration

### Task 19: Seller settlement client, evidence payloads, and settings

**Files:**
- Modify: `apps/seller_agent/seller_agent/settings.py`
- Create: `apps/seller_agent/seller_agent/settlement.py`
- Test: `tests/unit/test_seller_settlement.py`

**Interfaces:**
- Produces: `SellerSettlementClient` (`get_transaction`, `upload_evidence`, `get_evidence`, `close`), `SettlementError`, `build_shipment_manifest`, `build_delivery_confirmation`, `encode_payload`.
- Consumes: control-plane seller API from Task 10.

- [ ] **Step 1: Write the failing seller settlement tests**

`tests/unit/test_seller_settlement.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx

from commerce_core.contracts import Fulfillment, OfferLineItem, Order, OrderStatus
from seller_agent.settlement import (
    SellerSettlementClient,
    build_delivery_confirmation,
    build_shipment_manifest,
    encode_payload,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def order() -> Order:
    return Order(
        order_id="MM-DEMO",
        offer_id="offer-1",
        seller_id="northwind-audio",
        status=OrderStatus.CONFIRMED,
        quantity=2,
        total_cents=20000,
        line_items=[
            OfferLineItem(
                sku="NC-700",
                name="Nimbus NC-700",
                quantity=2,
                unit_price_cents=10000,
                list_unit_price_cents=12000,
                warranty_addon_cents=0,
                attributes={},
            )
        ],
        reserved_at=NOW,
        eta=NOW,
        tracking_number="TRK-1",
        fulfillment=Fulfillment(carrier="Northwind Logistics", status="reserved"),
    )


@respx.mock
async def test_get_transaction_uses_the_seller_bearer_token():
    route = respx.get(
        "http://control/seller/transactions/vf_1"
    ).mock(return_value=httpx.Response(200, json={"state": "AWARDED"}))
    client = SellerSettlementClient("http://control")
    projection = await client.get_transaction("v1.secret", "vf_1")
    assert projection["state"] == "AWARDED"
    assert route.calls[0].request.headers["authorization"] == "Bearer v1.secret"
    await client.close()


@respx.mock
async def test_upload_evidence_posts_multipart_without_leaking_the_token():
    route = respx.post(
        "http://control/seller/transactions/vf_1/evidence"
    ).mock(return_value=httpx.Response(201, json={"evidence_id": "ev_1"}))
    client = SellerSettlementClient("http://control")
    response = await client.upload_evidence(
        "v1.secret",
        "vf_1",
        kind="shipment_manifest",
        content=b'{"tracking_number":"TRK-1"}',
        media_type="application/json",
        filename="manifest.json",
        note="auto",
    )
    assert response["evidence_id"] == "ev_1"
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer v1.secret"
    assert b'name="kind"' in request.content
    assert b"shipment_manifest" in request.content
    assert b"TRK-1" in request.content
    await client.close()


def test_shipment_manifest_matches_the_order_and_agreement():
    payload = build_shipment_manifest(
        order(),
        transaction_id="vf_1",
        agreement_hash="a" * 64,
        now=NOW,
    )
    assert payload["tracking_number"] == "TRK-1"
    assert payload["carrier"] == "Northwind Logistics"
    assert payload["seller_id"] == "northwind-audio"
    assert payload["agreement_hash"] == "a" * 64
    assert payload["line_items"] == [{"sku": "NC-700", "quantity": 2}]
    assert payload["shipped_at"] < NOW.isoformat()


def test_delivery_confirmation_is_in_the_past_and_encodes_stably():
    payload = build_delivery_confirmation(
        order(), transaction_id="vf_1", now=NOW
    )
    assert payload["delivered_at"] < NOW.isoformat()
    assert payload["recipient"] == "Demo Buyer"
    encoded = encode_payload(payload)
    assert encoded == encode_payload(dict(reversed(list(payload.items()))))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_seller_settlement.py -v`
Expected: FAIL with `ModuleNotFoundError: seller_agent.settlement`.

- [ ] **Step 3: Add the seller settings**

Append to `apps/seller_agent/seller_agent/settings.py`:

```python
    verifund_mode: Literal["off", "fake", "sandbox"] = Field(
        default="off",
        validation_alias=AliasChoices("VERIFUND_MODE"),
    )
    verifund_url: str = Field(
        default="http://127.0.0.1:9300",
        validation_alias=AliasChoices("VERIFUND_URL", "SELLER_VERIFUND_URL"),
    )
    verifund_timeout_seconds: float = Field(
        default=20.0,
        validation_alias=AliasChoices("VERIFUND_TIMEOUT_SECONDS"),
    )
    verifund_auto_evidence: bool = Field(
        default=True,
        validation_alias=AliasChoices("VERIFUND_AUTO_EVIDENCE"),
    )
    verifund_evidence_retry_seconds: float = Field(
        default=2.0,
        validation_alias=AliasChoices("VERIFUND_EVIDENCE_RETRY_SECONDS"),
    )
```

- [ ] **Step 4: Implement the seller settlement client and evidence builders**

`apps/seller_agent/seller_agent/settlement.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from commerce_core.contracts import Order


class SettlementError(Exception):
    def __init__(
        self, code: str, message: str, *, status_code: int = 0
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_shipment_manifest(
    order: Order,
    *,
    transaction_id: str,
    agreement_hash: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    return {
        "transaction_id": transaction_id,
        "seller_id": order.seller_id,
        "agreement_hash": agreement_hash,
        "tracking_number": order.tracking_number,
        "carrier": order.fulfillment.carrier,
        "shipped_at": _iso(now - timedelta(hours=2)),
        "line_items": [
            {"sku": item.sku, "quantity": item.quantity}
            for item in order.line_items
        ],
    }


def build_delivery_confirmation(
    order: Order,
    *,
    transaction_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    return {
        "transaction_id": transaction_id,
        "tracking_number": order.tracking_number,
        "delivered_at": _iso(now - timedelta(hours=1)),
        "recipient": "Demo Buyer",
    }


def encode_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class SellerSettlementClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self, token: str) -> dict[str, str]:
        return {"authorization": f"Bearer {token}"}

    async def get_transaction(
        self, token: str, transaction_id: str
    ) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}",
            headers=self._headers(token),
        )
        if response.status_code >= 400:
            raise SettlementError(
                "unauthorized" if response.status_code == 401 else "invalid_request",
                "seller transaction lookup failed",
                status_code=response.status_code,
            )
        return response.json()

    async def upload_evidence(
        self,
        token: str,
        transaction_id: str,
        *,
        kind: str,
        content: bytes,
        media_type: str,
        filename: str,
        note: str = "",
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        data = {"kind": kind}
        if note:
            data["note"] = note
        if captured_at:
            data["captured_at"] = captured_at
        response = await self._client.post(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence",
            headers=self._headers(token),
            data=data,
            files={"file": (filename, content, media_type)},
        )
        if response.status_code >= 400:
            raise SettlementError(
                "invalid_request",
                "evidence upload failed",
                status_code=response.status_code,
            )
        return response.json()

    async def get_evidence(
        self, token: str, transaction_id: str, evidence_id: str
    ) -> tuple[bytes, str]:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence/{evidence_id}",
            headers=self._headers(token),
        )
        if response.status_code >= 400:
            raise SettlementError(
                "not_found",
                "evidence not found",
                status_code=response.status_code,
            )
        return response.content, response.headers.get(
            "content-type", "application/octet-stream"
        )
```

- [ ] **Step 5: Run the seller settlement tests**

Run: `uv run pytest tests/unit/test_seller_settlement.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/seller_agent/seller_agent/{settings.py,settlement.py} tests/unit/test_seller_settlement.py
git commit -m "feat(seller): add control-plane settlement client and evidence payloads"
```

---

### Task 20: Seller settlement-token store and retrying evidence outbox

**Files:**
- Modify: `apps/seller_agent/seller_agent/store.py`
- Create: `apps/seller_agent/seller_agent/evidence_outbox.py`
- Test: `tests/unit/test_seller_evidence_outbox.py`

**Interfaces:**
- Produces: `SellerStore.save_settlement_token(transaction_id, seller_id, token)`, `get_settlement_token(transaction_id) -> str | None`, `enqueue_evidence(...) -> bool`, `list_due_evidence(now, limit)`, `mark_evidence_sent(evidence_key, sent_at)`, `reschedule_evidence(evidence_key, next_attempt_at, error)`, `fail_evidence(evidence_key, error)`, `get_evidence_outbox(transaction_id, kind)`; `EvidenceOutbox(store, client, retry_seconds=2.0, batch_size=20)`, `enqueue(...)`, `run_once(now=None)`, `start()`, `stop()`.
- Consumes: `SellerSettlementClient.upload_evidence`, `SettlementError`.

- [ ] **Step 1: Write the failing outbox tests**

`tests/unit/test_seller_evidence_outbox.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.evidence_outbox import EvidenceOutbox
from seller_agent.settlement import SellerSettlementClient
from seller_agent.store import SellerStore

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
URL = "http://control/seller/transactions/vf_1/evidence"


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}"
    )
    value = SellerStore(engine)
    await value.create_schema()
    yield value
    await engine.dispose()


async def enqueue(outbox: EvidenceOutbox) -> bool:
    return await outbox.enqueue(
        transaction_id="vf_1",
        seller_id="northwind-audio",
        kind="shipment_manifest",
        content=b'{"tracking_number":"TRK-1"}',
        media_type="application/json",
        filename="manifest.json",
        note="auto",
        captured_at="2026-10-27T10:00:00Z",
        created_at=NOW,
    )


async def test_settlement_token_round_trips_and_replaces(store):
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.a")
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.b")
    assert await store.get_settlement_token("vf_1") == "v1.b"
    assert await store.get_settlement_token("vf_2") is None


async def test_enqueue_is_idempotent_per_transaction_and_kind(store):
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True
    assert await enqueue(outbox) is False
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    await client.close()


@respx.mock
async def test_run_once_uploads_due_evidence_and_marks_it_sent(store):
    route = respx.post(URL).mock(
        return_value=httpx.Response(201, json={"evidence_id": "ev_1"})
    )
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.secret")
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True

    result = await outbox.run_once(now=NOW)

    assert result == {"sent": 1, "retried": 0, "failed": 0}
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer v1.secret"
    assert b'name="kind"' in request.content
    assert b"shipment_manifest" in request.content
    assert b"TRK-1" in request.content
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "sent"
    assert row["sent_at"] == "2026-10-27T12:00:00Z"
    await client.close()


@respx.mock
async def test_run_once_backs_off_after_a_transient_failure(store):
    route = respx.post(URL).mock(return_value=httpx.Response(503))
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.secret")
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True

    first = await outbox.run_once(now=NOW)

    assert first == {"sent": 0, "retried": 1, "failed": 0}
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["next_attempt_at"] == "2026-10-27T12:00:02Z"
    assert row["last_error"]

    route.mock(return_value=httpx.Response(201, json={"evidence_id": "ev_1"}))
    second = await outbox.run_once(now=NOW + timedelta(seconds=3))
    assert second == {"sent": 1, "retried": 0, "failed": 0}
    await client.close()


@respx.mock
async def test_run_once_marks_permanent_failures(store):
    respx.post(URL).mock(return_value=httpx.Response(422))
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.secret")
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True

    result = await outbox.run_once(now=NOW)

    assert result == {"sent": 0, "retried": 0, "failed": 1}
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "failed"
    assert row["attempts"] == 1
    assert "evidence upload failed" in row["last_error"]
    await client.close()


async def test_run_once_waits_when_no_seller_token_is_stored(store):
    client = SellerSettlementClient("http://control")
    outbox = EvidenceOutbox(store, client, retry_seconds=2.0)
    assert await enqueue(outbox) is True

    result = await outbox.run_once(now=NOW)

    assert result == {"sent": 0, "retried": 1, "failed": 0}
    row = await store.get_evidence_outbox("vf_1", "shipment_manifest")
    assert row["status"] == "pending"
    assert row["last_error"] == "seller token unavailable"
    assert row["next_attempt_at"] == "2026-10-27T12:00:02Z"
    await client.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_seller_evidence_outbox.py -v`
Expected: FAIL with `ModuleNotFoundError: seller_agent.evidence_outbox` and missing store methods.

- [ ] **Step 3: Add the two SQLite tables and store methods**

In `store.py`, extend the imports:

```python
from sqlalchemy import (
    JSON,
    Column,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    select,
)
```

Add a module-level helper:

```python
def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
```

Register the tables after `self.orders`:

```python
        self.settlement_tokens = Table(
            "settlement_tokens",
            self.metadata,
            Column("transaction_id", String, primary_key=True),
            Column("seller_id", String, nullable=False),
            Column("token", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.evidence_outbox = Table(
            "evidence_outbox",
            self.metadata,
            Column("evidence_key", String, primary_key=True),
            Column("transaction_id", String, nullable=False),
            Column("seller_id", String, nullable=False),
            Column("kind", String, nullable=False),
            Column("filename", String, nullable=False),
            Column("media_type", String, nullable=False),
            Column("content", LargeBinary, nullable=False),
            Column("note", String, nullable=False, default=""),
            Column("captured_at", String, nullable=True),
            Column("status", String, nullable=False, default="pending"),
            Column("attempts", Integer, nullable=False, default=0),
            Column("next_attempt_at", String, nullable=False),
            Column("last_error", String, nullable=True),
            Column("created_at", String, nullable=False),
            Column("sent_at", String, nullable=True),
            UniqueConstraint(
                "transaction_id",
                "kind",
                name="uq_evidence_outbox_transaction_kind",
            ),
        )
```

Append the store methods:

```python
    async def save_settlement_token(
        self, transaction_id: str, seller_id: str, token: str
    ) -> None:
        statement = sqlite_insert(self.settlement_tokens).values(
            transaction_id=transaction_id,
            seller_id=seller_id,
            token=token,
            updated_at=_iso(datetime.now(UTC)),
        )
        statement = statement.on_conflict_do_update(
            index_elements=["transaction_id"],
            set_={
                "seller_id": seller_id,
                "token": token,
                "updated_at": _iso(datetime.now(UTC)),
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def get_settlement_token(
        self, transaction_id: str
    ) -> str | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.settlement_tokens.c.token).where(
                    self.settlement_tokens.c.transaction_id
                    == transaction_id
                )
            )
            row = result.first()
            return row.token if row else None

    async def enqueue_evidence(
        self,
        *,
        transaction_id: str,
        seller_id: str,
        kind: str,
        content: bytes,
        media_type: str,
        filename: str,
        note: str = "",
        captured_at: str | None = None,
        created_at: datetime | None = None,
    ) -> bool:
        created = _iso(created_at or datetime.now(UTC))
        statement = (
            sqlite_insert(self.evidence_outbox)
            .values(
                evidence_key=uuid.uuid4().hex,
                transaction_id=transaction_id,
                seller_id=seller_id,
                kind=kind,
                filename=filename,
                media_type=media_type,
                content=content,
                note=note,
                captured_at=captured_at,
                status="pending",
                attempts=0,
                next_attempt_at=created,
                last_error=None,
                created_at=created,
                sent_at=None,
            )
            .on_conflict_do_nothing(
                index_elements=["transaction_id", "kind"]
            )
        )
        async with self.engine.begin() as conn:
            result = await conn.execute(statement)
        return bool(result.rowcount)

    async def list_due_evidence(
        self, *, now: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.evidence_outbox)
                .where(
                    self.evidence_outbox.c.status == "pending",
                    self.evidence_outbox.c.next_attempt_at <= now,
                )
                .order_by(self.evidence_outbox.c.created_at)
                .limit(max(1, min(limit, 100)))
            )
            return [dict(row._mapping) for row in result]

    async def mark_evidence_sent(
        self, evidence_key: str, *, sent_at: str
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.evidence_outbox.update()
                .where(self.evidence_outbox.c.evidence_key == evidence_key)
                .values(status="sent", sent_at=sent_at, last_error=None)
            )

    async def reschedule_evidence(
        self,
        evidence_key: str,
        *,
        next_attempt_at: str,
        error: str,
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.evidence_outbox.update()
                .where(self.evidence_outbox.c.evidence_key == evidence_key)
                .values(
                    attempts=self.evidence_outbox.c.attempts + 1,
                    next_attempt_at=next_attempt_at,
                    last_error=error,
                )
            )

    async def fail_evidence(
        self, evidence_key: str, *, error: str
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.evidence_outbox.update()
                .where(self.evidence_outbox.c.evidence_key == evidence_key)
                .values(
                    status="failed",
                    attempts=self.evidence_outbox.c.attempts + 1,
                    last_error=error,
                )
            )

    async def get_evidence_outbox(
        self, transaction_id: str, kind: str
    ) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.evidence_outbox).where(
                    self.evidence_outbox.c.transaction_id
                    == transaction_id,
                    self.evidence_outbox.c.kind == kind,
                )
            )
            row = result.first()
            return dict(row._mapping) if row else None
```

Add `import uuid` at the top of `store.py`.

- [ ] **Step 4: Implement the outbox worker**

`apps/seller_agent/seller_agent/evidence_outbox.py`:

```python
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import httpx

from seller_agent.settlement import SellerSettlementClient, SettlementError
from seller_agent.store import SellerStore

logger = logging.getLogger(__name__)
RETRYABLE_STATUS = {408, 429}
MAX_BACKOFF_SECONDS = 60.0


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class EvidenceOutbox:
    def __init__(
        self,
        store: SellerStore,
        client: SellerSettlementClient,
        *,
        retry_seconds: float = 2.0,
        batch_size: int = 20,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.client = client
        self.retry_seconds = retry_seconds
        self.batch_size = batch_size
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def enqueue(
        self,
        *,
        transaction_id: str,
        seller_id: str,
        kind: str,
        content: bytes,
        media_type: str,
        filename: str,
        note: str = "",
        captured_at: str | None = None,
        created_at: datetime | None = None,
    ) -> bool:
        return await self.store.enqueue_evidence(
            transaction_id=transaction_id,
            seller_id=seller_id,
            kind=kind,
            content=content,
            media_type=media_type,
            filename=filename,
            note=note,
            captured_at=captured_at,
            created_at=created_at,
        )

    async def run_once(
        self, *, now: datetime | None = None
    ) -> dict[str, int]:
        current = now or self._clock()
        rows = await self.store.list_due_evidence(
            now=_iso(current), limit=self.batch_size
        )
        counts = {"sent": 0, "retried": 0, "failed": 0}
        for row in rows:
            token = await self.store.get_settlement_token(
                row["transaction_id"]
            )
            if not token:
                await self.store.reschedule_evidence(
                    row["evidence_key"],
                    next_attempt_at=_iso(
                        current + timedelta(seconds=self.retry_seconds)
                    ),
                    error="seller token unavailable",
                )
                counts["retried"] += 1
                continue
            try:
                await self.client.upload_evidence(
                    token,
                    row["transaction_id"],
                    kind=row["kind"],
                    content=row["content"],
                    media_type=row["media_type"],
                    filename=row["filename"],
                    note=row["note"],
                    captured_at=row["captured_at"],
                )
            except SettlementError as exc:
                if (
                    exc.status_code in RETRYABLE_STATUS
                    or exc.status_code >= 500
                ):
                    await self._retry(row, current, f"{exc.code}: {exc.message}")
                    counts["retried"] += 1
                else:
                    await self.store.fail_evidence(
                        row["evidence_key"],
                        error=f"{exc.code}: {exc.message}",
                    )
                    counts["failed"] += 1
                continue
            except httpx.HTTPError as exc:
                await self._retry(row, current, type(exc).__name__)
                counts["retried"] += 1
                continue
            await self.store.mark_evidence_sent(
                row["evidence_key"], sent_at=_iso(current)
            )
            counts["sent"] += 1
        return counts

    async def _retry(
        self, row: dict[str, Any], current: datetime, error: str
    ) -> None:
        attempt = int(row["attempts"]) + 1
        delay = min(
            self.retry_seconds * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS
        )
        await self.store.reschedule_evidence(
            row["evidence_key"],
            next_attempt_at=_iso(current + timedelta(seconds=delay)),
            error=error,
        )

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._loop(), name="seller-evidence-outbox"
        )

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("seller evidence outbox sweep failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.retry_seconds
                )
            except TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
```

- [ ] **Step 5: Run the outbox tests**

Run: `uv run pytest tests/unit/test_seller_evidence_outbox.py -v`
Expected: PASS.

- [ ] **Step 6: Run the seller tests**

Run: `uv run pytest tests/unit tests/integration -k seller -v`
Expected: PASS; the new tables are additive and `create_schema` still works on an existing seller database.

- [ ] **Step 7: Commit**

```bash
git add apps/seller_agent/seller_agent/{store.py,evidence_outbox.py} tests/unit/test_seller_evidence_outbox.py
git commit -m "feat(seller): persist settlement tokens and retry evidence uploads"
```

---

### Task 21: Seller acceptance and order settlement validation

**Files:**
- Modify: `apps/seller_agent/seller_agent/service.py`
- Modify: `apps/seller_agent/seller_agent/graph.py`
- Modify: `apps/seller_agent/seller_agent/order_service.py`
- Modify: `apps/seller_agent/seller_agent/executor.py`
- Test: `tests/unit/test_seller_settlement_validation.py`

**Interfaces:**
- Produces: `SellerService(..., settlement=None, settlement_enabled=False)`, `validate_acceptance(accepted, *, token)`, `validate_purchase_order(po, *, token)`, `strip_settlement_token(envelope)`, `settlement_token_from(envelope)`, `SellerService.redact_message(message)`, `OrderService.create_order(po, *, settlement_validator=None)`.
- Consumes: `SellerSettlementClient.get_transaction`, `SellerStore.save_settlement_token`, `AcceptOffer`/`PurchaseOrderRequest` settlement fields from Task 2.

- [ ] **Step 1: Write the failing seller validation tests**

`tests/unit/test_seller_settlement_validation.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from a2a.types.a2a_pb2 import Role
from commerce_core.a2a_parts import first_envelope, make_message
from commerce_core.contracts import (
    AcceptOffer,
    ApprovalReceipt,
    Offer,
    OfferLineItem,
    OfferStatus,
    PurchaseOrderRequest,
    ShippingAddress,
)
from commerce_core.extension import wrap_payload
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.graph import CommerceProtocolError, accept_offer
from seller_agent.order_service import OrderError, OrderService
from seller_agent.planner import ScriptedSellerPlanner
from seller_agent.service import (
    SellerService,
    settlement_token_from,
    strip_settlement_token,
)
from seller_agent.store import SellerStore

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64
TOKEN = "v1.secret"


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}"
    )
    value = SellerStore(engine)
    await value.create_schema()
    yield value
    await engine.dispose()


class FakeSettlement:
    def __init__(self, projection: dict) -> None:
        self.projection = projection
        self.calls: list[tuple[str, str]] = []

    async def get_transaction(self, token, transaction_id):
        self.calls.append((token, transaction_id))
        return dict(self.projection)


def projection(**overrides):
    value = {
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "state": "AWARDED",
        "seller_id": "northwind-audio",
        "amount_cents": 120000,
        "currency": "USD",
        "agreement_hash": HASH,
        "agreement_version": 1,
        "quantity": 12,
        "line_items": [],
        "delivery_days": 5,
        "warranty_months": 24,
        "returns_days": 30,
        "purchase_order": None,
        "evidence": None,
        "deadlines": {"evidence": None, "inspection": None},
        "allowed_actions": [],
        "updated_at": NOW.isoformat(),
    }
    value.update(overrides)
    return value


def accept() -> AcceptOffer:
    return AcceptOffer(
        offer_id="offer-1",
        round=1,
        accepted_total_cents=120000,
        settlement_transaction_id="vf_1",
        agreement_hash=HASH,
        settlement_token=TOKEN,
    )


def offer() -> Offer:
    return Offer(
        offer_id="offer-1",
        request_id="rfq-1",
        seller_id="northwind-audio",
        seller_name="Northwind Audio",
        seller_rating=4.8,
        line_items=[
            OfferLineItem(
                sku="NC-700",
                name="Nimbus NC-700",
                quantity=12,
                unit_price_cents=10000,
                list_unit_price_cents=12000,
            )
        ],
        subtotal_cents=120000,
        total_cents=120000,
        delivery_days=5,
        warranty_months=24,
        returns_days=30,
        valid_until=NOW + timedelta(days=7),
        status=OfferStatus.FINAL,
    )


def purchase_order() -> PurchaseOrderRequest:
    return PurchaseOrderRequest(
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
        expected_total_cents=120000,
        settlement_transaction_id="vf_1",
        agreement_hash=HASH,
        settlement_token=TOKEN,
    )


def build(store, policy, projection_value=None):
    client = FakeSettlement(projection_value or projection())
    service = SellerService(
        store=store,
        policy=policy,
        planner=ScriptedSellerPlanner(),
        settlement=client,
        settlement_enabled=True,
    )
    return service, client


async def test_handle_turn_keeps_the_token_out_of_graph_state(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy)
    captured: dict = {}

    class Graph:
        async def ainvoke(self, state, config):
            captured["state"] = state
            captured["config"] = config
            return {
                "error": {
                    "code": "invalid_request",
                    "message": "stop",
                    "retryable": False,
                    "details": {},
                }
            }

    service.graph = Graph()
    message = make_message(
        role=Role.ROLE_USER,
        text="Accept the award.",
        context_id="ctx-1",
        envelope=wrap_payload("accept_offer", accept()),
    )

    await service.handle_turn("task-1", "ctx-1", message)

    assert "settlement_token" not in captured["state"]["incoming"]["payload"]
    assert captured["state"]["incoming"]["payload"]["agreement_hash"] == HASH
    assert (
        captured["config"]["configurable"]["settlement_token"] == TOKEN
    )


async def test_redact_message_removes_the_token_from_a2a_history(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy)
    message = make_message(
        role=Role.ROLE_USER,
        text="Accept the award.",
        context_id="ctx-1",
        envelope=wrap_payload("accept_offer", accept()),
    )

    redacted = service.redact_message(message)

    assert settlement_token_from(first_envelope(message)) == TOKEN
    assert settlement_token_from(first_envelope(redacted)) is None
    assert first_envelope(redacted)["payload"]["agreement_hash"] == HASH


def test_strip_settlement_token_does_not_mutate_the_source():
    envelope = wrap_payload("accept_offer", accept())
    cleaned = strip_settlement_token(envelope)
    assert "settlement_token" not in cleaned["payload"]
    assert envelope["payload"]["settlement_token"] == TOKEN


async def test_validate_acceptance_binds_the_agreement_and_stores_the_token(
    store, northwind_policy
):
    service, client = build(store, northwind_policy)

    result = await service.validate_acceptance(accept(), token=TOKEN)

    assert result["agreement_hash"] == HASH
    assert client.calls == [(TOKEN, "vf_1")]
    assert await store.get_settlement_token("vf_1") == TOKEN


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "FUNDED"),
        ("state", "CANCELED"),
        ("seller_id", "circuitforge"),
        ("agreement_hash", "b" * 64),
        ("amount_cents", 1),
        ("currency", "EUR"),
    ],
)
async def test_validate_acceptance_rejects_bad_bindings(
    store, northwind_policy, field, value
):
    service, _ = build(
        store, northwind_policy, projection(**{field: value})
    )

    with pytest.raises(CommerceProtocolError):
        await service.validate_acceptance(accept(), token=TOKEN)


async def test_validate_acceptance_requires_a_token_and_fields(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy)

    with pytest.raises(CommerceProtocolError):
        await service.validate_acceptance(accept(), token=None)

    missing = accept().model_copy(update={"agreement_hash": None})
    with pytest.raises(CommerceProtocolError):
        await service.validate_acceptance(missing, token=TOKEN)


async def test_validate_purchase_order_requires_funded_and_rotates_the_token(
    store, northwind_policy
):
    await store.save_settlement_token("vf_1", "northwind-audio", "v1.old")
    service, client = build(
        store, northwind_policy, projection(state="FUNDED")
    )

    result = await service.validate_purchase_order(
        purchase_order(), token=TOKEN
    )

    assert result["state"] == "FUNDED"
    assert client.calls == [(TOKEN, "vf_1")]
    assert await store.get_settlement_token("vf_1") == TOKEN


async def test_validate_purchase_order_rejects_an_unfunded_transaction(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy, projection(state="AWARDED"))

    with pytest.raises(CommerceProtocolError):
        await service.validate_purchase_order(
            purchase_order(), token=TOKEN
        )


async def test_accept_offer_node_passes_the_token_from_config(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy)
    await store.save_offer(offer(), task_id="task-1", context_id="ctx-1")

    result = await accept_offer(
        {
            "task_id": "task-1",
            "context_id": "ctx-1",
            "kind": "accept_offer",
            "incoming": strip_settlement_token(
                wrap_payload("accept_offer", accept())
            ),
        },
        {"configurable": {"service": service, "settlement_token": TOKEN}},
    )

    assert result["offer"]["status"] == "accepted"


async def test_order_service_validates_before_reserving_stock(
    store, northwind_policy
):
    await store.set_stock("NC-700", 20, 0)
    await store.save_offer(offer(), task_id="task-1", context_id="ctx-1")
    called: list[str] = []

    async def validator(po):
        called.append(po.idempotency_key)
        raise RuntimeError("transaction is not funded")

    with pytest.raises(OrderError):
        await OrderService(store).create_order(
            purchase_order(), settlement_validator=validator
        )

    assert called == ["run-1:offer-1"]
    assert (await store.get_stock("NC-700")).on_hand == 20


async def test_order_service_skips_validation_for_an_idempotent_retry(
    store, northwind_policy
):
    await store.set_stock("NC-700", 20, 0)
    await store.save_offer(offer(), task_id="task-1", context_id="ctx-1")
    service = OrderService(store)
    first = await service.create_order(purchase_order())

    async def validator(po):
        raise RuntimeError("late validation must not run")

    second = await service.create_order(
        purchase_order(), settlement_validator=validator
    )

    assert second.order_id == first.order_id
    assert (await store.get_stock("NC-700")).on_hand == 8
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_seller_settlement_validation.py -v`
Expected: FAIL with `TypeError` for the new `SellerService` keyword arguments and `ImportError` for the token helpers.

- [ ] **Step 3: Add token helpers and settlement validation to `SellerService`**

In `service.py`, add imports:

```python
import json
from typing import Any

from commerce_core.contracts import AcceptOffer, PurchaseOrderRequest
from google.protobuf import json_format

from seller_agent.settlement import SellerSettlementClient, SettlementError
```

Add module helpers before `SellerService`:

```python
SETTLEMENT_TOKEN_FIELD = "settlement_token"


def settlement_token_from(envelope: dict[str, Any]) -> str | None:
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None
    token = payload.get(SETTLEMENT_TOKEN_FIELD)
    return token if isinstance(token, str) and token else None


def strip_settlement_token(
    envelope: dict[str, Any],
) -> dict[str, Any]:
    cleaned = json.loads(json.dumps(envelope))
    payload = cleaned.get("payload")
    if isinstance(payload, dict):
        payload.pop(SETTLEMENT_TOKEN_FIELD, None)
    return cleaned
```

Extend the constructor:

```python
    def __init__(
        self,
        *,
        store: SellerStore,
        policy: SellerPolicy,
        planner: SellerPlanner,
        settlement: SellerSettlementClient | None = None,
        settlement_enabled: bool = False,
    ) -> None:
        self.store = store
        self.policy = policy
        self.planner = planner
        self.settlement = settlement
        self.settlement_enabled = settlement_enabled
        self.order_service = OrderService(store)
        self.graph = build_graph()
```

Add the redaction and validation methods:

```python
    def redact_message(self, message: Message) -> Message:
        clone = Message()
        clone.CopyFrom(message)
        for part in clone.parts:
            if not part.HasField("data"):
                continue
            value = json_format.MessageToDict(part.data)
            payload = value.get("payload")
            if (
                isinstance(payload, dict)
                and SETTLEMENT_TOKEN_FIELD in payload
            ):
                payload.pop(SETTLEMENT_TOKEN_FIELD)
                part.data.Clear()
                json_format.ParseDict(value, part.data)
        return clone

    def _require_settlement(self) -> SellerSettlementClient:
        if self.settlement is None:
            raise CommerceProtocolError("settlement is not configured")
        return self.settlement

    async def _settlement_projection(
        self, transaction_id: str, token: str
    ) -> dict[str, Any]:
        client = self._require_settlement()
        try:
            return await client.get_transaction(token, transaction_id)
        except SettlementError as exc:
            raise CommerceProtocolError(
                f"settlement token was rejected ({exc.code})"
            ) from exc

    async def validate_acceptance(
        self, accepted: AcceptOffer, *, token: str | None
    ) -> dict[str, Any] | None:
        if not self.settlement_enabled:
            return None
        if not token:
            raise CommerceProtocolError("settlement token is required")
        if (
            not accepted.settlement_transaction_id
            or not accepted.agreement_hash
        ):
            raise CommerceProtocolError("settlement fields are required")
        projection = await self._settlement_projection(
            accepted.settlement_transaction_id, token
        )
        if projection.get("state") != "AWARDED":
            raise CommerceProtocolError(
                "transaction is not awaiting seller acceptance"
            )
        if projection.get("seller_id") != self.policy.seller_id:
            raise CommerceProtocolError(
                "settlement seller does not match this seller"
            )
        if projection.get("agreement_hash") != accepted.agreement_hash:
            raise CommerceProtocolError("agreement hash mismatch")
        if int(projection.get("amount_cents", 0)) != (
            accepted.accepted_total_cents
        ):
            raise CommerceProtocolError("accepted total mismatch")
        if projection.get("currency") != "USD":
            raise CommerceProtocolError("unsupported settlement currency")
        await self.store.save_settlement_token(
            accepted.settlement_transaction_id,
            self.policy.seller_id,
            token,
        )
        return projection

    async def validate_purchase_order(
        self, po: PurchaseOrderRequest, *, token: str | None
    ) -> dict[str, Any] | None:
        if not self.settlement_enabled:
            return None
        if not token:
            raise CommerceProtocolError("settlement token is required")
        if not po.settlement_transaction_id or not po.agreement_hash:
            raise CommerceProtocolError("settlement fields are required")
        projection = await self._settlement_projection(
            po.settlement_transaction_id, token
        )
        if projection.get("state") != "FUNDED":
            raise CommerceProtocolError(
                "transaction is not funded for this purchase order"
            )
        if projection.get("seller_id") != self.policy.seller_id:
            raise CommerceProtocolError(
                "settlement seller does not match this seller"
            )
        if projection.get("agreement_hash") != po.agreement_hash:
            raise CommerceProtocolError("agreement hash mismatch")
        if int(projection.get("amount_cents", 0)) != po.expected_total_cents:
            raise CommerceProtocolError("purchase order total mismatch")
        if projection.get("currency") != "USD":
            raise CommerceProtocolError("unsupported settlement currency")
        await self.store.save_settlement_token(
            po.settlement_transaction_id, self.policy.seller_id, token
        )
        return projection
```

Update `handle_turn` to strip the token and pass it through config:

```python
        envelope = first_envelope(message)
        try:
            if envelope is None:
                raise CommerceProtocolError("missing DataPart")
            kind_from_envelope(envelope)
            settlement_token = settlement_token_from(envelope)
            incoming = strip_settlement_token(envelope)
        except CommerceProtocolError as exc:
            ...
        state = {
            "task_id": task_id,
            "context_id": context_id,
            "incoming": incoming,
        }
        ...
                config={
                    "configurable": {
                        "thread_id": task_id,
                        "planner": self.planner,
                        "service": self,
                        "settlement_token": settlement_token,
                    }
                },
```

- [ ] **Step 4: Validate in the graph's accept and order nodes**

In `accept_offer`, after the existing offer checks and before `model_copy`:

```python
        if (
            service.settlement_enabled
            and state.get("kind") == "accept_offer"
        ):
            await service.validate_acceptance(
                accepted,
                token=config["configurable"].get("settlement_token"),
            )
```

In `order`, build a per-request validator:

```python
        po = parse_payload(
            "purchase_order", state["incoming"], PurchaseOrderRequest
        )
        validator = None
        if service.settlement_enabled:
            async def validator(request):
                await service.validate_purchase_order(
                    request,
                    token=config["configurable"].get("settlement_token"),
                )

        created = await service.order_service.create_order(
            po, settlement_validator=validator
        )
```

Do not put the token into `SellerState`; it stays in the node's `RunnableConfig`.

- [ ] **Step 5: Add the validator hook to `OrderService`**

In `order_service.py`, add imports:

```python
from collections.abc import Awaitable, Callable
```

Add the type alias:

```python
SettlementValidator = Callable[[PurchaseOrderRequest], Awaitable[None]]
```

Change `create_order`:

```python
    async def create_order(
        self,
        po: PurchaseOrderRequest,
        *,
        settlement_validator: SettlementValidator | None = None,
    ) -> Order:
```

After the existing `self._validate(po, offer)` call and before `tx.reserve`:

```python
            if settlement_validator is not None:
                try:
                    await settlement_validator(po)
                except OrderError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise OrderError(
                        CommerceErrorCode.CONFLICT,
                        str(exc) or "Settlement validation failed.",
                    ) from exc
```

The idempotency lookup stays before the validator so a repeated purchase order returns the existing order even after the transaction has left `FUNDED`.

- [ ] **Step 6: Redact the token from A2A task history**

In `executor.py`, replace the history construction in `_start_task`:

```python
        message = context.message
        history = (
            [self.service.redact_message(message)]
            if message is not None
            else []
        )
```

`handle_turn` still receives the original message and extracts the token from it.

- [ ] **Step 7: Run the seller validation tests**

Run: `uv run pytest tests/unit/test_seller_settlement_validation.py -v`
Expected: PASS.

- [ ] **Step 8: Run the seller suite**

Run: `uv run pytest tests/unit tests/integration -k seller -v`
Expected: PASS; off-mode A2A tests keep working because settlement validation is skipped when `settlement_enabled` is false.

- [ ] **Step 9: Commit**

```bash
git add apps/seller_agent/seller_agent/{service.py,graph.py,order_service.py,executor.py} tests/unit/test_seller_settlement_validation.py
git commit -m "feat(seller): validate settlement tokens before acceptance and ordering"
```

---

### Task 22: Seller evidence queue, dashboard settlement status, and server wiring

**Files:**
- Modify: `apps/seller_agent/seller_agent/service.py`
- Modify: `apps/seller_agent/seller_agent/graph.py`
- Modify: `apps/seller_agent/seller_agent/store.py`
- Modify: `apps/seller_agent/seller_agent/server.py`
- Test: `tests/unit/test_seller_evidence_flow.py`

**Interfaces:**
- Produces: `SellerService.queue_evidence(order, po) -> int`, `SellerService.settlement_status() -> list[dict]`, `SellerStore.list_settlement_tokens(limit=5)`; server builds `SellerSettlementClient`/`EvidenceOutbox` and starts them in the lifespan.
- Consumes: `EvidenceOutbox.enqueue`, `build_shipment_manifest`, `build_delivery_confirmation`, `encode_payload`, `Settings.verifund_*`.

- [ ] **Step 1: Write the failing evidence and dashboard tests**

`tests/unit/test_seller_evidence_flow.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from commerce_core.contracts import (
    ApprovalReceipt,
    Fulfillment,
    OfferLineItem,
    Order,
    OrderStatus,
    PurchaseOrderRequest,
    ShippingAddress,
)
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.planner import ScriptedSellerPlanner
from seller_agent.service import SellerService
from seller_agent.settlement import SettlementError
from seller_agent.store import SellerStore

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64
TOKEN = "v1.secret"


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}"
    )
    value = SellerStore(engine)
    await value.create_schema()
    yield value
    await engine.dispose()


class FakeOutbox:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.fail = False

    async def enqueue(self, **kwargs):
        if self.fail:
            raise RuntimeError("outbox unavailable")
        self.items.append(kwargs)
        return True


class FakeSettlement:
    def __init__(self, projection=None, error=None) -> None:
        self.projection = projection
        self.error = error

    async def get_transaction(self, token, transaction_id):
        if self.error is not None:
            raise self.error
        return dict(self.projection)


def order() -> Order:
    return Order(
        order_id="MM-DEMO",
        offer_id="offer-1",
        seller_id="northwind-audio",
        status=OrderStatus.CONFIRMED,
        quantity=2,
        total_cents=20000,
        line_items=[
            OfferLineItem(
                sku="NC-700",
                name="Nimbus NC-700",
                quantity=2,
                unit_price_cents=10000,
                list_unit_price_cents=12000,
            )
        ],
        reserved_at=NOW,
        eta=NOW + timedelta(days=5),
        tracking_number="TRK-1",
        fulfillment=Fulfillment(
            carrier="Northwind Logistics", status="reserved"
        ),
    )


def purchase_order() -> PurchaseOrderRequest:
    return PurchaseOrderRequest(
        request_id="po-1",
        run_id="run-1",
        offer_id="offer-1",
        seller_id="northwind-audio",
        quantity=2,
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
        expected_total_cents=20000,
        settlement_transaction_id="vf_1",
        agreement_hash=HASH,
        settlement_token=TOKEN,
    )


def projection(**overrides):
    value = {
        "transaction_id": "vf_1",
        "state": "FUNDED",
        "seller_id": "northwind-audio",
        "amount_cents": 20000,
        "currency": "USD",
        "agreement_hash": HASH,
        "deadlines": {"evidence": None, "inspection": None},
        "evidence": None,
        "purchase_order": None,
        "updated_at": NOW.isoformat(),
    }
    value.update(overrides)
    return value


def build(store, policy, *, outbox=None, settlement=None, auto=True):
    return SellerService(
        store=store,
        policy=policy,
        planner=ScriptedSellerPlanner(),
        settlement=settlement,
        settlement_enabled=True,
        evidence_outbox=outbox,
        auto_evidence=auto,
    )


async def test_queue_evidence_enqueues_manifest_and_delivery(
    store, northwind_policy
):
    outbox = FakeOutbox()
    service = build(store, northwind_policy, outbox=outbox)

    count = await service.queue_evidence(order(), purchase_order())

    assert count == 2
    kinds = [item["kind"] for item in outbox.items]
    assert kinds == ["shipment_manifest", "delivery_confirmation"]
    assert all(item["transaction_id"] == "vf_1" for item in outbox.items)
    manifest = outbox.items[0]
    assert manifest["filename"] == "shipment-manifest.json"
    assert b"TRK-1" in manifest["content"]
    assert manifest["captured_at"] == json.loads(
        manifest["content"]
    )["shipped_at"]


async def test_queue_evidence_is_skipped_when_auto_evidence_is_off(
    store, northwind_policy
):
    outbox = FakeOutbox()
    service = build(
        store, northwind_policy, outbox=outbox, auto=False
    )

    assert await service.queue_evidence(order(), purchase_order()) == 0
    assert outbox.items == []


async def test_queue_evidence_does_not_fail_the_order_when_storage_is_down(
    store, northwind_policy
):
    outbox = FakeOutbox()
    outbox.fail = True
    service = build(store, northwind_policy, outbox=outbox)

    assert await service.queue_evidence(order(), purchase_order()) == 0


async def test_settlement_status_omits_tokens_and_reports_state(
    store, northwind_policy
):
    await store.save_settlement_token("vf_1", "northwind-audio", TOKEN)
    settlement = FakeSettlement(projection())
    service = build(store, northwind_policy, settlement=settlement)

    rows = await service.settlement_status()

    assert rows[0]["transaction_id"] == "vf_1"
    assert rows[0]["state"] == "FUNDED"
    assert rows[0]["unavailable"] is False
    assert TOKEN not in json.dumps(rows)


async def test_settlement_status_degrades_when_the_control_plane_is_down(
    store, northwind_policy
):
    await store.save_settlement_token("vf_1", "northwind-audio", TOKEN)
    settlement = FakeSettlement(
        error=SettlementError("provider_unavailable", "down", status_code=503)
    )
    service = build(store, northwind_policy, settlement=settlement)

    rows = await service.settlement_status()

    assert rows[0]["transaction_id"] == "vf_1"
    assert rows[0]["state"] == "unavailable"
    assert rows[0]["unavailable"] is True
    assert TOKEN not in json.dumps(rows)


async def test_list_settlement_tokens_never_returns_the_token(
    store, northwind_policy
):
    await store.save_settlement_token("vf_1", "northwind-audio", TOKEN)

    rows = await store.list_settlement_tokens()

    assert rows == [
        {
            "transaction_id": "vf_1",
            "seller_id": "northwind-audio",
            "updated_at": rows[0]["updated_at"],
        }
    ]
    assert "token" not in rows[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_seller_evidence_flow.py -v`
Expected: FAIL with `TypeError` for `evidence_outbox`/`auto_evidence` and `AttributeError: settlement_status`.

- [ ] **Step 3: Add the evidence queue and settlement status**

In `service.py`, add imports:

```python
import logging

from seller_agent.settlement import (
    build_delivery_confirmation,
    build_shipment_manifest,
    encode_payload,
)

logger = logging.getLogger(__name__)
```

Extend the constructor:

```python
        settlement: SellerSettlementClient | None = None,
        settlement_enabled: bool = False,
        evidence_outbox: EvidenceOutbox | None = None,
        auto_evidence: bool = True,
```

and assign:

```python
        self.evidence_outbox = evidence_outbox
        self.auto_evidence = auto_evidence
```

Import the type under `TYPE_CHECKING` to avoid a runtime cycle:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seller_agent.evidence_outbox import EvidenceOutbox
```

Add the methods:

```python
    async def queue_evidence(
        self, order: Order, po: PurchaseOrderRequest
    ) -> int:
        if not (
            self.settlement_enabled
            and self.auto_evidence
            and self.evidence_outbox is not None
            and po.settlement_transaction_id
            and po.agreement_hash
        ):
            return 0
        transaction_id = po.settlement_transaction_id
        manifest = build_shipment_manifest(
            order,
            transaction_id=transaction_id,
            agreement_hash=po.agreement_hash,
        )
        delivery = build_delivery_confirmation(
            order, transaction_id=transaction_id
        )
        try:
            await self.evidence_outbox.enqueue(
                transaction_id=transaction_id,
                seller_id=self.policy.seller_id,
                kind="shipment_manifest",
                content=encode_payload(manifest),
                media_type="application/json",
                filename="shipment-manifest.json",
                note="Auto-generated by the seller agent.",
                captured_at=manifest["shipped_at"],
            )
            await self.evidence_outbox.enqueue(
                transaction_id=transaction_id,
                seller_id=self.policy.seller_id,
                kind="delivery_confirmation",
                content=encode_payload(delivery),
                media_type="application/json",
                filename="delivery-confirmation.json",
                note="Auto-generated by the seller agent.",
                captured_at=delivery["delivered_at"],
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not enqueue seller evidence")
            return 0
        return 2

    async def settlement_status(self) -> list[dict[str, Any]]:
        if not self.settlement_enabled or self.settlement is None:
            return []
        rows = await self.store.list_settlement_tokens(limit=5)
        statuses: list[dict[str, Any]] = []
        for row in rows:
            transaction_id = row["transaction_id"]
            token = await self.store.get_settlement_token(transaction_id)
            if not token:
                continue
            try:
                projection = await self.settlement.get_transaction(
                    token, transaction_id
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "seller settlement status unavailable for %s",
                    transaction_id,
                )
                statuses.append(
                    {
                        "transaction_id": transaction_id,
                        "seller_id": row["seller_id"],
                        "state": "unavailable",
                        "unavailable": True,
                    }
                )
                continue
            statuses.append(
                {
                    "transaction_id": transaction_id,
                    "seller_id": row["seller_id"],
                    "state": projection.get("state"),
                    "amount_cents": projection.get("amount_cents"),
                    "currency": projection.get("currency"),
                    "agreement_hash": projection.get("agreement_hash"),
                    "deadlines": projection.get("deadlines") or {},
                    "evidence": projection.get("evidence"),
                    "purchase_order": projection.get("purchase_order"),
                    "updated_at": projection.get("updated_at"),
                    "unavailable": False,
                }
            )
        return statuses
```

Add `Order` and `PurchaseOrderRequest` to the `commerce_core.contracts` import if they are not already present.

- [ ] **Step 4: List settlement tokens without exposing them**

In `store.py`, append:

```python
    async def list_settlement_tokens(
        self, limit: int = 5
    ) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(
                    self.settlement_tokens.c.transaction_id,
                    self.settlement_tokens.c.seller_id,
                    self.settlement_tokens.c.updated_at,
                )
                .order_by(self.settlement_tokens.c.updated_at.desc())
                .limit(max(1, min(limit, 20)))
            )
            return [dict(row._mapping) for row in result]
```

- [ ] **Step 5: Queue evidence after the order commits**

In `graph.py`'s `order` node, immediately after `create_order` returns:

```python
        created = await service.order_service.create_order(
            po, settlement_validator=validator
        )
        await service.queue_evidence(created, po)
```

`queue_evidence` swallows storage failures so an order is never failed by the outbox.

- [ ] **Step 6: Wire the client and outbox into the seller app**

In `server.py`, add imports:

```python
from seller_agent.evidence_outbox import EvidenceOutbox
from seller_agent.settlement import SellerSettlementClient
```

Before constructing `SellerService`:

```python
    settlement_client = None
    evidence_outbox = None
    if settings.verifund_mode != "off":
        settlement_client = SellerSettlementClient(
            settings.verifund_url,
            timeout_seconds=settings.verifund_timeout_seconds,
        )
        evidence_outbox = EvidenceOutbox(
            store,
            settlement_client,
            retry_seconds=settings.verifund_evidence_retry_seconds,
        )
```

Pass them to the service:

```python
    service = SellerService(
        store=store,
        policy=policy,
        planner=planner,
        settlement=settlement_client,
        settlement_enabled=settings.verifund_mode != "off",
        evidence_outbox=evidence_outbox,
        auto_evidence=settings.verifund_auto_evidence,
    )
```

Update the lifespan:

```python
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await store.create_schema()
            await store.seed_catalog(policy)
            if evidence_outbox is not None:
                await evidence_outbox.start()
            yield
        finally:
            if evidence_outbox is not None:
                await evidence_outbox.stop()
            if settlement_client is not None:
                await settlement_client.close()
            await engine.dispose()
```

Add the status to the dashboard response:

```python
            "settlement": await service.settlement_status(),
```

Place it next to `recent_orders` so the console can render it without another request.

- [ ] **Step 7: Run the seller evidence tests**

Run: `uv run pytest tests/unit/test_seller_evidence_flow.py -v`
Expected: PASS.

- [ ] **Step 8: Run the seller suite**

Run: `uv run pytest tests/unit tests/integration -k seller -v`
Expected: PASS; `VERIFUND_MODE=off` remains the default and starts no outbox.

- [ ] **Step 9: Commit**

```bash
git add apps/seller_agent/seller_agent/{service.py,graph.py,store.py,server.py} tests/unit/test_seller_evidence_flow.py
git commit -m "feat(seller): queue evidence after orders and surface settlement status"
```

---

### Task 22A: Add generic A2A agent registration and discovery

The Verifund agent is not a seller: it has no catalog, no commerce extension, and
no seller token. Registering it through `/v1/sellers` would require a catalog and
reject its card. Add a separate agent store and `/v1/agents` routes, leaving
seller registration and discovery untouched.

**Files:**
- Modify: `packages/commerce_core/commerce_core/cards.py`
- Modify: `apps/registry/registry/store.py`
- Modify: `apps/registry/registry/api.py`
- Modify: `apps/registry/registry/settings.py`
- Test: `tests/unit/test_registry_agents.py`

**Interfaces:**
- Produces: `validate_generic_agent_card(card) -> list[str]`; `AgentCreate`, `AgentDiscoverRequest`, `POST /v1/agents`, `GET /v1/agents`, `GET /v1/agents/{agent_id}`, `POST /v1/agents/{agent_id}/refresh`, `POST /v1/agents/discover`; `RegistryStore.upsert_agent`, `list_agents`, `get_agent`, `mark_agent_health`; `Settings.allowed_card_hosts` includes the Compose hostname `verifund-agent`.
- Consumes: existing `fetch_agent_card`, `canonical_card_hash`, admin bearer auth, and SQLite setup. Seller routes, seller discovery, and product search are unchanged.

- [ ] **Step 1: Write the failing generic-agent tests**

`tests/unit/test_registry_agents.py`:

```python
from __future__ import annotations

import httpx
import pytest
import respx
from a2a.types.a2a_pb2 import AgentCard
from google.protobuf import json_format
from sqlalchemy.ext.asyncio import create_async_engine

from commerce_core.cards import validate_generic_agent_card
from registry.api import create_app
from registry.settings import Settings
from registry.store import RegistryStore

VERIFUND_CARD = {
    "name": "Verifund",
    "description": "Agreement and settlement control for MarketMesh.",
    "version": "1.0.0",
    "capabilities": {"streaming": True},
    "supportedInterfaces": [
        {
            "url": "http://127.0.0.1:9301/a2a",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ],
    "skills": [
        {"id": "verifund.agreement.create", "name": "Create agreement"},
        {"id": "verifund.transaction.status", "name": "Transaction status"},
        {"id": "verifund.transaction.fund", "name": "Fund transaction"},
        {"id": "verifund.evidence.review", "name": "Review evidence"},
        {"id": "verifund.transaction.release", "name": "Release transaction"},
        {"id": "verifund.receipt.get", "name": "Get receipt"},
    ],
    "securitySchemes": {"bearer": {"httpAuthSecurityScheme": {"scheme": "bearer"}}},
}


def card(data: dict | None = None) -> AgentCard:
    value = AgentCard()
    json_format.ParseDict(data or VERIFUND_CARD, value)
    return value


def test_generic_card_accepts_verifund_without_a_commerce_extension() -> None:
    assert validate_generic_agent_card(card()) == []


def test_generic_card_still_requires_a2a_shape() -> None:
    broken = {**VERIFUND_CARD, "capabilities": {"streaming": False}}
    assert "streaming is required" in validate_generic_agent_card(card(broken))
    no_skills = {**VERIFUND_CARD, "skills": []}
    assert any("skill" in error for error in validate_generic_agent_card(card(no_skills)))


async def test_agent_store_is_separate_from_sellers(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}")
    store = RegistryStore(engine)
    await store.create_schema()
    await store.upsert_agent(
        agent_id="verifund",
        name="Verifund",
        card_url="http://127.0.0.1:9301/.well-known/agent-card.json",
        skills=["verifund.agreement.create"],
        card_json=VERIFUND_CARD,
        card_hash="a" * 64,
        healthy=True,
        error=None,
    )
    assert [row["agent_id"] for row in await store.list_agents()] == ["verifund"]
    assert await store.list_sellers() == []
    assert (await store.get_agent("verifund"))["name"] == "Verifund"
    assert [row["agent_id"] for row in await store.list_agents(skill="verifund.agreement.create")] == ["verifund"]
    assert await store.list_agents(skill="verifund.unknown") == []
    await engine.dispose()


@respx.mock
async def test_agent_routes_register_refresh_and_discover(tmp_path):
    card_url = "http://127.0.0.1:9301/.well-known/agent-card.json"
    respx.get(card_url).mock(
        return_value=httpx.Response(200, json=VERIFUND_CARD)
    )
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}",
        admin_token="admin",
        allowed_card_hosts=("127.0.0.1",),
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://registry") as http:
            refused = await http.post("/v1/agents", json={"card_url": card_url})
            assert refused.status_code == 401

            created = await http.post(
                "/v1/agents",
                headers={"authorization": "Bearer admin"},
                json={"card_url": card_url},
            )
            assert created.status_code == 201, created.text
            assert created.json()["agent_id"] == "verifund"
            assert "commerce" not in created.json()["skills"][0]

            listed = await http.get("/v1/agents", headers={"authorization": "Bearer admin"})
            assert listed.json()["agents"][0]["agent_id"] == "verifund"

            found = await http.post(
                "/v1/agents/discover",
                headers={"authorization": "Bearer admin"},
                json={"skill": "verifund.transaction.fund"},
            )
            assert found.status_code == 200
            assert found.json()["agents"][0]["agent_id"] == "verifund"

            missing = await http.post(
                "/v1/agents/discover",
                headers={"authorization": "Bearer admin"},
                json={"skill": "verifund.unknown"},
            )
            assert missing.json() == {"agents": []}

            refreshed = await http.post(
                "/v1/agents/verifund/refresh",
                headers={"authorization": "Bearer admin"},
            )
            assert refreshed.status_code == 200
            assert refreshed.json()["healthy"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_registry_agents.py -v`
Expected: FAIL with missing `validate_generic_agent_card`, `upsert_agent`, and `/v1/agents` 404s.

- [ ] **Step 3: Add the generic card validator**

In `packages/commerce_core/commerce_core/cards.py`:

```python
def validate_generic_agent_card(card: AgentCard) -> list[str]:
    errors: list[str] = []
    if not card.name:
        errors.append("missing name")
    if not card.version:
        errors.append("missing version")
    if not any(
        interface.protocol_binding == "JSONRPC"
        and interface.protocol_version.startswith("1.")
        for interface in card.supported_interfaces
    ):
        errors.append("missing JSONRPC A2A 1.x interface")
    if not card.capabilities.streaming:
        errors.append("streaming is required")
    if not list(card.skills):
        errors.append("missing at least one skill")
    if "bearer" not in card.security_schemes:
        errors.append("missing bearer security scheme")
    return errors
```

Add `"buyer"`, `"verifund-agent"`, and `"host.docker.internal"` to
`DEFAULT_CARD_HOSTS` so the orchestrator can fetch the Buyer and Verifund
cards through Compose service names.

- [ ] **Step 4: Add the separate agent table and operations**

In `RegistryStore.__init__`, after `self.listings`:

```python
        self.agents = Table(
            "agents",
            self.metadata,
            Column("agent_id", String(64), primary_key=True),
            Column("name", String, nullable=False),
            Column("card_url", String, nullable=False),
            Column("skills", JSON, nullable=False),
            Column("card_json", JSON, nullable=False),
            Column("card_hash", String(64), nullable=False),
            Column("last_seen_at", String, nullable=False),
            Column("healthy", Boolean, nullable=False, default=True),
            Column("last_error", String, nullable=True),
        )
```

Add methods:

```python
    async def upsert_agent(
        self,
        *,
        agent_id: str,
        name: str,
        card_url: str,
        skills: list[str],
        card_json: dict[str, Any],
        card_hash: str,
        healthy: bool,
        error: str | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        values = {
            "agent_id": agent_id,
            "name": name,
            "card_url": card_url,
            "skills": skills,
            "card_json": card_json,
            "card_hash": card_hash,
            "last_seen_at": now,
            "healthy": healthy,
            "last_error": error,
        }
        statement = sqlite_insert(self.agents).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["agent_id"],
            set_={key: value for key, value in values.items() if key != "agent_id"},
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)
        return values

    async def list_agents(self, skill: str | None = None) -> list[dict[str, Any]]:
        statement = select(self.agents).order_by(self.agents.c.agent_id)
        if skill:
            statement = statement.where(self.agents.c.skills.contains([skill]))
        async with self.engine.connect() as conn:
            result = await conn.execute(statement)
            return [dict(row._mapping) for row in result]

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                select(self.agents).where(self.agents.c.agent_id == agent_id)
            )
            row = result.first()
            return dict(row._mapping) if row else None

    async def mark_agent_health(
        self, agent_id: str, healthy: bool, error: str | None
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.agents.update()
                .where(self.agents.c.agent_id == agent_id)
                .values(healthy=healthy, last_error=error)
            )
```

If SQLite JSON `contains([skill])` is unreliable, load healthy agents and filter
`skill in row["skills"]` in Python. Keep the returned order stable.

- [ ] **Step 5: Add the registry routes**

In `apps/registry/registry/api.py`, import `validate_generic_agent_card`, then add:

```python
class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str | None = None
    card_url: str


class AgentDiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str
    limit: int = Field(default=20, ge=1, le=100)


def _agent_view(row: dict[str, Any], include_card: bool = False) -> dict[str, Any]:
    view = {
        "agent_id": row["agent_id"],
        "name": row["name"],
        "card_url": row["card_url"],
        "skills": row["skills"],
        "card_hash": row["card_hash"],
        "last_seen_at": row["last_seen_at"],
        "healthy": row["healthy"],
        "last_error": row.get("last_error"),
    }
    if include_card:
        view["card_json"] = row["card_json"]
    return view


async def _load_agent_card(card_url: str, settings: Settings):
    card = await fetch_agent_card(
        card_url, allowed_hosts=settings.allowed_card_hosts
    )
    errors = validate_generic_agent_card(card)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return card


@app.post("/v1/agents", status_code=201)
async def register_agent(
    body: AgentCreate,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    try:
        card = await _load_agent_card(body.card_url, settings)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    agent_id = body.agent_id or _slug(card.name)
    if not SELLER_ID_PATTERN.fullmatch(agent_id):
        raise HTTPException(status_code=400, detail="invalid agent id")
    payload = json_format.MessageToDict(card, preserving_proto_field_name=False)
    row = await store.upsert_agent(
        agent_id=agent_id,
        name=card.name,
        card_url=body.card_url,
        skills=sorted(skill.id for skill in card.skills),
        card_json=payload,
        card_hash=canonical_card_hash(payload),
        healthy=True,
        error=None,
    )
    return _agent_view(row, include_card=True)


@app.get("/v1/agents")
async def list_agents(
    _: None = Depends(require_admin),
    skill: str | None = None,
) -> dict[str, Any]:
    rows = await store.list_agents(skill=skill)
    return {"agents": [_agent_view(row) for row in rows]}


@app.get("/v1/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    row = await store.get_agent(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return _agent_view(row, include_card=True)


@app.post("/v1/agents/{agent_id}/refresh")
async def refresh_agent(
    agent_id: str,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    row = await store.get_agent(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")
    try:
        card = await _load_agent_card(row["card_url"], settings)
    except Exception as exc:  # noqa: BLE001
        await store.mark_agent_health(agent_id, False, str(exc))
        raise HTTPException(status_code=400, detail=f"agent card unavailable: {exc}") from exc
    payload = json_format.MessageToDict(card, preserving_proto_field_name=False)
    row = await store.upsert_agent(
        agent_id=agent_id,
        name=card.name,
        card_url=row["card_url"],
        skills=sorted(skill.id for skill in card.skills),
        card_json=payload,
        card_hash=canonical_card_hash(payload),
        healthy=True,
        error=None,
    )
    return _agent_view(row, include_card=True)


@app.post("/v1/agents/discover")
async def discover_agents(
    body: AgentDiscoverRequest,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    rows = await store.list_agents(skill=body.skill)
    return {
        "agents": [
            _agent_view(row)
            for row in rows
            if row["healthy"]
        ][: body.limit]
    }
```

Add `"verifund-agent"` and `"host.docker.internal"` to the default
`allowed_card_hosts` tuple in `apps/registry/registry/settings.py`.

- [ ] **Step 6: Run the registry tests and the existing seller tests**

Run: `uv run pytest tests/unit/test_registry_agents.py tests/integration -k registry -v`
Expected: PASS. `/v1/sellers`, `/v1/discover`, and catalog search behavior are unchanged.

- [ ] **Step 7: Commit**

```bash
git add packages/commerce_core/commerce_core/cards.py apps/registry/registry/{store.py,api.py,settings.py} tests/unit/test_registry_agents.py
git commit -m "feat(registry): register generic A2A agents separately from sellers"
```

---

### Task 22B: Create the Verifund agent package, card, client, and server

The Verifund process is a separate A2A service. It holds only the buyer
internal credential (`VERIFUND_AGENT_INTERNAL_TOKEN`) and its own A2A bearer
token (`VERIFUND_AGENT_A2A_TOKEN`). It must not read
`VERIFUND_OPS_TOKEN`, seller tokens, or PayPal settings.

**Files:**
- Create: `apps/verifund_agent/pyproject.toml`
- Create: `apps/verifund_agent/verifund_agent/{__init__.py,__main__.py,settings.py,card.py,auth.py,client.py,service.py,executor.py,server.py}`
- Modify: root `pyproject.toml`
- Test: `tests/unit/test_verifund_agent_package.py`

**Interfaces:**
- Produces: `Settings` (`agent_port`, `public_url`, `a2a_token`, `buyer_base_url`, `buyer_internal_token`, `request_timeout_seconds`); `build_card(base_url)` with all six skills; `BuyerInternalClient` with `create_agreement`, `get_settlement`, `approve_funding`, `release`, `receipt`, `evidence`; `VerifundExecutor`; `create_app(settings)`.
- Consumes: `verifund_contracts` A2A envelopes and buyer routes from Task 17A.

- [ ] **Step 1: Write the failing package tests**

`tests/unit/test_verifund_agent_package.py`:

```python
from __future__ import annotations

import httpx
import respx

from verifund_agent.card import build_card
from verifund_agent.client import BuyerInternalClient
from verifund_agent.settings import Settings
from verifund_contracts import AwardRequest, BuyerAgreementRequest

REQUIRED_SKILLS = {
    "verifund.agreement.create",
    "verifund.transaction.status",
    "verifund.transaction.fund",
    "verifund.evidence.review",
    "verifund.transaction.release",
    "verifund.receipt.get",
}


def test_card_exposes_all_verifund_skills_without_commerce_extension() -> None:
    card = build_card("http://127.0.0.1:9301")
    assert {skill.id for skill in card.skills} == REQUIRED_SKILLS
    assert all(
        extension.uri != "https://marketmesh.example/extensions/commerce/v1"
        for extension in card.capabilities.extensions
    )
    assert card.capabilities.streaming is True
    assert "bearer" in card.security_schemes


def test_settings_hold_no_control_plane_seller_or_paypal_credentials() -> None:
    settings = Settings()
    forbidden = {
        "ops_token",
        "verifund_ops_token",
        "seller_token_secret",
        "paypal_client_id",
        "paypal_client_secret",
    }
    assert forbidden.isdisjoint(settings.model_dump())
    assert settings.buyer_internal_token
    assert settings.a2a_token
    assert settings.a2a_token != settings.buyer_internal_token


@respx.mock
async def test_buyer_client_uses_only_the_agent_internal_header() -> None:
    route = respx.get("http://buyer/internal/runs/run-1/settlement").mock(
        return_value=httpx.Response(200, json={"projection": {"state": "AGREED"}})
    )
    client = BuyerInternalClient(
        "http://buyer",
        internal_token="agent-internal",
    )
    await client.get_settlement("run-1")
    request = route.calls[0].request
    assert request.headers["x-verifund-agent-token"] == "agent-internal"
    assert "authorization" not in request.headers
    assert "ops-token" not in str(request.headers)


@respx.mock
async def test_buyer_client_creates_an_agreement_with_the_exact_award() -> None:
    route = respx.post(
        "http://buyer/internal/runs/run-1/settlement/agreement"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "transaction_id": "vf_1",
                "state": "AWARDED",
                "agreement": {},
                "agreement_version": 1,
                "agreement_hash": "a" * 64,
                "seller_token_ref": "run:run-1:transaction:vf_1",
            },
        )
    )
    client = BuyerInternalClient(
        "http://buyer",
        internal_token="agent-internal",
    )
    request = BuyerAgreementRequest(
        award=AwardRequest(
            run_id="run-1",
            buyer_id="demo-buyer",
            seller_id="northwind-audio",
            offer_id="offer-1",
            amount_cents=123400,
            shipping_cents=3400,
            quantity=12,
            line_items=[
                {
                    "sku": "NC-700",
                    "name": "Nimbus NC-700 ANC Headset",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                }
            ],
            delivery_days=7,
            warranty_months=24,
            returns_days=30,
        ),
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        idempotency_key="agreement:run-1:offer-1",
    )
    await client.create_agreement("run-1", request)
    body = route.calls[0].request.read().decode()
    assert '"run_id": "run-1"' in body
    assert '"buyer_task_id": "buyer-task-1"' in body
    assert route.calls[0].request.headers["x-verifund-agent-token"] == "agent-internal"


def test_server_requires_the_a2a_bearer_token() -> None:
    from fastapi.testclient import TestClient

    from verifund_agent.server import create_app

    app = create_app(Settings(a2a_token="a2a-secret"))
    with TestClient(app) as http:
        refused = http.post("/a2a", json={})
        assert refused.status_code == 401
        allowed = http.post(
            "/a2a",
            headers={"authorization": "Bearer a2a-secret"},
            json={},
        )
        assert allowed.status_code != 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_agent_package.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verifund_agent'`.

- [ ] **Step 3: Add the workspace package**

`apps/verifund_agent/pyproject.toml`:

```toml
[project]
name = "marketmesh-verifund-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "marketmesh-commerce-core",
  "verifund-contracts",
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "a2a-sdk[http-server,fastapi]==1.2.3",
  "httpx>=0.27,<1",
  "pydantic-settings>=2.6,<3",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["verifund_agent"]

[tool.uv.sources]
marketmesh-commerce-core = { workspace = true }
verifund-contracts = { workspace = true }
```

Add `"apps/verifund_agent"` to the root workspace members and
`verifund-contracts = { workspace = true }` to the root sources. Then run
`uv lock && uv sync --all-packages`.

- [ ] **Step 4: Implement settings, card, and buyer client**

`apps/verifund_agent/verifund_agent/settings.py`:

```python
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )
    service_name: str = "verifund-agent"
    host: str = Field(default="127.0.0.1", validation_alias=AliasChoices("HOST"))
    agent_port: int = Field(
        default=9301,
        validation_alias=AliasChoices("VERIFUND_AGENT_PORT", "PORT"),
    )
    public_url: str = Field(
        default="http://127.0.0.1:9301",
        validation_alias=AliasChoices("VERIFUND_AGENT_URL"),
    )
    a2a_token: str = Field(
        default="dev-verifund-agent-a2a",
        validation_alias=AliasChoices("VERIFUND_AGENT_A2A_TOKEN"),
    )
    buyer_base_url: str = Field(
        default="http://127.0.0.1:9100",
        validation_alias=AliasChoices(
            "BUYER_INTERNAL_URL",
            "VERIFUND_AGENT_BUYER_URL",
        ),
    )
    buyer_internal_token: str = Field(
        default="dev-verifund-agent-internal",
        validation_alias=AliasChoices("VERIFUND_AGENT_INTERNAL_TOKEN"),
    )
    request_timeout_seconds: float = Field(
        default=20.0,
        validation_alias=AliasChoices("VERIFUND_AGENT_TIMEOUT_SECONDS"),
    )
```

`apps/verifund_agent/verifund_agent/card.py`:

```python
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol

SKILLS = (
    ("verifund.agreement.create", "Create agreement", "Assemble the agreement from the exact Buyer award and canonicalize it through the buyer."),
    ("verifund.transaction.status", "Transaction status", "Return the buyer-confirmed transaction projection."),
    ("verifund.transaction.fund", "Fund transaction", "Submit the structured human funding decision and return the checkout handoff."),
    ("verifund.evidence.review", "Review evidence", "Summarize evidence metadata and deterministic verification outcome."),
    ("verifund.transaction.release", "Release transaction", "Submit the structured human release decision through the buyer."),
    ("verifund.receipt.get", "Get receipt", "Return the verified signed receipt after release."),
)


def build_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="Verifund",
        description="Agreement and settlement control for MarketMesh.",
        version="1.0.0",
        provider=AgentProvider(organization="MarketMesh", url=base_url),
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url.rstrip('/')}/a2a",
                protocol_binding=TransportProtocol.JSONRPC,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id=skill_id,
                name=name,
                description=description,
                tags=["verifund", "settlement"],
                input_modes=["application/json"],
                output_modes=["application/json"],
            )
            for skill_id, name, description in SKILLS
        ],
        security_schemes={
            "bearer": SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer")
            )
        },
        security_requirements=[
            SecurityRequirement(schemes={"bearer": StringList(list=[])})
        ],
    )
```

`apps/verifund_agent/verifund_agent/client.py`:

```python
from __future__ import annotations

from typing import Any

import httpx

from verifund_contracts import (
    BuyerAgreementRequest,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
)


class BuyerAPIError(Exception):
    def __init__(self, message: str, *, status_code: int, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class BuyerInternalClient:
    def __init__(
        self,
        base_url: str,
        *,
        internal_token: str,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"x-verifund-agent-token": internal_token},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        response = await self._client.request(method, self.base_url + path, json=json)
        if response.status_code >= 400:
            raise BuyerAPIError(
                f"buyer returned HTTP {response.status_code}",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )
        return response.json()

    async def create_agreement(
        self, run_id: str, request: BuyerAgreementRequest
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/agreement",
            json=request.model_dump(mode="json"),
        )

    async def get_settlement(self, run_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/internal/runs/{run_id}/settlement"
        )

    async def approve_funding(
        self, run_id: str, decision: FundingApprovalDecision
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/approve-funding",
            json=decision.model_dump(mode="json"),
        )

    async def release(
        self, run_id: str, decision: ReleaseApprovalDecision
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/release",
            json=decision.model_dump(mode="json"),
        )

    async def receipt(self, run_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/internal/runs/{run_id}/settlement/receipt"
        )

    async def evidence(
        self, run_id: str, evidence_id: str
    ) -> tuple[bytes, str, str]:
        response = await self._client.get(
            f"{self.base_url}/internal/runs/{run_id}/settlement/evidence/{evidence_id}"
        )
        if response.status_code >= 400:
            raise BuyerAPIError(
                f"buyer returned HTTP {response.status_code}",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )
        disposition = response.headers.get("content-disposition", "")
        filename = "evidence"
        if 'filename="' in disposition:
            filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
        return (
            response.content,
            response.headers.get("content-type", "application/octet-stream"),
            filename,
        )
```

- [ ] **Step 5: Implement the service skeleton, executor, and server**

`service.py` starts as an explicit unsupported-skill skeleton so the package is
importable and the executor can be wired without a circular dependency. Task
22C replaces the `handle` body with the agreement and status handlers.

```python
from __future__ import annotations

from typing import Any

from verifund_contracts import VerifundTaskRequest, VerifundTaskResult

from verifund_agent.client import BuyerInternalClient


class VerifundAgentService:
    def __init__(self, *, buyer: BuyerInternalClient) -> None:
        self.buyer = buyer

    async def handle(self, request: VerifundTaskRequest) -> VerifundTaskResult:
        return VerifundTaskResult(
            skill=request.skill,
            status="failed",
            run_id=request.run_id,
            transaction_id=request.transaction_id,
            agreement_version=request.agreement_version,
            agreement_hash=request.agreement_hash,
            message="unsupported Verifund skill",
        )
```

`executor.py` mirrors the seller executor: emit a working task, call
`VerifundAgentService.handle(...)`, emit a data artifact with the
`VerifundTaskResult` envelope, then a terminal status. Failures map to
`TASK_STATE_FAILED`; `input_required` maps to
`TASK_STATE_INPUT_REQUIRED` only for a human-gated result.

`server.py`:

```python
from contextlib import asynccontextmanager

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from fastapi import FastAPI

from verifund_agent.auth import BearerAuthMiddleware
from verifund_agent.card import build_card
from verifund_agent.client import BuyerInternalClient
from verifund_agent.executor import VerifundExecutor
from verifund_agent.service import VerifundAgentService
from verifund_agent.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    card = build_card(settings.public_url)
    buyer = BuyerInternalClient(
        settings.buyer_base_url,
        internal_token=settings.buyer_internal_token,
        timeout=settings.request_timeout_seconds,
    )
    service = VerifundAgentService(buyer=buyer)
    executor = VerifundExecutor(service)
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            await buyer.close()

    app = FastAPI(title="MarketMesh Verifund Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.buyer = buyer
    app.state.service = service
    app.add_middleware(
        BearerAuthMiddleware,
        token=settings.a2a_token,
        public_paths={
            "/health",
            "/ready",
            "/.well-known/agent-card.json",
        },
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a"),
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "verifund-agent"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready", "service": "verifund-agent"}

    return app
```

Copy `apps/seller_agent/seller_agent/auth.py` to
`apps/verifund_agent/verifund_agent/auth.py`.

`__main__.py` starts uvicorn on `settings.host:settings.agent_port`.

- [ ] **Step 6: Run the package tests**

Run: `uv run pytest tests/unit/test_verifund_agent_package.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/verifund_agent pyproject.toml uv.lock tests/unit/test_verifund_agent_package.py
git commit -m "feat(verifund): add standalone agent package, card, and authenticated server"
```

---

### Task 22C: Implement `verifund.agreement.create` and `verifund.transaction.status`

**Files:**
- Modify: `apps/verifund_agent/verifund_agent/service.py`
- Modify: `apps/verifund_agent/verifund_agent/executor.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: `VerifundAgentService.handle(request: VerifundTaskRequest) -> VerifundTaskResult`; `agreement.create` and `transaction.status` handlers.
- Consumes: `BuyerInternalClient`, `AgreementProjection`, `BuyerAgreementRequest`, `VerifundTaskRequest`/`Result`, and `AgreementReviewResult` only for validation of review envelopes; Verifund never submits a review decision.

- [ ] **Step 1: Write the failing service tests**

`tests/unit/test_verifund_agent_service.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from verifund_agent.service import VerifundAgentService
from verifund_contracts import (
    AgreementProjection,
    BuyerAgreementRequest,
    VerifundSkill,
    VerifundTaskRequest,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award(**overrides):
    payload = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }
    payload.update(overrides)
    return payload


class Buyer:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def create_agreement(self, run_id, request):
        self.calls.append(("create_agreement", run_id, request))
        return {
            "transaction_id": "vf_1",
            "state": "AWARDED",
            "agreement": {},
            "agreement_version": 1,
            "agreement_hash": "a" * 64,
            "seller_token_ref": "run:run-1:transaction:vf_1",
        }

    async def get_settlement(self, run_id):
        self.calls.append(("get_settlement", run_id))
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "projection": {"state": "AGREED", "transaction_id": "vf_1"},
        }


@pytest.fixture
def service():
    buyer = Buyer()
    return VerifundAgentService(buyer=buyer), buyer


async def test_agreement_create_uses_the_exact_award_and_returns_the_projection(service):
    value, buyer = service
    request = VerifundTaskRequest(
        skill=VerifundSkill.AGREEMENT_CREATE,
        run_id="run-1",
        payload={"award": award(), "buyer_task_id": "buyer-task-1", "buyer_context_id": "run-1"},
        idempotency_key="agreement:run-1:offer-1",
    )
    result = await value.handle(request)
    assert result.status == "completed"
    assert result.next_action == "buyer_review"
    assert result.data["seller_token_ref"] == "run:run-1:transaction:vf_1"
    call = buyer.calls[0]
    assert call[0] == "create_agreement"
    assert call[2].award.model_dump(mode="json") == award()
    assert call[2].buyer_task_id == "buyer-task-1"


async def test_agreement_create_rejects_a_run_mismatch(service):
    value, buyer = service
    request = VerifundTaskRequest(
        skill=VerifundSkill.AGREEMENT_CREATE,
        run_id="run-2",
        payload={"award": award(), "buyer_task_id": "buyer-task-1", "buyer_context_id": "run-1"},
        idempotency_key="agreement:run-2:offer-1",
    )
    result = await value.handle(request)
    assert result.status == "failed"
    assert "run" in result.message.lower()
    assert buyer.calls == []


async def test_status_returns_the_buyer_projection(service):
    value, buyer = service
    request = VerifundTaskRequest(
        skill=VerifundSkill.TRANSACTION_STATUS,
        run_id="run-1",
        transaction_id="vf_1",
        idempotency_key="status:run-1:vf_1",
    )
    result = await value.handle(request)
    assert result.status == "completed"
    assert result.state == "AGREED"
    assert result.data["projection"]["state"] == "AGREED"
    assert buyer.calls == [("get_settlement", "run-1")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -v`
Expected: FAIL with missing `verifund_agent.service`.

- [ ] **Step 3: Implement the service**

Replace `apps/verifund_agent/verifund_agent/service.py` with:

```python
from __future__ import annotations

from typing import Any

from verifund_contracts import (
    BuyerAgreementRequest,
    VerifundSkill,
    VerifundTaskRequest,
    VerifundTaskResult,
)

from verifund_agent.client import BuyerAPIError, BuyerInternalClient


class VerifundAgentService:
    def __init__(self, *, buyer: BuyerInternalClient) -> None:
        self.buyer = buyer

    async def handle(self, request: VerifundTaskRequest) -> VerifundTaskResult:
        try:
            if request.skill == VerifundSkill.AGREEMENT_CREATE:
                return await self._agreement_create(request)
            if request.skill == VerifundSkill.TRANSACTION_STATUS:
                return await self._transaction_status(request)
        except BuyerAPIError as exc:
            return self._failed(
                request,
                message=str(exc),
                retryable=exc.retryable,
            )
        return self._failed(request, message="unsupported Verifund skill")

    def _base(self, request: VerifundTaskRequest) -> dict[str, Any]:
        return {
            "skill": request.skill,
            "run_id": request.run_id,
            "transaction_id": request.transaction_id,
            "agreement_version": request.agreement_version,
            "agreement_hash": request.agreement_hash,
        }

    def _failed(
        self,
        request: VerifundTaskRequest,
        *,
        message: str,
        retryable: bool = False,
        next_action: str | None = None,
    ) -> VerifundTaskResult:
        return VerifundTaskResult(
            **self._base(request),
            status="failed",
            message=message,
            retryable=retryable,
            next_action=next_action,
        )

    async def _agreement_create(
        self, request: VerifundTaskRequest
    ) -> VerifundTaskResult:
        award = request.payload.get("award") or {}
        if award.get("run_id") != request.run_id:
            return self._failed(
                request, message="award run does not match the task run"
            )
        body = BuyerAgreementRequest(
            award=award,
            buyer_task_id=str(request.payload.get("buyer_task_id") or ""),
            buyer_context_id=str(request.payload.get("buyer_context_id") or ""),
            idempotency_key=request.idempotency_key,
        )
        response = await self.buyer.create_agreement(request.run_id, body)
        return VerifundTaskResult(
            **self._base(request),
            status="completed",
            transaction_id=response["transaction_id"],
            agreement_version=response["agreement_version"],
            agreement_hash=response["agreement_hash"],
            state=response["state"],
            data={
                "agreement": response["agreement"],
                "seller_token_ref": response["seller_token_ref"],
            },
            next_action="buyer_review",
            message="Canonical agreement created; resume the Buyer task for review.",
        )

    async def _transaction_status(
        self, request: VerifundTaskRequest
    ) -> VerifundTaskResult:
        view = await self.buyer.get_settlement(request.run_id)
        projection = view.get("projection") or {}
        return VerifundTaskResult(
            **self._base(request),
            status="completed",
            transaction_id=projection.get("transaction_id") or view.get("transaction_id"),
            agreement_version=projection.get("agreement_version") or view.get("agreement_version"),
            agreement_hash=projection.get("agreement_hash") or view.get("agreement_hash"),
            state=projection.get("state"),
            data={"projection": projection, "seller_token_ref": view.get("seller_token_ref")},
            message=f"Transaction is {projection.get('state', 'unknown')}.",
        )
```

`executor.py` calls `service.handle()` after parsing the envelope:

```python
        envelope = first_envelope(context.message)
        request = parse_verifund_task_request(envelope)
        result = await self.service.handle(request)
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=make_artifact("verifund-result", wrap_verifund_task_result(result)),
                last_chunk=True,
            )
        )
```

- [ ] **Step 4: Run the service tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py tests/unit/test_verifund_agent_package.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_agent/verifund_agent/{service.py,executor.py} tests/unit/test_verifund_agent_service.py
git commit -m "feat(verifund): create canonical agreements and report transaction status"
```

---

### Task 22D: Implement fund, evidence review, release, and receipt skills

**Files:**
- Modify: `apps/verifund_agent/verifund_agent/service.py`
- Test: `tests/unit/test_verifund_agent_settlement.py`

**Interfaces:**
- Produces: handlers for `verifund.transaction.fund`, `verifund.evidence.review`, `verifund.transaction.release`, `verifund.receipt.get`.
- `transaction.fund` accepts only `payload.funding_approval` validated by `FundingApprovalDecision`; `transaction.release` accepts only `payload.release_approval` validated by `ReleaseApprovalDecision`. Both must echo the request transaction/version/hash and never infer a decision from prose.
- `evidence.review` returns `next_action="release_approval"` only when the buyer projection is `RELEASE_PERMITTED` or `REVIEW_REQUIRED`; it never releases by itself.

- [ ] **Step 1: Write the failing skill tests**

`tests/unit/test_verifund_agent_settlement.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from verifund_agent.service import VerifundAgentService
from verifund_contracts import (
    FundingApprovalDecision,
    ReleaseApprovalDecision,
    VerifundSkill,
    VerifundTaskRequest,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


class Buyer:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def approve_funding(self, run_id, decision):
        self.calls.append(("fund", run_id, decision))
        return {
            "projection": {"state": "FUNDING_PENDING", "transaction_id": "vf_1"},
            "checkout_url": "http://paypal.test/checkout/1",
            "expires_at": "2026-10-27T12:30:00Z",
        }

    async def release(self, run_id, decision):
        self.calls.append(("release", run_id, decision))
        return {"state": "PAYOUT_PENDING", "transaction_id": "vf_1"}

    async def get_settlement(self, run_id):
        self.calls.append(("view", run_id))
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement_version": 1,
            "agreement_hash": HASH,
            "projection": {
                "state": "RELEASE_PERMITTED",
                "transaction_id": "vf_1",
                "evidence": {
                    "required": ["shipment_manifest", "delivery_confirmation"],
                    "received": ["shipment_manifest", "delivery_confirmation"],
                    "complete": True,
                    "items": [
                        {"evidence_id": "ev_1", "kind": "shipment_manifest"},
                        {"evidence_id": "ev_2", "kind": "delivery_confirmation"},
                    ],
                },
                "verification": {"status": "permitted", "reasons": []},
            },
        }

    async def receipt(self, run_id):
        self.calls.append(("receipt", run_id))
        return {"payload": {"transaction_id": "vf_1"}, "verified": True}


@pytest.fixture
def service():
    buyer = Buyer()
    return VerifundAgentService(buyer=buyer), buyer


def funding(**overrides) -> dict:
    payload = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "approved": True,
        "approved_by": "demo-reviewer",
        "note": "ok",
        "decided_at": NOW.isoformat(),
        "idempotency_key": "fund:run-1:vf_1",
    }
    payload.update(overrides)
    return payload


def release(**overrides) -> dict:
    payload = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "approved": True,
        "released_by": "demo-reviewer",
        "note": "verified",
        "override": False,
        "decided_at": NOW.isoformat(),
        "idempotency_key": "release:run-1:vf_1",
    }
    payload.update(overrides)
    return payload


async def test_fund_requires_a_structured_decision(service):
    value, buyer = service
    missing = VerifundTaskRequest(
        skill=VerifundSkill.TRANSACTION_FUND,
        run_id="run-1",
        transaction_id="vf_1",
        idempotency_key="fund:run-1:vf_1",
        payload={},
    )
    assert (await value.handle(missing)).status == "failed"
    assert buyer.calls == []

    request = VerifundTaskRequest(
        skill=VerifundSkill.TRANSACTION_FUND,
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        idempotency_key="fund:run-1:vf_1",
        payload={"funding_approval": funding()},
    )
    result = await value.handle(request)
    assert result.status == "completed"
    assert result.data["checkout_url"].startswith("http://paypal.test/")
    assert buyer.calls[0][0] == "fund"


async def test_fund_rejects_a_stale_hash(service):
    value, buyer = service
    request = VerifundTaskRequest(
        skill=VerifundSkill.TRANSACTION_FUND,
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        idempotency_key="fund:run-1:vf_1",
        payload={"funding_approval": funding(agreement_hash="b" * 64)},
    )
    result = await value.handle(request)
    assert result.status == "failed"
    assert buyer.calls == []


async def test_evidence_review_requests_a_separate_release_gate(service):
    value, _ = service
    request = VerifundTaskRequest(
        skill=VerifundSkill.EVIDENCE_REVIEW,
        run_id="run-1",
        transaction_id="vf_1",
        idempotency_key="evidence:run-1:vf_1",
        payload={},
    )
    result = await value.handle(request)
    assert result.status == "completed"
    assert result.next_action == "release_approval"
    assert result.data["evidence"]["complete"] is True
    assert result.data["verification"]["status"] == "permitted"


async def test_release_requires_the_release_decision(service):
    value, buyer = service
    request = VerifundTaskRequest(
        skill=VerifundSkill.TRANSACTION_RELEASE,
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        idempotency_key="release:run-1:vf_1",
        payload={"release_approval": release()},
    )
    result = await value.handle(request)
    assert result.status == "completed"
    assert result.state == "PAYOUT_PENDING"
    assert buyer.calls[0][0] == "release"


async def test_receipt_returns_the_buyer_verified_document(service):
    value, _ = service
    request = VerifundTaskRequest(
        skill=VerifundSkill.RECEIPT_GET,
        run_id="run-1",
        transaction_id="vf_1",
        idempotency_key="receipt:run-1:vf_1",
    )
    result = await value.handle(request)
    assert result.status == "completed"
    assert result.data["receipt"]["verified"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_agent_settlement.py -v`
Expected: FAIL because the four handlers return `unsupported Verifund skill`.

- [ ] **Step 3: Implement the handlers**

Add `FundingApprovalDecision` and `ReleaseApprovalDecision` to the
`verifund_contracts` import in `service.py`. Append to `VerifundAgentService`
the four handlers below, then extend the `handle` dispatch with these branches
immediately after `TRANSACTION_STATUS`:

```python
            if request.skill == VerifundSkill.TRANSACTION_FUND:
                return await self._transaction_fund(request)
            if request.skill == VerifundSkill.EVIDENCE_REVIEW:
                return await self._evidence_review(request)
            if request.skill == VerifundSkill.TRANSACTION_RELEASE:
                return await self._transaction_release(request)
            if request.skill == VerifundSkill.RECEIPT_GET:
                return await self._receipt_get(request)
```

Handlers:

```python
    def _require_decision_binding(
        self,
        request: VerifundTaskRequest,
        decision: FundingApprovalDecision | ReleaseApprovalDecision,
    ) -> str | None:
        if decision.run_id != request.run_id:
            return "decision run does not match the task run"
        if request.transaction_id and decision.transaction_id != request.transaction_id:
            return "decision transaction does not match the task transaction"
        if (
            request.agreement_version is not None
            and decision.agreement_version != request.agreement_version
        ):
            return "decision version does not match the task version"
        if request.agreement_hash and decision.agreement_hash != request.agreement_hash:
            return "decision hash does not match the task hash"
        return None

    async def _transaction_fund(
        self, request: VerifundTaskRequest
    ) -> VerifundTaskResult:
        raw = request.payload.get("funding_approval")
        if not isinstance(raw, dict):
            return self._failed(
                request, message="funding_approval is required", next_action="funding_approval"
            )
        try:
            decision = FundingApprovalDecision.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            return self._failed(request, message=f"invalid funding approval: {exc}")
        mismatch = self._require_decision_binding(request, decision)
        if mismatch:
            return self._failed(request, message=mismatch)
        result = await self.buyer.approve_funding(request.run_id, decision)
        projection = result.get("projection") or {}
        return VerifundTaskResult(
            **self._base(request),
            status="completed",
            transaction_id=decision.transaction_id,
            agreement_version=decision.agreement_version,
            agreement_hash=decision.agreement_hash,
            state=projection.get("state"),
            data={
                "projection": projection,
                "checkout_url": result.get("checkout_url"),
                "expires_at": result.get("expires_at"),
            },
            next_action="checkout" if result.get("checkout_url") else None,
            message="Funding approval recorded.",
        )

    async def _evidence_review(
        self, request: VerifundTaskRequest
    ) -> VerifundTaskResult:
        view = await self.buyer.get_settlement(request.run_id)
        projection = view.get("projection") or {}
        state = projection.get("state")
        next_action = (
            "release_approval"
            if state in {"RELEASE_PERMITTED", "REVIEW_REQUIRED"}
            else None
        )
        return VerifundTaskResult(
            **self._base(request),
            status="completed",
            transaction_id=projection.get("transaction_id") or view.get("transaction_id"),
            agreement_version=view.get("agreement_version"),
            agreement_hash=view.get("agreement_hash"),
            state=state,
            data={
                "evidence": projection.get("evidence"),
                "verification": projection.get("verification"),
                "allowed_actions": projection.get("allowed_actions", []),
            },
            next_action=next_action,
            message=(
                "Evidence is ready for a separate release decision."
                if next_action
                else "Evidence is not yet ready for release."
            ),
        )

    async def _transaction_release(
        self, request: VerifundTaskRequest
    ) -> VerifundTaskResult:
        raw = request.payload.get("release_approval")
        if not isinstance(raw, dict):
            return self._failed(
                request, message="release_approval is required", next_action="release_approval"
            )
        try:
            decision = ReleaseApprovalDecision.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            return self._failed(request, message=f"invalid release approval: {exc}")
        mismatch = self._require_decision_binding(request, decision)
        if mismatch:
            return self._failed(request, message=mismatch)
        projection = await self.buyer.release(request.run_id, decision)
        return VerifundTaskResult(
            **self._base(request),
            status="completed",
            transaction_id=decision.transaction_id,
            agreement_version=decision.agreement_version,
            agreement_hash=decision.agreement_hash,
            state=projection.get("state"),
            data={"projection": projection},
            message="Release decision submitted.",
        )

    async def _receipt_get(
        self, request: VerifundTaskRequest
    ) -> VerifundTaskResult:
        receipt = await self.buyer.receipt(request.run_id)
        return VerifundTaskResult(
            **self._base(request),
            status="completed",
            transaction_id=(receipt.get("payload") or {}).get("transaction_id")
            or request.transaction_id,
            data={"receipt": receipt},
            message="Verified receipt retrieved."
                if receipt.get("verified")
                else "Receipt retrieved but not verified.",
        )
```

`_transaction_fund` must not call `approve_funding` when `decision.approved` is
false? It must; the buyer route records the rejection and cancels. Keep it.

- [ ] **Step 4: Run the settlement skill tests**

Run: `uv run pytest tests/unit/test_verifund_agent_settlement.py tests/unit/test_verifund_agent_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_agent/verifund_agent/service.py tests/unit/test_verifund_agent_settlement.py
git commit -m "feat(verifund): add funding, evidence, release, and receipt skills"
```

---

### Task 22E: Add the Buyer `commerce.agreement.review` A2A entrypoint

Task 16A adds the card skill and graph checkpoints. This task makes the A2A
entrypoint strict: a review envelope may only resume an existing interrupted
Buyer task, the task/context IDs must match, and the graph must record the
Buyer's decision before any Seller review is requested.

**Files:**
- Create: `apps/buyer_agent/buyer_agent/review.py`
- Modify: `apps/buyer_agent/buyer_agent/executor.py`
- Test: `tests/protocol/test_buyer_agreement_review.py`

**Interfaces:**
- Produces: `parse_review_envelope(message) -> AgreementReviewRequest`; `resume_value(request) -> dict`.
- Consumes: `AgreementReviewRequest`, `parse_agreement_review_request`, and the buyer graph's `agreement` resume key.

- [ ] **Step 1: Write the failing protocol tests**

`tests/protocol/test_buyer_agreement_review.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from a2a.types.a2a_pb2 import Message, Role
from commerce_core.a2a_parts import make_message

from buyer_agent.review import parse_review_envelope, resume_value
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewRequest,
    wrap_agreement_review_request,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def agreement() -> AgreementProjection:
    payload = {
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "shipping_cents": 3400,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "created_at": "2026-10-27T12:00:00Z",
    }
    probe = AgreementProjection.model_construct(**payload, agreement_hash="0" * 64)
    return AgreementProjection(**payload, agreement_hash=probe.recompute_hash())


def message(**overrides) -> Message:
    request = AgreementReviewRequest(
        party="buyer",
        run_id="run-1",
        transaction_id="vf_1",
        agreement=agreement(),
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        requested_at=NOW,
        idempotency_key="review:vf_1:1",
    )
    payload = {**request.model_dump(mode="json"), **overrides}
    return make_message(
        role=Role.ROLE_USER,
        text="Buyer agreement review.",
        context_id="run-1",
        task_id="buyer-task-1",
        envelope=wrap_agreement_review_request(
            AgreementReviewRequest.model_validate(payload)
        ) if not overrides else {
            "schema": "https://marketmesh.example/extensions/verifund/v1/schemas/agreement-review-request.json",
            "schema_version": "1.0",
            "payload": payload,
        },
    )


def test_review_envelope_requires_the_original_buyer_task() -> None:
    request = parse_review_envelope(message())
    assert request.party == "buyer"
    assert request.buyer_task_id == "buyer-task-1"
    assert resume_value(request) == {
        "agreement": request.agreement.model_dump(mode="json")
    }


def test_review_envelope_rejects_a_seller_party() -> None:
    with pytest.raises(ValueError):
        parse_review_envelope(message(party="seller"))


def test_review_envelope_rejects_a_missing_envelope() -> None:
    with pytest.raises(ValueError):
        parse_review_envelope(
            Message(
                message_id="m1",
                role=Role.ROLE_USER,
                context_id="run-1",
                task_id="buyer-task-1",
                parts=[],
            )
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/protocol/test_buyer_agreement_review.py -v`
Expected: FAIL with missing `buyer_agent.review`.

- [ ] **Step 3: Implement the review entrypoint**

`apps/buyer_agent/buyer_agent/review.py`:

```python
from __future__ import annotations

from a2a.types.a2a_pb2 import Message
from commerce_core.a2a_parts import first_envelope
from verifund_contracts import (
    AgreementReviewRequest,
    parse_agreement_review_request,
)


def parse_review_envelope(message: Message) -> AgreementReviewRequest:
    envelope = first_envelope(message)
    if envelope is None:
        raise ValueError("agreement review requires a structured envelope")
    request = parse_agreement_review_request(envelope)
    if request.party != "buyer":
        raise ValueError("buyer agent cannot accept a seller review envelope")
    if not request.buyer_task_id or not request.buyer_context_id:
        raise ValueError("buyer review requires the original task and context")
    return request


def resume_value(request: AgreementReviewRequest) -> dict:
    return {"agreement": request.agreement.model_dump(mode="json")}
```

In `executor.py`, before the generic approval path:

```python
        envelope = first_envelope(context.message)
        if envelope is not None and envelope.get("schema", "").endswith(
            "/agreement-review-request.json"
        ):
            request = parse_review_envelope(context.message)
            if (
                request.buyer_task_id != (context.task_id or "")
                or request.buyer_context_id != (context.context_id or "")
            ):
                return self._failed(
                    context,
                    "agreement review does not match the interrupted Buyer task",
                )
            return await self._resume(
                context,
                Command(resume=resume_value(request)),
            )
```

If the executor has no `_failed`/`_resume` helpers, add small local helpers that
enqueue the same `TaskStatusUpdateEvent`/`Command(resume=...)` shapes used by the
existing approval and seller-result branches; do not duplicate the graph call.
The resume call must use the existing task/context configuration; it must not
create a new task. In the graph, `create_settlement_award` then validates the
terms, `report_buyer_review` records `POST /buyer-review`, and the task pauses
at `seller_review_required`.

- [ ] **Step 4: Run the protocol tests**

Run: `uv run pytest tests/protocol/test_buyer_agreement_review.py tests/protocol -k agreement -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/{review.py,executor.py} tests/protocol/test_buyer_agreement_review.py
git commit -m "feat(buyer): add the commerce.agreement.review A2A entrypoint"
```

---

### Task 22F: Add the Seller `commerce.agreement.review` skill

The Seller must validate the same agreement version/hash against its own offer
and stock, without changing terms or calling the control plane. Its decision is
a structured A2A artifact that the orchestrator relays to the Buyer.

**Files:**
- Create: `apps/seller_agent/seller_agent/agreement.py`
- Modify: `apps/seller_agent/seller_agent/{card.py,service.py}`
- Modify: `apps/seller_agent/pyproject.toml`
- Test: `tests/unit/test_seller_agreement_review.py`

**Interfaces:**
- Produces: `review_agreement(policy, store, request) -> AgreementReviewResult`; Seller Agent Card skill `commerce.agreement.review`.
- Consumes: `AgreementReviewRequest`, `AgreementReviewDecision`, `AgreementReviewResult`, `SellerPolicy`, `SellerStore.get_offer`, and `wrap_payload` is not used because this is a Verifund envelope.

- [ ] **Step 1: Write the failing Seller review tests**

`tests/unit/test_seller_agreement_review.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from commerce_core.contracts import Offer, OfferLineItem
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.agreement import review_agreement
from seller_agent.store import SellerStore
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewRequest,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def agreement(**overrides) -> AgreementProjection:
    payload = {
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "shipping_cents": 3400,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "created_at": "2026-10-27T12:00:00Z",
    }
    payload.update(overrides)
    probe = AgreementProjection.model_construct(**payload, agreement_hash="0" * 64)
    return AgreementProjection(**payload, agreement_hash=probe.recompute_hash())


def request(**overrides) -> AgreementReviewRequest:
    payload = {
        "party": "seller",
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement": agreement(),
        "seller_task_id": "seller-task-1",
        "seller_context_id": "run-1",
        "requested_at": NOW,
        "idempotency_key": "review:vf_1:1",
    }
    payload.update(overrides)
    return AgreementReviewRequest.model_validate(payload)


class Policy:
    seller_id = "northwind-audio"


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}")
    value = SellerStore(engine)
    await value.create_schema()
    yield value
    await engine.dispose()


async def test_accepts_a_matching_offer(store):
    offer = Offer(
        offer_id="offer-1",
        request_id="rfq-1",
        seller_id="northwind-audio",
        seller_name="Northwind Audio",
        seller_rating=4.8,
        line_items=[
            OfferLineItem(
                sku="NC-700",
                name="Nimbus NC-700 ANC Headset",
                quantity=12,
                unit_price_cents=10000,
                list_unit_price_cents=12000,
                warranty_addon_cents=0,
                attributes={"color": "graphite"},
            )
        ],
        subtotal_cents=120000,
        shipping_cents=3400,
        total_cents=123400,
        delivery_days=7,
        warranty_months=24,
        returns_days=30,
        valid_until=NOW,
    )
    await store.save_offer(offer, task_id="negotiation-task", context_id="run-1")
    result = await review_agreement(Policy(), store, request())
    assert result.status == "accepted"
    assert result.agreement_hash == request().agreement.agreement_hash
    assert result.party == "seller"


async def test_rejects_a_different_seller(store):
    result = await review_agreement(
        Policy(), store, request(agreement=agreement(seller_id="other"))
    )
    assert result.status == "rejected"
    assert result.reason_code == "terms_mismatch"


async def test_rejects_a_stale_transaction(store):
    result = await review_agreement(
        Policy(), store, request(transaction_id="vf_other")
    )
    assert result.status == "rejected"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_seller_agreement_review.py -v`
Expected: FAIL with missing `seller_agent.agreement`.

- [ ] **Step 3: Add the dependency and implementation**

Add `verifund-contracts` to `apps/seller_agent/pyproject.toml` and
`verifund-contracts = { workspace = true }` to its `[tool.uv.sources]`.

`apps/seller_agent/seller_agent/agreement.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from verifund_contracts import (
    AgreementReviewDecision,
    AgreementReviewRequest,
    AgreementReviewResult,
)


def _result(
    request: AgreementReviewRequest,
    *,
    status: AgreementReviewDecision,
    reason_code: str | None = None,
    note: str = "",
) -> AgreementReviewResult:
    return AgreementReviewResult(
        party="seller",
        status=status,
        run_id=request.run_id,
        transaction_id=request.transaction_id,
        agreement_version=request.agreement.agreement_version,
        agreement_hash=request.agreement.agreement_hash,
        task_id=request.seller_task_id or "",
        context_id=request.seller_context_id or "",
        reviewed_at=datetime.now(UTC),
        reason_code=reason_code,
        note=note,
    )


async def review_agreement(policy, store, request: AgreementReviewRequest) -> AgreementReviewResult:
    agreement = request.agreement
    if agreement.seller_id != policy.seller_id:
        return _result(
            request,
            status=AgreementReviewDecision.REJECTED,
            reason_code="terms_mismatch",
            note="Agreement seller does not match this seller.",
        )
    offer = await store.get_offer(agreement.offer_id)
    if offer is None:
        return _result(
            request,
            status=AgreementReviewDecision.REJECTED,
            reason_code="terms_mismatch",
            note="Offer is unknown to this seller.",
        )
    expected_lines = [
        (
            item.sku,
            item.name,
            item.quantity,
            item.unit_price_cents,
            item.warranty_addon_cents,
        )
        for item in agreement.line_items
    ]
    stored_lines = [
        (
            item.sku,
            item.name,
            item.quantity,
            item.unit_price_cents,
            item.warranty_addon_cents,
        )
        for item in offer.line_items
    ]
    if (
        offer.seller_id != policy.seller_id
        or offer.total_cents != agreement.amount_cents
        or offer.currency != agreement.currency
        or stored_lines != expected_lines
    ):
        return _result(
            request,
            status=AgreementReviewDecision.REJECTED,
            reason_code="terms_mismatch",
            note="Agreement terms do not match the stored offer.",
        )
    return _result(
        request,
        status=AgreementReviewDecision.ACCEPTED,
        note="Offer, quantity, and terms match.",
    )
```

Compare only the commercial terms shared by `AgreementProjection` and
`OfferLineItem`; the stored offer also carries `list_unit_price_cents` and
`attributes`, which are not part of the canonical agreement. The Seller returns
rejected for any mismatch and never mutates its offer/store.

- [ ] **Step 4: Dispatch the envelope before commerce parsing**

Import `parse_agreement_review_request` and `wrap_agreement_review_result`
from `verifund_contracts`, then in `SellerService.handle_turn`, try the Verifund
schema first, before `kind_from_envelope`:

```python
        envelope = first_envelope(message)
        if envelope is not None and envelope.get("schema", "").endswith(
            "/agreement-review-request.json"
        ):
            review = parse_agreement_review_request(envelope)
            result = await review_agreement(self.policy, self.store, review)
            return SellerTurn(
                task_state=TaskState.TASK_STATE_COMPLETED,
                artifacts=[
                    make_artifact(
                        "agreement-review",
                        wrap_agreement_review_result(result),
                    )
                ],
                message=(
                    "Agreement accepted."
                    if result.status == "accepted"
                    else "Agreement rejected."
                ),
            )
```

Add `commerce.agreement.review` to `build_agent_card` using the same skill
pattern as the Buyer.

- [ ] **Step 5: Run the Seller tests**

Run: `uv run pytest tests/unit/test_seller_agreement_review.py tests/unit tests/integration -k seller -v`
Expected: PASS. Commerce offer/order behavior is unchanged.

- [ ] **Step 6: Commit**

```bash
git add apps/seller_agent/pyproject.toml apps/seller_agent/seller_agent/{agreement.py,card.py,service.py} tests/unit/test_seller_agreement_review.py uv.lock
git commit -m "feat(seller): review Verifund agreements bound to stored offers"
```

---

### Task 22G: Route Verifund A2A tasks through the orchestrator

The orchestrator is the only component that coordinates the three agents. It
must call them sequentially, preserve the exact agreement/task correlation, and
never turn a pending/failed A2A result into consent.

**Files:**
- Create: `apps/orchestrator_agent/orchestrator_agent/verifund.py`
- Modify: `apps/orchestrator_agent/orchestrator_agent/{agent.py,settings.py}`
- Modify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts` only if the
  existing tool registry needs the new tool names exposed.
- Test: `tests/unit/test_orchestrator_verifund.py`

**Interfaces:**
- Produces: `VerifundA2AClient` (`create_agreement`, `status`, `fund`, `evidence_review`, `release`, `receipt`); `BuyerA2AAgents` (`resume_buyer`, `resume_buyer_with_seller`, `review_seller`); `AgreementCoordinator.run(run_id, buyer_task_id, buyer_context_id, award, buyer_a2a_url, seller_card_url, seller_id)` returning the agreement plus normalized `buyer_review`/`seller_decision` fields; orchestrator tools `verifund_create_agreement`, `verifund_status`, `verifund_fund`, `verifund_evidence_review`, `verifund_release`, `verifund_receipt`.
- Consumes: the agent card registered by Tasks 22A/26, `verifund_contracts` envelopes/decisions, `fetch_agent_card`, and the orchestrator `_a2a_send`/`_buyer_response`/seller-token helpers from `mediation.py`. The orchestrator uses the configured `VERIFUND_AGENT_CARD_URL`/`VERIFUND_AGENT_URL`; it never receives `REGISTRY_ADMIN_TOKEN` and does not call the admin-only registry discovery routes at runtime.

- [ ] **Step 1: Write the failing orchestrator tests**

`tests/unit/test_orchestrator_verifund.py`:

```python
from __future__ import annotations

import pytest

from verifund_contracts import AgreementProjection

from orchestrator_agent.settings import Settings
from orchestrator_agent.verifund import AgreementCoordinator


def agreement() -> dict:
    payload = {
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "currency": "USD",
        "amount_cents": 123400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "shipping_cents": 3400,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "created_at": "2026-10-27T12:00:00Z",
    }
    probe = AgreementProjection.model_construct(
        **payload, agreement_hash="0" * 64
    )
    return AgreementProjection(
        **payload, agreement_hash=probe.recompute_hash()
    ).model_dump(mode="json")


AGREEMENT_HASH = agreement()["agreement_hash"]


class Verifund:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def create_agreement(self, request):
        self.calls.append(("create", request))
        return {
            "status": "completed",
            "data": {
                "agreement": agreement(),
                "seller_token_ref": "run:run-1:transaction:vf_1",
            },
            "next_action": "buyer_review",
        }

    async def status(self, run_id):
        self.calls.append(("status", run_id))
        return {"status": "completed", "state": "AGREED"}


class Agents:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def resume_buyer(self, task_id, value):
        self.calls.append(("buyer", task_id, value))
        return {
            "status": "seller_review_required",
            "buyer_agent_review": {
                "status": "accepted",
                "agreement_hash": AGREEMENT_HASH,
            },
        }

    async def review_seller(self, card_url, request):
        self.calls.append(("seller", card_url, request))
        return {"status": "accepted", "agreement_hash": AGREEMENT_HASH}

    async def resume_buyer_with_seller(self, task_id, decision):
        self.calls.append(("buyer_seller", task_id, decision))
        return {
            "status": "funding_approval_required",
            "buyer_agent_review": {
                "status": "accepted",
                "agreement_hash": AGREEMENT_HASH,
            },
            "seller_decision": decision,
        }


def test_settings_default_to_a_disabled_mode(monkeypatch):
    monkeypatch.delenv("VERIFUND_MODE", raising=False)
    settings = Settings()
    assert settings.verifund_mode == "off"
    assert settings.verifund_agent_url.endswith(":9301")
    assert settings.verifund_agent_a2a_token


async def test_coordinator_runs_buyer_seller_buyer_in_order():
    verifund = Verifund()
    agents = Agents()
    coordinator = AgreementCoordinator(verifund=verifund, agents=agents)
    result = await coordinator.run(
        run_id="run-1",
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        award={"run_id": "run-1"},
        buyer_a2a_url="http://buyer",
        seller_card_url="http://seller/.well-known/agent-card.json",
        seller_id="northwind-audio",
    )
    assert [call[0] for call in verifund.calls] == ["create"]
    assert [call[0] for call in agents.calls] == ["buyer", "seller", "buyer_seller"]
    envelope = agents.calls[1][2]
    assert envelope["payload"]["seller_task_id"].startswith("agreement-review:")
    assert envelope["payload"]["seller_context_id"] == "run-1"
    assert result["buyer_status"] == "funding_approval_required"
    assert result["seller_status"] == "accepted"
    assert result["funding_hitl"] is True
    assert result["buyer_review"]["status"] == "accepted"
    assert result["seller_decision"]["status"] == "accepted"
    assert result["agreement_hash"] == AGREEMENT_HASH


async def test_coordinator_never_opens_funding_after_seller_rejection():
    verifund = Verifund()
    agents = Agents()
    agents.review_seller = lambda *args, **kwargs: _rejected()
    coordinator = AgreementCoordinator(verifund=verifund, agents=agents)
    result = await coordinator.run(
        run_id="run-1",
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        award={"run_id": "run-1"},
        buyer_a2a_url="http://buyer",
        seller_card_url="http://seller/.well-known/agent-card.json",
        seller_id="northwind-audio",
    )
    assert result["funding_hitl"] is False
    assert result["seller_status"] == "rejected"
    assert [call[0] for call in agents.calls] == ["buyer", "seller"]


async def _rejected():
    return {"status": "rejected", "agreement_hash": "a" * 64}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_orchestrator_verifund.py -v`
Expected: FAIL with missing `orchestrator_agent.verifund` and Settings fields.

- [ ] **Step 3: Add orchestrator settings**

Append to `Settings`:

```python
    verifund_mode: str = Field(
        default="off",
        validation_alias=AliasChoices("VERIFUND_MODE"),
    )
    verifund_agent_url: str = Field(
        default="http://127.0.0.1:9301",
        validation_alias=AliasChoices("VERIFUND_AGENT_URL"),
    )
    verifund_agent_a2a_token: str = Field(
        default="dev-verifund-agent-a2a",
        validation_alias=AliasChoices("VERIFUND_AGENT_A2A_TOKEN"),
    )
    verifund_agent_card_url: str = Field(
        default="http://127.0.0.1:9301/.well-known/agent-card.json",
        validation_alias=AliasChoices("VERIFUND_AGENT_CARD_URL"),
    )
    verifund_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("VERIFUND_AGENT_TIMEOUT_SECONDS"),
    )
```

`verifund_mode` must default to `off` and the A2A calls must be unreachable in
that mode.

- [ ] **Step 4: Implement the Verifund client and coordinator**

`apps/orchestrator_agent/orchestrator_agent/verifund.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types.a2a_pb2 import Role, SendMessageRequest
from commerce_core.a2a_parts import make_message, part_value
from commerce_core.cards import fetch_agent_card
from orchestrator_agent.mediation import (
    _a2a_send,
    _buyer_response,
    _resolve_seller_token,
)
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewRequest,
    AgreementReviewResult,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
    VerifundSkill,
    VerifundTaskRequest,
    VerifundTaskResult,
    parse_agreement_review_result,
    parse_verifund_task_result,
    wrap_agreement_review_request,
    wrap_agreement_review_result,
    wrap_verifund_task_request,
)


class VerifundA2AClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = 60.0,
        card_url: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.card_url = card_url or f"{self.base_url}/.well-known/agent-card.json"

    async def _send(self, envelope: dict) -> dict[str, Any]:
        card = await fetch_agent_card(
            self.card_url, allowed_hosts=("127.0.0.1", "localhost", "verifund-agent", "host.docker.internal")
        )
        http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=httpx.Timeout(self.timeout, connect=5.0),
        )
        client = ClientFactory(ClientConfig(streaming=True, httpx_client=http)).create(card)
        message = make_message(
            role=Role.ROLE_USER,
            text="Verifund task.",
            context_id="orchestrator",
            envelope=envelope,
        )
        result: dict[str, Any] | None = None
        try:
            async for frame in client.send_message(SendMessageRequest(message=message)):
                kind = frame.WhichOneof("payload")
                artifacts = []
                if kind == "artifact_update":
                    artifacts = [frame.artifact_update.artifact]
                elif kind == "task":
                    artifacts = list(frame.task.artifacts)
                for artifact in artifacts:
                    for part in artifact.parts:
                        value = part_value(part)
                        if isinstance(value, dict):
                            result = parse_verifund_task_result(value).model_dump(mode="json")
        finally:
            await client.close()
            await http.aclose()
        if result is None:
            raise RuntimeError("Verifund returned no structured result")
        return result

    async def _task(
        self,
        skill: VerifundSkill,
        *,
        run_id: str,
        transaction_id: str | None = None,
        agreement_version: int | None = None,
        agreement_hash: str | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = VerifundTaskRequest(
            skill=skill,
            run_id=run_id,
            transaction_id=transaction_id,
            agreement_version=agreement_version,
            agreement_hash=agreement_hash,
            payload=payload or {},
            idempotency_key=idempotency_key,
        )
        return await self._send(wrap_verifund_task_request(request))

    async def create_agreement(self, request: VerifundTaskRequest) -> dict[str, Any]:
        return await self._send(wrap_verifund_task_request(request))

    async def status(self, run_id: str, **kwargs) -> dict[str, Any]:
        return await self._task(VerifundSkill.TRANSACTION_STATUS, run_id=run_id, **kwargs)

    async def fund(self, run_id: str, decision: FundingApprovalDecision, **kwargs) -> dict[str, Any]:
        return await self._task(
            VerifundSkill.TRANSACTION_FUND,
            run_id=run_id,
            transaction_id=decision.transaction_id,
            agreement_version=decision.agreement_version,
            agreement_hash=decision.agreement_hash,
            payload={"funding_approval": decision.model_dump(mode="json")},
            idempotency_key=decision.idempotency_key,
        )

    async def evidence_review(self, run_id: str, transaction_id: str, **kwargs) -> dict[str, Any]:
        return await self._task(
            VerifundSkill.EVIDENCE_REVIEW,
            run_id=run_id,
            transaction_id=transaction_id,
            **kwargs,
        )

    async def release(self, run_id: str, decision: ReleaseApprovalDecision, **kwargs) -> dict[str, Any]:
        return await self._task(
            VerifundSkill.TRANSACTION_RELEASE,
            run_id=run_id,
            transaction_id=decision.transaction_id,
            agreement_version=decision.agreement_version,
            agreement_hash=decision.agreement_hash,
            payload={"release_approval": decision.model_dump(mode="json")},
            idempotency_key=decision.idempotency_key,
        )

    async def receipt(self, run_id: str, transaction_id: str, **kwargs) -> dict[str, Any]:
        return await self._task(
            VerifundSkill.RECEIPT_GET,
            run_id=run_id,
            transaction_id=transaction_id,
            **kwargs,
        )


class BuyerA2AAgents:
    """Resume the original Buyer task and call the Seller review skill."""

    def __init__(self, *, buyer_a2a_url: str) -> None:
        self.buyer_a2a_url = buyer_a2a_url.rstrip("/")
        self._buyer_contexts: dict[str, str] = {}

    async def _send(
        self,
        *,
        task_id: str,
        context_id: str,
        envelope: dict[str, Any],
        text: str,
    ) -> dict[str, Any]:
        message = make_message(
            role=Role.ROLE_USER,
            text=text,
            context_id=context_id,
            task_id=task_id,
            envelope=envelope,
        )
        frames = await _a2a_send(self.buyer_a2a_url, message)
        response = _buyer_response(frames)
        if response is None:
            raise RuntimeError("Buyer returned no structured response")
        return response

    async def resume_buyer(
        self, task_id: str, value: dict[str, Any]
    ) -> dict[str, Any]:
        agreement = AgreementProjection.model_validate(value["agreement"])
        buyer_context = str(value.get("buyer_context_id") or agreement.run_id)
        request = AgreementReviewRequest(
            party="buyer",
            run_id=agreement.run_id,
            transaction_id=agreement.transaction_id,
            agreement=agreement,
            buyer_task_id=task_id,
            buyer_context_id=buyer_context,
            requested_at=datetime.now(UTC),
            idempotency_key=(
                f"review:{agreement.transaction_id}:"
                f"{agreement.agreement_version}"
            ),
        )
        self._buyer_contexts[task_id] = buyer_context
        return await self._send(
            task_id=task_id,
            context_id=buyer_context,
            envelope=wrap_agreement_review_request(request),
            text="Buyer agreement review.",
        )

    async def resume_buyer_with_seller(
        self, task_id: str, decision: dict[str, Any]
    ) -> dict[str, Any]:
        result = AgreementReviewResult.model_validate(decision)
        context_id = self._buyer_contexts.get(task_id, result.run_id)
        return await self._send(
            task_id=task_id,
            context_id=context_id,
            envelope=wrap_agreement_review_result(result),
            text="Seller agreement review.",
        )

    async def review_seller(
        self, seller_card_url: str, envelope: dict[str, Any]
    ) -> dict[str, Any]:
        payload = envelope.get("payload") or {}
        agreement = payload.get("agreement") or {}
        seller_id = str(agreement.get("seller_id") or "") or None
        seller_base = seller_card_url.split("/.well-known")[0]
        message = make_message(
            role=Role.ROLE_USER,
            text="Verifund agreement review.",
            context_id=str(
                payload.get("seller_context_id")
                or agreement.get("run_id")
                or ""
            ),
            envelope=envelope,
        )
        frames = await _a2a_send(
            seller_base,
            message,
            token=_resolve_seller_token(seller_card_url, None, seller_id),
        )
        result = None
        for frame in frames:
            kind = frame.WhichOneof("payload")
            artifacts = []
            if kind == "artifact_update":
                artifacts = [frame.artifact_update.artifact]
            elif kind == "task":
                artifacts = list(frame.task.artifacts)
            for artifact in artifacts:
                for part in artifact.parts:
                    value = part_value(part)
                    if isinstance(value, dict):
                        result = parse_agreement_review_result(value).model_dump(
                            mode="json"
                        )
        if result is None:
            raise RuntimeError("Seller returned no structured agreement review")
        return result


class AgreementCoordinator:
    def __init__(self, *, verifund, agents=None) -> None:
        self.verifund = verifund
        self.agents = agents

    async def run(
        self,
        *,
        run_id: str,
        buyer_task_id: str,
        buyer_context_id: str,
        award: dict[str, Any],
        buyer_a2a_url: str,
        seller_card_url: str,
        seller_id: str,
    ) -> dict[str, Any]:
        agents = self.agents or BuyerA2AAgents(buyer_a2a_url=buyer_a2a_url)
        created = await self.verifund.create_agreement(
            VerifundTaskRequest(
                skill=VerifundSkill.AGREEMENT_CREATE,
                run_id=run_id,
                payload={
                    "award": award,
                    "buyer_task_id": buyer_task_id,
                    "buyer_context_id": buyer_context_id,
                },
                idempotency_key=f"agreement:{run_id}:{award.get('offer_id')}",
            )
        )
        if created["status"] != "completed":
            return {
                "buyer_status": None,
                "seller_status": None,
                "funding_hitl": False,
                "error": created.get("message"),
            }
        agreement = created["data"]["agreement"]
        buyer = await agents.resume_buyer(
            buyer_task_id,
            {
                "agreement": agreement,
                "seller_token_ref": created["data"]["seller_token_ref"],
                "buyer_context_id": buyer_context_id,
            },
        )
        if buyer.get("status") != "seller_review_required":
            return {
                "buyer_status": buyer.get("status"),
                "seller_status": None,
                "funding_hitl": False,
                "agreement": agreement,
                "buyer_review": buyer.get("buyer_agent_review"),
                "error": buyer.get("message"),
            }
        seller_task_id = (
            f"agreement-review:{agreement['transaction_id']}:"
            f"{agreement['agreement_version']}"
        )
        seller_request = AgreementReviewRequest(
            party="seller",
            run_id=run_id,
            transaction_id=agreement["transaction_id"],
            agreement=agreement,
            seller_task_id=seller_task_id,
            seller_context_id=run_id,
            requested_at=datetime.now(UTC),
            idempotency_key=f"review:{agreement['transaction_id']}:{agreement['agreement_version']}",
        )
        seller = await agents.review_seller(
            seller_card_url, wrap_agreement_review_request(seller_request)
        )
        if seller.get("status") != "accepted":
            return {
                "buyer_status": buyer.get("status"),
                "seller_status": seller.get("status"),
                "funding_hitl": False,
                "agreement": agreement,
                "buyer_review": buyer.get("buyer_agent_review"),
                "seller_decision": seller,
                "transaction_id": agreement["transaction_id"],
                "agreement_version": agreement["agreement_version"],
                "agreement_hash": agreement["agreement_hash"],
            }
        resumed = await agents.resume_buyer_with_seller(
            buyer_task_id, seller
        )
        return {
            "buyer_status": resumed.get("status"),
            "seller_status": "accepted",
            "funding_hitl": resumed.get("status") == "funding_approval_required",
            "agreement": agreement,
            "buyer_review": (
                resumed.get("buyer_agent_review")
                or buyer.get("buyer_agent_review")
            ),
            "seller_decision": resumed.get("seller_decision") or seller,
            "transaction_id": agreement["transaction_id"],
            "agreement_version": agreement["agreement_version"],
            "agreement_hash": agreement["agreement_hash"],
        }
```

Replace the `__import__` calls with normal `datetime` imports. The
`seller_task_id` is a deterministic agreement-review correlation ID carried in
the envelope; the orchestrator does not pre-create an A2A task. `resume_buyer`
must send the canonical agreement envelope to the existing Buyer task, and
`review_seller` must send the `AgreementReviewRequest` envelope and validate the
returned `AgreementReviewResult` against the same transaction/version/hash. Do
not send `seller_task_id` as the A2A `task_id`; the Seller echoes the correlation
ID in its result. `BuyerA2AAgents` is the production adapter: `resume_buyer`
sends a wrapped `AgreementReviewRequest` (task 22E's strict entrypoint) to the
original Buyer task/context, `resume_buyer_with_seller` sends a wrapped
`AgreementReviewResult`, and `review_seller` resolves the Seller bearer token
from the agreement's `seller_id`. The coordinator normalizes the Buyer's
`buyer_agent_review` field to `buyer_review` so the console HITL args match the
Buyer's structured review, and includes the resulting `seller_decision`.

- [ ] **Step 5: Register the tools and guard funding**

In `agent.py`, add six `FunctionTool` wrappers and extend the instruction text:

```text
- Call verifund_create_agreement after the Buyer pauses with
  agreement_create_required. Pass the exact award and original Buyer task IDs.
- Resume the Buyer task with the returned agreement before calling the Seller.
- Call the Seller commerce.agreement.review skill only after the Buyer accepts.
- Never render the funding HITL unless the Buyer resumed with
  funding_approval_required after the Seller accepted. Pass the Buyer's
  `buyer_agent_review` as `buyer_review` and its `seller_decision` unchanged;
  do not reconstruct either review from chat text.
- Call verifund_fund only with the structured FundingApprovalDecision returned
  by useHumanInTheLoop; call verifund_release only with the structured
  ReleaseApprovalDecision.
- Treat pending, input-required, failed, or malformed results as non-success.
```

The funding tool must reject a missing/invalid `FundingApprovalDecision` and the
release tool must reject a missing/invalid `ReleaseApprovalDecision`; free-form
chat text never authorizes either call.

- [ ] **Step 6: Run the orchestrator tests**

Run: `uv run pytest tests/unit/test_orchestrator_verifund.py tests/unit tests/protocol -k "orchestrator or agreement" -v`
Expected: PASS. Existing sourcing and seller mediation tests still pass.

- [ ] **Step 7: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/{verifund.py,agent.py,settings.py} tests/unit/test_orchestrator_verifund.py
git commit -m "feat(orchestrator): route Verifund agreement and settlement tasks sequentially"
```

## Phase 4 — Transaction Room console

### Task 23: Console settlement types, shared stages, API client, and proxy routes

**Files:**
- Modify: `apps/console/lib/types.ts`
- Create: `apps/console/lib/stages.ts`
- Modify: `apps/console/lib/format.ts`
- Modify: `apps/console/lib/api.ts`
- Create: `apps/console/lib/buyer-proxy.ts`
- Modify: `apps/console/app/api/runs/[runId]/route.ts`
- Create: `apps/console/app/api/runs/[runId]/settlement/route.ts`
- Create: `apps/console/app/api/runs/[runId]/settlement/advance/route.ts`
- Create: `apps/console/app/api/runs/[runId]/settlement/release/route.ts`
- Create: `apps/console/app/api/runs/[runId]/settlement/review/route.ts`
- Create: `apps/console/app/api/runs/[runId]/settlement/cancel/route.ts`
- Create: `apps/console/app/api/runs/[runId]/settlement/receipt/route.ts`
- Create: `apps/console/app/api/runs/[runId]/settlement/evidence/[evidenceId]/route.ts`
- Test: `apps/console/lib/stages.test.ts`

**Interfaces:**
- Produces: `SettlementProjection`, `SettlementReceipt`, `SettlementEvidenceItem`, `SettlementReviewReason`, `CancelReasonCode`; `isTerminalStage(stage, settlement)`, `isPausedStage(stage)`, `stageLabel(stage)`; `fetchSettlement`, `advanceSettlement`, `releaseSettlement`, `reviewSettlement`, `cancelSettlement`, `fetchSettlementReceipt`, `settlementEvidenceUrl`; same-origin proxy routes that add `x-marketmesh-console-token` server-side.
- Consumes: buyer settlement API from Task 17, `BUYER_API_URL`, `BUYER_CONSOLE_API_TOKEN`.

- [ ] **Step 1: Write the failing stage-helper tests**

`apps/console/lib/stages.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  isPausedStage,
  isTerminalStage,
  stageLabel,
} from "./stages";

describe("settlement stages", () => {
  it("labels buyer and settlement stages", () => {
    expect(stageLabel("funding_pending")).toBe("Funding pending");
    expect(stageLabel("verification_pending")).toBe(
      "Verification pending",
    );
    expect(stageLabel("review_required")).toBe("Review required");
    expect(stageLabel("released")).toBe("Released");
    expect(stageLabel("ordered")).toBe("Ordered");
  });

  it("treats released and canceled as terminal in settlement mode", () => {
    expect(isTerminalStage("released", true)).toBe(true);
    expect(isTerminalStage("canceled", true)).toBe(true);
    expect(isTerminalStage("failed", true)).toBe(true);
    expect(isTerminalStage("verification_pending", true)).toBe(false);
    expect(isTerminalStage("review_required", true)).toBe(false);
  });

  it("keeps ordered terminal only in legacy mode", () => {
    expect(isTerminalStage("ordered", false)).toBe(true);
    expect(isTerminalStage("ordered", true)).toBe(false);
  });

  it("marks human and provider pauses", () => {
    expect(isPausedStage("awaiting_approval")).toBe(true);
    expect(isPausedStage("funding_pending")).toBe(true);
    expect(isPausedStage("release_permitted")).toBe(true);
    expect(isPausedStage("review_required")).toBe(true);
    expect(isPausedStage("funded")).toBe(false);
    expect(isPausedStage("released")).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/console && npm test -- lib/stages.test.ts`
Expected: FAIL with `Cannot find module './stages'`.

- [ ] **Step 3: Add shared stage helpers**

`apps/console/lib/stages.ts`:

```ts
const LABELS: Record<string, string> = {
  new: "Brief",
  brief_ready: "Brief parsed",
  needs_clarification: "Brief needed",
  sellers_discovered: "Sellers discovered",
  sourcing_planned: "RFQ composed",
  negotiating: "Negotiating",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  rejected: "Rejected",
  ordering: "Ordering",
  ordered: "Ordered",
  order_failed: "Order failed",
  no_award: "No award",
  failed: "Failed",
  awarded: "Awarded",
  agreed: "Agreed",
  funding_pending: "Funding pending",
  funded: "Funded",
  fulfillment_pending: "Fulfillment pending",
  verification_pending: "Verification pending",
  release_permitted: "Release permitted",
  payout_pending: "Payout pending",
  released: "Released",
  review_required: "Review required",
  canceled: "Canceled",
};

export const LEGACY_TERMINAL_STAGES = new Set([
  "ordered",
  "rejected",
  "failed",
  "order_failed",
  "no_award",
]);

export const SETTLEMENT_TERMINAL_STAGES = new Set([
  "released",
  "canceled",
  "failed",
  "rejected",
  "no_award",
]);

export const PAUSED_STAGES = new Set([
  "awaiting_approval",
  "funding_pending",
  "verification_pending",
  "release_permitted",
  "review_required",
]);

export function stageLabel(stage?: string): string {
  return LABELS[(stage ?? "new").toLowerCase()] ?? "Brief";
}

export function isTerminalStage(
  stage?: string,
  settlement = false,
): boolean {
  if (!stage) return false;
  const normalized = stage.toLowerCase();
  if (settlement) {
    return SETTLEMENT_TERMINAL_STAGES.has(normalized);
  }
  return LEGACY_TERMINAL_STAGES.has(normalized);
}

export function isPausedStage(stage?: string): boolean {
  return PAUSED_STAGES.has((stage ?? "").toLowerCase());
}
```

In `format.ts`, remove the local `stageLabel` definition and re-export the shared helper:

```ts
export { stageLabel } from "./stages";
```

- [ ] **Step 4: Add the settlement types**

Append to `apps/console/lib/types.ts`:

```ts
export type SettlementState =
  | "AWARDED"
  | "AGREED"
  | "FUNDING_PENDING"
  | "FUNDED"
  | "FULFILLMENT_PENDING"
  | "VERIFICATION_PENDING"
  | "RELEASE_PERMITTED"
  | "PAYOUT_PENDING"
  | "RELEASED"
  | "REVIEW_REQUIRED"
  | "CANCELED"
  | "FAILED";

export type SettlementReviewReason =
  | "missing_evidence"
  | "invalid_evidence_hash"
  | "seller_mismatch"
  | "agreement_mismatch"
  | "tracking_mismatch"
  | "delivery_in_future"
  | "inspection_not_elapsed"
  | "funding_mismatch"
  | "evidence_deadline_missed"
  | "ledger_incomplete"
  | "manual_flag"
  | "late_capture";

export type CancelReasonCode =
  | "buyer_rejected"
  | "buyer_cancelled"
  | "reviewer_cancelled";

export type SettlementEvidenceItem = {
  evidence_id: string;
  kind: string;
  sha256: string;
  media_type: string;
  size_bytes: number;
  original_filename: string;
  note?: string | null;
  created_at: string;
};

export type SettlementProjection = {
  transaction_id: string;
  run_id: string;
  state: SettlementState;
  last_seq: number;
  amount_cents: number;
  currency: string;
  buyer_id: string;
  seller_id: string;
  agreement_hash: string;
  agreement_version: number;
  seller_decision: {
    status: string;
    reported_at: string;
    reason_code?: string | null;
    note?: string | null;
  } | null;
  approval: {
    approved_by: string;
    approved_at: string;
    note?: string | null;
  } | null;
  cancellation: {
    reason_code: string;
    note?: string | null;
    at: string;
  } | null;
  funding: {
    status: string;
    provider_order_id?: string | null;
    capture_id?: string | null;
    payer_action_url?: string | null;
    completed_at?: string | null;
  } | null;
  purchase_order: {
    seller_order_id: string;
    tracking_number?: string | null;
    carrier?: string | null;
    eta?: string | null;
  } | null;
  evidence: {
    required: string[];
    received: string[];
    complete: boolean;
    deadline?: string | null;
    items: SettlementEvidenceItem[];
  } | null;
  verification: {
    status: string;
    reasons: string[];
    checked_at?: string | null;
    override_allowed: boolean;
  } | null;
  payout: {
    status: string;
    batch_id?: string | null;
    item_id?: string | null;
    amount_cents?: number | null;
    updated_at?: string | null;
  } | null;
  receipt_available: boolean;
  deadlines: {
    evidence?: string | null;
    inspection?: string | null;
  };
  allowed_actions: string[];
  updated_at: string;
  settlement_unavailable?: boolean;
};

export type SettlementReceipt = {
  payload: {
    receipt_version: number;
    transaction_id: string;
    agreement_hash: string;
    amount_cents: number;
    currency: string;
    buyer_id: string;
    seller_id: string;
    capture_id: string;
    payout_item_id: string;
    evidence_hashes: string[];
    released_at: string;
  };
  payload_hash: string;
  signature: string;
  kid: string;
  verified: boolean;
};

export type SettlementResponse = {
  run_id: string;
  settlement: SettlementProjection;
  interrupt?: Record<string, unknown> | null;
};
```

Extend `BuyerState` with:

```ts
  settlement?: SettlementProjection | null;
  settlement_receipt?: SettlementReceipt | null;
```

Extend `SellerDashboard` with:

```ts
  settlement?: Array<{
    transaction_id: string;
    seller_id: string;
    state: string;
    amount_cents?: number | null;
    currency?: string | null;
    deadlines?: { evidence?: string | null; inspection?: string | null };
    evidence?: SettlementProjection["evidence"];
    unavailable?: boolean;
  }>;
```

- [ ] **Step 5: Add the client API functions**

In `apps/console/lib/api.ts`, import the settlement types:

```ts
import type {
  CancelReasonCode,
  SettlementProjection,
  SettlementReceipt,
  SettlementResponse,
  SettlementReviewReason,
} from "./types";
```

Add:

```ts
async function settlementJson<T>(
  runId: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(
    `/api/runs/${encodeURIComponent(runId)}/settlement${path}`,
    {
      ...init,
      cache: "no-store",
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    },
  );
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Settlement request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export function fetchSettlement(runId: string) {
  return settlementJson<SettlementProjection>(runId, "");
}

export function advanceSettlement(runId: string) {
  return settlementJson<SettlementResponse>(runId, "/advance", {
    method: "POST",
    body: JSON.stringify({ action: "refresh" }),
  });
}

export function releaseSettlement(
  runId: string,
  body: { released_by: string; note?: string; override?: boolean },
) {
  return settlementJson<SettlementResponse>(runId, "/release", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function reviewSettlement(
  runId: string,
  body: {
    action: "flag_review" | "retry_payout";
    reason?: SettlementReviewReason;
    note?: string;
  },
) {
  return settlementJson<SettlementResponse>(runId, "/review", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function cancelSettlement(
  runId: string,
  body: { reason_code: CancelReasonCode; note?: string },
) {
  return settlementJson<SettlementResponse>(runId, "/cancel", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function fetchSettlementReceipt(runId: string) {
  return settlementJson<SettlementReceipt>(runId, "/receipt");
}

export function settlementEvidenceUrl(
  runId: string,
  evidenceId: string,
): string {
  return `/api/runs/${encodeURIComponent(runId)}/settlement/evidence/${encodeURIComponent(evidenceId)}`;
}
```

Also add `settlement?: SettlementProjection;` to the local `BuyerRun` type.

- [ ] **Step 6: Add the server-side buyer proxy helper**

`apps/console/lib/buyer-proxy.ts`:

```ts
import { NextResponse } from "next/server";

const BUYER = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
const CONSOLE_TOKEN =
  process.env.BUYER_CONSOLE_API_TOKEN ?? "dev-console";

function headers(extra?: HeadersInit): Headers {
  const value = new Headers(extra);
  value.set("x-marketmesh-console-token", CONSOLE_TOKEN);
  return value;
}

export async function buyerJson(
  path: string,
  init: RequestInit = {},
  timeoutMs = 10_000,
): Promise<Response> {
  try {
    const response = await fetch(`${BUYER}${path}`, {
      ...init,
      cache: "no-store",
      headers: headers(init.headers),
      signal: AbortSignal.timeout(timeoutMs),
    });
    const contentType =
      response.headers.get("content-type") ?? "application/json";
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": contentType },
    });
  } catch {
    return NextResponse.json(
      { error: "Buyer API is unavailable" },
      { status: 503 },
    );
  }
}

export async function buyerBinary(
  path: string,
  timeoutMs = 10_000,
): Promise<Response> {
  try {
    const response = await fetch(`${BUYER}${path}`, {
      cache: "no-store",
      headers: headers(),
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) {
      return new Response(await response.text(), {
        status: response.status,
        headers: {
          "content-type":
            response.headers.get("content-type") ?? "application/json",
        },
      });
    }
    const output = new Headers();
    output.set(
      "content-type",
      response.headers.get("content-type") ?? "application/octet-stream",
    );
    const disposition = response.headers.get("content-disposition");
    if (disposition) output.set("content-disposition", disposition);
    return new Response(await response.arrayBuffer(), {
      status: response.status,
      headers: output,
    });
  } catch {
    return NextResponse.json(
      { error: "Buyer API is unavailable" },
      { status: 503 },
    );
  }
}
```

- [ ] **Step 7: Replace the run proxy and add settlement proxies**

`apps/console/app/api/runs/[runId]/route.ts` becomes:

```ts
import type { NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  return buyerJson(
    `/api/runs/${encodeURIComponent(runId)}`,
    {},
    8_000,
  );
}
```

Create the settlement collection route:

```ts
import type { NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  return buyerJson(
    `/api/runs/${encodeURIComponent(runId)}/settlement`,
  );
}
```

Create a small POST proxy body type in each route file. The advance route:

```ts
import { type NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const body = (await request.text()) || JSON.stringify({ action: "refresh" });
  return buyerJson(
    `/api/runs/${encodeURIComponent(runId)}/settlement/advance`,
    { method: "POST", body, headers: { "content-type": "application/json" } },
  );
}
```

The release, review, and cancel routes are identical apart from the final path segment (`release`, `review`, `cancel`) and must forward the request body unchanged. Create all three with the same shape.

The receipt route:

```ts
import type { NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  return buyerJson(
    `/api/runs/${encodeURIComponent(runId)}/settlement/receipt`,
  );
}
```

The evidence route:

```ts
import type { NextRequest } from "next/server";
import { buyerBinary } from "@/lib/buyer-proxy";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string; evidenceId: string }> },
) {
  const { runId, evidenceId } = await params;
  return buyerBinary(
    `/api/runs/${encodeURIComponent(runId)}/settlement/evidence/${encodeURIComponent(evidenceId)}`,
  );
}
```

The browser never receives `BUYER_CONSOLE_API_TOKEN`; the proxy adds it on the server.

- [ ] **Step 8: Run the console unit tests and typecheck**

Run: `cd apps/console && npm test -- lib/stages.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/console/lib apps/console/app/api/runs
git commit -m "feat(console): add settlement types, stage helpers, and buyer proxies"
```

---

### Task 24: Transaction Room components

**Chat-first amendment (normative):** the Transaction Room is a synchronized,
read-only settlement detail view. Funding approval and payout release controls
belong in the chat HITL cards from Task 25A. Any `onAdvance`, `onRelease`, or
button-driven approval/release example below is superseded: replace it with
status, checkout state, verification reasons, evidence, timeline, and receipt
rendering. Keep checkout and reviewer decisions actionable only through chat.

**Files:**
- Create: `apps/console/features/deal-room/components/transaction-timeline.tsx`
- Create: `apps/console/features/deal-room/components/funding-panel.tsx`
- Create: `apps/console/features/deal-room/components/evidence-list.tsx`
- Create: `apps/console/features/deal-room/components/release-panel.tsx`
- Create: `apps/console/features/deal-room/components/receipt-panel.tsx`
- Create: `apps/console/features/deal-room/components/transaction-room.tsx`
- Modify: `apps/console/app/globals.css`
- Test: `apps/console/features/deal-room/components/transaction-room.test.tsx`

**Interfaces:**
- Produces: read-only `TransactionRoom` with props `settlement`, `receipt`, `error`, `evidenceUrl`; subcomponents `TransactionTimeline`, funding/status summary, `EvidenceList`, verification/release status summary, and `ReceiptPanel`.
- Consumes: `SettlementProjection`, `SettlementReceipt`, `SettlementReviewReason`, `CancelReasonCode`, `money`, `formatDateTime`, `Status`, `Button`.

- [ ] **Step 1: Write the failing component tests**

`apps/console/features/deal-room/components/transaction-room.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  SettlementProjection,
  SettlementReceipt,
} from "@/lib/types";
import { TransactionRoom } from "./transaction-room";

const HASH = "a".repeat(64);

function projection(
  overrides: Partial<SettlementProjection> = {},
): SettlementProjection {
  return {
    transaction_id: "vf_1",
    run_id: "run-1",
    state: "FUNDING_PENDING",
    last_seq: 5,
    amount_cents: 123400,
    currency: "USD",
    buyer_id: "demo-buyer",
    seller_id: "northwind-audio",
    agreement_hash: HASH,
    agreement_version: 1,
    seller_decision: null,
    approval: null,
    cancellation: null,
    funding: { status: "created" },
    purchase_order: null,
    evidence: null,
    verification: null,
    payout: null,
    receipt_available: false,
    deadlines: { evidence: null, inspection: null },
    allowed_actions: [],
    updated_at: "2026-10-27T12:00:00Z",
    ...overrides,
  };
}

function receipt(): SettlementReceipt {
  return {
    payload: {
      receipt_version: 1,
      transaction_id: "vf_1",
      agreement_hash: HASH,
      amount_cents: 123400,
      currency: "USD",
      buyer_id: "demo-buyer",
      seller_id: "northwind-audio",
      capture_id: "CAP-1",
      payout_item_id: "PAY-1",
      evidence_hashes: ["b".repeat(64)],
      released_at: "2026-10-27T12:00:00Z",
    },
    payload_hash: "c".repeat(64),
    signature: "sig-value",
    kid: "receipt-2026-10",
    verified: true,
  };
}

function noop() {}

describe("TransactionRoom", () => {
  it("shows the funding checkpoint and PayPal checkout link", () => {
    render(
      <TransactionRoom
        settlement={projection({
          funding: {
            status: "created",
            payer_action_url:
              "https://www.sandbox.paypal.com/checkoutnow?token=1",
          },
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Funding" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open paypal checkout/i }),
    ).toHaveAttribute(
      "href",
      "https://www.sandbox.paypal.com/checkoutnow?token=1",
    );
  });

  it("lists evidence and verification blockers", () => {
    render(
      <TransactionRoom
        settlement={projection({
          state: "REVIEW_REQUIRED",
          evidence: {
            required: ["shipment_manifest", "delivery_confirmation"],
            received: ["shipment_manifest"],
            complete: false,
            deadline: "2026-10-28T12:00:00Z",
            items: [
              {
                evidence_id: "ev_1",
                kind: "shipment_manifest",
                sha256: "b".repeat(64),
                media_type: "application/json",
                size_bytes: 128,
                original_filename: "manifest.json",
                note: "auto",
                created_at: "2026-10-27T10:00:00Z",
              },
            ],
          },
          verification: {
            status: "failed",
            reasons: ["tracking_mismatch"],
            checked_at: "2026-10-27T12:00:00Z",
            override_allowed: true,
          },
          allowed_actions: ["flag_review", "retry_payout", "cancel"],
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    expect(screen.getByText("shipment_manifest")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "manifest.json" }),
    ).toHaveAttribute("href", "/evidence/ev_1");
    expect(screen.getByText(/tracking mismatch/i)).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 evidence items/i)).toBeInTheDocument();
  });

  it("sends an audited release with the reviewer note", () => {
    const onRelease = vi.fn();
    render(
      <TransactionRoom
        settlement={projection({
          state: "RELEASE_PERMITTED",
          verification: {
            status: "passed",
            reasons: [],
            checked_at: "2026-10-27T12:00:00Z",
            override_allowed: false,
          },
          allowed_actions: ["release"],
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={onRelease}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    fireEvent.change(screen.getByLabelText("Release note"), {
      target: { value: "documents verified" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Release funds" }));

    expect(onRelease).toHaveBeenCalledWith({
      released_by: "demo-reviewer",
      note: "documents verified",
      override: false,
    });
  });

  it("keeps non-overridable review reasons out of the release action", () => {
    render(
      <TransactionRoom
        settlement={projection({
          state: "REVIEW_REQUIRED",
          verification: {
            status: "failed",
            reasons: ["funding_mismatch"],
            checked_at: "2026-10-27T12:00:00Z",
            override_allowed: true,
          },
          allowed_actions: ["flag_review", "retry_payout"],
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Release funds" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/resolve this in paypal/i),
    ).toBeInTheDocument();
  });

  it("retries a payout from review", () => {
    const onReview = vi.fn();
    render(
      <TransactionRoom
        settlement={projection({
          state: "REVIEW_REQUIRED",
          verification: {
            status: "failed",
            reasons: ["manual_flag"],
            checked_at: "2026-10-27T12:00:00Z",
            override_allowed: true,
          },
          allowed_actions: ["flag_review", "retry_payout", "cancel"],
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={onReview}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Retry payout" }));

    expect(onReview).toHaveBeenCalledWith({
      action: "retry_payout",
      note: "",
    });
  });

  it("shows the signed receipt after release", () => {
    render(
      <TransactionRoom
        settlement={projection({
          state: "RELEASED",
          receipt_available: true,
          allowed_actions: [],
        })}
        receipt={receipt()}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Settlement receipt" }),
    ).toBeInTheDocument();
    expect(screen.getByText("verified")).toBeInTheDocument();
    expect(screen.getByText("receipt-2026-10")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/console && npm test -- features/deal-room/components/transaction-room.test.tsx`
Expected: FAIL with `Cannot find module './transaction-room'`.

- [ ] **Step 3: Implement the settlement timeline**

`transaction-timeline.tsx`:

```tsx
import { Check } from "lucide-react";
import type { SettlementState } from "@/lib/types";

const STEPS = [
  { state: "AWARDED", label: "Awarded" },
  { state: "AGREED", label: "Agreed" },
  { state: "FUNDING_PENDING", label: "Funding" },
  { state: "FUNDED", label: "Funded" },
  { state: "VERIFICATION_PENDING", label: "Evidence" },
  { state: "RELEASE_PERMITTED", label: "Verified" },
  { state: "PAYOUT_PENDING", label: "Payout" },
  { state: "RELEASED", label: "Released" },
] as const;

const INDEX = Object.fromEntries(
  STEPS.map((step, index) => [step.state, index]),
) as Record<string, number>;

export function TransactionTimeline({
  state,
}: {
  state?: SettlementState;
}) {
  let current = state ? (INDEX[state] ?? -1) : -1;
  if (state === "REVIEW_REQUIRED") current = 5;
  const stopped = state === "CANCELED" || state === "FAILED";

  return (
    <ol className="mm-timeline" aria-label="Settlement timeline">
      {STEPS.map((step, index) => {
        const complete = !stopped && index < current;
        const active = !stopped && index === current;
        return (
          <li
            key={step.state}
            className={
              complete ? "is-complete" : active ? "is-current" : ""
            }
            aria-current={active ? "step" : undefined}
          >
            <span className="mm-timeline-dot">
              {complete ? <Check size={10} aria-hidden="true" /> : null}
            </span>
            <span>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
```

- [ ] **Step 4: Implement the funding and evidence panels**

`funding-panel.tsx`:

```tsx
import { ExternalLink, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Status } from "@/components/ui/status";
import { formatDateTime, money } from "@/lib/format";
import type { SettlementProjection } from "@/lib/types";

export function FundingPanel({
  settlement,
  busy,
  onAdvance,
}: {
  settlement: SettlementProjection;
  busy: boolean;
  onAdvance: () => void;
}) {
  const funding = settlement.funding;

  return (
    <section className="mm-panel" aria-labelledby="funding-title">
      <header className="mm-panel-head">
        <div>
          <p className="mm-kicker">PayPal sandbox</p>
          <h2 id="funding-title">Funding</h2>
        </div>
        <Status tone={funding?.status === "captured" ? "signal" : "amber"}>
          {funding?.status ?? "not started"}
        </Status>
      </header>

      <div className="mm-order-metrics">
        <div>
          <span className="mm-kicker">Held amount</span>
          <strong>{money(settlement.amount_cents)}</strong>
        </div>
        <div>
          <span className="mm-kicker">Currency</span>
          <strong>{settlement.currency}</strong>
        </div>
        <div>
          <span className="mm-kicker">Capture</span>
          <strong className="mm-tracking">
            {funding?.capture_id ?? "—"}
          </strong>
        </div>
        <div>
          <span className="mm-kicker">Completed</span>
          <strong>{formatDateTime(funding?.completed_at)}</strong>
        </div>
      </div>

      {funding?.payer_action_url ? (
        <a
          className="mm-button mm-button-outline"
          href={funding.payer_action_url}
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLink size={13} aria-hidden="true" />
          Open PayPal checkout
        </a>
      ) : null}

      {settlement.state === "FUNDING_PENDING" ? (
        <Button
          variant="outline"
          size="sm"
          loading={busy}
          leftIcon={<RefreshCcw size={13} aria-hidden="true" />}
          onClick={onAdvance}
        >
          Refresh funding
        </Button>
      ) : null}
    </section>
  );
}
```

`evidence-list.tsx`:

```tsx
import { FileText } from "lucide-react";
import { formatDateTime } from "@/lib/format";
import type { SettlementProjection } from "@/lib/types";

function label(value: string) {
  return value.replaceAll("_", " ");
}

export function EvidenceList({
  settlement,
  evidenceUrl,
}: {
  settlement: SettlementProjection;
  evidenceUrl: (evidenceId: string) => string;
}) {
  const evidence = settlement.evidence;
  const received = evidence?.received.length ?? 0;
  const required = evidence?.required.length ?? 0;
  const reasons = settlement.verification?.reasons ?? [];

  return (
    <section className="mm-panel" aria-labelledby="evidence-title">
      <header className="mm-panel-head">
        <div>
          <p className="mm-kicker">Seller submissions</p>
          <h2 id="evidence-title">Evidence</h2>
        </div>
        <span className="mm-mono-note">
          {received} of {required} evidence items
        </span>
      </header>

      {evidence?.items.length ? (
        <ul className="mm-evidence-list">
          {evidence.items.map((item) => (
            <li key={item.evidence_id}>
              <FileText size={14} aria-hidden="true" />
              <div>
                <strong>{label(item.kind)}</strong>
                <small>
                  {formatDateTime(item.created_at)} ·{" "}
                  {item.size_bytes} bytes
                </small>
              </div>
              <a href={evidenceUrl(item.evidence_id)}>
                {item.original_filename}
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mm-empty">
          The seller has not uploaded shipment evidence yet.
        </p>
      )}

      <p className="mm-settlement-deadline">
        Evidence deadline:{" "}
        <strong>{formatDateTime(evidence?.deadline)}</strong>
      </p>

      {reasons.length ? (
        <div className="mm-settlement-blockers" role="status">
          <span className="mm-kicker">Verification blockers</span>
          <ul>
            {reasons.map((reason) => (
              <li key={reason}>{label(reason)}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
```

- [ ] **Step 5: Implement the release, receipt, and room panels**

`release-panel.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type {
  CancelReasonCode,
  SettlementProjection,
  SettlementReviewReason,
} from "@/lib/types";

const NON_OVERRIDABLE = new Set([
  "funding_mismatch",
  "ledger_incomplete",
  "late_capture",
]);

const REVIEW_REASONS: SettlementReviewReason[] = [
  "manual_flag",
  "tracking_mismatch",
  "agreement_mismatch",
  "delivery_in_future",
  "inspection_not_elapsed",
  "missing_evidence",
  "invalid_evidence_hash",
  "seller_mismatch",
];

export function ReleasePanel({
  settlement,
  busy,
  error,
  onAdvance,
  onRelease,
  onReview,
  onCancel,
}: {
  settlement: SettlementProjection;
  busy: boolean;
  error: string | null;
  onAdvance: () => void;
  onRelease: (input: {
    released_by: string;
    note: string;
    override: boolean;
  }) => void;
  onReview: (input: {
    action: "flag_review" | "retry_payout";
    reason?: SettlementReviewReason;
    note?: string;
  }) => void;
  onCancel: (input: {
    reason_code: CancelReasonCode;
    note: string;
  }) => void;
}) {
  const [note, setNote] = useState("");
  const [override, setOverride] = useState(false);
  const [reason, setReason] =
    useState<SettlementReviewReason>("manual_flag");
  const allowed = new Set(settlement.allowed_actions);
  const reasons = settlement.verification?.reasons ?? [];
  const nonOverridable = reasons.some((item) =>
    NON_OVERRIDABLE.has(item),
  );

  return (
    <section className="mm-panel" aria-labelledby="release-title">
      <header className="mm-panel-head">
        <div>
          <p className="mm-kicker">Reviewer checkpoint</p>
          <h2 id="release-title">Release</h2>
        </div>
        <span className="mm-mono-note">human-gated</span>
      </header>

      {settlement.state === "RELEASED" ? (
        <p className="mm-empty">
          Funds were released and the receipt is available below.
        </p>
      ) : settlement.state === "CANCELED" ? (
        <p className="mm-empty">
          Canceled:{" "}
          {settlement.cancellation?.reason_code ?? "no reason recorded"}.
        </p>
      ) : settlement.state === "REVIEW_REQUIRED" ? (
        <div>
          {nonOverridable ? (
            <p className="mm-settlement-warning" role="alert">
              Resolve this in PayPal before retrying. This reason cannot be
              overridden in Verifund.
            </p>
          ) : null}
          <label className="mm-field" htmlFor="review-reason">
            <span className="mm-kicker">Review reason</span>
            <select
              id="review-reason"
              value={reason}
              onChange={(event) =>
                setReason(event.target.value as SettlementReviewReason)
              }
            >
              {REVIEW_REASONS.map((item) => (
                <option key={item} value={item}>
                  {item.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="mm-field" htmlFor="review-note">
            <span className="mm-kicker">Review note</span>
            <textarea
              id="review-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          <div className="mm-settlement-actions">
            {allowed.has("flag_review") ? (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() =>
                  onReview({ action: "flag_review", reason, note })
                }
              >
                Flag for review
              </Button>
            ) : null}
            {allowed.has("retry_payout") ? (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => onReview({ action: "retry_payout", note })}
              >
                Retry payout
              </Button>
            ) : null}
            {allowed.has("cancel") ? (
              <Button
                variant="danger"
                size="sm"
                disabled={busy}
                onClick={() =>
                  onCancel({
                    reason_code: "reviewer_cancelled",
                    note,
                  })
                }
              >
                Cancel transaction
              </Button>
            ) : null}
          </div>
        </div>
      ) : settlement.state === "RELEASE_PERMITTED" &&
        allowed.has("release") ? (
        <div>
          <p className="mm-empty">
            Verification passed. Releasing creates the PayPal payout and
            signs the receipt.
          </p>
          <label className="mm-field" htmlFor="release-note">
            <span className="mm-kicker">Release note</span>
            <textarea
              id="release-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          {settlement.verification?.override_allowed &&
          !nonOverridable ? (
            <label className="mm-checkbox">
              <input
                type="checkbox"
                checked={override}
                onChange={(event) => setOverride(event.target.checked)}
              />
              Override the verification flag with this note
            </label>
          ) : null}
          <Button
            size="sm"
            loading={busy}
            onClick={() =>
              onRelease({
                released_by: "demo-reviewer",
                note,
                override,
              })
            }
          >
            Release funds
          </Button>
        </div>
      ) : (
        <div>
          <p className="mm-empty">
            The buyer and seller are progressing this transaction. Refresh to
            pull the latest state.
          </p>
          <Button
            variant="outline"
            size="sm"
            loading={busy}
            onClick={onAdvance}
          >
            Refresh state
          </Button>
        </div>
      )}

      {error ? <p className="mm-settlement-warning">{error}</p> : null}
    </section>
  );
}
```

`receipt-panel.tsx`:

```tsx
import { BadgeCheck } from "lucide-react";
import { formatDateTime, money } from "@/lib/format";
import type { SettlementReceipt } from "@/lib/types";

export function ReceiptPanel({
  receipt,
  busy,
  onRefresh,
}: {
  receipt: SettlementReceipt | null;
  busy: boolean;
  onRefresh: () => void;
}) {
  if (!receipt) {
    return (
      <section className="mm-panel" aria-labelledby="receipt-title">
        <header className="mm-panel-head">
          <div>
            <p className="mm-kicker">Signed artifact</p>
            <h2 id="receipt-title">Settlement receipt</h2>
          </div>
        </header>
        <p className="mm-empty">Receipt has not been loaded yet.</p>
        <button
          type="button"
          className="mm-button mm-button-outline mm-button-sm"
          disabled={busy}
          onClick={onRefresh}
        >
          Load receipt
        </button>
      </section>
    );
  }

  return (
    <section className="mm-panel" aria-labelledby="receipt-title">
      <header className="mm-panel-head">
        <div>
          <p className="mm-kicker">Signed artifact</p>
          <h2 id="receipt-title">Settlement receipt</h2>
        </div>
        <span className="mm-receipt-verified">
          <BadgeCheck size={14} aria-hidden="true" />
          {receipt.verified ? "verified" : "unverified"}
        </span>
      </header>
      <div className="mm-order-metrics">
        <div>
          <span className="mm-kicker">Amount</span>
          <strong>{money(receipt.payload.amount_cents)}</strong>
        </div>
        <div>
          <span className="mm-kicker">Released</span>
          <strong>{formatDateTime(receipt.payload.released_at)}</strong>
        </div>
        <div>
          <span className="mm-kicker">Key</span>
          <strong>{receipt.kid}</strong>
        </div>
        <div>
          <span className="mm-kicker">Signature</span>
          <strong className="mm-tracking">{receipt.signature}</strong>
        </div>
      </div>
      <p className="mm-mono-note">
        Payload hash {receipt.payload_hash}
      </p>
    </section>
  );
}
```

`transaction-room.tsx`:

```tsx
import { Status } from "@/components/ui/status";
import { shortId } from "@/lib/format";
import type {
  CancelReasonCode,
  SettlementProjection,
  SettlementReceipt,
  SettlementReviewReason,
} from "@/lib/types";
import { EvidenceList } from "./evidence-list";
import { FundingPanel } from "./funding-panel";
import { ReceiptPanel } from "./receipt-panel";
import { ReleasePanel } from "./release-panel";
import { TransactionTimeline } from "./transaction-timeline";

export type TransactionRoomProps = {
  settlement: SettlementProjection | null;
  receipt: SettlementReceipt | null;
  busy: boolean;
  error: string | null;
  onAdvance: () => void;
  onRelease: (input: {
    released_by: string;
    note: string;
    override: boolean;
  }) => void;
  onReview: (input: {
    action: "flag_review" | "retry_payout";
    reason?: SettlementReviewReason;
    note?: string;
  }) => void;
  onCancel: (input: {
    reason_code: CancelReasonCode;
    note: string;
  }) => void;
  onRefreshReceipt: () => void;
  evidenceUrl: (evidenceId: string) => string;
};

export function TransactionRoom({
  settlement,
  receipt,
  busy,
  error,
  onAdvance,
  onRelease,
  onReview,
  onCancel,
  onRefreshReceipt,
  evidenceUrl,
}: TransactionRoomProps) {
  if (!settlement) {
    return (
      <section className="mm-panel" aria-labelledby="transaction-room-title">
        <header className="mm-panel-head">
          <div>
            <p className="mm-kicker">Verifund</p>
            <h2 id="transaction-room-title">Transaction Room</h2>
          </div>
        </header>
        <p className="mm-empty">
          A funded transaction appears here after the seller accepts the
          award.
        </p>
      </section>
    );
  }

  return (
    <div className="mm-transaction-room">
      <section
        className="mm-panel mm-settlement-summary"
        aria-labelledby="transaction-room-title"
      >
        <header className="mm-panel-head">
          <div>
            <p className="mm-kicker">Verifund · {settlement.currency}</p>
            <h2 id="transaction-room-title">Transaction Room</h2>
            <p className="mm-mono-note">
              {shortId(settlement.transaction_id, 18)} ·{" "}
              {settlement.seller_id}
            </p>
          </div>
          <Status
            tone={
              settlement.state === "REVIEW_REQUIRED"
                ? "error"
                : settlement.state === "RELEASED"
                  ? "signal"
                  : "amber"
            }
          >
            {settlement.state.replaceAll("_", " ")}
          </Status>
        </header>
        <TransactionTimeline state={settlement.state} />
        {settlement.settlement_unavailable ? (
          <p className="mm-settlement-warning" role="status">
            The control plane is unavailable. Showing the last known state.
          </p>
        ) : null}
      </section>

      <FundingPanel
        settlement={settlement}
        busy={busy}
        onAdvance={onAdvance}
      />
      <EvidenceList settlement={settlement} evidenceUrl={evidenceUrl} />
      <ReleasePanel
        settlement={settlement}
        busy={busy}
        error={error}
        onAdvance={onAdvance}
        onRelease={onRelease}
        onReview={onReview}
        onCancel={onCancel}
      />
      {settlement.state === "RELEASED" ? (
        <ReceiptPanel
          receipt={receipt}
          busy={busy}
          onRefresh={onRefreshReceipt}
        />
      ) : null}
    </div>
  );
}
```

- [ ] **Step 6: Add the compact styles**

Append to `apps/console/app/globals.css`:

```css
/* ---------- Transaction Room ---------- */

.mm-transaction-room {
  display: grid;
  gap: 14px;
}

.mm-settlement-summary .mm-timeline {
  margin-top: 4px;
}

.mm-settlement-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.mm-field {
  display: grid;
  gap: 5px;
  margin-top: 12px;
}

.mm-field textarea {
  min-height: 68px;
  resize: vertical;
}

.mm-field input,
.mm-field select,
.mm-field textarea {
  width: 100%;
  padding: 8px 9px;
  border: 1px solid var(--rule-strong);
  background: var(--panel);
  color: var(--ink);
  font: inherit;
  font-size: 11px;
}

.mm-checkbox {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 10px;
  color: var(--muted);
  font-size: 10px;
}

.mm-evidence-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.mm-evidence-list li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 8px 0;
  border-top: 1px solid var(--rule);
}

.mm-evidence-list li > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mm-evidence-list small {
  color: var(--muted);
  font-size: 8px;
}

.mm-evidence-list a {
  color: var(--signal);
  font-family: var(--font-spline-sans-mono), monospace;
  font-size: 8px;
  text-decoration: underline;
}

.mm-settlement-deadline {
  margin: 12px 0 0;
  color: var(--muted);
  font-size: 10px;
}

.mm-settlement-blockers {
  margin-top: 12px;
  padding: 10px;
  border: 1px solid var(--red);
}

.mm-settlement-blockers ul {
  margin: 6px 0 0;
  padding-left: 18px;
  color: var(--red);
  font-size: 10px;
  text-transform: capitalize;
}

.mm-settlement-warning {
  margin: 10px 0;
  padding: 9px 10px;
  border-left: 2px solid var(--red);
  background: rgba(154, 52, 40, 0.06);
  color: var(--red);
  font-size: 10px;
  line-height: 1.5;
}

.mm-receipt-verified {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--signal);
  font-family: var(--font-spline-sans-mono), monospace;
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
```

- [ ] **Step 7: Run the component tests**

Run: `cd apps/console && npm test -- features/deal-room/components/transaction-room.test.tsx`
Expected: PASS.

- [ ] **Step 8: Run the console unit tests and typecheck**

Run: `cd apps/console && npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/console/features/deal-room/components apps/console/app/globals.css
git commit -m "feat(console): build the Verifund Transaction Room"
```

---

### Task 25: Wire settlement state into the run workspace, stepper, and seller dashboard

**Files:**
- Create: `apps/console/lib/run-merge.ts`
- Test: `apps/console/lib/run-merge.test.ts`
- Modify: `apps/console/features/runs/use-run.ts`
- Modify: `apps/console/features/deal-room/hooks/use-run-state.ts`
- Modify: `apps/console/features/deal-room/hooks/use-run-detail.ts`
- Modify: `apps/console/features/deal-room/run-detail.tsx`
- Modify: `apps/console/features/deal-room/components/run-detail-workspace.tsx`
- Modify: `apps/console/features/deal-room/components/stage-stepper.tsx`
- Modify: `apps/console/app/(console)/sellers/[sellerId]/page.tsx`
- Modify: `apps/console/lib/types.ts`

**Interfaces:**
- Produces: `mergeRunState(state, run)`, `useRunDetail` settlement fields (`settlement`, `settlementReceipt`, `settlementBusy`, `settlementError`, `refreshSettlement`, `releaseSettlement`, `reviewSettlement`, `cancelSettlement`, `refreshSettlementReceipt`, `settlementEvidenceUrl`), `StageStepper` `settlementState` prop, seller dashboard settlement table.
- Consumes: Task 23 types/API/stages and Task 24 `TransactionRoom`.

- [ ] **Step 1: Write the failing merge test**

`apps/console/lib/run-merge.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { BuyerRun } from "./api";
import { mergeRunState } from "./run-merge";
import type { BuyerState, SettlementProjection } from "./types";

const settlement = {
  transaction_id: "vf_1",
  state: "FUNDED",
  amount_cents: 123400,
} as SettlementProjection;

describe("mergeRunState", () => {
  it("merges the run projection into the agent state", () => {
    const state: BuyerState = {
      run_id: "run-1",
      stage: "approved",
      settlement: null,
    };
    const run: BuyerRun = {
      run_id: "run-1",
      stage: "funded",
      settlement,
    };

    const merged = mergeRunState(state, run);

    expect(merged.stage).toBe("funded");
    expect(merged.settlement?.transaction_id).toBe("vf_1");
  });

  it("keeps a cached settlement when the run read omits it", () => {
    const state: BuyerState = { settlement };
    const run: BuyerRun = { run_id: "run-1", stage: "funded" };

    const merged = mergeRunState(state, run);

    expect(merged.settlement).toEqual(settlement);
  });

  it("preserves the state when no run is available", () => {
    const state: BuyerState = { stage: "negotiating" };
    expect(mergeRunState(state, null)).toBe(state);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/console && npm test -- lib/run-merge.test.ts`
Expected: FAIL with `Cannot find module './run-merge'`.

- [ ] **Step 3: Extract the merge helper and use shared terminal stages**

`apps/console/lib/run-merge.ts`:

```ts
import type { BuyerRun } from "./api";
import type { BuyerState } from "./types";

export function mergeRunState(
  state: BuyerState,
  run: BuyerRun | null,
): BuyerState {
  if (!run) return state;
  return {
    ...state,
    run_id: run.run_id ?? state.run_id,
    task_id: run.run_id ?? state.task_id,
    stage: run.stage ?? state.stage,
    mandate: run.mandate ?? state.mandate,
    award: run.award ?? state.award,
    order: run.order ?? state.order,
    error: run.error ?? state.error,
    settlement: run.settlement ?? state.settlement ?? null,
  };
}
```

In `features/runs/use-run.ts`, import `isTerminalStage` from `@/lib/stages` and change the interval:

```ts
    refetchInterval: (query) => {
      const data = query.state.data;
      if (isTerminalStage(data?.stage, Boolean(data?.settlement))) {
        return false;
      }
      return data?.stage === "review_required" ? 10_000 : 2_000;
    },
```

In `features/deal-room/hooks/use-run-state.ts`, replace the local `TERMINAL` set:

```ts
import { isTerminalStage } from "@/lib/stages";
...
  const settlement = (state as BuyerState).settlement ?? null;
  const stage = settlement
    ? settlement.state.toLowerCase()
    : ((state as BuyerState).stage ?? "new");
  return {
    ...
    stage,
    terminal: isTerminalStage(stage, Boolean(settlement)),
    settlement,
    ...
  };
```

- [ ] **Step 4: Add settlement state and actions to `useRunDetail`**

At the top of `use-run-detail.ts`, import:

```ts
import { useQueryClient } from "@tanstack/react-query";
import {
  advanceSettlement,
  cancelSettlement,
  fetchSettlementReceipt,
  releaseSettlement,
  reviewSettlement,
  settlementEvidenceUrl,
} from "@/lib/api";
import { mergeRunState } from "@/lib/run-merge";
import { isTerminalStage } from "@/lib/stages";
import type {
  BuyerRun,
} from "@/lib/api";
import type {
  CancelReasonCode,
  SettlementReceipt,
  SettlementResponse,
  SettlementReviewReason,
} from "@/lib/types";
```

Delete the local `TERMINAL_STAGES` and `mergeRunState` definitions.

Inside the hook, after `const { run: buyerRun } = useRun(routeRunId);`:

```ts
  const queryClient = useQueryClient();
  const [settlementReceipt, setSettlementReceipt] =
    useState<SettlementReceipt | null>(null);
  const [settlementBusy, setSettlementBusy] = useState(false);
  const [settlementError, setSettlementError] = useState<string | null>(
    null,
  );
```

Replace the state/stage block with:

```ts
  const state = useMemo(
    () => mergeRunState(buyerState, buyerRun),
    [buyerState, buyerRun],
  );
  const settlement = state.settlement ?? null;
  const stage = settlement
    ? settlement.state.toLowerCase()
    : (state.stage ?? "new");
  const terminal = isTerminalStage(stage, Boolean(settlement));
```

Add the receipt effect and action callbacks before the return:

```ts
  useEffect(() => {
    if (!settlement?.receipt_available) return;
    let active = true;
    fetchSettlementReceipt(routeRunId)
      .then((value) => {
        if (active) setSettlementReceipt(value);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [routeRunId, settlement?.receipt_available]);

  const applySettlement = useCallback(
    (response: SettlementResponse) => {
      queryClient.setQueryData<BuyerRun | null>(
        ["run", routeRunId],
        (current) =>
          current
            ? {
                ...current,
                stage: response.settlement.state.toLowerCase(),
                settlement: response.settlement,
              }
            : current,
      );
      setSettlementError(null);
      if (response.settlement.receipt_available) {
        void fetchSettlementReceipt(routeRunId)
          .then(setSettlementReceipt)
          .catch(() => {});
      }
    },
    [queryClient, routeRunId],
  );

  const forwardSellerCall = useCallback(
    (interrupt: Record<string, unknown> | null | undefined) => {
      if (!interrupt || interrupt.reason !== "seller_call") return;
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: JSON.stringify({
          status: "seller_call_required",
          ...interrupt,
        }),
      });
      void copilotkit.runAgent({ agent });
    },
    [agent, copilotkit],
  );

  const runSettlementAction = useCallback(
    async (action: () => Promise<SettlementResponse>) => {
      setSettlementBusy(true);
      setSettlementError(null);
      try {
        const response = await action();
        applySettlement(response);
        forwardSellerCall(response.interrupt);
      } catch (error) {
        setSettlementError(
          error instanceof Error
            ? error.message
            : "Settlement action failed.",
        );
      } finally {
        setSettlementBusy(false);
      }
    },
    [applySettlement, forwardSellerCall],
  );

  const refreshSettlement = useCallback(
    () =>
      runSettlementAction(() => advanceSettlement(routeRunId)),
    [routeRunId, runSettlementAction],
  );

  const releaseSettlementAction = useCallback(
    (input: {
      released_by: string;
      note: string;
      override: boolean;
    }) =>
      runSettlementAction(() =>
        releaseSettlement(routeRunId, input),
      ),
    [routeRunId, runSettlementAction],
  );

  const reviewSettlementAction = useCallback(
    (input: {
      action: "flag_review" | "retry_payout";
      reason?: SettlementReviewReason;
      note?: string;
    }) =>
      runSettlementAction(() =>
        reviewSettlement(routeRunId, input),
      ),
    [routeRunId, runSettlementAction],
  );

  const cancelSettlementAction = useCallback(
    (input: { reason_code: CancelReasonCode; note: string }) =>
      runSettlementAction(() => cancelSettlement(routeRunId, input)),
    [routeRunId, runSettlementAction],
  );

  const refreshSettlementReceipt = useCallback(async () => {
    setSettlementBusy(true);
    try {
      setSettlementReceipt(await fetchSettlementReceipt(routeRunId));
      setSettlementError(null);
    } catch (error) {
      setSettlementError(
        error instanceof Error ? error.message : "Receipt unavailable.",
      );
    } finally {
      setSettlementBusy(false);
    }
  }, [routeRunId]);

  const evidenceUrl = useCallback(
    (evidenceId: string) =>
      settlementEvidenceUrl(routeRunId, evidenceId),
    [routeRunId],
  );
```

Add to the returned object:

```ts
    settlement,
    settlementReceipt,
    settlementBusy,
    settlementError,
    refreshSettlement,
    releaseSettlement: releaseSettlementAction,
    reviewSettlement: reviewSettlementAction,
    cancelSettlement: cancelSettlementAction,
    refreshSettlementReceipt,
    settlementEvidenceUrl: evidenceUrl,
```

- [ ] **Step 5: Pass settlement props through the run page and workspace**

In `run-detail.tsx`, extend the workspace call:

```tsx
        settlement={detail.settlement}
        settlementReceipt={detail.settlementReceipt}
        settlementBusy={detail.settlementBusy}
        settlementError={detail.settlementError}
        onSettlementAdvance={() => void detail.refreshSettlement()}
        onSettlementRelease={(input) =>
          void detail.releaseSettlement(input)
        }
        onSettlementReview={(input) =>
          void detail.reviewSettlement(input)
        }
        onSettlementCancel={(input) =>
          void detail.cancelSettlement(input)
        }
        onSettlementRefreshReceipt={() =>
          void detail.refreshSettlementReceipt()
        }
        settlementEvidenceUrl={detail.settlementEvidenceUrl}
```

Pass the settlement state to the stepper:

```tsx
      {showStageStepper ? (
        <StageStepper
          stage={detail.stage}
          settlementState={detail.settlement?.state}
        />
      ) : null}
```

In `run-detail-workspace.tsx`, add the props to the type and destructuring:

```ts
  settlement: SettlementProjection | null;
  settlementReceipt: SettlementReceipt | null;
  settlementBusy: boolean;
  settlementError: string | null;
  onSettlementAdvance: () => void;
  onSettlementRelease: (input: {
    released_by: string;
    note: string;
    override: boolean;
  }) => void;
  onSettlementReview: (input: {
    action: "flag_review" | "retry_payout";
    reason?: SettlementReviewReason;
    note?: string;
  }) => void;
  onSettlementCancel: (input: {
    reason_code: CancelReasonCode;
    note: string;
  }) => void;
  onSettlementRefreshReceipt: () => void;
  settlementEvidenceUrl: (evidenceId: string) => string;
```

Replace `<EscrowGuide />` in the sidebar with:

```tsx
        <TransactionRoom
          settlement={settlement}
          receipt={settlementReceipt}
          busy={settlementBusy}
          error={settlementError}
          onAdvance={onSettlementAdvance}
          onRelease={onSettlementRelease}
          onReview={onSettlementReview}
          onCancel={onSettlementCancel}
          onRefreshReceipt={onSettlementRefreshReceipt}
          evidenceUrl={settlementEvidenceUrl}
        />
```

Delete the `EscrowGuide` function and the now-unused icons (`CheckCircle2`, `LockKeyhole`, `ShieldCheck`, `Truck`). Keep `CircleAlert`.

- [ ] **Step 6: Extend the stage stepper**

Replace `stage-stepper.tsx` with:

```tsx
import { Check } from "lucide-react";
import type { SettlementState } from "@/lib/types";

const LEGACY_STEPS = [
  "Brief",
  "Discover",
  "RFQ",
  "Negotiate",
  "Approve",
  "Order",
] as const;

const SETTLEMENT_STEPS = [
  "Award",
  "Agree",
  "Fund",
  "Order",
  "Verify",
  "Release",
  "Paid",
] as const;

const LEGACY_INDEX: Record<string, number> = {
  new: 0,
  needs_clarification: 0,
  brief_ready: 0,
  sellers_discovered: 1,
  failed: 1,
  sourcing_planned: 2,
  negotiating: 3,
  awaiting_approval: 4,
  approved: 4,
  rejected: 4,
  ordering: 5,
  ordered: 5,
  order_failed: 5,
  no_award: 4,
};

const SETTLEMENT_INDEX: Record<SettlementState, number> = {
  AWARDED: 0,
  AGREED: 1,
  FUNDING_PENDING: 2,
  FUNDED: 3,
  FULFILLMENT_PENDING: 4,
  VERIFICATION_PENDING: 4,
  RELEASE_PERMITTED: 5,
  PAYOUT_PENDING: 6,
  RELEASED: 6,
  REVIEW_REQUIRED: 4,
  CANCELED: -1,
  FAILED: -1,
};

type StageStepperProps = {
  stage?: string;
  settlementState?: SettlementState;
};

export function StageStepper({
  stage = "new",
  settlementState,
}: StageStepperProps) {
  const steps = settlementState ? SETTLEMENT_STEPS : LEGACY_STEPS;
  const current = settlementState
    ? SETTLEMENT_INDEX[settlementState]
    : (LEGACY_INDEX[stage] ?? 0);
  const stopped =
    stage === "rejected" ||
    stage === "no_award" ||
    settlementState === "CANCELED" ||
    settlementState === "FAILED";

  return (
    <nav className="mm-stepper" aria-label="Sourcing stages">
      <ol>
        {steps.map((label, index) => {
          const complete = index < current;
          const active = index === current;
          const status = complete
            ? "complete"
            : active
              ? stopped
                ? "stopped"
                : "current"
              : "pending";
          return (
            <li
              key={label}
              className={`mm-step ${status}`}
              aria-current={active ? "step" : undefined}
            >
              <span className="mm-step-mark" aria-hidden="true">
                {complete ? <Check size={12} strokeWidth={2.4} /> : index + 1}
              </span>
              <span className="mm-step-label">{label}</span>
              <span className="sr-only">{status}</span>
            </li>
          );
        })}
      </ol>
      <span className="mm-stepper-state" aria-live="polite">
        {stopped
          ? settlementState === "CANCELED"
            ? "Transaction canceled"
            : "Transaction stopped"
          : settlementState === "RELEASED"
            ? "Payout released"
            : settlementState === "REVIEW_REQUIRED"
              ? "Reviewer decision required"
              : settlementState
                ? settlementState.replaceAll("_", " ").toLowerCase()
                : stage === "awaiting_approval"
                  ? "Human checkpoint"
                  : steps[Math.max(current, 0)]}
      </span>
    </nav>
  );
}
```

- [ ] **Step 7: Show settlement status on the seller detail page**

Add `updated_at?: string | null;` to the `settlement` entry in `SellerDashboard` in `lib/types.ts`.

In `(console)/sellers/[sellerId]/page.tsx`, after the Recent orders section, add:

```tsx
          <Section title="Settlement status" eyebrow="Verifund">
            {!dashboard ? (
              <DashboardSectionState
                loading={dashboardQuery.isLoading}
                error={dashboardQuery.error}
                onRetry={() => void dashboardQuery.refetch()}
              />
            ) : dashboard.settlement?.length ? (
              <div className="mm-seller-table-scroll">
                <table className="mm-seller-data-table">
                  <thead>
                    <tr>
                      <th>Transaction</th>
                      <th>State</th>
                      <th>Amount</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dashboard.settlement.map((item) => (
                      <tr key={item.transaction_id}>
                        <td className="mm-seller-mono">
                          {shortId(item.transaction_id, 14)}
                        </td>
                        <td>
                          <span className="mm-seller-status-tag">
                            {item.state}
                          </span>
                        </td>
                        <td>
                          {item.amount_cents == null
                            ? "—"
                            : currency(
                                item.amount_cents,
                                item.currency ?? "USD",
                              )}
                        </td>
                        <td>
                          {item.evidence
                            ? `${item.evidence.received.length}/${item.evidence.required.length}`
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mm-seller-no-activity">
                No settlement transactions recorded yet.
              </p>
            )}
          </Section>
```

- [ ] **Step 8: Run the console unit tests and typecheck**

Run: `cd apps/console && npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 9: Run the console build**

Run: `cd apps/console && npm run build`
Expected: PASS. Fix any unused imports or type errors before committing.

- [ ] **Step 10: Commit**

```bash
git add apps/console/lib apps/console/features/runs apps/console/features/deal-room 'apps/console/app/(console)/sellers/[sellerId]/page.tsx'
git commit -m "feat(console): wire settlement actions into run and seller views"
```

---

### Task 25A: Add the chat-first Verifund HITL workflow

**Files:**
- Create: `apps/console/features/chat/verifund-tools.tsx`
- Create: `apps/console/features/chat/verifund-tools.test.tsx`
- Modify: `apps/console/features/chat/chat.tsx`
- Modify: `apps/console/features/deal-room/console-shell.tsx`
- Modify: `apps/console/features/deal-room/run-detail.tsx`
- Modify: `apps/console/features/deal-room/hooks/use-run-detail.ts`
- Modify: `apps/console/lib/config.ts`
- Modify: `apps/console/next.config.ts`

**Interfaces:**
- Produces: `verifundToolsEnabled(mode)`, `bilateralReviewStatus(args)`, `fundingDecision(args, choice)`, `releaseGate(projection)`, `releaseDecision(args, choice)`, `parseVerifundToolResult(result)`, `AgreementReviewCard`, `FundingApprovalCard`, `ReleaseApprovalCard`, `EvidenceSummaryCard`, `ReceiptCard`, `CheckoutCard`, `VerifundStatusCard`; HITL tools `request_verifund_funding_approval` and `request_verifund_release_approval`; renderers for `verifund_create_agreement`, `verifund_status`, `verifund_evidence_review`, `verifund_fund`, `verifund_receipt`.
- Consumes: the `VerifundTaskResult` envelopes and tool names from Task 22G, `SettlementProjection`/`SettlementReceipt` from Task 23, and the exact `FundingApprovalDecision`/`ReleaseApprovalDecision` shapes from Task 1A. Free-form chat text never becomes a decision.

- [ ] **Step 1: Write the failing chat-tool tests**

`apps/console/features/chat/verifund-tools.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  AgreementReviewCard,
  FundingApprovalCard,
  ReceiptCard,
  bilateralReviewStatus,
  fundingDecision,
  releaseDecision,
  releaseGate,
  verifundToolsEnabled,
} from "./verifund-tools";

const HASH = "a".repeat(64);
const NOW = "2026-10-27T12:00:00.000Z";

const agreement = {
  agreement_version: 1,
  transaction_id: "vf_1",
  run_id: "run-1",
  buyer_id: "demo-buyer",
  seller_id: "northwind-audio",
  offer_id: "offer-1",
  currency: "USD",
  amount_cents: 123400,
  quantity: 12,
  line_items: [
    {
      sku: "NC-700",
      name: "Nimbus NC-700 ANC Headset",
      quantity: 12,
      unit_price_cents: 10000,
      warranty_addon_cents: 0,
    },
  ],
  shipping_cents: 3400,
  delivery_days: 7,
  warranty_months: 24,
  returns_days: 30,
  created_at: NOW,
  agreement_hash: HASH,
};

const accepted = {
  status: "accepted" as const,
  agreement_version: 1,
  agreement_hash: HASH,
};

function fundingArgs(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "run-1",
    transaction_id: "vf_1",
    agreement_version: 1,
    agreement_hash: HASH,
    agreement,
    buyer_review: accepted,
    seller_decision: accepted,
    message: "Approve funding for this agreement.",
    ...overrides,
  };
}

describe("verifund chat tools", () => {
  it("enables the tools only in settlement modes", () => {
    expect(verifundToolsEnabled("off")).toBe(false);
    expect(verifundToolsEnabled(undefined)).toBe(false);
    expect(verifundToolsEnabled("fake")).toBe(true);
    expect(verifundToolsEnabled("sandbox")).toBe(true);
  });

  it("requires both agents to accept the same version and hash", () => {
    expect(bilateralReviewStatus(fundingArgs())).toBe("ready");
    expect(
      bilateralReviewStatus(fundingArgs({ buyer_review: null })),
    ).toBe("buyer_pending");
    expect(
      bilateralReviewStatus(fundingArgs({ seller_decision: null })),
    ).toBe("seller_pending");
    expect(
      bilateralReviewStatus(
        fundingArgs({
          seller_decision: { ...accepted, agreement_hash: "b".repeat(64) },
        }),
      ),
    ).toBe("mismatch");
    expect(
      bilateralReviewStatus(
        fundingArgs({
          buyer_review: { ...accepted, agreement_version: 2 },
        }),
      ),
    ).toBe("mismatch");
  });

  it("builds a decision with the original identifiers and idempotency key", () => {
    const decision = fundingDecision(fundingArgs(), {
      approved: true,
      approvedBy: "Demo Buyer",
      note: "ok",
      decidedAt: NOW,
    });
    expect(decision).toMatchObject({
      run_id: "run-1",
      transaction_id: "vf_1",
      agreement_version: 1,
      agreement_hash: HASH,
      approved: true,
      approved_by: "Demo Buyer",
      note: "ok",
      decided_at: NOW,
    });
    expect(decision.idempotency_key).toBe(
      `fund:run-1:vf_1:1:${HASH}`,
    );
    expect(() =>
      fundingDecision(fundingArgs({ seller_decision: null }), {
        approved: true,
        decidedAt: NOW,
      }),
    ).toThrow(/Buyer and Seller/);
  });

  it("gates release on verification and requires a note for an override", () => {
    expect(releaseGate(null).enabled).toBe(false);
    expect(
      releaseGate({ state: "FUNDED" } as never).enabled,
    ).toBe(false);
    expect(
      releaseGate({
        state: "REVIEW_REQUIRED",
        verification: { override_allowed: false },
      } as never).enabled,
    ).toBe(false);
    const overrideGate = releaseGate({
      state: "REVIEW_REQUIRED",
      verification: { override_allowed: true },
    } as never);
    expect(overrideGate).toEqual({
      enabled: true,
      overrideAllowed: true,
      reason: null,
    });
    const args = {
      run_id: "run-1",
      transaction_id: "vf_1",
      agreement_version: 1,
      agreement_hash: HASH,
      projection: {
        state: "REVIEW_REQUIRED",
        transaction_id: "vf_1",
        agreement_hash: HASH,
        verification: { override_allowed: true },
      },
      message: "Release this transaction.",
    };
    expect(() =>
      releaseDecision(args as never, {
        approved: true,
        override: true,
        note: " ",
        decidedAt: NOW,
      }),
    ).toThrow(/requires a note/);
    expect(
      releaseDecision(args as never, {
        approved: true,
        override: true,
        note: "Manual inspection complete.",
        decidedAt: NOW,
        releasedBy: "Demo Buyer",
      }),
    ).toMatchObject({
      approved: true,
      override: true,
      released_by: "Demo Buyer",
      idempotency_key: `release:run-1:vf_1:1:${HASH}`,
    });
  });

  it("renders the agreement and the bilateral status", () => {
    render(
      <AgreementReviewCard
        agreement={agreement}
        buyerReview={accepted}
        sellerDecision={accepted}
      />,
    );
    expect(screen.getByTestId("verifund-agreement")).toBeInTheDocument();
    expect(screen.getByText("northwind-audio")).toBeInTheDocument();
    expect(screen.getByText("Buyer accepted")).toBeInTheDocument();
    expect(screen.getByText("Seller accepted")).toBeInTheDocument();
    expect(screen.getByText("$1,234.00")).toBeInTheDocument();
  });

  it("blocks funding until both reviews are accepted", () => {
    const onApprove = vi.fn();
    const { rerender } = render(
      <FundingApprovalCard
        args={fundingArgs({ seller_decision: null })}
        onApprove={onApprove}
        onReject={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Approve funding" }),
    ).toBeDisabled();
    expect(screen.getByTestId("verifund-funding-blocked")).toBeInTheDocument();

    rerender(
      <FundingApprovalCard
        args={fundingArgs()}
        onApprove={onApprove}
        onReject={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Approve funding" }),
    );
    expect(onApprove).toHaveBeenCalledWith("");
  });

  it("renders receipt verification and refuses a malformed receipt", () => {
    render(
      <ReceiptCard
        receipt={{
          payload: {
            receipt_version: 1,
            transaction_id: "vf_1",
            agreement_hash: HASH,
            amount_cents: 123400,
            currency: "USD",
            buyer_id: "demo-buyer",
            seller_id: "northwind-audio",
            capture_id: "cap_1",
            payout_item_id: "pay_1",
            evidence_hashes: [HASH],
            released_at: NOW,
          },
          payload_hash: HASH,
          signature: "sig",
          kid: "dev-1",
          verified: true,
        }}
      />,
    );
    expect(screen.getByText("Verified receipt")).toBeInTheDocument();
    expect(screen.getByText(/dev-1/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/console && npm test -- features/chat/verifund-tools.test.tsx`
Expected: FAIL with `Cannot find module './verifund-tools'`.

- [ ] **Step 3: Implement the schemas, guards, and cards**

`apps/console/features/chat/verifund-tools.tsx`:

```tsx
"use client";

import { useState } from "react";
import { z } from "zod";
import type { SettlementProjection, SettlementReceipt } from "@/lib/types";

export const reviewDecisionSchema = z.object({
  status: z.enum(["accepted", "rejected"]),
  agreement_version: z.number().int().positive(),
  agreement_hash: z.string().regex(/^[0-9a-f]{64}$/),
});

export const agreementSchema = z.object({
  agreement_version: z.number().int().positive(),
  transaction_id: z.string().min(1),
  run_id: z.string().min(1),
  buyer_id: z.string().min(1),
  seller_id: z.string().min(1),
  offer_id: z.string().min(1),
  currency: z.string().min(1),
  amount_cents: z.number().int().positive(),
  quantity: z.number().int().positive(),
  line_items: z.array(
    z.object({
      sku: z.string(),
      name: z.string(),
      quantity: z.number().int().positive(),
      unit_price_cents: z.number().int().positive(),
      warranty_addon_cents: z.number().int().nonnegative().default(0),
    }),
  ),
  shipping_cents: z.number().int().nonnegative(),
  delivery_days: z.number().int().nonnegative(),
  warranty_months: z.number().int().nonnegative(),
  returns_days: z.number().int().nonnegative(),
  created_at: z.string().min(1),
  agreement_hash: z.string().regex(/^[0-9a-f]{64}$/),
});

export const fundingApprovalArgsSchema = z.object({
  run_id: z.string().min(1),
  transaction_id: z.string().min(1),
  agreement_version: z.number().int().positive(),
  agreement_hash: z.string().regex(/^[0-9a-f]{64}$/),
  agreement: agreementSchema,
  buyer_review: reviewDecisionSchema.nullable(),
  seller_decision: reviewDecisionSchema.nullable(),
  message: z.string().default("Approve funding for this agreement."),
});

export const releaseApprovalArgsSchema = z.object({
  run_id: z.string().min(1),
  transaction_id: z.string().min(1),
  agreement_version: z.number().int().positive(),
  agreement_hash: z.string().regex(/^[0-9a-f]{64}$/),
  projection: z.record(z.unknown()).nullable(),
  message: z.string().default("Release this transaction."),
});

export type VerifundAgreement = z.infer<typeof agreementSchema>;
export type ReviewDecision = z.infer<typeof reviewDecisionSchema>;
export type FundingApprovalArgs = z.infer<typeof fundingApprovalArgsSchema>;
export type ReleaseApprovalArgs = z.infer<typeof releaseApprovalArgsSchema>;

export type FundingDecision = {
  run_id: string;
  transaction_id: string;
  agreement_version: number;
  agreement_hash: string;
  approved: boolean;
  approved_by: string;
  note: string;
  decided_at: string;
  idempotency_key: string;
};

export type ReleaseDecision = {
  run_id: string;
  transaction_id: string;
  agreement_version: number;
  agreement_hash: string;
  approved: boolean;
  released_by: string;
  note: string;
  override: boolean;
  decided_at: string;
  idempotency_key: string;
};

export function verifundToolsEnabled(mode: string | undefined): boolean {
  return mode === "fake" || mode === "sandbox";
}

export function parseVerifundToolResult(
  result: unknown,
): Record<string, any> | null {
  if (result && typeof result === "object") {
    return result as Record<string, any>;
  }
  if (typeof result !== "string") return null;
  const content = result.startsWith("A2A Agent Response: ")
    ? result.slice("A2A Agent Response: ".length)
    : result;
  try {
    const parsed = JSON.parse(content);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, any>)
      : null;
  } catch {
    return null;
  }
}

export function bilateralReviewStatus(
  args: Pick<
    FundingApprovalArgs,
    "agreement" | "buyer_review" | "seller_decision"
  >,
): "ready" | "buyer_pending" | "seller_pending" | "mismatch" {
  const { agreement, buyer_review, seller_decision } = args;
  if (!buyer_review || buyer_review.status !== "accepted") {
    return "buyer_pending";
  }
  if (!seller_decision || seller_decision.status !== "accepted") {
    return "seller_pending";
  }
  const bound = (review: ReviewDecision) =>
    review.agreement_version === agreement.agreement_version &&
    review.agreement_hash === agreement.agreement_hash;
  if (!bound(buyer_review) || !bound(seller_decision)) return "mismatch";
  return "ready";
}

export function fundingDecision(
  args: FundingApprovalArgs,
  choice: {
    approved: boolean;
    approvedBy?: string;
    note?: string;
    decidedAt?: string;
  },
): FundingDecision {
  if (
    args.agreement.run_id !== args.run_id ||
    args.agreement.transaction_id !== args.transaction_id ||
    args.agreement.agreement_version !== args.agreement_version ||
    args.agreement.agreement_hash !== args.agreement_hash
  ) {
    throw new Error("The agreement is bound to another run or version.");
  }
  if (bilateralReviewStatus(args) !== "ready") {
    throw new Error(
      "Buyer and Seller must accept the same agreement before funding.",
    );
  }
  return {
    run_id: args.run_id,
    transaction_id: args.transaction_id,
    agreement_version: args.agreement_version,
    agreement_hash: args.agreement_hash,
    approved: choice.approved,
    approved_by: choice.approvedBy ?? "Demo Buyer",
    note: choice.note ?? "",
    decided_at: choice.decidedAt ?? new Date().toISOString(),
    idempotency_key: `fund:${args.run_id}:${args.transaction_id}:${args.agreement_version}:${args.agreement_hash}`,
  };
}

export type ReleaseGate = {
  enabled: boolean;
  overrideAllowed: boolean;
  reason: string | null;
};

export function releaseGate(
  projection: Partial<SettlementProjection> | null,
): ReleaseGate {
  if (!projection) {
    return {
      enabled: false,
      overrideAllowed: false,
      reason: "Waiting for the transaction projection.",
    };
  }
  if (
    projection.state !== "RELEASE_PERMITTED" &&
    projection.state !== "REVIEW_REQUIRED"
  ) {
    return {
      enabled: false,
      overrideAllowed: false,
      reason: `Release is not permitted while the transaction is ${projection.state}.`,
    };
  }
  const overrideAllowed =
    projection.state === "REVIEW_REQUIRED" &&
    Boolean(projection.verification?.override_allowed);
  if (projection.state === "REVIEW_REQUIRED" && !overrideAllowed) {
    return {
      enabled: false,
      overrideAllowed: false,
      reason: "This verification failure cannot be overridden.",
    };
  }
  return { enabled: true, overrideAllowed, reason: null };
}

export function releaseDecision(
  args: ReleaseApprovalArgs,
  choice: {
    approved: boolean;
    releasedBy?: string;
    note?: string;
    override?: boolean;
    decidedAt?: string;
  },
): ReleaseDecision {
  const projection = (args.projection ?? {}) as Partial<SettlementProjection>;
  const gate = releaseGate(projection);
  if (!gate.enabled) {
    throw new Error(gate.reason ?? "Release is not permitted.");
  }
  if (projection.transaction_id && projection.transaction_id !== args.transaction_id) {
    throw new Error("The projection transaction does not match.");
  }
  if (projection.agreement_hash && projection.agreement_hash !== args.agreement_hash) {
    throw new Error("The projection agreement hash is stale.");
  }
  const override = Boolean(choice.override);
  if (override && !gate.overrideAllowed) {
    throw new Error("Override is not allowed for this verification result.");
  }
  const note = choice.note ?? "";
  if (override && !note.trim()) {
    throw new Error("An override release requires a note.");
  }
  return {
    run_id: args.run_id,
    transaction_id: args.transaction_id,
    agreement_version: args.agreement_version,
    agreement_hash: args.agreement_hash,
    approved: choice.approved,
    released_by: choice.releasedBy ?? "Demo Buyer",
    note,
    override,
    decided_at: choice.decidedAt ?? new Date().toISOString(),
    idempotency_key: `release:${args.run_id}:${args.transaction_id}:${args.agreement_version}:${args.agreement_hash}`,
  };
}

function money(cents: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(cents / 100);
}

function reviewLabel(prefix: string, review: ReviewDecision | null) {
  if (!review) return `${prefix} review pending`;
  if (review.status === "rejected") return `${prefix} rejected`;
  return `${prefix} accepted`;
}

export function AgreementReviewCard({
  agreement,
  buyerReview,
  sellerDecision,
}: {
  agreement: VerifundAgreement;
  buyerReview: ReviewDecision | null;
  sellerDecision: ReviewDecision | null;
}) {
  return (
    <section
      className="mm-chat-approval"
      data-testid="verifund-agreement"
      aria-labelledby="verifund-agreement-title"
    >
      <p className="mm-kicker">Verifund · canonical agreement</p>
      <h3 id="verifund-agreement-title">
        {agreement.seller_id} · {money(agreement.amount_cents, agreement.currency)}
      </h3>
      <dl>
        <dt>Transaction</dt>
        <dd>{agreement.transaction_id}</dd>
        <dt>Version</dt>
        <dd>{agreement.agreement_version}</dd>
        <dt>Hash</dt>
        <dd className="mm-mono-note">{agreement.agreement_hash}</dd>
        <dt>Buyer</dt>
        <dd>{reviewLabel("Buyer", buyerReview)}</dd>
        <dt>Seller</dt>
        <dd>{reviewLabel("Seller", sellerDecision)}</dd>
      </dl>
      <ul>
        {agreement.line_items.map((item) => (
          <li key={`${item.sku}-${item.unit_price_cents}`}>
            {item.quantity} × {item.name} ·{" "}
            {money(item.unit_price_cents, agreement.currency)}
          </li>
        ))}
      </ul>
      <p>
        Delivery in {agreement.delivery_days} days · {agreement.warranty_months}
        -month warranty · {agreement.returns_days}-day returns
      </p>
    </section>
  );
}

export function FundingApprovalCard({
  args,
  onApprove,
  onReject,
}: {
  args: FundingApprovalArgs;
  onApprove: (note: string) => void;
  onReject: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  const readiness = bilateralReviewStatus(args);
  const ready = readiness === "ready";
  return (
    <section
      className="mm-chat-approval"
      data-testid="verifund-funding"
      aria-labelledby="verifund-funding-title"
    >
      <p className="mm-kicker">Verifund · human funding approval</p>
      <h3 id="verifund-funding-title">{args.message}</h3>
      <AgreementReviewCard
        agreement={args.agreement}
        buyerReview={args.buyer_review}
        sellerDecision={args.seller_decision}
      />
      {!ready ? (
        <p role="alert" data-testid="verifund-funding-blocked">
          {readiness === "mismatch"
            ? "The recorded reviews are bound to different terms. Funding is blocked."
            : `Waiting for the ${
                readiness === "buyer_pending" ? "Buyer" : "Seller"
              } decision before funding.`}
        </p>
      ) : null}
      <label>
        Note
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <div>
        <button
          type="button"
          disabled={!ready}
          onClick={() => onApprove(note)}
        >
          Approve funding
        </button>
        <button type="button" disabled={!ready} onClick={() => onReject(note)}>
          Reject funding
        </button>
      </div>
    </section>
  );
}

export function ReleaseApprovalCard({
  args,
  onDecision,
}: {
  args: ReleaseApprovalArgs;
  onDecision: (decision: ReleaseDecision) => void;
}) {
  const [note, setNote] = useState("");
  const [override, setOverride] = useState(false);
  const gate = releaseGate(
    (args.projection ?? null) as Partial<SettlementProjection> | null,
  );
  const blocked = !gate.enabled || (override && !note.trim());
  return (
    <section
      className="mm-chat-approval"
      data-testid="verifund-release"
      aria-labelledby="verifund-release-title"
    >
      <p className="mm-kicker">Verifund · human release approval</p>
      <h3 id="verifund-release-title">{args.message}</h3>
      {!gate.enabled ? <p role="alert">{gate.reason}</p> : null}
      <label>
        Note
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      {gate.overrideAllowed ? (
        <label>
          <input
            type="checkbox"
            checked={override}
            onChange={(event) => setOverride(event.target.checked)}
          />
          Override the verification failure
        </label>
      ) : null}
      <div>
        <button
          type="button"
          disabled={blocked}
          onClick={() =>
            onDecision(
              releaseDecision(args, {
                approved: true,
                override,
                note,
              }),
            )
          }
        >
          Release funds
        </button>
        <button
          type="button"
          disabled={!gate.enabled}
          onClick={() =>
            onDecision(
              releaseDecision(args, {
                approved: false,
                override: false,
                note,
              }),
            )
          }
        >
          Reject release
        </button>
      </div>
    </section>
  );
}

export function EvidenceSummaryCard({
  projection,
}: {
  projection: Partial<SettlementProjection> | null;
}) {
  if (!projection) return null;
  const evidence = projection.evidence;
  return (
    <section className="mm-chat-approval" data-testid="verifund-evidence">
      <p className="mm-kicker">Verifund · evidence review</p>
      <p>
        {evidence
          ? `${evidence.received.length}/${evidence.required.length} required evidence items received`
          : "No evidence has been reported."}
      </p>
      {projection.verification ? (
        <p>
          Verification: {projection.verification.status}
          {projection.verification.reasons.length
            ? ` · ${projection.verification.reasons.join(", ")}`
            : ""}
        </p>
      ) : null}
    </section>
  );
}

export function ReceiptCard({ receipt }: { receipt: SettlementReceipt }) {
  return (
    <section className="mm-chat-approval" data-testid="verifund-receipt">
      <p className="mm-kicker">Verifund · signed receipt</p>
      <h3>{receipt.verified ? "Verified receipt" : "Receipt not verified"}</h3>
      <p>
        {receipt.payload.transaction_id} ·{" "}
        {money(receipt.payload.amount_cents, receipt.payload.currency)}
      </p>
      <p className="mm-mono-note">
        {receipt.kid} · {receipt.payload_hash}
      </p>
    </section>
  );
}

export function CheckoutCard({
  url,
  expiresAt,
}: {
  url: string;
  expiresAt?: string | null;
}) {
  return (
    <section className="mm-chat-approval" data-testid="verifund-checkout">
      <p className="mm-kicker">Verifund · funding handoff</p>
      <a href={url} target="_blank" rel="noreferrer">
        Open the payment checkout
      </a>
      {expiresAt ? <p>Link expires at {expiresAt}</p> : null}
    </section>
  );
}

export function VerifundStatusCard({
  state,
  message,
}: {
  state?: string | null;
  message?: string;
}) {
  return (
    <p className="mm-chat-approval-result" data-testid="verifund-status">
      {message ?? `Verifund state: ${state ?? "unknown"}`}
    </p>
  );
}
```

- [ ] **Step 4: Run the helper tests**

Run: `cd apps/console && npm test -- features/chat/verifund-tools.test.tsx`
Expected: PASS.

- [ ] **Step 5: Register the HITL tools and renderers**

In `apps/console/features/chat/chat.tsx`, import the module and add `verifundMode` / `onVerifundAction` to `ChatProps`. After the existing `useHumanInTheLoop` call, add:

```tsx
  const verifundEnabled = verifundToolsEnabled(verifundMode);

  useHumanInTheLoop(
    {
      agentId: "marketmesh_orchestrator",
      name: "request_verifund_funding_approval",
      description:
        "Show the canonical agreement and the Buyer/Seller review status, then wait for an explicit human funding decision. Use only after the Buyer returns funding_approval_required. Pass the exact identifiers from that response.",
      available: verifundEnabled,
      parameters: fundingApprovalArgsSchema,
      render: ({ args, status, respond }) => {
        if (status === "executing" && respond) {
          return (
            <FundingApprovalCard
              args={args as FundingApprovalArgs}
              onApprove={(note) => {
                respond(
                  fundingDecision(args as FundingApprovalArgs, {
                    approved: true,
                    note,
                  }),
                );
                onVerifundAction?.();
              }}
              onReject={(note) => {
                respond(
                  fundingDecision(args as FundingApprovalArgs, {
                    approved: false,
                    note,
                  }),
                );
                onVerifundAction?.();
              }}
            />
          );
        }
        return null;
      },
    },
    [verifundEnabled, onVerifundAction],
  );

  useHumanInTheLoop(
    {
      agentId: "marketmesh_orchestrator",
      name: "request_verifund_release_approval",
      description:
        "Show the evidence/verification summary and wait for an explicit human release decision. Use only after verifund.evidence.review returns release_approval. An override requires a note.",
      available: verifundEnabled,
      parameters: releaseApprovalArgsSchema,
      render: ({ args, status, respond }) => {
        if (status === "executing" && respond) {
          return (
            <ReleaseApprovalCard
              args={args as ReleaseApprovalArgs}
              onDecision={(decision) => {
                respond(decision);
                onVerifundAction?.();
              }}
            />
          );
        }
        return null;
      },
    },
    [verifundEnabled, onVerifundAction],
  );

  useRenderTool({
    name: "verifund_create_agreement",
    parameters: z.object({
      run_id: z.string().optional(),
      award: z.record(z.unknown()).optional(),
    }),
    render: ({ status, result }) => {
      const parsed = parseVerifundToolResult(result);
      const agreement = parsed?.data?.agreement;
      if (status !== "complete" || !agreement) return null;
      return (
        <AgreementReviewCard
          agreement={agreement as VerifundAgreement}
          buyerReview={null}
          sellerDecision={null}
        />
      );
    },
  });

  useRenderTool({
    name: "verifund_status",
    parameters: z.object({ run_id: z.string().optional() }),
    render: ({ status, result }) => {
      const parsed = parseVerifundToolResult(result);
      if (status !== "complete" || !parsed) return null;
      return (
        <VerifundStatusCard
          state={parsed.state ?? parsed.data?.projection?.state}
          message={parsed.message}
        />
      );
    },
  });

  useRenderTool({
    name: "verifund_evidence_review",
    parameters: z.object({ run_id: z.string().optional() }),
    render: ({ status, result }) => {
      const parsed = parseVerifundToolResult(result);
      if (status !== "complete" || !parsed) return null;
      return (
        <EvidenceSummaryCard
          projection={(parsed.data?.projection ??
            parsed.data) as Partial<SettlementProjection>}
        />
      );
    },
  });

  useRenderTool({
    name: "verifund_fund",
    parameters: z.object({ run_id: z.string().optional() }),
    render: ({ status, result }) => {
      const parsed = parseVerifundToolResult(result);
      const url = parsed?.data?.checkout_url;
      if (status !== "complete" || typeof url !== "string") return null;
      return (
        <CheckoutCard url={url} expiresAt={parsed?.data?.expires_at ?? null} />
      );
    },
  });

  useRenderTool({
    name: "verifund_receipt",
    parameters: z.object({ run_id: z.string().optional() }),
    render: ({ status, result }) => {
      const parsed = parseVerifundToolResult(result);
      const receipt = parsed?.data?.receipt;
      if (status !== "complete" || !receipt) return null;
      return <ReceiptCard receipt={receipt as SettlementReceipt} />;
    },
  });
```

- [ ] **Step 6: Wire the settlement mode and run refresh**

In `apps/console/lib/config.ts`, add:

```ts
  verifundMode: (process.env.NEXT_PUBLIC_VERIFUND_MODE ?? "off") as
    | "off"
    | "fake"
    | "sandbox",
```

In `apps/console/next.config.ts`, add to `env`:

```ts
    NEXT_PUBLIC_VERIFUND_MODE: process.env.VERIFUND_MODE ?? "off",
```

In `console-shell.tsx`, destructure `refresh` from `useRun` and pass it to `Chat`:

```tsx
  const { run: buyerRun, refresh: refreshRun } = useRun(routeRunId ?? "");
...
          <Chat
            onRunSample={() => void startRun(SAMPLE_BRIEF)}
            isRunning={isRunning}
            isReady={isReady}
            verifundMode={config.verifundMode}
            onVerifundAction={() => void refreshRun()}
          />
```

In `run-detail.tsx`, pass the same props and use `detail.refreshRun` from the hook. In `use-run-detail.ts`, destructure and return it:

```ts
  const { run: buyerRun, refresh: refreshRun } = useRun(routeRunId);
...
    refreshRun,
```

The HITL tools remain registered in `off` mode with `available: false`, so the orchestrator never receives them and the legacy award-approval flow is unchanged. `verifundMode` comes from the same `VERIFUND_MODE` value that starts or stops the Verifund agent.

- [ ] **Step 7: Run the console tests and typecheck**

Run: `cd apps/console && npm test -- features/chat/verifund-tools.test.tsx lib/stages.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 8: Run the full console test suite**

Run: `cd apps/console && npm test`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/console/features/chat/verifund-tools.tsx apps/console/features/chat/verifund-tools.test.tsx apps/console/features/chat/chat.tsx apps/console/features/deal-room/console-shell.tsx apps/console/features/deal-room/run-detail.tsx apps/console/features/deal-room/hooks/use-run-detail.ts apps/console/lib/config.ts apps/console/next.config.ts
git commit -m "feat(console): add chat-first Verifund review, funding, and release decisions"
```

## Phase 5 — Operations, verification, and docs

### Task 26: Local dev orchestration for Verifund modes

The control plane and the Verifund A2A agent are separate processes. The agent
is registered once through the registry admin API by a short-lived registration
process, not by the runtime agent process. The runtime process receives only its
A2A bearer token, its buyer-internal token, and the buyer URL; it never inherits
the control-plane ops token, seller tokens, or PayPal credentials.

**Files:**
- Modify: `scripts/config.py`
- Modify: `scripts/dev.py`
- Modify: `scripts/run_demo.py`
- Modify: `scripts/e2e.py`
- Create: `apps/verifund_agent/verifund_agent/register.py`
- Test: `tests/unit/test_verifund_dev_config.py`
- Test: `tests/unit/test_verifund_agent_registration.py`

**Interfaces:**
- Produces: `config.verifund_mode()`, `verifund_port()`, `verifund_agent_port()`, `verifund_agent_url()`, `verifund_agent_card_url()`, `verifund_agent_a2a_token()`, `verifund_agent_internal_token()`, `verifund_url()`, `verifund_public_base_url()`, `verifund_console_base_url()`, `verifund_ops_token()`, `buyer_internal_token()`, `verifund_database_url()`, `verifund_evidence_dir()`, `verifund_seller_token_secret()`, `verifund_link_secret()`, `verifund_receipt_keys()`, `verifund_receipt_active_kid()`, `verifund_fake_webhook_secret()`, `verifund_timeout_seconds()`, `verifund_auto_evidence()`, `verifund_evidence_retry_seconds()`, `verifund_inspection_window_hours()`, `seller_payout_emails()`, `paypal_api_base()`, `paypal_env()`, `paypal_webhook_id()`, `paypal_platform_email()`, `paypal_buyer_email()`; `dev.control_plane_environment(llm_mode, verifund_mode)`, `dev.verifund_agent_environment(verifund_mode)`, `dev.verifund_registration_environment(verifund_mode)`, `dev.verifund_enabled(mode)`, `dev.run_stack(scripted, verifund_mode)`; `verifund_agent.register.register(...)` and `verifund_agent.register.main(...)`.
- Consumes: `VERIFUND_MODE`, the seller/buyer settings from Tasks 15, 17A, and 19, the control-plane settings from Task 4, the registry admin API from Task 22A, and the agent server from Task 22B.

- [ ] **Step 1: Write the failing config, dev-wiring, and registration tests**

`tests/unit/test_verifund_dev_config.py`:

```python
from __future__ import annotations

import json

from scripts import config, dev


def clear(monkeypatch, *names: str) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_mode_defaults_to_off(monkeypatch):
    clear(monkeypatch, "VERIFUND_MODE")
    assert config.verifund_mode() == "off"
    assert config.verifund_inspection_window_hours() == 24


def test_fake_mode_shortens_the_inspection_window(monkeypatch):
    monkeypatch.setenv("VERIFUND_MODE", "fake")
    clear(monkeypatch, "VERIFUND_INSPECTION_WINDOW_HOURS")
    assert config.verifund_inspection_window_hours() == 0


def test_explicit_inspection_window_wins(monkeypatch):
    monkeypatch.setenv("VERIFUND_MODE", "fake")
    monkeypatch.setenv("VERIFUND_INSPECTION_WINDOW_HOURS", "6")
    assert config.verifund_inspection_window_hours() == 6


def test_unknown_mode_falls_back_to_off(monkeypatch):
    monkeypatch.setenv("VERIFUND_MODE", "staging")
    assert config.verifund_mode() == "off"


def test_control_plane_url_prefers_verifund_control_plane_url(monkeypatch):
    monkeypatch.setenv("VERIFUND_CONTROL_PLANE_URL", "http://control-plane:9300/")
    clear(monkeypatch, "VERIFUND_URL")
    assert config.verifund_url() == "http://control-plane:9300"


def test_verifund_agent_defaults_and_tokens(monkeypatch):
    clear(
        monkeypatch,
        "VERIFUND_AGENT_PORT",
        "VERIFUND_AGENT_URL",
        "VERIFUND_AGENT_CARD_URL",
        "VERIFUND_AGENT_A2A_TOKEN",
        "VERIFUND_AGENT_INTERNAL_TOKEN",
    )
    assert config.verifund_agent_port() == 9301
    assert config.verifund_agent_url() == "http://127.0.0.1:9301"
    assert (
        config.verifund_agent_card_url()
        == "http://127.0.0.1:9301/.well-known/agent-card.json"
    )
    assert config.verifund_agent_a2a_token() == "dev-verifund-agent-a2a"
    assert (
        config.verifund_agent_internal_token()
        == "dev-verifund-agent-internal"
    )


def test_payout_map_keeps_defaults_and_applies_overrides(monkeypatch):
    monkeypatch.setenv(
        "VERIFUND_SELLER_PAYOUT_EMAILS",
        '{"northwind-audio":"pay@northwind.test"}',
    )
    emails = json.loads(config.seller_payout_emails())
    assert emails["northwind-audio"] == "pay@northwind.test"
    assert emails["summit-tech"] == "seller-summit@example.com"
    assert len(emails) == 4


def test_invalid_payout_json_is_passed_through_for_startup_validation(monkeypatch):
    monkeypatch.setenv("VERIFUND_SELLER_PAYOUT_EMAILS", "{broken")
    assert config.seller_payout_emails() == "{broken"


def test_receipt_key_defaults(monkeypatch):
    clear(monkeypatch, "VERIFUND_RECEIPT_KEYS")
    assert json.loads(config.verifund_receipt_keys()) == {
        "dev-1": "dev-verifund-receipt-key"
    }


def test_off_mode_does_not_wire_the_buyer_to_the_control_plane(monkeypatch):
    clear(monkeypatch, "VERIFUND_URL", "VERIFUND_OPS_TOKEN", "BUYER_INTERNAL_TOKEN")
    buyer = dev.buyer_environment("scripted", "off")
    assert buyer["VERIFUND_MODE"] == "off"
    assert "VERIFUND_URL" not in buyer
    assert "BUYER_INTERNAL_TOKEN" not in buyer
    assert "VERIFUND_AGENT_INTERNAL_TOKEN" not in buyer

    orchestrator = dev.orchestrator_environment("scripted", "off")
    assert "VERIFUND_AGENT_URL" not in orchestrator
    assert "VERIFUND_AGENT_CARD_URL" not in orchestrator
    assert "VERIFUND_AGENT_A2A_TOKEN" not in orchestrator


def test_fake_mode_wires_buyer_seller_orchestrator_and_agent(monkeypatch):
    monkeypatch.setenv("VERIFUND_URL", "http://control:9300")
    monkeypatch.setenv("VERIFUND_OPS_TOKEN", "ops-token")
    monkeypatch.setenv("BUYER_INTERNAL_TOKEN", "internal-token")
    monkeypatch.setenv(
        "VERIFUND_AGENT_INTERNAL_TOKEN", "agent-internal-token"
    )
    monkeypatch.setenv("VERIFUND_AGENT_A2A_TOKEN", "agent-a2a-token")

    buyer = dev.buyer_environment("scripted", "fake")
    assert buyer["VERIFUND_URL"] == "http://control:9300"
    assert buyer["VERIFUND_OPS_TOKEN"] == "ops-token"
    assert buyer["BUYER_INTERNAL_TOKEN"] == "internal-token"
    assert (
        buyer["VERIFUND_AGENT_INTERNAL_TOKEN"] == "agent-internal-token"
    )

    seller = dev.seller_environment("scripted", config.SELLERS[0], "fake")
    assert seller["VERIFUND_MODE"] == "fake"
    assert seller["VERIFUND_URL"] == "http://control:9300"

    orchestrator = dev.orchestrator_environment("scripted", "fake")
    assert orchestrator["BUYER_INTERNAL_URL"] == config.buyer_url()
    assert orchestrator["BUYER_INTERNAL_TOKEN"] == "internal-token"
    assert orchestrator["VERIFUND_AGENT_URL"] == config.verifund_agent_url()
    assert (
        orchestrator["VERIFUND_AGENT_CARD_URL"]
        == config.verifund_agent_card_url()
    )
    assert orchestrator["VERIFUND_AGENT_A2A_TOKEN"] == "agent-a2a-token"

    agent = dev.verifund_agent_environment("fake")
    assert agent["VERIFUND_MODE"] == "fake"
    assert agent["PORT"] == "9301"
    assert agent["VERIFUND_AGENT_PORT"] == "9301"
    assert agent["VERIFUND_AGENT_URL"] == config.verifund_agent_url()
    assert agent["BUYER_INTERNAL_URL"] == config.buyer_url()
    assert agent["VERIFUND_AGENT_A2A_TOKEN"] == "agent-a2a-token"
    assert (
        agent["VERIFUND_AGENT_INTERNAL_TOKEN"] == "agent-internal-token"
    )


def test_agent_environment_is_least_privilege(monkeypatch):
    monkeypatch.setenv("VERIFUND_OPS_TOKEN", "ops-secret")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "paypal-secret")
    monkeypatch.setenv("SELLER_NORTHWIND_TOKEN", "seller-secret")
    monkeypatch.setenv(
        "BUYER_SELLER_TOKENS", '{"northwind-audio":"seller-secret"}'
    )
    monkeypatch.setenv("BUYER_INTERNAL_TOKEN", "buyer-internal-secret")
    clear(
        monkeypatch,
        "VERIFUND_AGENT_PORT",
        "VERIFUND_AGENT_URL",
        "VERIFUND_AGENT_A2A_TOKEN",
        "VERIFUND_AGENT_INTERNAL_TOKEN",
    )
    env = dev.verifund_agent_environment("fake")
    assert env["VERIFUND_MODE"] == "fake"
    assert env["PORT"] == "9301"
    assert env["VERIFUND_AGENT_PORT"] == "9301"
    assert env["VERIFUND_AGENT_URL"] == "http://127.0.0.1:9301"
    assert env["VERIFUND_AGENT_A2A_TOKEN"] == "dev-verifund-agent-a2a"
    assert (
        env["VERIFUND_AGENT_INTERNAL_TOKEN"]
        == "dev-verifund-agent-internal"
    )
    assert env["BUYER_INTERNAL_URL"] == config.buyer_url()
    for name in (
        "VERIFUND_OPS_TOKEN",
        "PAYPAL_CLIENT_SECRET",
        "SELLER_NORTHWIND_TOKEN",
        "BUYER_SELLER_TOKENS",
        "BUYER_INTERNAL_TOKEN",
    ):
        assert name not in env
    assert "ops-secret" not in env.values()
    assert "paypal-secret" not in env.values()
    assert "seller-secret" not in env.values()
    assert "buyer-internal-secret" not in env.values()


def test_registration_environment_has_admin_auth_but_no_runtime_secrets(
    monkeypatch,
):
    monkeypatch.setenv("REGISTRY_URL", "http://registry:9105")
    monkeypatch.setenv("REGISTRY_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("VERIFUND_OPS_TOKEN", "ops-secret")
    monkeypatch.setenv("VERIFUND_AGENT_INTERNAL_TOKEN", "agent-internal")
    monkeypatch.setenv("VERIFUND_AGENT_A2A_TOKEN", "agent-a2a")
    env = dev.verifund_registration_environment("fake")
    assert env["REGISTRY_URL"] == "http://registry:9105"
    assert env["REGISTRY_ADMIN_TOKEN"] == "admin-secret"
    assert env["VERIFUND_AGENT_ID"] == "verifund"
    assert env["VERIFUND_AGENT_CARD_URL"] == config.verifund_agent_card_url()
    for name in (
        "VERIFUND_AGENT_INTERNAL_TOKEN",
        "VERIFUND_AGENT_A2A_TOKEN",
        "VERIFUND_OPS_TOKEN",
    ):
        assert name not in env
    assert "agent-internal" not in env.values()
    assert "agent-a2a" not in env.values()


def test_control_plane_environment_uses_fake_defaults(monkeypatch):
    monkeypatch.setenv("VERIFUND_MODE", "fake")
    clear(
        monkeypatch,
        "VERIFUND_INSPECTION_WINDOW_HOURS",
        "VERIFUND_ALLOW_PUBLIC_BIND",
    )
    env = dev.control_plane_environment("scripted", "fake")
    assert env["VERIFUND_MODE"] == "fake"
    assert env["VERIFUND_INSPECTION_WINDOW_HOURS"] == "0"
    assert env["VERIFUND_ALLOW_PUBLIC_BIND"] == "0"
    assert (
        json.loads(env["VERIFUND_SELLER_PAYOUT_EMAILS"])["northwind-audio"]
        == "seller-northwind@example.com"
    )
```

`tests/unit/test_verifund_agent_registration.py`:

```python
from __future__ import annotations

import json

import httpx
import pytest
import respx

from verifund_agent.register import card_url_from_env, main, register


def test_card_url_defaults_from_the_agent_url(monkeypatch):
    monkeypatch.delenv("VERIFUND_AGENT_CARD_URL", raising=False)
    monkeypatch.setenv("VERIFUND_AGENT_URL", "http://agent:9301/")
    assert (
        card_url_from_env()
        == "http://agent:9301/.well-known/agent-card.json"
    )


@respx.mock
async def test_register_posts_the_card_url_with_admin_auth():
    route = respx.post("http://registry/v1/agents").mock(
        return_value=httpx.Response(
            201,
            json={
                "agent_id": "verifund",
                "card_url": "http://agent:9301/.well-known/agent-card.json",
            },
        )
    )
    row = await register(
        registry_url="http://registry/",
        admin_token="admin",
        agent_id="verifund",
        card_url="http://agent:9301/.well-known/agent-card.json",
        timeout_seconds=1,
        interval_seconds=0,
    )
    assert row["agent_id"] == "verifund"
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer admin"
    assert json.loads(request.read()) == {
        "agent_id": "verifund",
        "card_url": "http://agent:9301/.well-known/agent-card.json",
    }


@respx.mock
async def test_register_retries_a_transient_registry_error():
    route = respx.post("http://registry/v1/agents")
    route.side_effect = [
        httpx.Response(503, text="registry starting"),
        httpx.Response(201, json={"agent_id": "verifund"}),
    ]
    row = await register(
        registry_url="http://registry",
        admin_token="admin",
        agent_id="verifund",
        card_url="http://agent:9301/.well-known/agent-card.json",
        timeout_seconds=1,
        interval_seconds=0,
    )
    assert row["agent_id"] == "verifund"
    assert route.call_count == 2


@respx.mock
async def test_register_fails_fast_when_the_card_is_invalid():
    respx.post("http://registry/v1/agents").mock(
        return_value=httpx.Response(400, text="missing streaming")
    )
    with pytest.raises(RuntimeError, match="missing streaming"):
        await register(
            registry_url="http://registry",
            admin_token="admin",
            agent_id="verifund",
            card_url="http://agent:9301/.well-known/agent-card.json",
            timeout_seconds=1,
            interval_seconds=0,
        )


def test_main_requires_the_registry_admin_token(monkeypatch, capsys):
    monkeypatch.delenv("REGISTRY_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    assert main([]) == 1
    assert "REGISTRY_ADMIN_TOKEN" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_dev_config.py tests/unit/test_verifund_agent_registration.py -v`
Expected: FAIL with `AttributeError: module 'scripts.config' has no attribute 'verifund_mode'` and `ModuleNotFoundError: No module named 'verifund_agent.register'`.

- [ ] **Step 3: Add the Verifund config helpers**

In `scripts/config.py`, add `import json` to the top of the module and add after `SELLERS`:

```python
VERIFUND_MODES = {"off", "fake", "sandbox"}

SELLER_PAYOUT_EMAILS = {
    "northwind-audio": "seller-northwind@example.com",
    "circuitforge": "seller-circuitforge@example.com",
    "aurora-supply": "seller-aurora@example.com",
    "summit-tech": "seller-summit@example.com",
}


def verifund_mode() -> str:
    mode = _env("VERIFUND_MODE", "off").strip().lower()
    return mode if mode in VERIFUND_MODES else "off"


def verifund_port() -> int:
    return _port("VERIFUND_PORT", 9300)


def verifund_agent_port() -> int:
    return _port("VERIFUND_AGENT_PORT", 9301)


def verifund_agent_url() -> str:
    return _env(
        "VERIFUND_AGENT_URL",
        f"http://127.0.0.1:{verifund_agent_port()}",
    ).rstrip("/")


def verifund_agent_card_url() -> str:
    return _env(
        "VERIFUND_AGENT_CARD_URL",
        f"{verifund_agent_url()}/.well-known/agent-card.json",
    )


def verifund_agent_a2a_token() -> str:
    return _env("VERIFUND_AGENT_A2A_TOKEN", "dev-verifund-agent-a2a")


def verifund_agent_internal_token() -> str:
    return _env(
        "VERIFUND_AGENT_INTERNAL_TOKEN", "dev-verifund-agent-internal"
    )


def verifund_url() -> str:
    return _env(
        "VERIFUND_URL",
        _env(
            "VERIFUND_CONTROL_PLANE_URL",
            f"http://127.0.0.1:{verifund_port()}",
        ),
    ).rstrip("/")


def verifund_public_base_url() -> str:
    return _env("VERIFUND_PUBLIC_BASE_URL", verifund_url()).rstrip("/")


def verifund_console_base_url() -> str:
    return _env(
        "VERIFUND_CONSOLE_BASE_URL",
        f"http://127.0.0.1:{console_port()}",
    ).rstrip("/")


def verifund_ops_token() -> str:
    return _env("VERIFUND_OPS_TOKEN", "dev-verifund-ops")


def buyer_internal_token() -> str:
    return _env("BUYER_INTERNAL_TOKEN", "dev-buyer-internal")


def verifund_database_url() -> str:
    return _env(
        "VERIFUND_DATABASE_URL",
        "sqlite+aiosqlite:///./data/verifund.db",
    )


def verifund_evidence_dir() -> str:
    return _env("VERIFUND_EVIDENCE_DIR", "./data/evidence")


def verifund_seller_token_secret() -> str:
    return _env(
        "VERIFUND_SELLER_TOKEN_SECRET",
        "dev-verifund-seller-token-secret",
    )


def verifund_link_secret() -> str:
    return _env("VERIFUND_LINK_SECRET", "dev-verifund-link-secret")


def verifund_receipt_keys() -> str:
    return _env(
        "VERIFUND_RECEIPT_KEYS",
        '{"dev-1":"dev-verifund-receipt-key"}',
    )


def verifund_receipt_active_kid() -> str:
    return _env("VERIFUND_RECEIPT_ACTIVE_KID", "dev-1")


def verifund_fake_webhook_secret() -> str:
    return _env("VERIFUND_FAKE_WEBHOOK_SECRET", "dev-verifund-fake-webhook")


def verifund_timeout_seconds() -> float:
    raw = _env("VERIFUND_TIMEOUT_SECONDS", "20")
    try:
        return float(raw)
    except ValueError:
        return 20.0


def verifund_auto_evidence() -> str:
    return _env("VERIFUND_AUTO_EVIDENCE", "true")


def verifund_evidence_retry_seconds() -> str:
    return _env("VERIFUND_EVIDENCE_RETRY_SECONDS", "2")


def verifund_inspection_window_hours() -> int:
    default = "0" if verifund_mode() == "fake" else "24"
    raw = _env("VERIFUND_INSPECTION_WINDOW_HOURS", default)
    try:
        return max(0, int(raw))
    except ValueError:
        return int(default)


def seller_payout_emails() -> str:
    configured = _env("VERIFUND_SELLER_PAYOUT_EMAILS", "").strip()
    if not configured:
        return json.dumps(SELLER_PAYOUT_EMAILS, sort_keys=True)
    try:
        overrides = json.loads(configured)
    except json.JSONDecodeError:
        return configured
    if not isinstance(overrides, dict):
        return configured
    merged = dict(SELLER_PAYOUT_EMAILS)
    merged.update({str(key): str(value) for key, value in overrides.items()})
    return json.dumps(merged, sort_keys=True)


def paypal_env() -> str:
    return _env("PAYPAL_ENV", "sandbox")


def paypal_api_base() -> str:
    return _env("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")


def paypal_webhook_id() -> str:
    return _env("PAYPAL_WEBHOOK_ID", "")


def paypal_platform_email() -> str:
    return _env("PAYPAL_PLATFORM_EMAIL", "")


def paypal_buyer_email() -> str:
    return _env("PAYPAL_BUYER_EMAIL", "")
```

Delete the now-redundant `import json` inside `seller_tokens_json`.

- [ ] **Step 4: Add the one-shot registration CLI**

`apps/verifund_agent/verifund_agent/register.py`:

```python
"""Register the running Verifund A2A agent with the MarketMesh registry."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import Any

import httpx

DEFAULT_REGISTRY_URL = "http://127.0.0.1:9105"
DEFAULT_AGENT_ID = "verifund"


def card_url_from_env() -> str:
    configured = os.environ.get("VERIFUND_AGENT_CARD_URL", "").strip()
    if configured:
        return configured
    base = os.environ.get("VERIFUND_AGENT_URL", "http://127.0.0.1:9301")
    return f"{base.rstrip('/')}/.well-known/agent-card.json"


def registration_payload(agent_id: str, card_url: str) -> dict[str, str]:
    return {"agent_id": agent_id, "card_url": card_url}


async def register(
    *,
    registry_url: str,
    admin_token: str,
    agent_id: str,
    card_url: str,
    timeout_seconds: float = 60.0,
    interval_seconds: float = 1.0,
) -> dict[str, Any]:
    if not admin_token:
        raise RuntimeError("REGISTRY_ADMIN_TOKEN is required")
    deadline = time.monotonic() + timeout_seconds
    last_error = "registry did not accept the agent"
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                response = await client.post(
                    f"{registry_url.rstrip('/')}/v1/agents",
                    headers={"authorization": f"Bearer {admin_token}"},
                    json=registration_payload(agent_id, card_url),
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
            else:
                if response.status_code in {200, 201}:
                    return response.json()
                last_error = (
                    f"registry returned HTTP {response.status_code}: "
                    f"{response.text}"
                )
                if response.status_code in {400, 401, 403, 404}:
                    raise RuntimeError(last_error)
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "agent registration timed out after "
                    f"{timeout_seconds:.0f}s: {last_error}"
                )
            await asyncio.sleep(interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register the Verifund A2A agent with the registry."
    )
    parser.add_argument(
        "--registry-url",
        default=os.environ.get("REGISTRY_URL", DEFAULT_REGISTRY_URL),
    )
    parser.add_argument(
        "--agent-id",
        default=os.environ.get("VERIFUND_AGENT_ID", DEFAULT_AGENT_ID),
    )
    parser.add_argument("--card-url", default=card_url_from_env())
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(
            os.environ.get("VERIFUND_AGENT_REGISTER_TIMEOUT_SECONDS", "60")
        ),
    )
    args = parser.parse_args(argv)
    try:
        row = asyncio.run(
            register(
                registry_url=args.registry_url,
                admin_token=os.environ.get("REGISTRY_ADMIN_TOKEN", ""),
                agent_id=args.agent_id,
                card_url=args.card_url,
                timeout_seconds=args.timeout_seconds,
            )
        )
    except RuntimeError as exc:
        print(
            f"Verifund agent registration failed: {exc}", file=sys.stderr
        )
        return 1
    print(
        f"registered {row.get('agent_id', args.agent_id)} -> "
        f"{row.get('card_url', args.card_url)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the registration tests**

Run: `uv run pytest tests/unit/test_verifund_agent_registration.py -v`
Expected: PASS.

- [ ] **Step 6: Wire the control plane, agent, and registration into `scripts/dev.py`**

Replace the `from config import (...)` block with a package-safe import. Add after the stdlib imports:

```python
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.config import (  # noqa: E402
    ROOT,
    SELLERS,
    admin_token,
    buyer_a2a_url,
    buyer_agui_url,
    buyer_internal_token,
    buyer_url,
    console_port,
    llm_mode,
    nebius_api_key,
    nebius_base_url,
    nebius_model,
    orchestrator_agui_url,
    orchestrator_port,
    orchestrator_url,
    paypal_api_base,
    paypal_buyer_email,
    paypal_env,
    paypal_platform_email,
    paypal_webhook_id,
    registry_url,
    seller_payout_emails,
    seller_tokens_json,
    verifund_agent_a2a_token,
    verifund_agent_card_url,
    verifund_agent_internal_token,
    verifund_agent_port,
    verifund_agent_url,
    verifund_auto_evidence,
    verifund_console_base_url,
    verifund_database_url,
    verifund_evidence_dir,
    verifund_evidence_retry_seconds,
    verifund_fake_webhook_secret,
    verifund_inspection_window_hours,
    verifund_link_secret,
    verifund_mode,
    verifund_ops_token,
    verifund_port,
    verifund_public_base_url,
    verifund_receipt_active_kid,
    verifund_receipt_keys,
    verifund_seller_token_secret,
    verifund_timeout_seconds,
    verifund_url,
)
```

Add the helpers after `_base_env`:

```python
AGENT_FORBIDDEN_ENV = (
    "VERIFUND_OPS_TOKEN",
    "VERIFUND_SELLER_TOKEN_SECRET",
    "VERIFUND_LINK_SECRET",
    "VERIFUND_RECEIPT_KEYS",
    "VERIFUND_RECEIPT_ACTIVE_KID",
    "BUYER_SELLER_TOKENS",
    "BUYER_INTERNAL_TOKEN",
    "PAYPAL_CLIENT_ID",
    "PAYPAL_CLIENT_SECRET",
    "PAYPAL_WEBHOOK_ID",
    "PAYPAL_PLATFORM_EMAIL",
    "PAYPAL_BUYER_EMAIL",
) + tuple(seller.token_var for seller in SELLERS)


def verifund_enabled(mode: str) -> bool:
    return mode != "off"


def verifund_agent_environment(mode: str) -> dict[str, str]:
    env = _base_env(mode)
    for name in AGENT_FORBIDDEN_ENV:
        env.pop(name, None)
    env.update(
        {
            "HOST": _env_value("HOST", "127.0.0.1"),
            "PORT": str(verifund_agent_port()),
            "VERIFUND_AGENT_PORT": str(verifund_agent_port()),
            "VERIFUND_AGENT_URL": verifund_agent_url(),
            "VERIFUND_AGENT_A2A_TOKEN": verifund_agent_a2a_token(),
            "VERIFUND_AGENT_INTERNAL_TOKEN": (
                verifund_agent_internal_token()
            ),
            "VERIFUND_AGENT_TIMEOUT_SECONDS": _env_value(
                "VERIFUND_AGENT_TIMEOUT_SECONDS", "20"
            ),
            "BUYER_INTERNAL_URL": buyer_url(),
            "VERIFUND_MODE": mode,
        }
    )
    return env


def verifund_registration_environment(mode: str) -> dict[str, str]:
    env = _base_env(mode)
    for name in AGENT_FORBIDDEN_ENV:
        env.pop(name, None)
    env.pop("VERIFUND_AGENT_A2A_TOKEN", None)
    env.pop("VERIFUND_AGENT_INTERNAL_TOKEN", None)
    env.update(
        {
            "REGISTRY_URL": registry_url(),
            "REGISTRY_ADMIN_TOKEN": admin_token(),
            "VERIFUND_AGENT_ID": "verifund",
            "VERIFUND_AGENT_CARD_URL": verifund_agent_card_url(),
        }
    )
    return env


def control_plane_environment(llm: str, mode: str) -> dict[str, str]:
    env = _base_env(llm)
    env.update(
        {
            "VERIFUND_MODE": mode,
            "HOST": _env_value("HOST", "127.0.0.1"),
            "VERIFUND_PORT": str(verifund_port()),
            "VERIFUND_PUBLIC_BASE_URL": verifund_public_base_url(),
            "VERIFUND_CONSOLE_BASE_URL": verifund_console_base_url(),
            "VERIFUND_ALLOW_PUBLIC_BIND": _env_value(
                "VERIFUND_ALLOW_PUBLIC_BIND", "0"
            ),
            "VERIFUND_OPS_TOKEN": verifund_ops_token(),
            "VERIFUND_SELLER_TOKEN_SECRET": verifund_seller_token_secret(),
            "VERIFUND_LINK_SECRET": verifund_link_secret(),
            "VERIFUND_RECEIPT_KEYS": verifund_receipt_keys(),
            "VERIFUND_RECEIPT_ACTIVE_KID": verifund_receipt_active_kid(),
            "VERIFUND_DATABASE_URL": verifund_database_url(),
            "VERIFUND_EVIDENCE_DIR": verifund_evidence_dir(),
            "VERIFUND_INSPECTION_WINDOW_HOURS": str(
                verifund_inspection_window_hours()
            ),
            "VERIFUND_FAKE_WEBHOOK_SECRET": verifund_fake_webhook_secret(),
            "VERIFUND_SELLER_PAYOUT_EMAILS": seller_payout_emails(),
            "PAYPAL_ENV": paypal_env(),
            "PAYPAL_API_BASE": paypal_api_base(),
            "PAYPAL_CLIENT_ID": _env_value("PAYPAL_CLIENT_ID", ""),
            "PAYPAL_CLIENT_SECRET": _env_value("PAYPAL_CLIENT_SECRET", ""),
            "PAYPAL_WEBHOOK_ID": paypal_webhook_id(),
            "PAYPAL_PLATFORM_EMAIL": paypal_platform_email(),
            "PAYPAL_BUYER_EMAIL": paypal_buyer_email(),
        }
    )
    return env
```

Change the env builders to accept the Verifund mode:

```python
def seller_environment(mode: str, seller, verifund_mode: str) -> dict[str, str]:
    env = _base_env(mode)
    env.update(
        {
            "PORT": str(seller.port),
            "SELLER_PORT": str(seller.port),
            "PROFILE_PATH": str(seller.profile_path),
            "PUBLIC_BASE_URL": seller.base_url,
            "SELLER_TOKEN": seller.token,
            "DATABASE_URL": seller.database_url,
            "SELLER_DATABASE_URL": seller.database_url,
            "VERIFUND_MODE": verifund_mode,
        }
    )
    if verifund_enabled(verifund_mode):
        env.update(
            {
                "VERIFUND_URL": verifund_url(),
                "VERIFUND_TIMEOUT_SECONDS": str(verifund_timeout_seconds()),
                "VERIFUND_AUTO_EVIDENCE": verifund_auto_evidence(),
                "VERIFUND_EVIDENCE_RETRY_SECONDS": (
                    verifund_evidence_retry_seconds()
                ),
            }
        )
    return env


def buyer_environment(mode: str, verifund_mode: str) -> dict[str, str]:
    env = _base_env(mode)
    env.update(
        {
            "PORT": _env_value("BUYER_PORT", "9100"),
            "BUYER_PORT": _env_value("BUYER_PORT", "9100"),
            "REGISTRY_URL": registry_url(),
            "BUYER_DATABASE_URL": _buyer_database(),
            "BUYER_CHECKPOINT_PATH": _checkpoint_path(),
            "BUYER_SELLER_TOKENS": seller_tokens_json(),
            "BUYER_CONSOLE_API_TOKEN": _env_value(
                "BUYER_CONSOLE_API_TOKEN", "dev-console"
            ),
            "ALLOWED_CARD_HOSTS": allowed_card_hosts_json(),
            "VERIFUND_MODE": verifund_mode,
        }
    )
    if verifund_enabled(verifund_mode):
        env.update(
            {
                "VERIFUND_URL": verifund_url(),
                "VERIFUND_OPS_TOKEN": verifund_ops_token(),
                "VERIFUND_TIMEOUT_SECONDS": str(verifund_timeout_seconds()),
                "VERIFUND_CONSOLE_BASE_URL": verifund_console_base_url(),
                "BUYER_INTERNAL_TOKEN": buyer_internal_token(),
                "VERIFUND_AGENT_INTERNAL_TOKEN": (
                    verifund_agent_internal_token()
                ),
            }
        )
    return env


def orchestrator_environment(mode: str, verifund_mode: str) -> dict[str, str]:
    env = _base_env(mode)
    env.update(
        {
            "PORT": str(orchestrator_port()),
            "ORCHESTRATOR_PORT": str(orchestrator_port()),
            "ORCHESTRATOR_URL": orchestrator_url(),
            "ORCHESTRATOR_AGUI_URL": orchestrator_agui_url(),
            "BUYER_A2A_URL": buyer_a2a_url(),
            "SELLER_URLS": ",".join(seller.base_url for seller in SELLERS),
            "COPILOTKIT_AGENT_MODEL": f"openai:{nebius_model()}",
            "OPENAI_BASE_URL": nebius_base_url(),
            "VERIFUND_MODE": verifund_mode,
        }
    )
    if verifund_enabled(verifund_mode):
        env.update(
            {
                "BUYER_INTERNAL_URL": buyer_url(),
                "BUYER_INTERNAL_TOKEN": buyer_internal_token(),
                "VERIFUND_AGENT_URL": verifund_agent_url(),
                "VERIFUND_AGENT_CARD_URL": verifund_agent_card_url(),
                "VERIFUND_AGENT_A2A_TOKEN": verifund_agent_a2a_token(),
                "VERIFUND_AGENT_TIMEOUT_SECONDS": _env_value(
                    "VERIFUND_AGENT_TIMEOUT_SECONDS", "60"
                ),
            }
        )
    env.update(seller_auth_environment())
    if mode == "live":
        env["OPENAI_API_KEY"] = nebius_api_key()
    return env
```

Change `_write_pids` to record the mode:

```python
def _write_pids(children: list[Child], mode: str, verifund_mode: str) -> None:
    payload = {
        "started_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "verifund_mode": verifund_mode,
        "services": [
            {
                "name": child.name,
                "pid": child.process.pid,
                "url": child.url,
                "log": str(child.log_path),
            }
            for child in children
        ],
    }
    PID_FILE.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
```

Change `run_stack`:

```python
def run_stack(scripted: bool, verifund_mode: str) -> int:
    mode = _resolve_mode(scripted)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ...
    print(f"MarketMesh local stack · {mode} mode · Verifund {verifund_mode}")
```

Start the control plane and agent after the registry wait and before the seller loop:

```python
        if verifund_enabled(verifund_mode):
            control_plane = start_child(
                "verifund",
                [sys.executable, "-m", "verifund_control_plane"],
                env=control_plane_environment(mode, verifund_mode),
                url=f"{verifund_url()}/health",
            )
            children.append(control_plane)
            wait_for_http(
                "verifund",
                f"{verifund_url()}/health",
                timeout=45,
                process=control_plane.process,
                log_path=control_plane.log_path,
            )
            if verifund_mode == "sandbox" and not verifund_public_base_url().startswith(
                "https://"
            ):
                print(
                    "Sandbox needs a public HTTPS tunnel; "
                    "VERIFUND_PUBLIC_BASE_URL is not HTTPS."
                )

            agent = start_child(
                "verifund-agent",
                [sys.executable, "-m", "verifund_agent"],
                env=verifund_agent_environment(verifund_mode),
                url=f"{verifund_agent_url()}/health",
            )
            children.append(agent)
            wait_for_http(
                "verifund-agent",
                f"{verifund_agent_url()}/health",
                timeout=45,
                process=agent.process,
                log_path=agent.log_path,
            )
            registration = subprocess.run(
                [sys.executable, "-m", "verifund_agent.register"],
                cwd=ROOT,
                env=verifund_registration_environment(verifund_mode),
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            if registration.returncode != 0:
                raise RuntimeError(
                    "Verifund agent registration failed.\n"
                    f"{registration.stdout}{registration.stderr}"
                )
            print(
                "  registered    verifund -> "
                f"{registry_url().rstrip('/')}/v1/agents"
            )
```

Update the three call sites:

```python
                env=seller_environment(mode, seller, verifund_mode),
                env=buyer_environment(mode, verifund_mode),
                env=orchestrator_environment(mode, verifund_mode),
```

Update `_write_pids(children, mode, verifund_mode)` and the ready banner:

```python
        _write_pids(children, mode, verifund_mode)
        print("\nMarketMesh is ready")
        print(f"  Console       http://127.0.0.1:{console_port()}")
        print(f"  Orchestrator  {orchestrator_agui_url()}")
        print(f"  Buyer AG-UI   {buyer_agui_url()}")
        print(f"  Registry      {registry_url().rstrip('/')}/v1/sellers")
        if verifund_enabled(verifund_mode):
            print(f"  Verifund      {verifund_url()}")
            print(f"  Verifund A2A  {verifund_agent_url()}")
```

CLI:

```python
    parser.add_argument(
        "--verifund",
        choices=["off", "fake", "sandbox"],
        default=None,
        help="start the Verifund control plane and A2A agent in the given mode",
    )
    ...
    configured = args.verifund or verifund_mode()
    return run_stack(args.scripted, configured)
```

- [ ] **Step 7: Pass the mode through the demo and E2E runners**

`scripts/run_demo.py` gains a CLI and checkout guidance:

```python
import argparse
import os
...

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verifund", choices=["off", "fake", "sandbox"], default=None
    )
    args = parser.parse_args()
    ...
        command = [sys.executable, str(ROOT / "scripts/dev.py")]
        if args.verifund:
            command.extend(["--verifund", args.verifund])
        ...
    mode = args.verifund or os.environ.get("VERIFUND_MODE", "off")
    if mode in {"fake", "sandbox"}:
        print(
            "\nReview the agreement in chat, approve funding, and complete "
            "PayPal checkout. Review evidence and approve payout release in "
            "the separate chat checkpoint."
        )
    return 0
```

`scripts/e2e.py` propagates the mode to the Playwright process and the stack:

```python
    env["VERIFUND_MODE"] = os.environ.get("VERIFUND_MODE", "off")
    env.setdefault("VERIFUND_CONSOLE_BASE_URL", CONSOLE_URL)
```

The dev stack reads `VERIFUND_MODE` from the environment when `--verifund` is absent, so no extra CLI flag is needed here.

- [ ] **Step 8: Run the config, registration, and existing script tests**

Run: `uv run pytest tests/unit/test_verifund_dev_config.py tests/unit/test_verifund_agent_registration.py tests/test_standalone.py -v`
Expected: PASS.

- [ ] **Step 9: Verify the off-mode stack still starts**

Run: `uv run python scripts/dev.py --scripted` in a terminal, wait for `MarketMesh is ready`, then `uv run python scripts/dev.py stop`.
Expected: the same services as before; no `verifund` or `verifund-agent` process and no Verifund lines in the banner.

- [ ] **Step 10: Verify fake mode starts and registers the agent**

Run: `uv run python scripts/dev.py --scripted --verifund fake` in a terminal and wait for:
```
MarketMesh is ready
  Verifund      http://127.0.0.1:9300
  Verifund A2A  http://127.0.0.1:9301
```
Then run:

```bash
curl -fsS http://127.0.0.1:9301/.well-known/agent-card.json | python -c "import json,sys; card=json.load(sys.stdin); assert len(card['skills']) == 6; print(card['name'])"
curl -fsS -H "authorization: Bearer dev-registry-admin" http://127.0.0.1:9105/v1/agents
```

Expected: the card prints `Verifund`, and the registry lists one healthy `verifund` agent with all six skills. Stop the stack with `uv run python scripts/dev.py stop`.

- [ ] **Step 11: Commit**

```bash
git add scripts/config.py scripts/dev.py scripts/run_demo.py scripts/e2e.py apps/verifund_agent/verifund_agent/register.py tests/unit/test_verifund_dev_config.py tests/unit/test_verifund_agent_registration.py
git commit -m "feat(ops): start and register the Verifund agent in the local stack"
```

---

### Task 27: Compose, Dockerfile, Makefile, and environment packaging

**Files:**
- Modify: `Dockerfile.python`
- Modify: `docker-compose.yml`
- Modify: `Makefile`
- Modify: `.env.example`
- Modify: `.gitignore`
- Test: `tests/unit/test_verifund_packaging.py`

**Interfaces:**
- Produces: `verifund`, `verifund-agent`, and one-shot `verifund-register` Compose profile services; ports `127.0.0.1:9300` and `127.0.0.1:9301`; Verifund env for buyer/sellers/orchestrator/agent; registration through the registry admin API; `make verifund-*` targets; documented `.env.example` keys.
- Consumes: `scripts/config.py` getters, the registration CLI from Task 26, and the service entry points from Tasks 4, 15, 19, and 22B.

- [ ] **Step 1: Write the failing packaging tests**

`tests/unit/test_verifund_packaging.py`:

```python
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_defines_the_verifund_profile_services():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["verifund"]
    agent = compose["services"]["verifund-agent"]
    registration = compose["services"]["verifund-register"]

    assert service["profiles"] == ["verifund"]
    assert "127.0.0.1:9300:9300" in service["ports"]
    assert service["environment"]["VERIFUND_MODE"] == "${VERIFUND_MODE:-fake}"
    assert service["environment"]["VERIFUND_ALLOW_PUBLIC_BIND"] == "1"
    assert (
        service["environment"]["VERIFUND_DATABASE_URL"]
        == "sqlite+aiosqlite:////app/data/verifund.db"
    )
    assert service["environment"]["VERIFUND_EVIDENCE_DIR"] == "/app/data/evidence"

    assert agent["profiles"] == ["verifund"]
    assert "127.0.0.1:9301:9301" in agent["ports"]
    assert agent["environment"]["BUYER_INTERNAL_URL"] == "http://buyer:9100"
    assert (
        agent["environment"]["VERIFUND_AGENT_URL"]
        == "http://verifund-agent:9301"
    )
    assert (
        agent["environment"]["VERIFUND_AGENT_A2A_TOKEN"]
        == "${VERIFUND_AGENT_A2A_TOKEN:-dev-verifund-agent-a2a}"
    )
    assert (
        agent["environment"]["VERIFUND_AGENT_INTERNAL_TOKEN"]
        == "${VERIFUND_AGENT_INTERNAL_TOKEN:-dev-verifund-agent-internal}"
    )
    assert "VERIFUND_OPS_TOKEN" not in agent["environment"]
    assert "PAYPAL_CLIENT_SECRET" not in agent["environment"]
    assert "SELLER_TOKEN" not in agent["environment"]

    assert registration["profiles"] == ["verifund"]
    assert registration["command"] == "python -m verifund_agent.register"
    assert registration["restart"] == "no"
    assert registration["environment"]["REGISTRY_URL"] == "http://registry:9105"
    assert (
        registration["environment"]["REGISTRY_ADMIN_TOKEN"]
        == "${REGISTRY_ADMIN_TOKEN:-dev-registry-admin}"
    )
    assert (
        registration["environment"]["VERIFUND_AGENT_CARD_URL"]
        == "http://verifund-agent:9301/.well-known/agent-card.json"
    )


def test_compose_wires_settlement_settings_into_existing_services():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    registry = compose["services"]["registry"]["environment"]
    assert "verifund-agent" in registry["ALLOWED_CARD_HOSTS"]

    buyer = compose["services"]["buyer"]["environment"]
    assert buyer["VERIFUND_MODE"] == "${VERIFUND_MODE:-off}"
    assert buyer["VERIFUND_URL"] == "http://verifund:9300"
    assert (
        buyer["BUYER_INTERNAL_TOKEN"]
        == "${BUYER_INTERNAL_TOKEN:-dev-buyer-internal}"
    )
    assert (
        buyer["VERIFUND_AGENT_INTERNAL_TOKEN"]
        == "${VERIFUND_AGENT_INTERNAL_TOKEN:-dev-verifund-agent-internal}"
    )

    for name in ("northwind", "circuitforge", "aurora", "summit-tech"):
        seller = compose["services"][name]["environment"]
        assert seller["VERIFUND_MODE"] == "${VERIFUND_MODE:-off}"
        assert seller["VERIFUND_URL"] == "http://verifund:9300"

    orchestrator = compose["services"]["orchestrator"]["environment"]
    assert orchestrator["BUYER_INTERNAL_URL"] == "http://buyer:9100"
    assert (
        orchestrator["BUYER_INTERNAL_TOKEN"]
        == "${BUYER_INTERNAL_TOKEN:-dev-buyer-internal}"
    )
    assert orchestrator["VERIFUND_MODE"] == "${VERIFUND_MODE:-off}"
    assert orchestrator["VERIFUND_AGENT_URL"] == "http://verifund-agent:9301"
    assert (
        orchestrator["VERIFUND_AGENT_CARD_URL"]
        == "http://verifund-agent:9301/.well-known/agent-card.json"
    )
    assert (
        orchestrator["VERIFUND_AGENT_A2A_TOKEN"]
        == "${VERIFUND_AGENT_A2A_TOKEN:-dev-verifund-agent-a2a}"
    )

    console = compose["services"]["console"]["environment"]
    assert console["VERIFUND_MODE"] == "${VERIFUND_MODE:-off}"


def test_dockerfile_copies_the_verifund_services():
    text = (ROOT / "Dockerfile.python").read_text()
    assert (
        "COPY apps/verifund_control_plane ./apps/verifund_control_plane" in text
    )
    assert "COPY apps/verifund_agent ./apps/verifund_agent" in text


def test_makefile_exposes_verifund_targets():
    text = (ROOT / "Makefile").read_text()
    for target in (
        "verifund-smoke",
        "verifund-e2e",
        "verifund-demo",
        "verifund-preflight",
        "verifund-sandbox-smoke",
    ):
        assert f"{target}:" in text
    assert "rm -rf data/evidence" in text


def test_env_example_documents_every_verifund_setting():
    text = (ROOT / ".env.example").read_text()
    for name in (
        "VERIFUND_MODE",
        "VERIFUND_PORT",
        "VERIFUND_AGENT_PORT",
        "VERIFUND_AGENT_URL",
        "VERIFUND_AGENT_CARD_URL",
        "VERIFUND_AGENT_A2A_TOKEN",
        "VERIFUND_AGENT_INTERNAL_TOKEN",
        "VERIFUND_AGENT_TIMEOUT_SECONDS",
        "VERIFUND_AGENT_REGISTER_TIMEOUT_SECONDS",
        "VERIFUND_CONTROL_PLANE_URL",
        "VERIFUND_PUBLIC_BASE_URL",
        "VERIFUND_CONSOLE_BASE_URL",
        "VERIFUND_ALLOW_PUBLIC_BIND",
        "VERIFUND_OPS_TOKEN",
        "BUYER_INTERNAL_TOKEN",
        "VERIFUND_SELLER_TOKEN_SECRET",
        "VERIFUND_LINK_SECRET",
        "VERIFUND_RECEIPT_KEYS",
        "VERIFUND_RECEIPT_ACTIVE_KID",
        "VERIFUND_DATABASE_URL",
        "VERIFUND_EVIDENCE_DIR",
        "VERIFUND_MAX_EVIDENCE_BYTES",
        "VERIFUND_TIMEOUT_SECONDS",
        "VERIFUND_SELLER_TOKEN_TTL_HOURS",
        "VERIFUND_CHECKOUT_LINK_TTL_MINUTES",
        "VERIFUND_RETURN_LINK_TTL_HOURS",
        "VERIFUND_EVIDENCE_DEADLINE_HOURS",
        "VERIFUND_INSPECTION_WINDOW_HOURS",
        "VERIFUND_FUNDING_TIMEOUT_HOURS",
        "VERIFUND_PAYOUT_ALERT_HOURS",
        "PAYPAL_ENV",
        "PAYPAL_API_BASE",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_WEBHOOK_ID",
        "PAYPAL_PLATFORM_EMAIL",
        "PAYPAL_BUYER_EMAIL",
        "VERIFUND_SELLER_PAYOUT_EMAILS",
        "VERIFUND_RECONCILER_ENABLED",
        "VERIFUND_RECONCILER_PENDING_SECONDS",
        "VERIFUND_RECONCILER_DEADLINE_SECONDS",
        "VERIFUND_RECONCILER_RECEIPT_SECONDS",
        "VERIFUND_FAKE_SCENARIO",
        "VERIFUND_FAKE_WEBHOOK_SECRET",
        "VERIFUND_AUTO_EVIDENCE",
        "VERIFUND_EVIDENCE_RETRY_SECONDS",
    ):
        assert f"{name}=" in text, name


def test_gitignore_excludes_evidence_and_coverage_artifacts():
    text = (ROOT / ".gitignore").read_text()
    assert "data/evidence/" in text
    assert ".coverage" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_packaging.py -v`
Expected: FAIL with `KeyError: 'verifund'` and missing Makefile/env entries.

- [ ] **Step 3: Copy both Verifund services into the Python image**

In `Dockerfile.python`, add after the orchestrator copy:

```dockerfile
COPY apps/verifund_control_plane ./apps/verifund_control_plane
COPY apps/verifund_agent ./apps/verifund_agent
```

`COPY packages ./packages` already carries `verifund_contracts`. The control
plane, the A2A agent, and the one-shot registration job run from the same image;
Compose selects the module with `command`.

- [ ] **Step 4: Add the Compose profile service and wire the env**

In `docker-compose.yml`, add after `orchestrator` and before `console`:

```yaml
  verifund:
    <<: *python-service
    profiles: ["verifund"]
    command: python -m verifund_control_plane
    environment:
      HOST: 0.0.0.0
      VERIFUND_MODE: ${VERIFUND_MODE:-fake}
      VERIFUND_PORT: 9300
      VERIFUND_PUBLIC_BASE_URL: ${VERIFUND_PUBLIC_BASE_URL:-http://127.0.0.1:9300}
      VERIFUND_CONSOLE_BASE_URL: ${VERIFUND_CONSOLE_BASE_URL:-http://127.0.0.1:3000}
      VERIFUND_ALLOW_PUBLIC_BIND: "1"
      VERIFUND_OPS_TOKEN: ${VERIFUND_OPS_TOKEN:-dev-verifund-ops}
      VERIFUND_SELLER_TOKEN_SECRET: ${VERIFUND_SELLER_TOKEN_SECRET:-dev-verifund-seller-token-secret}
      VERIFUND_LINK_SECRET: ${VERIFUND_LINK_SECRET:-dev-verifund-link-secret}
      VERIFUND_RECEIPT_KEYS: ${VERIFUND_RECEIPT_KEYS:-'{"dev-1":"dev-verifund-receipt-key"}'}
      VERIFUND_RECEIPT_ACTIVE_KID: ${VERIFUND_RECEIPT_ACTIVE_KID:-dev-1}
      VERIFUND_DATABASE_URL: sqlite+aiosqlite:////app/data/verifund.db
      VERIFUND_EVIDENCE_DIR: /app/data/evidence
      VERIFUND_MAX_EVIDENCE_BYTES: ${VERIFUND_MAX_EVIDENCE_BYTES:-25000000}
      VERIFUND_SELLER_TOKEN_TTL_HOURS: ${VERIFUND_SELLER_TOKEN_TTL_HOURS:-72}
      VERIFUND_CHECKOUT_LINK_TTL_MINUTES: ${VERIFUND_CHECKOUT_LINK_TTL_MINUTES:-30}
      VERIFUND_RETURN_LINK_TTL_HOURS: ${VERIFUND_RETURN_LINK_TTL_HOURS:-24}
      VERIFUND_EVIDENCE_DEADLINE_HOURS: ${VERIFUND_EVIDENCE_DEADLINE_HOURS:-72}
      VERIFUND_INSPECTION_WINDOW_HOURS: ${VERIFUND_INSPECTION_WINDOW_HOURS:-24}
      VERIFUND_FUNDING_TIMEOUT_HOURS: ${VERIFUND_FUNDING_TIMEOUT_HOURS:-24}
      VERIFUND_PAYOUT_ALERT_HOURS: ${VERIFUND_PAYOUT_ALERT_HOURS:-1}
      VERIFUND_SELLER_PAYOUT_EMAILS: ${VERIFUND_SELLER_PAYOUT_EMAILS:-}
      VERIFUND_RECONCILER_ENABLED: ${VERIFUND_RECONCILER_ENABLED:-true}
      VERIFUND_RECONCILER_PENDING_SECONDS: ${VERIFUND_RECONCILER_PENDING_SECONDS:-30}
      VERIFUND_RECONCILER_DEADLINE_SECONDS: ${VERIFUND_RECONCILER_DEADLINE_SECONDS:-60}
      VERIFUND_RECONCILER_RECEIPT_SECONDS: ${VERIFUND_RECONCILER_RECEIPT_SECONDS:-300}
      VERIFUND_FAKE_SCENARIO: ${VERIFUND_FAKE_SCENARIO:-success}
      VERIFUND_FAKE_WEBHOOK_SECRET: ${VERIFUND_FAKE_WEBHOOK_SECRET:-dev-verifund-fake-webhook}
      PAYPAL_ENV: ${PAYPAL_ENV:-sandbox}
      PAYPAL_API_BASE: ${PAYPAL_API_BASE:-https://api-m.sandbox.paypal.com}
      PAYPAL_CLIENT_ID: ${PAYPAL_CLIENT_ID:-}
      PAYPAL_CLIENT_SECRET: ${PAYPAL_CLIENT_SECRET:-}
      PAYPAL_WEBHOOK_ID: ${PAYPAL_WEBHOOK_ID:-}
      PAYPAL_PLATFORM_EMAIL: ${PAYPAL_PLATFORM_EMAIL:-}
      PAYPAL_BUYER_EMAIL: ${PAYPAL_BUYER_EMAIL:-}
    ports:
      - "127.0.0.1:9300:9300"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9300/health', timeout=2)"]
      interval: 5s
      timeout: 3s
      retries: 20
```

Add the A2A service alongside the control plane:

```yaml
  verifund-agent:
    <<: *python-service
    profiles: ["verifund"]
    command: python -m verifund_agent
    environment:
      HOST: 0.0.0.0
      VERIFUND_AGENT_PORT: 9301
      VERIFUND_AGENT_URL: http://verifund-agent:9301
      VERIFUND_AGENT_A2A_TOKEN: ${VERIFUND_AGENT_A2A_TOKEN:-dev-verifund-agent-a2a}
      VERIFUND_AGENT_INTERNAL_TOKEN: ${VERIFUND_AGENT_INTERNAL_TOKEN:-dev-verifund-agent-internal}
      VERIFUND_AGENT_TIMEOUT_SECONDS: ${VERIFUND_AGENT_TIMEOUT_SECONDS:-20}
      BUYER_INTERNAL_URL: http://buyer:9100
      VERIFUND_MODE: ${VERIFUND_MODE:-fake}
    ports:
      - "127.0.0.1:9301:9301"
    depends_on:
      buyer:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9301/ready', timeout=2)"]
      interval: 5s
      timeout: 3s
      retries: 20
```

Add the one-shot registration job. It fetches the agent card through the
registry and exits; it is not part of the runtime agent process and never
receives the agent's runtime tokens:

```yaml
  verifund-register:
    <<: *python-service
    profiles: ["verifund"]
    command: python -m verifund_agent.register
    restart: "no"
    depends_on:
      registry:
        condition: service_healthy
      verifund-agent:
        condition: service_healthy
    environment:
      REGISTRY_URL: http://registry:9105
      REGISTRY_ADMIN_TOKEN: ${REGISTRY_ADMIN_TOKEN:-dev-registry-admin}
      VERIFUND_AGENT_ID: verifund
      VERIFUND_AGENT_CARD_URL: http://verifund-agent:9301/.well-known/agent-card.json
      VERIFUND_AGENT_REGISTER_TIMEOUT_SECONDS: ${VERIFUND_AGENT_REGISTER_TIMEOUT_SECONDS:-60}
```

In the `registry` environment, extend the allowlist so the registry can fetch
the agent card through the Compose network name:

```yaml
      ALLOWED_CARD_HOSTS: '["127.0.0.1","localhost","northwind","circuitforge","aurora","summit-tech","verifund-agent","host.docker.internal"]'
```

In the `buyer` environment add:

```yaml
      VERIFUND_MODE: ${VERIFUND_MODE:-off}
      VERIFUND_URL: http://verifund:9300
      VERIFUND_OPS_TOKEN: ${VERIFUND_OPS_TOKEN:-dev-verifund-ops}
      VERIFUND_TIMEOUT_SECONDS: ${VERIFUND_TIMEOUT_SECONDS:-20}
      VERIFUND_CONSOLE_BASE_URL: ${VERIFUND_CONSOLE_BASE_URL:-http://127.0.0.1:3000}
      BUYER_INTERNAL_TOKEN: ${BUYER_INTERNAL_TOKEN:-dev-buyer-internal}
      VERIFUND_AGENT_INTERNAL_TOKEN: ${VERIFUND_AGENT_INTERNAL_TOKEN:-dev-verifund-agent-internal}
```

In each seller environment add:

```yaml
      VERIFUND_MODE: ${VERIFUND_MODE:-off}
      VERIFUND_URL: http://verifund:9300
      VERIFUND_TIMEOUT_SECONDS: ${VERIFUND_TIMEOUT_SECONDS:-20}
      VERIFUND_AUTO_EVIDENCE: ${VERIFUND_AUTO_EVIDENCE:-true}
      VERIFUND_EVIDENCE_RETRY_SECONDS: ${VERIFUND_EVIDENCE_RETRY_SECONDS:-2}
```

In the `orchestrator` environment add:

```yaml
      VERIFUND_MODE: ${VERIFUND_MODE:-off}
      BUYER_INTERNAL_URL: http://buyer:9100
      BUYER_INTERNAL_TOKEN: ${BUYER_INTERNAL_TOKEN:-dev-buyer-internal}
      VERIFUND_AGENT_URL: http://verifund-agent:9301
      VERIFUND_AGENT_CARD_URL: http://verifund-agent:9301/.well-known/agent-card.json
      VERIFUND_AGENT_A2A_TOKEN: ${VERIFUND_AGENT_A2A_TOKEN:-dev-verifund-agent-a2a}
      VERIFUND_AGENT_TIMEOUT_SECONDS: ${VERIFUND_AGENT_TIMEOUT_SECONDS:-60}
```

In the `console` environment add:

```yaml
      VERIFUND_MODE: ${VERIFUND_MODE:-off}
```

The `verifund` service has no `depends_on` on buyer/sellers and no service
depends on it. The `verifund-agent` depends on the buyer only for its runtime
calls. `verifund-register` runs once after the agent is healthy and exits
successfully; it does not restart. In `off` mode none of the three services is
started. In `fake`/`sandbox` mode start them with
`docker compose --profile verifund up`.

The `verifund-agent` service receives no `VERIFUND_OPS_TOKEN`, seller token,
paypal credential, or registry admin token. The `verifund-register` service
receives the registry admin token but not the agent's A2A or internal tokens.

- [ ] **Step 5: Add the environment template**

Append to `.env.example`:

```bash
# ---------------------------------------------------------------------------
# Verifund settlement
# ---------------------------------------------------------------------------
# off keeps the existing MarketMesh flow. fake uses the local fake PayPal
# adapter. sandbox uses the real PayPal Sandbox REST API.
VERIFUND_MODE=off
VERIFUND_PORT=9300
VERIFUND_AGENT_PORT=9301
VERIFUND_AGENT_URL=http://127.0.0.1:9301
VERIFUND_AGENT_CARD_URL=http://127.0.0.1:9301/.well-known/agent-card.json
VERIFUND_AGENT_A2A_TOKEN=dev-verifund-agent-a2a
VERIFUND_AGENT_INTERNAL_TOKEN=dev-verifund-agent-internal
VERIFUND_AGENT_TIMEOUT_SECONDS=20
VERIFUND_AGENT_REGISTER_TIMEOUT_SECONDS=60
VERIFUND_CONTROL_PLANE_URL=http://127.0.0.1:9300
VERIFUND_PUBLIC_BASE_URL=http://127.0.0.1:9300
VERIFUND_CONSOLE_BASE_URL=http://127.0.0.1:3000
VERIFUND_ALLOW_PUBLIC_BIND=0

# Auth and signing. Replace every dev default before sandbox use.
VERIFUND_OPS_TOKEN=dev-verifund-ops
BUYER_INTERNAL_TOKEN=dev-buyer-internal
VERIFUND_SELLER_TOKEN_SECRET=dev-verifund-seller-token-secret
VERIFUND_LINK_SECRET=dev-verifund-link-secret
VERIFUND_RECEIPT_KEYS='{"dev-1":"dev-verifund-receipt-key"}'
VERIFUND_RECEIPT_ACTIVE_KID=dev-1

# Storage
VERIFUND_DATABASE_URL=sqlite+aiosqlite:///./data/verifund.db
VERIFUND_EVIDENCE_DIR=./data/evidence
VERIFUND_MAX_EVIDENCE_BYTES=25000000

# Lifecycle. fake mode defaults the inspection window to 0 so the demo can
# release in one session; set it explicitly to override.
VERIFUND_TIMEOUT_SECONDS=20
VERIFUND_SELLER_TOKEN_TTL_HOURS=72
VERIFUND_CHECKOUT_LINK_TTL_MINUTES=30
VERIFUND_RETURN_LINK_TTL_HOURS=24
VERIFUND_EVIDENCE_DEADLINE_HOURS=72
VERIFUND_INSPECTION_WINDOW_HOURS=24
VERIFUND_FUNDING_TIMEOUT_HOURS=24
VERIFUND_PAYOUT_ALERT_HOURS=1
VERIFUND_AUTO_EVIDENCE=true
VERIFUND_EVIDENCE_RETRY_SECONDS=2

# PayPal Sandbox. See docs/verifund-paypal-sandbox.md.
PAYPAL_ENV=sandbox
PAYPAL_API_BASE=https://api-m.sandbox.paypal.com
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_WEBHOOK_ID=
PAYPAL_PLATFORM_EMAIL=
PAYPAL_BUYER_EMAIL=
VERIFUND_SELLER_PAYOUT_EMAILS='{"northwind-audio":"seller-northwind@example.com","circuitforge":"seller-circuitforge@example.com","aurora-supply":"seller-aurora@example.com","summit-tech":"seller-summit@example.com"}'

# Reconciler
VERIFUND_RECONCILER_ENABLED=true
VERIFUND_RECONCILER_PENDING_SECONDS=30
VERIFUND_RECONCILER_DEADLINE_SECONDS=60
VERIFUND_RECONCILER_RECEIPT_SECONDS=300

# Fake mode only
VERIFUND_FAKE_SCENARIO=success
VERIFUND_FAKE_WEBHOOK_SECRET=dev-verifund-fake-webhook
```

- [ ] **Step 6: Add the Makefile targets and reset cleanup**

Change the first line to:

```makefile
.PHONY: setup dev dev-scripted seed reset test lint e2e demo down \
	verifund-smoke verifund-e2e verifund-demo verifund-preflight \
	verifund-sandbox-smoke
```

Change `reset`:

```makefile
reset:
	rm -f data/*.db data/*.db-wal data/*.db-shm
	rm -rf data/evidence
```

Append:

```makefile
verifund-smoke:
	uv run python scripts/verifund_smoke.py

verifund-e2e:
	uv run python scripts/verifund_e2e.py

verifund-demo:
	uv run python scripts/run_demo.py --verifund fake

verifund-preflight:
	uv run python scripts/verifund_sandbox_preflight.py

verifund-sandbox-smoke:
	uv run python scripts/verifund_sandbox_smoke.py
```

- [ ] **Step 7: Ignore local artifacts**

Append to `.gitignore`:

```gitignore
# Verifund local artifacts (data/ is already ignored; keep this explicit)
data/evidence/
.coverage
coverage.xml
htmlcov/
```

- [ ] **Step 8: Validate the packaging**

Run: `uv run pytest tests/unit/test_verifund_packaging.py -v`
Expected: PASS.

Run: `docker compose config --quiet` (skip if Docker is unavailable; record that in the commit message).
Expected: no error.

Run: `docker compose --profile verifund config --services`
Expected: includes `verifund`, `verifund-agent`, and `verifund-register`.

- [ ] **Step 9: Commit**

```bash
git add Dockerfile.python docker-compose.yml Makefile .env.example .gitignore tests/unit/test_verifund_packaging.py
git commit -m "chore(ops): package the Verifund control plane and agent for compose"
```

---

### Task 28: Headless fake smoke and Playwright end-to-end flow

**Files:**
- Create: `scripts/verifund_flow.py`
- Create: `scripts/verifund_smoke.py`
- Create: `scripts/verifund_e2e.py`
- Create: `apps/console/e2e/verifund.spec.ts`
- Modify: `apps/console/e2e/console.spec.ts`
- Test: `tests/unit/test_verifund_scripts.py`

**Interfaces:**
- Produces: `AwardContext` helpers `award_payload`, `manifest_payload`, `delivery_payload`, `summarize_ledger`; `VerifundFlow` (`award`, `accept`, `approve`, `fund`, `complete_checkout`, `purchase_order`, `upload_evidence`, `verify`, `release`, `get_state`, `get_receipt`, `wait_for_state`, `run`); `smoke_environment`, `ledger_rows`, `main`; `e2e_environment`, `playwright_command`, `main`; the `e2e/verifund.spec.ts` browser test that drives approvals and release through chat and checks the Transaction Room projection.
- Consumes: the control-plane ops and seller APIs, the fake checkout route, `scripts/dev.py --verifund fake`, and the shared console stage labels.

- [ ] **Step 1: Write the failing script tests**

`tests/unit/test_verifund_scripts.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.verifund_e2e import e2e_environment, playwright_command
from scripts.verifund_flow import (
    AMOUNT_CENTS,
    award_payload,
    delivery_payload,
    manifest_payload,
    summarize_ledger,
)
from scripts.verifund_smoke import smoke_environment

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def test_award_payload_is_balanced():
    payload = award_payload("run-1")

    assert payload["run_id"] == "run-1"
    assert payload["amount_cents"] == AMOUNT_CENTS
    assert sum(item["quantity"] for item in payload["line_items"]) == (
        payload["quantity"]
    )
    assert (
        sum(
            (item["unit_price_cents"] + item["warranty_addon_cents"])
            * item["quantity"]
            for item in payload["line_items"]
        )
        + payload["shipping_cents"]
        == payload["amount_cents"]
    )


def test_manifest_and_delivery_payloads_are_policy_ready():
    manifest = manifest_payload(
        seller_id="northwind-audio",
        agreement_hash="a" * 64,
        tracking_number="TRK-1",
        shipped_at=NOW - timedelta(hours=2),
    )
    delivery = delivery_payload(
        tracking_number="TRK-1", delivered_at=NOW - timedelta(hours=1)
    )

    assert manifest["tracking_number"] == delivery["tracking_number"] == "TRK-1"
    assert manifest["agreement_hash"] == "a" * 64
    assert datetime.fromisoformat(delivery["delivered_at"]) < NOW


def test_summarize_ledger_balances_held_funds():
    rows = [
        {"account": "platform_cash", "debit_cents": 123400, "credit_cents": 0},
        {"account": "held_funds", "debit_cents": 0, "credit_cents": 123400},
        {"account": "held_funds", "debit_cents": 123400, "credit_cents": 0},
        {"account": "seller_paid", "debit_cents": 0, "credit_cents": 123400},
    ]

    summary = summarize_ledger(rows)

    assert summary["held_funds"] == {"debit": 123400, "credit": 123400}
    assert summary["platform_cash"] == {"debit": 123400, "credit": 0}
    assert summary["seller_paid"] == {"debit": 0, "credit": 123400}
    assert sum(item["debit"] for item in summary.values()) == sum(
        item["credit"] for item in summary.values()
    )


def test_smoke_environment_is_isolated_and_fake(tmp_path: Path):
    env = smoke_environment(tmp_path, port=9399)

    assert env["VERIFUND_MODE"] == "fake"
    assert env["VERIFUND_PORT"] == "9399"
    assert env["VERIFUND_INSPECTION_WINDOW_HOURS"] == "0"
    assert env["VERIFUND_RECONCILER_ENABLED"] == "false"
    assert str(tmp_path / "verifund.db") in env["VERIFUND_DATABASE_URL"]
    assert env["VERIFUND_EVIDENCE_DIR"] == str(tmp_path / "evidence")


def test_e2e_environment_forces_fake_mode():
    env = e2e_environment({"PATH": "/bin"})

    assert env["VERIFUND_MODE"] == "fake"
    assert env["VERIFUND_INSPECTION_WINDOW_HOURS"] == "0"
    assert env["VERIFUND_CONTROL_PLANE_URL"] == "http://127.0.0.1:9300"
    assert playwright_command() == [
        "pnpm",
        "exec",
        "playwright",
        "test",
        "e2e/verifund.spec.ts",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_scripts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.verifund_flow'`.

- [ ] **Step 3: Implement the shared lifecycle driver**

`scripts/verifund_flow.py`:

```python
"""Drive one Verifund transaction through the control-plane HTTP API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

import httpx

AMOUNT_CENTS = 123400
SHIPPING_CENTS = 3400
QUANTITY = 12
UNIT_PRICE_CENTS = 10000
SELLER_ID = "northwind-audio"
BUYER_ID = "buyer-demo"
DEFAULT_RUN_ID = "run-verifund-smoke"


def award_payload(run_id: str = DEFAULT_RUN_ID) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "buyer_id": BUYER_ID,
        "seller_id": SELLER_ID,
        "offer_id": "offer-northwind-1",
        "currency": "USD",
        "amount_cents": AMOUNT_CENTS,
        "shipping_cents": SHIPPING_CENTS,
        "quantity": QUANTITY,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": QUANTITY,
                "unit_price_cents": UNIT_PRICE_CENTS,
                "warranty_addon_cents": 0,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
    }


def manifest_payload(
    *,
    seller_id: str,
    agreement_hash: str,
    tracking_number: str,
    shipped_at: datetime,
) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "seller_id": seller_id,
        "agreement_hash": agreement_hash,
        "tracking_number": tracking_number,
        "carrier": "Verifund Logistics",
        "shipped_at": shipped_at.isoformat(),
        "items": [{"sku": "NC-700", "quantity": QUANTITY}],
    }


def delivery_payload(
    *, tracking_number: str, delivered_at: datetime
) -> dict[str, Any]:
    return {
        "confirmation_version": 1,
        "tracking_number": tracking_number,
        "carrier": "Verifund Logistics",
        "delivered_at": delivered_at.isoformat(),
        "recipient": "Demo Buyer",
    }


def summarize_ledger(
    rows: list[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        account = str(row["account"])
        bucket = summary.setdefault(account, {"debit": 0, "credit": 0})
        bucket["debit"] += int(row["debit_cents"])
        bucket["credit"] += int(row["credit_cents"])
    return summary


def encode_payload(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True).encode("utf-8")


@dataclass(frozen=True)
class FlowResult:
    transaction_id: str
    agreement_hash: str
    state: str
    receipt: dict[str, Any]


class VerifundFlow:
    def __init__(
        self,
        base_url: str,
        ops_token: str,
        *,
        console_base_url: str = "http://127.0.0.1:3000",
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.console_base_url = console_base_url.rstrip("/")
        self.ops_token = ops_token
        self._client = client or httpx.Client(
            base_url=self.base_url, timeout=timeout
        )
        self._owns_client = client is None

    def __enter__(self) -> VerifundFlow:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _ops_headers(
        self, actor: str, idempotency_key: str | None
    ) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {self.ops_token}",
            "x-verifund-actor": actor,
        }
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        return headers

    def _ops(
        self,
        method: str,
        path: str,
        *,
        actor: str = "buyer-agent",
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        response = self._client.request(
            method,
            path,
            headers=self._ops_headers(actor, idempotency_key),
            **kwargs,
        )
        response.raise_for_status()
        return response

    def award(self, run_id: str = DEFAULT_RUN_ID) -> dict[str, Any]:
        return self._ops(
            "POST",
            "/awards",
            json=award_payload(run_id),
            idempotency_key=f"award:{run_id}",
        ).json()

    def accept(
        self, award: Mapping[str, Any], *, seller_task_id: str = "task-verifund"
    ) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/accept",
            json={
                "seller_id": SELLER_ID,
                "agreement_hash": award["agreement_hash"],
                "accepted_total_cents": AMOUNT_CENTS,
                "seller_task_id": seller_task_id,
                "accepted_at": datetime.now(UTC).isoformat(),
            },
            idempotency_key=f"accept:{transaction_id}",
        ).json()

    def approve(
        self,
        award: Mapping[str, Any],
        *,
        approved_by: str = "console:reviewer",
    ) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/approve",
            actor="console:reviewer",
            json={
                "approval_id": f"approval-{transaction_id}",
                "approved_by": approved_by,
                "approved_at": datetime.now(UTC).isoformat(),
                "note": "verifund flow",
                "agreement_hash": award["agreement_hash"],
            },
            idempotency_key=f"approve:{transaction_id}",
        ).json()

    def fund(
        self,
        award: Mapping[str, Any],
        *,
        run_id: str = DEFAULT_RUN_ID,
    ) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        return_url = f"{self.console_base_url}/runs/{run_id}"
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/fund",
            json={
                "agreement_hash": award["agreement_hash"],
                "return_url": return_url,
                "cancel_url": return_url,
            },
            idempotency_key=f"fund:{transaction_id}",
        ).json()

    def complete_checkout(self, checkout_url: str) -> str:
        response = self._client.post(
            checkout_url, data={"action": "approve"}, follow_redirects=False
        )
        if response.status_code not in {302, 303}:
            raise RuntimeError(
                f"fake checkout returned {response.status_code}: "
                f"{response.text[:200]}"
            )
        return response.headers.get("location", "")

    def purchase_order(
        self,
        award: Mapping[str, Any],
        request: Mapping[str, Any],
        *,
        tracking_number: str = "VF-TRK-1",
    ) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        now = datetime.now(UTC)
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/purchase-order",
            json={
                "agreement_hash": award["agreement_hash"],
                "seller_order_id": f"MM-{transaction_id[-6:].upper()}",
                "offer_id": request["offer_id"],
                "quantity": request["quantity"],
                "total_cents": request["amount_cents"],
                "currency": request["currency"],
                "tracking_number": tracking_number,
                "carrier": "Verifund Logistics",
                "reserved_at": now.isoformat(),
                "eta": (
                    now + timedelta(days=int(request["delivery_days"]))
                ).isoformat(),
                "line_items": [
                    {
                        "sku": item["sku"],
                        "quantity": item["quantity"],
                        "unit_price_cents": item["unit_price_cents"],
                        "warranty_addon_cents": item["warranty_addon_cents"],
                    }
                    for item in request["line_items"]
                ],
            },
            idempotency_key=f"po:{transaction_id}",
        ).json()

    def upload_evidence(
        self,
        award: Mapping[str, Any],
        kind: str,
        payload: Mapping[str, Any],
        filename: str,
    ) -> dict[str, Any]:
        transaction_id = str(award["transaction_id"])
        response = self._client.post(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence",
            headers={"authorization": f"Bearer {award['seller_token']}"},
            data={
                "kind": kind,
                "note": f"verifund flow {kind}",
                "captured_at": datetime.now(UTC).isoformat(),
            },
            files={
                "file": (filename, encode_payload(payload), "application/json")
            },
        )
        response.raise_for_status()
        return response.json()

    def verify(self, transaction_id: str) -> dict[str, Any]:
        return self._ops(
            "POST", f"/transactions/{transaction_id}/verify", json={}
        ).json()

    def release(
        self,
        transaction_id: str,
        *,
        released_by: str = "console:reviewer",
    ) -> dict[str, Any]:
        return self._ops(
            "POST",
            f"/transactions/{transaction_id}/release",
            actor="console:reviewer",
            json={
                "released_by": released_by,
                "note": "verifund flow",
                "override": False,
            },
        ).json()

    def get_state(self, transaction_id: str) -> dict[str, Any]:
        return self._ops(
            "GET",
            f"/transactions/{transaction_id}/state",
            actor="console:reviewer",
        ).json()

    def get_receipt(self, transaction_id: str) -> dict[str, Any]:
        return self._ops(
            "GET",
            f"/transactions/{transaction_id}/receipt",
            actor="console:reviewer",
        ).json()

    def wait_for_state(
        self, transaction_id: str, state: str, *, timeout: float = 30.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        current: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            current = self.get_state(transaction_id)
            if current["state"] == state:
                return current
            time.sleep(0.2)
        raise TimeoutError(
            f"transaction {transaction_id} did not reach {state}: {current}"
        )

    def run(self, run_id: str = DEFAULT_RUN_ID) -> FlowResult:
        request = award_payload(run_id)
        award = self.award(run_id)
        self.accept(award)
        self.approve(award)
        funded = self.fund(award, run_id=run_id)
        self.complete_checkout(str(funded["checkout_url"]))
        self.wait_for_state(str(award["transaction_id"]), "FUNDED")
        self.purchase_order(award, request)
        now = datetime.now(UTC)
        self.upload_evidence(
            award,
            "shipment_manifest",
            manifest_payload(
                seller_id=SELLER_ID,
                agreement_hash=str(award["agreement_hash"]),
                tracking_number="VF-TRK-1",
                shipped_at=now - timedelta(hours=2),
            ),
            "shipment-manifest.json",
        )
        self.upload_evidence(
            award,
            "delivery_confirmation",
            delivery_payload(
                tracking_number="VF-TRK-1",
                delivered_at=now - timedelta(hours=1),
            ),
            "delivery-confirmation.json",
        )
        self.verify(str(award["transaction_id"]))
        self.release(str(award["transaction_id"]))
        state = self.wait_for_state(str(award["transaction_id"]), "RELEASED")
        receipt = self.get_receipt(str(award["transaction_id"]))
        return FlowResult(
            transaction_id=str(award["transaction_id"]),
            agreement_hash=str(award["agreement_hash"]),
            state=str(state["state"]),
            receipt=receipt,
        )
```

- [ ] **Step 4: Add the headless smoke runner**

`scripts/verifund_smoke.py`:

```python
"""Run a headless fake-mode Verifund lifecycle against a temporary control plane."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.config import ROOT  # noqa: E402
from scripts.verifund_flow import (  # noqa: E402
    AMOUNT_CENTS,
    SELLER_ID,
    VerifundFlow,
    summarize_ledger,
)

EXPECTED_LEDGER = {
    "platform_cash": {"debit": AMOUNT_CENTS, "credit": 0},
    "held_funds": {"debit": AMOUNT_CENTS, "credit": AMOUNT_CENTS},
    "seller_paid": {"debit": 0, "credit": AMOUNT_CENTS},
}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def smoke_environment(root: Path, *, port: int) -> dict[str, str]:
    return {
        "VERIFUND_MODE": "fake",
        "HOST": "127.0.0.1",
        "VERIFUND_PORT": str(port),
        "VERIFUND_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
        "VERIFUND_CONSOLE_BASE_URL": "http://127.0.0.1:3000",
        "VERIFUND_DATABASE_URL": (
            f"sqlite+aiosqlite:///{root / 'verifund.db'}"
        ),
        "VERIFUND_EVIDENCE_DIR": str(root / "evidence"),
        "VERIFUND_INSPECTION_WINDOW_HOURS": "0",
        "VERIFUND_RECONCILER_ENABLED": "false",
        "VERIFUND_OPS_TOKEN": "smoke-ops",
        "VERIFUND_SELLER_TOKEN_SECRET": "smoke-seller-token-secret",
        "VERIFUND_LINK_SECRET": "smoke-link-secret",
        "VERIFUND_SELLER_PAYOUT_EMAILS": json.dumps(
            {SELLER_ID: "seller-northwind@example.com"}
        ),
    }


def wait_for(url: str, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for {url}")


def ledger_rows(database: Path, transaction_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "select account, debit_cents, credit_cents "
            "from ledger_entries where transaction_id = ?",
            (transaction_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="run-verifund-smoke")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="verifund-smoke-") as tmp:
        root = Path(tmp)
        port = free_port()
        env = os.environ.copy()
        env.update(smoke_environment(root, port=port))
        log_path = root / "control-plane.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "verifund_control_plane"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                wait_for(f"http://127.0.0.1:{port}/health")
                with VerifundFlow(
                    f"http://127.0.0.1:{port}",
                    "smoke-ops",
                    console_base_url="http://127.0.0.1:3000",
                ) as flow:
                    result = flow.run(args.run_id)
                summary = summarize_ledger(
                    ledger_rows(root / "verifund.db", result.transaction_id)
                )
                if summary != EXPECTED_LEDGER:
                    raise AssertionError(f"unexpected ledger: {summary!r}")
                if result.state != "RELEASED":
                    raise AssertionError(
                        f"unexpected final state: {result.state}"
                    )
                if not result.receipt.get("verified"):
                    raise AssertionError("receipt signature did not verify")
                print(
                    json.dumps(
                        {
                            "transaction_id": result.transaction_id,
                            "state": result.state,
                            "agreement_hash": result.agreement_hash,
                            "receipt_payload_hash": result.receipt[
                                "payload_hash"
                            ],
                            "ledger": summary,
                        },
                        indent=2,
                    )
                )
                return 0
            except Exception:
                log.flush()
                print(
                    log_path.read_text(encoding="utf-8", errors="replace"),
                    file=sys.stderr,
                )
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Add the Playwright runner**

`scripts/verifund_e2e.py`:

```python
"""Run the fake Verifund stack and its Playwright acceptance test."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
CONSOLE_URL = f"http://127.0.0.1:{os.environ.get('CONSOLE_PORT', '3000')}"
CONTROL_PLANE_URL = (
    f"http://127.0.0.1:{os.environ.get('VERIFUND_PORT', '9300')}"
)


def e2e_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env["MARKETMESH_LLM_MODE"] = "scripted"
    env["VERIFUND_MODE"] = "fake"
    env["VERIFUND_INSPECTION_WINDOW_HOURS"] = "0"
    env["VERIFUND_CONTROL_PLANE_URL"] = CONTROL_PLANE_URL
    env.setdefault("VERIFUND_AGENT_PORT", "9301")
    env.setdefault(
        "VERIFUND_AGENT_INTERNAL_TOKEN", "dev-verifund-agent-internal"
    )
    env["VERIFUND_CONSOLE_BASE_URL"] = CONSOLE_URL
    env.setdefault(
        "CONSOLE_PORT", os.environ.get("CONSOLE_PORT", "3000")
    )
    return env


def playwright_command() -> list[str]:
    return [
        "pnpm",
        "exec",
        "playwright",
        "test",
        "e2e/verifund.spec.ts",
    ]


def wait_for(url: str, *, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {url}")


def stop_stack() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/dev.py"), "stop"],
        cwd=ROOT,
        check=False,
    )


def main() -> int:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        print(
            "pnpm is required for the Verifund browser test.", file=sys.stderr
        )
        return 1

    stop_stack()
    env = e2e_environment()
    dev = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts/dev.py"),
            "--scripted",
            "--verifund",
            "fake",
        ],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )
    try:
        wait_for(CONSOLE_URL)
        subprocess.run(
            [pnpm, "exec", "playwright", "install", "chromium"],
            cwd=ROOT / "apps/console",
            env=env,
            check=False,
        )
        return subprocess.run(
            playwright_command(),
            cwd=ROOT / "apps/console",
            env=env,
            check=False,
        ).returncode
    finally:
        if dev.poll() is None:
            try:
                os.killpg(dev.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                dev.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(dev.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        stop_stack()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Write the fake-mode browser test**

`apps/console/e2e/verifund.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

const MODE = process.env.VERIFUND_MODE ?? "off";

test.skip(MODE !== "fake", "Verifund fake mode only");

test("chat completes a Verifund transaction with two human approvals", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("MarketMesh", { exact: true })).toBeVisible();

  const runSample = page.getByRole("button", { name: "Run sample brief" });
  await expect(runSample).toBeEnabled({ timeout: 15_000 });
  await runSample.click();

  const approve = page.getByRole("button", { name: "Approve agreement and fund" });
  await expect(approve).toBeVisible({ timeout: 30_000 });
  await approve.first().click();

  const checkout = page.getByRole("link", {
    name: "Continue to PayPal checkout",
  });
  await expect(checkout).toBeVisible({ timeout: 30_000 });
  const checkoutUrl = await checkout.getAttribute("href");
  expect(checkoutUrl).toBeTruthy();
  await page.goto(checkoutUrl as string);

  await expect(
    page.getByRole("heading", { name: "Verifund fake checkout" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Approve payment" }).click();

  await expect(page.getByText("Payment confirmed", { exact: true })).toBeVisible({
    timeout: 30_000,
  });

  await expect(page.getByText("Order confirmed").first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    page.getByText(/2 of 2 evidence items/i),
  ).toBeVisible({ timeout: 60_000 });

  const release = page.getByRole("button", { name: "Approve payout release" });
  await expect(release).toBeVisible({ timeout: 60_000 });
  await release.click();

  await expect(page.getByText("Verifund receipt", { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("verified", { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("tab", { name: "Transaction Room" }).click();
  await expect(page.getByText("RELEASED", { exact: true })).toBeVisible();
});
```

- [ ] **Step 7: Keep the legacy browser spec off in settlement mode**

At the top of `apps/console/e2e/console.spec.ts`, after the imports:

```ts
const VERIFUND_MODE = process.env.VERIFUND_MODE ?? "off";

test.skip(
  VERIFUND_MODE !== "off",
  "Legacy MarketMesh flow runs only with Verifund off",
);
```

- [ ] **Step 8: Run the script tests**

Run: `uv run pytest tests/unit/test_verifund_scripts.py -v`
Expected: PASS.

- [ ] **Step 9: Run the headless fake lifecycle**

Run: `uv run python scripts/verifund_smoke.py`
Expected: PASS and print the transaction ID, `RELEASED`, the receipt hash, and the four-row ledger summary. The process exits `0` and the temporary control plane is stopped.

- [ ] **Step 10: Run the fake browser flow**

Run: `uv run python scripts/verifund_e2e.py`
Expected: the fake stack starts, `pnpm exec playwright test e2e/verifund.spec.ts` passes, the receipt panel shows `verified`, and the stack stops.

- [ ] **Step 11: Commit**

```bash
git add scripts/verifund_flow.py scripts/verifund_smoke.py scripts/verifund_e2e.py apps/console/e2e/verifund.spec.ts apps/console/e2e/console.spec.ts tests/unit/test_verifund_scripts.py
git commit -m "test(verifund): add headless smoke and fake-mode browser flow"
```

---

### Task 29: PayPal Sandbox preflight and gated sandbox smoke

**Files:**
- Create: `scripts/verifund_sandbox_preflight.py`
- Create: `scripts/verifund_sandbox_smoke.py`
- Test: `tests/unit/test_verifund_sandbox_preflight.py`
- Test: `tests/unit/test_verifund_sandbox_smoke.py`

**Interfaces:**
- Produces: `PreflightCheck`, `PreflightReport`, `preflight(settings, *, client)`, `main`; `SandboxSmokeConfig`, `smoke_config(env=None)`, `wait_for_state(source, transaction_id, *, target, timeout, poll_seconds, stop_states=frozenset())`, `wait_for_funding(source, transaction_id, *, timeout, poll_seconds)`, `wait_for_payout(source, transaction_id, *, timeout, poll_seconds)`, `main`.
- Consumes: `verifund_control_plane.settings.Settings`, PayPal Sandbox OAuth and webhook REST endpoints, `scripts/verifund_flow` (`VerifundFlow`, `award_payload`, `manifest_payload`, `delivery_payload`, `SELLER_ID`), and the running control plane's ops and seller APIs.

- [ ] **Step 1: Write the failing preflight tests**

`tests/unit/test_verifund_sandbox_preflight.py`:

```python
from __future__ import annotations

import httpx

from scripts.verifund_sandbox_preflight import preflight
from verifund_control_plane.settings import Settings


def sandbox_settings(**overrides):
    values = {
        "_env_file": None,
        "mode": "sandbox",
        "host": "127.0.0.1",
        "public_base_url": "https://verifund.example.com",
        "console_base_url": "https://console.example.com",
        "ops_token": "o" * 32,
        "seller_token_secret": "s" * 32,
        "link_secret": "l" * 32,
        "receipt_keys": {"test-1": "r" * 32},
        "receipt_active_kid": "test-1",
        "paypal_env": "sandbox",
        "paypal_api_base": "https://api-m.sandbox.paypal.com",
        "paypal_client_id": "client-id",
        "paypal_client_secret": "client-secret",
        "paypal_webhook_id": "WH-1",
        "paypal_platform_email": "platform@example.com",
        "paypal_buyer_email": "buyer@example.com",
        "seller_payout_emails": {"northwind-audio": "northwind@example.com"},
    }
    values.update(overrides)
    return Settings(**values)


def paypal_handler(requests: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(f"{request.method} {request.url}")
        host = request.url.host
        if host == "api-m.sandbox.paypal.com":
            if request.url.path == "/v1/oauth2/token":
                assert request.headers["authorization"].startswith("Basic ")
                return httpx.Response(
                    200,
                    json={"access_token": "A21.test", "expires_in": 32400},
                )
            if request.url.path == "/v1/notifications/webhooks/WH-1":
                assert request.headers["authorization"] == "Bearer A21.test"
                return httpx.Response(200, json={"id": "WH-1"})
        if host == "verifund.example.com":
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/webhooks/paypal":
                return httpx.Response(401, json={"detail": "signature"})
        return httpx.Response(404)

    return handler


def test_preflight_passes_a_complete_sandbox_configuration():
    requests: list[str] = []
    with httpx.Client(
        transport=httpx.MockTransport(paypal_handler(requests))
    ) as client:
        report = preflight(sandbox_settings(), client=client)

    assert report.ok, report.lines()
    assert [check.name for check in report.checks] == [
        "mode",
        "settings",
        "paypal_environment",
        "paypal_accounts",
        "seller_payouts",
        "reconciler",
        "paypal_oauth",
        "paypal_webhook",
        "public_health",
        "public_webhook",
    ]
    assert any(
        item == "POST https://verifund.example.com/webhooks/paypal"
        for item in requests
    )


def test_preflight_rejects_non_sandbox_mode_without_network():
    called: list[str] = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                called.append(str(request.url))
                or httpx.Response(500)
            )
        )
    ) as client:
        report = preflight(sandbox_settings(mode="fake"), client=client)

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["mode"].ok is False
    assert called == []


def test_preflight_stops_before_network_when_settings_fail():
    called: list[str] = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                called.append(str(request.url))
                or httpx.Response(500)
            )
        )
    ) as client:
        report = preflight(
            sandbox_settings(seller_payout_emails={}), client=client
        )

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["settings"].ok is False
    assert "VERIFUND_SELLER_PAYOUT_EMAILS" in checks["settings"].detail
    assert called == []


def test_preflight_rejects_payout_email_overlap():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500)
        )
    ) as client:
        report = preflight(
            sandbox_settings(
                seller_payout_emails={"northwind-audio": "buyer@example.com"}
            ),
            client=client,
        )

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["settings"].ok is False
    assert checks["seller_payouts"].ok is False
    assert "buyer account" in checks["seller_payouts"].detail


def test_preflight_reports_paypal_oauth_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                401,
                json={
                    "error": "invalid_client",
                    "error_description": "Client Authentication failed",
                },
            )
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = preflight(sandbox_settings(), client=client)

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["paypal_oauth"].ok is False
    assert "HTTP 401" in checks["paypal_oauth"].detail
    assert "Client Authentication failed" in checks["paypal_oauth"].detail
    assert checks["paypal_webhook"].ok is False
    assert "skipped" in checks["paypal_webhook"].detail


def test_preflight_reports_an_unreachable_public_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200, json={"access_token": "A21.test", "expires_in": 32400}
            )
        if request.url.path == "/v1/notifications/webhooks/WH-1":
            return httpx.Response(200, json={"id": "WH-1"})
        raise httpx.ConnectError("tunnel is down", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = preflight(sandbox_settings(), client=client)

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["public_health"].ok is False
    assert "ConnectError" in checks["public_health"].detail
    assert checks["public_webhook"].ok is False


def test_preflight_requires_the_reconciler():
    with httpx.Client(
        transport=httpx.MockTransport(paypal_handler())
    ) as client:
        report = preflight(
            sandbox_settings(reconciler_enabled=False), client=client
        )

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["reconciler"].ok is False
    assert "VERIFUND_RECONCILER_ENABLED" in checks["reconciler"].detail


def test_preflight_rejects_the_live_paypal_host():
    with httpx.Client(
        transport=httpx.MockTransport(paypal_handler())
    ) as client:
        report = preflight(
            sandbox_settings(
                paypal_api_base="https://api-m.paypal.com",
                public_base_url="https://verifund.example.com",
            ),
            client=client,
        )

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["paypal_environment"].ok is False
    assert checks["settings"].ok is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_sandbox_preflight.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.verifund_sandbox_preflight'`.

- [ ] **Step 3: Implement the preflight**

`scripts/verifund_sandbox_preflight.py`:

```python
"""Validate a PayPal Sandbox configuration before starting the control plane."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verifund_control_plane.settings import Settings  # noqa: E402

PAYPAL_SANDBOX_HOST = "https://api-m.sandbox.paypal.com"


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def lines(self) -> list[str]:
        return [
            f"[{'PASS' if check.ok else 'FAIL'}] {check.name}: {check.detail}"
            for check in self.checks
        ]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [
            {"name": check.name, "ok": check.ok, "detail": check.detail}
            for check in self.checks
        ]


def _json_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _error_detail(response: httpx.Response) -> str:
    payload = _json_payload(response)
    for key in ("error_description", "error", "message", "detail"):
        value = payload.get(key)
        if value:
            return str(value)[:200]
    return response.text[:200].strip() or response.reason_phrase


def _settings_check(settings: Settings) -> tuple[PreflightCheck, str | None]:
    try:
        settings.validate_for_mode()
    except ValueError as exc:
        return PreflightCheck("settings", False, str(exc)), str(exc)
    return (
        PreflightCheck(
            "settings", True, "required sandbox settings are present"
        ),
        None,
    )


def _account_checks(settings: Settings) -> list[PreflightCheck]:
    accounts = {
        "platform": settings.paypal_platform_email,
        "buyer": settings.paypal_buyer_email,
    }
    missing = [name for name, value in accounts.items() if not value]
    account_check = PreflightCheck(
        "paypal_accounts",
        not missing,
        (
            "platform and buyer emails are set"
            if not missing
            else f"missing: {', '.join(missing)}"
        ),
    )

    payout_emails = list(settings.seller_payout_emails.values())
    problems: list[str] = []
    if not payout_emails:
        problems.append("no seller payout emails")
    if len(payout_emails) != len(set(payout_emails)):
        problems.append("duplicate payout emails")
    reserved = {
        settings.paypal_platform_email,
        settings.paypal_buyer_email,
    } - {""}
    if reserved.intersection(payout_emails):
        problems.append(
            "a payout email reuses the platform or buyer account"
        )
    payout_check = PreflightCheck(
        "seller_payouts",
        not problems,
        (
            f"{len(payout_emails)} payout accounts configured"
            if not problems
            else "; ".join(problems)
        ),
    )
    return [account_check, payout_check]


def _paypal_checks(
    settings: Settings, client: httpx.Client
) -> list[PreflightCheck]:
    base = settings.paypal_api_base.rstrip("/")
    try:
        response = client.post(
            f"{base}/v1/oauth2/token",
            auth=(
                settings.paypal_client_id,
                settings.paypal_client_secret,
            ),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return [
            PreflightCheck("paypal_oauth", False, detail),
            PreflightCheck("paypal_webhook", False, "skipped: no access token"),
        ]
    if response.status_code != 200:
        detail = f"HTTP {response.status_code}: {_error_detail(response)}"
        return [
            PreflightCheck("paypal_oauth", False, detail),
            PreflightCheck("paypal_webhook", False, "skipped: no access token"),
        ]

    payload = _json_payload(response)
    token = str(payload.get("access_token") or "")
    oauth_check = PreflightCheck(
        "paypal_oauth",
        bool(token),
        (
            f"token acquired; expires_in={payload.get('expires_in')}"
            if token
            else "response did not include access_token"
        ),
    )
    if not token:
        return [
            oauth_check,
            PreflightCheck("paypal_webhook", False, "skipped: no access token"),
        ]

    try:
        webhook = client.get(
            f"{base}/v1/notifications/webhooks/{settings.paypal_webhook_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        return [
            oauth_check,
            PreflightCheck(
                "paypal_webhook",
                False,
                f"{type(exc).__name__}: {exc}",
            ),
        ]

    return [
        oauth_check,
        PreflightCheck(
            "paypal_webhook",
            webhook.status_code == 200,
            (
                f"{settings.paypal_webhook_id} resolved for this REST app"
                if webhook.status_code == 200
                else (
                    f"HTTP {webhook.status_code} for "
                    f"{settings.paypal_webhook_id}: {_error_detail(webhook)}"
                )
            ),
        ),
    ]


def _public_checks(
    settings: Settings, client: httpx.Client
) -> list[PreflightCheck]:
    base = settings.public_base_url.rstrip("/")
    checks: list[PreflightCheck] = []
    try:
        health = client.get(f"{base}/health")
    except httpx.HTTPError as exc:
        checks.append(
            PreflightCheck(
                "public_health",
                False,
                f"{type(exc).__name__}: {exc}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                "public_health",
                health.status_code == 200,
                f"HTTP {health.status_code} for {base}/health",
            )
        )

    try:
        webhook = client.post(
            f"{base}/webhooks/paypal",
            headers={"content-type": "application/json"},
            content=b"{}",
        )
    except httpx.HTTPError as exc:
        checks.append(
            PreflightCheck(
                "public_webhook",
                False,
                f"{type(exc).__name__}: {exc}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                "public_webhook",
                webhook.status_code == 401,
                (
                    f"HTTP {webhook.status_code} for {base}/webhooks/paypal; "
                    "401 proves unsigned requests reach the control plane"
                ),
            )
        )
    return checks


def preflight(
    settings: Settings, *, client: httpx.Client
) -> PreflightReport:
    checks: list[PreflightCheck] = []

    mode_ok = settings.mode == "sandbox"
    checks.append(
        PreflightCheck(
            "mode",
            mode_ok,
            f"VERIFUND_MODE is {settings.mode!r}; expected 'sandbox'",
        )
    )

    settings_check, settings_error = _settings_check(settings)
    checks.append(settings_check)

    environment_ok = (
        settings.paypal_env == "sandbox"
        and settings.paypal_api_base.rstrip("/") == PAYPAL_SANDBOX_HOST
    )
    checks.append(
        PreflightCheck(
            "paypal_environment",
            environment_ok,
            (
                f"PAYPAL_ENV={settings.paypal_env!r}, "
                f"PAYPAL_API_BASE={settings.paypal_api_base!r}"
            ),
        )
    )

    checks.extend(_account_checks(settings))
    checks.append(
        PreflightCheck(
            "reconciler",
            settings.reconciler_enabled,
            (
                "reconciler enabled"
                if settings.reconciler_enabled
                else "VERIFUND_RECONCILER_ENABLED=false"
            ),
        )
    )

    if mode_ok and settings_error is None:
        checks.extend(_paypal_checks(settings, client))
        checks.extend(_public_checks(settings, client))

    return PreflightReport(tuple(checks))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON"
    )
    args = parser.parse_args(argv)

    with httpx.Client(timeout=20.0, follow_redirects=False) as client:
        report = preflight(Settings(), client=client)

    if args.json:
        print(json.dumps(report.as_dicts(), indent=2))
    else:
        for line in report.lines():
            print(line)

    if report.ok:
        print("Sandbox preflight passed.")
        return 0
    print(
        "Sandbox preflight failed; fix the checks above.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write the failing sandbox-smoke tests**

`tests/unit/test_verifund_sandbox_smoke.py`:

```python
from __future__ import annotations

import pytest

from scripts.verifund_sandbox_smoke import (
    SandboxSmokeConfig,
    smoke_config,
    wait_for_funding,
    wait_for_state,
)


class FakeSource:
    def __init__(self, states: list[str]) -> None:
        self.states = list(states)
        self.calls = 0

    def get_state(self, transaction_id: str) -> dict[str, object]:
        self.calls += 1
        if len(self.states) > 1:
            state = self.states.pop(0)
        else:
            state = self.states[0]
        return {"transaction_id": transaction_id, "state": state}


def test_smoke_config_requires_the_gate():
    with pytest.raises(RuntimeError, match="VERIFUND_SANDBOX_SMOKE"):
        smoke_config({"VERIFUND_MODE": "sandbox"})


def test_smoke_config_requires_sandbox_mode():
    with pytest.raises(RuntimeError, match="VERIFUND_MODE=sandbox"):
        smoke_config(
            {"VERIFUND_SANDBOX_SMOKE": "1", "VERIFUND_MODE": "fake"}
        )


def test_smoke_config_requires_an_ops_token():
    with pytest.raises(RuntimeError, match="VERIFUND_OPS_TOKEN"):
        smoke_config(
            {"VERIFUND_SANDBOX_SMOKE": "1", "VERIFUND_MODE": "sandbox"}
        )


def test_smoke_config_reads_overrides():
    config = smoke_config(
        {
            "VERIFUND_SANDBOX_SMOKE": "1",
            "VERIFUND_MODE": "sandbox",
            "VERIFUND_CONTROL_PLANE_URL": "https://control.example.com/",
            "VERIFUND_OPS_TOKEN": "ops-token",
            "VERIFUND_SANDBOX_RUN_ID": "run-sandbox",
            "VERIFUND_SANDBOX_FUND_TIMEOUT": "60",
            "VERIFUND_SANDBOX_POLL_SECONDS": "1.5",
        }
    )

    assert config == SandboxSmokeConfig(
        base_url="https://control.example.com",
        ops_token="ops-token",
        run_id="run-sandbox",
        fund_timeout_seconds=60.0,
        poll_seconds=1.5,
    )


def test_wait_for_state_returns_the_target_projection():
    source = FakeSource(["FUNDING_PENDING", "FUNDED"])

    result = wait_for_state(
        source,
        "vf_1",
        target="FUNDED",
        timeout=5,
        poll_seconds=0,
        stop_states={"CANCELED"},
    )

    assert result["state"] == "FUNDED"
    assert source.calls == 2


def test_wait_for_funding_stops_on_canceled():
    with pytest.raises(RuntimeError, match="CANCELED"):
        wait_for_funding(
            FakeSource(["CANCELED"]), "vf_1", timeout=5, poll_seconds=0
        )


def test_wait_for_state_times_out():
    with pytest.raises(TimeoutError, match="FUNDED"):
        wait_for_state(
            FakeSource(["FUNDING_PENDING"]),
            "vf_1",
            target="FUNDED",
            timeout=0.01,
            poll_seconds=0,
            stop_states={"CANCELED", "FAILED"},
        )
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_verifund_sandbox_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.verifund_sandbox_smoke'`.

- [ ] **Step 6: Implement the gated sandbox smoke**

`scripts/verifund_sandbox_smoke.py`:

```python
"""Run one real PayPal Sandbox transaction against a running control plane.

This script is manual and gated: it needs `VERIFUND_SANDBOX_SMOKE=1`,
`VERIFUND_MODE=sandbox`, a public HTTPS tunnel, and a human who can pay with
the sandbox buyer account. It never runs in CI.

For a one-shot smoke, start the control plane with
`VERIFUND_INSPECTION_WINDOW_HOURS=0`. Otherwise the script stops after
`VERIFY` and prints the inspection deadline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Protocol

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verifund_flow import (  # noqa: E402
    SELLER_ID,
    VerifundFlow,
    award_payload,
    delivery_payload,
    manifest_payload,
)


class StateSource(Protocol):
    def get_state(self, transaction_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SandboxSmokeConfig:
    base_url: str
    ops_token: str
    run_id: str
    fund_timeout_seconds: float
    poll_seconds: float


def smoke_config(
    env: Mapping[str, str] | None = None,
) -> SandboxSmokeConfig:
    values = os.environ if env is None else env
    if values.get("VERIFUND_SANDBOX_SMOKE") != "1":
        raise RuntimeError(
            "set VERIFUND_SANDBOX_SMOKE=1 to run the PayPal sandbox smoke"
        )
    if values.get("VERIFUND_MODE") != "sandbox":
        raise RuntimeError(
            "the sandbox smoke requires VERIFUND_MODE=sandbox"
        )
    ops_token = values.get("VERIFUND_OPS_TOKEN", "")
    if not ops_token:
        raise RuntimeError("VERIFUND_OPS_TOKEN is required")
    return SandboxSmokeConfig(
        base_url=values.get(
            "VERIFUND_CONTROL_PLANE_URL", "http://127.0.0.1:9300"
        ).rstrip("/"),
        ops_token=ops_token,
        run_id=values.get(
            "VERIFUND_SANDBOX_RUN_ID", "run-verifund-sandbox"
        ),
        fund_timeout_seconds=float(
            values.get("VERIFUND_SANDBOX_FUND_TIMEOUT", "900")
        ),
        poll_seconds=float(
            values.get("VERIFUND_SANDBOX_POLL_SECONDS", "3")
        ),
    )


def wait_for_state(
    source: StateSource,
    transaction_id: str,
    *,
    target: str,
    timeout: float,
    poll_seconds: float,
    stop_states: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    current: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        current = source.get_state(transaction_id)
        state = str(current.get("state"))
        if state == target:
            return current
        if state in stop_states:
            raise RuntimeError(
                f"transaction {transaction_id} stopped in {state}"
            )
        time.sleep(poll_seconds)
    raise TimeoutError(
        f"transaction {transaction_id} did not reach {target} "
        f"within {timeout}s: {current}"
    )


def wait_for_funding(
    source: StateSource,
    transaction_id: str,
    *,
    timeout: float,
    poll_seconds: float,
) -> dict[str, Any]:
    return wait_for_state(
        source,
        transaction_id,
        target="FUNDED",
        timeout=timeout,
        poll_seconds=poll_seconds,
        stop_states={"CANCELED", "FAILED"},
    )


def wait_for_payout(
    source: StateSource,
    transaction_id: str,
    *,
    timeout: float,
    poll_seconds: float,
) -> dict[str, Any]:
    return wait_for_state(
        source,
        transaction_id,
        target="RELEASED",
        timeout=timeout,
        poll_seconds=poll_seconds,
        stop_states={"REVIEW_REQUIRED", "CANCELED", "FAILED"},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--payout-timeout",
        type=float,
        default=float(
            os.environ.get("VERIFUND_SANDBOX_PAYOUT_TIMEOUT", "600")
        ),
    )
    args = parser.parse_args(argv)

    try:
        config = smoke_config()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    run_id = args.run_id or config.run_id
    console_base_url = os.environ.get(
        "VERIFUND_CONSOLE_BASE_URL", "http://127.0.0.1:3000"
    )

    with VerifundFlow(
        config.base_url,
        config.ops_token,
        console_base_url=console_base_url,
    ) as flow:
        request = award_payload(run_id)
        award = flow.award(run_id)
        transaction_id = str(award["transaction_id"])
        flow.accept(award)
        flow.approve(award)
        funded = flow.fund(award, run_id=run_id)
        checkout_url = str(funded.get("checkout_url") or "")
        if not checkout_url:
            print(
                "The control plane did not return a checkout URL.",
                file=sys.stderr,
            )
            return 1

        print(f"transaction: {transaction_id}")
        print(f"agreement:   {award['agreement_hash']}")
        print("Open this PayPal sandbox checkout and pay as the buyer:")
        print(checkout_url)
        print(
            f"Waiting up to {config.fund_timeout_seconds:.0f}s for FUNDED...",
            flush=True,
        )

        try:
            state = wait_for_funding(
                flow,
                transaction_id,
                timeout=config.fund_timeout_seconds,
                poll_seconds=config.poll_seconds,
            )
        except (RuntimeError, TimeoutError) as exc:
            print(f"Funding did not complete: {exc}", file=sys.stderr)
            return 1

        funding = state.get("funding") or {}
        capture_id = funding.get("capture_id")
        print(f"FUNDED capture: {capture_id}")

        purchase = flow.purchase_order(award, request)
        print(f"purchase order: {purchase.get('state')}")

        now = datetime.now(UTC)
        tracking = "VF-SANDBOX-TRK-1"
        flow.upload_evidence(
            award,
            "shipment_manifest",
            manifest_payload(
                seller_id=SELLER_ID,
                agreement_hash=str(award["agreement_hash"]),
                tracking_number=tracking,
                shipped_at=now - timedelta(hours=2),
            ),
            "shipment-manifest.json",
        )
        flow.upload_evidence(
            award,
            "delivery_confirmation",
            delivery_payload(
                tracking_number=tracking,
                delivered_at=now - timedelta(hours=1),
            ),
            "delivery-confirmation.json",
        )

        verification = flow.verify(transaction_id)
        verification_state = verification.get("state")
        print(f"verify: {verification_state}")
        if verification_state == "REVIEW_REQUIRED":
            reasons = (verification.get("verification") or {}).get(
                "reasons"
            )
            print(f"Verification requires review: {reasons}", file=sys.stderr)
            return 1
        if verification_state == "VERIFICATION_PENDING":
            deadline = (verification.get("deadlines") or {}).get(
                "inspection"
            )
            print(
                "Evidence is complete, but the inspection window is open "
                f"until {deadline}.",
                file=sys.stderr,
            )
            print(
                "Restart the control plane with "
                "VERIFUND_INSPECTION_WINDOW_HOURS=0 for a one-shot smoke.",
                file=sys.stderr,
            )
            return 3

        released = flow.release(transaction_id)
        if released.get("state") != "RELEASED":
            print(
                "Waiting up to "
                f"{args.payout_timeout:.0f}s for the sandbox payout...",
                flush=True,
            )
            try:
                state = wait_for_payout(
                    flow,
                    transaction_id,
                    timeout=args.payout_timeout,
                    poll_seconds=config.poll_seconds,
                )
            except (RuntimeError, TimeoutError) as exc:
                print(f"Payout did not complete: {exc}", file=sys.stderr)
                return 1
        else:
            state = released

        receipt = flow.get_receipt(transaction_id)
        payout = state.get("payout") or {}
        print(
            json.dumps(
                {
                    "transaction_id": transaction_id,
                    "state": state.get("state"),
                    "agreement_hash": award["agreement_hash"],
                    "capture_id": capture_id,
                    "payout_batch_id": payout.get("batch_id"),
                    "payout_item_id": payout.get("item_id"),
                    "receipt_payload_hash": receipt.get("payload_hash"),
                    "receipt_signature": receipt.get("signature"),
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run the sandbox test suites**

Run: `uv run pytest tests/unit/test_verifund_sandbox_preflight.py tests/unit/test_verifund_sandbox_smoke.py -v`
Expected: PASS.

- [ ] **Step 8: Verify the preflight reports instead of crashing in off mode**

Run: `uv run python scripts/verifund_sandbox_preflight.py`
Expected: exit code `2`, lines beginning with `[FAIL] mode:` and `[FAIL] settings:` (the default mode is `off`), and no traceback. This proves the script is safe to run before sandbox configuration exists.

- [ ] **Step 9: Commit**

```bash
git add scripts/verifund_sandbox_preflight.py scripts/verifund_sandbox_smoke.py tests/unit/test_verifund_sandbox_preflight.py tests/unit/test_verifund_sandbox_smoke.py
git commit -m "feat(verifund): add sandbox preflight and gated live smoke"
```

---

### Task 30: Documentation, superseding note, and final verification

**Files:**
- Modify: `README.md`
- Create: `docs/verifund-paypal-sandbox.md`
- Modify: `docs/architecture.md`
- Modify: `docs/runbook.md`
- Modify: `docs/superpowers/specs/2026-10-21-marketmesh-a2a-commerce-design.md`

**Interfaces:**
- Produces: user-facing mode documentation, the PayPal Sandbox setup guide, operator actions, and an explicit statement that the new spec supersedes the payment non-goals only when Verifund is enabled.
- Consumes: every public command, environment variable, route, and state name implemented in Tasks 1–29.

- [ ] **Step 1: Mark the old MarketMesh spec as partly superseded**

In `docs/superpowers/specs/2026-10-21-marketmesh-a2a-commerce-design.md`, insert immediately after the `**Scope:**` line:

```markdown
> **Superseded in part — 2026-10-27.** The optional Verifund settlement
> subsystem (`VERIFUND_MODE=fake|sandbox`) is specified in
> [`2026-10-27-verifund-control-plane-design.md`](./2026-10-27-verifund-control-plane-design.md).
> The payment, escrow, and transaction-coordinator non-goals below continue to
> apply unchanged when `VERIFUND_MODE=off`, which remains the default.
```

- [ ] **Step 2: Update the README feature map**

In `README.md`, add this row to the end of the **What runs** table:

```markdown
| Verifund control plane | 9300 | Optional settlement authority; fake or PayPal Sandbox modes only |
```

Replace the **What is mocked** bullet that starts with “No payment processing” with:

```markdown
- `VERIFUND_MODE=off` performs no payment processing, money movement, or real
  shipping. `VERIFUND_MODE=fake` simulates the PayPal checkout and payouts in
  SQLite. `VERIFUND_MODE=sandbox` moves PayPal Sandbox funds only; no live money
  is involved.
```

Add this section after **Using the console** and before **Adding a fourth seller**:

```markdown
## Verifund settlement (optional)

`VERIFUND_MODE` selects the settlement behavior:

| Mode | Behavior |
| --- | --- |
| `off` (default) | Existing MarketMesh negotiation and order flow only. No control plane, no settlement fields, no extra processes. |
| `fake` | Local control plane on port 9300 and registered Verifund A2A agent on port 9301 with fake checkout and payouts. The chat-led agreement → funding → evidence → release → receipt lifecycle runs without network access. |
| `sandbox` | Real PayPal Sandbox Orders, Capture, Payouts, and webhooks. Manual testing only; the control plane refuses the live PayPal host. |

When enabled, the registered Verifund A2A agent works with the CopilotKit
orchestrator in chat. The user reviews the control-plane agreement and approves
funding in a HITL card, completes payer approval on PayPal's hosted page, then
reviews the deterministic evidence result and separately approves payout
release in chat. The Transaction Room shows the synchronized funding, evidence,
verification, payout, cancellation, and signed receipt details. Fake mode starts
the Verifund agent on port 9301; `off` starts no settlement services.

```bash
make verifund-smoke      # headless fake lifecycle; temporary control plane
make verifund-demo       # fake stack with the console
make verifund-e2e        # Playwright fake-mode acceptance test
make verifund-preflight  # PayPal Sandbox configuration checks
VERIFUND_SANDBOX_SMOKE=1 make verifund-sandbox-smoke  # gated manual sandbox run
```

Data lives in `data/verifund.db` and `data/evidence/`. `make reset` removes both.
See [`docs/verifund-paypal-sandbox.md`](docs/verifund-paypal-sandbox.md) for the
account, webhook, tunnel, and payout setup, and
[`docs/superpowers/specs/2026-10-27-verifund-control-plane-design.md`](docs/superpowers/specs/2026-10-27-verifund-control-plane-design.md)
for the design.
```

Add to the **Tests** section after the `make e2e` line:

```markdown
- `make verifund-smoke` — headless fake settlement lifecycle.
- `make verifund-e2e` — Playwright fake settlement flow.
```

Add to **Troubleshooting**:

```markdown
- Verifund control plane will not start: inspect `.dev-logs/verifund.log`; sandbox
  mode refuses default secrets, a missing webhook ID, a non-HTTPS public URL, and
  the live PayPal host.
- Fake checkout never reaches `FUNDED`: click **Refresh state** in the Transaction
  Room; the fake webhook is a UI convenience, not the source of truth.
- Sandbox capture or payout is missing: run `make verifund-preflight`, confirm the
  tunnel still points at port 9300, and check that the platform account has sandbox
  balance.
- Payout lands in `REVIEW_REQUIRED`: open the PayPal sandbox activity for the batch;
  funding mismatches, ledger inconsistencies, and late captures are resolved in
  PayPal, not with a Verifund override.
```

Replace the **Security limits** paragraph with:

```markdown
This is a local prototype. The bearer tokens in `.env` are development credentials,
not a production secret manager. The approval receipt proves that a UI interaction
occurred; it does not prove a verified human identity. Verifund is Sandbox-only and
must never be pointed at live PayPal. Do not expose these services to an untrusted
network or use this prototype for real purchasing, payment, or fulfillment.
```

- [ ] **Step 3: Document the settlement architecture**

In `docs/architecture.md`, add this row to the **Service boundaries** table:

```markdown
| Verifund control plane | Settlement state, held-funds ledger, evidence records, PayPal calls, receipts, audit | Mandate, ranking, seller stock |
```

Add this section after **Protocol split**:

```markdown
## Settlement subsystem

`VERIFUND_MODE=fake|sandbox` adds one authority for money and transaction state:

```text
Console ──► Buyer ──► Verifund control plane (:9300) ──► PayPal Sandbox
              │            │
              │            ├── SQLite: verifund.db
              └── A2A ──►  └── evidence: data/evidence/<sha256>
```

The buyer, seller, and console are clients. The control plane owns agreement
hashing, the state machine, the held-funds ledger, evidence records, PayPal calls,
webhooks, payout, receipts, and audit. The buyer stores only its copy of the seller
token in `run_secrets`; the seller stores its copy in `settlement_tokens`; neither
enters graph state, traces, logs, or AG-UI.

The state machine is `AWARDED → AGREED → FUNDING_PENDING → FUNDED →
FULFILLMENT_PENDING → VERIFICATION_PENDING → RELEASE_PERMITTED →
PAYOUT_PENDING → RELEASED`, with `REVIEW_REQUIRED`, `CANCELED`, and `FAILED` as
exception or terminal states. Policy computes `RELEASE_PERMITTED`; a reviewer
performs the audited release. Funding mismatches, ledger inconsistencies, and late
captures cannot be overridden and are resolved in PayPal.

`VERIFUND_MODE=off` keeps the service boundaries and behavior in the rest of this
document unchanged.
```

Add these bullets to **Failure handling**:

```markdown
- **Verifund capture pending** — the buyer keeps polling the compact state
  projection; the reconciler retries unmatched webhooks and late captures.
- **Verifund evidence incomplete at the deadline** — the transaction stays
  `VERIFICATION_PENDING`; it never releases on partial evidence.
- **Verifund payout failure** — the transaction moves to `REVIEW_REQUIRED`; the
  reviewer retries the payout or resolves it in PayPal.
```

Replace the sentence “There is no payment processing, real fulfillment, tenant isolation, or production secret management in this codebase.” with:

```markdown
There is no live payment processing, real fulfillment, tenant isolation, or
production secret management in this codebase. Verifund moves PayPal Sandbox
funds only and is disabled by default.
```

- [ ] **Step 4: Write the PayPal Sandbox guide**

`docs/verifund-paypal-sandbox.md`:

```markdown
# Verifund PayPal Sandbox guide

Verifund is the optional settlement subsystem for MarketMesh. This guide wires it
to PayPal Sandbox. `VERIFUND_MODE=off` remains the default and requires none of
this configuration.

Verifund v1 is Sandbox only. The control plane rejects
`https://api-m.paypal.com`, refuses default development secrets, and exits when the
sandbox configuration is incomplete. Do not point it at a live PayPal app.

## 1. What you need

| Item | Purpose |
| --- | --- |
| PayPal Developer account | Sandbox accounts, REST app, webhooks |
| Platform Business account | Owns the REST app, captures funds, sends Payouts |
| Buyer Personal account | Approves the checkout |
| One Personal account per seller | Receives Payouts; four recommended |
| Public HTTPS tunnel | Delivers PayPal return/cancel redirects and webhooks |
| Python + Node.js toolchain | `make setup`, `make dev` |

## 2. Create the sandbox accounts

1. Open <https://developer.paypal.com/dashboard/accounts>.
2. Create or confirm a **Business** sandbox account for the platform, country
   `US`, currency `USD`.
3. Create a **Personal** sandbox account for the buyer.
4. Create four **Personal** sandbox accounts for sellers. Confirm each email and
   confirm that it can receive Payouts.
5. Add sandbox funds to the platform Business account. Payouts fail without a
   balance.

Record every email. Seller payout emails must be unique and must not reuse the
platform or buyer account.

## 3. Create the REST app and webhook

1. In the Developer Dashboard, open **Apps & Credentials** in the **Sandbox**
   tab.
2. Create an app under the platform Business account.
3. Copy the **Client ID** and **Secret** into `PAYPAL_CLIENT_ID` and
   `PAYPAL_CLIENT_SECRET`.
4. Add a webhook with URL `https://<public-host>/webhooks/paypal`.
5. Subscribe to these events:
   - `PAYMENT.CAPTURE.COMPLETED`
   - `PAYMENT.CAPTURE.PENDING`
   - `PAYMENT.CAPTURE.DECLINED`
   - `PAYMENT.CAPTURE.REFUNDED`
   - `PAYMENT.CAPTURE.REVERSED`
   - `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`
   - `PAYMENT.PAYOUTS-ITEM.FAILED`
   - `PAYMENT.PAYOUTS-ITEM.BLOCKED`
   - `PAYMENT.PAYOUTS-ITEM.DENIED`
   - `PAYMENT.PAYOUTS-ITEM.RETURNED`
   - `PAYMENT.PAYOUTS-ITEM.REFUNDED`
   - `PAYMENT.PAYOUTS-ITEM.REVERSED`
   - `PAYMENT.PAYOUTS-ITEM.ONHOLD`
   - `PAYMENT.PAYOUTS-ITEM.UNCLAIMED`
   - `PAYMENT.PAYOUTS-ITEM.CANCELED`
6. Copy the webhook ID into `PAYPAL_WEBHOOK_ID`.
7. Copy the Business account email into `PAYPAL_PLATFORM_EMAIL` and the Personal
   buyer email into `PAYPAL_BUYER_EMAIL`.

The webhook must belong to the same REST app as the client credentials. Preflight
verifies this with `GET /v1/notifications/webhooks/{id}`.

Do not subscribe the release flow to `CHECKOUT.ORDER.COMPLETED`; PayPal documents
it as marketplace/platform-only.

## 4. Start the HTTPS tunnel

PayPal must reach the webhook and must redirect the buyer to the console. Start
the control plane first, then expose only port 9300:

```bash
cloudflared tunnel --url http://127.0.0.1:9300
```

Use the printed `https://...` origin as `VERIFUND_PUBLIC_BASE_URL`. Keep
`VERIFUND_CONSOLE_BASE_URL=http://127.0.0.1:3000`; the buyer's browser must be
able to open the local console after PayPal redirects back.

With ngrok:

```bash
ngrok http 9300
```

## 5. Configure `.env`

Generate each secret with `openssl rand -hex 32`. Do not reuse the development
defaults from `.env.example`.

```dotenv
VERIFUND_MODE=sandbox
VERIFUND_PORT=9300
VERIFUND_PUBLIC_BASE_URL=https://<public-host>
VERIFUND_CONSOLE_BASE_URL=http://127.0.0.1:3000
VERIFUND_ALLOW_PUBLIC_BIND=0

VERIFUND_OPS_TOKEN=<32+ random bytes>
VERIFUND_SELLER_TOKEN_SECRET=<32+ random bytes>
VERIFUND_LINK_SECRET=<32+ random bytes>
VERIFUND_RECEIPT_KEYS={"sandbox-1":"<32+ random bytes>"}
VERIFUND_RECEIPT_ACTIVE_KID=sandbox-1
BUYER_INTERNAL_TOKEN=<32+ random bytes>

VERIFUND_DATABASE_URL=sqlite+aiosqlite:///./data/verifund.db
VERIFUND_EVIDENCE_DIR=./data/evidence
VERIFUND_INSPECTION_WINDOW_HOURS=0
VERIFUND_RECONCILER_ENABLED=true
VERIFUND_SELLER_PAYOUT_EMAILS={"northwind-audio":"<seller-1>","circuitforge":"<seller-2>","aurora":"<seller-3>","summit-tech":"<seller-4>"}

PAYPAL_ENV=sandbox
PAYPAL_API_BASE=https://api-m.sandbox.paypal.com
PAYPAL_CLIENT_ID=<client-id>
PAYPAL_CLIENT_SECRET=<client-secret>
PAYPAL_WEBHOOK_ID=<webhook-id>
PAYPAL_PLATFORM_EMAIL=<platform-business-email>
PAYPAL_BUYER_EMAIL=<buyer-personal-email>
```

`VERIFUND_INSPECTION_WINDOW_HOURS=0` makes a one-shot demo release immediately
after verification. The production default is `24`; with a non-zero window the
transaction waits in `VERIFICATION_PENDING` until the deadline.

The buyer, seller, and orchestrator read their Verifund settings from the same
`.env`; `scripts/dev.py` copies the relevant values into each process.

## 6. Run the preflight

```bash
make verifund-preflight
```

Exit `0` means the sandbox configuration is complete. Exit `2` lists every failed
check. Add `--json` for machine-readable output.

| Check | What it proves |
| --- | --- |
| `mode` | `VERIFUND_MODE=sandbox` |
| `settings` | secrets are strong, the public URL is HTTPS, the receipt key exists, and the payout map is valid |
| `paypal_environment` | `PAYPAL_ENV=sandbox` and the sandbox API host |
| `paypal_accounts` | platform and buyer emails are set |
| `seller_payouts` | payout emails are present, unique, and not platform/buyer accounts |
| `reconciler` | webhook fallback and deadline processing are enabled |
| `paypal_oauth` | the client ID/secret obtain a sandbox access token |
| `paypal_webhook` | the webhook ID resolves for this REST app |
| `public_health` | the tunnel reaches `GET /health` |
| `public_webhook` | an unsigned `POST /webhooks/paypal` returns `401`, proving traffic reaches the control plane |

## 7. Exercise fake mode first

```bash
make verifund-smoke
make verifund-e2e
```

The first command runs the complete lifecycle against a temporary fake control
plane. The second starts the fake control plane, registry, buyer, Verifund A2A
agent, orchestrator, seller, and console; Playwright drives agreement/funding
and payout-release HITL decisions through chat, then checks the synchronized
Transaction Room. Fix fake-mode failures before spending time on PayPal.

## 8. Run the sandbox smoke

```bash
make down
VERIFUND_SANDBOX_SMOKE=1 make verifund-sandbox-smoke
```

The script is manual and never runs in CI. It:

1. Creates an award, agreement, acceptance, and approval.
2. Creates the PayPal Sandbox order and prints the payer-action URL.
3. Waits for you to pay with the buyer Personal account.
4. Reports the purchase order and uploads shipment/delivery evidence.
5. Verifies policy and performs the audited release.
6. Waits for the Payouts batch and fetches the signed receipt.

Record the printed transaction ID, agreement hash, capture ID, payout batch/item
IDs, and receipt hash as the sandbox evidence required by the design.

If the inspection window is not zero, the script exits `3` after verification and
prints the deadline. That is not a failure: wait for the window, then release in
the console or rerun with `VERIFUND_INSPECTION_WINDOW_HOURS=0`.

## 9. Run the manual console flow

1. `make down`
2. `uv run python scripts/dev.py --verifund sandbox`
3. Open <http://127.0.0.1:3000>, run the sample brief, and review the exact
   agreement in the chat HITL card.
4. Approve agreement/funding in chat, follow the checkout action, and pay as the
   buyer on PayPal's hosted page.
5. Return to the run chat and wait for confirmed capture, seller order, two
   evidence items, and the control plane's verification result.
6. Review the evidence summary and approve payout release in the separate chat
   HITL card; the verified receipt appears in chat.
7. Open the Transaction Room to inspect the synchronized timeline, evidence,
   payout state, and receipt.

The buyer keeps polling `GET /transactions/{id}/state`; chat and the
Transaction Room render the same run projection when `last_seq` advances.

## 10. Webhook behavior

- `PAYMENT.CAPTURE.COMPLETED` records the capture and moves to `FUNDED`.
- `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` moves `PAYOUT_PENDING` to `RELEASED`.
- Capture or payout failures move to `REVIEW_REQUIRED`.
- Duplicate `event_id` values are stored once; the second delivery returns
  `{"status":"duplicate"}`.
- Unmatched or temporarily failed events stay in the webhook store; the
  in-process reconciler retries them and also polls PayPal when webhooks are lost.

## 11. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are required` | Fill both in the sandbox app |
| `PAYPAL_WEBHOOK_ID is required` | Create the webhook and copy its ID |
| `VERIFUND_PUBLIC_BASE_URL must be HTTPS` | Start the tunnel and use its HTTPS origin |
| `webhook signature is invalid` | The webhook belongs to another app, or a proxy modified the body |
| `VERSION_ALREADY_USED` during funding | Wait for the reconciler, then `POST /transactions/{id}/funding/refresh` |
| Still `FUNDING_PENDING` | The buyer did not approve the PayPal order |
| `VERIFICATION_PENDING` after evidence | The inspection window is still open |
| `PAYOUT_PENDING` for a long time | The platform Business account has no sandbox balance |
| Payout item `RECEIVER_UNREGISTERED` | The seller email is unconfirmed or cannot receive Payouts |
| `REVIEW_REQUIRED` with `ledger_incomplete` or `funding_mismatch` | Resolve in PayPal; these reasons cannot be overridden in Verifund |
| `REVIEW_REQUIRED` after release | A refund or reversal arrived; reconcile it in PayPal |

## 12. Shut down and reset

```bash
make down
make reset   # removes data/verifund.db, data/evidence/, and the other local DBs
```

Never delete `data/verifund.db` while the control plane is running.
```

- [ ] **Step 5: Add Verifund operations to the runbook**

In `docs/runbook.md`, add this row to **Ports and health**:

```markdown
| Verifund control plane | <http://127.0.0.1:9300> | `/health`, `/ready`, `/metrics` |
```

Add to **Start and stop**:

```markdown
uv run python scripts/dev.py --verifund fake     # fake settlement stack
uv run python scripts/dev.py --verifund sandbox  # real PayPal Sandbox stack
make verifund-smoke                              # headless fake lifecycle
```

Add this section after **Token rotation** and before **Common errors**:

```markdown
## Verifund operations

`VERIFUND_MODE` is `off`, `fake`, or `sandbox` (default `off`). The control plane
listens on `127.0.0.1:9300` only when the mode is `fake` or `sandbox`.

| Mode | Start | PayPal |
| --- | --- | --- |
| `off` | `make dev` | none |
| `fake` | `uv run python scripts/dev.py --verifund fake` | local fake checkout |
| `sandbox` | `uv run python scripts/dev.py --verifund sandbox` | real Sandbox REST + webhooks |

Logs are in `.dev-logs/verifund.log`. Health: `GET /health`; readiness:
`GET /ready`; metrics: `GET /metrics`.

```bash
curl http://127.0.0.1:9300/health
curl -H "Authorization: Bearer $VERIFUND_OPS_TOKEN" \
  http://127.0.0.1:9300/transactions
```

Common actions:

| Situation | Action |
| --- | --- |
| Capture not reflected | `POST /transactions/{id}/funding/refresh`; the reconciler also polls |
| Evidence complete, policy waiting | Wait for the inspection deadline |
| Payout stuck in `PAYOUT_PENDING` | `POST /transactions/{id}/payout` after checking the PayPal batch |
| Verification or policy failure | Reviewer `POST /release` with `override: true` and a note, except for funding mismatch, ledger inconsistency, or late capture |
| Buyer no longer wants the order | `POST /transactions/{id}/cancel` with an allowed reason |
| Refund or reversal after release | Resolve in PayPal; the transaction moves to `REVIEW_REQUIRED` |

`make reset` deletes `data/verifund.db` and `data/evidence/` along with the other
local databases. Stop the stack first.
```

Add to **Manual smoke test** after the legacy reject step:

```markdown
For the fake settlement flow:

```bash
make verifund-smoke
make verifund-e2e
```

For PayPal Sandbox, follow [`verifund-paypal-sandbox.md`](verifund-paypal-sandbox.md)
and then run the gated smoke:

```bash
VERIFUND_SANDBOX_SMOKE=1 make verifund-sandbox-smoke
```
```

Replace the final sentence of **Safe operating limits** (“There is no payment processing…”) with:

```markdown
There is no live payment processing, real fulfillment, tenant isolation, or
production secret management in this codebase. Verifund moves PayPal Sandbox
funds only and is disabled by default.
```

- [ ] **Step 6: Verify documentation links and mode wording**

Run: `test -f docs/verifund-paypal-sandbox.md && rg -n "VERIFUND_MODE|verifund-paypal-sandbox" README.md docs/runbook.md docs/architecture.md`
Expected: every file mentions the mode switch, and both README and the runbook link to the sandbox guide.

- [ ] **Step 7: Run the Python suite and lint**

Run: `uv run pytest tests -q`
Expected: PASS.

Run: `uv run ruff check .`
Expected: PASS with no errors.

Run: `uv run python scripts/check_standalone.py`
Expected: PASS; only the guard and its tests mention the parent backend path or module names.

- [ ] **Step 8: Run the console suite**

Run: `cd apps/console && pnpm run test`
Expected: PASS.

Run: `cd apps/console && pnpm run typecheck`
Expected: PASS.

Run: `cd apps/console && pnpm run build`
Expected: PASS.

- [ ] **Step 9: Run the fake settlement end to end**

Run: `uv run python scripts/verifund_smoke.py`
Expected: exit `0`, `RELEASED`, a verified receipt hash, and the four-row ledger summary.

Run: `uv run python scripts/verifund_e2e.py`
Expected: the fake stack starts, `e2e/verifund.spec.ts` passes, and the receipt panel shows `verified`.

- [ ] **Step 10: Confirm the default path is unchanged**

Run: `VERIFUND_MODE=off uv run pytest tests/unit tests/protocol tests/integration -q`
Expected: PASS, and no process on port 9300 is started by the tests.

Run: `git status --porcelain`
Expected: clean after the commit below.

- [ ] **Step 11: Commit**

```bash
git add README.md docs/verifund-paypal-sandbox.md docs/architecture.md docs/runbook.md docs/superpowers/specs/2026-10-21-marketmesh-a2a-commerce-design.md
git commit -m "docs(verifund): document sandbox setup, operations, and off-mode compatibility"
```

---

## Plan complete

All 30 tasks are defined. Execution order is dependency order; each task ends
with its own tests and commit. Do not skip a red/green cycle.

