# Verifund Agreement Management — Design

**Status:** Design approved in brainstorm; pending written-spec review
**Date:** 2026-10-30
**Audience:** Implementation team
**Scope:** Agreement generation, consent, versioning, expiry, and buyer approval inside the existing Verifund control plane.

**Related documents:**

- [`verifund-agreement-recommendation.md`](./verifund-agreement-recommendation.md)
- [`verifund-agreement-enhancement.md`](./verifund-agreement-enhancement.md)
- [`2026-10-27-verifund-control-plane-design.md`](./2026-10-27-verifund-control-plane-design.md)
- [`2026-10-28-multi-tenancy-design.md`](./2026-10-28-multi-tenancy-design.md)

---

## 1. Summary

MarketMesh already generates a deterministic agreement at award time and requires a seller review plus a buyer-agent review before funding. That implementation conflates three different acts: accepting a negotiated offer, consenting to a contract, and authorizing payment. It also has no versioning, no change requests, no agreement expiry, and only a thin set of contractual terms.

This design introduces agreement management as a first-class module inside `verifund_control_plane`:

- The agreement is a separate aggregate with its own state machine, independent of transaction settlement state.
- The agreement is generated deterministically from the winning offer, itemized with tax and fees, bound to the exact offer round and hash, and rendered as an immutable HTML artifact.
- Seller acceptance, human buyer approval, and funding authorization are distinct events with separate evidence.
- Any material change creates a new immutable version and invalidates prior consent.
- Unsigned or stale approvals cannot be replayed: buyer approval uses a short-lived, single-use token bound to the agreement version and digest.
- Per-stage deadlines expire stale agreements, and funding is impossible unless the exact approved version is `AGREED`.
- Seller agents may auto-accept only within a configured mandate; otherwise a seller operator must decide.

Clerk-based authentication and full multi-tenancy are deliberately deferred. The agreement module depends on a small `ActorContext` boundary so a Clerk adapter can replace the demo adapter later without changing agreement logic.

---

## 2. Goals and non-goals

### Goals

1. Generate a deterministic, itemized goods agreement from the winning offer.
2. Bind the agreement to the exact negotiated offer (`offer_round`, `offer_hash`).
3. Separate seller acceptance, human buyer approval, and funding authorization.
4. Make agreement state independent from transaction state.
5. Support structured change requests with immutable versions and fresh consent.
6. Enforce per-stage expiry.
7. Enforce seller authority limits.
8. Provide three approval surfaces over one approval service: dedicated page, chat card, signed external link.
9. Produce an auditable HTML agreement artifact and a complete decision history.
10. Block funding unless the exact version and digest were approved.

### Non-goals

- Clerk sign-in, user roles, seller operators, and tenant data isolation.
- PDF generation or formal e-signature.
- WhatsApp/Discord delivery of approval links.
- Services agreements, milestones, subscriptions, multi-currency, or tax calculation.
- Seller-operator console UI or admin console.
- Partial approvals, combined agreement/funding approval, or threshold-based approval.
- Migration of existing `data/verifund.db` data.
- Backward-compatible A2A envelopes.
- An exhaustive adversarial failure matrix, fuzzing, or load testing.

---

## 3. Binding decisions

These decisions were made during the design interview and are not open for reinterpretation without a new design review.

| Topic | Decision |
|---|---|
| Approval separation | Human buyer agreement approval is distinct from funding authorization. |
| Agreement state | Separate `AgreementState`, independent of `TransactionState`. |
| Agreement scope | Goods only now, with `agreement_type` and `terms_version` discriminators. |
| Change handling | Full versioning loop with structured change sets and fresh consent. |
| Interim approval proof | Signed, short-lived, single-use approval tokens; Clerk adapter later. |
| Offer binding | Bind `offer_round` + canonical `offer_hash`, verified by buyer, seller, and control plane. |
| Rendered artifact | Server-rendered HTML stored by version/digest; no PDF or e-signature. |
| Expiry | Per-stage configurable windows with explicit `expires_at`. |
| Data migration | Clean schema reset; no backward compatibility. |
| Seller authority | Seller mandate/limits; agent may auto-accept only within limits. |
| Tax and fees | Explicit `tax_cents` and `fees_cents`; deterministic total. |
| Inspection | Explicit inspection period plus a start event (`DELIVERY_CONFIRMED`). |
| Acceptance order | Seller acceptance → human buyer approval → separate funding authorization. |
| Change representation | Structured change set, not free text; backend regenerates terms deterministically. |
| Service boundary | Modular monolith: `agreements/` package inside `verifund_control_plane`, same process and SQLite DB. |
| Approval surfaces | Dedicated page, chat card, and signed external link; messaging delivery deferred. |
| Definition of done | Full mechanics with focused tests, not the full failure matrix. |

---

## 4. Domain model

### 4.1 Aggregate objects

| Object | Responsibility |
|---|---|
| `Agreement` | Identity, current version, lifecycle state, offer binding, stage deadline, transaction link. |
| `AgreementVersion` | Immutable contractual snapshot: canonical terms, digest, rendered HTML, provenance. |
| `AgreementDecision` | Append-only record of a party's formal act on a version: `ACCEPT`, `REJECT`, or `REQUEST_CHANGES`. |
| `ChangeRequest` | Structured proposal against a base version, with requester, operations, status, and resolution. |
| `ApprovalToken` | Buyer-only, short-lived, single-use proof bound to `(agreement_id, version, digest)`. |
| `AgreementEvent` | Append-only audit event scoped to an agreement. |

The seller mandate is not a control-plane aggregate. It lives in the seller agent profile, and each seller decision records an `authority_snapshot` of the exact limits applied.

### 4.2 States

`AgreementState` has seven values:

```text
PENDING_SELLER
PENDING_BUYER
CHANGES_REQUESTED
AGREED
REJECTED
EXPIRED
TERMINATED
```

There is no persisted `DRAFTED` state. Generation, validation, digesting, and rendering complete before the agreement row is inserted. The first persisted state is `PENDING_SELLER`.

```text
award
  └─> PENDING_SELLER
        ├─ seller ACCEPT ──────────────> PENDING_BUYER
        │                                 ├─ buyer ACCEPT ───> AGREED
        │                                 ├─ buyer REJECT ───> REJECTED
        │                                 └─ buyer REQUEST_CHANGES ─┐
        ├─ seller REJECT ──────────────> REJECTED                 │
        ├─ seller OPERATOR_REQUIRED ───> PENDING_SELLER (flagged)  │
        └─ seller REQUEST_CHANGES ─────> CHANGES_REQUESTED <──────┘
                                             ├─ counterparty ACCEPT_CHANGES
                                             │     └─> new version N+1 ──> PENDING_SELLER
                                             ├─ counterparty REJECT_CHANGES
                                             │     └─> requester's prior pending state
                                             └─ deadline ──> EXPIRED

any non-terminal state + deadline elapsed ──> EXPIRED
AGREED + transaction canceled/funding expired ──> TERMINATED
```

