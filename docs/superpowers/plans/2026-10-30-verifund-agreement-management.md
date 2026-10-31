# Verifund Agreement Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote bilateral agreement generation into a first-class Verifund service: deterministic itemized goods agreements, separate seller acceptance / buyer agreement approval / funding authorization, immutable versioning with structured change requests, per-stage expiry, seller mandate enforcement, and three approval surfaces over one consent service.

**Architecture:** Add an `agreements/` package inside `verifund_control_plane` as the sole authority for agreement state (modular monolith, same process and SQLite DB). Extend shared contracts in `verifund_contracts` and `commerce_core`. Reorder the Verifund lifecycle to seller → buyer → funding. Add a console review page and a non-blocking chat card. Clean schema reset; no migrations.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, SQLite, Pydantic v2, LangGraph, Next.js 15, CopilotKit, pytest, vitest.

**Specs:**
- `docs/superpowers/specs/verifund-agreement-enhancement.md` — the requested behavior and architectural recommendation.
- `docs/superpowers/specs/2026-10-30-verifund-agreement-management-design.md` — the approved, detailed design this plan implements. Section references below (§n) point here unless stated otherwise.

---

## How to use this plan

Execute phases in order. Every task is test-first, ends with a focused verification command, and ends with a commit. Do not start a task until the previous task's verification passes. The control plane and shared contracts are the foundation; agents and console must not be changed before Phase 2 is green.

Run Python commands from the repository root with `uv run`. Run console commands from `apps/console` with `pnpm`.

## Scope check

This is one end-to-end feature with a strict dependency chain: shared contracts → control plane → seller agent → buyer agent → Verifund agent/orchestrator → console. Splitting it into independent plans would create non-working intermediate products because the A2A envelopes and agreement state are shared. The phase order still creates working checkpoints: the control plane is fully testable over HTTP before any agent changes, and the agents are testable before the console exists.

## Spec reconciliation (enhancement doc → approved design)

The enhancement document uses illustrative names. The approved design refines them; implement the approved design and preserve the enhancement document's guarantees.

| Enhancement doc term | Implemented term | Why |
|---|---|---|
| `PENDING_SELLER_ACCEPTANCE` | `AgreementState.PENDING_SELLER` | Shorter persisted value; same meaning. |
| `PENDING_BUYER_APPROVAL` | `AgreementState.PENDING_BUYER` | Same meaning. |
| `ACTIVE` | No persisted state; `AGREED` + transaction `AGREED`/`FUNDING_PENDING` | §4.2: `AGREED` is terminal for consent; funding does not mutate the agreement. |
| `DRAFT` | No persisted state; generation/validation/digest/render complete before insert | §4.2: the first persisted state is `PENDING_SELLER`. |
| Transaction `AGREEMENT_PENDING` | Transaction stays `AWARDED` while agreement is `PENDING_SELLER`/`PENDING_BUYER` | Avoids a second transaction state with no distinct money semantics; the agreement state is the observable agreement phase. |
| `seller_acceptances` + `buyer_approvals` tables | One append-only `agreement_decisions` table with `party` | Same evidence, one CAS/idempotency path; §11.1. |
| `verifund_get_agreement` etc. | `GET /agreements/{id}` plus the A2A operations in Phase 5 | Independently callable operations without inventing a second API style. |
| `agreement_digest` | `agreement_hash` | Existing field name is retained for compatibility; it is the SHA-256 digest. |

The invariant from the enhancement doc is implemented verbatim in `AgreementService.verify_funding_binding()`:

```python
def verify_funding_binding(agreement: Agreement, transaction: TransactionProjection,
                           version: int, digest: str) -> None:
    if agreement.status is not AgreementState.AGREED:
        raise AgreementError("invalid_state", "agreement is not AGREED")
    if agreement.current_version != version:
        raise AgreementError("hash_mismatch", "stale agreement version")
    current = agreement.current_version_record
    if current.agreement_hash != digest:
        raise AgreementError("hash_mismatch", "stale agreement digest")
    buyer = agreement.effective_decision("buyer")
    seller = agreement.effective_decision("seller")
    if buyer is None or seller is None:
        raise AgreementError("invalid_state", "both acceptances are required")
    for decision in (buyer, seller):
        if decision.version != version or decision.agreement_hash != digest:
            raise AgreementError("hash_mismatch", "acceptance does not bind this version")
    if transaction.agreement_id != agreement.agreement_id:
        raise AgreementError("invalid_state", "transaction is bound to another agreement")
```

## Global Constraints

- Clean DB reset only. No migration code. Delete `data/verifund.db*` before running.
- No backward-compatible A2A envelopes; bump `VERIFUND_SCHEMA_BASE` to `/v2`.
- All timestamps are UTC ISO-8601 with `Z`. Money is integer cents.
- `Idempotency-Key` is required on every mutating agreement endpoint.
- No LLM in agreement generation, validation, term application, or consent recording.
- Approval tokens are never stored in plaintext and never logged.
- Demo `ActorContext` only; Clerk is a later milestone.
- Goods v1 only: no services, subscriptions, multi-currency, PDF, or e-signature.
- `AGREED` requires two `ACCEPT` decisions on the same current version and digest.
- Funding is impossible unless `status = AGREED`, the current version/digest match, both decisions bind that version/digest, and the transaction points at the agreement.
- Seller agents may auto-accept only inside their configured mandate; otherwise `OPERATOR_REQUIRED`.
- One open change request per agreement. A change request never mutates an existing version; it creates `N+1` and requires two fresh acceptances.
- Old versions, decisions, and change requests are never deleted.
- Never put an approval token in chat, logs, audit payloads, or idempotency responses.

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `packages/commerce_core/commerce_core/binding.py` | `canonical_offer_binding`, `binding_from_award`, `offer_hash`; the single offer projection shared by buyer, seller, and control plane. |
| `apps/verifund_control_plane/verifund_control_plane/agreements/__init__.py` | Package exports. |
| `.../agreements/models.py` | Aggregate dataclasses, enums, `ActorContext`, `AgreementProjection` builder. |
| `.../agreements/states.py` | Transition table and guards. |
| `.../agreements/digest.py` | Canonical JSON and SHA-256 envelope. |
| `.../agreements/generator.py` | Award validation, goods-v1 terms construction, term validation, change-set application. |
| `.../agreements/renderer.py` | Deterministic HTML rendering. |
| `.../agreements/repository.py` | Agreement tables and CAS/query operations. |
| `.../agreements/tokens.py` | Buyer approval token issue/verify/consume. |
| `.../agreements/service.py` | Agreement lifecycle orchestration. |
| `.../agreements/routes.py` | HTTP endpoints and actor resolution. |
| `.../agreements/expiry.py` | Lazy and reconciler-driven expiry. |
| `.../agreements/templates/goods_agreement.html` | Deterministic server-side template. |
| `apps/seller_agent/seller_agent/mandate.py` | `SellerMandate` model and loader. |
| `apps/seller_agent/seller_agent/agreement_store.py` | `seller_agreement_reviews` persistence and chain lookup. |
| `apps/console/app/agreements/[id]/page.tsx` | Dedicated agreement review page. |
| `apps/console/app/agreements/[id]/actions.ts` | Server actions for decision + run resume. |
| `apps/console/features/agreements/AgreementDocument.tsx` | Rendered terms and digest. |
| `apps/console/features/agreements/AgreementSummary.tsx` | Version, total, status, seller decision, precheck. |
| `apps/console/features/agreements/ApprovalActions.tsx` | Approve / reject / request changes. |
| `apps/console/features/agreements/VersionHistory.tsx` | Version and decision history. |
| `apps/console/features/agreements/AgreementApprovalCard.tsx` | Chat notification card with review link. |

### Modified files

| Path | Change |
|---|---|
| `packages/commerce_core/commerce_core/contracts.py` | `Offer.tax_cents`, `Offer.fees_cents`, total validator, `round`. |
| `packages/verifund_contracts/verifund_contracts/models.py` | Agreement enums/views, extended projection/award/approve/fund models. |
| `packages/verifund_contracts/verifund_contracts/a2a.py` | Checkpoints, buyer approval resume model, extended review envelopes, `/v2`. |
| `apps/verifund_control_plane/verifund_control_plane/repository.py` | New tables, `transactions.agreement_id`, precheck column, schema reset. |
| `apps/verifund_control_plane/verifund_control_plane/service.py` | Award/accept/precheck/approve/fund/cancel integration. |
| `apps/verifund_control_plane/verifund_control_plane/app.py` | Agreement router, service, signer, expiry wiring. |
| `apps/verifund_control_plane/verifund_control_plane/settings.py` | Agreement windows and token TTL. |
| `apps/verifund_control_plane/verifund_control_plane/reconciler.py` | Agreement expiry sweep and funding-expiry termination. |
| `apps/verifund_control_plane/verifund_control_plane/api/checkout.py` | Award/accept/precheck/approve/fund request handling. |
| `apps/seller_agent/seller_agent/agreement.py` | Offer hash, digest, chain, mandate verification. |
| `apps/seller_agent/seller_agent/graph.py` | Extended review result and decision routing. |
| `apps/seller_agent/seller_agent/store.py` | Store reviewed versions. |
| `apps/seller_agent/seller_agent/profiles/*.yaml` | `mandate` block. |
| `apps/buyer_agent/buyer_agent/graph.py` | Seller → precheck → buyer approval → funding order. |
| `apps/buyer_agent/buyer_agent/agreement_service.py` | Agreement reads, precheck, seller decision, funding binding. |
| `apps/buyer_agent/buyer_agent/settlement_client.py` | New agreement/token/decision methods. |
| `apps/buyer_agent/buyer_agent/review.py` | Extended review envelope parsing. |
| `apps/verifund_agent/verifund_agent/graph.py` | Seller → buyer → change loop → funding; `sync_agreement`. |
| `apps/verifund_agent/verifund_agent/service.py` | Agreement status reads and resume binding. |
| `apps/verifund_agent/verifund_agent/client.py` | Buyer internal agreement endpoint. |
| `apps/orchestrator_agent/orchestrator_agent/verifund.py` | Seller review → buyer approval → funding; `resume_agreement`. |
| `apps/orchestrator_agent/orchestrator_agent/agent.py` | Review-card instructions; no chat approval. |
| `apps/console/lib/api.ts` | Control-plane agreement client methods. |
| `apps/console/lib/types.ts` | Agreement types. |
| `apps/console/features/chat/verifund-tools.tsx` | Checkpoint labels and agreement card. |
| `apps/console/features/chat/chat.tsx` | Funding card version/digest and review link. |
| `docs/workflow.md` | New lifecycle, invariants, approval separation. |

### Test files

| Path | Covers |
|---|---|
| `tests/unit/test_commerce_contracts.py` | Offer tax/fees and totals. |
| `tests/unit/test_offer_binding.py` | Shared offer projection and hash. |
| `tests/unit/test_agreement_digest.py` | Canonical JSON, digest binding, tamper detection. |
| `tests/unit/test_agreement_generator.py` | Goods-v1 terms, validation, change sets. |
| `tests/unit/test_agreement_renderer.py` | Deterministic, escaped HTML. |
| `tests/unit/test_agreement_states.py` | Allowed/forbidden transitions. |
| `tests/unit/test_agreement_repository.py` | Schema, CAS, tokens, events, expiry. |
| `tests/unit/test_agreement_tokens.py` | Sign/verify/consume/revoke. |
| `tests/unit/test_agreement_service.py` | Create, decide, change, expire, funding binding. |
| `tests/integration/test_agreement_routes.py` | HTTP auth, idempotency, happy path, errors. |
| `tests/integration/test_agreement_lifecycle.py` | End-to-end award → seller → buyer → funding. |
| `tests/integration/test_agreement_expiry.py` | Lazy and reconciler expiry. |
| `tests/unit/test_seller_mandate.py` | Mandate limits. |
| `tests/unit/test_seller_agreement_review.py` | Offer/digest/chain/mandate verification. |
| `tests/unit/test_buyer_agreement_service.py` | Buyer reads, precheck, funding binding. |
| `tests/unit/test_buyer_agreement_checkpoints.py` | Seller → precheck → buyer → funding order. |
| `tests/unit/test_verifund_agent_graph.py` | Graph reorder and change loop. |
| `tests/unit/test_orchestrator_verifund.py` | Orchestrator order and resume binding. |
| `apps/console/features/agreements/*.test.tsx` | Review page, stale digest, actions. |

## Task Index

- Phase 0 — Shared contracts and offer binding
  - Task 0.1 — Extend `Offer` with tax, fees, round, and total validation
  - Task 0.2 — Add the shared offer binding and hash
  - Task 0.3 — Extend `verifund_contracts` agreement models
  - Task 0.4 — Extend A2A envelopes and checkpoints to `/v2`
- Phase 1 — Control-plane agreement module
  - Task 1.1 — Agreement aggregates and state machine
  - Task 1.2 — Digest and goods-v1 generator
  - Task 1.3 — Deterministic HTML renderer
  - Task 1.4 — Agreement repository and schema
  - Task 1.5 — Buyer approval tokens
  - Task 1.6 — Agreement service lifecycle
  - Task 1.7 — Agreement HTTP routes and app wiring
- Phase 2 — Control-plane integration
  - Task 2.1 — Award creates agreement + transaction atomically
  - Task 2.2 — Seller decision and non-binding buyer precheck
  - Task 2.3 — Buyer decision and token issuance
  - Task 2.4 — Funding authorization and funding binding
  - Task 2.5 — Expiry reconciler and termination
  - Task 2.6 — Cancellation mapping
- Phase 3 — Seller agent
  - Task 3.1 — Seller mandate and profile configuration
  - Task 3.2 — Agreement verification against offer, digest, and mandate
  - Task 3.3 — Local review history and version-chain verification
  - Task 3.4 — Seller graph and A2A result integration
- Phase 4 — Buyer agent
  - Task 4.1 — Settlement client agreement methods
  - Task 4.2 — Buyer agreement service methods and funding binding
  - Task 4.3 — Graph reorder: seller → precheck → buyer → funding
  - Task 4.4 — Extended seller review envelope parsing
- Phase 5 — Verifund agent and orchestrator
  - Task 5.1 — Verifund graph reorder and `sync_agreement`
  - Task 5.2 — Verifund service/client agreement reads
  - Task 5.3 — Orchestrator seller → buyer → funding lifecycle
  - Task 5.4 — Orchestrator instructions and review card
- Phase 6 — Console
  - Task 6.1 — Control-plane client and types
  - Task 6.2 — Agreement review page and server actions
  - Task 6.3 — Chat agreement card and checkpoint labels
  - Task 6.4 — Funding card version/digest binding
- Phase 7 — Reset, docs, verification
  - Task 7.1 — Schema reset and seed
  - Task 7.2 — Workflow documentation
  - Task 7.3 — Full focused verification

---

## Phase 0 — Shared contracts and offer binding

### Task 0.1: Extend `Offer` with tax, fees, and a correct total

**Files:**
- Modify: `packages/commerce_core/commerce_core/contracts.py`
- Test: `tests/unit/test_commerce_contracts.py`

**Interfaces:**
- Consumes: none.
- Produces: `Offer.tax_cents`, `Offer.fees_cents`, `Offer.round` (already present), `Offer.validate_totals()` requiring `total = subtotal + shipping + tax + fees`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_commerce_contracts.py
from datetime import datetime, timedelta

from commerce_core.contracts import (
    Currency,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
)


def test_offer_total_includes_tax_and_fees():
    item = OfferLineItem(
        sku="S", name="N", quantity=2,
        unit_price_cents=1000, list_unit_price_cents=1200,
    )
    offer = Offer(
        offer_id="o1", request_id="r1", seller_id="s1",
        seller_name="S", seller_rating=4.5, currency=Currency.USD,
        line_items=[item], subtotal_cents=2000, shipping_cents=300,
        tax_cents=150, fees_cents=50, total_cents=2500,
        delivery_days=3, valid_until=datetime.now(UTC) + timedelta(hours=1),
    )
    assert offer.total_cents == 2500


