# Buyer Workspace — Clerk Access Migration

**Date:** 2026-11-07  
**Status:** Approved design (brainstormed) — not yet implemented  
**Related:** `docs/superpowers/specs/2026-11-07-seller-workspace-clerk-access-design.md` (seller parity reference)

## Problem

Buyer-side access still relies on legacy auth patterns that do not match the Clerk-based model now used for seller workspace access:

- **Control plane buyer actions:** `apps/verifund_control_plane/verifund_control_plane/api/buyer.py` authenticates `/buyer/transactions/{id}/delivery-confirmed|accept|dispute` with `BuyerTokenService` bearer tokens (`txn:buy`, `typ=buyer_txn`) and repo-stored token revocation/ownership checks.
- **Agreements buyer decisions:** `agreements/routes.py` / `agreements/service.py` use agreement approval tokens (`X-Approval-Token`) and buyer bearer token read branches in places; console agreement decision flow fetches an approval token then posts a buyer decision.
- **Buyer token lifecycle:** `BuyerTokenService`/`buyer_tokens`, ops `POST /transactions/{id}/issue-buyer-token`, and service issuance paths remain.
- **Console:** there is no dedicated `/buyer/*` workspace. Buyer-touching surfaces include agreement decisions/pages/proxies, runs/stream views proxied to the buyer agent, CopilotKit, marketplace/seller-dashboard proxies, and settings. Some paths use `controlPlaneForUser` (Clerk→CP) while others use static tokens to the buyer agent (`x-marketmesh-console-token`, internal tokens) and buyer-agent console APIs enforce token+`organization_id` patterns.
- **Buyer agent:** `apps/buyer_agent` calls control plane with ops/actor-style auth (`BuyerSettlementClient`/`VerifundClient`), uses `X-Approval-Token`/buyer decision helpers, and exposes console/internal/agent APIs protected by multiple static tokens (`x-marketmesh-console-token`, `x-verifund-internal-token`, `x-marketmesh-internal-token`, `x-verifund-agent-token`).

## Decisions (confirmed)

1. **Scope:** **full parity** with the seller Clerk migration for migrated buyer paths — replace legacy `BuyerTokenService`/`buyer_txn` bearer auth on migrated control-plane buyer/agreement routes with a resolved `BuyerPrincipal` (Clerk for console/user actions, internal service auth for trusted automation), fail-closed tenant scoping, **no legacy buyer bearer tokens on migrated routes**.
2. **Buyer identity model:** buyers are **individual Clerk users** in the product model. Resolution uses a **direct `clerk_user_id → buyer_profile` mapping** (new `buyer_profiles.clerk_user_id` column, unique): Clerk identity provides `identity.clerk_user_id` (from `sub`) which resolves to the stable `buyer_id` (`get_buyer_profile_by_clerk_user_id`). **`organization_id` is deliberately NOT part of `BuyerPrincipal`** — buyers have no business org; the personal org in tenancy exists only for Seller/other tenant features. Ownership is `txn.buyer_id == principal.buyer_id` only (no `buyer_organization_id` OR fallback). Internal service auth resolves the same way via `x-buyer-clerk-user-id` (fallback: `x-buyer-id` → profile → `clerk_user_id`).
3. **Console:** migrate **existing buyer-touching surfaces** (agreements buyer decisions, agreement pages/proxies, runs tied to buyer org, related proxies) to Clerk auth — do **not** require creating a full `/buyer/*` workspace in this migration.
4. **Control plane routes:** migrate **both** `api/buyer.py` actions (`delivery-confirmed`, `accept`, `dispute`) **and** agreements buyer-decision paths (and buyer-related agreement auth where applicable).
5. **Agreement approval tokens:** **replace `X-Approval-Token` buyer-decision flow with `BuyerPrincipal`-only decisions**. Preserve security invariants with required server-validated `agreement_version` + `agreement_hash`, required `Idempotency-Key`/idempotent replay semantics, and fail-closed ownership/state/scope checks.
6. **Automation:** buyer agent settlement/automation → CP uses **dedicated internal service auth** (new token), not Clerk browser sessions and not legacy buyer bearer tokens.
7. **Scopes:** mirror seller-style scope/capability mapping from Clerk buyer role/permissions; settlement/internal gets only minimal required scopes.
8. **Legacy:** remove legacy buyer bearer token checks from migrated routes; **deprecate/disable** `BuyerTokenService` issuance / ops `issue-buyer-token` for migrated flows.
9. **Error semantics:** match seller **fail-closed** pattern — 401 unauthenticated; prefer 404 to avoid leaking cross-tenant resource existence where appropriate; 403 only where safe/explicit per existing isolation semantics.
10. **Buyer agent:** **full auth overhaul** across buyer_agent→CP settlement auth and buyer agent exposed/internal/agent auth surfaces impacted by this migration (larger blast radius; see Section 4).

