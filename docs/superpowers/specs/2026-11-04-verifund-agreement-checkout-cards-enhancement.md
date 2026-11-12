# Verifund Agreement and PayPal Checkout HITL Cards — Enhancement Spec

**Date:** 2026-11-04
**Status:** Approved design, revision 2 (implementation pending)
**Scope:** `apps/console/features/chat/verifund-tools.tsx`, `apps/console/app/globals.css`, orchestrator checkout args, console zod schemas, and the backend data plumbing for a required product-metadata block.

**Revision 2** records the decisions taken after the code-level review of revision 1. The important changes are: a versioned offer binding, a tolerant-but-required `attributes` field, seller metadata read from the catalog rather than guessed, cards rendering the hashed terms instead of demo copy, `mm-*` styling only, and an explicit statement of the checkout-run migration risk.

---

## 0. Locked decisions

| # | Decision |
|---|---|
| 1 | `AwardLineItem.attributes` is required, with a model-level before-validator that injects `{}` for legacy payloads |
| 2 | `SellerPolicy.for_product` carries description, emoji, tag, and hex color from the selected catalog product |
| 3 | The offer binding is versioned; v1 (`binding_version` absent or 1) remains verifiable |
| 4 | Every contract-bearing field on the cards renders from the hashed `terms` |
| 5 | The checkout card shows `args.amount_cents` (the charged amount) and warns when `terms.totals.total_cents` differs |
| 6 | Secondary card sections use native `<details>`/`<summary>` |
| 7 | `paypalCheckoutArgsSchema.agreement` is required; no amount-only fallback |
| 8 | Cards are styled with `mm-*` classes in `globals.css`; no Tailwind palette literals |
| 9 | Products without catalog metadata render a generic tile with a neutral background |

## 1. Problem

The current agreement and PayPal checkout HITL cards in `apps/console/features/chat/chat.tsx` are functional but sparse. They do not render the negotiated product, commercial terms, seller obligations, inspection/verification, returns/disputes, or agreement acceptance status that the canonical agreement already carries. The reference card structure in `apps/console/components/sample-agreement-checkout-cards-structure.tsx` shows the information architecture the cards should adopt, but it is a demo with hardcoded data and a Tailwind palette that appears nowhere else in the console.

Two data problems block the rewrite:

1. The checkout HITL payload (`_checkout_args` in `apps/orchestrator_agent/orchestrator_agent/verifund.py`) discards the agreement projection the Verifund lifecycle already produces, so the checkout card cannot show what is being paid for.
2. Product metadata stops at the seller catalog. `SellerPolicy.for_product` flattens the selected product to name, SKU, price, and a semantic color name, dropping description, emoji, tag, and the hex tile color, so nothing downstream can render a real product tile.

## 2. Goals

1. Rebuild both HITL cards to match the reference's information architecture while using only the console's `mm-` design system.
2. Render the canonical agreement's terms — product, money rows, obligations, evidence, inspection, remedies, dispute window, acceptance matrix, digest — from the hashed payload.
3. Enrich the checkout card with product summary, order summary, agreement reference, and the Verifund trust panel.
4. Carry a required product-metadata block (`attributes`) from seller catalog → offer → award → agreement terms → console. Individual keys may be absent.
5. Preserve all existing behavior: real PayPal create/capture/poll/cancel/fallback, approval binding to version/digest, and the three agreement decisions, including for awards created before this change.

## 3. Non-goals

- Moving agreement generation earlier in the lifecycle. The order (award approval → agreement creation → agreement approval) is retained.
- Redesigning the full agreement review page (`/agreements/{id}`) or the canonical HTML renderer.
- Changing the payment contract (PayPal order creation/capture still keys off `transaction_id`).
- Introducing real product image URLs. `image_url` remains an optional attribute key that the card renders if present; the primary visual is an emoji in a tinted tile.
- Reworking change requests, buyer/seller decision semantics, or the digest envelope.

## 4. Current flow (unchanged)