def test_offer_rejects_wrong_total():
    item = OfferLineItem(
        sku="S", name="N", quantity=1,
        unit_price_cents=1000, list_unit_price_cents=1200,
    )
    import pytest
    with pytest.raises(ValueError):
        Offer(
            offer_id="o1", request_id="r1", seller_id="s1",
            seller_name="S", seller_rating=4.5, currency=Currency.USD,
            line_items=[item], subtotal_cents=1000, shipping_cents=300,
            tax_cents=150, fees_cents=50, total_cents=9999,
            delivery_days=3, valid_until=datetime.now(UTC) + timedelta(hours=1),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_commerce_contracts.py -v`
Expected: FAIL — `tax_cents` unknown field.

- [ ] **Step 3: Implement**

In `packages/commerce_core/commerce_core/contracts.py`, add fields and fix the validator:

```python
# packages/commerce_core/commerce_core/contracts.py — in class Offer(CommerceModel):
# Add these two fields (all other fields unchanged):
    tax_cents: int = Field(default=0, ge=0)
    fees_cents: int = Field(default=0, ge=0)

# In Offer.validate_totals, replace the total check with:
    if self.total_cents != (
        self.subtotal_cents + self.shipping_cents
        + self.tax_cents + self.fees_cents
    ):
        raise ValueError("total_cents does not match subtotal, shipping, tax, fees")
        computed = 0
        for item in self.line_items:
            if item.quantity <= 0:
                raise ValueError("line item quantity must be positive")
            if item.unit_price_cents <= 0:
                raise ValueError("line item unit price must be positive")
            if item.warranty_addon_cents < 0:
                raise ValueError("warranty add-on must not be negative")
            computed += (
                item.unit_price_cents + item.warranty_addon_cents
            ) * item.quantity
        if computed != self.subtotal_cents:
            raise ValueError("subtotal_cents does not match line items")
        if self.total_cents != (
            self.subtotal_cents + self.shipping_cents
            + self.tax_cents + self.fees_cents
        ):
            raise ValueError("total_cents does not match subtotal, shipping, tax, fees")
        if self.delivery_days <= 0:
            raise ValueError("delivery_days must be positive")
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_commerce_contracts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/contracts.py tests/unit/test_commerce_contracts.py
git commit -m "feat(commerce): add tax and fees to Offer totals"
```

### Task 0.2: Add the canonical offer binding and hash

**Files:**
- Create: `packages/commerce_core/commerce_core/binding.py`
- Modify: `packages/commerce_core/commerce_core/__init__.py`
- Test: `tests/unit/test_offer_binding.py`

**Interfaces:**
- Consumes: `Offer` from `commerce_core.contracts`.
- Produces: `canonical_offer_binding(offer) -> dict`, `binding_from_award(award) -> dict`, `offer_hash(binding) -> str`. All three buy, sell, and control plane use these.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_offer_binding.py
from datetime import datetime, timedelta, timezone

from commerce_core.binding import (
    binding_from_award,
    canonical_offer_binding,
    offer_hash,
)
from commerce_core.contracts import Currency, Offer, OfferLineItem


def _offer():
    return Offer(
        offer_id="o1", request_id="r1", seller_id="s1",
        seller_name="S", seller_rating=4.5, currency=Currency.USD,
        line_items=[OfferLineItem(
            sku="SKU-1", name="Sensor", quantity=2,
            unit_price_cents=1000, list_unit_price_cents=1200,
            warranty_addon_cents=100,
        )],
        subtotal_cents=2200, shipping_cents=300, tax_cents=150,
        fees_cents=50, total_cents=2700, delivery_days=3,
        warranty_months=12, returns_days=30,
        valid_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_binding_and_hash_are_deterministic():
    offer = _offer()
    binding = canonical_offer_binding(offer)
    assert binding["total_cents"] == 2700
    assert binding["round"] == 1
    h1 = offer_hash(binding)
    h2 = offer_hash(canonical_offer_binding(offer))
    assert h1 == h2
    assert len(h1) == 64


def test_binding_from_award_matches_offer():
    offer = _offer()
    award_binding = binding_from_award({
        "offer_id": "o1", "request_id": "r1", "seller_id": "s1",
        "currency": "USD", "offer_round": 1, "offer_valid_until": offer.valid_until,
        "line_items": [{"sku": "SKU-1", "name": "Sensor", "quantity": 2,
                        "unit_price_cents": 1000, "warranty_addon_cents": 100}],
        "subtotal_cents": 2200, "shipping_cents": 300, "tax_cents": 150,
        "fees_cents": 50, "total_cents": 2700, "delivery_days": 3,
        "warranty_months": 12, "returns_days": 30,
    })
    assert offer_hash(award_binding) == offer_hash(canonical_offer_binding(offer))


def test_mutated_price_changes_hash():
    offer = _offer()
    binding = canonical_offer_binding(offer)
    binding["line_items"][0]["unit_price_cents"] = 1100
    assert offer_hash(binding) != offer_hash(canonical_offer_binding(offer))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_offer_binding.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```python
# packages/commerce_core/commerce_core/binding.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from commerce_core.contracts import Offer
from verifund_contracts.models import canonical_json, sha256_hex


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        from datetime import UTC
        value = value.replace(tzinfo=UTC)
    return value.astimezone(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_offer_binding(offer: Offer) -> dict[str, Any]:
    return {
        "offer_id": offer.offer_id,
        "request_id": offer.request_id,
        "seller_id": offer.seller_id,
        "currency": offer.currency.value if hasattr(offer.currency, "value") else str(offer.currency),
        "round": offer.round,
        "line_items": [
            {
                "sku": item.sku,
                "name": item.name,
                "quantity": item.quantity,
                "unit_price_cents": item.unit_price_cents,
                "warranty_addon_cents": item.warranty_addon_cents,
            }
            for item in offer.line_items
        ],
        "subtotal_cents": offer.subtotal_cents,
        "shipping_cents": offer.shipping_cents,
        "tax_cents": offer.tax_cents,
        "fees_cents": offer.fees_cents,
        "total_cents": offer.total_cents,
        "delivery_days": offer.delivery_days,
        "warranty_months": offer.warranty_months,
        "returns_days": offer.returns_days,
        "offer_valid_until": _iso(offer.valid_until),
    }


def binding_from_award(award: dict[str, Any]) -> dict[str, Any]:
    return {
        "offer_id": award["offer_id"],
        "request_id": award["request_id"],
        "seller_id": award["seller_id"],
        "currency": award["currency"],
        "round": award["offer_round"],
        "line_items": [
            {
                "sku": item["sku"],
                "name": item["name"],
                "quantity": item["quantity"],
                "unit_price_cents": item["unit_price_cents"],
                "warranty_addon_cents": item.get("warranty_addon_cents", 0),
            }
            for item in award["line_items"]
        ],
        "subtotal_cents": award["subtotal_cents"],
        "shipping_cents": award["shipping_cents"],
        "tax_cents": award["tax_cents"],
        "fees_cents": award["fees_cents"],
        "total_cents": award["total_cents"],
        "delivery_days": award["delivery_days"],
        "warranty_months": award["warranty_months"],
        "returns_days": award["returns_days"],
        "offer_valid_until": _iso(award["offer_valid_until"])
        if not isinstance(award["offer_valid_until"], str)
        else award["offer_valid_until"],
    }


def offer_hash(binding: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(binding))
```

Then export from `commerce_core/__init__.py`:
```python
from commerce_core.binding import (
    binding_from_award, canonical_offer_binding, offer_hash,
)
```

Note: `verifund_contracts` must be importable by `commerce_core`. It already is (used elsewhere). If a circular import appears, move `canonical_json`/`sha256_hex` duplication into `binding.py` using `json`/`hashlib` directly. To avoid coupling, implement canonical JSON locally:

```python
import hashlib, json
def _canonical_json(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
def offer_hash(binding): return hashlib.sha256(_canonical_json(binding)).hexdigest()
```

Keep `verifund_contracts` import only where needed; better to avoid import in `commerce_core`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_offer_binding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/binding.py packages/commerce_core/commerce_core/__init__.py tests/unit/test_offer_binding.py
git commit -m "feat(commerce): add canonical offer binding and offer_hash"
```

### Task 0.3: Extend verifund_contracts agreement models

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/models.py`
- Test: `tests/unit/test_verifund_contracts.py`

**Interfaces:**
- Consumes: none.
- Produces: `AgreementState`, `AgreementDecision`, `BuyerApprovalDecision`, `RemedyPolicy`, `RemedyTerms`, `ChangeOperationType`, `ChangeOperation`, `ChangeSet`, `ChangeRequestView`, `ApprovalTokenResponse`, `AgreementVersionView`, `AgreementView`, `AgreementDecisionView`, `AgreementProjection` with `agreement_id`, `status`, `expires_at`, `terms`, `offer_round`, `offer_hash`, `offer_valid_until`, `tax_cents`, `fees_cents`, `inspection_period_hours`, `inspection_starts_on`, `evidence_required`, `remedies`, `dispute_window_hours`, `supersedes_version`, `change_request_id`; `canonical_payload()` returns the §5.5 digest envelope; `AwardRequest` extended; `ApproveRequest.agreement_version`, `FundRequest.agreement_version`.

Ensure `from typing import Any, Literal` is present in `models.py` (the views use `Literal`).

Append to `models.py` (imports `datetime`, `Any` already present):

```python
class AgreementState(StrEnum):
    PENDING_SELLER = "PENDING_SELLER"
    PENDING_BUYER = "PENDING_BUYER"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    AGREED = "AGREED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AgreementDecision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class BuyerApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class RemedyPolicy(StrEnum):
    CANCEL_AND_REFUND = "cancel_and_refund"
    REFUND_OR_REPLACEMENT = "refund_or_replacement"


class RemedyTerms(VerifundModel):
    non_delivery: RemedyPolicy
    late_delivery: RemedyPolicy
    damaged_goods: RemedyPolicy


class ChangeOperationType(StrEnum):
    SET_UNIT_PRICE = "set_unit_price"
    SET_QUANTITY = "set_quantity"
    SET_SHIPPING = "set_shipping"
    SET_TAX = "set_tax"
    SET_FEES = "set_fees"
    SET_DELIVERY_DAYS = "set_delivery_days"
    SET_WARRANTY_MONTHS = "set_warranty_months"
    SET_RETURNS_DAYS = "set_returns_days"
    SET_INSPECTION_PERIOD = "set_inspection_period"
    SET_EVIDENCE_REQUIRED = "set_evidence_required"
    SET_REMEDIES = "set_remedies"


class ChangeOperation(VerifundModel):
    op: ChangeOperationType
    sku: str | None = None
    unit_price_cents: int | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, gt=0)
    shipping_cents: int | None = Field(default=None, ge=0)
    tax_cents: int | None = Field(default=None, ge=0)
    fees_cents: int | None = Field(default=None, ge=0)
    delivery_days: int | None = Field(default=None, ge=1)
    warranty_months: int | None = Field(default=None, ge=0)
    returns_days: int | None = Field(default=None, ge=0)
    inspection_period_hours: int | None = Field(default=None, ge=1)
    evidence_required: list[EvidenceKind] | None = None
    remedies: RemedyTerms | None = None
    dispute_window_hours: int | None = Field(default=None, ge=1)


class ChangeSet(VerifundModel):
    operations: list[ChangeOperation] = Field(min_length=1)
    reason: str = ""


class AgreementDecisionView(VerifundModel):
    decision_id: str
    party: Literal["buyer", "seller"]
    decision: AgreementDecision
    actor_type: str
    actor_id: str
    authority_ref: str | None = None
    agreement_hash: str
    version: int
    note: str = ""
    decided_at: datetime


class ChangeRequestView(VerifundModel):
    change_request_id: str
    base_version: int
    base_hash: str
    requested_by_party: Literal["buyer", "seller"]
    requested_by_actor_type: str
    requested_by_actor_id: str
    operations: list[ChangeOperation]
    reason: str = ""
    status: Literal["PENDING", "ACCEPTED", "REJECTED", "EXPIRED"]
    resolved_by_party: Literal["buyer", "seller"] | None = None
    resolution_note: str = ""
    resulting_version: int | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class AgreementVersionView(VerifundModel):
    version: int
    agreement_hash: str
    created_at: datetime
    supersedes_version: int | None = None
    change_request_id: str | None = None
    superseded_at: datetime | None = None
    decisions: list[AgreementDecisionView] = Field(default_factory=list)
    is_current: bool


class ApprovalTokenResponse(VerifundModel):
    token: str
    review_url: str
    expires_at: datetime
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")


class AgreementView(VerifundModel):
    agreement_id: str
    transaction_id: str
    run_id: str
    buyer_id: str
    seller_id: str
    status: AgreementState
    current_version: int = Field(ge=1)
    expires_at: datetime | None = None
    agreed_at: datetime | None = None
    offer_id: str
    offer_round: int = Field(ge=1)
    offer_hash: str = Field(pattern="^[0-9a-f]{64}$")
    offer_valid_until: datetime
    seller_operator_required: bool = False
    version: AgreementVersionView
    decisions: list[AgreementDecisionView] = Field(default_factory=list)
    change_request: ChangeRequestView | None = None
    review_url: str | None = None


```

Extend `AgreementProjection`:

```python
class AgreementProjection(VerifundModel):
    agreement_id: str = Field(min_length=1)            # NEW
    agreement_version: int = Field(ge=1)
    transaction_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    offer_round: int = Field(ge=1)                     # NEW
    offer_hash: str = Field(pattern="^[0-9a-f]{64}$")  # NEW
    offer_valid_until: datetime                        # NEW
    currency: str = Field(default="USD", pattern="^USD$")
    amount_cents: int = Field(gt=0)
    quantity: int = Field(gt=0)
    line_items: list[AwardLineItem] = Field(min_length=1)
    shipping_cents: int = Field(ge=0)
    tax_cents: int = Field(ge=0)                      # NEW
    fees_cents: int = Field(ge=0)                     # NEW
    delivery_days: int = Field(ge=0)
    warranty_months: int = Field(ge=0)
    returns_days: int = Field(ge=0)
    inspection_period_hours: int = Field(ge=1)          # NEW
    inspection_starts_on: str = Field(min_length=1)     # NEW
    evidence_required: list[EvidenceKind] = Field(min_length=1)  # NEW
    remedies: RemedyTerms                              # NEW
    dispute_window_hours: int = Field(ge=1)             # NEW
    terms: dict[str, Any]                             # NEW
    status: AgreementState                            # NEW
    expires_at: datetime | None = None                 # NEW
    supersedes_version: int | None = None              # NEW
    change_request_id: str | None = None               # NEW
    created_at: str = Field(min_length=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": "verifund.agreement.v1",
            "agreement_id": self.agreement_id,
            "version": self.agreement_version,
            "agreement_type": self.terms.get("agreement_type", "goods"),
            "terms_version": self.terms.get("terms_version", 1),
            "terms": self.terms,
        }

    def recompute_hash(self) -> str:
        from verifund_contracts.models import canonical_json, sha256_hex
        return sha256_hex(canonical_json(self.canonical_payload()))
```

Add a validator that summary fields match `terms`:
```python
@model_validator(mode="after")
def _summary_must_match_terms(self) -> "AgreementProjection":
    terms = self.terms or {}
    totals = terms.get("totals", {})
    if totals.get("total_cents") != self.amount_cents:
        raise ValueError("amount_cents must match terms totals")
    if totals.get("shipping_cents") != self.shipping_cents:
        raise ValueError("shipping_cents must match terms totals")
    if totals.get("tax_cents") != self.tax_cents:
        raise ValueError("tax_cents must match terms totals")
    if totals.get("fees_cents") != self.fees_cents:
        raise ValueError("fees_cents must match terms totals")
    if terms.get("delivery", {}).get("delivery_days") != self.delivery_days:
        raise ValueError("delivery_days must match terms")
    if terms.get("warranty_months") != self.warranty_months:
        raise ValueError("warranty_months must match terms")
    if terms.get("returns_days") != self.returns_days:
        raise ValueError("returns_days must match terms")
    if terms.get("inspection", {}).get("period_hours") != self.inspection_period_hours:
        raise ValueError("inspection_period_hours must match terms")
    if terms.get("inspection", {}).get("starts_on") != self.inspection_starts_on:
        raise ValueError("inspection_starts_on must match terms")
    if terms.get("evidence_required") != self.evidence_required:
        raise ValueError("evidence_required must match terms")
    if terms.get("remedies") != self.remedies.model_dump(mode="json"):
        raise ValueError("remedies must match terms")
    if terms.get("dispute_window_hours") != self.dispute_window_hours:
        raise ValueError("dispute_window_hours must match terms")
    return self
```

Extend `AwardRequest`:
```python
class AwardRequest(VerifundModel):
    run_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)               # NEW
    buyer_display_name: str = Field(min_length=1)       # NEW
    seller_display_name: str = Field(min_length=1)      # NEW
    currency: str = Field(default="USD", pattern="^USD$")
    amount_cents: int = Field(gt=0)
    shipping_cents: int = Field(ge=0)
    tax_cents: int = Field(ge=0)                       # NEW
    fees_cents: int = Field(ge=0)                      # NEW
    quantity: int = Field(gt=0)
    line_items: list[AwardLineItem] = Field(min_length=1)
    delivery_days: int = Field(ge=1)                    # NEW (was ge=0)
    warranty_months: int = Field(ge=0)
    returns_days: int = Field(ge=0)
    offer_round: int = Field(ge=1)                     # NEW
    offer_hash: str = Field(pattern="^[0-9a-f]{64}$")  # NEW
    offer_valid_until: datetime                        # NEW
    inspection_period_hours: int = Field(default=48, ge=1)  # NEW
    inspection_starts_on: str = Field(default="DELIVERY_CONFIRMED", min_length=1)  # NEW
    evidence_required: list[EvidenceKind] = Field(      # NEW
        default_factory=lambda: [EvidenceKind.SHIPMENT_MANIFEST,
                                 EvidenceKind.DELIVERY_CONFIRMATION,
                                 EvidenceKind.INVOICE],
        min_length=1,
    )
    remedies: RemedyTerms                              # NEW
    dispute_window_hours: int = Field(default=72, ge=1)  # NEW
```

Update `_totals_must_match`:
```python
@model_validator(mode="after")
def _totals_must_match(self) -> "AwardRequest":
    line_quantity = sum(item.quantity for item in self.line_items)
    if line_quantity != self.quantity:
        raise ValueError("quantity must equal the sum of line-item quantities")
    line_total = sum(
        (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
        for item in self.line_items
    )
    if line_total + self.shipping_cents + self.tax_cents + self.fees_cents != self.amount_cents:
        raise ValueError("amount_cents must equal line items plus shipping, tax, fees")
    if EvidenceKind.DELIVERY_CONFIRMATION not in self.evidence_required:
        raise ValueError("evidence_required must include delivery_confirmation")
    return self
```

Extend `ApproveRequest`:
```python
class ApproveRequest(VerifundModel):
    approval_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    note: str = ""
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    agreement_version: int = Field(ge=1)   # NEW
```

Extend `FundRequest`:
```python
class FundRequest(VerifundModel):
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    agreement_version: int = Field(ge=1)   # NEW
    return_url: str
    cancel_url: str
```

Extend `AgreementReviewDecision` in `models.py` (already defined earlier):
```python
class AgreementReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    OPERATOR_REQUIRED = "operator_required"   # NEW
    CHANGES_REQUESTED = "changes_requested"   # NEW
```

- [ ] **Step 2: Extend `BuyerAgreementReviewRequest` to carry extended seller result fields (non-binding precheck).** Add optional `recommendation: str | None = None`, `rationale: str = ""`.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -v`
Expected: PASS (update fixtures if needed; keep `agreement_hash` field name).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(contracts): add agreement state, versioning, and binding fields"
```

### Task 0.4: Extend A2A envelopes and checkpoints to `/v2`

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/a2a.py`
- Test: `tests/unit/test_verifund_a2a_contracts.py`

**Interfaces:**
- Consumes: `AgreementProjection`, `AgreementReviewDecision`, `AgreementState`.
- Produces: `BUYER_APPROVAL_REQUIRED`, `SELLER_OPERATOR_REQUIRED`, `AGREEMENT_CHANGES_REQUESTED` checkpoints; `BuyerAgreementApprovalDecision`; extended `AgreementReviewRequest.change_request`; extended `AgreementReviewResult` with `offer_hash`, `actor_type`, `actor_id`, `authority_ref`, `authority_snapshot`, `verified_change_request_id`; `VERIFUND_SCHEMA_BASE` ending in `v2`.

- [ ] **Step 1: Apply the changes.**

```python
VERIFUND_SCHEMA_BASE = "https://marketmesh.example/extensions/verifund/v2/schemas"
```

```python
class VerifundCheckpoint(StrEnum):
    BUYER_REVIEW_REQUIRED = "buyer_review_required"
    SELLER_REVIEW_REQUIRED = "seller_review_required"
    BUYER_APPROVAL_REQUIRED = "buyer_approval_required"          # NEW
    SELLER_OPERATOR_REQUIRED = "seller_operator_required"        # NEW
    AGREEMENT_CHANGES_REQUESTED = "agreement_changes_requested"  # NEW
    FUNDING_APPROVAL_REQUIRED = "funding_approval_required"
    FUNDING_PENDING = "funding_pending"
    PURCHASE_ORDER_REQUIRED = "purchase_order_required"
    EVIDENCE_PENDING = "evidence_pending"
    RELEASE_APPROVAL_REQUIRED = "release_approval_required"
```

```python
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
    change_request: ChangeSet | None = None   # NEW (for N+1)
```

```python
class AgreementReviewResult(VerifundModel):
    party: Literal["buyer", "seller"]
    status: AgreementReviewDecision
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    offer_hash: str = Field(pattern="^[0-9a-f]{64}$")  # NEW
    actor_type: str = Field(min_length=1)               # NEW
    actor_id: str = Field(min_length=1)                # NEW
    authority_ref: str | None = None                    # NEW
    authority_snapshot: dict[str, Any] = Field(default_factory=dict)  # NEW
    verified_change_request_id: str | None = None       # NEW
    task_id: str = Field(min_length=1)
    context_id: str = Field(min_length=1)
    reviewed_at: datetime
    reason_code: str | None = None
    note: str = ""
```

```python
class BuyerAgreementApprovalDecision(VerifundModel):
    agreement_version: int = Field(ge=1)
    agreement_hash: str = Field(pattern="^[0-9a-f]{64}$")
    decision: BuyerApprovalDecision
    note: str = ""
    change_set: ChangeSet | None = None
    idempotency_key: str = Field(min_length=1)
```

- [ ] **Step 2: Update `_wrap`/`_unwrap` schema version to `"2.0"`?** The envelope `schema_version` field stays `"1.0"` (internal envelope version); only `VERIFUND_SCHEMA_BASE` path changes. Keep `"1.0"`.

- [ ] **Step 3: Run tests and commit.**

Run: `uv run pytest tests/unit/test_verifund_a2a_contracts.py tests/unit/test_verifund_contracts.py -v`
Expected: PASS

Commit: `git commit -m "feat(contracts): bump A2A envelopes to v2 and add agreement checkpoints"`

---

## Phase 1 — Control-plane agreement module

### Task 1.1: Agreement aggregates and state machine

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/agreements/__init__.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/agreements/models.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/agreements/states.py`
- Test: `tests/unit/test_agreement_states.py`

**Interfaces:**
- Consumes: `AgreementState`, `AgreementDecision` from `verifund_contracts.models`.
- Produces: `Agreement`, `AgreementVersion`, `AgreementDecisionRecord`, `ChangeRequest`, `ApprovalTokenRecord`, `AgreementEvent`, `ActorContext`, `AgreementError`, `ALLOWED_TRANSITIONS`, `assert_agreement_transition`, `is_terminal`, `next_state`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agreement_states.py
from verifund_control_plane.agreements.states import (
    is_terminal, next_state,
)
from verifund_contracts.models import AgreementState


def test_allowed_transitions():
    assert next_state(AgreementState.PENDING_SELLER, "SELLER_ACCEPT") == AgreementState.PENDING_BUYER
    assert next_state(AgreementState.PENDING_BUYER, "BUYER_ACCEPT") == AgreementState.AGREED
    assert next_state(AgreementState.PENDING_SELLER, "SELLER_REJECT") == AgreementState.REJECTED


def test_terminal_rejects_all():
    for st in (AgreementState.REJECTED, AgreementState.EXPIRED, AgreementState.TERMINATED):
        assert is_terminal(st) is True
        try:
            next_state(st, "SELLER_ACCEPT")
            raised = False
        except ValueError:
            raised = True
        assert raised


def test_changes_reject_returns_requester_pending():
    assert next_state(
        AgreementState.CHANGES_REQUESTED, "CHANGES_REJECT", requester="seller",
    ) == AgreementState.PENDING_SELLER
    assert next_state(
        AgreementState.CHANGES_REQUESTED, "CHANGES_REJECT", requester="buyer",
    ) == AgreementState.PENDING_BUYER
```

- [ ] **Step 2: Implement `models.py`**

```python
# apps/verifund_control_plane/verifund_control_plane/agreements/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from verifund_contracts.models import AgreementState, AgreementDecision, ChangeOperation


@dataclass
class ActorContext:
    actor_id: str
    actor_type: str
    display_name: str = ""


@dataclass
class AgreementVersion:
    agreement_id: str
    version: int
    terms: dict[str, Any]
    agreement_hash: str
    rendered_html: str
    renderer_version: str
    created_at: datetime
    supersedes_version: int | None = None
    change_request_id: str | None = None
    superseded_at: datetime | None = None


@dataclass
class Agreement:
    agreement_id: str
    transaction_id: str
    run_id: str
    buyer_id: str
    seller_id: str
    current_version: int
    status: AgreementState
    offer_id: str
    offer_round: int
    offer_hash: str
    offer_valid_until: datetime
    expires_at: datetime | None
    agreed_at: datetime | None
    rejected_at: datetime | None
    expired_at: datetime | None
    terminated_at: datetime | None
    terminal_reason: str | None
    seller_operator_required: bool
    row_version: int
    created_at: datetime
    updated_at: datetime
    current_version_record: AgreementVersion | None = None


@dataclass
class AgreementDecisionRecord:
    decision_id: str
    agreement_id: str
    version: int
    party: str
    decision: AgreementDecision
    actor_type: str
    actor_id: str
    authority_ref: str | None
    authority_snapshot: dict[str, Any]
    agreement_hash: str
    verified_offer_hash: str | None
    verified_change_request_id: str | None
    reason_code: str | None
    note: str
    change_request_id: str | None
    idempotency_key: str
    decided_at: datetime


@dataclass
class ChangeRequest:
    change_request_id: str
    agreement_id: str
    base_version: int
    base_hash: str
    requested_by_party: str
    requested_by_actor_type: str
    requested_by_actor_id: str
    operations: list[ChangeOperation]
    reason: str
    status: str
    resolved_by_party: str | None = None
    resolved_by_actor_type: str | None = None
    resolved_by_actor_id: str | None = None
    resolution_note: str = ""
    resulting_version: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(__import__("datetime").timezone.utc))
    resolved_at: datetime | None = None


@dataclass
class ApprovalTokenRecord:
    jti: str
    agreement_id: str
    version: int
    agreement_hash: str
    subject_id: str
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    issued_by_actor_type: str = ""
    issued_by_actor_id: str = ""
    consumed_by_decision_id: str | None = None


@dataclass
class AgreementEvent:
    event_id: int | None
    agreement_id: str
    version: int | None
    event_type: str
    payload: dict[str, Any]
    actor_type: str
    actor_id: str
    created_at: datetime


class AgreementError(Exception):
    def __init__(self, code: str, message: str, *, agreement_id: str | None = None,
                 version: int | None = None, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.agreement_id = agreement_id
        self.version = version
        self.field = field
```

- [ ] **Step 3: Implement `states.py`**

```python
# apps/verifund_control_plane/verifund_control_plane/agreements/states.py
from __future__ import annotations

from verifund_contracts.models import AgreementState


TERMINAL_STATES = {
    AgreementState.REJECTED, AgreementState.EXPIRED, AgreementState.TERMINATED,
}


def is_terminal(state: AgreementState) -> bool:
    return state in TERMINAL_STATES


def next_state(state: AgreementState, event: str, *, requester: str | None = None) -> AgreementState:
    if is_terminal(state):
        raise ValueError(f"no transitions from terminal state {state}")
    table = {
        (AgreementState.PENDING_SELLER, "SELLER_ACCEPT"): AgreementState.PENDING_BUYER,
        (AgreementState.PENDING_SELLER, "SELLER_REJECT"): AgreementState.REJECTED,
        (AgreementState.PENDING_SELLER, "SELLER_OPERATOR_REQUIRED"): AgreementState.PENDING_SELLER,
        (AgreementState.PENDING_SELLER, "SELLER_REQUEST_CHANGES"): AgreementState.CHANGES_REQUESTED,
        (AgreementState.PENDING_BUYER, "BUYER_ACCEPT"): AgreementState.AGREED,
        (AgreementState.PENDING_BUYER, "BUYER_REJECT"): AgreementState.REJECTED,
        (AgreementState.PENDING_BUYER, "BUYER_REQUEST_CHANGES"): AgreementState.CHANGES_REQUESTED,
        (AgreementState.CHANGES_REQUESTED, "CHANGES_ACCEPT"): AgreementState.PENDING_SELLER,
        (AgreementState.CHANGES_REQUESTED, "EXPIRE"): AgreementState.EXPIRED,
    }
    if (state, event) == (AgreementState.CHANGES_REQUESTED, "CHANGES_REJECT"):
        if requester == "seller":
            return AgreementState.PENDING_SELLER
        if requester == "buyer":
            return AgreementState.PENDING_BUYER
        raise ValueError("requester is required for changes_reject")
    if (state, event) == (AgreementState.AGREED, "TERMINATE"):
        return AgreementState.TERMINATED
    if (state, event) not in table:
        raise ValueError(f"invalid transition {state} --{event}--> ?")
    return table[(state, event)]


def assert_transition(state: AgreementState, event: str, *, requester: str | None = None) -> AgreementState:
    return next_state(state, event, requester=requester)
```

Lazy expiry is handled separately in `expiry.py`; `next_state(..., "EXPIRE")` only valid from non-terminal states.

- [ ] **Step 4: Run tests and commit.**

Run: `uv run pytest tests/unit/test_agreement_states.py -v`
Expected: PASS

Commit: `git commit -m "feat(agreements): add domain models and state machine"`

### Task 1.2: Deterministic digest and goods-v1 generator

**Files:**
- Create: `.../agreements/digest.py`
- Create: `.../agreements/generator.py`
- Test: `tests/unit/test_agreement_digest.py`, `tests/unit/test_agreement_generator.py`

**Interfaces:**
- Consumes: `AwardRequest`, `EvidenceKind`, `RemedyTerms` from `verifund_contracts.models`; `canonical_offer_binding`, `offer_hash` from `commerce_core.binding`.
- Produces: `canonical_json`, `sha256_hex`, `agreement_hash(agreement_id, version, terms)`, `build_terms(award, now)`, `validate_award(award, now)`, `validate_terms(terms, award)`, `apply_change_set(base_terms, change_set)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_agreement_digest.py
import json
from datetime import datetime, timezone

from verifund_control_plane.agreements.digest import (
    agreement_hash, canonical_json, sha256_hex,
)


def test_canonical_json_sorted_compact():
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_agreement_hash_binds_version():
    terms = {"schema": "verifund.agreement.v1", "agreement_type": "goods",
             "terms_version": 1, "totals": {"total_cents": 100}}
    h1 = agreement_hash("agr_1", 1, terms)
    h2 = agreement_hash("agr_1", 2, terms)
    assert h1 != h2
    assert len(h1) == 64


def test_tamper_detection():
    terms = {"schema": "verifund.agreement.v1", "agreement_type": "goods",
             "terms_version": 1, "totals": {"total_cents": 100}}
    h = agreement_hash("agr_1", 1, terms)
    terms["totals"]["total_cents"] = 200
    assert agreement_hash("agr_1", 1, terms) != h
```

```python
# tests/unit/test_agreement_generator.py
from datetime import datetime, timedelta, timezone

from verifund_contracts.models import (
    AwardLineItem, AwardRequest, EvidenceKind, RemedyTerms, RemedyPolicy,
)
from verifund_control_plane.agreements.generator import (
    apply_change_set, build_terms, validate_award, validate_terms,
)


def _award():
    return AwardRequest(
        run_id="run-1", buyer_id="buyer-1", seller_id="seller-1",
        offer_id="offer-1", request_id="rfq-1",
        buyer_display_name="Buyer", seller_display_name="Seller",
        currency="USD", amount_cents=51600, shipping_cents=2500,
        tax_cents=3600, fees_cents=500, quantity=10,
        line_items=[AwardLineItem(sku="SKU-1", name="Sensor", quantity=10,
                                 unit_price_cents=4200, warranty_addon_cents=300)],
        delivery_days=5, warranty_months=12, returns_days=30,
        offer_round=2, offer_hash="a" * 64,
        offer_valid_until=datetime.now(timezone.utc) + timedelta(hours=1),
        remedies=RemedyTerms(
            non_delivery=RemedyPolicy.CANCEL_AND_REFUND,
            late_delivery=RemedyPolicy.CANCEL_AND_REFUND,
            damaged_goods=RemedyPolicy.REFUND_OR_REPLACEMENT,
        ),
    )


def test_build_terms_totals():
    award = _award()
    terms = build_terms(award, datetime.now(timezone.utc))
    assert terms["totals"]["total_cents"] == 51600
    assert terms["totals"]["subtotal_cents"] == 45000
    assert terms["items"][0]["line_total_cents"] == 45000


def test_validate_terms_rejects_bad_arithmetic():
    import pytest
    award = _award()
    terms = build_terms(award, datetime.now(timezone.utc))
    terms["totals"]["total_cents"] = 1
    with pytest.raises(ValueError):
        validate_terms(terms, award)


def test_apply_change_set_recomputes():
    from verifund_contracts.models import ChangeOperation, ChangeOperationType, ChangeSet
    award = _award()
    terms = build_terms(award, datetime.now(timezone.utc))
    cs = ChangeSet(operations=[ChangeOperation(
        op=ChangeOperationType.SET_SHIPPING, shipping_cents=1000,
    )])
    new = apply_change_set(terms, cs)
    assert new["totals"]["shipping_cents"] == 1000
    assert new["totals"]["total_cents"] == 51600 - 2500 + 1000
```

- [ ] **Step 2: Implement `digest.py`**

```python
# apps/verifund_control_plane/verifund_control_plane/agreements/digest.py
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def agreement_hash(agreement_id: str, version: int, terms: dict[str, Any]) -> str:
    payload = {
        "schema": "verifund.agreement.v1",
        "agreement_id": agreement_id,
        "version": version,
        "agreement_type": terms.get("agreement_type", "goods"),
        "terms_version": terms.get("terms_version", 1),
        "terms": terms,
    }
    return sha256_hex(canonical_json(payload))
```

- [ ] **Step 3: Implement `generator.py`**

```python
# apps/verifund_control_plane/verifund_control_plane/agreements/generator.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from verifund_contracts.models import (
    AwardRequest, EvidenceKind, RemedyTerms,
)

from .digest import agreement_hash


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_award(award: AwardRequest, now: datetime) -> None:
    if now > award.offer_valid_until:
        raise ValueError("offer_expired")
    from commerce_core.binding import binding_from_award, canonical_offer_binding, offer_hash
    # buyer/seller/control-plane binding parity is checked by callers; here only shape
    if award.currency != "USD":
        raise ValueError("invalid_terms")
    if award.delivery_days < 1:
        raise ValueError("invalid_terms")
    if EvidenceKind.DELIVERY_CONFIRMATION not in award.evidence_required:
        raise ValueError("invalid_terms")


def build_terms(award: AwardRequest, now: datetime) -> dict[str, Any]:
    items = []
    subtotal = 0
    for li in award.line_items:
        line_total = (li.unit_price_cents + li.warranty_addon_cents) * li.quantity
        subtotal += line_total
        items.append({
            "sku": li.sku,
            "name": li.name,
            "quantity": li.quantity,
            "unit_price_cents": li.unit_price_cents,
            "warranty_addon_cents": li.warranty_addon_cents,
            "line_total_cents": line_total,
        })
    if subtotal != award.amount_cents - award.shipping_cents - award.tax_cents - award.fees_cents:
        raise ValueError("invalid_terms")
    if subtotal != sum(
        (li.unit_price_cents + li.warranty_addon_cents) * li.quantity
        for li in award.line_items
    ):
        raise ValueError("invalid_terms")
    return {
        "schema": "verifund.agreement.v1",
        "agreement_type": "goods",
        "terms_version": 1,
        "platform_terms_version": "v1",
        "parties": {
            "buyer": {"id": award.buyer_id, "display_name": award.buyer_display_name},
            "seller": {"id": award.seller_id, "display_name": award.seller_display_name},
        },
        "offer": {
            "offer_id": award.offer_id,
            "request_id": award.request_id,
            "offer_round": award.offer_round,
            "offer_hash": award.offer_hash,
            "offer_valid_until": _iso(award.offer_valid_until),
        },
        "items": items,
        "totals": {
            "currency": award.currency,
            "subtotal_cents": subtotal,
            "shipping_cents": award.shipping_cents,
            "tax_cents": award.tax_cents,
            "fees_cents": award.fees_cents,
            "total_cents": award.amount_cents,
        },
        "delivery": {"delivery_days": award.delivery_days, "starts_on": "FUNDING_CONFIRMED"},
        "warranty_months": award.warranty_months,
        "returns_days": award.returns_days,
        "inspection": {
            "period_hours": award.inspection_period_hours,
            "starts_on": award.inspection_starts_on,
        },
        "evidence_required": [e.value for e in award.evidence_required],
        "remedies": award.remedies.model_dump(mode="json"),
        "dispute_window_hours": award.dispute_window_hours,
    }


def validate_terms(terms: dict[str, Any], award: AwardRequest) -> None:
    if terms.get("schema") != "verifund.agreement.v1":
        raise ValueError("invalid_terms")
    if terms.get("agreement_type") != "goods":
        raise ValueError("invalid_terms")
    if terms.get("terms_version") != 1:
        raise ValueError("invalid_terms")
    parties = terms.get("parties", {})
    if parties.get("buyer", {}).get("id") != award.buyer_id:
        raise ValueError("invalid_terms")
    if parties.get("seller", {}).get("id") != award.seller_id:
        raise ValueError("invalid_terms")
    offer = terms.get("offer", {})
    if offer.get("offer_id") != award.offer_id:
        raise ValueError("invalid_terms")
    if offer.get("offer_round") != award.offer_round:
        raise ValueError("offer_mismatch")
    if offer.get("offer_hash") != award.offer_hash:
        raise ValueError("offer_mismatch")
    totals = terms.get("totals", {})
    if totals.get("currency") != "USD":
        raise ValueError("invalid_terms")
    items = terms.get("items", [])
    if not items:
        raise ValueError("invalid_terms")
    skus = [i.get("sku") for i in items]
    if len(set(skus)) != len(skus):
        raise ValueError("invalid_terms")
    subtotal = sum(
        (i.get("unit_price_cents", 0) + i.get("warranty_addon_cents", 0)) * i.get("quantity", 0)
        for i in items
    )
    if subtotal != totals.get("subtotal_cents"):
        raise ValueError("invalid_terms")
    if totals.get("total_cents") != (
        totals.get("subtotal_cents", 0) + totals.get("shipping_cents", 0)
        + totals.get("tax_cents", 0) + totals.get("fees_cents", 0)
    ):
        raise ValueError("invalid_terms")
    if any(i.get("quantity", 0) <= 0 for i in items):
        raise ValueError("invalid_terms")
    if any(i.get("unit_price_cents", 0) < 0 for i in items):
        raise ValueError("invalid_terms")
    delivery = terms.get("delivery", {})
    if delivery.get("delivery_days", 0) < 1:
        raise ValueError("invalid_terms")
    inspection = terms.get("inspection", {})
    if inspection.get("period_hours", 0) < 1:
        raise ValueError("invalid_terms")
    evidence = terms.get("evidence_required", [])
    if not evidence or "delivery_confirmation" not in evidence:
        raise ValueError("invalid_terms")
    if terms.get("dispute_window_hours", 0) < 1:
        raise ValueError("invalid_terms")
    remedies = terms.get("remedies", {})
    if not all(k in remedies for k in ("non_delivery", "late_delivery", "damaged_goods")):
        raise ValueError("invalid_terms")
    if terms.get("totals", {}).get("total_cents", 0) != award.amount_cents:
        raise ValueError("invalid_terms")


def apply_change_set(base_terms: dict[str, Any], change_set) -> dict[str, Any]:
    import copy
    terms = copy.deepcopy(base_terms)
    items_by_sku = {i["sku"]: i for i in terms["items"]}
    for op in change_set.operations:
        kind = op.op.value if hasattr(op.op, "value") else str(op.op)
        if kind == "set_unit_price":
            if op.sku not in items_by_sku:
                raise ValueError("invalid_change_set")
            items_by_sku[op.sku]["unit_price_cents"] = op.unit_price_cents
            items_by_sku[op.sku]["line_total_cents"] = (
                items_by_sku[op.sku]["unit_price_cents"]
                + items_by_sku[op.sku]["warranty_addon_cents"]
            ) * items_by_sku[op.sku]["quantity"]
        elif kind == "set_quantity":
            if op.sku not in items_by_sku:
                raise ValueError("invalid_change_set")
            if op.quantity is None or op.quantity <= 0:
                raise ValueError("invalid_change_set")
            items_by_sku[op.sku]["quantity"] = op.quantity
            items_by_sku[op.sku]["line_total_cents"] = (
                items_by_sku[op.sku]["unit_price_cents"]
                + items_by_sku[op.sku]["warranty_addon_cents"]
            ) * items_by_sku[op.sku]["quantity"]
        elif kind == "set_shipping":
            terms["totals"]["shipping_cents"] = op.shipping_cents
        elif kind == "set_tax":
            terms["totals"]["tax_cents"] = op.tax_cents
        elif kind == "set_fees":
            terms["totals"]["fees_cents"] = op.fees_cents
        elif kind == "set_delivery_days":
            terms["delivery"]["delivery_days"] = op.delivery_days
        elif kind == "set_warranty_months":
            terms["warranty_months"] = op.warranty_months
        elif kind == "set_returns_days":
            terms["returns_days"] = op.returns_days
        elif kind == "set_inspection_period":
            terms["inspection"]["period_hours"] = op.inspection_period_hours
        elif kind == "set_evidence_required":
            terms["evidence_required"] = [e.value if hasattr(e, "value") else str(e) for e in op.evidence_required]
        elif kind == "set_remedies":
            terms["remedies"] = op.remedies.model_dump(mode="json") if op.remedies else terms["remedies"]
            if op.dispute_window_hours is not None:
                terms["dispute_window_hours"] = op.dispute_window_hours
        else:
            raise ValueError("invalid_change_set")
        # recompute subtotal/total
        terms["totals"]["subtotal_cents"] = sum(i["line_total_cents"] for i in terms["items"])
        terms["totals"]["total_cents"] = (
            terms["totals"]["subtotal_cents"] + terms["totals"]["shipping_cents"]
            + terms["totals"]["tax_cents"] + terms["totals"]["fees_cents"]
        )
    return terms
```

- [ ] **Step 4: Run tests and commit.**

Run: `uv run pytest tests/unit/test_agreement_digest.py tests/unit/test_agreement_generator.py -v`
Expected: PASS

Commit: `git commit -m "feat(agreements): add deterministic generator, digest, and change sets"`

### Task 1.3: Deterministic HTML renderer

**Files:**
- Create: `.../agreements/renderer.py`
- Create: `.../agreements/templates/goods_agreement.html`
- Test: `tests/unit/test_agreement_renderer.py`

**Interfaces:**
- Consumes: terms dict, agreement_id, version, agreement_hash.
- Produces: `RENDERER_VERSION = "v1"`, `render_agreement(terms, agreement_id, version, agreement_hash) -> str`.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_agreement_renderer.py
from verifund_control_plane.agreements.renderer import (
    RENDERER_VERSION, render_agreement,
)


def test_renderer_deterministic():
    terms = {"schema": "verifund.agreement.v1", "agreement_type": "goods",
             "terms_version": 1, "platform_terms_version": "v1",
             "parties": {"buyer": {"id": "b", "display_name": "Buyer"},
                         "seller": {"id": "s", "display_name": "Seller"}},
             "offer": {"offer_id": "o1", "request_id": "r1", "offer_round": 1,
                       "offer_hash": "a" * 64, "offer_valid_until": "2026-11-01T00:00:00Z"},
             "items": [{"sku": "S", "name": "N", "quantity": 1,
                        "unit_price_cents": 100, "warranty_addon_cents": 0,
                        "line_total_cents": 100}],
             "totals": {"currency": "USD", "subtotal_cents": 100,
                        "shipping_cents": 0, "tax_cents": 0, "fees_cents": 0,
                        "total_cents": 100},
             "delivery": {"delivery_days": 3, "starts_on": "FUNDING_CONFIRMED"},
             "warranty_months": 12, "returns_days": 30,
             "inspection": {"period_hours": 48, "starts_on": "DELIVERY_CONFIRMED"},
             "evidence_required": ["delivery_confirmation"],
             "remedies": {"non_delivery": "cancel_and_refund",
                          "late_delivery": "cancel_and_refund",
                          "damaged_goods": "refund_or_replacement"},
             "dispute_window_hours": 72}
    out1 = render_agreement(terms, "agr_1", 1, "b" * 64)
    out2 = render_agreement(terms, "agr_1", 1, "b" * 64)
    assert out1 == out2
    assert "<table" in out1
    assert "agr_1" in out1 and "b" * 8 in out1
    assert "<script" not in out1


def test_renderer_escapes():
    terms = {"schema": "verifund.agreement.v1", "agreement_type": "goods",
             "terms_version": 1, "platform_terms_version": "v1",
             "parties": {"buyer": {"id": "b", "display_name": "<x>"},
                         "seller": {"id": "s", "display_name": "Seller"}},
             "offer": {"offer_id": "o1", "request_id": "r1", "offer_round": 1,
                       "offer_hash": "a" * 64, "offer_valid_until": "2026-11-01T00:00:00Z"},
             "items": [{"sku": "S", "name": "<y>", "quantity": 1,
                        "unit_price_cents": 100, "warranty_addon_cents": 0,
                        "line_total_cents": 100}],
             "totals": {"currency": "USD", "subtotal_cents": 100,
                        "shipping_cents": 0, "tax_cents": 0, "fees_cents": 0,
                        "total_cents": 100},
             "delivery": {"delivery_days": 3, "starts_on": "FUNDING_CONFIRMED"},
             "warranty_months": 12, "returns_days": 30,
             "inspection": {"period_hours": 48, "starts_on": "DELIVERY_CONFIRMED"},
             "evidence_required": ["delivery_confirmation"],
             "remedies": {"non_delivery": "cancel_and_refund",
                          "late_delivery": "cancel_and_refund",
                          "damaged_goods": "refund_or_replacement"},
             "dispute_window_hours": 72}
    out = render_agreement(terms, "agr_1", 1, "b" * 64)
    assert "<x>" not in out and "&lt;x&gt;" in out
    assert "<y>" not in out
```

- [ ] **Step 2: Implement renderer**

```python
# apps/verifund_control_plane/verifund_control_plane/agreements/renderer.py
from __future__ import annotations

import html
from typing import Any

RENDERER_VERSION = "v1"


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def render_agreement(terms: dict[str, Any], agreement_id: str, version: int,
                     agreement_hash: str) -> str:
    buyer = terms["parties"]["buyer"]
    seller = terms["parties"]["seller"]
    rows = []
    for item in terms["items"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['sku'])}</td>"
            f"<td>{html.escape(item['name'])}</td>"
            f"<td>{item['quantity']}</td>"
            f"<td>{_money(item['unit_price_cents'])}</td>"
            f"<td>{_money(item['warranty_addon_cents'])}</td>"
            f"<td>{_money(item['line_total_cents'])}</td>"
            "</tr>"
        )
    totals = terms["totals"]
    evidence = ", ".join(html.escape(e) for e in terms["evidence_required"])
    remedies = terms["remedies"]
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Agreement {html.escape(agreement_id)}</title></head>
<body>
<h1>Verifund Goods Agreement</h1>
<p>Agreement ID: {html.escape(agreement_id)} | Version: {version} | Digest: {html.escape(agreement_hash[:16])}</p>
<h2>Parties</h2>
<p>Buyer: {html.escape(buyer['display_name'])} ({html.escape(buyer['id'])})</p>
<p>Seller: {html.escape(seller['display_name'])} ({html.escape(seller['id'])})</p>
<h2>Items</h2>
<table border="1" cellpadding="4">
<tr><th>SKU</th><th>Name</th><th>Qty</th><th>Unit</th><th>Warranty</th><th>Line total</th></tr>
{''.join(rows)}
</table>
<h2>Totals ({html.escape(totals['currency'])})</h2>
<p>Subtotal: {_money(totals['subtotal_cents'])}</p>
<p>Shipping: {_money(totals['shipping_cents'])}</p>
<p>Tax: {_money(totals['tax_cents'])}</p>
<p>Fees: {_money(totals['fees_cents'])}</p>
<p><strong>Total: {_money(totals['total_cents'])}</strong></p>
<h2>Terms</h2>
<p>Delivery: {terms['delivery']['delivery_days']} days (starts {terms['delivery']['starts_on']})</p>
<p>Warranty: {terms['warranty_months']} months</p>
<p>Returns: {terms['returns_days']} days</p>
<p>Inspection: {terms['inspection']['period_hours']} hours (starts {terms['inspection']['starts_on']})</p>
<p>Evidence required: {evidence}</p>
<p>Remedies: non-delivery={remedies['non_delivery']}, late={remedies['late_delivery']}, damaged={remedies['damaged_goods']}</p>
<p>Dispute window: {terms['dispute_window_hours']} hours</p>
<footer>
<p>Renderer: {RENDERER_VERSION} | Platform terms: {html.escape(terms.get('platform_terms_version','v1'))}</p>
<p>Digest: {html.escape(agreement_hash)}</p>
</footer>
</body>
</html>"""
    return doc
```

- [ ] **Step 4: Run tests and commit.**

Run: `uv run pytest tests/unit/test_agreement_renderer.py -v`
Expected: PASS

Commit: `git commit -m "feat(agreements): add deterministic HTML renderer"`

---

### Task 1.4: Agreement repository and schema

**Files:**
- Create: `.../agreements/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py` (add `buyer_precheck` column rename and `agreement_id` FK; replace old `agreements`/`agreement_reviews` tables with the normalized ones via the new module)
- Test: `tests/unit/test_agreement_repository.py`

**Interfaces:**
- Consumes: `Agreement`, `AgreementVersion`, `AgreementDecisionRecord`, `ChangeRequest`, `ApprovalTokenRecord`, `AgreementEvent` from `.models`.
- Produces: `AgreementRepository` with `create_schema(conn)`, `create(conn, agreement, version)`, `get`, `get_by_transaction`, `get_version`, `list_versions`, `append_decision`, `update_status_cas`, `create_change_request`, `get_open_change_request`, `resolve_change_request`, `issue_token`, `consume_token`, `revoke_tokens`, `append_event`, `list_events`, `list_expired`, `expire`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_agreement_repository.py
import pytest
from datetime import datetime, timedelta, timezone

from verifund_control_plane.agreements.models import (
    ActorContext, Agreement, AgreementVersion, AgreementEvent,
)
from verifund_control_plane.agreements.repository import AgreementRepository
from verifund_control_plane.db import configure_sqlite, create_engine


@pytest.fixture
async def repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await configure_sqlite(engine)
    r = AgreementRepository(engine)
    async with engine.begin() as conn:
        await r.create_schema(conn)
    yield r
    await engine.dispose()


async def test_create_and_get(repo):
    now = datetime.now(timezone.utc)
    agr = Agreement(
        agreement_id="agr_1", transaction_id="txn_1", run_id="run_1",
        buyer_id="b", seller_id="s", current_version=1,
        status=__import__("verifund_contracts.models", fromlist=["AgreementState"]).AgreementState.PENDING_SELLER,
        offer_id="o1", offer_round=1, offer_hash="a" * 64,
        offer_valid_until=now, expires_at=now, agreed_at=None,
        rejected_at=None, expired_at=None, terminated_at=None,
        terminal_reason=None, seller_operator_required=False,
        row_version=1, created_at=now, updated_at=now,
    )
    ver = AgreementVersion(
        agreement_id="agr_1", version=1, terms={"x": 1}, agreement_hash="b" * 64,
        rendered_html="<html/>", renderer_version="v1", created_at=now,
    )
    async with repo.transaction() as conn:
        await repo.create(conn, agr, ver)
        await repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id="agr_1", version=1,
            event_type="agreement.created", payload={}, actor_type="system",
            actor_id="cp", created_at=now,
        ))
    got = await repo.get("agr_1")
    assert got is not None and got.agreement_id == "agr_1"
    vers = await repo.list_versions("agr_1")
    assert len(vers) == 1
    events = await repo.list_events("agr_1")
    assert len(events) == 1


async def test_cas_status(repo):
    now = datetime.now(timezone.utc)
    from verifund_contracts.models import AgreementState
    agr = Agreement(
        agreement_id="agr_2", transaction_id="txn_2", run_id="run_2",
        buyer_id="b", seller_id="s", current_version=1,
        status=AgreementState.PENDING_SELLER, offer_id="o1", offer_round=1,
        offer_hash="a" * 64, offer_valid_until=now, expires_at=now,
        agreed_at=None, rejected_at=None, expired_at=None, terminated_at=None,
        terminal_reason=None, seller_operator_required=False, row_version=1,
        created_at=now, updated_at=now,
    )
    ver = AgreementVersion(
        agreement_id="agr_2", version=1, terms={}, agreement_hash="b" * 64,
        rendered_html="<html/>", renderer_version="v1", created_at=now,
    )
    async with repo.transaction() as conn:
        await repo.create(conn, agr, ver)
    ok = await repo.update_status_cas(
        "agr_2", expected_status=AgreementState.PENDING_SELLER,
        expected_row_version=1, new_status=AgreementState.PENDING_BUYER,
        new_row_version=2, expires_at=None, now=now,
    )
    assert ok is True
    again = await repo.update_status_cas(
        "agr_2", expected_status=AgreementState.PENDING_SELLER,
        expected_row_version=1, new_status=AgreementState.PENDING_BUYER,
        new_row_version=2, expires_at=None, now=now,
    )
    assert again is False
```

- [ ] **Step 2: Implement `repository.py`**

```python
# apps/verifund_control_plane/verifund_control_plane/agreements/repository.py
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, select, update, insert, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from verifund_control_plane.db import transaction
from .models import (
    Agreement, AgreementDecisionRecord, AgreementEvent,
    AgreementVersion, ApprovalTokenRecord, ChangeRequest,
)


def _iso(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _dt(v: str | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


class AgreementRepository:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.metadata = MetaData()
        self._define_tables()

    def _define_tables(self) -> None:
        self.agreements = Table(
            "agreements", self.metadata,
            Column("agreement_id", String, primary_key=True),
            Column("transaction_id", String, nullable=False, unique=True),
            Column("run_id", String, nullable=False, index=True),
            Column("buyer_id", String, nullable=False, index=True),
            Column("seller_id", String, nullable=False, index=True),
            Column("current_version", Integer, nullable=False),
            Column("status", String, nullable=False, index=True),
            Column("offer_id", String, nullable=False),
            Column("offer_round", Integer, nullable=False),
            Column("offer_hash", String, nullable=False),
            Column("offer_valid_until", String, nullable=False),
            Column("expires_at", String, nullable=True),
            Column("agreed_at", String, nullable=True),
            Column("rejected_at", String, nullable=True),
            Column("expired_at", String, nullable=True),
            Column("terminated_at", String, nullable=True),
            Column("terminal_reason", String, nullable=True),
            Column("seller_operator_required", Integer, nullable=False, default=0),
            Column("row_version", Integer, nullable=False, default=1),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.agreement_versions = Table(
            "agreement_versions", self.metadata,
            Column("agreement_id", String, nullable=False),
            Column("version", Integer, nullable=False),
            Column("terms", Text, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("rendered_html", Text, nullable=False),
            Column("renderer_version", String, nullable=False),
            Column("created_at", String, nullable=False),
            Column("supersedes_version", Integer, nullable=True),
            Column("change_request_id", String, nullable=True),
            Column("superseded_at", String, nullable=True),
            # composite PK
        )
        # set PK constraint manually
        from sqlalchemy import PrimaryKeyConstraint
        self.agreement_versions.append_constraint(
            PrimaryKeyConstraint("agreement_id", "version", name="pk_agreement_versions")
        )
        self.agreement_decisions = Table(
            "agreement_decisions", self.metadata,
            Column("decision_id", String, primary_key=True),
            Column("agreement_id", String, nullable=False, index=True),
            Column("version", Integer, nullable=False),
            Column("party", String, nullable=False),
            Column("decision", String, nullable=False),
            Column("actor_type", String, nullable=False),
            Column("actor_id", String, nullable=False),
            Column("authority_ref", String, nullable=True),
            Column("authority_snapshot", Text, nullable=True),
            Column("agreement_hash", String, nullable=False),
            Column("verified_offer_hash", String, nullable=True),
            Column("verified_change_request_id", String, nullable=True),
            Column("reason_code", String, nullable=True),
            Column("note", Text, nullable=False, default=""),
            Column("change_request_id", String, nullable=True),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("decided_at", String, nullable=False),
        )
        self.agreement_change_requests = Table(
            "agreement_change_requests", self.metadata,
            Column("change_request_id", String, primary_key=True),
            Column("agreement_id", String, nullable=False, index=True),
            Column("base_version", Integer, nullable=False),
            Column("base_hash", String, nullable=False),
            Column("requested_by_party", String, nullable=False),
            Column("requested_by_actor_type", String, nullable=False),
            Column("requested_by_actor_id", String, nullable=False),
            Column("operations", Text, nullable=False),
            Column("reason", Text, nullable=False, default=""),
            Column("status", String, nullable=False, index=True),
            Column("resolved_by_party", String, nullable=True),
            Column("resolved_by_actor_type", String, nullable=True),
            Column("resolved_by_actor_id", String, nullable=True),
            Column("resolution_note", Text, nullable=True),
            Column("resulting_version", Integer, nullable=True),
            Column("created_at", String, nullable=False),
            Column("resolved_at", String, nullable=True),
        )
        self.agreement_approval_tokens = Table(
            "agreement_approval_tokens", self.metadata,
            Column("jti", String, primary_key=True),
            Column("agreement_id", String, nullable=False, index=True),
            Column("version", Integer, nullable=False),
            Column("agreement_hash", String, nullable=False),
            Column("subject_id", String, nullable=False),
            Column("token_hash", String, nullable=False),
            Column("issued_at", String, nullable=False),
            Column("expires_at", String, nullable=False, index=True),
            Column("used_at", String, nullable=True),
            Column("revoked_at", String, nullable=True),
            Column("issued_by_actor_type", String, nullable=False),
            Column("issued_by_actor_id", String, nullable=False),
            Column("consumed_by_decision_id", String, nullable=True),
        )
        self.agreement_events = Table(
            "agreement_events", self.metadata,
            Column("event_id", Integer, primary_key=True, autoincrement=True),
            Column("agreement_id", String, nullable=False, index=True),
            Column("version", Integer, nullable=True),
            Column("event_type", String, nullable=False),
            Column("payload", Text, nullable=False),
            Column("actor_type", String, nullable=False),
            Column("actor_id", String, nullable=False),
            Column("created_at", String, nullable=False),
        )

    async def create_schema(self, conn: AsyncConnection) -> None:
        await conn.run_sync(self.metadata.create_all)
        # partial unique index for one open change request per agreement
        await conn.execute(__import__("sqlalchemy").text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_change_pending "
            "ON agreement_change_requests(agreement_id) WHERE status = 'PENDING'"
        ))

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncConnection, None]:
        async with self.engine.begin() as conn:
            yield conn

    def _row_to_agreement(self, row) -> Agreement:
        from verifund_contracts.models import AgreementState
        return Agreement(
            agreement_id=row["agreement_id"],
            transaction_id=row["transaction_id"],
            run_id=row["run_id"],
            buyer_id=row["buyer_id"],
            seller_id=row["seller_id"],
            current_version=row["current_version"],
            status=AgreementState(row["status"]),
            offer_id=row["offer_id"],
            offer_round=row["offer_round"],
            offer_hash=row["offer_hash"],
            offer_valid_until=_dt(row["offer_valid_until"]),
            expires_at=_dt(row["expires_at"]),
            agreed_at=_dt(row["agreed_at"]),
            rejected_at=_dt(row["rejected_at"]),
            expired_at=_dt(row["expired_at"]),
            terminated_at=_dt(row["terminated_at"]),
            terminal_reason=row["terminal_reason"],
            seller_operator_required=bool(row["seller_operator_required"]),
            row_version=row["row_version"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    async def create(self, conn, agreement: Agreement, version: AgreementVersion) -> None:
        import json as _json
        await conn.execute(self.agreements.insert().values(
            agreement_id=agreement.agreement_id,
            transaction_id=agreement.transaction_id,
            run_id=agreement.run_id,
            buyer_id=agreement.buyer_id,
            seller_id=agreement.seller_id,
            current_version=agreement.current_version,
            status=agreement.status.value,
            offer_id=agreement.offer_id,
            offer_round=agreement.offer_round,
            offer_hash=agreement.offer_hash,
            offer_valid_until=_iso(agreement.offer_valid_until),
            expires_at=_iso(agreement.expires_at),
            agreed_at=_iso(agreement.agreed_at),
            rejected_at=_iso(agreement.rejected_at),
            expired_at=_iso(agreement.expired_at),
            terminated_at=_iso(agreement.terminated_at),
            terminal_reason=agreement.terminal_reason,
            seller_operator_required=1 if agreement.seller_operator_required else 0,
            row_version=agreement.row_version,
            created_at=_iso(agreement.created_at),
            updated_at=_iso(agreement.updated_at),
        ))
        await conn.execute(self.agreement_versions.insert().values(
            agreement_id=version.agreement_id,
            version=version.version,
            terms=_json.dumps(version.terms, sort_keys=True),
            agreement_hash=version.agreement_hash,
            rendered_html=version.rendered_html,
            renderer_version=version.renderer_version,
            created_at=_iso(version.created_at),
            supersedes_version=version.supersedes_version,
            change_request_id=version.change_request_id,
            superseded_at=_iso(version.superseded_at),
        ))

    async def get(self, agreement_id: str) -> Agreement | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                self.agreements.select().where(self.agreements.c.agreement_id == agreement_id)
            )).mappings().first()
            if row is None:
                return None
            agr = self._row_to_agreement(row)
            ver_row = (await conn.execute(
                self.agreement_versions.select().where(
                    self.agreement_versions.c.agreement_id == agreement_id,
                    self.agreement_versions.c.version == agr.current_version,
                )
            )).mappings().first()
            if ver_row is not None:
                agr.current_version_record = AgreementVersion(
                    agreement_id=ver_row["agreement_id"],
                    version=ver_row["version"],
                    terms=__import__("json").loads(ver_row["terms"]),
                    agreement_hash=ver_row["agreement_hash"],
                    rendered_html=ver_row["rendered_html"],
                    renderer_version=ver_row["renderer_version"],
                    created_at=_dt(ver_row["created_at"]),
                    supersedes_version=ver_row["supersedes_version"],
                    change_request_id=ver_row["change_request_id"],
                    superseded_at=_dt(ver_row["superseded_at"]),
                )
            return agr

    async def get_by_transaction(self, transaction_id: str) -> Agreement | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                self.agreements.select().where(self.agreements.c.transaction_id == transaction_id)
            )).mappings().first()
        if row is None:
            return None
        return await self.get(row["agreement_id"])

    async def get_version(self, agreement_id: str, version: int) -> AgreementVersion | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                self.agreement_versions.select().where(
                    self.agreement_versions.c.agreement_id == agreement_id,
                    self.agreement_versions.c.version == version,
                )
            )).mappings().first()
        if row is None:
            return None
        import json as _json
        return AgreementVersion(
            agreement_id=row["agreement_id"], version=row["version"],
            terms=_json.loads(row["terms"]), agreement_hash=row["agreement_hash"],
            rendered_html=row["rendered_html"], renderer_version=row["renderer_version"],
            created_at=_dt(row["created_at"]), supersedes_version=row["supersedes_version"],
            change_request_id=row["change_request_id"],
            superseded_at=_dt(row["superseded_at"]),
        )

    async def list_versions(self, agreement_id: str) -> list[AgreementVersion]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(
                self.agreement_versions.select().where(
                    self.agreement_versions.c.agreement_id == agreement_id
                ).order_by(self.agreement_versions.c.version)
            )).mappings().all()
        import json as _json
        return [AgreementVersion(
            agreement_id=r["agreement_id"], version=r["version"],
            terms=_json.loads(r["terms"]), agreement_hash=r["agreement_hash"],
            rendered_html=r["rendered_html"], renderer_version=r["renderer_version"],
            created_at=_dt(r["created_at"]), supersedes_version=r["supersedes_version"],
            change_request_id=r["change_request_id"],
            superseded_at=_dt(r["superseded_at"]),
        ) for r in rows]

    async def append_decision(self, conn, decision: AgreementDecisionRecord) -> None:
        import json as _json
        await conn.execute(self.agreement_decisions.insert().values(
            decision_id=decision.decision_id,
            agreement_id=decision.agreement_id,
            version=decision.version,
            party=decision.party,
            decision=decision.decision.value,
            actor_type=decision.actor_type,
            actor_id=decision.actor_id,
            authority_ref=decision.authority_ref,
            authority_snapshot=_json.dumps(decision.authority_snapshot or {}),
            agreement_hash=decision.agreement_hash,
            verified_offer_hash=decision.verified_offer_hash,
            verified_change_request_id=decision.verified_change_request_id,
            reason_code=decision.reason_code,
            note=decision.note,
            change_request_id=decision.change_request_id,
            idempotency_key=decision.idempotency_key,
            decided_at=_iso(decision.decided_at),
        ))

    async def update_status_cas(self, agreement_id, *, expected_status, expected_row_version,
                               new_status, new_row_version, expires_at, now,
                               extra: dict[str, Any] | None = None) -> bool:
        from verifund_contracts.models import AgreementState
        values = {
            "status": new_status.value if hasattr(new_status, "value") else new_status,
            "row_version": new_row_version,
            "updated_at": _iso(now),
            "expires_at": _iso(expires_at),
        }
        if extra:
            values.update(extra)
        stmt = self.agreements.update().where(
            self.agreements.c.agreement_id == agreement_id,
            self.agreements.c.status == (expected_status.value if hasattr(expected_status, "value") else expected_status),
            self.agreements.c.row_version == expected_row_version,
        )
        if expires_at is not None:
            # deadline guard: only if not expired
            pass
        result = await conn.execute(stmt.values(**values))
        return result.rowcount == 1

    async def create_change_request(self, conn, cr: ChangeRequest) -> None:
        import json as _json
        await conn.execute(self.agreement_change_requests.insert().values(
            change_request_id=cr.change_request_id,
            agreement_id=cr.agreement_id,
            base_version=cr.base_version,
            base_hash=cr.base_hash,
            requested_by_party=cr.requested_by_party,
            requested_by_actor_type=cr.requested_by_actor_type,
            requested_by_actor_id=cr.requested_by_actor_id,
            operations=_json.dumps([o.model_dump(mode="json") for o in cr.operations]),
            reason=cr.reason,
            status=cr.status,
            created_at=_iso(cr.created_at),
        ))

    async def get_open_change_request(self, agreement_id: str) -> ChangeRequest | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                self.agreement_change_requests.select().where(
                    self.agreement_change_requests.c.agreement_id == agreement_id,
                    self.agreement_change_requests.c.status == "PENDING",
                )
            )).mappings().first()
        if row is None:
            return None
        import json as _json
        from verifund_contracts.models import ChangeOperation
        ops = [ChangeOperation.model_validate(o) for o in _json.loads(row["operations"])]
        return ChangeRequest(
            change_request_id=row["change_request_id"],
            agreement_id=row["agreement_id"],
            base_version=row["base_version"],
            base_hash=row["base_hash"],
            requested_by_party=row["requested_by_party"],
            requested_by_actor_type=row["requested_by_actor_type"],
            requested_by_actor_id=row["requested_by_actor_id"],
            operations=ops,
            reason=row["reason"],
            status=row["status"],
            resolved_by_party=row["resolved_by_party"],
            resolved_by_actor_type=row["resolved_by_actor_type"],
            resolved_by_actor_id=row["resolved_by_actor_id"],
            resolution_note=row["resolution_note"] or "",
            resulting_version=row["resulting_version"],
            created_at=_dt(row["created_at"]),
            resolved_at=_dt(row["resolved_at"]),
        )

    async def resolve_change_request(self, conn, change_request_id: str, *,
                                     status: str, resolved_by_party: str,
                                     resolved_by_actor_type: str, resolved_by_actor_id: str,
                                     resolution_note: str, resulting_version: int | None,
                                     resolved_at: datetime) -> None:
        await conn.execute(self.agreement_change_requests.update().where(
            self.agreement_change_requests.c.change_request_id == change_request_id,
        ).values(
            status=status,
            resolved_by_party=resolved_by_party,
            resolved_by_actor_type=resolved_by_actor_type,
            resolved_by_actor_id=resolved_by_actor_id,
            resolution_note=resolution_note,
            resulting_version=resulting_version,
            resolved_at=_iso(resolved_at),
        ))

    async def issue_token(self, conn, token: ApprovalTokenRecord) -> None:
        await conn.execute(self.agreement_approval_tokens.insert().values(
            jti=token.jti,
            agreement_id=token.agreement_id,
            version=token.version,
            agreement_hash=token.agreement_hash,
            subject_id=token.subject_id,
            token_hash=token.token_hash,
            issued_at=_iso(token.issued_at),
            expires_at=_iso(token.expires_at),
            used_at=None,
            revoked_at=None,
            issued_by_actor_type=token.issued_by_actor_type,
            issued_by_actor_id=token.issued_by_actor_id,
            consumed_by_decision_id=None,
        ))

    async def consume_token(self, conn, jti: str, now: datetime,
                            consumed_by_decision_id: str) -> bool:
        stmt = self.agreement_approval_tokens.update().where(
            self.agreement_approval_tokens.c.jti == jti,
            self.agreement_approval_tokens.c.used_at.is_(None),
            self.agreement_approval_tokens.c.revoked_at.is_(None),
        ).values(used_at=_iso(now), consumed_by_decision_id=consumed_by_decision_id)
        result = await conn.execute(stmt)
        return result.rowcount == 1

    async def revoke_tokens(self, conn, agreement_id: str, version: int, now: datetime) -> None:
        await conn.execute(self.agreement_approval_tokens.update().where(
            self.agreement_approval_tokens.c.agreement_id == agreement_id,
            self.agreement_approval_tokens.c.version == version,
            self.agreement_approval_tokens.c.used_at.is_(None),
            self.agreement_approval_tokens.c.revoked_at.is_(None),
        ).values(revoked_at=_iso(now)))

    async def get_token(self, jti: str) -> ApprovalTokenRecord | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                self.agreement_approval_tokens.select().where(
                    self.agreement_approval_tokens.c.jti == jti
                )
            )).mappings().first()
        if row is None:
            return None
        return ApprovalTokenRecord(
            jti=row["jti"], agreement_id=row["agreement_id"],
            version=row["version"], agreement_hash=row["agreement_hash"],
            subject_id=row["subject_id"], token_hash=row["token_hash"],
            issued_at=_dt(row["issued_at"]), expires_at=_dt(row["expires_at"]),
            used_at=_dt(row["used_at"]), revoked_at=_dt(row["revoked_at"]),
            issued_by_actor_type=row["issued_by_actor_type"],
            issued_by_actor_id=row["issued_by_actor_id"],
            consumed_by_decision_id=row["consumed_by_decision_id"],
        )

    async def append_event(self, conn, event: AgreementEvent) -> None:
        await conn.execute(self.agreement_events.insert().values(
            agreement_id=event.agreement_id,
            version=event.version,
            event_type=event.event_type,
            payload=__import__("json").dumps(event.payload, sort_keys=True),
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            created_at=_iso(event.created_at),
        ))

    async def list_events(self, agreement_id: str) -> list[AgreementEvent]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(
                self.agreement_events.select().where(
                    self.agreement_events.c.agreement_id == agreement_id
                ).order_by(self.agreement_events.c.event_id)
            )).mappings().all()
        import json as _json
        return [AgreementEvent(
            event_id=r["event_id"], agreement_id=r["agreement_id"],
            version=r["version"], event_type=r["event_type"],
            payload=_json.loads(r["payload"]), actor_type=r["actor_type"],
            actor_id=r["actor_id"], created_at=_dt(r["created_at"]),
        ) for r in rows]

    async def list_expired(self, now: datetime, limit: int = 100) -> list[str]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(
                self.agreements.select().where(
                    self.agreements.c.status.in_(["PENDING_SELLER", "PENDING_BUYER", "CHANGES_REQUESTED"]),
                    self.agreements.c.expires_at.is_not(None),
                    self.agreements.c.expires_at <= _iso(now),
                ).limit(limit)
            )).mappings().all()
        return [r["agreement_id"] for r in rows]

    async def expire(self, conn, agreement_id: str, expected_row_version: int, now: datetime) -> bool:
        stmt = self.agreements.update().where(
            self.agreements.c.agreement_id == agreement_id,
            self.agreements.c.row_version == expected_row_version,
            self.agreements.c.expires_at.is_not(None),
            self.agreements.c.expires_at <= _iso(now),
        ).values(
            status="EXPIRED", expired_at=_iso(now), row_version=expected_row_version + 1,
            updated_at=_iso(now),
        )
        result = await conn.execute(stmt)
        return result.rowcount == 1
```

Note: `AgreementRepository` must share the same `transaction()` helper. The control plane's `Repository` has `transaction()`. To keep a single DB, `AgreementRepository` takes the same engine. `VerifundService` will own both repos. `create_schema` must be called for both. In `app.py`, call `repo.create_schema()` (existing) and `agreement_repo.create_schema()`.

Also modify the existing `Repository`:
- Replace the JSON-blob `agreements` and `agreement_reviews` tables? The design says replace them. But existing code/tests may reference `repo.agreements`. To minimize breakage, keep the tables for now but unused; or remove and update tests. The plan says clean reset. We'll keep the old tables removed and update tests that reference them. Given complexity, in Task 2.1 we update `Repository.create_schema` to add new columns to `transactions` (`buyer_precheck` rename, `agreement_id` already present) and remove old agreement tables. The `AgreementRepository` owns agreement tables. Existing tests referencing `repo.agreements` will need updates; track in Task 7.

Also add to `AgreementRepository`:
- `async def create_version(self, conn, version: AgreementVersion) -> None` — inserts into `agreement_versions`.
- `async def list_decisions(self, agreement_id: str) -> list[AgreementDecisionRecord]` — reads `agreement_decisions` ordered by `decided_at`.
- `async def get_decision_by_idempotency(self, key: str)` for idempotency replay.

### Task 1.5: Buyer approval tokens

**Files:**
- Create: `.../agreements/tokens.py`
- Test: `tests/unit/test_agreement_tokens.py`

**Interfaces:**
- Consumes: `LinkSigner` pattern from `verifund_control_plane.tokens`.
- Produces: `ApprovalTokenService` with `issue(agreement, actor, now) -> (raw_token, record)`, `verify(raw_token) -> claims`, `consume(conn, jti, decision_id, now) -> bool`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_agreement_tokens.py
from datetime import datetime, timedelta, timezone

from verifund_control_plane.agreements.tokens import ApprovalTokenService
from verifund_control_plane.tokens import LinkSigner


def test_issue_verify_consume():
    signer = LinkSigner("secret-32-chars-minimum-xxxxxxxx", clock=lambda: datetime.now(timezone.utc))
    svc = ApprovalTokenService(signer, ttl_minutes=30)
    now = datetime.now(timezone.utc)
    raw, record = svc.issue("agr_1", 1, "a" * 64, "buyer-1", "demo", "demo-buyer", now)
    claims = svc.verify(raw)
    assert claims["aud"] == "agreement-approval"
    assert claims["sub"] == "buyer-1"
    assert claims["agreement_id"] == "agr_1"
    assert claims["version"] == 1
    assert claims["agreement_hash"] == "a" * 64
```

- [ ] **Step 2: Implement tokens**

```python
# apps/verifund_control_plane/verifund_control_plane/agreements/tokens.py
from __future__ import annotations

import hashlib
import hmac
import json
import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .models import ApprovalTokenRecord


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


class ApprovalTokenService:
    def __init__(self, secret: str, *, ttl_minutes: int = 30,
                 clock: Callable[[], datetime] | None = None):
        self.secret = secret.encode("utf-8")
        self.ttl_minutes = ttl_minutes
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return self.clock()

    def issue(self, agreement_id: str, version: int, agreement_hash: str,
              subject_id: str, issued_by_actor_type: str,
              issued_by_actor_id: str, agreement_expires_at: datetime | None,
              now: datetime | None = None) -> tuple[str, ApprovalTokenRecord]:
        now = now or self._now()
        jti = str(uuid.uuid4())
        ttl = timedelta(minutes=self.ttl_minutes)
        exp = now + ttl
        if agreement_expires_at is not None:
            exp = min(exp, agreement_expires_at)
        claims = {
            "jti": jti, "aud": "agreement-approval", "sub": subject_id,
            "agreement_id": agreement_id, "version": version,
            "agreement_hash": agreement_hash,
            "iat": now.isoformat().replace("+00:00", "Z"),
            "exp": exp.isoformat().replace("+00:00", "Z"),
        }
        raw = _b64url_encode(json.dumps(claims, sort_keys=True).encode()) + "." + _b64url_encode(
            hmac.new(self.secret, json.dumps(claims, sort_keys=True).encode(), hashlib.sha256).digest()
        )
        record = ApprovalTokenRecord(
            jti=jti, agreement_id=agreement_id, version=version,
            agreement_hash=agreement_hash, subject_id=subject_id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            issued_at=now, expires_at=exp,
            issued_by_actor_type=issued_by_actor_type,
            issued_by_actor_id=issued_by_actor_id,
        )
        return raw, record

    def verify(self, raw: str) -> dict[str, Any]:
        try:
            body, sig = raw.split(".", 1)
        except ValueError:
            raise ValueError("invalid_token")
        claims_json = _b64url_decode(body)
        claims = json.loads(claims_json)
        expected_sig = hmac.new(self.secret, claims_json, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig), expected_sig):
            raise ValueError("invalid_signature")
        now = self._now()
        exp = datetime.fromisoformat(claims["exp"].replace("Z", "+00:00"))
        if now > exp:
            raise ValueError("token_expired")
        if claims.get("aud") != "agreement-approval":
            raise ValueError("invalid_audience")
        return claims

    async def consume(self, repo, jti: str, decision_id: str, now: datetime) -> bool:
        return await repo.consume_token(repo.engine and None, jti, now, decision_id) if False else await repo.consume_token_by_jti(jti, decision_id, now)
```

The `consume` helper depends on the repository. To keep it simple, the service calls `repo.consume_token(conn, jti, now, decision_id)` directly. The token service only issues/verifies. Adjust `issue` signature to accept a signer-like secret string; `app.py` passes `settings.link_secret`.

- [ ] **Step 3: Run tests and commit.**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -v`
Expected: PASS

Commit: `git commit -m "feat(agreements): add single-use approval tokens"`

### Task 1.6: Agreement service lifecycle

**Files:**
- Create: `.../agreements/service.py`
- Test: `tests/unit/test_agreement_service.py`

**Interfaces:**
- Consumes: `AgreementRepository`, `ApprovalTokenService`, settings, clock.
- Produces: `AgreementService` with `create_from_award(conn, award, transaction_id, run_id, now)`, `record_seller_decision(conn, agreement_id, request, actor, now)`, `issue_buyer_token(conn, agreement_id, actor, now)`, `record_buyer_decision(conn, agreement_id, token_claims, request, actor, now)`, `create_change_request(conn, ...)`, `resolve_change_request(conn, ...)`, `expire_due(now)`, `terminate(conn, agreement_id, reason, now)`, `get`, `get_by_transaction`, `list_versions`, `document`, `verify_funding_binding`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_agreement_service.py
import pytest
from datetime import datetime, timedelta, timezone

from verifund_contracts.models import (
    AgreementDecision, AgreementState, AwardRequest, BuyerApprovalDecision,
    ChangeSet, ChangeOperation, ChangeOperationType, EvidenceKind, RemedyTerms,
    RemedyPolicy,
)
from verifund_control_plane.agreements.service import AgreementService


def _award():
    return AwardRequest(
        run_id="run-1", buyer_id="buyer-1", seller_id="seller-1",
        offer_id="offer-1", request_id="rfq-1",
        buyer_display_name="Buyer", seller_display_name="Seller",
        currency="USD", amount_cents=51600, shipping_cents=2500,
        tax_cents=3600, fees_cents=500, quantity=10,
        line_items=[__import__("verifund_contracts.models", fromlist=["AwardLineItem"]).AwardLineItem(
            sku="SKU-1", name="Sensor", quantity=10,
            unit_price_cents=4200, warranty_addon_cents=300)],
        delivery_days=5, warranty_months=12, returns_days=30,
        offer_round=2, offer_hash="a" * 64,
        offer_valid_until=datetime.now(timezone.utc) + timedelta(hours=1),
        remedies=RemedyTerms(non_delivery=RemedyPolicy.CANCEL_AND_REFUND,
                             late_delivery=RemedyPolicy.CANCEL_AND_REFUND,
                             damaged_goods=RemedyPolicy.REFUND_OR_REPLACEMENT),
    )


@pytest.mark.asyncio
async def test_create_and_seller_accept(tmp_path):
    from verifund_control_plane.db import configure_sqlite, create_engine
    from verifund_control_plane.agreements.repository import AgreementRepository
    from verifund_control_plane.agreements.tokens import ApprovalTokenService
    from verifund_control_plane.settings import Settings
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await configure_sqlite(engine)
    repo = AgreementRepository(engine)
    async with engine.begin() as conn:
        await repo.create_schema(conn)
    svc = AgreementService(repo=repo, token_service=ApprovalTokenService("secret-32-chars-minimum-xxxxxxxx"),
                           settings=Settings(), clock=lambda: datetime.now(timezone.utc))
    award = _award()
    now = datetime.now(timezone.utc)
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
```

- [ ] **Step 2: Implement `service.py`**

This is the core. Implement all methods following the design §6-§7. Key logic:

```python
# apps/verifund_control_plane/verifund_control_plane/agreements/service.py
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from verifund_contracts.models import (
    AgreementDecision, AgreementState, BuyerApprovalDecision, ChangeOperation,
    ChangeSet, EvidenceKind,
)
from verifund_control_plane.agreements.models import (
    ActorContext, Agreement, AgreementDecisionRecord, AgreementError,
    AgreementEvent, ApprovalTokenRecord, ChangeRequest,
)
from verifund_control_plane.agreements.repository import AgreementRepository
from verifund_control_plane.agreements.states import next_state, is_terminal
from verifund_control_plane.agreements.generator import (
    build_terms, validate_award, validate_terms, apply_change_set,
)
from verifund_control_plane.agreements.digest import agreement_hash
from verifund_control_plane.agreements.renderer import render_agreement, RENDERER_VERSION
from verifund_control_plane.agreements.tokens import ApprovalTokenService
from verifund_control_plane.settings import Settings
from verifund_control_plane.errors import VerifundError


def _iso(v): ...  # reuse repository helper


class AgreementService:
    def __init__(self, *, repo: AgreementRepository, token_service: ApprovalTokenService,
                 settings: Settings, clock: Callable[[], datetime]):
        self.repo = repo
        self.token_service = token_service
        self.settings = settings
        self.clock = clock

    def _now(self): return self.clock()

    async def create_from_award(self, conn, award, transaction_id, run_id, now):
        validate_award(award, now)
        # offer hash parity check left to caller; recompute binding here optionally
        terms = build_terms(award, now)
        validate_terms(terms, award)
        agreement_id = f"agr_{uuid.uuid4().hex}"
        h = agreement_hash(agreement_id, 1, terms)
        html_doc = render_agreement(terms, agreement_id, 1, h)
        seller_hours = getattr(self.settings, "agreement_seller_acceptance_hours", 24)
        expires_at = now + timedelta(hours=seller_hours)
        from verifund_contracts.models import AgreementState as AS
        agreement = Agreement(
            agreement_id=agreement_id, transaction_id=transaction_id, run_id=run_id,
            buyer_id=award.buyer_id, seller_id=award.seller_id, current_version=1,
            status=AS.PENDING_SELLER, offer_id=award.offer_id,
            offer_round=award.offer_round, offer_hash=award.offer_hash,
            offer_valid_until=award.offer_valid_until, expires_at=expires_at,
            agreed_at=None, rejected_at=None, expired_at=None, terminated_at=None,
            terminal_reason=None, seller_operator_required=False, row_version=1,
            created_at=now, updated_at=now,
        )
        from .models import AgreementVersion
        version = AgreementVersion(
            agreement_id=agreement_id, version=1, terms=terms, agreement_hash=h,
            rendered_html=html_doc, renderer_version=RENDERER_VERSION, created_at=now,
        )
        await self.repo.create(conn, agreement, version)
        agreement.current_version_record = version
        await self.repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id=agreement_id, version=1,
            event_type="agreement.created", payload={"offer_id": award.offer_id},
            actor_type="system", actor_id="control-plane", created_at=now,
        ))
        return agreement

    async def record_seller_decision(self, conn, agreement_id, *, decision, actor_type,
                                     actor_id, authority_ref, authority_snapshot,
                                     agreement_version, agreement_hash, verified_offer_hash,
                                     note, idempotency_key, now, change_set=None):
        agreement = await self.repo.get(agreement_id)
        if agreement is None:
            raise AgreementError("not_found", "agreement not found", agreement_id=agreement_id)
        if is_terminal(agreement.status):
            raise AgreementError("invalid_state", "agreement is terminal", agreement_id=agreement_id)
        if agreement.status != AgreementState.PENDING_SELLER:
            raise AgreementError("invalid_state", "seller decision only in PENDING_SELLER")
        if agreement.current_version != agreement_version:
            raise AgreementError("hash_mismatch", "stale version", agreement_id=agreement_id, version=agreement_version)
        cur = agreement.current_version_record
        if cur is None or cur.agreement_hash != agreement_hash:
            raise AgreementError("hash_mismatch", "stale digest", agreement_id=agreement_id, version=agreement_version)
        # deadline check
        if agreement.expires_at is not None and now > agreement.expires_at:
            # lazy expire
            await self._expire_one(conn, agreement, now)
            raise AgreementError("agreement_expired", "agreement expired", agreement_id=agreement_id)
        if decision == AgreementDecision.ACCEPT:
            new_status = next_state(agreement.status, "SELLER_ACCEPT")
            seller_hours = getattr(self.settings, "agreement_buyer_approval_hours", 24)
            new_expires = now + timedelta(hours=seller_hours)
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex}", agreement_id=agreement_id,
                version=agreement_version, party="seller", decision=AgreementDecision.ACCEPT,
                actor_type=actor_type, actor_id=actor_id, authority_ref=authority_ref,
                authority_snapshot=authority_snapshot or {}, agreement_hash=agreement_hash,
                verified_offer_hash=verified_offer_hash, verified_change_request_id=None,
                reason_code=None, note=note, change_request_id=None,
                idempotency_key=idempotency_key, decided_at=now,
            ))
            ok = await self.repo.update_status_cas(
                agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version, new_status=new_status,
                new_row_version=agreement.row_version + 1, expires_at=new_expires, now=now,
            )
            if not ok:
                raise AgreementError("conflict", "concurrent update", agreement_id=agreement_id)
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement_version,
                event_type="seller.accepted", payload={}, actor_type=actor_type,
                actor_id=actor_id, created_at=now,
            ))
            agreement.status = new_status
            agreement.expires_at = new_expires
            agreement.row_version += 1
            return agreement
        if decision == AgreementDecision.REJECT:
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex}", agreement_id=agreement_id,
                version=agreement_version, party="seller", decision=AgreementDecision.REJECT,
                actor_type=actor_type, actor_id=actor_id, authority_ref=authority_ref,
                authority_snapshot=authority_snapshot or {}, agreement_hash=agreement_hash,
                verified_offer_hash=verified_offer_hash, verified_change_request_id=None,
                reason_code=None, note=note, change_request_id=None,
                idempotency_key=idempotency_key, decided_at=now,
            ))
            await self.repo.update_status_cas(
                agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version, new_status=AgreementState.REJECTED,
                new_row_version=agreement.row_version + 1, expires_at=None, now=now,
                extra={"rejected_at": _iso(now)},
            )
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement_version,
                event_type="seller.rejected", payload={}, actor_type=actor_type,
                actor_id=actor_id, created_at=now,
            ))
            agreement.status = AgreementState.REJECTED
            return agreement
        if decision == AgreementDecision.REQUEST_CHANGES:
            # create change request
            from verifund_contracts.models import ChangeSet
            if change_set is None:
                raise AgreementError("invalid_request", "change_set required")
            cr_id = f"cr_{uuid.uuid4().hex}"
            cr = ChangeRequest(
                change_request_id=cr_id, agreement_id=agreement_id,
                base_version=agreement_version, base_hash=agreement_hash,
                requested_by_party="seller", requested_by_actor_type=actor_type,
                requested_by_actor_id=actor_id, operations=change_set.operations,
                reason=change_set.reason, status="PENDING", created_at=now,
            )
            await self.repo.create_change_request(conn, cr)
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex}", agreement_id=agreement_id,
                version=agreement_version, party="seller",
                decision=AgreementDecision.REQUEST_CHANGES, actor_type=actor_type,
                actor_id=actor_id, authority_ref=authority_ref,
                authority_snapshot=authority_snapshot or {}, agreement_hash=agreement_hash,
                verified_offer_hash=verified_offer_hash, verified_change_request_id=None,
                reason_code=None, note=note, change_request_id=cr_id,
                idempotency_key=idempotency_key, decided_at=now,
            ))
            change_hours = getattr(self.settings, "agreement_change_response_hours", 24)
            new_expires = now + timedelta(hours=change_hours)
            await self.repo.update_status_cas(
                agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version,
                new_status=AgreementState.CHANGES_REQUESTED,
                new_row_version=agreement.row_version + 1, expires_at=new_expires, now=now,
            )
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement_version,
                event_type="seller.requested_changes", payload={"change_request_id": cr_id},
                actor_type=actor_type, actor_id=actor_id, created_at=now,
            ))
            agreement.status = AgreementState.CHANGES_REQUESTED
            agreement.expires_at = new_expires
            agreement.row_version += 1
            return agreement
        # OPERATOR_REQUIRED is reported by seller agent but handled as no-op flag by control plane
        raise AgreementError("invalid_request", "unsupported decision")

    async def _expire_one(self, conn, agreement, now):
        ok = await self.repo.expire(conn, agreement.agreement_id, agreement.row_version, now)
        if ok:
            await self.repo.revoke_tokens(conn, agreement.agreement_id, agreement.current_version, now)
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement.agreement_id,
                version=agreement.current_version, event_type="agreement.expired",
                payload={}, actor_type="system", actor_id="reconciler", created_at=now,
            ))

    async def issue_buyer_token(self, conn, agreement_id, actor, now):
        agreement = await self.repo.get(agreement_id)
        if agreement is None or agreement.status != AgreementState.PENDING_BUYER:
            raise AgreementError("invalid_state", "not pending buyer")
        cur = agreement.current_version_record
        raw, record = self.token_service.issue(
            agreement.agreement_id, agreement.current_version, cur.agreement_hash,
            agreement.buyer_id, actor.actor_type, actor.actor_id,
            agreement.expires_at, now,
        )
        await self.repo.issue_token(conn, record)
        return raw, record

    async def record_buyer_decision(self, conn, agreement_id, token_claims, request, actor, now):
        agreement = await self.repo.get(agreement_id)
        if agreement is None:
            raise AgreementError("not_found", "agreement not found")
        if is_terminal(agreement.status):
            raise AgreementError("invalid_state", "terminal")
        if agreement.status != AgreementState.PENDING_BUYER:
            raise AgreementError("invalid_state", "buyer decision only in PENDING_BUYER")
        # token checks
        jti = token_claims.get("jti")
        token = await self.repo.get_token(jti)
        if token is None:
            raise AgreementError("token_revoked", "unknown token")
        if token.used_at is not None:
            raise AgreementError("token_used", "token already used")
        if token.revoked_at is not None:
            raise AgreementError("token_revoked", "token revoked")
        if token.expires_at < now:
            raise AgreementError("token_expired", "token expired")
        if token.subject_id != agreement.buyer_id or token.subject_id != actor.actor_id:
            raise AgreementError("forbidden", "token subject mismatch")
        if token.version != agreement.current_version or token.agreement_hash != agreement.current_version_record.agreement_hash:
            raise AgreementError("hash_mismatch", "token does not bind current version")
        if request.agreement_version != agreement.current_version or request.agreement_hash != agreement.current_version_record.agreement_hash:
            raise AgreementError("hash_mismatch", "stale version/digest")
        decision = request.decision  # BuyerApprovalDecision
        # consume token atomically
        ok = await self.repo.consume_token(conn, jti, now, None)
        if not ok:
            raise AgreementError("token_used", "token already used")
        if decision == BuyerApprovalDecision.APPROVE:
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex}", agreement_id=agreement_id,
                version=agreement.current_version, party="buyer",
                decision=AgreementDecision.ACCEPT, actor_type=actor.actor_type,
                actor_id=actor.actor_id, authority_ref=None,
                authority_snapshot={}, agreement_hash=agreement.current_version_record.agreement_hash,
                verified_offer_hash=None, verified_change_request_id=None,
                reason_code=None, note=request.note, change_request_id=None,
                idempotency_key=request.idempotency_key, decided_at=now,
            ))
            await self.repo.update_status_cas(
                agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version, new_status=AgreementState.AGREED,
                new_row_version=agreement.row_version + 1, expires_at=None, now=now,
                extra={"agreed_at": _iso(now)},
            )
            await self.repo.revoke_tokens(conn, agreement_id, agreement.current_version, now)
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement.current_version,
                event_type="agreement.agreed", payload={}, actor_type=actor.actor_type,
                actor_id=actor.actor_id, created_at=now,
            ))
            agreement.status = AgreementState.AGREED
            return agreement
        if decision == BuyerApprovalDecision.REJECT:
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex}", agreement_id=agreement_id,
                version=agreement.current_version, party="buyer",
                decision=AgreementDecision.REJECT, actor_type=actor.actor_type,
                actor_id=actor.actor_id, authority_ref=None,
                authority_snapshot={}, agreement_hash=agreement.current_version_record.agreement_hash,
                verified_offer_hash=None, verified_change_request_id=None,
                reason_code=None, note=request.note, change_request_id=None,
                idempotency_key=request.idempotency_key, decided_at=now,
            ))
            await self.repo.update_status_cas(
                agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version, new_status=AgreementState.REJECTED,
                new_row_version=agreement.row_version + 1, expires_at=None, now=now,
                extra={"rejected_at": _iso(now)},
            )
            agreement.status = AgreementState.REJECTED
            return agreement
        if decision == BuyerApprovalDecision.REQUEST_CHANGES:
            if request.change_set is None:
                raise AgreementError("invalid_request", "change_set required")
            cr_id = f"cr_{uuid.uuid4().hex}"
            from .models import ChangeRequest
            cr = ChangeRequest(
                change_request_id=cr_id, agreement_id=agreement_id,
                base_version=agreement.current_version, base_hash=agreement.current_version_record.agreement_hash,
                requested_by_party="buyer", requested_by_actor_type=actor.actor_type,
                requested_by_actor_id=actor.actor_id, operations=request.change_set.operations,
                reason=request.change_set.reason, status="PENDING", created_at=now,
            )
            await self.repo.create_change_request(conn, cr)
            await self.repo.append_decision(conn, AgreementDecisionRecord(
                decision_id=f"dec_{uuid.uuid4().hex}", agreement_id=agreement_id,
                version=agreement.current_version, party="buyer",
                decision=AgreementDecision.REQUEST_CHANGES, actor_type=actor.actor_type,
                actor_id=actor.actor_id, authority_ref=None,
                authority_snapshot={}, agreement_hash=agreement.current_version_record.agreement_hash,
                verified_offer_hash=None, verified_change_request_id=None,
                reason_code=None, note=request.note, change_request_id=cr_id,
                idempotency_key=request.idempotency_key, decided_at=now,
            ))
            change_hours = getattr(self.settings, "agreement_change_response_hours", 24)
            new_expires = now + timedelta(hours=change_hours)
            await self.repo.update_status_cas(
                agreement_id, expected_status=agreement.status,
                expected_row_version=agreement.row_version,
                new_status=AgreementState.CHANGES_REQUESTED,
                new_row_version=agreement.row_version + 1, expires_at=new_expires, now=now,
            )
            agreement.status = AgreementState.CHANGES_REQUESTED
            agreement.expires_at = new_expires
            agreement.row_version += 1
            return agreement
        raise AgreementError("invalid_request", "unsupported decision")

    async def create_change_request(self, conn, agreement_id, party, actor, change_set, now):
        # used by the dedicated change-request endpoint; same as decision path
        agreement = await self.repo.get(agreement_id)
        if agreement is None:
            raise AgreementError("not_found", "agreement not found")
        if is_terminal(agreement.status):
            raise AgreementError("invalid_state", "terminal")
        if party == "buyer" and agreement.status != AgreementState.PENDING_BUYER:
            raise AgreementError("invalid_state", "buyer change request only in PENDING_BUYER")
        if party == "seller" and agreement.status != AgreementState.PENDING_SELLER:
            raise AgreementError("invalid_state", "seller change request only in PENDING_SELLER")
        # delegate to record_*_decision with REQUEST_CHANGES
        ...

    async def resolve_change_request(self, conn, agreement_id, change_request_id, accept, actor, note, now):
        agreement = await self.repo.get(agreement_id)
        cr = await self.repo.get_open_change_request(agreement_id)
        if cr is None or cr.change_request_id != change_request_id:
            raise AgreementError("not_found", "change request not found")
        # counterparty check
        if cr.requested_by_party == "buyer" and actor.actor_type not in ("SELLER_AGENT", "SELLER_OPERATOR"):
            raise AgreementError("forbidden", "only seller may resolve buyer request")
        if cr.requested_by_party == "seller" and actor.actor_type != "buyer":
            raise AgreementError("forbidden", "only buyer may resolve seller request")
        if not accept:
            # reject
            requester_pending = (
                AgreementState.PENDING_SELLER if cr.requested_by_party == "seller"
                else AgreementState.PENDING_BUYER
            )
            await self.repo.resolve_change_request(
                conn, change_request_id, status="REJECTED",
                resolved_by_party="seller" if cr.requested_by_party == "buyer" else "buyer",
                resolved_by_actor_type=actor.actor_type, resolved_by_actor_id=actor.actor_id,
                resolution_note=note, resulting_version=None, resolved_at=now,
            )
            change_hours = getattr(self.settings, "agreement_change_response_hours", 24)
            await self.repo.update_status_cas(
                agreement_id, expected_status=AgreementState.CHANGES_REQUESTED,
                expected_row_version=agreement.row_version, new_status=requester_pending,
                new_row_version=agreement.row_version + 1,
                expires_at=now + timedelta(hours=change_hours), now=now,
            )
            await self.repo.append_event(conn, AgreementEvent(
                event_id=None, agreement_id=agreement_id, version=agreement.current_version,
                event_type="changes_rejected", payload={"change_request_id": change_request_id},
                actor_type=actor.actor_type, actor_id=actor.actor_id, created_at=now,
            ))
            return await self.repo.get(agreement_id)
        # accept: apply change set
        base_version = await self.repo.get_version(agreement_id, cr.base_version)
        from .generator import apply_change_set, validate_terms
        new_terms = apply_change_set(base_version.terms, type("CS", (), {"operations": cr.operations, "reason": cr.reason})())
        # validate against a synthetic award-less check: reuse validate_terms with None? 
        # validate_terms requires award; for changes we skip award-specific checks
        # (offer binding stays fixed). Just structural validation:
        # (re-implement minimal: totals arithmetic already in apply_change_set)
        new_version_number = agreement.current_version + 1
        new_hash = agreement_hash(agreement_id, new_version_number, new_terms)
        new_html = render_agreement(new_terms, agreement_id, new_version_number, new_hash)
        # insert new version
        from .models import AgreementVersion
        new_ver = AgreementVersion(
            agreement_id=agreement_id, version=new_version_number, terms=new_terms,
            agreement_hash=new_hash, rendered_html=new_html, renderer_version=RENDERER_VERSION,
            created_at=now, supersedes_version=cr.base_version,
            change_request_id=change_request_id,
        )
        await self.repo.create_version(conn, new_ver)  # need add method
        await self.repo.resolve_change_request(
            conn, change_request_id, status="ACCEPTED",
            resolved_by_party="seller" if cr.requested_by_party == "buyer" else "buyer",
            resolved_by_actor_type=actor.actor_type, resolved_by_actor_id=actor.actor_id,
            resolution_note=note, resulting_version=new_version_number, resolved_at=now,
        )
        seller_hours = getattr(self.settings, "agreement_seller_acceptance_hours", 24)
        await self.repo.update_status_cas(
            agreement_id, expected_status=AgreementState.CHANGES_REQUESTED,
            expected_row_version=agreement.row_version,
            new_status=AgreementState.PENDING_SELLER,
            new_row_version=agreement.row_version + 1,
            expires_at=now + timedelta(hours=seller_hours), now=now,
            extra={"current_version": new_version_number},
        )
        # update agreement.current_version in DB already via extra? need column update
        await self.repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id=agreement_id, version=new_version_number,
            event_type="changes_accepted", payload={"change_request_id": change_request_id},
            actor_type=actor.actor_type, actor_id=actor.actor_id, created_at=now,
        ))
        return await self.repo.get(agreement_id)

    async def expire_due(self, now):
        ids = await self.repo.list_expired(now)
        expired = []
        for aid in ids:
            agreement = await self.repo.get(aid)
            if agreement is None:
                continue
            async with self.repo.transaction() as conn:
                ok = await self.repo.expire(conn, aid, agreement.row_version, now)
                if ok:
                    await self.repo.revoke_tokens(conn, aid, agreement.current_version, now)
                    await self.repo.append_event(conn, AgreementEvent(
                        event_id=None, agreement_id=aid, version=agreement.current_version,
                        event_type="agreement.expired", payload={}, actor_type="system",
                        actor_id="reconciler", created_at=now,
                    ))
                    expired.append(aid)
        return expired

    async def terminate(self, conn, agreement_id, reason, now):
        agreement = await self.repo.get(agreement_id)
        if agreement is None or agreement.status != AgreementState.AGREED:
            return agreement
        await self.repo.update_status_cas(
            agreement_id, expected_status=AgreementState.AGREED,
            expected_row_version=agreement.row_version, new_status=AgreementState.TERMINATED,
            new_row_version=agreement.row_version + 1, expires_at=None, now=now,
            extra={"terminated_at": _iso(now), "terminal_reason": reason},
        )
        await self.repo.append_event(conn, AgreementEvent(
            event_id=None, agreement_id=agreement_id, version=agreement.current_version,
            event_type="agreement.terminated", payload={"reason": reason},
            actor_type="system", actor_id="control-plane", created_at=now,
        ))
        return await self.repo.get(agreement_id)

    async def get(self, agreement_id):
        return await self.repo.get(agreement_id)

    async def get_by_transaction(self, transaction_id):
        return await self.repo.get_by_transaction(transaction_id)

    async def list_versions(self, agreement_id):
        return await self.repo.list_versions(agreement_id)

    async def document(self, agreement_id, version=None):
        agr = await self.repo.get(agreement_id)
        if agr is None:
            return None
        v = version or agr.current_version
        ver = await self.repo.get_version(agreement_id, v)
        return ver.rendered_html if ver else None

    def verify_funding_binding(self, agreement, transaction, version, digest):
        if agreement is None or agreement.status is not AgreementState.AGREED:
            raise AgreementError("invalid_state", "agreement is not AGREED", agreement_id=agreement.agreement_id if agreement else None)
        if agreement.current_version != version:
            raise AgreementError("hash_mismatch", "stale agreement version")
        cur = agreement.current_version_record
        if cur is None or cur.agreement_hash != digest:
            raise AgreementError("hash_mismatch", "stale agreement digest")
        # decisions
        decs = [d for d in (await self.repo.list_decisions(agreement.agreement_id)) if d.version == version]
        buyer = next((d for d in decs if d.party == "buyer" and d.decision == AgreementDecision.ACCEPT), None)
        seller = next((d for d in decs if d.party == "seller" and d.decision == AgreementDecision.ACCEPT), None)
        if buyer is None or seller is None:
            raise AgreementError("invalid_state", "both acceptances are required")
        for d in (buyer, seller):
            if d.agreement_hash != digest:
                raise AgreementError("hash_mismatch", "acceptance does not bind this version")
        if transaction.agreement_id != agreement.agreement_id:
            raise AgreementError("invalid_state", "transaction is bound to another agreement")
```

Note: `repo.list_decisions` and `repo.create_version` must be added to the repository. Add them:
- `create_version(conn, version)` inserts into `agreement_versions`.
- `list_decisions(agreement_id)` returns list of `AgreementDecisionRecord`.

Also `repo.transaction()` is async context manager; `AgreementRepository` has it.

This service is long; the plan includes it as the reference implementation. Implementers should split helpers as needed. `VerifundError` mapping is done in routes.

- [ ] **Step 3: Run tests and commit.**

Run: `uv run pytest tests/unit/test_agreement_service.py -v`
Expected: PASS

Commit: `git commit -m "feat(agreements): add agreement service orchestration"`

### Task 1.7: Agreement HTTP routes and app wiring

**Files:**
- Create: `.../agreements/routes.py`
- Modify: `.../app.py`
- Modify: `.../settings.py`
- Test: `tests/integration/test_agreement_routes.py`

**Interfaces:**
- Consumes: `AgreementService`, `ApprovalTokenService`, `ActorContext`.
- Produces: router with endpoints from §10.2.

- [ ] **Step 1: Write failing tests** (happy path + auth + mismatch + idempotency).

- [ ] **Step 2: Implement routes.**

```python
# apps/verifund_control_plane/verifund_control_plane/agreements/routes.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from typing import Any

from verifund_control_plane.agreements.models import ActorContext, AgreementError
from verifund_control_plane.agreements.service import AgreementService
from verifund_contracts.models import (
    BuyerApprovalDecision, ChangeSet, AgreementState,
)

router = APIRouter(prefix="/agreements", tags=["agreements"])


def get_actor(request: Request) -> ActorContext:
    actor_id = request.headers.get("X-Actor-Id", "demo-buyer")
    actor_type = request.headers.get("X-Actor-Type", "buyer")
    return ActorContext(actor_id=actor_id, actor_type=actor_type, display_name=actor_id)


def get_service(request: Request) -> AgreementService:
    return request.app.state.agreement_service


def _handle(err: AgreementError):
    status = {"not_found": 404, "forbidden": 403, "invalid_state": 409,
              "hash_mismatch": 409, "agreement_expired": 409, "token_used": 409,
              "token_revoked": 409, "token_expired": 409, "conflict": 409,
              "offer_mismatch": 409, "offer_expired": 409}.get(err.code, 400)
    raise HTTPException(status_code=status, detail={"code": err.code, "message": err.message,
                                                   "agreement_id": err.agreement_id,
                                                   "version": err.version})


@router.get("")
async def list_agreements(transaction_id: str | None = None, request: Request = None):
    svc = get_service(request)
    if transaction_id:
        agr = await svc.get_by_transaction(transaction_id)
        return [agr] if agr else []
    return []


@router.get("/{agreement_id}")
async def get_agreement(agreement_id: str, request: Request):
    svc = get_service(request)
    agr = await svc.get(agreement_id)
    if agr is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    # build AgreementView (simplified)
    return {"agreement_id": agr.agreement_id, "status": agr.status.value,
            "current_version": agr.current_version}


@router.get("/{agreement_id}/versions")
async def versions(agreement_id: str, request: Request):
    svc = get_service(request)
    vers = await svc.list_versions(agreement_id)
    return [{"version": v.version, "agreement_hash": v.agreement_hash,
             "created_at": v.created_at.isoformat().replace("+00:00", "Z")} for v in vers]


@router.get("/{agreement_id}/document")
async def document(agreement_id: str, version: int | None = None, request: Request = None,
                   authorization: str | None = Header(default=None)):
    svc = get_service(request)
    html_doc = await svc.document(agreement_id, version)
    if html_doc is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_doc, media_type="text/html")


@router.post("/{agreement_id}/approval-token")
async def issue_token(agreement_id: str, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key")):
    svc = get_service(request)
    actor = get_actor(request)
    now = request.app.state.clock()
    async with svc.repo.transaction() as conn:
        raw, record = await svc.issue_buyer_token(conn, agreement_id, actor, now)
        await svc.repo.issue_token(conn, record)
    return {"token": raw, "review_url": f"/agreements/{agreement_id}",
            "expires_at": record.expires_at.isoformat().replace("+00:00", "Z"),
            "agreement_version": record.version,
            "agreement_hash": record.agreement_hash}


@router.post("/{agreement_id}/buyer-decision")
async def buyer_decision(agreement_id: str, body: dict, request: Request,
                        idempotency_key: str = Header(..., alias="Idempotency-Key"),
                        token: str = Header(..., alias="X-Approval-Token")):
    svc = get_service(request)
    actor = get_actor(request)
    now = request.app.state.clock()
    try:
        claims = svc.token_service.verify(token)
    except Exception:
        raise HTTPException(status_code=401, detail={"code": "token_expired"})
    from verifund_contracts.models import BuyerApprovalDecision
    req = ...  # parse body into BuyerAgreementApprovalDecision
    async with svc.repo.transaction() as conn:
        agreement = await svc.record_buyer_decision(
            conn, agreement_id, claims, req, actor, now)
    return {"status": agreement.status.value, "version": agreement.current_version}


@router.post("/{agreement_id}/seller-decision")
async def seller_decision(agreement_id: str, body: dict, request: Request,
                         idempotency_key: str = Header(..., alias="Idempotency-Key")):
    ...


@router.post("/{agreement_id}/change-requests")
async def create_change_request(agreement_id: str, body: dict, request: Request,
                               idempotency_key: str = Header(..., alias="Idempotency-Key")):
    ...


@router.post("/{agreement_id}/change-requests/{cr_id}/resolve")
async def resolve_change_request(agreement_id: str, cr_id: str, body: dict, request: Request,
                                idempotency_key: str = Header(..., alias="Idempotency-Key")):
    ...
```

The plan shows the route skeleton; implementers fill in body parsing using the contract models. The full view building (AgreementView) is deferred to a helper `build_agreement_view(agreement, repo)`.

- [ ] **Step 3: Wire into `app.py`.**

```python
# in create_app, after repo creation:
from verifund_control_plane.agreements.repository import AgreementRepository
from verifund_control_plane.agreements.tokens import ApprovalTokenService
from verifund_control_plane.agreements.service import AgreementService
from verifund_control_plane.agreements import routes as agreement_routes

agreement_repo = AgreementRepository(engine)
agreement_tokens = ApprovalTokenService(
    settings.link_secret, ttl_minutes=settings.approval_token_ttl_minutes, clock=now,
)
agreement_service = AgreementService(
    repo=agreement_repo, token_service=agreement_tokens,
    settings=settings, clock=now,
)
...
app.state.agreement_repo = agreement_repo
app.state.agreement_tokens = agreement_tokens
app.state.agreement_service = agreement_service
...
# in lifespan:
await app.state.agreement_repo.create_schema()
...
app.include_router(agreement_routes.router)
```

- [ ] **Step 4: Add settings**

```python
# settings.py additions
agreement_seller_acceptance_hours: int = 24
agreement_buyer_approval_hours: int = 24
agreement_change_response_hours: int = 24
approval_token_ttl_minutes: int = 30
```

- [ ] **Step 5: Run tests and commit.**

Run: `uv run pytest tests/integration/test_agreement_routes.py -v`
Expected: PASS

Commit: `git commit -m "feat(agreements): add HTTP routes and wire into app"`

---

## Phase 2 — Control-plane integration

### Task 2.1: Award creates agreement and transaction atomically

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py` (`award`)
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py` (remove old `agreements`/`agreement_reviews` JSON blobs from `create_schema` path; add `buyer_precheck` column alias; keep `agreement_id` already present)
- Test: `tests/integration/test_verifund_service.py`, `tests/integration/test_verifund_lifecycle.py`

**Interfaces:**
- Consumes: `AgreementService.create_from_award`.
- Produces: `award()` returns `AwardResponse` with `state=AWARDED`, `agreement.status=PENDING_SELLER`, `agreement_version=1`.

- [ ] **Step 1: Update award test expectations** to `PENDING_SELLER` and the new agreement state. Run `uv run pytest tests/integration/test_verifund_service.py -v` to see failures.

- [ ] **Step 2: Refactor `award()`**

Inside `VerifundService.__init__`, accept `agreement_service: AgreementService`. In `app.py`, pass it.

```python
# service.py award() — replace agreement creation block
async def award(self, request: AwardRequest, *, idempotency_key: str | None = None):
    body = request.model_dump(mode="json")
    cached = await self._mutate(...)  # existing idempotency wrapper
    ...
    async with self.repo.transaction() as conn:
        # 1. generate agreement
        agreement = await self.agreement_service.create_from_award(
            conn, request, None, request.run_id, self._now())
        # 2. create transaction with agreement_id
        txn = await self.repo.create_transaction(
            conn, run_id=request.run_id, buyer_id=request.buyer_id,
            seller_id=request.seller_id, offer_id=request.offer_id,
            amount_cents=request.amount_cents, currency=request.currency,
            agreement_id=agreement.agreement_id,
            agreement_version=1, agreement_hash=agreement.current_version_record.agreement_hash,
            state=TransactionState.AWARDED, ...,
        )
        # 3. issue seller token (existing)
        seller_token = await self.tokens.issue(...)
        # 4. idempotency store + commit
        ...
    return AwardResponse(
        transaction_id=txn.transaction_id, state=TransactionState.AWARDED,
        agreement_hash=agreement.current_version_record.agreement_hash,
        agreement=agreement.current_version_record to projection,
        agreement_version=1, seller_token=seller_token, expires_at=...,
    )
```

The projection is built from the agreement version's terms + summary fields. Build it in `AgreementService` and store on the agreement, or construct in `award()` using a helper `build_projection(agreement, version, request)`.

- [ ] **Step 3: Run tests and commit.**

Run: `uv run pytest tests/integration/test_verifund_service.py tests/integration/test_verifund_lifecycle.py -v`
Expected: PASS

Commit: `git commit -m "feat(verifund): create agreement and transaction atomically on award"`

### Task 2.2: Seller decision and non-binding buyer precheck

**Files:**
- Modify: `service.py` (`accept`, `record_buyer_review`)
- Test: `tests/integration/test_verifund_service.py`

- [ ] **Step 1: Update tests** for seller accept not setting `AGREED`; precheck non-binding.

- [ ] **Step 2: Refactor `accept()`**

```python
async def accept(self, request: AcceptRequest, *, idempotency_key):
    ...
    async with self.repo.transaction() as conn:
        agreement = await self.agreement_service.record_seller_decision(
            conn, transaction.agreement_id,
            decision=... (map AcceptRequest to AgreementDecision.ACCEPT),
            actor_type="SELLER_AGENT", actor_id=request.seller_id,
            authority_ref=f"seller-token:{request.seller_task_id}",
            authority_snapshot={}, agreement_version=request.agreement_version
            if hasattr(request, "agreement_version") else transaction.agreement_version,
            agreement_hash=request.agreement_hash,
            verified_offer_hash=request.offer_hash if hasattr(request, "offer_hash") else None,
            note="", idempotency_key=idempotency_key, now=self._now(),
        )
        if agreement.status == AgreementState.REJECTED:
            await self.repo.cancel_transaction(conn, transaction.transaction_id, ...)
        # seller decision projection update
        ...
```

`AcceptRequest` is extended in Task 0.3 with `agreement_version`, `agreement_hash`, `offer_hash`, `actor_type`, `actor_id`, `authority_ref`, `authority_snapshot`. Make them optional with defaults for the compatibility wrapper.

- [ ] **Step 3: Refactor `record_buyer_review()`** to store `buyer_precheck` (rename column) only; never set `AGREED`.

```python
async def record_buyer_review(self, request: BuyerAgreementReviewRequest, ...):
    ...
    async with self.repo.transaction() as conn:
        await self.repo.update_transaction(conn, transaction_id,
            buyer_precheck=request.model_dump(mode="json"))
        await self.repo.append_event(conn, EventInput(type="buyer.precheck", ...))
    return BuyerAgreementResponse(... state=transaction.state (unchanged AWARDED) ...)
```

- [ ] **Step 4: Run tests and commit.**

Run: `uv run pytest tests/integration/test_verifund_service.py -v`
Expected: PASS

Commit: `git commit -m "feat(verifund): delegate seller decision; make buyer review a precheck"`

### Task 2.3: Buyer decision and token issuance

**Files:**
- Modify: `service.py` (add `issue_approval_token`, `record_buyer_decision`, `get_agreement`, `list_agreement_versions`, `get_agreement_document`, `create_change_request`, `resolve_change_request`)
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/checkout.py`
- Test: `tests/integration/test_agreement_routes.py`

Already covered by Task 1.7 routes calling `AgreementService`. Ensure `VerifundService` delegates to `AgreementService` for these and wraps in idempotency. Add thin wrappers:

```python
async def issue_approval_token(self, agreement_id, actor, idempotency_key):
    now = self._now()
    async with self.repo.transaction() as conn:
        raw, record = await self.agreement_service.issue_buyer_token(conn, agreement_id, actor, now)
        await self.repo... # already issued in issue_buyer_token
    return raw, record
```

Note: `issue_buyer_token` in `AgreementService` already calls `repo.issue_token`. Keep one call.

- [ ] Run tests and commit.

### Task 2.4: Funding authorization and funding binding

**Files:**
- Modify: `service.py` (`approve`, `fund`)
- Test: `tests/integration/test_verifund_funding.py`, `tests/integration/test_verifund_service.py`

- [ ] **Step 1: Update tests** for `agreement_version` on `ApproveRequest`/`FundRequest`.

- [ ] **Step 2: Add binding checks in `approve()` and `fund()`**

```python
async def approve(self, request: ApproveRequest, ...):
    ...
    agreement = await self.agreement_service.get_by_transaction(transaction.transaction_id)
    await self.agreement_service.verify_funding_binding(
        agreement, transaction, request.agreement_version, request.agreement_hash)
    # existing funding approval logic, now also stores agreement_version/hash on the approval record
    ...

async def fund(self, request: FundRequest, ...):
    ...
    agreement = await self.agreement_service.get_by_transaction(transaction.transaction_id)
    await self.agreement_service.verify_funding_binding(
        agreement, transaction, request.agreement_version, request.agreement_hash)
    # existing fund logic
    ...
```

- [ ] **Step 3: Run tests and commit.**

Run: `uv run pytest tests/integration/test_verifund_funding.py tests/integration/test_verifund_service.py -v`
Expected: PASS

Commit: `git commit -m "feat(verifund): bind funding approval and funding to agreed version"`

### Task 2.5: Expiry reconciler and termination

**Files:**
- Modify: `reconciler.py`
- Modify: `service.py` (`cancel`)
- Test: `tests/integration/test_verifund_reconciler.py`, `tests/integration/test_agreement_expiry.py`

- [ ] **Step 1: Write failing test** for stale agreement → `EXPIRED`, transaction canceled, token revoked.

- [ ] **Step 2: Wire `AgreementService.expire_due`** into the reconciler's existing sweep cadence. Add a funding-expiry path that calls `AgreementService.terminate()`.

```python
# reconciler.py — add to sweep
expired = await self.service.agreement_service.expire_due(self.clock())
for aid in expired:
    agr = await self.service.agreement_service.get(aid)
    if agr and agr.transaction_id:
        txn = await self.repo.get_transaction(agr.transaction_id)
        if txn and txn.state not in (TransactionState.FUNDED, ...):
            await self.service.cancel_transaction(agr.transaction_id, reason=CancelReason.AGREEMENT_EXPIRED)
```

Lazy expiry: in `AgreementService.record_seller_decision` and `record_buyer_decision`, call `expire_due` for the specific agreement if `expires_at <= now` before proceeding (or rely on `repo.expire` conditional update). Implement a helper `_ensure_not_expired(conn, agreement, now)` that calls `repo.expire` + event + revoke + cancel if expired, then raises `AgreementError("agreement_expired", ...)`.

- [ ] **Step 3: Update `cancel()`** to map: if agreement status is pre-agreement (`PENDING_*`/`CHANGES_REQUESTED`) → `REJECTED` + cancel transaction; if `AGREED` → `TERMINATED` + cancel transaction.

- [ ] **Step 4: Run tests and commit.**

Run: `uv run pytest tests/integration/test_verifund_reconciler.py tests/integration/test_agreement_expiry.py -v`
Expected: PASS

Commit: `git commit -m "feat(verifund): add agreement expiry and termination"`

### Task 2.6: Cancellation mapping and legacy table cleanup

**Files:**
- Modify: `repository.py` (remove old `agreements`/`agreement_reviews` JSON tables; rename `buyer_agent_review` to `buyer_precheck`)
- Modify: tests referencing removed tables/columns.

- [ ] **Step 1: Update schema.** Remove the old `agreements` and `agreement_reviews` Table definitions; rename column `buyer_agent_review` → `buyer_precheck`. Add `agreement_id` index (already present).

- [ ] **Step 2: Update all code/tests** referencing `repo.agreements`, `repo.agreement_reviews`, `buyer_agent_review`. Use grep: `grep -rn "buyer_agent_review\|repo.agreements\|repo.agreement_reviews" --include=*.py`.

- [ ] **Step 3: Run tests and commit.**

Run: `uv run pytest tests/integration/test_verifund_service.py tests/unit/test_verifund_repository.py -v`
Expected: PASS

Commit: `git commit -m "feat(verifund): remove legacy agreement blobs and rename precheck column"`

---

## Phase 3 — Seller agent

### Task 3.1: Seller mandate and profile configuration

**Files:**
- Create: `apps/seller_agent/seller_agent/mandate.py`
- Modify: `apps/seller_agent/seller_agent/profiles/*.yaml`
- Modify: `apps/seller_agent/seller_agent/settings.py`
- Test: `tests/unit/test_seller_mandate.py`

**Interfaces:**
- Produces: `SellerMandate` dataclass + `load_mandate(profile) -> SellerMandate`.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_seller_mandate.py
from seller_agent.mandate import SellerMandate, load_mandate


def test_load_mandate_from_profile():
    profile = {"seller_id": "northwind", "mandate": {
        "version": 1, "auto_accept": True,
        "allowed_currencies": ["USD"], "max_total_cents": 500000,
        "min_warranty_months": 0, "max_warranty_months": 24,
        "min_returns_days": 0, "max_returns_days": 60,
        "max_inspection_period_hours": 72, "max_dispute_window_hours": 168,
    }}
    m = load_mandate(profile)
    assert m.version == 1 and m.auto_accept is True
    assert m.allows(currency="USD", total_cents=100000, warranty_months=12,
                   returns_days=30, inspection_period_hours=48,
                   dispute_window_hours=72) is True
    assert m.allows(total_cents=600000) is False
```

- [ ] **Step 2: Implement `mandate.py`**

```python
# apps/seller_agent/seller_agent/mandate.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SellerMandate:
    version: int = 1
    auto_accept: bool = True
    allowed_currencies: list[str] = field(default_factory=lambda: ["USD"])
    max_total_cents: int = 500000
    min_warranty_months: int = 0
    max_warranty_months: int = 24
    min_returns_days: int = 0
    max_returns_days: int = 60
    max_inspection_period_hours: int = 72
    max_dispute_window_hours: int = 168

    def allows(self, *, currency="USD", total_cents=0, warranty_months=0,
               returns_days=0, inspection_period_hours=0,
               dispute_window_hours=0) -> bool:
        if currency not in self.allowed_currencies:
            return False
        if total_cents > self.max_total_cents:
            return False
        if not (self.min_warranty_months <= warranty_months <= self.max_warranty_months):
            return False
        if not (self.min_returns_days <= returns_days <= self.max_returns_days):
            return False
        if inspection_period_hours > self.max_inspection_period_hours:
            return False
        if dispute_window_hours > self.max_dispute_window_hours:
            return False
        return True


def load_mandate(profile: dict[str, Any]) -> SellerMandate:
    raw = profile.get("mandate") or {}
    return SellerMandate(**{k: v for k, v in raw.items() if k in SellerMandate.__dataclass_fields__})
```

- [ ] **Step 3: Add `mandate` block to each profile YAML.**

- [ ] **Step 4: Run tests and commit.**

### Task 3.2: Agreement verification against offer, digest, and mandate

**Files:**
- Modify: `apps/seller_agent/seller_agent/agreement.py`
- Test: `tests/unit/test_seller_agreement_review.py`

**Interfaces:**
- Consumes: `AgreementProjection`, `Offer` (from store), `SellerMandate`.
- Produces: `AgreementReviewResult` with `status` in {`ACCEPTED`, `REJECTED`, `OPERATOR_REQUIRED`, `CHANGES_REQUESTED`}, plus `offer_hash`, `actor_type`, `actor_id`, `authority_ref`, `authority_snapshot`, `verified_change_request_id`.

- [ ] **Step 1: Update tests** for offer hash recompute, digest verify, mandate evaluation, operator required, change verification.

- [ ] **Step 2: Implement verification**

```python
# apps/seller_agent/seller_agent/agreement.py
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from commerce_core.binding import canonical_offer_binding, offer_hash
from verifund_contracts.models import AgreementReviewDecision, AgreementReviewResult
from seller_agent.mandate import SellerMandate
from seller_agent.agreement_store import SellerAgreementReviewStore


def recompute_offer_hash(offer) -> str:
    return offer_hash(canonical_offer_binding(offer))


def recompute_agreement_hash(projection) -> str:
    from verifund_contracts.models import canonical_json, sha256_hex
    payload = projection.canonical_payload()
    return sha256_hex(canonical_json(payload))


def review_agreement(projection, offer, mandate: SellerMandate,
                     store: SellerAgreementReviewStore, seller_id: str,
                     now: datetime) -> AgreementReviewResult:
    # 1. seller identity
    if projection.seller_id != seller_id:
        return _result(projection, AgreementReviewDecision.REJECTED, "seller_mismatch", now)
    # 2. offer hash
    computed_offer_hash = recompute_offer_hash(offer)
    if computed_offer_hash != projection.offer_hash:
        return _result(projection, AgreementReviewDecision.REJECTED, "offer_mismatch", now,
                       offer_hash=computed_offer_hash)
    # 3. agreement digest
    computed_agreement_hash = recompute_agreement_hash(projection)
    if computed_agreement_hash != projection.agreement_hash:
        return _result(projection, AgreementReviewDecision.REJECTED, "hash_mismatch", now,
                       offer_hash=computed_offer_hash)
    # 4. version provenance
    previous = store.get(projection.agreement_id, projection.agreement_version - 1) if projection.agreement_version > 1 else None
    if projection.agreement_version == 1:
        # terms must match offer-derived terms (checked by control plane; here trust but record)
        pass
    else:
        # apply accepted change request operations to previous terms and compare
        # (implementation: store previous terms + change request; verify digest chain)
        if previous is None:
            return _result(projection, AgreementReviewDecision.REJECTED, "version_provenance_failed", now,
                           offer_hash=computed_offer_hash)
    # 5. mandate
    terms = projection.terms
    totals = terms.get("totals", {})
    if not mandate.allows(
        currency=totals.get("currency", "USD"),
        total_cents=totals.get("total_cents", 0),
        warranty_months=terms.get("warranty_months", 0),
        returns_days=terms.get("returns_days", 0),
        inspection_period_hours=terms.get("inspection", {}).get("period_hours", 0),
        dispute_window_hours=terms.get("dispute_window_hours", 0),
    ):
        if not mandate.auto_accept:
            return _result(projection, AgreementReviewDecision.OPERATOR_REQUIRED, "outside_mandate", now,
                           offer_hash=computed_offer_hash)
        # auto-accept disabled for out-of-mandate even if auto_accept True? spec: auto-accept only inside limits
        return _result(projection, AgreementReviewDecision.OPERATOR_REQUIRED, "outside_mandate", now,
                       offer_hash=computed_offer_hash)
    # 6. accept
    store.record(projection, computed_offer_hash, decision="ACCEPTED", now=now)
    return _result(projection, AgreementReviewDecision.ACCEPTED, None, now,
                   offer_hash=computed_offer_hash, accepted=True)


def _result(projection, status, reason_code, now, *, offer_hash=None, accepted=False,
            verified_change_request_id=None):
    return AgreementReviewResult(
        party="seller", status=status, run_id=projection.run_id,
        transaction_id=projection.transaction_id,
        agreement_version=projection.agreement_version,
        agreement_hash=projection.agreement_hash, offer_hash=offer_hash or "",
        actor_type="SELLER_AGENT", actor_id=projection.seller_id,
        authority_ref=f"seller-mandate:{projection.seller_id}:1",
        authority_snapshot={}, verified_change_request_id=verified_change_request_id,
        task_id="", context_id="", reviewed_at=now,
        reason_code=reason_code, note="",
    )
```

Replace `_result` placeholders with the actual extended fields. Keep `task_id`/`context_id` filled by the caller.

- [ ] **Step 3: Run tests and commit.**

### Task 3.3: Local review store and chain verification

**Files:**
- Create: `apps/seller_agent/seller_agent/agreement_store.py`
- Modify: `apps/seller_agent/seller_agent/store.py` (add `seller_agreement_reviews` table)
- Test: `tests/unit/test_seller_agreement_review.py`

- [ ] **Step 1: Implement store**

```python
# apps/seller_agent/seller_agent/agreement_store.py
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


class SellerAgreementReviewStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_schema()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _ensure_schema(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS seller_agreement_reviews (
                agreement_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                agreement_hash TEXT NOT NULL,
                offer_hash TEXT NOT NULL,
                terms TEXT NOT NULL,
                change_request_id TEXT,
                decision TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                PRIMARY KEY (agreement_id, version)
            )""")

    def record(self, agreement_id, version, agreement_hash, offer_hash, terms, change_request_id, decision, reviewed_at):
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO seller_agreement_reviews VALUES (?,?,?,?,?,?,?,?)",
                (agreement_id, version, agreement_hash, offer_hash,
                 json.dumps(terms, sort_keys=True), change_request_id, decision,
                 reviewed_at.isoformat().replace("+00:00", "Z")),
            )

    def get(self, agreement_id, version):
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM seller_agreement_reviews WHERE agreement_id=? AND version=?",
                (agreement_id, version),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list(self, agreement_id):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM seller_agreement_reviews WHERE agreement_id=? ORDER BY version",
                (agreement_id,),
            ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 2: Run tests and commit.**

