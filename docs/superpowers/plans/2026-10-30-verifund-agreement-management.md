# Verifund Agreement Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement agreement management: deterministic itemized goods agreements, separate seller/buyer/funding approvals, immutable versioning with structured change requests, per-stage expiry, seller mandate, and three approval surfaces.

**Architecture:** Add an `agreements/` package inside `verifund_control_plane` as the sole authority for agreement state (modular monolith, same process and SQLite DB). Extend shared contracts in `verifund_contracts` and `commerce_core`. Reorder the Verifund lifecycle to seller → buyer → funding. Add a console review page and a non-blocking chat card. Clean schema reset; no migrations.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, SQLite, Pydantic, LangGraph, Next.js 15, CopilotKit, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-10-30-verifund-agreement-management-design.md`

## Global Constraints

- Clean DB reset only. No migration code. Delete `data/verifund.db*` before running.
- No backward-compatible A2A envelopes; bump `VERIFUND_SCHEMA_BASE` to `/v2`.
- All timestamps UTC ISO-8601 with `Z`.
- Money in integer cents.
- `Idempotency-Key` required on every mutating endpoint.
- No LLM in agreement generation, validation, or term application.
- Approval tokens never stored in plaintext and never logged.
- Demo `ActorContext` only; Clerk is a later milestone.
- YAGNI: goods v1 only, HTML artifact only, no messaging delivery.

---

## Phase 0 — Shared contracts and offer binding

### Task 0.1: Extend `Offer` with tax and fees

**Files:**
- Modify: `packages/commerce_core/commerce_core/contracts.py`
- Test: `tests/unit/test_commerce_contracts.py` (create if missing)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_commerce_contracts.py
from commerce_core.contracts import Offer, OfferLineItem, OfferTerms, Currency, OfferStatus
from datetime import datetime, timedelta

def test_offer_total_includes_tax_and_fees():
    item = OfferLineItem(sku="S", name="N", quantity=2, unit_price_cents=1000,
                         list_unit_price_cents=1200)
    offer = Offer(
        offer_id="o1", request_id="r1", seller_id="s1", seller_name="S",
        seller_rating=4.5, currency=Currency.USD, line_items=[item],
        subtotal_cents=2000, shipping_cents=300, tax_cents=150, fees_cents=50,
        total_cents=2500, delivery_days=3, valid_until=datetime.now() + timedelta(hours=1),
    )
    assert offer.total_cents == 2500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_commerce_contracts.py -v`
Expected: FAIL — `tax_cents` unknown field.

- [ ] **Step 3: Implement**

```python
# packages/commerce_core/commerce_core/contracts.py
class Offer(CommerceModel):
    ...
    subtotal_cents: int = Field(ge=0)
    shipping_cents: int = Field(default=0, ge=0)
    tax_cents: int = Field(default=0, ge=0)
    fees_cents: int = Field(default=0, ge=0)
    total_cents: int = Field(ge=0)
    ...

    @model_validator(mode="after")
    def validate_totals(self) -> "Offer":
        computed = 0
        for item in self.line_items:
            ...
            computed += (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
        if computed != self.subtotal_cents:
            raise ValueError("subtotal_cents does not match line items")
        if self.total_cents != self.subtotal_cents + self.shipping_cents + self.tax_cents + self.fees_cents:
            raise ValueError("total_cents does not match subtotal, shipping, tax, and fees")
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_commerce_contracts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/contracts.py tests/unit/test_commerce_contracts.py
git commit -m "feat(commerce): add tax_cents and fees_cents to Offer"
```

### Task 0.2: Add canonical offer binding helpers

