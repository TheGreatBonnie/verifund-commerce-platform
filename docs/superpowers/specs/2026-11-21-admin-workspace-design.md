# Admin Workspace — Clerk-Gated Platform Operations

**Date:** 2026-11-21
**Status:** Approved design (brainstormed + grilled) — not yet implemented
**Scope:** `apps/console` on `deploy/console`; backend changes on `deploy/render`
**Related:** `docs/superpowers/specs/2026-11-07-seller-workspace-clerk-access-design.md`,
`docs/superpowers/specs/2026-11-07-buyer-workspace-clerk-access-design.md`,
`docs/superpowers/specs/2026-11-06-verifund-multi-tenancy-design.md`,
`docs/auth-boundaries.md`

## Problem

The console has a seller workspace (`app/seller/**`, gated by `app/seller/layout.tsx:18-21`
via `lib/seller-access.ts`) and a buyer surface (`(public)` + `(console)`, gated by
`consoleSession()`). There is no admin workspace. Earlier multi-tenancy work deliberately
deferred a platform-admin UI (`2026-11-06-verifund-multi-tenancy-design.md:170`) and sketched
an `(console)/admin/verification/**` path (`:1063`) that was never built.

Today:

- `apps/console/lib/user-role.ts:3` defines `UserRole = "buyer" | "seller"`. The only
  Clerk role write is `promoteUserRole()` (`:5-7`) into `publicMetadata.role`. The only
  read is `app/post-auth/page.tsx:27-28`, whose `isRole()` guard (`:8-10`) rejects any
  other value — an `admin` value would send the user to `/choose-role`, which offers
  only buyer/seller and would overwrite the role.
- `deploy/render` already has a `platform_admins` table
  (`tenancy/repository.py:84-90`), `add_platform_admin`/`is_platform_admin`
  (`:484-501`), `require_platform_admin()` (`tenancy/routes.py:28-37`), and
  `GET /v1/me` returning `is_platform_admin` (`:83-95`). No console caller uses
  `/v1/me`, and no backend Python code reads Clerk `publicMetadata`.
- `PAYPAL_PLATFORM_EMAIL` is only a PayPal Business-account setting
  (`settings.py:162-163`, validation at `:268`). The ledger has a `platform_cash`
  account (`domain.py:280-290`), but transactions are owned only by `buyer_id`,
  `seller_id`, and organization id. There is no platform-side owner principal.
- Route protection is `auth.protect()` per file; `proxy.ts:1-3` is only
  `clerkMiddleware()` and a static test (`tests/app/route-guards.test.ts:40-55`)
  requires every non-public server page, route, and action to contain the literal
  string `auth.protect()`.

## Decisions (confirmed)

1. **Scope:** full ops suite in this slice — overview, platform transactions, ledger,
   audit, payouts, disputes, seller verification, read-only users, and settings.
2. **Role granting:** out-of-band only. `publicMetadata.role = "admin"` is set in the
   Clerk Dashboard or by a backend script. No self-service or in-app promotion.
3. **Denied access:** a signed-in non-admin navigating to `/admin` is silently
   redirected to `/`; no 403/404 page and no explanation.
4. **Admin reach:** additive. Admins keep buyer and seller workspace access and get an
   `Admin` link in both headers.
5. **Source of truth:** Clerk `publicMetadata.role` is authoritative; the existing
   verified Clerk webhook mirrors it into `platform_admins` so backend
   `require_platform_admin()` checks stay fail-closed.
6. **Route placement:** a top-level `/admin` tree mirroring `/seller`, with its own
   layout, nav, and gate. Not nested under the `(console)` buyer group.
7. **Users screen:** read-only. No in-app promote/demote UI.
8. **Platform ownership:** the platform is an explicit transaction participant keyed to
   `PAYPAL_PLATFORM_EMAIL`, stamped on transactions. Admins act as the platform owner;
   audit records both the human actor and the platform account.