### Task 3.4: Seller graph and A2A result integration

**Files:**
- Modify: `apps/seller_agent/seller_agent/graph.py`
- Modify: `apps/seller_agent/seller_agent/service.py`
- Test: `tests/unit/test_seller_agreement_review.py`, `tests/protocol/test_seller_negotiation.py`

- [ ] **Step 1: Update the seller review node** to pass the full projection to `review_agreement`, fill `task_id`/`context_id` from the A2A request, and return the extended `AgreementReviewResult` via `wrap_agreement_review_result`.

- [ ] **Step 2: Handle `OPERATOR_REQUIRED`** by returning a result with status `OPERATOR_REQUIRED` (no decision row; control plane keeps `PENDING_SELLER`).

- [ ] **Step 3: Run tests and commit.**

---

## Phase 4 — Buyer agent

### Task 4.1: Settlement client agreement methods

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/settlement_client.py`
- Test: `tests/unit/test_buyer_settlement_client.py`

**Interfaces:**
- Produces: `BuyerSettlementClient.get_agreement`, `get_agreement_versions`, `get_agreement_document`, `issue_approval_token`, `record_seller_decision`, `precheck`, `buyer_decision`, plus existing methods now accept `agreement_version`/`agreement_hash`.

- [ ] **Step 1: Add methods** matching the control-plane endpoints:

```python
async def get_agreement(self, agreement_id: str) -> dict: ...
async def get_agreement_by_transaction(self, transaction_id: str) -> dict: ...
async def get_agreement_versions(self, agreement_id: str) -> list[dict]: ...
async def get_agreement_document(self, agreement_id: str, version: int | None = None) -> str: ...
async def issue_approval_token(self, agreement_id: str) -> dict: ...
async def record_seller_decision(self, agreement_id: str, payload: dict) -> dict: ...
async def precheck(self, transaction_id: str, agreement: dict) -> dict: ...
async def buyer_decision(self, agreement_id: str, token: str, payload: dict) -> dict: ...
```

Each uses the existing httpx client and `X-Actor-*` headers defaulting to `demo-buyer`/`buyer`.

- [ ] **Step 2: Run tests and commit.**

### Task 4.2: Buyer agreement service methods and funding binding

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/agreement_service.py`
- Test: `tests/unit/test_buyer_agreement_service.py` (create)