**Files:**
- Modify: `packages/commerce_core/commerce_core/contracts.py`
- Modify: `packages/commerce_core/commerce_core/__init__.py` (if exports)
- Test: `tests/unit/test_offer_binding.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_offer_binding.py
from commerce_core.contracts import Offer, OfferLineItem, Currency, canonical_offer_binding, offer_hash, binding_from_award
from verifund_contracts.models import AwardRequest, AwardLineItem
from datetime import datetime, timedelta

def _offer():
    item = OfferLineItem(sku="S", name="N", quantity=2, unit_price_cents=1000,
                         list_unit_price_cents=1200)
    return Offer(
        offer_id="o1", request_id="r1", seller_id="s1", seller_name="S",
        seller_rating=4.5, currency=Currency.USD, line_items=[item],
        subtotal_cents=2000, shipping_cents=300, tax_cents=150, fees_cents=50,
        total_cents=2500, delivery_days=3, warranty_months=12, returns_days=30,
        valid_until=datetime.now() + timedelta(hours=1), round=2,
    )

def test_offer_hash_stable_across_mutable_fields():
    a = _offer()
    b = _offer()
    b.status = OfferStatus.ACCEPTED if False else b.status
    b.rationale = "changed"
    assert offer_hash(canonical_offer_binding(a)) == offer_hash(canonical_offer_binding(b))

def test_binding_from_award_matches_offer_hash():
    offer = _offer()
    award = AwardRequest(
        run_id="run1", buyer_id="b1", seller_id="s1", offer_id="o1",
        currency="USD", amount_cents=2500, shipping_cents=300, quantity=2,
        line_items=[AwardLineItem(sku="S", name="N", quantity=2,
                                 unit_price_cents=1000, warranty_addon_cents=0)],
        delivery_days=3, warranty_months=12, returns_days=30,
        request_id="r1", offer_round=2, offer_hash=offer_hash(canonical_offer_binding(offer)),
        offer_valid_until=offer.valid_until,
        tax_cents=150, fees_cents=50,
    )
    assert binding_from_award(award) == canonical_offer_binding(offer)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_offer_binding.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add to `contracts.py`:

```python
import hashlib, json

def _binding_dict(offer_or_award) -> dict:
    # normalize either Offer or AwardRequest into the binding shape
    ...

def canonical_offer_binding(offer: Offer) -> dict:
    return {
        "offer_id": offer.offer_id,
        "request_id": offer.request_id,
        "seller_id": offer.seller_id,
        "currency": offer.currency.value,
        "round": offer.round,
        "line_items": [
            {
                "sku": li.sku,
                "name": li.name,
                "quantity": li.quantity,
                "unit_price_cents": li.unit_price_cents,
                "warranty_addon_cents": li.warranty_addon_cents,
            } for li in offer.line_items
        ],
        "subtotal_cents": offer.subtotal_cents,
        "shipping_cents": offer.shipping_cents,
        "tax_cents": offer.tax_cents,
        "fees_cents": offer.fees_cents,
        "total_cents": offer.total_cents,
        "delivery_days": offer.delivery_days,
        "warranty_months": offer.warranty_months,
        "returns_days": offer.returns_days,
        "offer_valid_until": offer.valid_until.astimezone(timezone.utc).isoformat().replace("+00:00","Z"),
    }

def binding_from_award(award: AwardRequest) -> dict:
    return {
        "offer_id": award.offer_id,
        "request_id": award.request_id,
        "seller_id": award.seller_id,
        "currency": award.currency,
        "round": award.offer_round,
        "line_items": [
            {
                "sku": li.sku,
                "name": li.name,
                "quantity": li.quantity,
                "unit_price_cents": li.unit_price_cents,
                "warranty_addon_cents": li.warranty_addon_cents,
            } for li in award.line_items
        ],
        "subtotal_cents": sum((li.unit_price_cents + li.warranty_addon_cents) * li.quantity for li in award.line_items),
        "shipping_cents": award.shipping_cents,
        "tax_cents": award.tax_cents,
        "fees_cents": award.fees_cents,
        "total_cents": award.amount_cents,
        "delivery_days": award.delivery_days,
        "warranty_months": award.warranty_months,
        "returns_days": award.returns_days,
        "offer_valid_until": award.offer_valid_until.astimezone(timezone.utc).isoformat().replace("+00:00","Z"),
    }

def offer_hash(binding: dict) -> str:
    return sha256_hex(canonical_json(binding))