## Goals / Non-goals

**Goals**
- Clerk-authenticated buyers can perform migrated agreement decisions and buyer actions on **owned** resources without legacy buyer bearer/approval tokens.
- CP migrated buyer/agreement routes authorize via a resolved `BuyerPrincipal` (Clerk or verified internal service auth) — fail closed.
- Console migrated surfaces use Clerk auth; buyer agent automation uses internal service auth; ownership is enforced server-side.
- Preserve tenant isolation and existing business/state-machine rules; update affected in-repo callers/tests.

**Non-goals**
- Creating a full `/buyer/*` console workspace.
- Preserving legacy `BuyerTokenService` / `buyer_txn` bearer auth or `X-Approval-Token` buyer decisions on migrated routes.
- Broad refactors unrelated to auth/scoping/migration.

## Approach A (approved)

Mirrored `BuyerPrincipal` migration (seller pattern): new buyer principal resolver, route-by-route CP migration, agreement decision semantic change with explicit invariants, dedicated buyer settlement internal token, full buyer agent auth overhaul as scoped, incremental validation.

## Section 1 — Control plane: buyer principal, auth, and scoping

### 1.1 `BuyerPrincipal`

Resolved only by the server (never from request body/query):

- `buyer_id: str` — stable buyer identifier used by transactions/agreements/service APIs
- `clerk_user_id: str | None` — Clerk `sub` used to resolve `buyer_id` (Clerk path); sourced from `buyer_profiles.clerk_user_id` for internal-service path (may be `None` only for legacy seed rows without a linked Clerk user — then Clerk auth fails closed)
- `actor: str` — audit actor (`user:{local user_id}` for Clerk, `service:buyer-settlement` for internal)
- `auth_kind: "clerk" | "internal_service"`
- `scopes: set[str]` / capability flags (e.g. `txn:read`, `txn:act`, `agreement:decide`, `evidence:read`/`write` as needed)

### 1.2 Resolver (new `apps/verifund_control_plane/verifund_control_plane/api/buyer_auth.py`, mirroring `seller_auth.py`)

Resolution order is explicit and fail-closed:

1. **Internal service (buyer agent automation/settlement):** `X-Verifund-Buyer-Internal-Token` constant-time compared to `settings.buyer_settlement_internal_token` (`VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN`, shared by CP + buyer agent). Require `X-Buyer-Clerk-User-Id` (fallback: `X-Buyer-Id` → profile → `clerk_user_id`). Validate against `buyer_profiles.clerk_user_id`/`buyer_id` and target resource — **401** invalid/missing token, **404/403** fail-closed on ownership/context mismatch (no existence leak). Grant only minimal scopes needed.

2. **Clerk (console/user):** if not internal service auth, `require_identity(request)`. Resolve **directly by `identity.clerk_user_id`** via `get_buyer_profile_by_clerk_user_id` (fail closed 403 if no linked profile). `BuyerPrincipal.clerk_user_id = identity.clerk_user_id`. Role/permissions still gate scopes (`org:buyer` `approve` → `txn:act`/`agreement:decide`), but tenant is **not** used for buyer identity. **401** unauthenticated, **404/403** fail-closed.

3. **Legacy removed from migrated routes:** no `BuyerTokenService.verify` / `buyer_txn` bearer, no `X-Approval-Token` decision auth on migrated agreement buyer-decision paths, no static console token auth for migrated buyer surfaces.

### 1.3 Authorization helpers

- `require_buyer_principal(request, ...)` → `BuyerPrincipal`
- `authorize_transaction_buyer(principal, txn)` / `authorize_agreement_buyer(principal, agreement)` — load resource, enforce `txn/agreement.buyer_id == principal.buyer_id` with **fail-closed 404** where appropriate. Reject client-supplied `buyer_id` filters on lists.
- Scope checks (e.g. `require_scope(principal, "txn:act")`) return safe errors per design.
- Rate limiting re-keyed off principal (not legacy claims).

## Section 2 — Control plane route migration

### 2.1 `api/buyer.py` (migrated to `BuyerPrincipal`)