**Interfaces:**
- Produces: `get_agreement`, `record_seller_decision`, `precheck`, `issue_approval_token`, `buyer_decision`, `verify_funding_binding`.

- [ ] **Step 1: Add methods**

```python
class BuyerAgreementService:
    def __init__(self, client):
        self.client = client

    async def get_agreement(self, agreement_id: str):
        return await self.client.get_agreement(agreement_id)

    async def record_seller_decision(self, agreement_id: str, result):
        payload = {
            "agreement_version": result.agreement_version,
            "agreement_hash": result.agreement_hash,
            "decision": result.status.value.upper() if hasattr(result.status, "value") else str(result.status),
            "actor_type": result.actor_type,
            "actor_id": result.actor_id,
            "authority_ref": result.authority_ref,
            "authority_snapshot": result.authority_snapshot,
            "verified_offer_hash": result.offer_hash,
            "verified_change_request_id": result.verified_change_request_id,
            "note": result.note,
            "idempotency_key": f"seller-decision:{agreement_id}:{result.agreement_version}",
        }
        return await self.client.record_seller_decision(agreement_id, payload)

    async def precheck(self, transaction_id: str, agreement: dict) -> dict:
        return await self.client.precheck(transaction_id, {"agreement": agreement})

    async def issue_approval_token(self, agreement_id: str) -> dict:
        return await self.client.issue_approval_token(agreement_id)

    async def buyer_decision(self, agreement_id: str, token: str, decision, note="", change_set=None):
        payload = {
            "agreement_version": decision.agreement_version,
            "agreement_hash": decision.agreement_hash,
            "decision": decision.decision.value,
            "note": note,
            "change_set": change_set.model_dump(mode="json") if change_set else None,
            "idempotency_key": f"buyer-decision:{agreement_id}:{decision.agreement_version}",
        }
        return await self.client.buyer_decision(agreement_id, token, payload)
```