9. **Platform actions in this slice:** oversight (list/detail/ledger/audit) plus
   payout-release approval and dispute/refund oversight. Admin does **not** gain buyer
   decision or seller fulfillment powers.

## Goals / Non-goals

**Goals**

- A signed-in Clerk admin can reach `/admin` and use the full ops suite.
- Non-admins cannot reach any `/admin` page or `/v1/admin/*` endpoint.
- Clerk role changes grant and revoke platform-admin authority on the backend.
- Platform-owned transactions are identifiable by the configured platform PayPal email
  and are visible/actionable only through the admin workspace.
- All existing buyer/seller isolation and audit invariants remain intact.

**Non-goals**

- In-app role management, admin signup, or an admin role in the `/choose-role` picker.
- Replacing the machine ops token for service automation; it stays for webhooks and
  internal jobs.
- Full buyer/seller action authority for admins.
- A separate deployment or Clerk Organization for admins.

## Approach (approved)

Mirror the seller workspace pattern: a top-level route tree with a server-side gate,
Clerk-derived identity, and fail-closed backend authorization. Add a server-derived
platform-owner principal so the admin workspace owns `PAYPAL_PLATFORM_EMAIL`
transactions without granting any user buyer/seller ownership by accident.

Implementation is sequenced in four milestones inside this single spec: (1) role sync
plus console gate and navigation, (2) platform principal and transaction ownership,
(3) the ops pages, (4) tests and rollout validation.

## Section 1 — Clerk role becomes the backend source of truth (`deploy/render`)

- Extend `apps/verifund_control_plane/verifund_control_plane/tenancy/sync.py`
  (`apply_clerk_event`) so `user.created` and `user.updated` reconcile
  `publicMetadata.role` into the `platform_admins` table, and `user.deleted` removes
  the row. Only Svix-verified and deduplicated events reach this code
  (`api/webhooks.py:97-127`); no unverified request may grant authority.
- Add an idempotent set/revoke helper beside `add_platform_admin` in
  `tenancy/repository.py:484-501`; the existing helper can only insert, so a demotion
  from `admin` to `buyer`/`seller` must explicitly delete the row.
- Reconciliation is by resolved local `user_id` from `upsert_user` (never by a
  client-supplied id). After sync, `require_identity()` continues to set
  `Identity.is_platform_admin` from `store.is_platform_admin(user["id"])`
  (`tenancy/identity.py:87,120`), and `GET /v1/me` reports the flag.
- The backend still does not trust `publicMetadata` directly at request time; it trusts
  the mirrored DB row. This keeps the existing audit trail and 403 behavior of
  `require_platform_admin()` (`tenancy/routes.py:28-37`).

## Section 2 — Console role vocabulary and post-auth routing (`deploy/console`)

- `lib/user-role.ts:3`: extend the union to `"buyer" | "seller" | "admin"`.
  `promoteUserRole()` keeps its current behavior; it is not called with `admin` from
  any user-facing flow.
- `app/post-auth/page.tsx:8-10`: extend `isRole()` to accept `admin`; at `:42-49`,
  route `admin` to `/admin` before the seller/buyer branches. An admin with no role
  metadata still goes to `/choose-role` only if genuinely unrecognized.
- `app/choose-role/page.tsx` / `actions.ts`: if the current user's role is `admin`,
  redirect to `/admin` and do not render the chooser, so an admin cannot demote
  themselves through the buyer/seller picker.
- `components/layout/console-layout.tsx:50,55`: leave the two sign-up buttons as
  buyer/seller; do not add an admin signup option.

## Section 3 — Admin workspace routing, layout, and gate

- New `app/admin/layout.tsx`, modeled on `app/seller/layout.tsx:18-21`:
  `const admin = await adminAccess(); if (!admin) redirect("/");`
  then render admin chrome (`components/admin/admin-nav.tsx`, `UserButton`,
  sign-out action, and a marketplace link back to `/`).