```

Import `OfferStatus` in the test; ensure `canonical_json`/`sha256_hex` from verifund_contracts or define locally. Since commerce_core shouldn't depend on verifund_contracts, define the canonical JSON helper in commerce_core (or use json.dumps). Use a local `_canonical`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_offer_binding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/contracts.py tests/unit/test_offer_binding.py
git commit -m "feat(commerce): add canonical offer binding and offer_hash"
```

### Task 0.3: Extend verifund_contracts models

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/models.py`
- Modify: `packages/verifund_contracts/verifund_contracts/a2a.py`
- Test: `tests/unit/test_verifund_contracts.py`

- [ ] **Step 1: Add `AgreementState`, `AgreementDecision`, `BuyerApprovalDecision`, `RemedyPolicy` enums and `ChangeOperation`/`ChangeSet`/`ApprovalTokenResponse`/`AgreementView` models.**
- [ ] **Step 2: Extend `AgreementProjection` with new fields + `canonical_payload()` returning the digest envelope.**
- [ ] **Step 3: Extend `AwardRequest`, `ApproveRequest`, `FundRequest`.**
- [ ] **Step 4: Add `AgreementReviewDecision` members `OPERATOR_REQUIRED`, `CHANGES_REQUESTED` (in models.py).**
- [ ] **Step 5: Extend `AgreementReviewResult` in a2a.py.**
- [ ] **Step 6: Add checkpoints and `BuyerAgreementApprovalDecision` in a2a.py; bump schema base to `/v2`.**
- [ ] **Step 7: Run tests and commit.**

(Implementation follows the spec §9.2 exactly; code mirrors the field lists. The existing test file will need fixture updates; keep `agreement_hash` field name.)

```bash
git commit -m "feat(contracts): add agreement state, versioning, and binding fields"
```

---

## Phase 1 — Control-plane agreement package

### Task 1.1: Package skeleton, models, state machine

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/agreements/__init__.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/agreements/models.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/agreements/states.py`
- Test: `tests/unit/test_agreement_states.py`

- [ ] **Step 1: Write the failing test** — transition table allows only documented transitions; terminal states reject all.
- [ ] **Step 2: Implement `models.py`** — dataclasses `Agreement`, `AgreementVersion`, `AgreementDecisionRecord`, `ChangeRequest`, `ApprovalToken`, `AgreementEvent` with `row_version`.
- [ ] **Step 3: Implement `states.py`** — `ALLOWED_AGREEMENT_TRANSITIONS`, `assert_agreement_transition`, `is_terminal`.
- [ ] **Step 4: Run tests, commit.**

```bash
git commit -m "feat(agreements): add domain models and state machine"
```

### Task 1.2: Generator, digest, renderer

**Files:**
- Create: `.../agreements/digest.py`
- Create: `.../agreements/generator.py`
- Create: `.../agreements/renderer.py`
- Test: `tests/unit/test_agreement_generator.py`, `test_agreement_digest.py`, `test_agreement_renderer.py`

- [ ] **Step 1: Write failing tests** for canonical JSON stability, digest version binding, tamper detection, HTML determinism, totals validation.
- [ ] **Step 2: Implement `digest.py`** — `canonical_json`, `sha256_hex`, `agreement_hash(agreement_id, version, terms)`.
- [ ] **Step 3: Implement `generator.py`** — `build_terms(award, now, platform_terms_version)`, `validate_terms`.
- [ ] **Step 4: Implement `renderer.py`** — deterministic HTML template with escaping.
- [ ] **Step 5: Run tests, commit.**

```bash
git commit -m "feat(agreements): add deterministic generator, digest, and HTML renderer"
```

### Task 1.3: Repository

**Files:**
- Create: `.../agreements/repository.py`
- Test: `tests/unit/test_agreement_repository.py`

- [ ] **Step 1: Write failing tests** for create/get/version/decision/change-request/token/events/expiry sweep using a temporary SQLite DB.
- [ ] **Step 2: Implement tables** in `create_schema` (call from existing `Repository.create_schema` or a new `AgreementRepository.create_schema`).
- [ ] **Step 3: Implement methods** listed in spec §11.3, including CAS and partial unique index.
- [ ] **Step 4: Run tests, commit.**