- [ ] **Step 2: Update funding approval and fund calls** to pass `agreement_version` and `agreement_hash` from the settlement store (already there).

- [ ] **Step 3: Run tests and commit.**

### Task 4.3: Graph reorder — seller → precheck → buyer → funding

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/graph.py`
- Test: `tests/unit/test_buyer_agreement_checkpoints.py`, `tests/unit/test_buyer_graph.py`

- [ ] **Step 1: Update tests** for the new order and checkpoint names.

- [ ] **Step 2: Reorder nodes**

Remove the node that calls `record_buyer_review` as an acceptance step before seller review. After `await_seller_review` (which receives the seller result and calls `record_seller_decision`), add:

```python
async def precheck_node(state):
    agreement = await agreement_service.get_agreement(state["agreement_id"])
    result = await agreement_service.precheck(state["transaction_id"], agreement)
    state["buyer_precheck"] = result
    return state

async def await_buyer_approval(state):
    # interrupt with agreement + review URL + precheck recommendation
    agreement = await agreement_service.get_agreement(state["agreement_id"])
    token_resp = await agreement_service.issue_approval_token(state["agreement_id"])
    interrupt_payload = {
        "checkpoint": "buyer_approval_required",
        "agreement": agreement,
        "review_url": token_resp["review_url"],
        "version": agreement["current_version"],
        "digest": agreement["agreement_hash"][:12],
        "seller_decision": state.get("seller_review_result"),
        "precheck": state.get("buyer_precheck"),
    }
    decision = interrupt(interrupt_payload)  # LangGraph interrupt
    # on resume, verify AGREED via control plane before proceeding
    refreshed = await agreement_service.get_agreement(state["agreement_id"])
    if refreshed["status"] != "AGREED":
        raise ValueError("agreement not agreed")
    state["agreement_status"] = refreshed["status"]
    return state