- Replace `authenticate_buyer` (bearer `txn:buy` + `buyer_tokens` repo checks) with `require_buyer_principal` + `authorize_transaction_buyer`.
- **Routes:** `POST /buyer/transactions/{id}/delivery-confirmed|accept|dispute`
  - Load txn, authorize ownership (fail-closed). Require action scope.
  - Preserve request/response parity and business rules: `confirm_delivery` body (`confirmed_at`, `condition`, `photos`, `carrier_event_at`); `accept` semantics (idempotent terminal handling, dispute-open blocked, payout start); `dispute` validation/allowed states and invalid-dispute audit-without-transition behavior.
  - Actor = `principal.actor`.

### 2.2 `agreements/routes.py` (buyer-auth paths)

- **`POST /agreements/{id}/buyer-decision` (breaking semantic change, approved):** remove `X-Approval-Token` requirement/consumption for buyer decisions on migrated path. Require `BuyerPrincipal` + ownership of agreement/transaction + scope (e.g. `agreement:decide`/`txn:approve`).
  - **Required safety invariants (replacing approval token proof):** request must include `agreement_version` and `agreement_hash`; server validates against current agreement version/hash (reject stale/mismatch). Require `Idempotency-Key` (header and/or body as contract specifies) and enforce idempotent replay semantics. Allowed only in valid state (e.g. `PENDING_BUYER`) with same transition rules (APPROVE→`AGREED` + txn pointer sync/legacy agreement-token revocation behavior as applicable; REJECT→`REJECTED`; REQUEST_CHANGES→`CHANGES_REQUESTED` + change request). **Fail closed** on ownership/state/hash/version/scope mismatch.
- **`POST /agreements/{id}/approval-token`:** deprecate/remove for migrated console/user flow (or restrict to ops/internal only if a justified non-user caller remains). Must not bypass `BuyerPrincipal` ownership checks where user context applies.
- **Read/list auth (`_authorize_agreement_read` and list endpoints):** replace buyer bearer `buyer_tokens.verify(..., txn:buy)` branch with `BuyerPrincipal` resolution/ownership for user reads where feasible; keep/adjust ops and seller token read paths only if still valid and out of buyer-migration scope (document). List-all remains ops/platform-scoped unless explicitly changed.
- **Other agreement routes** (seller-decision, change-request resolution, document/version): update buyer-related authorization to fail-closed principal checks where they accept buyer context; preserve existing seller/ops contracts.

### 2.3 `api/ops.py` and legacy issuance

- `POST /transactions/{id}/issue-buyer-token`: **deprecate/disable** for migrated flows (exact response: 410/403/404-safe error chosen in implementation; update callers). `service.issue_buyer_token` / `BuyerTokenService` removed from migrated paths; keep minimal compatibility only if required for explicitly identified out-of-scope legacy callers.

### 2.4 Service/repository/settings

- **Settings:** add `buyer_settlement_internal_token` / `VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN` (and wire into app state as needed).
- **Service (`service.py`):** `confirm_delivery`, `buyer_accept`, `open_dispute` accept authorized `buyer_id`/principal context (no reliance on legacy token claims). Agreement service `record_buyer_decision`/related methods refactored for no `X-Approval-Token` consumption path while preserving audit events/state-transition invariants.
- **Repository:** buyer lists scoped to principal; ownership via resolved `buyer_id` only. `buyer_tokens` table: no new writes. Resolver uses `buyer_profiles.clerk_user_id` (new unique column; `organization_id` column retained only for seed/backfill compat, not used for Buyer auth).

## Section 3 — Console migration (existing buyer-touching surfaces)

### 3.1 Agreement buyer decisions

- **Files (expected):** `apps/console/app/(console)/agreements/[id]/actions.ts`, `AgreementDecisionPanel.tsx`, `app/api/agreements/[id]/approval-token/route.ts` (remove/change), `app/api/agreements/[id]/buyer-decision/route.ts`, related agreement pages/components.
- Keep `auth.protect()` / Clerk session. **No approval-token fetch or `X-Approval-Token` header.** Call CP `buyer-decision` via `controlPlaneForUser` with `agreement_version`, `agreement_hash`, `decision`, note/reason fields per contract, plus `Idempotency-Key`. Preserve UX and orchestrator resume behavior (`/verifund/resume-agreement`) if still applicable.

### 3.2 Agreement reads/pages

- Verify/update agreement proxies/pages using `controlPlaneForUser` to align with migrated CP read auth. No static buyer tokens.

### 3.3 Runs / buyer-agent backed surfaces