- New `lib/admin-access.ts`: call `consoleSession()` (which runs `auth.protect()`),
  then `controlPlaneForUser("/v1/me")`, and return `true` only for a 2xx response whose
  JSON has `is_platform_admin === true`. Return `false` on non-2xx, malformed JSON, or
  network failure. Do not use `controlPlaneAsPlatform`; the request must carry the
  signed-in user's Clerk token (`lib/control-plane.ts:6-19`).
- Every server page, route handler, and action under `app/admin/**` contains a literal
  `auth.protect()` call to satisfy `tests/app/route-guards.test.ts:51-53`. The layout
  gate is defense in depth, not a substitute for the per-file guard.
- Non-admin pages redirect to `/` as decided; API routes under `app/api/admin/**`
  return 403 when `adminAccess()` is false.

## Section 4 — Platform-owner principal and transaction ownership (`deploy/render`)

- Add a server-derived platform principal named `PLATFORM_OWNER_IDENTITY` in
  `tenancy/identity.py`, whose account key is `settings.paypal_platform_email`. It is
  never accepted from headers, body, or query.
- Add `platform_account_email` to the transaction record, stamped at checkout/capture
  from server settings near `domain.py:280-290` and persisted in the repository. Do not
  infer ownership by querying current config at read time; the stamp records which
  platform account settled that transaction.
- Add `authorize_platform_transaction(principal, txn, settings)`: the admin workspace
  may act on a transaction only when `txn.platform_account_email ==
  settings.paypal_platform_email`. Mismatches return 404 so cross-account existence
  does not leak, matching the seller/buyer fail-closed pattern
  (`api/seller_auth.py:140-157`).
- Admin actions execute as the platform owner. Audit entries record the exact actor
  string `user:{clerk_user_id} acting for platform:{email}` through
  `repository.record_audit`, so no action is attributed to an anonymous system actor.
- Cross-tenant reads use `TenantScope(..., include_all=True)` explicitly
  (`tenancy/tenant_repository.py:15-24`) and are always paired with the platform-account
  filter. Platform-admin status alone never widens ordinary tenant-scoped queries.

## Section 5 — Admin pages and data contracts

All pages are server components under `app/admin/`, each with `auth.protect()`, the
layout gate, and data fetched via `controlPlaneForUser`.

| Route | Purpose | Backend contract |
|---|---|---|
| `/admin` | Overview: pending verifications, platform-held funds, open disputes, links | `GET /v1/admin/overview` (new) |
| `/admin/transactions` | Platform-owned transaction list with state/seller/buyer/date filters | `GET /v1/admin/transactions` (new), scoped by `platform_account_email` + `include_all` |
| `/admin/transactions/[id]` | Detail: agreement, participants, `platform_cash`/`held_funds` ledger, evidence, timeline | `GET /v1/admin/transactions/{id}` (new) |
| `/admin/transactions/[id]/audit` | Per-transaction audit trail | `GET /v1/admin/transactions/{id}/audit` (new) |
| `/admin/payouts` | Payout-release queue and approvals | `POST /ops/transactions/{id}/payout-release` (`tenancy/routes.py:52-80`), extended to accept platform-admin identity |
| `/admin/disputes` | Read-only dispute/refund oversight on platform transactions: state, evidence, and timeline. No buyer decision or refund execution in this slice | New list/detail endpoints under the platform-owner gate |
| `/admin/verification` | Seller verification review queue | `POST /ops/sellers/{id}/verification` (`tenancy/routes.py:40-49`) plus a new pending-sellers list |
| `/admin/users` | Read-only directory of users, roles, org memberships, `is_platform_admin` | Server-side `clerkClient()` or a new read-only backend endpoint; no mutations |
| `/admin/audit` | Global audit log with filters | New platform-admin route over `repository.list_audit` |
| `/admin/settings` | Display the configured platform PayPal account (redacted) and linkage | Backend settings, server-only |

