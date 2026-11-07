# Seller Workspace — Clerk Access Migration (Fix "Seller access is required")

**Date:** 2026-11-07  
**Status:** Approved design (brainstormed) — not yet implemented  
**Issue:** Verified sellers see `Seller access is required` on `/seller/dashboard` (and other workspace views) because the console workspace uses a legacy cookie/transaction-scoped seller bearer token, while verification/onboarding is now Clerk/control-plane based.

## Problem

- **Workspace gate (new):** `apps/console/app/seller/layout.tsx` + `lib/seller-access.ts` allow seller workspace access for a Clerk org with a seller profile (non-suspended) via `GET /v1/seller/onboarding` (`controlPlaneForUser`).
- **Workspace data (legacy):** `dashboard/orders/fulfillment/evidence/payouts` and detail pages call `loadSeller` in `apps/console/lib/seller-api.ts`, which requires an HttpOnly `verifund_seller_sessions` cookie (`sellerToken()` throws `SellerApiError("Seller access is required", 401)` at `:163-171`). Cookies are only created by legacy invitation exchange (`exchangeInvitation`/`saveSellerToken`) — **not** by Clerk verification.
- **Control plane (legacy):** `apps/verifund_control_plane/.../api/seller.py` authenticates `/seller/transactions*`, `/seller/evidence`, `/seller/payouts`, `/seller/agreements*` with `SellerTokenService`/`app.state.tokens` (per-txn bearer token, revocation, agreement-hash binding). No Clerk path exists for these routes.
- **Related migration:** “Seller access from Clerk, not the cookie” (`docs/superpowers/plans/2026-11-06-verifund-multi-tenancy-implementation.md`, Task 21).

## Decisions (confirmed)

1. **Scope:** full seller workspace — dashboard, orders, fulfillment, evidence/payouts views, detail/activity/evidence subpages, and evidence upload/download/dispute-evidence proxies.
2. **User/console auth:** **Clerk-only** for migrated `/seller/*` user access (no legacy seller bearer tokens for console users).
3. **Settlement auth:** trusted `seller_agent` settlement/evidence automation uses **internal service auth** (not legacy seller tokens, not Clerk browser sessions).

## Goals / Non-goals

**Goals**
- Verified Clerk sellers load the seller workspace without “Seller access is required”.
- CP `/seller/*` workspace routes authorize via a resolved seller principal: Clerk identity or verified internal service auth (settlement) — fail closed.
- Console reads/writes/proxies use Clerk auth; settlement uses internal service auth + the CP’s supported evidence contract.
- Preserve tenant isolation and existing business rules; update affected in-repo callers/tests.

**Non-goals**
- Preserving legacy `verifund_seller_sessions` cookie / `SellerTokenService` bearer auth on migrated routes.
- Reintroducing `kind`-based evidence upload (CP already requires `requirement_id`).
- Broad refactors unrelated to auth/scoping/migration.

## Approach A (approved)

Unified `SellerPrincipal` resolver on CP, Clerk-only console access, internal service auth for settlement, route-by-route migration with parity and fail-closed scoping.

## Section 1 — Control plane: seller principal, auth, and scoping

### 1.1 `SellerPrincipal`
Resolved only by the server (never from request body/query): `seller_id`, `organization_id`, `actor`, `auth_kind` (`clerk|internal_service`), effective scopes/capabilities (e.g. `txn:read`, `evidence:write`).

### 1.2 Resolver (e.g. `apps/verifund_control_plane/.../api/seller_auth.py` or `api/seller.py`)
**A. Internal service (settlement):** triggered by an explicit internal header (e.g. `X-Verifund-Internal-Token`). Constant-time verify against a dedicated setting (recommend `VERIFUND_SETTLEMENT_INTERNAL_TOKEN` / `settings.settlement_internal_token`; CP and seller agent share it). Require explicit context headers (e.g. `X-Organization-Id` and/or `X-Seller-Id`) and validate against the resolved seller profile/target transaction — **fail closed** (401/403/404; do not leak). Grant only settlement-needed scopes.

**B. Clerk (console/user):** if not valid internal service auth, `require_identity(request)`. Resolve seller profile by `identity.tenant_id` (`get_seller_profile_by_organization`); require eligible business/seller context (fail closed). Derive `seller_id`/org; map role/permissions to read/write scopes.

**C. Legacy:** **removed** from migrated routes — no `app.state.tokens.verify` / `SellerTokenService`.

### 1.3 Authorization & scoping (fail closed)
- **Lists** (`GET /seller/transactions|evidence|payouts`): scope to principal `seller_id` (and support `seller_organization_id` matching for transitional data only where needed, tested). Reject client `seller_id` filter.
- **Per-txn** (detail, events, evidence list/download, upload, dispute-evidence, declarations): load txn (404 missing). Authorize if `txn.seller_id == principal.seller_id` OR (when set) `txn.seller_organization_id == principal.organization_id`; deny cross-tenant (404/403 per existing isolation semantics, e.g. `test_tenant_isolation`/participant gates).
- **Writes:** require write scope; preserve state/hash/agreement/validation rules. Actor = principal actor.
- **Download:** same ownership check; stream from evidence store with correct headers.
- **Rate limit:** re-key off principal (not legacy claims).