- **Files (expected):** `apps/console/lib/buyer-proxy.ts`, `app/api/runs/route.ts`, `app/api/runs/[runId]/stream/route.ts`, other buyer-agent proxies.
- Replace static `x-marketmesh-console-token` / ad-hoc token usage for migrated console→buyer-agent paths with the auth contract defined by the buyer agent overhaul (Clerk-derived identity/org proof or explicit validated boundary). Maintain fail-closed `organization_id`/ownership scoping. Preserve SSE/binary/content headers.

### 3.4 CopilotKit / marketplace / other touchpoints

- Review `app/api/copilotkit/[[...slug]]/route.ts`, marketplace/seller-dashboard proxies and related config. Migrate buyer-console auth assumptions impacted by the overhaul; keep unrelated seller/internal contracts stable unless intentionally changed and tested.

### 3.5 Config/docs

- Update `.env.example` and console env usage for new/renamed tokens; remove legacy buyer approval-token/bearer console flow references.

## Section 4 — Buyer agent (full auth overhaul), settlement, callers/tests, rollout

### 4.1 Buyer agent → Control Plane

- **`settlement_client.py` / `VerifundClient` usage / agreement service paths:** use internal service auth (`X-Verifund-Buyer-Internal-Token` + explicit context headers) for migrated CP buyer/agreement/settlement operations. CP validates context server-side (fail-closed). `buyer_decision` sends `agreement_version`, `agreement_hash`, `decision`, `idempotency_key` (no `X-Approval-Token`). Remove/repurpose `issue_approval_token` per migrated contract. Update `precheck`/buyer review paths to migrated contract. Do not break unrelated seller/accept flows.

### 4.2 Buyer agent exposed APIs (full overhaul)

- **`console_api.py` / `settlement_api.py` / related:** consolidate/replace `x-marketmesh-console-token`, `x-verifund-internal-token`, `x-marketmesh-internal-token`, `x-verifund-agent-token` usage with a coherent model: Clerk-derived/verifiable identity + fail-closed org ownership for console/user paths; explicit least-privilege internal tokens for service/agent boundaries. Update `authorize_run_stream`, run listing, and settlement projection gating to enforce ownership (404 on cross-org/missing). `organization_id` must not be trusted from client without verification in the chosen model.

### 4.3 Data/migrations and legacy cleanup

- Ensure `buyer_profiles`/`buyer_organization_id` resolution is reliable for migrated environments (use existing tenancy/backfill; fail closed if profile cannot be resolved safely). No isolation weakening.
- `buyer_tokens`: no writes from migrated flows; issuance deprecated/disabled for migrated flows. Optional cleanup/revocation documented.
- Agreement approval-token infrastructure: retire buyer-decision dependency; keep only if justified for out-of-scope flows.

### 4.4 Callers, tests, config, docs

- Update `packages/verifund_contracts`, `scripts/*` (including buyer-touching flow scripts), console routes, and CP/buyer agent integration points.
- Add/update `tests/support/buyer_auth.py` (Clerk/internal helpers) mirroring seller. Migrate CP tests for `/buyer/*` and agreements buyer decisions; preserve cross-tenant isolation, hash/version mismatch, idempotency replay, and state-machine/dispute/accept invariants. Update buyer agent and console tests.
- Config/docs: `.env.example` + service docs for `VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN` and renamed headers/tokens; update relevant workspace/docs and spec status after implementation verification.
- **Validation:** targeted CP (buyer routes, agreements, tenancy/isolation), buyer_agent, console `tsc --noEmit` + vitest; broader/full suite with evidence (separate pre-existing/flaky failures).

### 4.5 Manual verification (sandbox)

Clerk buyer (individual user resolved to eligible buyer profile/org context) can: perform migrated agreement decisions and `/buyer/*` actions on owned resources; see migrated runs/agreements surfaces as intended. Buyer agent automation works with internal auth. Cross-tenant/cross-buyer access denied (fail-closed, no leakage). Legacy buyer bearer/approval-token paths no longer authorize migrated routes.

### 4.6 Risks

- **Approval-token removal** changes agreement security/UX contract — mitigate with strict hash+version+idempotency+ownership checks and regression tests.
- **Buyer profile resolution** depends on tenancy data quality/personal-org mapping — fail closed; document prerequisites/backfill.
- **Full buyer agent auth overhaul** has large blast radius — migrate incrementally with targeted tests.
- **Shared contracts/clients** may affect other callers — scope changes and test parity.
- **Full-suite flakiness** — report evidence; do not mask regressions.