`AGREED` is terminal for consent. Funding, fulfillment, release, and payout do not mutate the agreement. `TERMINATED` records that a contract ended after consent but before or during performance. A successfully released transaction leaves the agreement in `AGREED` as the historical record of the contract that was performed.

### 4.3 Transition table

| From | Event | To | Side effects |
|---|---|---|---|
| `PENDING_SELLER` | Seller `ACCEPT` | `PENDING_BUYER` | Issue buyer stage deadline; record decision; event. |
| `PENDING_SELLER` | Seller `REJECT` | `REJECTED` | Record decision; cancel transaction; event. |
| `PENDING_SELLER` | Seller `OPERATOR_REQUIRED` | `PENDING_SELLER` | Set operator flag; event; no decision row. |
| `PENDING_SELLER` | Seller `REQUEST_CHANGES` | `CHANGES_REQUESTED` | Create change request; set change deadline; event. |
| `PENDING_BUYER` | Buyer `ACCEPT` | `AGREED` | Record decision; transition transaction `AWARDED → AGREED`; set `agreed_at`; event. |
| `PENDING_BUYER` | Buyer `REJECT` | `REJECTED` | Record decision; cancel transaction; event. |
| `PENDING_BUYER` | Buyer `REQUEST_CHANGES` | `CHANGES_REQUESTED` | Create change request; set change deadline; event. |
| `CHANGES_REQUESTED` | Counterparty accepts | `PENDING_SELLER` | Apply operations; append version `N+1`; mark request accepted; set seller deadline; event. |
| `CHANGES_REQUESTED` | Counterparty rejects | requester's prior pending state | Mark request rejected; set a fresh stage deadline; event. |
| any stage-pending state | Deadline elapsed | `EXPIRED` | Mark expired; revoke tokens; cancel transaction if not funded; event. |
| `AGREED` | Transaction canceled or funding expired | `TERMINATED` | Set `terminated_at`; event. |

Terminal states (`REJECTED`, `EXPIRED`, `TERMINATED`) accept no decisions.

### 4.4 Invariants

1. Only the current version accepts decisions.
2. A decision's `agreement_hash` must equal the current version's digest; otherwise `409 hash_mismatch`.
3. Decisions are append-only. At most one decision is effective at a time, enforced by a status/`row_version` compare-and-swap. Duplicate requests are handled by unique idempotency keys. A version may have multiple decision attempts when a change request is rejected.
4. Buyer decisions are legal only in `PENDING_BUYER`; seller decisions only in `PENDING_SELLER`.
5. `AGREED` requires an `ACCEPT` from both parties on the same version.
6. No term mutation without a new version. Version `N+1` always requires two fresh acceptances.
7. Funding requires `status = AGREED`, the current version, and the exact digest presented to the payer.
8. Expiry and rejection are monotonic: once terminal, no decision is accepted.
9. The agreement owns consent and terms; the transaction owns money, evidence, fulfillment, and payout.

---

## 5. Agreement generation

### 5.1 Pipeline

`AgreementService.create_from_award()` is deterministic. No LLM participates.

```text
AwardRequest + seller profile + platform terms config + clock
  → validate_award()
  → recompute offer_hash from the award's commercial fields
  → compare offer_hash / offer_round / offer_valid_until
  → build canonical terms (goods v1)
  → validate_terms()
  → canonical JSON + SHA-256 agreement hash
  → render HTML from the same canonical terms
  → insert Agreement + AgreementVersion in one SQLite transaction
  → emit agreement.created
```

If any step fails, nothing is persisted and the transaction never reaches `AWARDED`.

### 5.2 Offer binding

The hash must be computable by the buyer, seller, and control plane. It covers a defined **`OfferBinding`** projection, not the raw `Offer`:

```text
offer_id
request_id
seller_id
currency
round
line_items[
  sku, name, quantity, unit_price_cents, warranty_addon_cents
]
subtotal_cents
shipping_cents
tax_cents
fees_cents
total_cents
delivery_days
warranty_months
returns_days
offer_valid_until
```

`offer_hash = SHA-256(canonical_json(OfferBinding))`.

Excluded because they are mutable, routing metadata, or non-contractual in goods v1:

```text
status, rationale, seller_name, seller_rating, task_id, context_id,
delivery_date, OfferTerms (sustainability_certified, stock_confidence,
split_shipment, notes)
```

`OfferTerms` is explicitly non-contractual in this iteration. If these fields become contractual later, they must be added to `OfferBinding` and the terms schema, and the terms version must be bumped.

Shared functions in `commerce_core`:

```text
canonical_offer_binding(offer: Offer) -> dict
binding_from_award(award: AwardRequest) -> dict
offer_hash(binding: dict) -> str
```

`AwardRequest` carries the binding fields directly. The control plane recomputes the hash from the award. The seller recomputes it from its stored `Offer`. The hashes must match, or the seller rejects with `offer_mismatch`.

`AwardRequest.amount_cents` is the all-in total. The binding maps it to `total_cents`:

```text
amount_cents = line_total + shipping_cents + tax_cents + fees_cents
```

An award is rejected if `now > offer_valid_until`; the seller re-checks at acceptance.

### 5.3 Canonical terms — goods v1

```json
{
  "schema": "verifund.agreement.v1",
  "agreement_type": "goods",
  "terms_version": 1,
  "platform_terms_version": "v1",
  "parties": {
    "buyer": {"id": "buyer-1", "display_name": "Demo Buyer"},
    "seller": {"id": "northwind", "display_name": "Northwind Supply"}
  },
  "offer": {
    "offer_id": "offer-123",
    "request_id": "rfq-9",
    "offer_round": 2,
    "offer_hash": "<64 hex>",
    "offer_valid_until": "2026-11-01T12:00:00Z"
  },
  "items": [
    {
      "sku": "SKU-1",
      "name": "Industrial sensor",
      "quantity": 10,
      "unit_price_cents": 4200,
      "warranty_addon_cents": 300,
      "line_total_cents": 45000
    }
  ],
  "totals": {
    "currency": "USD",
    "subtotal_cents": 45000,
    "shipping_cents": 2500,
    "tax_cents": 3600,
    "fees_cents": 500,
    "total_cents": 51600
  },
  "delivery": {
    "delivery_days": 5,
    "starts_on": "FUNDING_CONFIRMED"
  },
  "warranty_months": 12,
  "returns_days": 30,
  "inspection": {
    "period_hours": 48,
    "starts_on": "DELIVERY_CONFIRMED"
  },
  "evidence_required": [
    "shipment_manifest",
    "delivery_confirmation",
    "invoice"
  ],
  "remedies": {
    "non_delivery": "cancel_and_refund",
    "late_delivery": "cancel_and_refund",
    "damaged_goods": "refund_or_replacement"
  },
  "dispute_window_hours": 72
}
```

Rules:

- Money is integer cents. `total = subtotal + shipping + tax + fees`; `subtotal = Σ (unit_price + warranty_addon) × quantity`.
- Tax and fees are seller-quoted. Verifund does not calculate them.
- `delivery_days >= 1` for goods. The absolute delivery deadline is not stored in the version; it is computed as `funded_at + delivery_days` and recorded on the transaction.
- `inspection.period_hours >= 1`; `inspection.starts_on` is `DELIVERY_CONFIRMED` in v1.
- `delivery.starts_on` is `FUNDING_CONFIRMED` in v1.
- `evidence_required` must be a non-empty subset of `EvidenceKind` and must include `delivery_confirmation`, because the inspection window starts on that event.
- The inspection window starts at `DELIVERY_CONFIRMED`. Release is permitted only after the inspection window elapses and no dispute is open. The dispute window also starts at `DELIVERY_CONFIRMED` and bounds when a dispute may be opened; an open dispute blocks release regardless of the inspection window. The dispute window does not delay release by itself.
- `RemedyPolicy` v1 values are `cancel_and_refund` and `refund_or_replacement`. Partial-refund remedies are not representable because there is no deterministic formula; they require a new terms version design.
- `inspection`, `evidence_required`, `remedies`, and `dispute_window_hours` are buyer/platform terms, not seller-quoted offer fields. The buyer agent populates them from its mandate or platform defaults, and the seller agent checks them against its mandate before accepting.
- `platform_terms_version` identifies the platform boilerplate text, which is versioned in code. Changing the boilerplate requires bumping this value.
- `agreement_type` and `terms_version` are the extension point for services agreements.

### 5.4 Validation

`validate_terms()` rejects:

- Negative tax, fees, shipping, price, or quantity.
- Line-item totals, subtotal, or total arithmetic mismatches.
- Non-USD currency.
- Missing or empty evidence list, or an evidence list without `delivery_confirmation`.
- Unknown evidence or remedy values.
- Non-positive delivery days, inspection period, or dispute window.
- Buyer/seller identity mismatches.
- Duplicate SKU within the line items.
- An offer hash or round that does not match the award.
- An expired offer.

`invalid_request` (400) covers terms errors; `offer_mismatch` (409) covers round/hash divergence; `offer_expired` (409) covers a stale offer.

### 5.5 Digest

```text
agreement_hash = SHA-256(canonical_json({
  "schema": "verifund.agreement.v1",
  "agreement_id": "<id>",
  "version": <n>,
  "agreement_type": "goods",
  "terms_version": 1,
  "terms": { ...canonical terms... }
}))
```

- Canonical JSON: sorted keys, compact separators, UTF-8, UTC `Z` timestamps.
- Operational metadata is excluded: `status`, `expires_at`, `created_at`, `updated_at`, decision rows, and stage deadlines.
- The digest binds the agreement identity, version, type, terms version, and every contractual term.
- `AgreementProjection.canonical_payload()` returns exactly this envelope. `recompute_hash()` must match `agreement_hash`.

### 5.6 HTML artifact

- Deterministic server-side template with no external assets.
- Renders parties, itemized table, totals, delivery, warranty, returns, inspection, evidence obligations, remedies, dispute window, version, digest, and a metadata footer.
- All values are HTML-escaped.
- Stored in `agreement_versions.rendered_html` with `renderer_version`.
- Re-rendering from stored terms must produce byte-identical output; a unit test enforces this.
- Served at `GET /agreements/{id}/document?version=N` as `text/html`.
- No PDF and no e-signature.

---

## 6. Acceptance and authorization

### 6.1 Seller decision

The seller agent receives the full agreement projection, including canonical terms and digest. Before returning a decision it must:

1. Match `agreement.seller_id` to its own seller ID.
2. Load its stored `Offer` by `offer_id` and recompute `offer_hash` from the shared `OfferBinding` projection.
3. Recompute the agreement hash from the projection and compare it to `agreement.agreement_hash`.
4. Verify version provenance:
   - Version 1: terms match the offer-derived terms.
   - Version `N+1`: load the locally stored previous version, apply the accepted change request operations deterministically, and compare the result to the new terms and digest.
5. Evaluate its `SellerMandate`, including total, currency, warranty, returns, inspection period, and dispute window limits.

The seller agent stores the versions it reviews in `seller_agreement_reviews` in `data/seller.db`, keyed by `(agreement_id, version)`, with terms, digest, offer hash, change request ID, and decision. This is what makes chain verification possible without trusting the control plane blindly.

Possible results:

| `AgreementReviewDecision` | Meaning | Control plane action |
|---|---|---|
| `ACCEPTED` | Offer and terms match; within mandate | Record `ACCEPT`; `PENDING_SELLER → PENDING_BUYER`. |
| `REJECTED` | Mismatch, out of stock, or policy refusal | Record `REJECT`; `PENDING_SELLER → REJECTED`; cancel transaction. |
| `OPERATOR_REQUIRED` | Terms valid but outside auto-accept limits | Stay `PENDING_SELLER`; set operator flag; no decision row. |
| `CHANGES_REQUESTED` | Structured change set attached | Record `REQUEST_CHANGES`; `PENDING_SELLER → CHANGES_REQUESTED`. |

`AgreementReviewResult` carries:

```text
party, status, run_id, transaction_id, agreement_version, agreement_hash,
offer_hash, actor_type, actor_id, authority_ref, authority_snapshot,
verified_change_request_id, task_id, context_id, reviewed_at,
reason_code, note
```

`actor_type` is `SELLER_AGENT` or `SELLER_OPERATOR`. `authority_ref` is `seller-mandate:{seller_id}:{mandate_version}` or the operator identity. `authority_snapshot` records the limits that were applied.

Seller operator acceptance uses the same control-plane endpoint with `actor_type=SELLER_OPERATOR`; a successful operator decision clears the `seller_operator_required` flag. The seller-operator console is out of scope, but the API and tests are not. Demo mandates are generous enough that the agent auto-accepts in the normal flow.

### 6.2 Buyer approval tokens

Seller `ACCEPT` moves the agreement to `PENDING_BUYER` and sets `expires_at = now + buyer_approval_hours`. The control plane issues buyer approval tokens:

```json
{
  "jti": "uuid",
  "aud": "agreement-approval",
  "sub": "buyer-id",
  "agreement_id": "agr_...",
  "version": 2,
  "agreement_hash": "sha256...",
  "iat": "2026-10-30T12:00:00Z",
  "exp": "2026-10-30T12:30:00Z"
}
```

- Signed with the existing `LinkSigner` HMAC secret and validated with the same production-secret rules.
- Stored as `jti`, `token_hash`, binding, `expires_at`, `used_at`, `revoked_at`, and issuer. The raw token is never stored.
- Audience is `agreement-approval`; subject is the buyer; version and digest are the exact current version.
- TTL is `min(now + token_ttl, agreement.expires_at)`.
- Multiple tokens may be outstanding for the same `(agreement, version)` — for example, the console page and an external link. **Issuance does not revoke prior tokens.** The first successful decision consumes its token and revokes all other unused tokens for that agreement/version.
- Consumption is an atomic conditional update: `WHERE jti = ? AND used_at IS NULL AND revoked_at IS NULL`.
- A token authorizes agreement decisions only. It cannot authorize funding.