```bash
git commit -m "feat(agreements): add normalized repository and CAS operations"
```

### Task 1.4: Approval tokens

**Files:**
- Create: `.../agreements/tokens.py`
- Test: `tests/unit/test_agreement_tokens.py`

- [ ] **Step 1: Write failing tests** for sign/verify, audience, subject, expiry, single-use, revocation.
- [ ] **Step 2: Implement** issue/verify/consume using `LinkSigner`.
- [ ] **Step 3: Run tests, commit.**

```bash
git commit -m "feat(agreements): add single-use approval tokens"
```

### Task 1.5: Service

**Files:**
- Create: `.../agreements/service.py`
- Test: `tests/unit/test_agreement_service.py`

- [ ] **Step 1: Write failing tests** for create, seller decision, buyer decision, change request, resolve, expire, token consumption.
- [ ] **Step 2: Implement** `create_from_award`, `record_seller_decision`, `issue_approval_token`, `record_buyer_decision`, `create_change_request`, `resolve_change_request`, `expire_due`, `get`, `versions`, `document`.
- [ ] **Step 3: Run tests, commit.**

```bash
git commit -m "feat(agreements): add agreement service orchestration"
```

### Task 1.6: Routes

**Files:**
- Create: `.../agreements/routes.py`
- Modify: `.../app.py` (include router, wire dependencies)
- Test: `tests/integration/test_agreement_routes.py`

- [ ] **Step 1: Write failing tests** for each endpoint (auth, happy path, mismatch, expiry).
- [ ] **Step 2: Implement routes** with `Idempotency-Key` and actor resolution.
- [ ] **Step 3: Wire into `app.py`.**
- [ ] **Step 4: Run tests, commit.**

```bash
git commit -m "feat(agreements): add HTTP routes and wire into app"
```

---

## Phase 2 — Control-plane integration

### Task 2.1: Award integration

**Files:**
- Modify: `.../service.py` (`award`)
- Modify: `.../repository.py` (transaction insert with `agreement_id`)
- Test: `tests/integration/test_verifund_service.py`

- [ ] **Step 1: Update award test expectations** to `PENDING_SELLER` and new agreement state.
- [ ] **Step 2: Refactor `award()`** to call `AgreementService.create_from_award` in the same transaction.
- [ ] **Step 3: Run tests, commit.**

### Task 2.2: Seller decision and buyer precheck

**Files:**
- Modify: `.../service.py` (`accept`, `record_buyer_review`)
- Test: `tests/integration/test_verifund_service.py`

- [ ] **Step 1: Update tests** for seller accept not setting `AGREED`; precheck non-binding.
- [ ] **Step 2: Refactor `accept()`** to delegate to `AgreementService.record_seller_decision`; update transaction only on reject.
- [ ] **Step 3: Refactor `record_buyer_review()`** to store `buyer_precheck` only.
- [ ] **Step 4: Run tests, commit.**

### Task 2.3: Buyer decision and tokens

**Files:**
- Modify: `.../service.py` (add buyer decision + token methods, or delegate to agreements service)
- Test: `tests/integration/test_agreement_routes.py`

Already covered by Task 1.6 routes; ensure service methods are called. Commit with Task 1.6.

### Task 2.4: Funding authorization and funding binding

**Files:**
- Modify: `.../service.py` (`approve`, `fund`)
- Modify: `packages/verifund_contracts/verifund_contracts/models.py` (already in Task 0.3)
- Test: `tests/integration/test_verifund_service.py`

- [ ] **Step 1: Update tests** for `agreement_version` on `ApproveRequest`/`FundRequest`.
- [ ] **Step 2: Add version/digest checks** in `approve()` and `fund()`.
- [ ] **Step 3: Run tests, commit.**

### Task 2.5: Expiry reconciler wiring