```

Route `await_buyer_approval` only after seller accept; on seller reject → finalize (canceled).

- [ ] **Step 3: Run tests and commit.**

### Task 4.4: Extended seller review envelope parsing

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/review.py`
- Test: `tests/protocol/test_buyer_agreement_review.py`

- [ ] **Step 1: Parse the extended fields** (`offer_hash`, `actor_type`, `actor_id`, `authority_ref`, `authority_snapshot`, `verified_change_request_id`) from `AgreementReviewResult` and store them on the settlement record.

- [ ] **Step 2: Run tests and commit.**

---

## Phase 5 — Verifund agent and orchestrator

### Task 5.1: Verifund graph reorder and `sync_agreement`

**Files:**
- Modify: `apps/verifund_agent/verifund_agent/graph.py`
- Modify: `apps/verifund_agent/verifund_agent/client.py`
- Test: `tests/unit/test_verifund_agent_graph.py`

**Interfaces:**
- Produces: nodes `create_agreement`, `sync_agreement`, `await_seller_review`, `await_buyer_approval`, `await_change_resolution`, `await_funding_approval`, `fund_transaction`, `purchase_order`, `evidence`, `release`, `receipt`, `finalize`; checkpoints `BUYER_APPROVAL_REQUIRED`, `SELLER_OPERATOR_REQUIRED`, `AGREEMENT_CHANGES_REQUESTED`.