The buyer decision endpoint requires three identities to agree: the token's `sub`, the resolved `ActorContext.actor_id`, and the buyer recorded on the agreement. In the demo, `ActorContext` comes from a small adapter defaulting to `demo-buyer`. Later, the Clerk adapter maps a verified JWT `sub` into the same interface.

### 6.3 Buyer decision

`POST /agreements/{id}/buyer-decision` accepts:

```text
agreement_version, agreement_hash, decision, note, change_set?
```

`BuyerApprovalDecision` values are `APPROVE`, `REJECT`, and `REQUEST_CHANGES`; `APPROVE` maps to the persisted `AgreementDecision.ACCEPT`.

- `APPROVE` → `PENDING_BUYER → AGREED`; transaction `AWARDED → AGREED`; set `agreed_at`; emit `agreement.agreed`.
- `REJECT` → `REJECTED`; cancel the transaction if not funded.
- `REQUEST_CHANGES` → `CHANGES_REQUESTED` with a structured change set.

The buyer agent may run a non-binding precheck before the human decision. The precheck is stored as `buyer_precheck` on the transaction and as an event. It cannot change the agreement state and cannot substitute for human approval. If the precheck rejects, the human may still approve; the recommendation is displayed on the review page.

### 6.4 Approval surfaces

| Surface | Behavior |
|---|---|
| Dedicated page `/agreements/[id]` | Server action fetches the agreement and issues a token immediately before submitting the decision. The browser never holds the token. Approve/reject/request-changes are server actions. |
| Chat approval card | Shows version, total, digest prefix, seller decision, and buyer precheck. The action opens the dedicated page. No approval happens in chat. |
| Signed external link | `POST /agreements/{id}/approval-token` returns a short-lived URL containing the token. The recipient lands on the same review page; the token is consumed on decision. Delivery via WhatsApp/Discord is deferred. |

All three surfaces converge on one buyer-decision service. The chat card is a notification card, not a competing consent path.

### 6.5 Idempotency and concurrency

- Every mutating endpoint requires `Idempotency-Key`, reusing the existing replay table.
- A duplicate decision with the same key and body returns the stored response. A different body with the same key returns `409 idempotency_conflict`.
- State changes use `WHERE status = expected AND row_version = expected AND (expires_at IS NULL OR expires_at > now)`.
- Token consumption, decision insertion, state transition, transaction update, and event append happen in one SQLite transaction.
- A deadline race returns `409 agreement_expired`; the reconciler then finalizes the state.
- A token replay returns `409 token_used`; a revoked token returns `409 token_revoked`.

---

## 7. Change requests and versioning

### 7.1 Structured change set

A change request is a typed operation list against a base version plus a non-contractual `reason`:

```text
set_unit_price          { sku, unit_price_cents }
set_quantity            { sku, quantity }
set_shipping            { shipping_cents }
set_tax                 { tax_cents }
set_fees                { fees_cents }
set_delivery_days       { delivery_days }
set_warranty_months     { warranty_months }
set_returns_days        { returns_days }
set_inspection_period   { inspection_period_hours }
set_evidence_required   { evidence_required[] }
set_remedies            { non_delivery, late_delivery, damaged_goods, dispute_window_hours }
```

Rules:

- Unknown SKU, negative values, empty evidence, or an unknown remedy → `400 invalid_change_set`.
- Adding or removing line items is a scope change. It must return to A2A negotiation and produce a new offer/award.
- `reason` is displayed in audit history but is never part of the contract or digest.
- One open change request per agreement. The requester cannot resolve their own request.
- Resolving requires the same authorization as a normal decision: buyer token for the buyer, seller token or operator authority for the seller.

### 7.2 Version generation and the offer chain

The original `offer_hash` anchors **version 1**. A price-changing version cannot still match the raw offer, so later versions are anchored by a digest chain:

```text
winning Offer
  └─ offer_hash
       └─ v1 agreement_hash
            └─ change request CR-1 (accepted by both)
                 └─ v2 agreement_hash
                      └─ change request CR-2 ...
```

- `offer_round` and `offer_hash` stay fixed on the agreement. Change requests do not invent a new offer round.
- Each version stores `supersedes_version` and `change_request_id`.
- `apply_change_set(base_terms, ops)` is a pure function. It recomputes line totals, subtotal, and total, then runs the same `validate_terms()` as initial generation.
- Verification of version `N+1` checks: the accepted change request targets `N`; applying it to `N` yields exactly the stored `N+1` terms and digest.
- Prior decisions remain attached to their version but are ineffective. `N+1` starts at `PENDING_SELLER` with a fresh seller window.
- A buyer who accepts a change request consumes a token bound to the base version. The regenerated version still needs a new token and fresh buyer approval.
- The seller agent verifies the chain using its locally stored previously reviewed version and the change request it accepted.

### 7.3 Resolution rules

- A seller change request can be resolved only by the buyer; a buyer change request can be resolved only by the seller.
- The resolution request includes `ACCEPT` or `REJECT` plus an optional note.
- On `ACCEPT`:
  - Apply operations to the base terms.
  - Validate the result.
  - Append version `N+1`.
  - Mark the change request `ACCEPTED` with `resulting_version = N+1`.
  - Set the agreement to `PENDING_SELLER`.
  - Set a fresh seller deadline.
  - Emit `changes_accepted`.
- On `REJECT`:
  - Mark the change request `REJECTED`.
  - Return to `PENDING_SELLER` if the seller was the requester, or `PENDING_BUYER` if the buyer was the requester.
  - Set a fresh stage deadline.
  - Emit `changes_rejected`.
- If the change-request deadline elapses, the agreement becomes `EXPIRED` and the change request becomes `EXPIRED`.

### 7.4 Version history

`GET /agreements/{id}/versions` returns, for every version:

- Version number and digest.
- Creation reason and accepted change request.
- `created_at` and `superseded_at`.
- Decisions with party, actor type, actor ID, authority reference, decision, and timestamp.
- Whether the version is current.

Version rows, decisions, and change requests are never deleted. Old documents remain retrievable for audit.

---

## 8. Expiry

### 8.1 Settings

```text
AGREEMENT_SELLER_ACCEPTANCE_HOURS     default 24
AGREEMENT_BUYER_APPROVAL_HOURS        default 24
AGREEMENT_CHANGE_RESPONSE_HOURS       default 24
AGREEMENT_APPROVAL_TOKEN_TTL_MINUTES  default 30
```

The existing funding timeout remains a transaction-level setting.

### 8.2 Behavior