1. A2A negotiation completes and the buyer agent pauses for award approval (`request_award_approval`).
2. On approval, the buyer graph reaches `create_settlement_award`, interrupts with `reason="agreement_create_required"`.
3. The orchestrator calls `verifund_create_agreement`; the Verifund agent drives `create_agreement`, which calls the buyer internal API `/internal/runs/{run_id}/settlement/agreement`.
4. The control plane `AgreementService.create_from_award` validates the award, verifies the offer hash, builds canonical terms, computes the SHA-256 digest, renders HTML, and persists v1 as `PENDING_SELLER`.
5. Seller review transitions the agreement to `PENDING_BUYER`; the Verifund lifecycle returns `buyer_approval_required`, and the orchestrator emits `request_verifund_agreement_approval` with the full `AgreementProjection`.
6. The buyer approves/rejects/requests changes via the review page server actions (token-bound, version/digest-bound).
7. Funding approval then returns `request_verifund_funding_approval`; embedded checkout returns `request_verifund_paypal_checkout`.

## 5. Data contract changes (backend)

### 5.1 Seller planner

`apps/seller_agent/seller_agent/graph.py` `_offer_from_quote` builds the offer line item around line 331 with `attributes={"color": policy.color}`. `policy` is the product-scoped policy produced by `SellerPolicy.for_product`, so it is the only place the offer can learn about the product.

Extend `SellerPolicy` (`packages/commerce_core/commerce_core/pricing.py`) with defaulted display fields:

```python
product_description: str = ""
image_emoji: str = "📦"
product_tag: str = ""
product_color: str = "#eef2ed"
```

Extend `for_product` to populate them from the selected `SellerCatalogProduct`:

```python
"product_description": product.description,
"image_emoji": product.image_emoji,
"product_tag": product.tag,
"product_color": product.color,      # hex, used for the tile
```

`"color": product.color_name` stays as-is: it is the semantic name (`gray`, `black`) and is now emitted as `color_name`, not used as a CSS background.

In the `catalog()` single-product fallback, set `color` to `self.color` only when it already looks like a hex value; otherwise `#eef2ed`. The fallback product has no description or emoji, which is the expected degraded case.

`_offer_from_quote` then emits:

```python
attributes={
    "color": policy.product_color,
    "color_name": policy.color,
    "description": policy.product_description or policy.product_name,
    "image_emoji": policy.image_emoji,
    "condition": "new",
    "category": policy.categories[0] if policy.categories else "",
    "tag": policy.product_tag,
    "specs": policy.product_description or policy.product_name,
}
```

`specs` stays a single `·`-delimited string because `attributes` is `dict[str, str]`; the card splits it into chips.

The same offer sets `binding_version=2` (§5.2).

### 5.2 Offer binding (versioned)

`packages/commerce_core/commerce_core/binding.py` gains a versioned payload. Revision 1 claimed the hash would not change for offers without attributes; that was wrong, because a canonical JSON key is always emitted. The change is therefore explicit:

- v1 (current behavior): no `binding_version` key, no `attributes` in line items.
- v2: `"binding_version": 2` and `"attributes": {...}` in each line item.

`Offer` (`packages/commerce_core/commerce_core/contracts.py`) and `AwardRequest` (`packages/verifund_contracts/verifund_contracts/models.py`) each gain `binding_version: int = Field(default=1, ge=1)`. New offers and awards set 2. Verification dispatches on the declared version, so hashes produced before this change stay valid.

`canonical_offer_binding` reads `offer.binding_version`; `binding_from_award` reads `award.get("binding_version") or 1`. Both must produce byte-identical payloads for the same version.

### 5.3 Award line item

`AwardLineItem` (`packages/verifund_contracts/verifund_contracts/models.py:129`) gains:

```python
attributes: dict[str, str]

@model_validator(mode="before")
@classmethod
def _default_attributes(cls, data: Any) -> Any:
    if isinstance(data, dict) and not data.get("attributes"):
        return {**data, "attributes": {}}
    return data
```

This is required on the schema and type but tolerant on ingress, so awards persisted before this change still validate and still round-trip. The producers that must send real values:

- `apps/buyer_agent/buyer_agent/settlement_flow.py` `build_award_request` — copy `attributes` and `binding_version` from the winning offer. Without this the award hits the shim and every card shows the generic tile.
- `apps/verifund_control_plane/verifund_control_plane/agreements/service.py` `build_projection` — pass `attributes=i.get("attributes") or {}` and construct the fallback line item with `attributes={}`.

### 5.4 Term builder

`build_terms` (`apps/verifund_control_plane/verifund_control_plane/agreements/generator.py:29`) copies the block into each term item:

```python
"attributes": li.attributes,
```

(`getattr` is no longer needed; the shim guarantees the field.) Because `agreement_hash()` hashes the whole `terms`, attributes are now part of the agreement digest. That is intended: what the approval card displays is what the digest binds.