- [ ] **Step 1: Update tests** for new order and checkpoints.

- [ ] **Step 2: Reorder and add sync router**

```python
def sync_agreement(state):
    agreement = client.get_agreement(state["agreement_id"])  # buyer internal
    status = agreement["status"]
    route = {
        "PENDING_SELLER": "await_seller_review",
        "PENDING_BUYER": "await_buyer_approval",
        "CHANGES_REQUESTED": "await_change_resolution",
        "AGREED": "await_funding_approval",
    }.get(status, "finalize")
    state["_next"] = route
    return state
```

`await_buyer_approval` node:
- call buyer internal precheck before interrupt;
- interrupt payload includes agreement, review_url, version, digest prefix, seller decision, precheck recommendation;
- on resume, re-read control plane and require `AGREED`.

`await_change_resolution` node:
- interrupt with `AGREEMENT_CHANGES_REQUESTED`;
- on resume, re-read agreement; if new version → `await_seller_review`; if rejected change → pending stage.

- [ ] **Step 3: Run tests and commit.**

### Task 5.2: Verifund service/client agreement reads

**Files:**
- Modify: `apps/verifund_agent/verifund_agent/service.py`
- Modify: `apps/verifund_agent/verifund_agent/client.py`
- Test: `tests/unit/test_verifund_agent_service.py`