- Every non-terminal transition sets `expires_at` for the new stage.
- `AGREED` has no agreement expiry; the transaction funding deadline governs.
- `ExpiryReconciler` runs on the existing reconciler cadence: select stale agreements, conditionally transition to `EXPIRED`, append an event, revoke outstanding tokens, and cancel the transaction if it has not been funded.
- Lazy expiry runs on every read and decision: if `expires_at <= now`, the same expiry path executes before the request is answered. Tests do not depend on the background loop.
- A decision and expiry race is resolved by the conditional update including `expires_at > now`. The loser receives `409 agreement_expired`.
- Funding checks the agreement directly: status must be `AGREED`, and the presented version/digest must match. The reconciler is a safety net, not the source of truth.
- If funding expires, the existing funding-expiry path cancels the transaction and calls `AgreementService.terminate()` so the agreement becomes `TERMINATED`.

---

## 9. Integration with the existing workflow

### 9.1 Lifecycle

Current:

```text
award → buyer-agent review → seller review → AGREED → funding HITL
```

New:

```text
award → seller review → buyer-agent precheck (non-binding) → human buyer approval
      → AGREED → funding HITL → funding → purchase order → evidence → release
```

```text
create_agreement (control plane: PENDING_SELLER, transaction AWARDED)
        │
        ▼
await_seller_review ──REJECT──> finalize (agreement REJECTED, transaction CANCELED)
        │ ACCEPT
        ▼
await_buyer_approval (interrupt; page link + precheck recommendation)
        │ APPROVE
        ▼
agreement AGREED, transaction AGREED
        │
        ▼
await_funding_approval (existing HITL, now version/hash-bound)
        │
        ▼
fund_transaction → funding settlement → purchase order → evidence → release
```

`REQUEST_CHANGES` at either stage routes to `await_change_resolution`. When resolved, the run re-reads the agreement and loops to `PENDING_SELLER` (new version) or back to the pending stage (change rejected).

### 9.2 Contracts

`packages/verifund_contracts/verifund_contracts/models.py`:

- Add `AgreementState`.
- Add `AgreementDecision` (`ACCEPT`, `REJECT`, `REQUEST_CHANGES`).
- Add `BuyerApprovalDecision` (`APPROVE`, `REJECT`, `REQUEST_CHANGES`).
- Extend `AgreementReviewDecision` with `OPERATOR_REQUIRED` and `CHANGES_REQUESTED`.
- Add `ChangeOperation`, `ChangeSet`, `ChangeRequestView`, `ChangeResolution`.
- Add `ApprovalTokenResponse`.
- Add `AgreementView` and `AgreementVersionView`.
- Extend `AgreementProjection` with `status`, `expires_at`, `terms`, `offer_round`, `offer_hash`, `offer_valid_until`, `tax_cents`, `fees_cents`, `inspection_period_hours`, `inspection_starts_on`, `evidence_required`, `remedies`, `dispute_window_hours`, `supersedes_version`, and `change_request_id`.
- Keep the existing summary fields (`amount_cents`, `quantity`, `line_items`, `shipping_cents`, `delivery_days`, `warranty_months`, `returns_days`) for current consumers, and add a validator that they match `terms`.
- Keep `agreement_hash` as the canonical version digest. Change `canonical_payload()` to return the digest envelope from §5.5, excluding mutable fields.
- Extend `AwardRequest` with `request_id`, `buyer_display_name`, `seller_display_name`, `offer_round`, `offer_hash`, `offer_valid_until`, `tax_cents`, `fees_cents`, `inspection_period_hours`, `inspection_starts_on`, `evidence_required`, `remedies`, and `dispute_window_hours`.
- Keep `AwardRequest.amount_cents` as the all-in total.
- Add `agreement_version` to `ApproveRequest` and `FundRequest`.

`packages/verifund_contracts/verifund_contracts/a2a.py`:

- Add checkpoints:
  - `BUYER_APPROVAL_REQUIRED = "buyer_approval_required"`
  - `SELLER_OPERATOR_REQUIRED = "seller_operator_required"`
  - `AGREEMENT_CHANGES_REQUESTED = "agreement_changes_requested"`
- Add `BuyerAgreementApprovalDecision` for the human resume payload.
- Extend `AgreementReviewRequest` with optional `change_request` details for version `N+1`.
- Extend `AgreementReviewResult` with `offer_hash`, `actor_type`, `actor_id`, `authority_ref`, `authority_snapshot`, and `verified_change_request_id`.
- Bump `VERIFUND_SCHEMA_BASE` to `/v2` for the changed agent-facing envelopes.

`packages/commerce_core/commerce_core/contracts.py`:

- Add `tax_cents` and `fees_cents` to `Offer`.
- Change the total validator to `subtotal + shipping + tax + fees`.
- Add shared `canonical_offer_binding()`, `binding_from_award()`, and `offer_hash()`.

### 9.3 Control plane

`apps/verifund_control_plane/verifund_control_plane/`:

- New `agreements/` package:
  - `models.py` — aggregate dataclasses and enums.
  - `states.py` — transition table and guards.
  - `generator.py` — award + offer → canonical terms.
  - `digest.py` — canonical JSON and hash.
  - `renderer.py` — deterministic HTML.
  - `repository.py` — agreement tables.
  - `service.py` — create, decide, change, expire, verify.
  - `tokens.py` — approval token issue/verify/consume.
  - `routes.py` — agreement endpoints.
  - `expiry.py` — reconciler sweep.
- `service.py`:
  - `award()` delegates generation and inserts agreement + transaction atomically.
  - `accept()` delegates the seller decision; it no longer sets `AGREED` directly.
  - `record_buyer_review()` becomes a non-binding precheck.
  - Add buyer decision, change-request, token, and agreement-read methods.
  - `approve()` and `fund()` validate current version/digest and the funding approval binding.
  - `cancel()` maps pre-agreement cancellations to `REJECTED` and post-agreement cancellations to `TERMINATED`.
- `repository.py`:
  - Replace the JSON-blob `agreements` and `agreement_reviews` tables with normalized agreement tables.
  - Add `agreement_id` to transactions.
  - Keep transaction events.
  - Clean schema reset; no migration.
- `app.py`:
  - Include the agreements router.
  - Wire `AgreementService`, token signer, and expiry reconciler into lifespan.

### 9.4 Seller agent

`apps/seller_agent/seller_agent/agreement.py`:

- Recompute offer hash from the stored offer.
- Recompute the agreement hash from the projection.
- Verify version provenance using local review history.
- Evaluate the seller mandate.
- Return `ACCEPTED`, `REJECTED`, `OPERATOR_REQUIRED`, or `CHANGES_REQUESTED`, with actor and authority fields.

`apps/seller_agent/seller_agent/profiles/*.yaml`:

```yaml
mandate:
  version: 1
  auto_accept: true
  allowed_currencies: ["USD"]
  max_total_cents: 500000
  min_warranty_months: 0
  max_warranty_months: 24
  min_returns_days: 0
  max_returns_days: 60
  max_inspection_period_hours: 72
  max_dispute_window_hours: 168
```