**Files:**
- Modify: `.../app.py`
- Modify: `.../reconciler.py`
- Test: `tests/integration/test_expiry.py` (create)

- [ ] **Step 1: Write failing test** for stale agreement → EXPIRED, transaction canceled, token revoked.
- [ ] **Step 2: Wire `AgreementService.expire_due`** into reconciler and add funding-expiry → terminate.
- [ ] **Step 3: Run tests, commit.**

### Task 2.6: Cancel and terminate

**Files:**
- Modify: `.../service.py` (`cancel`)
- Test: `tests/integration/test_verifund_service.py`

- [ ] **Step 1: Update cancel** to map to `REJECTED`/`TERMINATED`.
- [ ] **Step 2: Run tests, commit.**

---

## Phase 3 — Seller agent

### Task 3.1: Mandate profile and loader

**Files:**
- Modify: `apps/seller_agent/seller_agent/profiles/*.yaml`
- Modify: `apps/seller_agent/seller_agent/settings.py` (or a new `mandate.py`)
- Test: `tests/unit/test_seller_mandate.py`

- [ ] **Step 1: Add mandate block** to profiles.
- [ ] **Step 2: Implement loader** returning `SellerMandate`.
- [ ] **Step 3: Run tests, commit.**

### Task 3.2: Agreement review verification

**Files:**
- Modify: `apps/seller_agent/seller_agent/agreement.py`
- Test: `tests/unit/test_seller_agreement_review.py`

- [ ] **Step 1: Update tests** for offer hash recompute, digest verify, mandate evaluation, operator required.
- [ ] **Step 2: Implement** verification and return extended result.
- [ ] **Step 3: Run tests, commit.**

### Task 3.3: Local review store and chain verification

**Files:**
- Modify: `apps/seller_agent/seller_agent/store.py` (or new `agreement_store.py`)
- Modify: `apps/seller_agent/seller_agent/agreement.py`
- Test: `tests/unit/test_seller_agreement_review.py`

- [ ] **Step 1: Add `seller_agreement_reviews` table** to seller DB schema.
- [ ] **Step 2: Store reviewed versions** and verify version `N+1` chains.
- [ ] **Step 3: Run tests, commit.**

---

## Phase 4 — Buyer agent

### Task 4.1: Agreement service methods

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/agreement_service.py`
- Test: `tests/unit/test_buyer_agreement_service.py` (or existing)

- [ ] **Step 1: Add `get_agreement`, `record_seller_decision`, `precheck`.**
- [ ] **Step 2: Update funding approval/funding** to pass version/hash.
- [ ] **Step 3: Run tests, commit.**

### Task 4.2: Graph reorder and precheck

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/graph.py`
- Test: `tests/unit/test_buyer_graph.py`

- [ ] **Step 1: Remove formal buyer review before seller.**
- [ ] **Step 2: Add non-binding precheck node.**
- [ ] **Step 3: Run tests, commit.**

### Task 4.3: Settlement client methods

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/settlement_client.py`
- Test: `tests/unit/test_buyer_settlement_client.py`

- [ ] **Step 1: Add methods** for agreement reads, precheck, seller decisions, buyer decisions, tokens, versions, documents.
- [ ] **Step 2: Run tests, commit.**

### Task 4.4: Review envelope parsing

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/review.py`
- Test: `tests/protocol/test_buyer_agreement_review.py`

- [ ] **Step 1: Parse extended result fields.**
- [ ] **Step 2: Run tests, commit.**

---

## Phase 5 — Verifund agent and orchestrator

### Task 5.1: Graph reorder and checkpoints

**Files:**
- Modify: `apps/verifund_agent/verifund_agent/graph.py`
- Modify: `packages/verifund_contracts/verifund_contracts/a2a.py` (already)
- Test: `tests/unit/test_verifund_agent_graph.py`

- [ ] **Step 1: Update tests** for new order and checkpoints.
- [ ] **Step 2: Reorder nodes** and add `await_change_resolution`.
- [ ] **Step 3: Implement buyer precheck before interrupt.**
- [ ] **Step 4: Run tests, commit.**