## Section 2 — Control plane route migration

**Files:** primarily `apps/verifund_control_plane/verifund_control_plane/api/seller.py`; minimal `service.py`/`repository.py` only if scoping/backfill requires it; settings for settlement internal token.

- Replace `authenticate`/`authenticate_seller` and legacy token checks (including token-vs-agreement-hash binding, which is token-specific) with principal resolver + `authorize_transaction`.
- Maintain request/response parity: list filters/pagination/cursor validation, 400 on disallowed `seller_id`/bad params, multipart evidence/dispute uploads, `requirement_id` required + `kind` rejected (422), agreement/version/state checks.
- Service/repo: prefer existing `seller_id`-scoped methods (`list_transactions_keyset`, `counts_by_state`, evidence/payout/events/agreement) with the resolved stable `seller_id`; add targeted `seller_organization_id`-aware scoping only if necessary and covered by isolation tests.

## Section 3 — Console workspace & proxies

**Files:** `apps/console/lib/seller-api.ts`, seller workspace pages under `app/seller/*` (dashboard, orders, fulfillment, evidence, payouts, fulfillment detail/activity/evidence), API proxies under `app/api/seller/transactions/[id]/...`, and cleanup in `app/seller/actions.ts` as needed.

- Refactor `seller-api.ts` to a Clerk-based implementation (`controlPlaneForUser`) while preserving `SellerResult<T>`/`SellerApiError`/`loadSeller` ergonomics for pages. Remove cookie/`verifund_seller_sessions` workspace dependency (`readSellerSession`/`sellerToken`/`saveSellerToken`/etc.) if no longer used (confirm usages; keep isolated legacy invitation helpers only if still required).
- Migrate all `loadSeller("/seller/...")` call sites (dashboard, orders, fulfillment, evidence library, payouts, fulfillment detail/activity/evidence) to Clerk-authenticated fetches; keep `auth.protect()` and existing UX.
- Proxies: `auth.protect()` + forward via `controlPlaneForUser`. For uploads, pass `FormData` body without forcing `content-type` (preserve multipart boundary). For download, proxy status/body/`content-type`/`content-disposition` from CP. CP enforces org ownership.

## Section 4 — Settlement/internal callers, tests, rollout

### 4.1 Settlement & evidence outbox
- **`apps/seller_agent/seller_agent/settlement.py`:** internal service auth headers + required context; no legacy seller bearer token.
- **Contract alignment:** update upload to CP’s supported contract (`requirement_id`, file/reference/reference_type, `agreement_version`/note/captured_at as applicable) — **not** `kind`.
- **`evidence_outbox.py`, `store.py`/`shared_store.py`, enqueue sites (`graph.py`), `server.py`/settings:** replace per-txn legacy settlement token flow with internal-auth context; migrate outbox payload/schema/uniqueness from `kind` semantics to `requirement_id` (or equivalent) with a safe migration for existing local data; preserve idempotency/dedup.
- Wire `VERIFUND_SETTLEMENT_INTERNAL_TOKEN` (or chosen name) in CP and seller agent config/compose/env docs.

### 4.2 Callers/tests
- Update in-repo callers (`packages/verifund_contracts`, scripts) and **CP/seller_agent tests** that hit migrated `/seller/*` with legacy seller tokens to use Clerk identity fixtures/mocks or internal service auth. Preserve cross-tenant isolation assertions.
- Validate: targeted CP seller/tenancy/isolation suites, onboarding/agent flows, settlement/outbox tests, console vitest + `tsc --noEmit`. Run broader/full suite and report evidence; distinguish pre-existing/flaky failures (a prior full run showed non-isolated failures) from regressions.

### 4.3 Manual verification (sandbox)
Verified Clerk seller: `/seller/dashboard` no longer shows “Seller access is required” (loads data or empty state); orders/fulfillment/evidence/payouts/detail/activity work for owned txns; upload/dispute/download proxies work; settlement (if enabled) uploads via internal auth; cross-org access denied.

### 4.4 Risks
- **Blast radius:** tests/callers across CP, seller_agent, contracts/scripts (many legacy token references). Mitigate by incremental migration and targeted test runs.
- **Data backfill:** `seller_organization_id` may be null on older records; scope by `seller_id` (resolved from seller profile) and/or support safe OR-matching where verified, never weakening isolation.
- **Settlement contract:** outbox was `kind`-based while CP requires `requirement_id` — must be aligned as part of this migration.
- **Full-suite flakiness:** treat non-deterministic failures with evidence (isolation checks) and do not mask regressions.