`apps/seller_agent` local store:

- Add `seller_agreement_reviews` keyed by `(agreement_id, version)`, storing terms, digest, offer hash, change request ID, decision, and timestamp.
- This is the seller's evidence for verifying version `N+1`.

### 9.5 Buyer agent

`apps/buyer_agent/buyer_agent/agreement_service.py`:

- Add `get_agreement`.
- Add `record_seller_decision`.
- Add `precheck` (non-binding).
- Pass `agreement_version` and `agreement_hash` to funding approval and funding.
- Stop treating buyer review as acceptance.

`apps/buyer_agent/buyer_agent/graph.py`:

- Remove the formal buyer review before seller review.
- After seller acceptance, run a non-binding precheck and wait for the human decision.
- Keep the existing settlement store and seller token handling.

`apps/buyer_agent/buyer_agent/settlement_client.py`:

- Add client methods for agreement reads, precheck, seller decisions, buyer decisions, tokens, versions, and documents.

`apps/buyer_agent/buyer_agent/review.py`:

- Parse the extended review result with actor/authority/offer hash fields.

### 9.6 Verifund agent

`apps/verifund_agent/verifund_agent/graph.py`:

- Reorder to seller review → buyer approval → funding.
- Add `await_change_resolution`.
- Add a `sync_agreement` router that reads the current agreement status from the buyer internal API and routes to:
  - `PENDING_SELLER` → `await_seller_review`
  - `PENDING_BUYER` → `await_buyer_approval`
  - `CHANGES_REQUESTED` → `await_change_resolution`
  - `AGREED` → `await_funding_approval`
  - `REJECTED` / `EXPIRED` / `TERMINATED` → `finalize`
- Before interrupting at `await_buyer_approval`, call the buyer internal precheck and include its recommendation and rationale in the payload.
- The buyer interrupt payload includes the agreement, review URL, version, digest, seller decision, and precheck recommendation.
- After a buyer approval resume, query the control plane and require `AGREED` before proceeding; do not trust the resume payload alone.

Checkpoint additions:

```text
buyer_approval_required
seller_operator_required
agreement_changes_requested
```

### 9.7 Orchestrator

`apps/orchestrator_agent/orchestrator_agent/verifund.py`:

- `start()` expects `SELLER_REVIEW_REQUIRED`, performs the seller A2A review, records the seller decision, then expects `BUYER_APPROVAL_REQUIRED`.
- Add `resume_agreement(handle, decision)`.
- `_view()` exposes `agreement_review` with the review URL, version, digest, seller decision, and precheck.
- Funding HITL args already carry `agreement_version` and `agreement_hash`; the approval and funding requests must pass and enforce them.

`apps/orchestrator_agent/orchestrator_agent/agent.py`:

- Instruct the agent to present an agreement review card with a link.
- Never ask for agreement approval in chat.
- Keep funding as a blocking HITL tool.

### 9.8 Console

New route and components:

```text
apps/console/app/agreements/[id]/page.tsx
apps/console/app/agreements/[id]/actions.ts
apps/console/features/agreements/AgreementDocument.tsx
apps/console/features/agreements/AgreementSummary.tsx
apps/console/features/agreements/ApprovalActions.tsx
apps/console/features/agreements/VersionHistory.tsx
```

- The page renders version, digest, totals, terms, seller decision, buyer precheck, and version history.
- Server actions fetch the agreement, issue a token server-side at submit time for console users, submit the decision, and resume the Verifund run.
- External-link mode uses the token from the URL and sets `Referrer-Policy: no-referrer`.
- If resume fails after the decision is recorded, the page shows success for the decision and a retry action; the control plane remains the source of truth.

Chat:

- `apps/console/features/chat/verifund-tools.tsx` adds labels for `buyer_approval_required`, `agreement_changes_requested`, and `seller_operator_required`.
- Add an `AgreementApprovalCard` with version, total, digest prefix, and a “Review agreement” link.
- Add a non-blocking frontend tool `show_agreement_review` so the orchestrator can render the card. It is not a human-in-the-loop tool.
- The existing funding HITL card gains version and digest display.

Control-plane client:

- Add `getAgreement`, `issueApprovalToken`, `buyerDecision`, `sellerDecision`, `versions`, and `document`.

### 9.9 A2A protocol

- The changed agreement envelopes use schema base `/v2`.
- `AgreementReviewRequest` includes the full projection and, for `N+1`, the accepted change request details.
- `AgreementReviewResult` includes the verification evidence and authority fields.
- The seller token remains the transport credential for seller decisions.
- Human buyer approval is not an A2A message; it is a control-plane decision followed by an orchestrator resume.

### 9.10 Documentation and data reset

- Update `docs/workflow.md` with the new lifecycle, approval separation, version chain, and invariants.
- Update `docs/verifund-paypal-sandbox.md` if it references the old agreement flow.
- Delete `data/verifund.db*` and re-seed. `Repository.create_schema` creates the new tables.
- No migration code and no backward-compatible endpoints beyond the wrappers listed in §10.

---

## 10. API

### 10.1 Existing endpoints

| Method | Path | Auth | Change |
|---|---|---|---|
| `POST` | `/award` | Existing buyer/service auth | Creates agreement `PENDING_SELLER`; response includes agreement state. |
| `POST` | `/accept` | Seller token | Compatibility wrapper for seller decision; extended request with version, digest, offer hash, actor, authority, changes. |
| `POST` | `/buyer-review` | Existing buyer/service auth | Non-binding precheck only; never changes agreement state to `AGREED`. |
| `POST` | `/approve` | Existing buyer/service auth | Funding authorization; now requires `agreement_version` and current digest. |
| `POST` | `/fund` | Existing buyer/service auth | Requires `agreement_version`, current digest, `AGREED`, and a matching funding approval. |

### 10.2 New endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/agreements/{id}` | Buyer/seller/ops actor | Agreement view with current version, decisions, changes, and review URL. |
| `GET` | `/agreements/{id}/versions` | Buyer/seller/ops actor | Full version and decision history. |
| `GET` | `/agreements/{id}/document?version=N` | Buyer/seller/ops actor or approval token | Rendered HTML artifact. |
| `POST` | `/agreements/{id}/approval-token` | Buyer actor | Issue a token and review URL. |
| `POST` | `/agreements/{id}/buyer-decision` | Buyer actor + approval token | Approve, reject, or request changes. |
| `POST` | `/agreements/{id}/seller-decision` | Seller token or operator auth | Accept, reject, request changes, or report operator required. |
| `POST` | `/agreements/{id}/change-requests` | Requesting party | Create a structured change request. |
| `POST` | `/agreements/{id}/change-requests/{cr_id}/resolve` | Counterparty | Accept or reject a change request. |

`GET /agreements?transaction_id=...` is also supported for lookup by the console and orchestrator.

---

## 11. Persistence