- [ ] **Step 1: Add `get_agreement`, `resume_agreement`** to the service, and `get_agreement` to the buyer internal client (HTTP GET to buyer's internal agreement proxy).

- [ ] **Step 2: Run tests and commit.**

### Task 5.3: Orchestrator seller → buyer → funding lifecycle

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/verifund.py`
- Test: `tests/unit/test_orchestrator_verifund.py`

- [ ] **Step 1: Update tests** for seller → buyer → funding order and resume binding.

- [ ] **Step 2: Rewrite `start()` and add `resume_agreement()`**

```python
async def start(self, handle, award_payload):
    # expects SELLER_REVIEW_REQUIRED
    seller_result = await self._seller_review(handle, award_payload)
    await self.verifund.record_seller_decision(handle, seller_result)
    # now expects BUYER_APPROVAL_REQUIRED
    view = self._view(handle)
    view["agreement_review"] = {
        "review_url": ...,
        "version": ...,
        "digest": ...,
        "seller_decision": seller_result,
        "precheck": ...,
    }
    return view

async def resume_agreement(self, handle, decision: BuyerAgreementApprovalDecision):
    await self.verifund.resume(handle, checkpoint="buyer_approval_required", value=decision.model_dump(mode="json"))
    # require AGREED from control plane before proceeding
    agreement = await self.verifund.get_agreement(handle)
    if agreement["status"] != "AGREED":
        raise ValueError("agreement not agreed")
    return self._view(handle)
```

`_view()` exposes `agreement_review` with review_url, version, digest, seller decision, precheck.

Funding HITL args already carry `agreement_version` and `agreement_hash`; ensure `verifund_fund` passes them.

- [ ] **Step 3: Run tests and commit.**

### Task 5.4: Orchestrator instructions and review card

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py`
- Test: `tests/unit/test_orchestrator_mediation.py` (smoke)

- [ ] **Step 1: Update instructions**: present an agreement review card with a link; never ask for agreement approval in chat; keep funding as a blocking HITL tool.

- [ ] **Step 2: Register frontend tool** `show_agreement_review` (non-blocking) in the console (Task 6.3) and pass version/digest.

- [ ] **Step 3: Run tests and commit.**

---

## Phase 6 — Console

### Task 6.1: Control-plane client and types

**Files:**
- Modify: `apps/console/lib/api.ts` (or the control-plane client module)
- Modify: `apps/console/lib/types.ts`
- Test: `apps/console` vitest

- [ ] **Step 1: Locate the existing control-plane client** (`grep -rn "getTransaction\|issueApprovalToken\|controlPlane" apps/console/lib`).

- [ ] **Step 2: Add methods** `getAgreement`, `getAgreementVersions`, `getAgreementDocument`, `issueApprovalToken`, `buyerDecision`, `sellerDecision`, `createChangeRequest`, `resolveChangeRequest`.

- [ ] **Step 3: Add types** for `AgreementView`, `AgreementVersionView`, etc. mirroring `verifund_contracts`.

- [ ] **Step 4: Run typecheck and commit.**

Run: `cd apps/console && pnpm run typecheck`

### Task 6.2: Agreement review page and server actions

**Files:**
- Create: `apps/console/app/agreements/[id]/page.tsx`
- Create: `apps/console/app/agreements/[id]/actions.ts`
- Create: `apps/console/features/agreements/AgreementDocument.tsx`
- Create: `apps/console/features/agreements/AgreementSummary.tsx`
- Create: `apps/console/features/agreements/ApprovalActions.tsx`
- Create: `apps/console/features/agreements/VersionHistory.tsx`
- Test: `apps/console/features/agreements/*.test.tsx`

- [ ] **Step 1: Write failing component tests** for rendering version, digest, totals, terms, seller decision, precheck, stale digest disabling approval.

- [ ] **Step 2: Implement page** (server component) fetching the agreement via the control-plane client and rendering the subcomponents.

- [ ] **Step 3: Implement server actions** in `actions.ts`:
  - `approveAgreement(id, version, hash, note, idempotencyKey)`:
    - issue token server-side;
    - call `buyerDecision` with the token;
    - call orchestrator `resume_agreement`;
    - on resume failure, return `{ decisionRecorded: true, resumeError }`.
  - `rejectAgreement`, `requestChangesAgreement` similarly.
  - External-link mode: accept token from URL query, consume on decision, set `Referrer-Policy: no-referrer`.

- [ ] **Step 4: Run tests and commit.**

Run: `cd apps/console && pnpm test`

### Task 6.3: Chat agreement card and checkpoint labels

**Files:**
- Modify: `apps/console/features/chat/verifund-tools.tsx`
- Modify: `apps/console/features/chat/chat.tsx`
- Test: `apps/console/features/chat/verifund-tools.test.tsx`

- [ ] **Step 1: Add checkpoint labels** for `buyer_approval_required`, `agreement_changes_requested`, `seller_operator_required`.

- [ ] **Step 2: Add `AgreementApprovalCard`** (version, total, digest prefix, seller decision, precheck recommendation, "Review agreement" link). Render it when the orchestrator emits `show_agreement_review` (non-blocking frontend tool).

- [ ] **Step 3: Add non-blocking frontend tool** `show_agreement_review` via `useCopilotAction` with `renderInChat`/manual render; it must not call the control plane.

- [ ] **Step 4: Run tests and commit.**

### Task 6.4: Funding card version/digest binding

**Files:**
- Modify: `apps/console/features/chat/chat.tsx`
- Test: `apps/console/features/chat/verifund-tools.test.tsx`

- [ ] **Step 1: Display version and digest** in the existing funding HITL card; pass them through to `request_verifund_funding_approval`.

- [ ] **Step 2: Run tests and commit.**

---

## Phase 7 — Reset, docs, and verification

### Task 7.1: Clean database reset

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py` (create_schema)
- Docs: `docs/workflow.md`

- [ ] **Step 1: Ensure `create_schema`** creates all new tables (existing `Repository` for transactions/events + `AgreementRepository` for agreement tables). Delete `data/verifund.db*` and re-seed.

```bash
rm -f data/verifund.db data/verifund.db-wal data/verifund.db-shm
uv run python scripts/seed.py
```

- [ ] **Step 2: Run `make test`.**

### Task 7.2: Workflow documentation

**Files:**
- Modify: `docs/workflow.md`

- [ ] **Step 1: Update lifecycle** to seller → buyer → funding, approval separation, version chain, invariants, `can_start_funding`.

- [ ] **Step 2: Commit.**

### Task 7.3: Full focused verification

- [ ] **Step 1: Run `make test`.**
- [ ] **Step 2: Run `make lint`.**
- [ ] **Step 3: Run `cd apps/console && pnpm test`.**
- [ ] **Step 4: Fix any failures.**
- [ ] **Step 5: Commit final.**

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-30-verifund-agreement-management.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