### Task 5.2: Sync agreement router

**Files:**
- Modify: `apps/verifund_agent/verifund_agent/graph.py`
- Modify: `apps/verifund_agent/verifund_agent/client.py` (buyer internal client)
- Test: `tests/unit/test_verifund_agent_graph.py`

- [ ] **Step 1: Add `get_agreement` to buyer internal client.**
- [ ] **Step 2: Implement `sync_agreement` router.**
- [ ] **Step 3: Run tests, commit.**

### Task 5.3: Orchestrator lifecycle

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/verifund.py`
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py`
- Test: `tests/unit/test_orchestrator_verifund.py`

- [ ] **Step 1: Update tests** for seller → buyer → funding order.
- [ ] **Step 2: Rewrite `start()`** and add `resume_agreement()`.
- [ ] **Step 3: Update `_view()`** with `agreement_review`.
- [ ] **Step 4: Run tests, commit.**

---

## Phase 6 — Console

### Task 6.1: Control-plane client methods

**Files:**
- Modify: `apps/console/lib/...` (control-plane client; locate existing)
- Test: `apps/console` (vitest)

- [ ] **Step 1: Locate existing client** and add methods.
- [ ] **Step 2: Add `getAgreement`, `issueApprovalToken`, `buyerDecision`, `sellerDecision`, `versions`, `document`.**
- [ ] **Step 3: Run typecheck, commit.**

### Task 6.2: Review page and server actions

**Files:**
- Create: `apps/console/app/agreements/[id]/page.tsx`
- Create: `apps/console/app/agreements/[id]/actions.ts`
- Create: `apps/console/features/agreements/*`
- Test: `apps/console/features/agreements/*.test.tsx`

- [ ] **Step 1: Write failing component tests.**
- [ ] **Step 2: Implement page** rendering version, digest, totals, terms, seller decision, precheck, history.
- [ ] **Step 3: Implement server actions** (issue token at submit, submit decision, resume run, handle external token).
- [ ] **Step 4: Run tests, commit.**

### Task 6.3: Chat card and frontend tool

**Files:**
- Modify: `apps/console/features/chat/verifund-tools.tsx`
- Modify: `apps/console/features/chat/chat.tsx`
- Test: `apps/console/features/chat/verifund-tools.test.tsx`

- [ ] **Step 1: Update tests** for new checkpoint labels.
- [ ] **Step 2: Add `AgreementApprovalCard`** with link.
- [ ] **Step 3: Add non-blocking frontend tool `show_agreement_review`.**
- [ ] **Step 4: Run tests, commit.**

### Task 6.4: Funding card binding

**Files:**
- Modify: `apps/console/features/chat/chat.tsx` (funding HITL args)
- Test: `apps/console/features/chat/verifund-tools.test.tsx`

- [ ] **Step 1: Display version and digest** in the funding card.
- [ ] **Step 2: Pass them through** to `request_verifund_funding_approval`.
- [ ] **Step 3: Run tests, commit.**

---

## Phase 7 — Reset, docs, and verification

### Task 7.1: Clean database reset

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py` (`create_schema`)
- Docs: `docs/workflow.md`

- [ ] **Step 1: Update `create_schema`** with new tables and `transactions.agreement_id`.
- [ ] **Step 2: Delete `data/verifund.db*` and re-seed.**
- [ ] **Step 3: Run `make test`, commit.**

### Task 7.2: Documentation

**Files:**
- Modify: `docs/workflow.md`
- Modify: `docs/verifund-paypal-sandbox.md` (if needed)

- [ ] **Step 1: Update lifecycle diagram and invariants.**
- [ ] **Step 2: Commit.**

### Task 7.3: Full focused test pass

- [ ] **Step 1: Run `make test`.**
- [ ] **Step 2: Run `make lint`.**
- [ ] **Step 3: Run `cd apps/console && pnpm test`.**
- [ ] **Step 4: Fix any failures.**
- [ ] **Step 5: Commit final.**

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-30-verifund-agreement-management.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