### 5.5 Console schema

`agreementSchema` item gains `attributes: z.record(z.string())` (required). `paypalCheckoutArgsSchema` gains `agreement: z.record(z.unknown())` (required).

## 6. HITL payload changes (orchestrator)

`_checkout_args` (`apps/orchestrator_agent/orchestrator_agent/verifund.py:1011`) adds the projection:

```python
"agreement": data.get("agreement"),
```

This is safe because `await_checkout` spreads `**_binding(agreement)`, which includes `"agreement"`. No change is needed for the agreement HITL; it already receives the full projection.

`agreement` is required in the console schema, so the amount-only fallback is removed from the card and from this spec. Operational consequence, recorded in §11: a run parked at `await_checkout` when this ships has a persisted payload without `agreement` and its card will not render.

## 7. Card information architecture

Both cards live in `mm-approval` containers. The chat rail is 340–398 px wide, so every section is single-column. Styling comes from new `mm-` rules in `apps/console/app/globals.css`; no Tailwind palette utilities appear in the components.

### 7.1 Shared `ProductSummary` component

Local to `verifund-tools.tsx`. Reads `agreement.terms.items` with a fallback to `agreement.line_items`.

- Tile: 64×56, neutral `--panel-green` background. If `attributes.color` matches `^#([0-9a-f]{3}|[0-9a-f]{6})$` it is used as the background; otherwise the neutral background stands. This guard is on the card, because legacy awards carry color names such as `gray`.
- Image chain: `attributes.image_url` → `attributes.image_emoji` → `📦`.
- Name; when there is more than one line item, append `(+N more)`.
- Seller display name from `terms.parties.seller.display_name` with a verified mark.
- Chips: condition, then `attributes.specs` split on `·`, then warranty, returns, and inspection window. Four visible, remainder collapsed to a `+N` chip. Specs come first because the commercial values already appear in the money and inspection sections.
- Quantity from `agreement.quantity`.

### 7.2 Agreement card sections

1. **Header** — `FileCheck2`, "Verifund agreement", `{agreement_id}`, status pill with both states ("Awaiting your approval" / "Approved"), version and expiry from `agreement.expires_at`.
2. **Product summary** — shared component, wrapped in `data-testid="agreement-product-summary"`.
3. **Agreed commercial terms** — always visible. Product price, tracked shipping, taxes, fees, total payable (large), all from `terms.totals`.
4. **Inspection and verification** — always visible. `terms.inspection.period_hours`, `terms.inspection.starts_on`, and `terms.evidence_required` rendered as the verification checklist with human labels.
5. **Seller obligations** — collapsed `<details>`. Product-specification match (platform duty), tracked shipping within `terms.delivery.delivery_days`, warranty `terms.warranty_months`.
6. **Returns and disputes** — collapsed `<details>`. `terms.remedies.non_delivery` / `late_delivery` / `damaged_goods` with labels, `terms.returns_days`, `terms.dispute_window_hours`, and the review-page link.
7. **Agreement acceptance** — collapsed `<details>`. Seller Agent (from `args.seller_decision`), Buyer (pending), Verifund (validated), and the precheck recommendation when present.
8. **Digest** — collapsed `<details>`. Truncated digest, created timestamp, version.
9. **Note** — compact textarea.
10. **Actions** — existing `mm-approval-actions mm-approval-actions-split` structure: full-width Approve, then Reject and Request changes.
11. **Fine print** — "Approval applies only to agreement {id}, version v{version}."

Approved state continues to be handled by the `status === "complete"` line in `chat.tsx`; the pill's approved branch covers a card that receives an approved projection.

### 7.3 Checkout card sections

1. **Header** — wallet icon, "Secure checkout", "Payment for agreement {id} · v{version}", status pill.
2. **Product summary** — shared component, wrapped in `data-testid="checkout-product-summary"`.
3. **Order summary** — `terms.totals` line items; **total payable is `args.amount_cents`**, because that is what PayPal charges. If `terms.totals.total_cents` differs, render `data-testid="checkout-amount-mismatch"` with a warning and keep the server amount as the displayed total.
4. **Verifund trust panel** — tracked delivery, inspection window from `terms.inspection.period_hours`, verification rules from `terms.evidence_required`.
5. **Payment method** — PayPal button, "Powered by PayPal", demo disclaimer.
6. **Fine print** — authorization statement.