## Section 6 — Navigation and switching

- New `app/api/me/admin-access/route.ts`: `auth.protect()` + `adminAccess()` →
  `{ admin: boolean }`, mirroring `app/api/me/seller-access/route.ts:7-11`.
- New `components/layout/admin-link.tsx` (client), mirroring `seller-link.tsx:9-40`:
  query `/api/me/admin-access`, render nothing when false, and push `/admin` when true.
- Render `AdminLink` in the buyer header beside `SellerLink`
  (`components/layout/console-layout.tsx:63`) and in the seller topbar beside
  `MarketplaceLink` (`app/seller/layout.tsx:62`). Admin access is additive.
- Admin chrome includes a link back to `/` so an admin can return to the buyer surface;
  the existing `OrganizationSwitcher` behavior is unchanged.

## Section 7 — Backend endpoint surface (`deploy/render`)

- Add a `/v1/admin/*` router registered in
  `apps/verifund_control_plane/verifund_control_plane/app.py:241-252`, every route
  depending on `require_platform_admin()`.
- Extend the two human-relevant `/ops/*` routes (verification, payout release) to accept
  either the machine ops token or a platform-admin identity. All other `/ops/*` routes
  stay ops-token-only.
- Keep `GET /v1/me` as the console's source for the gate; no new `/api/me` contract on
  the backend.
- Repository additions: list/count platform transactions by `platform_account_email`,
  load detail with ledger and audit, and list pending seller verifications. Reuse
  existing scoped methods wherever possible; never add a client-supplied owner filter.

## Section 8 — Tests, validation, rollout

- Console unit/component tests: extend `tests/lib/user-role.test.ts` (admin value),
  `tests/app/post-auth.test.tsx` (admin → `/admin`, chooser guard), and
  `tests/app/route-guards.test.ts` (automatic for new files). Add
  `tests/lib/admin-access.test.ts`, `tests/app/admin-layout.test.tsx`, and
  `tests/components/layout/admin-link.test.tsx`.
- Backend tests: extend `tests/unit/test_platform_admin.py` for grant/revoke sync,
  platform-owner authorization, and cross-account 404; extend
  `tests/unit/test_clerk_webhooks.py` for the `user.updated` role event; add tests for
  stamped `platform_account_email` and audit actor.
- E2E: buyer hitting `/admin` lands on `/`; admin loads `/admin` and can open
  `/admin/transactions`; non-admin API calls to `/api/admin/*` return 403.
- Validation commands: console `npm run typecheck`, `npm run test`, targeted Playwright
  specs; backend targeted `uv run pytest tests/unit/test_platform_admin.py tests/unit/test_clerk_webhooks.py -q`
  plus the relevant transaction/isolation suites. Run the broader suite and report
  pre-existing/flaky failures separately.
- Rollout order: backend sync + `/v1/me` → console gate and nav → pages → tests →
  manual sandbox verification with a real Clerk admin user and the configured
  `PAYPAL_PLATFORM_EMAIL`.

## Risks

- **Role sync drift:** a missed or replayed webhook would leave stale authority.
  Mitigate with verified Svix events, dedupe, and idempotent set/revoke reconciliation.
- **Ownership ambiguity:** adding a platform participant changes who can act on a
  transaction. Mitigate by stamping `platform_account_email` server-side and failing
  closed with 404 on any mismatch; never infer by config alone.
- **Guard regressions:** a new admin page that omits `auth.protect()` fails the static
  test; the layout gate is not enough. Add the per-file guard as pages are created.
- **Ops-token overreach:** do not expose `controlPlaneAsPlatform()` or the ops token in
  admin pages; only verified webhooks and machine jobs use them.
- **Blast radius:** `/v1/admin/*` and the extended `/ops/*` routes touch tenancy and
  repository code shared with buyer/seller flows; validate targeted isolation suites
  before the broader run, and report flaky failures with evidence.