### 11.1 Tables

**`agreements`**

```sql
CREATE TABLE agreements (
  agreement_id TEXT PRIMARY KEY,
  transaction_id TEXT NOT NULL UNIQUE,
  run_id TEXT NOT NULL,
  buyer_id TEXT NOT NULL,
  seller_id TEXT NOT NULL,
  current_version INTEGER NOT NULL,
  status TEXT NOT NULL,
  offer_id TEXT NOT NULL,
  offer_round INTEGER NOT NULL,
  offer_hash TEXT NOT NULL,
  offer_valid_until TEXT NOT NULL,
  expires_at TEXT,
  agreed_at TEXT,
  rejected_at TEXT,
  expired_at TEXT,
  terminated_at TEXT,
  terminal_reason TEXT,
  seller_operator_required INTEGER NOT NULL DEFAULT 0,
  row_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Indexes: `(status, expires_at)`, `(run_id)`, `(buyer_id)`, `(seller_id)`.

`transaction_id` is unique but not a foreign key; `transactions.agreement_id` is the FK, avoiding a cycle.

**`agreement_versions`**

```sql
CREATE TABLE agreement_versions (
  agreement_id TEXT NOT NULL REFERENCES agreements(agreement_id),
  version INTEGER NOT NULL,
  terms TEXT NOT NULL,
  agreement_hash TEXT NOT NULL,
  rendered_html TEXT NOT NULL,
  renderer_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  supersedes_version INTEGER,
  change_request_id TEXT,
  superseded_at TEXT,
  PRIMARY KEY (agreement_id, version)
);
```

`terms` is canonical JSON. No UPDATE except setting `superseded_at`.

**`agreement_decisions`**

```sql
CREATE TABLE agreement_decisions (
  decision_id TEXT PRIMARY KEY,
  agreement_id TEXT NOT NULL REFERENCES agreements(agreement_id),
  version INTEGER NOT NULL,
  party TEXT NOT NULL,
  decision TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  authority_ref TEXT,
  authority_snapshot TEXT,
  agreement_hash TEXT NOT NULL,
  verified_offer_hash TEXT,
  verified_change_request_id TEXT,
  reason_code TEXT,
  note TEXT NOT NULL DEFAULT '',
  change_request_id TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  decided_at TEXT NOT NULL
);
```

Index: `(agreement_id, version, decided_at)`.

**`agreement_change_requests`**

```sql
CREATE TABLE agreement_change_requests (
  change_request_id TEXT PRIMARY KEY,
  agreement_id TEXT NOT NULL REFERENCES agreements(agreement_id),
  base_version INTEGER NOT NULL,
  base_hash TEXT NOT NULL,
  requested_by_party TEXT NOT NULL,
  requested_by_actor_type TEXT NOT NULL,
  requested_by_actor_id TEXT NOT NULL,
  operations TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  resolved_by_party TEXT,
  resolved_by_actor_type TEXT,
  resolved_by_actor_id TEXT,
  resolution_note TEXT,
  resulting_version INTEGER,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
```

Partial unique index:

```sql
CREATE UNIQUE INDEX ux_change_pending
ON agreement_change_requests(agreement_id)
WHERE status = 'PENDING';
```

**`agreement_approval_tokens`**

```sql
CREATE TABLE agreement_approval_tokens (
  jti TEXT PRIMARY KEY,
  agreement_id TEXT NOT NULL REFERENCES agreements(agreement_id),
  version INTEGER NOT NULL,
  agreement_hash TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  revoked_at TEXT,
  issued_by_actor_type TEXT NOT NULL,
  issued_by_actor_id TEXT NOT NULL,
  consumed_by_decision_id TEXT
);
```

Indexes: `(agreement_id, version)`, `(expires_at)`.

**`agreement_events`**

```sql
CREATE TABLE agreement_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  agreement_id TEXT NOT NULL REFERENCES agreements(agreement_id),
  version INTEGER,
  event_type TEXT NOT NULL,
  payload TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

Index: `(agreement_id, event_id)`.

**`transactions` changes**

- Add `agreement_id TEXT NOT NULL REFERENCES agreements(agreement_id)`.
- Keep `agreement_version` and `agreement_hash` as denormalized current pointers, updated atomically on version change.
- Rename `buyer_agent_review` to `buyer_precheck`.
- Add cancellation reasons `AGREEMENT_REJECTED`, `AGREEMENT_EXPIRED`, and `AGREEMENT_TERMINATED`.

### 11.2 Seller-side table

In `data/seller.db`:

```sql
CREATE TABLE seller_agreement_reviews (
  agreement_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  agreement_hash TEXT NOT NULL,
  offer_hash TEXT NOT NULL,
  terms TEXT NOT NULL,
  change_request_id TEXT,
  decision TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
  PRIMARY KEY (agreement_id, version)
);
```

This is the seller agent's local evidence for verifying later versions.

### 11.3 Repository boundary

A dedicated `AgreementRepository` shares the engine and `transaction()` helper with `Repository`, but owns only agreement tables:

```text
create(conn, agreement, version)
get(agreement_id)
get_by_transaction(transaction_id)
get_version(agreement_id, version)
list_versions(agreement_id)
append_decision(conn, decision)
update_status_cas(conn, agreement_id, expected_status, expected_row_version, ...)
create_change_request
get_open_change_request
resolve_change_request
issue_token
consume_token
revoke_tokens
append_event
list_events
list_expired(limit)
expire(conn, agreement_id, expected_row_version)
```

`AgreementService` owns transitions and calls the repository. `VerifundService` never writes agreement tables directly.

### 11.4 Transaction boundaries

| Operation | One SQLite transaction contains |
|---|---|
| Award | Insert agreement, version, event; insert transaction with `agreement_id` and current pointers. |
| Seller decision | Verify status/version/hash/deadline → insert decision → CAS status/deadline → event → update transaction if rejected. |
| Buyer decision | Consume token → insert decision → CAS status/deadline → event → update transaction if `AGREED`/`REJECTED`. |
| Change resolution | Verify open request → apply operations → insert version `N+1` → mark request resolved → CAS status → event. |
| Expiry | CAS to `EXPIRED` → event → revoke tokens → cancel transaction if not funded. |
| Funding | Existing transaction transition plus agreement status/version/hash precondition. |

All state changes use:

```sql
WHERE status = :expected
  AND row_version = :expected_row_version
  AND (expires_at IS NULL OR expires_at > :now)
```

A failed CAS returns `409 conflict`; a deadline failure returns `409 agreement_expired`.

### 11.5 Idempotency

Reuse the existing idempotency table for responses. The following are scope prefixes; the caller supplies a unique `Idempotency-Key` per logical request and reuses it only for retries:

```text
agreement:create:{run_id}:{offer_id}
seller-decision:{agreement_id}:{version}
buyer-decision:{agreement_id}:{version}
change-request:{agreement_id}:{version}
change-resolve:{change_request_id}
```

This matters because a party may make more than one decision attempt on the same version after a rejected change request; each attempt needs its own key.

Approval-token issuance is intentionally **not** cached. The raw token must not be stored in the idempotency response table. Multiple tokens may be outstanding; the first successful decision revokes the rest.

### 11.6 Schema reset

`Repository.create_schema` creates the new tables. Delete `data/verifund.db*` and re-seed. Tests create a fresh temporary database per test. There is no migration path.

---

## 12. Errors and security

### 12.1 Error taxonomy

| Status | Codes | When |
|---|---|---|
| 400 | `invalid_request`, `invalid_terms`, `invalid_change_set` | Arithmetic, missing evidence, bad operation, unsupported field. |
| 403 | `forbidden` | Wrong buyer/seller/actor; token subject mismatch. |
| 404 | `not_found` | Agreement, version, or change request missing. |
| 409 | `invalid_state`, `hash_mismatch`, `offer_mismatch`, `offer_expired`, `already_decided`, `token_used`, `token_revoked`, `token_expired`, `agreement_expired`, `idempotency_conflict`, `conflict` | Wrong stage, stale version/digest, replay, expiry, CAS loss. |
| 422 | Pydantic validation | Malformed payload. |

Errors carry `agreement_id`, `version`, and the failing field where safe. Tokens, raw HTML, and secrets never appear in errors or logs.

### 12.2 Security boundaries

- **Interim identity:** `ActorContext` is a small interface with a demo adapter now and a Clerk adapter later. Agreement logic depends only on `actor_id`, `actor_type`, and `display_name`.
- **Token binding:** approval tokens are audience-scoped, subject-bound, version/digest-bound, short-lived, and single-use.
- **No token leakage:** tokens are never written to logs, audit payloads, or idempotency responses. External links use `Referrer-Policy: no-referrer`; the console never puts a token in chat.
- **CSRF/replay:** console actions are same-origin server actions; control-plane mutations require an idempotency key and, for buyer consent, a token.
- **Authorization:** seller endpoints require the seller token and matching `seller_id`; buyer endpoints require the buyer actor and matching `buyer_id`; ops endpoints keep the ops bearer token.
- **Residual risk:** the demo actor adapter is spoofable by anyone with network access. This is acceptable only until Clerk lands. The token still prevents cross-agreement and replay attacks. The limitation must be documented.

---

## 13. Observability

- Agreement events are the audit trail.
- Optional Prometheus counters:
  - `agreement_created_total`
  - `agreement_transition_total{from,to}`
  - `agreement_expired_total`
  - `approval_token_rejected_total{reason}`
- Logs include `agreement_id`, version, and digest prefix; never tokens or full terms HTML.

---

## 14. Testing and definition of done

### 14.1 Unit

- Generator arithmetic: line totals, subtotal, tax, fees, total; invalid combinations rejected.
- Canonical JSON and digest: key ordering, UTF-8, tamper detection, version binding.
- Offer binding: buyer, seller, and control plane compute the same hash; mutated round, price, or quantity produces a mismatch.
- State machine: every allowed and forbidden transition, terminal states.
- Change sets: deterministic application, totals recomputed, unknown SKU rejected, version chain digest.
- Approval tokens: signature, audience, subject, expiry, single use, revocation.
- Seller mandate: auto-accept inside limits, `OPERATOR_REQUIRED` outside.

### 14.2 Integration (control plane, temporary SQLite)

- Happy path: award → seller accept → approval token → buyer approve → `AGREED` → funding approval → fund.
- Funding blocked before `AGREED` (seller acceptance alone, buyer-agent precheck alone).
- Version or digest mismatch rejected on seller and buyer decisions.
- Duplicate approval is idempotent; second token use returns `409 token_used`.
- Expiry blocks funding and cancels the transaction.
- One change-request round: version 2 created, old decision ineffective, both parties must accept again.
- Offer mismatch is detected by the seller agent and returned as `REJECTED` with `reason_code=offer_mismatch`; a seller `ACCEPT` whose verified offer hash differs from the agreement is rejected with `409 offer_mismatch`.

### 14.3 Protocol

- `AgreementProjection` hash recomputation with full terms.
- Seller review result carries actor, authority, and verified offer hash.
- Orchestrator order is seller → buyer → funding; resume payload binding is enforced.
- Verifund graph routes `CHANGES_REQUESTED` back to the correct stage.

### 14.4 Console

- Review page renders version, digest, totals, terms, and seller decision.
- Stale version/digest disables approval and surfaces the error.
- Server action consumes the token and resumes the run.
- Chat card links to the page; no approval happens in chat.

### 14.5 Commands

```text
make test                 # full Python suite
make lint                 # ruff + console typecheck
cd apps/console && pnpm test
```

### 14.6 Definition of done

The happy path plus the focused invariants above pass. No exhaustive adversarial matrix, no load tests, and no cross-browser e2e beyond the existing harness.

---

## 15. Risks and trade-offs

| Risk | Mitigation |
|---|---|
| Demo identity is not real authentication | Token binding plus an explicit `ActorContext` seam; Clerk is the next milestone. |
| SQLite single-writer limits decision throughput | Acceptable for the demo; CAS and short transactions keep contention low. |
| HTML artifact is not a legal e-signature | Document it as an evidentiary artifact; e-signature is a separate project. |
| A2A envelope change breaks agents | Bump the agent-facing schema to `v2`; clean reset; update both agents together. |
| `service.py` refactor introduces regressions | Extract into `agreements/` behind tests; keep the transaction state machine intact. |
| Change requests cannot add/remove line items | Scope changes return to A2A negotiation and produce a new offer/award. |
| Expiry reconciler may not run | Lazy expiry on every read/decision; funding checks directly. |
| Token in an external URL | Short TTL, single-use, no-referrer, no logging. |
| Seller mandate is self-attested | Record the authority snapshot; the seller remains the authority owner. Future operator auth can strengthen this. |

---

## 16. Implementation sequence

The implementation plan will detail the tasks. The high-level order is:

1. Contracts and shared offer binding in `verifund_contracts` and `commerce_core`.
2. `agreements/` package, schema, digest, renderer, and control-plane endpoints.
3. Seller agent verification, mandate, and local review history.
4. Buyer agent precheck and funding binding.
5. Verifund agent and orchestrator lifecycle reorder, including the change-resolution loop.
6. Console review page, server actions, chat card, and external-link flow.
7. Documentation, schema reset, and full focused test pass.

---

## 17. Success criteria

A human buyer can open the exact agreement version, see its terms and digest, approve it, and funding remains impossible until that approval exists. A structured change creates a new version and invalidates prior consent. An expired agreement cannot be funded. Replays are idempotent. The seller agent can only auto-accept inside its mandate. All three approval surfaces reach the same approval service, and no agent can manufacture buyer consent.

---

## 18. Open questions

None. All design forks were resolved during the brainstorm, and the remaining decisions are implementation details for the plan.