The real PayPal flow (create order, capture, poll, cancel, fallback, error) is unchanged. Keep `data-testid="paypal-checkout"` and `verifund-checkout-amount`.

## 8. Component structure and state

- `ProductSummary`, `agreementTerms`, `agreementItems`, `labelFor`, `hexColor`, and `formatStamp` are module-level helpers in `verifund-tools.tsx`. The existing `money(cents, currency)` helper is reused; no per-component duplicate.
- Collapsing uses native `<details>`; no React state, no new event handlers.
- `StatusPill` markup is the existing `mm-approval-flag` sibling pattern replaced by `mm-status-pill` with `is-amber` / `is-muted` modifiers.
- PayPal phases (`ready/confirming/fallback/error`) remain; busy state disables the button.
- All three agreement decisions remain.

## 9. Responsive, accessibility, and tests

- Single column throughout; no horizontal overflow. `<details>` summaries are keyboard-operable and expose expanded state natively.
- Test IDs: `agreement-approval-hitl`, `product-summary`, `agreement-product-summary`, `agreement-money-rows`, `agreement-inspection-panel`, `checkout-product-summary`, `checkout-order-summary`, `checkout-trust-panel`, `checkout-amount-mismatch`, `paypal-checkout`, `verifund-checkout-amount`, `agreement-hitl-error`.
- Update `apps/console/tests/features/chat/paypal-checkout-card.test.tsx` (agreement fixture, mismatch case; the `$3,400.00` server-amount assertion stays).
- Create `apps/console/tests/features/chat/agreement-approval-hitl.test.tsx` covering: product summary, total from terms, inspection window, a non-default remedy label, and collapsed sections being closed until opened.
- Backend tests: legacy award validates with injected `{}`; v1 and v2 offer hashes both verify; `for_product` propagates catalog metadata; the buyer award preserves attributes and `binding_version`.

## 10. Phases

1. **Model and binding** — `attributes` + shim, `binding_version` on `Offer`/`AwardRequest`, versioned binding, `build_terms`, `build_projection`.
2. **Seller planner** — `for_product` fields, offer attributes, `binding_version=2`.
3. **Buyer propagation** — `build_award_request` carries attributes and the binding version.
4. **Styles** — `mm-` card rules in `globals.css`.
5. **Console contract** — orchestrator `_checkout_args`, zod schemas.
6. **Components** — `ProductSummary`, agreement card, checkout card.
7. **Tests** — console and backend.
8. **Verification** — typecheck, focused suites, full console tests.

## 11. Risks

- **In-flight checkout runs.** `paypalCheckoutArgsSchema.agreement` is required. Any run parked at `await_checkout` at deploy time has a persisted HITL payload without the field, so its card fails arg validation. Mitigation: deploy when no runs are parked at that checkpoint, or restart those runs. `await_funding_approval` payloads already carry `agreement`, so they are unaffected.
- **Digest and binding migration.** Attributes join the digest for new agreements; `binding_version` keeps old hashes verifiable. Existing agreements' stored `terms` are unchanged, and `AgreementProjection.canonical_payload()` hashes `terms`, not `line_items`, so defaulting `attributes={}` in `build_projection` cannot invalidate a legacy digest. This corrects revision 1's stated reason.
- **Legacy color values.** Awards created before this change may carry `attributes.color = "gray"` or `"black"`. `gray` is valid CSS and would render a dark tile; the card's hex guard prevents it, and the neutral fallback applies.
- **Style port without coverage.** The `mm-` rules are not covered by automated tests. The suites assert structure and content, not visual parity; the CSS needs a manual look in the rail.
- **Metadata quality.** A single-product policy has no description or emoji, so the card shows a neutral tile and `📦`, and omits the specs chip.

## 12. Acceptance criteria

1. Both cards render product summary, commercial terms, and (for the agreement) obligations, evidence, inspection, remedies/dispute window, acceptance, and digest from the canonical agreement's `terms`.
2. The checkout card renders the server-authoritative amount and flags any divergence from the agreement total.
3. All existing PayPal flow tests (create/capture/poll/cancel/fallback/error) still pass, including the `$3,400.00` amount assertion.
4. All existing agreement decision tests (approve/reject/request changes, note, error) still pass.
5. No Tailwind palette utilities appear in either card; new styles use `mm-` classes built on existing `--paper`/`--panel`/`--ink`/`--signal`/`--rule` variables.
6. An award persisted without `attributes` and a v1 offer binding both still validate, verify, and render.
