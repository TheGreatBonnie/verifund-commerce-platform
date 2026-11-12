# Verifund Multi-Tenancy — Target Design

Date: 2026-11-06
Status: Design (26 decisions locked via three grill sessions; gate and onboarding decisions recorded 2026-11-06)
Related specs:
- `docs/superpowers/specs/2026-11-06-seller-agent-onboarding-design.md` (companion: onboarding workflow, commerce integrations, catalog, policy editor)
- `docs/superpowers/specs/verifund-multi-tenancy-recommendation.md` (organization-based tenancy recommendation)
- `docs/superpowers/specs/seller-agent-onboarding-recommendation.md` (seller and agent lifecycle recommendation)
- `docs/superpowers/specs/2026-11-04-verifund-seller-evidence-target-design.md` (seller workspace, evidence, buyer identity)
- `docs/superpowers/specs/2026-10-27-verifund-control-plane-design.md` (settlement authority)
Related code: `apps/console`, `apps/verifund_control_plane`, `apps/registry`,
`apps/buyer_agent`, `apps/seller_agent`, `apps/verifund_agent`, `packages/verifund_contracts`.

No code changes are made by this document. It is the design target for implementation.

## 1. Purpose

Verifund has no end-user identity today. Every console request acts as the platform
through a single shared ops token, human decisions are attributed to the hardcoded
strings `demo-buyer` and `demo-user`, and seller access is a transaction-scoped HMAC
cookie exchanged from a magic link. There is no organization, membership, role, or
permission table anywhere in the schema.

This document defines the target tenancy model: Clerk Organizations as the tenant
boundary, a mirrored identity and membership schema in Verifund, tenant columns on
every tenant-owned record, a single authorization path through the control plane, and
a verification gate that keeps self-serve seller creation from becoming self-serve
seller activation.

## 2. Decisions locked

### Round 1 — tenancy model (2026-11-06)

| # | Question | Decision |
|---|---|---|
| 1 | Tenant boundary | Clerk organization is the tenant; agents are scoped principals inside it |
| 2 | Personal buyer tenant key | Internal `organizations(kind='personal')` row per user, resolved from the verified `sub` |
| 3 | Seller org creation | Self-serve organization creation is allowed |
| 4 | Seller workspace access | Clerk account required; the magic link only bootstraps into the org |
| 5 | Platform Admin | Dedicated `platform_admins` table; the ops token shrinks to machine automation |
| 6 | Database isolation | Application-enforced repository with an explicit tenant scope; RLS-ready layout |
| 7 | Agent identity | First-class agent principals with per-agent credentials bound to `(organization_id, agent_id)` |
| 8 | Shared transactions | `buyer_organization_id` + `seller_organization_id`; no `transaction_participants` table yet |
| 9 | Org deletion / member removal | Soft-delete the org, read-only, counterparty retains access, no cascade deletes |
| 10 | Money actions | Re-read membership from the database for payout, refund, and release |
| 11 | Background workers | Explicit system principal with audited tenant attribution |
| 12 | Console routing | Flat routes with the active organization; backend cross-checks the token `org_id` |
| 13 | Org context in the console | Pass `organizationId` to `getToken()`; never rely on the `__session` cookie alone |

### Round 2 — verification gate and enforcement (2026-11-06)

Decision 3 allows any signed-in user to create an organization. That makes "has an
organization" and "is a seller" different facts, and the following decisions supply
the difference.

| # | Question | Decision |
|---|---|---|
| 14 | Self-serve seller activation | Organization creation is self-serve; seller capabilities require `seller_profiles.verification_status='verified'` |
| 15 | Verification state machine | `unverified → pending → verified` or `rejected`; `verified → suspended → verified`; only a platform admin moves a seller to `verified`, `rejected`, or `suspended` |
| 16 | Authorization source | The Clerk token authenticates and asserts the active organization; role and permissions are read from Verifund's mirrored membership tables |
| 17 | Non-participant response | `404 not_found` for a transaction the caller's tenant does not participate in; `403 forbidden` only inside a participant |
| 18 | Missing local tenant record | Lazy-sync the organization and membership from the Clerk Backend API before returning `403`; webhooks are not on the synchronous path |
| 19 | Demo data | The four seeded sellers are backfilled as `verified`; `demo-buyer` maps to a personal tenant |

### Round 3 — onboarding and agent lifecycle (2026-11-06)

The Clerk and seller-agent onboarding recommendation documents were analysed after
Round 2. Their stack assumptions (PostgreSQL, Next.js 16, Redis) do not match this
repository, but their lifecycle model exposed gaps: one verification axis cannot
express "verified seller, agent still configuring", and `organization.created` cannot
distinguish a buyer organization from a seller applicant.

| # | Question | Decision |
|---|---|---|
| 20 | Solo sellers | Selling requires a `kind='business'` organization; personal organizations remain buyer-only |
| 21 | Agent lifecycle authority | The control plane owns agent status, policies, activation, and credentials; the registry holds a public projection |
| 22 | Negotiation policy authority | The seller agent's store is authoritative; the control plane stores `policy_ref`, `policy_version`, and `policy_hash` |
| 23 | Suspended seller with money in flight | New business is frozen, existing transactions stay fulfillable, and payouts require an explicit platform-admin release |
| 24 | Agent activation gate | Activation requires an automated test run that passed against the current policy and card hashes |
| 25 | Seller intent | Seller onboarding is an explicit, idempotent action, not a side effect of `organization.created` |
| 26 | Agents per organization | No product cap; a configurable abuse ceiling (default 50) applies and is not a plan limit |

Decisions 1–13 are the answers recorded in the 2026-11-06 grill session. Decisions 14–19
resolve the consequences of decision 3 and the enforcement details the first round left
open. Decisions 20–26 settle the onboarding and agent lifecycle boundaries that the
recommendation documents exposed. Nothing below contradicts a locked decision.

## 3. Current state

### 3.1 Identity surfaces as built

| Surface | Identity today | Location |
|---|---|---|
| Console → control plane | Shared `VERIFUND_OPS_TOKEN` on every call | `apps/console/lib/control-plane-proxy.ts` |
| Console human identity | Hardcoded `demo-buyer`, `demo-user` | `apps/console/app/(console)/agreements/[id]/actions.ts`, `apps/console/app/api/copilotkit/[[...slug]]/route.ts` |
| Seller workspace | Transaction-scoped HMAC bearer in an HttpOnly cookie | `apps/console/lib/seller-api.ts`, `apps/verifund_control_plane/.../api/seller.py` |
| Buyer actions | Transaction-scoped HMAC bearer issued by ops | `.../api/buyer.py` |
| Agent-to-agent calls | Static per-seller bearer tokens in `.env` | `BUYER_SELLER_TOKENS`, `SELLER_*_TOKEN` |
| Registry writes | Shared admin token | `apps/registry/registry/api.py` |
| Agreement actor | Spoofable `X-Actor-Id` header, defaulting to `demo-buyer` | `.../agreements/routes.py` |

`README.md` states the position explicitly: "There is no multi-tenant authentication or
production credential exchange."

### 3.2 Data model

- `transactions` carries `buyer_id` and `seller_id` as opaque strings
  (`verifund_control_plane/repository.py`). No organization columns.
- `evidence` carries `seller_id`; there is no tenant column.
- Agreements carry `buyer_id` and `seller_id`; authorization is transaction-scoped.
- There is no `users`, `organizations`, `organization_members`, `roles`, `permissions`,
  `invitations`, `payment_accounts`, `agent_credentials`, or `audit_events` table.
- The control plane, registry, buyer agent, and seller agents are SQLite
  (`sqlite+aiosqlite`). PostgreSQL Row-Level Security is not available.

### 3.3 What is already correct and should be generalized

The seller and buyer token chains in `api/seller.py` and `api/buyer.py` already do
signature, expiry, revocation, transaction binding, and ownership checks. The seller
list endpoints derive scope from `claims.seller_id` and reject a `seller_id` query
parameter rather than ignoring it. That is the pattern the tenant layer extends: scope
comes from the verified credential, and a caller-supplied identifier is rejected, not
filtered.

### 3.4 Gaps this design closes

1. Any console visitor can act as the platform because the ops token is the console's
   identity.
2. Human actions are unattributable: the audit trail records `demo-buyer`.
3. A seller is a string, not an organization with members, roles, and a lifecycle.
4. There is no way to express that a buyer belongs to a business rather than acting as
   an individual.
5. Seller creation and seller activation are the same event.
6. Tenant-owned records cannot be listed or deleted per tenant.
7. There is no seller onboarding and no agent lifecycle. A seller profile and an agent's
   operational status are implied by configuration files, not recorded as state.

## 4. Goals and non-goals

### 4.1 Goals

- Authenticate every human through Clerk and resolve an authorized tenant context
  before any control-plane service executes.
- Mirror Clerk organizations, users, memberships, and roles into Verifund, and treat
  that mirror as the authorization source.
- Add `organization_id` to every tenant-owned record and enforce scope in one
  repository layer.
- Allow a user to belong to multiple organizations with different roles, and to switch
  workspaces without changing accounts.
- Keep buyer and seller organizations able to share a transaction without exposing
  private organizational data.
- Gate seller capabilities on platform verification while keeping organization
  creation self-serve, and let a seller start onboarding only when they choose to sell.
- Let a verified seller provision, test, and activate an agent without granting
  discovery or A2A access before the agent passes its checks.
- Preserve existing transactions, agreements, evidence, and receipts through an
  additive migration.

### 4.2 Non-goals

- PostgreSQL Row-Level Security. The layout is RLS-ready; the enforcement is
  application-level until a Postgres migration is scheduled.
- `transaction_participants`. Two organization columns express the current two-party
  reality. The table is added when a third party needs scoped access.
- Messaging channel accounts, conversations, and messages. Those tables do not exist
  in this repository.
- Redis, Redis Streams, Neon, and object-storage adapters. None are in use.
- Clerk Billing, subscriptions, seat-based pricing, and enterprise SSO. Organizations
  are the prerequisite for all three; none are implemented here.
- A platform-admin console UI. Platform administration is API-level in this phase.
- The onboarding wizard's visual design, commerce integration implementations, catalog
  and inventory schema, policy editor UI, and test-console UX. Those are scoped in the
  companion seller-agent onboarding spec; this document defines only their ownership,
  state, and authorization boundaries.

## 5. Target model

### 5.1 Three identity levels

| Level | Owner | Contents |
|---|---|---|
| Platform | Verifund | `platform_admins`, machine principals, verification review, global configuration |
| Organization | Tenant | Members, roles, agents, mandates, seller profile, payment accounts |
| User | Clerk | Global identity, email, sessions, organization memberships |

A user's role is never stored on the user. It is a property of the membership.

### 5.2 Clerk to Verifund mapping

| Clerk object | Verifund record | Notes |
|---|---|---|
| User (`sub`) | `users.clerk_user_id` | Global; may belong to many organizations |
| Organization (`o.id`) | `organizations.clerk_org_id` | Unique; internal `organizations.id` is the tenant key |
| Membership | `organization_members` | Unique `(organization_id, user_id)` |
| Role (`o.rol`) | `organization_members.role` | Mirrored; database value wins |
| Active organization | Request tenant context | Asserted by the token, verified against the mirror |
| Invitation | Onboarding path | Not an authorization grant by itself |
| Webhook events | Sync into the mirror | Identity source, never transaction authority |

The tenant key in business rows is the internal `organizations.id`, not the Clerk ID.
Clerk IDs are external identifiers that can change with an instance migration; internal
IDs keep historical transactions stable.

#### Tenant kinds

| Product concept | `organizations.kind` | Seller profile? |
|---|---|---|
| Individual buyer | `personal` | No |
| Business buyer or seller | `business` | Optional |
| Marketplace operator | `platform` | No |

The recommendation document's `INDIVIDUAL`, `ORGANIZATION`, and `MARKETPLACE` tenant
types map onto `personal`, `business`, and `platform`. They are not separate tables.

Only a `business` organization may own a `seller_profiles` row (decision 20). A personal
organization is a buyer context and cannot start seller onboarding. A solo seller
creates a business organization with one member; Clerk organization creation is one
step, and the model keeps `seller_profiles` 1:1 with Clerk organizations. The rule is
enforced in the repository, because SQLite cannot express a cross-table check
constraint.

### 5.3 Two security boundaries

1. **Tenant isolation** protects private organizational data: products, inventory,
   mandates, agent memory, payment accounts, private preferences.
2. **Transaction collaboration** lets the buyer and seller organizations read the same
   transaction with different permissions.

These are enforced by different mechanisms and must not be conflated. Tenant isolation
is a `WHERE organization_id = :tenant` discipline (and later RLS). Transaction
collaboration is an explicit participant check on two columns plus an action
permission.

## 6. Identity and session flow

### 6.1 Console

- `@clerk/nextjs` with `ClerkProvider` in `apps/console/app/layout.tsx`.
- `apps/console/middleware.ts` contains a bare `clerkMiddleware()`. Route protection is
  not centralized in middleware: this console is mostly client components that fetch
  through route handlers, so a matcher would create a false sense of protection.
- Every page, route handler, and Server Action calls `await auth.protect()` or
  `redirectToSignIn()` at its start.
- `<OrganizationSwitcher />` with personal accounts enabled is the workspace switcher.
  `<UserButton />` handles profile and sign-out.
- `apps/console/app/sign-in/[[...sign-in]]/page.tsx` and the matching sign-up route are
  public. So are `/fulfillment/access/[token]`, `/api/webhooks/*`, and health routes.
- The CopilotKit `identifyUser` callback returns the Clerk `userId`, not `demo-user`.

### 6.2 Console to control plane

The console remains a server-side proxy; the browser never receives a control-plane
credential. The proxy forwards the user's Clerk session token:

```ts
// apps/console/lib/control-plane.ts
export async function controlPlaneForUser(path: string, init: RequestInit = {}) {
  const { getToken, orgId } = await auth();
  const token = await getToken({ organizationId: orgId ?? undefined });
  if (!token) throw new Error("not signed in");
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
  return fetch(`${process.env.VERIFUND_CONTROL_PLANE_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}
```

`organizationId` is always passed explicitly (decision 13). The `__session` cookie is a
singleton for the browser, so a background fetch or a second tab can otherwise carry
the wrong organization.

The existing `controlPlaneJson()` remains, renamed `controlPlaneAsPlatform()`, and is
used only by platform-admin routes and automation. It is not a fallback for a missing
user session.

### 6.3 Control plane verification

Add `clerk-backend-api` to the control plane. One dependency authenticates every
tenant-facing route:

```python
# verifund_control_plane/tenancy/identity.py
@dataclass(frozen=True)
class Identity:
    user_id: str
    clerk_user_id: str
    tenant_id: str
    clerk_org_id: str | None
    role: str
    permissions: frozenset[str]
    is_platform_admin: bool

def require_identity(request: Request) -> Identity:
    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            secret_key=settings.clerk_secret_key,
            jwt_key=settings.clerk_jwt_key,          # networkless verification
            authorized_parties=[settings.console_base_url],
        ),
    )
    if not state.is_signed_in:
        raise VerifundError("unauthorized", "sign-in required", status_code=401)
    return resolve_identity(state.payload)
```

Verification requirements:

- Signature, `exp`, `nbf`, and `azp` are validated by the SDK. `authorized_parties`
  contains the console origin only.
- `jwt_key` (the PEM public key) is preferred over network JWKS so a Clerk outage does
  not take down settlement.
- `sub` is the only trusted user identifier. `org_id` is the only trusted organization
  assertion. No header, query parameter, or body field can supply either.
- Only session tokens are accepted: `accepts_token=['session_token']`. Machine tokens,
  OAuth tokens, and pending-session tokens (`sts`) are rejected with `401`.

### 6.4 Identity resolution

`resolve_identity` performs, in order:

1. Load `users` by `clerk_user_id = sub`. If missing, create from the token claims
   (`email`, `name`) — the webhook may still be in flight.
2. If `org_id` is present:
   - Load `organizations` by `clerk_org_id`. If missing, fetch the organization from the
     Clerk Backend API and insert it (decision 18). Webhooks are eventually consistent
     and must not be on the synchronous path.
   - Load `organization_members` for `(organization, user)`. If missing, fetch the
     membership from the Clerk Backend API; insert it if it exists. If it does not
     exist, return `403 forbidden`.
   - Reject `organizations.status != 'active'` with `403` unless the route is a
     read-only history route.
   - Load the role from the membership row and expand it through the permission map.
3. If `org_id` is absent, resolve the personal organization by
   `organizations.owner_user_id = user.id AND kind = 'personal'`. Create it if missing.
4. Load `platform_admins` by user; set `is_platform_admin`.

Decision 16: the token authenticates and asserts the active organization; the role and
permissions come from the database. This is what makes decision 10 (re-read membership
for money) a property of the whole system rather than a special case in the payout
code, and it avoids depending on the session token's custom-permission claim shape.

### 6.5 Clerk webhooks

The console has no database, so the console route is a forwarder and the control plane
is the writer:

1. `apps/console/app/api/webhooks/clerk/route.ts` reads the raw body and forwards it
   unchanged, with the `svix-id`, `svix-timestamp`, and `svix-signature` headers, to
   `POST /v1/webhooks/clerk` using `controlPlaneAsPlatform()`.
2. The control plane verifies the signature with `CLERK_WEBHOOK_SIGNING_SECRET`, then
   inserts into `webhook_events` with `source='clerk'` and `event_id=svix-id`.
3. A duplicate `(source, event_id)` is acknowledged with `200` and not replayed.

The console route is public. `auth.protect()` would make every delivery return `404`.
`CLERK_WEBHOOK_SIGNING_SECRET` lives in the control plane, not the console; the
publishable key and secret key stay in the console for the user session.

| Event | Effect |
|---|---|
| `user.created` / `user.updated` | Upsert `users`; no organization side effect |
| `user.deleted` | Set `users.status='disabled'`, clear `email` and `name`; never delete a user referenced by a transaction or audit row |
| `organization.created` | Upsert `organizations(kind='business', status='active')`. Do not create a `seller_profile` (decision 25) |
| `organization.updated` | Update name and slug |
| `organization.deleted` | Set `status='disabled'` (decision 9) |
| `organizationMembership.created/updated` | Upsert membership and role; reactivate a `removed` row |
| `organizationMembership.deleted` | Set `organization_members.status='removed'`; never delete the row |
| `organizationInvitation.created` | Record a pending invitation for the console |
| `organizationInvitation.revoked` | Mark the local invitation revoked |

Webhooks are not the synchronous path for onboarding. A user who creates an
organization and immediately navigates to it is served by the lazy sync in §6.4. A user
who starts selling calls `POST /v1/seller/onboarding`, which creates the seller profile
synchronously and idempotently; it never waits for `organization.created`.

## 7. Data model

### 7.1 Identity and tenancy tables

```sql
CREATE TABLE organizations (
    id            TEXT PRIMARY KEY,          -- internal UUID
    clerk_org_id  TEXT UNIQUE,               -- NULL for personal tenants
    kind          TEXT NOT NULL,             -- business | personal | platform
    name          TEXT NOT NULL,
    slug          TEXT UNIQUE,
    status        TEXT NOT NULL,             -- active | suspended | disabled
    owner_user_id TEXT REFERENCES users(id), -- personal tenants only
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE users (
    id            TEXT PRIMARY KEY,
    clerk_user_id TEXT NOT NULL UNIQUE,
    email         TEXT,
    name          TEXT,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE organization_members (
    id                  TEXT PRIMARY KEY,
    organization_id     TEXT NOT NULL REFERENCES organizations(id),
    user_id             TEXT NOT NULL REFERENCES users(id),
    role                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',  -- active | removed
    clerk_membership_id TEXT UNIQUE,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (organization_id, user_id)
);

CREATE TABLE platform_admins (
    user_id    TEXT PRIMARY KEY REFERENCES users(id),
    granted_by TEXT,
    created_at TEXT NOT NULL
);
```

### 7.2 Legacy identity bridges

Existing transactions reference `northwind-audio`, `circuitforge`, `aurora-supply`,
`summit-tech`, and `demo-buyer`. Those strings are not rewritten.

```sql
CREATE TABLE seller_profiles (
    seller_id           TEXT PRIMARY KEY,
    organization_id     TEXT NOT NULL UNIQUE REFERENCES organizations(id),
    display_name        TEXT NOT NULL,
    verification_status TEXT NOT NULL,   -- unverified | pending | verified | rejected | suspended
    verification_note   TEXT,
    verified_at         TEXT,
    verified_by         TEXT REFERENCES users(id),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE buyer_profiles (
    buyer_id        TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL UNIQUE REFERENCES organizations(id),
    created_at      TEXT NOT NULL
);
```

`seller_id` and `buyer_id` remain unique, human-readable keys. The organization columns
become the authorization keys. This keeps historical transactions, agreements,
evidence, receipts, and audit rows valid without a rewrite.

A `seller_profiles` row is created only by `POST /v1/seller/onboarding` (decision 25),
only for a `kind='business'` organization (decision 20). Its `seller_id` is derived from
the organization slug at that moment and made unique by suffix; it is not assigned when
the Clerk organization is created. A business organization that never starts onboarding
has no seller profile and is a buyer context.

### 7.3 Tenant columns

Add nullable columns first, backfill, then enforce non-null in the repository
constructor. SQLite cannot `ALTER COLUMN SET NOT NULL`; a table rebuild is the
alternative and is not required for this phase.

| Table | New columns |
|---|---|
| `transactions` | `buyer_organization_id`, `seller_organization_id` |
| `evidence` | `organization_id`, `storage_key` |
| `agreements` | `buyer_organization_id`, `seller_organization_id` |
| `audit_log` | `organization_id`, `actor_user_id` |
| `checkout_links` | `organization_id` |
| `buyer_tokens`, `seller_tokens` | `organization_id` (alongside the legacy owner column) |

Registry database (separate SQLite file):

| Table | New columns |
|---|---|
| `sellers` | `organization_id`, `verified` |
| `seller_listings` | `organization_id` |
| `agents` | `organization_id`, `published` |

Buyer agent database:

| Table | New columns |
|---|---|
| `runs` | `organization_id`, `user_id` |

### 7.4 Payment accounts

```sql
CREATE TABLE payment_accounts (
    id                   TEXT PRIMARY KEY,
    organization_id      TEXT NOT NULL REFERENCES organizations(id),
    provider             TEXT NOT NULL,           -- paypal
    provider_account_id  TEXT NOT NULL,           -- merchant id or payout email
    account_type         TEXT NOT NULL,           -- merchant | payout
    status               TEXT NOT NULL,           -- draft | active | disabled
    credentials_reference TEXT NOT NULL,          -- secret-manager key, never the secret
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    UNIQUE (organization_id, provider, account_type, provider_account_id)
);
```

At most one `active` payout account per `(organization_id, provider)`, enforced in the
repository inside the write transaction.

### 7.5 Seller onboarding tables

```sql
CREATE TABLE seller_onboarding (
    organization_id TEXT PRIMARY KEY REFERENCES organizations(id),
    status          TEXT NOT NULL,          -- not_started | in_progress | submitted | approved | rejected
    current_step    TEXT NOT NULL,
    completed_steps TEXT NOT NULL,          -- JSON list
    submitted_at    TEXT,
    completed_at    TEXT,
    updated_at      TEXT NOT NULL
);

CREATE TABLE seller_onboarding_events (
    id              TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    step            TEXT NOT NULL,
    event           TEXT NOT NULL,
    actor_user_id   TEXT REFERENCES users(id),
    payload         TEXT NOT NULL,          -- JSON
    created_at      TEXT NOT NULL
);

CREATE TABLE seller_verifications (
    id               TEXT PRIMARY KEY,
    organization_id  TEXT NOT NULL REFERENCES organizations(id),
    submitted_by     TEXT NOT NULL REFERENCES users(id),
    documents        TEXT NOT NULL,         -- JSON: tenant-prefixed evidence keys
    status           TEXT NOT NULL,         -- pending | approved | rejected
    reviewer_user_id TEXT REFERENCES users(id),
    decision_note    TEXT,
    decided_at       TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE seller_integrations (
    id                    TEXT PRIMARY KEY,
    organization_id       TEXT NOT NULL REFERENCES organizations(id),
    provider              TEXT NOT NULL,    -- shopify | woocommerce | csv | manual | slack
    status                TEXT NOT NULL,    -- connected | error | disconnected
    scopes                TEXT NOT NULL,    -- JSON list
    credentials_reference TEXT NOT NULL,    -- secret-manager key, never the secret
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE (organization_id, provider)
);
```

- Steps are `profile`, `verification`, `integrations`, `agent_setup`, `policies`,
  `testing`, `activation`. `completed_steps` drives the wizard; it is never an
  authorization input.
- Verification documents are written to tenant-prefixed evidence keys. The row holds
  keys, not bytes.
- Every step write is idempotent on `(organization_id, step)` and appends to
  `seller_onboarding_events`.
- `seller_integrations` is ownership and credential scope only. Provider
  implementations and the catalog schema belong to the companion onboarding spec.

### 7.6 Agent lifecycle tables (control plane)

```sql
CREATE TABLE agents (
    id              TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,          -- draft | configuring | testing | active | suspended | revoked
    policy_ref      TEXT NOT NULL,          -- key in the seller agent's store
    policy_version  TEXT NOT NULL,
    policy_hash     TEXT NOT NULL,
    card_hash       TEXT,
    created_by      TEXT REFERENCES users(id),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    activated_at    TEXT,
    revoked_at      TEXT,
    UNIQUE (organization_id, id)
);

CREATE TABLE agent_credentials (
    id              TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    token_hash      TEXT NOT NULL UNIQUE,
    scopes          TEXT NOT NULL,          -- JSON list
    status          TEXT NOT NULL,          -- active | revoked
    expires_at      TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE agent_test_runs (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    policy_hash     TEXT NOT NULL,
    card_hash       TEXT NOT NULL,
    checks          TEXT NOT NULL,          -- JSON: [{name, passed, detail}]
    passed          INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE payout_releases (
    id              TEXT PRIMARY KEY,
    transaction_id  TEXT NOT NULL,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    approved_by     TEXT NOT NULL REFERENCES users(id),
    reason          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (transaction_id, organization_id)
);
```

- The control plane owns agent status, credential issuance, and activation (decision
  21). `agent_credentials` lives here, not in the registry: one writer for identity.
- The seller agent's store owns the policy body. The control plane records
  `policy_ref`, `policy_version`, and `policy_hash`; a mismatch is drift (decision 22).
- A test run is bound to the `policy_hash` and `card_hash` it ran against. Either hash
  changing invalidates activation eligibility until the agent is retested (decision 24).
- `payout_releases` is consulted only for a seller that is not `active` and `verified`
  (decision 23).

### 7.7 Audit, invitations, and webhook events

```sql
CREATE TABLE audit_log (
    audit_id        TEXT PRIMARY KEY,
    scope           TEXT NOT NULL,          -- transaction | organization | agent | system
    transaction_id  TEXT,                   -- nullable: organization and agent events have none
    organization_id TEXT REFERENCES organizations(id),
    actor_user_id   TEXT REFERENCES users(id),
    actor_type      TEXT NOT NULL,          -- user | agent | system
    action          TEXT NOT NULL,
    resource_id     TEXT,
    payload         TEXT NOT NULL,          -- JSON
    created_at      TEXT NOT NULL
);

CREATE INDEX audit_log_org_time ON audit_log (organization_id, created_at);

CREATE TABLE organization_invitations (
    id                  TEXT PRIMARY KEY,
    organization_id     TEXT NOT NULL REFERENCES organizations(id),
    clerk_invitation_id TEXT UNIQUE,
    email               TEXT NOT NULL,
    role                TEXT NOT NULL,
    status              TEXT NOT NULL,      -- pending | accepted | revoked | expired
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
```

`webhook_events` already exists in the control plane. Add `source TEXT NOT NULL DEFAULT
'paypal'` (`paypal | clerk`), make `mode` nullable for Clerk rows, and enforce
uniqueness on `(source, event_id)`. Clerk's `svix-id` is the `event_id`.

### 7.8 Migration and backfill

1. Rebuild `audit_log`: `transaction_id` becomes nullable, and `scope`, `actor_type`,
   `organization_id`, `actor_user_id` are added. Copy `transaction_id` and the legacy
   `actor` string, then drop the old table. SQLite requires the rebuild.
2. Create the new tables.
3. Create one `organizations(kind='business')` row per seeded seller, plus
   `seller_profiles` rows with `verification_status='verified'` (decision 19). No
   `seller_profiles` rows are created for any other organization.
4. Create one `organizations(kind='personal')` row owned by the demo user, and a
   `buyer_profiles` row for `demo-buyer`.
5. Backfill `transactions.buyer_organization_id` / `seller_organization_id` through
   `buyer_profiles` / `seller_profiles`.
6. Backfill `evidence.organization_id` from the transaction's seller organization.
7. Backfill `agreements` from the transaction.
8. Backfill `audit_log.organization_id` from the transaction; leave system rows null.
9. Seed `payment_accounts` from `VERIFUND_SELLER_PAYOUT_EMAILS`, with
   `status='active'` for verified demo sellers.
10. Seed `agents` rows for the demo seller agents with `status='active'`, a policy
    reference, and credentials hashed from the existing static tokens. Seed
    `seller_onboarding` rows for the four demo sellers as `approved`.

Any transaction whose `buyer_id` or `seller_id` does not resolve to a profile aborts
the migration. Do not invent an organization for an unknown identifier.

## 8. Authorization model

### 8.1 Roles

Clerk allows ten custom roles per instance; two are the built-in `org:admin` and
`org:member`. The recommendation's nine-role table exceeds the cap with the defaults,
so six custom roles carry the business roles:

| Role | Scope |
|---|---|
| `org:admin` | Organization owner and administrators |
| `org:member` | Read-only baseline |
| `org:sales` | Products, offers, negotiation mandates |
| `org:fulfillment` | Evidence and fulfillment |
| `org:finance` | Payments and payouts |
| `org:reviewer` | Evidence review and disputes |
| `org:agent_manager` | Agent configuration and mandates |
| `org:buyer` | Personal buyer approvals |

Platform Admin is not a role in this table. It lives in `platform_admins` (decision 5).

### 8.2 Permissions

Custom permissions use Clerk's `org:<resource>:<action>` convention:

| Permission | Meaning |
|---|---|
| `org:transactions:read` | Read transactions the tenant participates in |
| `org:transactions:approve` | Approve an agreement or release |
| `org:evidence:read` | Read evidence |
| `org:evidence:write` | Submit evidence |
| `org:payouts:read` | Read payout status and history |
| `org:payouts:manage` | Create or change payout accounts and initiate payouts |
| `org:mandates:manage` | Configure agent mandates and pricing rules |
| `org:disputes:resolve` | Resolve a dispute |
| `org:agents:manage` | Register and configure agents |
| `org:members:manage` | Invite, remove, and re-role members |

Role to permission map:

| Permission | admin | member | sales | fulfillment | finance | reviewer | agent_manager | buyer |
|---|---|---|---|---|---|---|---|---|
| transactions:read | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| transactions:approve | ✓ | | | | | | | ✓ |
| evidence:read | ✓ | ✓ | ✓ | ✓ | | ✓ | | ✓ |
| evidence:write | ✓ | | | ✓ | | | | |
| payouts:read | ✓ | | | | ✓ | | | |
| payouts:manage | ✓ | | | | ✓ | | | |
| mandates:manage | ✓ | | ✓ | | | | ✓ | |
| disputes:resolve | ✓ | | | | | ✓ | | |
| agents:manage | ✓ | | | | | | ✓ | |
| members:manage | ✓ | | | | | | | |

The map lives in Verifund (`tenancy/permissions.py`), not only in Clerk. Clerk's role
assignment is mirrored; the permission expansion is ours, so a Clerk dashboard change
cannot silently widen a Verifund permission.

### 8.3 Transaction access

Every tenant-facing transaction route calls one helper:

```python
async def require_transaction(identity, transaction_id, action):
    txn = await repo.get_transaction(transaction_id)
    if identity.tenant_id not in (
        txn.buyer_organization_id,
        txn.seller_organization_id,
    ):
        raise VerifundError("not_found", "transaction not found", status_code=404)
    side = "buyer" if identity.tenant_id == txn.buyer_organization_id else "seller"
    if action not in allowed_actions(txn.state, side):
        raise VerifundError("forbidden", "action not permitted", status_code=403)
    permission = ACTION_PERMISSIONS[(side, action)]
    if permission not in identity.permissions:
        raise VerifundError("forbidden", "permission denied", status_code=403)
    return txn, side
```

Decision 17: a non-participant receives `404`, not `403`. The current seller code
returns `403 seller does not own transaction`, which confirms the transaction exists to
anyone who guesses an identifier.

Action to permission mapping is explicit, not inferred. Uploading evidence requires
`org:evidence:write`; releasing funds requires `org:transactions:approve` **and**
membership re-read (§8.4); changing a payout account requires `org:payouts:manage`.

`require_transaction` answers "is this my transaction". It does not answer "which
resources inside it may the other side see". That second question is fixed by resource,
not by request:

| Resource | Buyer organization | Seller organization | Notes |
|---|---|---|---|
| Buyer mandate and private preferences | Read/write | No access | Never leaves the buyer tenant |
| Seller catalog, inventory, pricing rules | Public listing projection only | Read/write | Private rows stay in the seller tenant |
| Negotiated offer | Read | Read/write | Shared once attached to the transaction |
| Agreement | Read | Read | Both parties; versions immutable |
| Evidence | Read as permitted | Read/write | Verification status visible to both |
| Payout account | No access | Read/manage | Never exposed to the buyer |
| Internal seller policy (floor price, discount) | No access | Read/write | Never in the Agent Card or A2A envelope |
| Agent credentials | No access | No access through routes | Service-to-service only |
| Audit rows | Own organization only | Own organization only | Platform admin sees all, audited |

The participant check runs first and returns `404` for a non-participant. Only then does
the resource table decide field and endpoint visibility. A resource table that is
checked after loading the row is not a boundary.

### 8.4 Money actions re-read membership

For `release`, `retry_payout`, payout-account mutation, and refund:

1. Resolve `Identity` as usual.
2. Re-read `organization_members` inside the same database transaction as the action.
3. If the membership or role changed since the token was issued, use the database
   value. A removed member is rejected even with an unexpired token.
4. Write `audit_log.actor_user_id` and `organization_id`.

Clerk session tokens are short-lived, but a revoked membership can still be carried by
a token for its remaining lifetime. Money is where that window must close.

### 8.5 Platform admin

`platform_admins` may call `/ops/*`, which can act across tenants. Every `/ops/*` write
records `organization_id` and `actor_user_id` in `audit_log`. Tenant-facing routes still
require membership: a platform admin is not implicitly a member of NovaTech, and the
console does not silently grant tenant access to platform staff.

The shared `VERIFUND_OPS_TOKEN` remains for machine automation (reconciler, seeding,
scripts) and is not accepted on tenant-facing routes. `/ops/*` accepts either the
service token (system actor) or a platform-admin Clerk identity (human actor).

### 8.6 Agents

- A Seller Agent is a principal with a credential bound to `(organization_id,
  agent_id)`. Credentials live in the control plane (decision 21); the registry does not
  verify them.
- The A2A gateway authenticates the credential, resolves the organization, and rejects a
  request whose envelope asserts a different `tenant_id` with `403`.
- The buyer agent's internal API credential is bound to the buyer organization.
- An agent credential never carries platform-admin authority.
- A credential is valid only while both `agents.status='active'` and
  `agent_credentials.status='active'`. `configuring`, `testing`, `suspended`, and
  `revoked` fail with `403 agent_not_active`, regardless of token expiry.

#### Effective agent authority

```
P_effective = P_tenant ∩ P_agent ∩ P_run
```

| Level | Stored where | Example |
|---|---|---|
| Tenant | `seller_profiles` and organization settings | May sell in KE; maximum discount 20% |
| Agent | Seller agent policy store, hashed in `agents.policy_*` | This agent: floor 1,350 USD, 90-day warranty |
| Run | Transaction mandate and negotiation state | This RFQ: maximum 1,400 USD, quantity 1 |

- The seller agent enforces the policy body. The orchestrator enforces the coarse
  capability and transaction state; it does not re-price an offer.
- `agreement.accept`, `payment.authorize`, and any action above the agent's configured
  ceiling require a human with the matching permission. Settlement release is never
  delegated to an agent.
- A run cannot widen a policy. The effective set is an intersection, not a union.

#### Orchestrator mediation

Before an A2A call, the orchestrator builds one trusted `AgentCallContext` and checks:

1. The buyer agent is `active` and belongs to the buyer organization.
2. The seller agent is `active` and belongs to the seller organization.
3. Both organizations are participants in the transaction.
4. The operation is permitted by the agent's capability list and the transaction state.
5. The seller credential reference resolves and is not revoked.

The context carries `transaction_id`, both organization IDs, both agent IDs, `run_id`,
`request_id`, and `correlation_id`. Seller bearer tokens are fetched at call time and
never enter LangGraph state, checkpoints, traces, logs, or AG-UI payloads.

#### Post-agreement role

After acceptance the seller agent may read obligations, draft evidence, and notify the
seller. It holds `fulfillment:assist`, which is read plus draft: every mutation goes
through the same authorized endpoint a human would use, with `actor_type='agent'` in the
audit row. The agent never advances transaction state directly.

## 9. Seller verification and agent activation gate

### 9.1 Why the gate exists

Decision 3 makes organization creation self-serve and decision 25 makes selling an
explicit action. Without gates, creating an organization or an agent would grant
registry listing, award acceptance, seller tokens, evidence submission, and payout
configuration. Decisions 14, 20, and 24 separate creation, verification, and activation.

### 9.2 Three status axes

| Axis | Field | Values | Who moves it |
|---|---|---|---|
| Organization | `organizations.status` | `active`, `suspended`, `disabled` | Platform admin; Clerk deletion webhook (decision 9) |
| Seller | `seller_profiles.verification_status` | `unverified`, `pending`, `verified`, `rejected`, `suspended` | Seller submits; platform admin decides |
| Agent | `agents.status` | `draft`, `configuring`, `testing`, `active`, `suspended`, `revoked` | Seller configures and tests; seller or platform admin suspends; revocation is terminal |
| Onboarding | `seller_onboarding.status` | `not_started`, `in_progress`, `submitted`, `approved`, `rejected` | Derived from steps and seller verification |

`seller_onboarding.status` routes the console and is never an authorization input.
Authorization reads `organizations.status`, `seller_profiles.verification_status`, and
`agents.status`. A verified seller with a `configuring` agent is the normal state, not
an edge case, and it must be expressible.

### 9.3 Seller verification state machine

```
(no profile) → unverified    POST /v1/seller/onboarding (decision 25)
unverified → pending        seller submits verification
pending    → verified       platform admin approves
pending    → rejected       platform admin rejects with a note
verified   → suspended      platform admin suspends (fraud, policy, dispute)
suspended  → verified       platform admin reinstates
rejected   → pending        seller may reapply after changing details
```

Only a platform admin moves a seller into `verified`, `rejected`, or `suspended`. The
seller can move `unverified` or `rejected` to `pending`. Every transition writes an
audit row with `scope='organization'`, `actor_user_id`, and `organization_id`.

### 9.4 Agent lifecycle state machine

```
(none) → draft              provision
          draft → configuring    seller defines capabilities
          draft → revoked
          configuring → testing  test run starts
          testing → active       test passed AND seller verified
          testing → configuring  test failed
          active → suspended     seller or platform admin
          suspended → active     reinstated; retest if policy or card changed
          active|configuring|suspended → revoked   credentials revoked; terminal
```

Rules:

- Only `active` agents appear in discovery and accept A2A calls.
- Activation requires a verified seller, a passing `agent_test_runs` row whose
  `policy_hash` and `card_hash` match the agent's current values, and at least one
  active credential (decision 24).
- `revoked` is terminal. Re-provisioning creates a new `agent_id`; history stays with
  the old row.
- Suspension keeps historical runs and transactions readable.

### 9.5 Capability matrices

Seller axis:

| Capability | unverified | pending | verified | suspended |
|---|---|---|---|---|
| Console workspace, settings, members | Yes | Yes | Yes | Read-only |
| Create a `seller_profiles` row | Onboarding only | — | — | — |
| Create a draft agent (control plane) | No | Yes | Yes | No |
| Run agent tests | No | Yes | Yes | No |
| Activate an agent / publish to the registry | No | No | Yes | No |
| Appear in discovery results | No | No | Yes | No |
| Accept an award (`/awards`) | 403 `seller_not_verified` | 403 | Yes | 403 |
| Receive a seller token or invitation | No | No | Yes | No |
| Submit evidence | No | No | Yes | Yes, existing transactions only |
| Create a `payment_accounts` row | No | Draft only | Yes | No |
| Activate a payout account | No | No | Yes | No |
| Receive a payout | No | No | Yes | Release required |

Agent axis:

| Capability | draft | configuring | testing | active | suspended | revoked |
|---|---|---|---|---|---|---|
| Console agent configuration | Yes | Yes | Yes | Yes | Read-only | Read-only |
| Start a test run | No | Yes | Yes | Yes (retest) | No | No |
| Activate | No | No | Yes, if the run passed | — | No | No |
| Registry publication | No | No | No | Yes | Removed | Removed |
| A2A calls with the credential | No | No | No | Yes | No | No |
| New awards | No | No | No | Yes | No | No |
| Historical runs and transactions | — | — | — | Yes | Read | Read |

An agent is operable only when the seller is `verified` **and** the agent is `active`.
Either axis alone is insufficient.

### 9.6 Enforcement points

1. `POST /v1/seller/onboarding` requires `org:admin`, `kind='business'`, and an
   `Idempotency-Key`; it creates the seller profile and onboarding row. It is a separate
   call from organization creation (decision 25).
2. `POST /v1/agents` (control plane) requires `org:agents:manage` and a seller profile in
   `pending` or `verified`. It creates a `draft` agent and an active credential.
3. `POST /v1/agents/{id}/activate` requires a verified seller and a passing test run
   bound to the current hashes.
4. `POST /v1/agents` (registry) is a projection sync: service auth only. It mirrors a
   control-plane agent that is already `active`; sellers do not call it.
5. `POST /v1/discover` and product search join `sellers.verified = true` **and**
   `agents.published = true`.
6. `create_award` in `api/ops.py` resolves `seller_profiles.verification_status` and
   rejects anything other than `verified` with `403 seller_not_verified`. The check runs
   before any transaction row is written.
7. `issue_invitation` and `reissue_seller_token` require a verified seller.
8. `payment_accounts` activation requires `verified` and `org:payouts:manage`.
9. Payout resolution requires a verified seller and an `active` account, or a
   `payout_releases` row for a suspended seller (decision 23).
10. Evidence upload requires a seller profile in `verified` or `suspended`, and the
    transaction must already exist. An unverified seller cannot have one.
11. The A2A gateway and `POST /v1/agent-credentials/verify` require an `active` agent and
    an `active` credential.

The registry and control plane are separate databases. `sellers.verified` and
`agents.published` are projections written by the control plane on transition. If a
projection write fails, the control-plane credential check still denies; discovery is an
optimization, not the authority. A sweep job reconciles rows whose projection is older
than the control-plane `updated_at`.

### 9.7 Suspension semantics

"Suspended seller" in this section means `seller_profiles.verification_status =
'suspended'`. It is not the same as `organizations.status='suspended'`, which is a
platform-level freeze: §6.4 makes that organization read-only and none of the write
allowances below apply until a platform admin reinstates it.

A suspended seller keeps its obligations and loses its ability to take on new ones:

| Action | Suspended seller |
|---|---|
| Read transaction history and agreements | Yes |
| Fulfill an existing transaction | Yes |
| Submit evidence for an existing transaction | Yes |
| Receive a new award | No |
| Appear in discovery | No |
| Invite a counterparty or receive a seller token | No |
| Change a payout account | No |
| Receive a payout | Only with a `payout_releases` row (decision 23) |

A `disabled` organization is read-only; the counterparty retains read access (decision
9), and payouts require a release. A suspended agent stops accepting A2A calls and is
removed from publication, but its runs and transactions stay readable. Reinstatement
does not restore activation if the policy or card hash changed while suspended; the
agent must be retested.

### 9.8 Abuse controls for self-serve creation

- Seller onboarding is idempotent per organization; a retry cannot create a second
  profile.
- A per-user organization creation limit (default 3), enforced in the console and
  re-checked in the control plane.
- `maxAllowedMemberships` set at Clerk organization creation (default 25).
- Slug uniqueness in both Clerk and Verifund.
- A review queue: `seller_verifications` rows in `pending`, ordered by submission time,
  is the platform admin work list.
- A configurable ceiling on agents per organization (default 50) bounds runaway
  provisioning. It is an abuse control, not a product limit (decision 26).
- Display names are not trust signals. Two organizations may be called "NovaTech";
  authorization and discovery key on IDs, never names.
- A seller with `unverified` status cannot be invited to a transaction, so an
  unverified organization cannot use the platform to contact buyers.

## 10. Console implementation

### 10.1 Files

| File | Change |
|---|---|
| `apps/console/package.json` | Add `@clerk/nextjs` |
| `apps/console/middleware.ts` | New; bare `clerkMiddleware()` |
| `apps/console/app/layout.tsx` | Wrap in `<ClerkProvider>` |
| `apps/console/app/sign-in/[[...sign-in]]/page.tsx` | New; `<SignIn />` |
| `apps/console/app/sign-up/[[...sign-up]]/page.tsx` | New; `<SignUp />` |
| `apps/console/lib/control-plane.ts` | New; `controlPlaneForUser`, `controlPlaneAsPlatform` |
| `apps/console/components/layout/console-layout.tsx` | Add `OrganizationSwitcher`, `UserButton` |
| `apps/console/app/(console)/layout.tsx` | Server guard; pass user to the client shell |
| `apps/console/app/(console)/agreements/*` | Remove `demo-buyer`; use the user token |
| `apps/console/app/seller/layout.tsx` | Require Clerk session + seller org membership |
| `apps/console/app/api/**/route.ts` | `await auth.protect()` at the top of every handler |
| `apps/console/app/**/actions.ts` | `await auth.protect()` at the top of every action |
| `apps/console/app/api/copilotkit/[[...slug]]/route.ts` | `identifyUser` returns the Clerk user |
| `apps/console/app/seller/onboarding/**` | New; resumable onboarding wizard shell |
| `apps/console/app/seller/agents/**` | New; agent configuration, test, activation |
| `apps/console/app/(console)/admin/verification/**` | New; platform-admin review queue |

### 10.2 Trust rules in the console

- The console never decides authorization for a mutation. It may hide UI with
  `has({ role })` or `has({ permission })` for usability, but the control plane is the
  gate.
- The console never sends `X-Actor-Id` or `X-Actor-Type`. Those headers are removed from
  the control plane's agreement routes and the actor is derived from `Identity`.
- The console never forwards a browser-supplied organization ID. It forwards the
  session token; the backend resolves the organization from it.
- `controlPlaneAsPlatform()` is imported only by platform-admin routes and the
  reconciler trigger. A lint rule or test asserts that no `app/(console)` or
  `app/seller` file imports it.

### 10.3 Seller workspace

The seller workspace becomes a normal organization workspace. `readSellerSession()` and
the invitation cookie store are removed for staff access:

- `/seller/*` resolves the organization from the Clerk session.
- A user sees the seller workspace only if their organization has a `seller_profiles`
  row and they hold `org:fulfillment` (or `org:admin`).
- The invitation link at `/fulfillment/access/[token]` remains a public onboarding
  route. It exchanges the token for nothing but a redirect into Clerk sign-in with the
  transaction ID preserved. After sign-in, membership in the seller organization is
  required. A user who is not a member is redirected to accept an organization
  invitation.

This preserves the magic link as an onboarding affordance (decision 4) while removing
it as a long-lived parallel identity.

### 10.4 Seller onboarding entry

`/seller` resolves in this order:

1. No `seller_profiles` row → redirect to `/seller/onboarding`. The organization has not
   started selling (decision 25).
2. Profile in `unverified`, `pending`, or `rejected` → the onboarding dashboard, showing
   the current step and reviewer notes.
3. Profile in `verified` → the workspace, with agent status in the header.
4. Profile `suspended` → the workspace in read-only mode, with the suspension reason.

The wizard steps are `profile`, `verification`, `integrations`, `agent_setup`,
`policies`, `testing`, `activation`. Each step writes to `seller_onboarding` and is
independently saveable; progress never lives only in the browser. `completed_steps`
controls navigation only — the control plane gates every action from the status axes in
§9.2.

The integrations and policy steps may link to the companion seller-onboarding spec for
their bodies. This document fixes only who owns the records and which status gates the
next step.

## 11. Control plane implementation

### 11.1 New module

```
verifund_control_plane/tenancy/
    __init__.py
    identity.py        # Identity, require_identity, resolve_identity, lazy sync
    permissions.py     # ROLE_PERMISSIONS, ACTION_PERMISSIONS
    repository.py      # organizations, users, memberships, platform_admins
    routes.py          # platform-admin verification endpoints (under /ops)

verifund_control_plane/onboarding/
    service.py         # idempotent seller onboarding, verification submissions
    routes.py          # /v1/seller/onboarding, /v1/seller/verification

verifund_control_plane/agents/
    lifecycle.py       # status transitions, test gate, activation
    credentials.py     # issue, verify, revoke
    registry_sync.py   # projection writes and reconciliation sweep
    routes.py          # /v1/agents, /v1/agent-credentials

verifund_control_plane/api/webhooks.py   # Clerk signature verification and ingestion
```

### 11.2 Settings

Add to `verifund_control_plane/settings.py`:

| Setting | Env var | Notes |
|---|---|---|
| `clerk_secret_key` | `CLERK_SECRET_KEY` | Required outside `mode=off` |
| `clerk_jwt_key` | `CLERK_JWT_KEY` | PEM public key; networkless verification |
| `clerk_authorized_parties` | `CLERK_AUTHORIZED_PARTIES` | JSON list; default `["http://127.0.0.1:3000"]` |
| `tenancy_enabled` | `VERIFUND_TENANCY_ENABLED` | `0` preserves the current demo path during migration |
| `clerk_webhook_secret` | `CLERK_WEBHOOK_SIGNING_SECRET` | Svix signing secret; required when webhooks are enabled |
| `max_agents_per_organization` | `VERIFUND_MAX_AGENTS_PER_ORG` | Abuse ceiling, default 50 (decision 26) |

`sandbox` mode validation gains: Clerk keys present, the authorized party is the
configured console origin, and `tenancy_enabled=1`. A sandbox deployment with tenancy
disabled is rejected.

The console additionally requires `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`,
`CLERK_SECRET_KEY`, and `CLERK_WEBHOOK_SIGNING_SECRET`. `CLERK_SECRET_KEY` is present in
both services but is never exposed to a component, a log line, or a response.

### 11.3 Repository scope

One repository entry point requires a tenant scope:

```python
@dataclass(frozen=True)
class TenantScope:
    organization_id: str
    user_id: str
    permissions: frozenset[str]
    is_platform_admin: bool = False

class TenantRepository:
    async def list_transactions(self, scope: TenantScope, **filters): ...
    async def get_transaction(self, scope: TenantScope, transaction_id: str): ...
    async def list_evidence(self, scope: TenantScope, transaction_id: str): ...
```

Rules:

- No `select(transactions)` outside `TenantRepository`, except in the reconciler and
  migrations.
- `get_transaction` applies the participant predicate in SQL, not after loading.
- A platform-admin scope must pass `include_all_tenants=True` explicitly, which is
  audited.
- Existing methods that take `seller_id`/`buyer_id` are kept for the legacy token paths
  during migration and deleted when those paths retire.

This is the RLS-ready seam. When the control plane moves to Postgres, `TenantRepository`
sets `app.tenant_id` with `SET LOCAL` and the policies from the recommendation document
take over; call sites do not change.

### 11.4 Routes

| Route group | Identity |
|---|---|
| `/ops/*` | Service token or platform-admin Clerk identity |
| `/agreements/*` | Clerk identity; participant check |
| `/seller/*` | Clerk identity; seller organization + action permission |
| `/v1/seller/onboarding/*` | Clerk identity; `org:admin`; `kind='business'` |
| `/v1/seller/verification/*` | Clerk identity; seller organization |
| `/v1/agents/*` (control plane) | Clerk identity; agent owner + `org:agents:manage` |
| `/v1/agent-credentials/verify` | Agent credential; service-to-service |
| `/v1/webhooks/clerk` | Svix signature only |
| `/v1/payout-releases/*` | Platform admin + `org:payouts:manage` |
| `/buyer/*` | Clerk identity or buyer agent principal; participant check |
| `/fulfillment/access/*` | Public invitation exchange, then Clerk |
| `/checkout/*` | Signed link, then Clerk for confirmation |
| `/webhooks/*` | Provider signature only |

The registry exposes its own `/v1/sellers` and `/v1/agents` paths as service-auth
projection endpoints (§12.1); they are not in this table and are not callable by the
console.

Error codes: `401 unauthorized` for a missing or invalid session; `403 forbidden` for a
missing permission or membership inside a participant; `404 not_found` for a
non-participant transaction; `403 seller_not_verified` for the seller gate; `403
agent_not_active` for a non-active agent or revoked credential; `409
tenancy_sync_pending` if lazy Clerk sync cannot complete; `409 onboarding_incomplete`
for an out-of-order step; `409 policy_drift` when the policy hash does not match the
seller agent's confirmed version; `400 card_url_not_owned` when a card URL does not
belong to the seller.

## 12. Registry and agent identity

### 12.1 Registry as a projection

Decision 21 makes the control plane the writer and the registry the discovery surface.

- Registry `sellers` and `agents` gain `organization_id`; `agents` gains `published`.
- `POST /v1/sellers` and `POST /v1/agents` are service-auth projection syncs. Sellers do
  not call them. The organization comes from the control-plane record, never the body.
- Public reads (`GET /v1/sellers`, `GET /v1/products`, `POST /v1/discover`) omit
  `organization_id`, filter `sellers.verified = true`, and require
  `agents.published = true`.
- `POST /v1/sellers/{id}/refresh` remains restricted to the owning organization or a
  platform admin.
- `SELLER_ID_PATTERN` remains; `seller_id` is globally unique and maps 1:1 to an
  organization.
- A suspended or revoked agent is unpublished, not deleted, so historical discovery
  responses still resolve. If the projection write fails, the control-plane credential
  check still denies and the sweep in §9.6 repairs the row.

### 12.2 Agent credentials

The table moved to §7.6. The protocol is:

- Credential format is an opaque random token with the `vf_agent_` prefix, returned once
  at issuance; only the hash is stored.
- `POST /v1/agent-credentials/verify` is service-to-service and returns
  `{organization_id, agent_id, scopes, status}` and nothing else.
- Verification succeeds only when both the credential and the agent are `active`.
- A seller agent may cache a positive result for at most 30 seconds, keyed on the token
  hash. Revocation latency is bounded by that TTL.
- The A2A gateway rejects an envelope `tenant_id` that differs from the verified
  organization with `403`.
- Revoking one agent does not revoke the organization's other agents (decision 7).
- The demo's static `SELLER_*_TOKEN` values are seeded into the control plane and bound
  to the matching seller organizations, so the sample flow continues to work.

### 12.3 Agent Card publication

- `card_json` contains public fields only: name, description, URL, version,
  capabilities, skills, and categories. It never contains a tenant ID, credential
  reference, policy body, inventory, or price floor.
- `card_hash` is computed over the public projection only.
- `card_url` must be the platform-issued `/{seller_id}/a2a` path or match the seller's
  registered endpoint allowlist. An arbitrary URL is rejected with
  `400 card_url_not_owned`, because a seller could otherwise point discovery at another
  seller's agent.
- Card fetch stays restricted by the registry's `allowed_card_hosts`.

### 12.4 Provisioning sequence

1. Control plane creates `agents(status='draft')` and an active credential.
2. The seller configures capabilities in the console; status becomes `configuring`.
3. Policy is written to the seller agent's store, which returns `policy_version` and
   `policy_hash`; the control plane records both (decision 22).
4. The card is generated and hashed; `card_hash` is stored.
5. The seller starts a test run; status becomes `testing` and `agent_test_runs` records
   the checks against both hashes.
6. On a pass with a verified seller, status becomes `active` and the control plane
   publishes the agent to the registry with `published=true`.
7. On a failure, status returns to `configuring` and the failed checks are returned to
   the console.

Every step is idempotent on `(organization_id, Idempotency-Key)`.

### 12.5 Policy drift

Because the seller agent's store is authoritative, the control plane cannot assume its
recorded hash is current. On activation, on retest, and in a daily sweep:

- Ask the seller agent for `policy_version` and `policy_hash`.
- If either differs from `agents.policy_*`, set `policy_drift`, deny activation, and
  surface the mismatch to the seller.
- Do not auto-overwrite. The seller either re-confirms the new policy or rolls back to
  the recorded version.
- A drifting agent that is already `active` keeps operating on its local policy until
  the seller resolves the mismatch; the flag is visible to the seller and platform
  admins, and new awards are blocked.

## 13. Payments

- `VERIFUND_SELLER_PAYOUT_EMAILS` becomes a seed source only. At startup it upserts
  `payment_accounts` rows for the demo organizations; runtime payout resolution reads
  the database exclusively.
- Payout resolution: transaction → `seller_organization_id` → `seller_profiles`
  (verified) → `payment_accounts` with `account_type='payout'` and `status='active'`.
- A missing or ambiguous active account is `409 payout_account_unavailable`, never a
  fallback to an environment variable.
- Only `org:payouts:manage` may create, change, or activate an account. `org:sales` and
  `org:fulfillment` cannot.
- `credentials_reference` names a secret-manager key. The PayPal secret never lives in
  the database, and the API never returns it.
- PayPal webhooks verify the signature first, then resolve the transaction from the
  provider payload, then confirm the transaction's seller organization matches the
  payment account. A webhook body cannot select a tenant.
- The platform merchant account is a `kind='platform'` organization. It is not a seller
  and cannot receive a seller payout.
- A suspended seller's payout is held unless a `payout_releases` row exists for
  `(transaction_id, organization_id)`. Creating one requires a platform admin and
  records `approved_by` and a reason; `org:payouts:manage` alone is not enough.
- The reconciler evaluates in order: seller `active` + `verified` + active payout account
  → pay; otherwise a release row → pay; otherwise
  `409 payout_hold_seller_suspended`.
- A release is per transaction, never a blanket reinstatement of the seller.
- Disabling an organization does not delete payout history or release records.

## 14. Evidence storage

- New keys: `tenants/{organization_id}/transactions/{transaction_id}/{sha256}`.
- `evidence.storage_key` records the key; `evidence.organization_id` records the
  tenant.
- Reads authorize the database row before opening the file. A path is never a
  capability.
- Legacy files remain at `data/evidence/{sha256}`. The store resolves a row with a null
  `storage_key` from the legacy root. New writes always use the tenant prefix.
- Content-addressed dedupe is scoped to the tenant. Two organizations uploading the
  same file get two objects; this avoids cross-tenant existence leaks and makes
  per-tenant export and deletion possible.
- Signed URLs, when introduced, are issued only after authorization and carry the
  tenant and transaction in the signed scope.
- Verification documents in `seller_verifications.documents` use
  `tenants/{organization_id}/verification/{document_id}/{sha256}`. A reviewer reads them
  through an authorized route; the storage key is never returned to the seller.

## 15. Background workers

- The reconciler and any future worker run as an explicit `SYSTEM` principal. They do
  not impersonate a tenant.
- Every job carries `tenant_id`, `transaction_id`, `initiated_by`, and
  `correlation_id`. These are lookup keys, not grants: the worker re-reads the row and
  the actor before acting.
- A payout reconciliation job resolves the payment account from the transaction's
  seller organization. It cannot use another tenant's account, even if the queue
  payload names one.
- Every worker write records `audit_log.organization_id`.
- A per-tenant worker identity is a later upgrade; it is not required while the
  reconciler is a single platform service.

## 16. Agent runs, checkpoints, and memory

- `runs` gains `organization_id` and `user_id`; the runs API filters by the caller's
  tenant.
- LangGraph checkpoint key: `thread_id = f"{organization_id}:{run_id}"`. `run_id`
  remains the public identifier; the tenant prefix prevents cross-tenant thread
  collisions.
- Checkpoint metadata includes `organization_id` and `agent_id`; the resume path
  asserts both against the authenticated identity.
- Agent memory namespace: `("tenants", organization_id, "agents", agent_id, "memory")`.
- Existing checkpoints in `data/*.db` are development artifacts. They are discarded, not
  migrated; this is recorded in the implementation plan so nobody expects continuity.
- The LLM never chooses a tenant. Retrieval tools receive the tenant from the
  authenticated context.

### 16.5 Other isolation surfaces

| Surface | Rule |
|---|---|
| SSE and AG-UI streaming | Authorize the run's organization and the caller's membership before the stream opens; a run ID is not a capability |
| Logs and traces | Carry `organization_id`, `agent_id`, and `run_id`; redact tokens, credentials, policy bodies, and card secrets |
| Integration credentials | Secret-manager references only; never in a card, log, response, or checkpoint |
| Queue and job payloads | Hints, not grants: the worker re-reads the row and the actor before acting |
| Registry card fetch | Host allowlist plus seller URL ownership (§12.3) |
| Agent memory | Namespaced by organization and agent (§16) |
| Checkpoints | Tenant-prefixed `thread_id` (§16) |
| Evidence | Tenant-prefixed keys with authorization before file access (§14) |

## 17. Isolation tests

Two tenants, two users, one shared transaction. Every row is expected.

| # | Scenario | Expected |
|---|---|---|
| 1 | A reads B's transaction | `404` |
| 2 | A reads B's evidence | `404` |
| 3 | A reads B's agreement | `404` |
| 4 | A and B read their shared transaction | `200` for both |
| 5 | Sales role reads payouts | `403` |
| 6 | Fulfillment role uploads evidence | `200` |
| 7 | Finance role releases funds | `200` |
| 8 | Removed member releases funds with an unexpired token | `403` |
| 9 | Unverified seller is awarded | `403 seller_not_verified` |
| 10 | Unverified seller appears in discovery | Absent |
| 11 | Unverified seller activates a payout account | `403` |
| 12 | Payout resolves another tenant's account | Impossible; no code path |
| 13 | Worker processes another tenant's job payload | Denied by row lookup |
| 14 | Request with no token | `401` on every protected route |
| 15 | Token with the wrong `azp` | `401` |
| 16 | Personal buyer A reads B's runs | `404` |
| 17 | Personal buyer has no organization claim | Resolves to the personal tenant |
| 18 | Webhook delivered twice | One row; idempotent |
| 19 | Org suspended mid-transaction | Read-only; counterparty retains read |
| 20 | Platform admin calls a tenant route without membership | `403` |
| 21 | A `configuring` agent calls A2A | `403 agent_not_active` |
| 22 | A revoked agent credential is used | Denied; historical runs stay readable |
| 23 | Policy changes after a passing test run | Activation blocked until retest |
| 24 | Card URL points at another seller's endpoint | `400 card_url_not_owned` |
| 25 | Suspended seller payout without a release | Held; with a release, paid |
| 26 | Onboarding retried with the same idempotency key | One profile, one onboarding row |
| 27 | Clerk webhook delivered twice | One `webhook_events` row; no duplicate membership |
| 28 | SSE subscription to another tenant's run | `404` |
| 29 | Buyer organization starts seller onboarding | `403` |
| 30 | Policy hash differs from the seller agent's confirmed version | `409 policy_drift`; activation blocked |

Tests 1–7 and 14 are the minimum merge gate. Tests 8–13 are the money and gate gate.
Tests 21–30 are the onboarding and agent gate.

## 18. Phases

| Phase | Scope | Exit criteria |
|---|---|---|
| M0 | Clerk in the console: provider, middleware, sign-in, org switcher, `auth.protect()` everywhere, `controlPlaneForUser` | A signed-in user reaches the console; a signed-out user is redirected; no page uses `demo-buyer` |
| M1 | Tenant schema, Clerk webhook ingestion, lazy sync, audit rebuild, backfill, seller verification state machine | Two organizations exist locally; creating an organization does not create a seller profile; the four demo sellers are verified; verification transitions are audited |
| M2 | `Identity` dependency and `TenantRepository` in the control plane; `/ops/*` platform-admin identity | Unauthenticated and cross-tenant requests fail; the console no longer sends the ops token for user actions |
| M3 | Tenant columns on transactions, evidence, agreements; transaction participant gate; visibility matrix; gate checks in award/token/invitation | Isolation tests 1–7, 9, 14 pass |
| M4 | Seller onboarding domain: explicit `POST /v1/seller/onboarding`, verification submission and review queue, resumable wizard, seller workspace on Clerk, invitation link becomes onboarding only | A seller starts and resumes onboarding; a platform admin approves it; an invited non-member is routed through the org invitation |
| M5 | Agent lifecycle: control-plane `agents`, credential move, provisioning, policy hash confirmation, test gate, activation, registry projection | A `configuring` or `revoked` agent cannot act; a card URL cannot name another seller's endpoint; tests 21–24 pass |
| M6 | `payment_accounts`, payout resolution, payout releases, evidence storage keys, reconciler system principal | No payout path reads an env var at runtime; a suspended seller is paid only with a release |
| M7 | Runs, checkpoints, memory scoping, and streaming authorization | Cross-tenant run reads and stream subscriptions return `404` |
| M8 | PostgreSQL migration and RLS (optional, separate spec) | The policies in the recommendation document are active and tested |

M0–M3 are the security milestone. M4–M7 make the product coherent. M8 is defense in
depth and is deliberately not bundled with the first implementation.

The companion seller-onboarding spec supplies the integration bodies, catalog schema,
policy editor, and test-console UX for M4–M5. This document supplies the tables, state
machines, and authorization checks they build on.

## 19. Risks and open issues

| Risk | Mitigation |
|---|---|
| Clerk webhook lag | Lazy sync from the Backend API on the request path (decision 18); webhooks are not the source of truth for onboarding |
| Session token outlives a membership change | Database re-read for money actions (decision 10); short token TTL |
| Custom role cap (10 per instance) | Six custom roles; permissions carry the granularity |
| Self-serve seller abuse | Verification gate; per-user org limit; review queue; verified-only discovery |
| Registry and control plane disagree on verification | Control plane denies independently; registry flag is a discovery optimization |
| SQLite cannot enforce RLS | Repository scope + isolation tests; Postgres migration is a named phase |
| Personal tenant proliferation | One personal org per user, created idempotently; never per session or per run |
| `seller_id` reuse across organizations | `seller_profiles.seller_id` is unique and 1:1; a new organization gets a new `seller_id` |
| Clerk outage | `jwt_key` networkless verification; no Backend API call on the common path |
| Demo flow breaks on the gate | Seeded sellers are backfilled `verified` (decision 19) |
| Console hides a failure as an empty list | Route handlers return the control-plane status; the agreements page stops swallowing auth failures |
| Policy drift or an offline seller agent blocks activation | Hash confirmation on every activation; queued edits; drift flag and `409 policy_drift`; the seller can roll back |
| Registry projection lags a revocation | Credential verification is the authority; a sweep reconciles rows older than `agents.updated_at` |
| Webhook secret now lives in the control plane | The console never verifies Clerk payloads; the control plane rejects unsigned or stale deliveries |
| Onboarding stalls with no reviewer | Review-queue age alert; a pending seller can still configure an agent but cannot activate |
| Runaway agent provisioning | Verified-seller requirement plus the configurable per-organization ceiling |
| Card URL impersonation | Platform-issued path or registered endpoint allowlist; `400 card_url_not_owned` |
| Audit table rebuild loses rows | Copy-then-drop inside one migration transaction with a row-count check |

Open issue: whether platform admins should be able to perform tenant money actions
through `/ops/*` with an audit trail, or whether a second human must approve. This does
not block M0–M3; it must be decided before M6.

Open issue: whether an organization can be both a buyer and a seller. The model allows
it (`seller_profiles` is optional), but no UI or policy defines it. Default position:
allowed, with separate permissions; revisit if it complicates discovery.

## 20. Deltas from the recommendation document

| Recommendation | This design | Reason |
|---|---|---|
| PostgreSQL RLS as the primary isolation layer | Application-enforced repository now; RLS-ready, Postgres in M8 | The repository is SQLite; RLS cannot run |
| Next.js 16 route structure | Next.js 15.5.15 with `middleware.ts` | Actual dependency |
| Nine organization roles | Six custom roles + granular permissions | Clerk caps custom roles at ten per instance, including defaults |
| Platform Admin as a role | `platform_admins` table | Clerk roles are organization-scoped |
| Every buyer is an organization | Personal organization row per user | Clerk personal accounts carry no `org_id` |
| `transaction_participants` from the start | Two organization columns | Two-party transactions; add the table with a third party |
| Messaging and Redis tenancy | Out of scope | Those subsystems do not exist in this repository |
| Neon and object storage | SQLite and local evidence directory | Actual stack |
| No seller verification model | Verification state machine and capability matrix | Self-serve creation requires a trust gate |
| `INDIVIDUAL` / `ORGANIZATION` / `MARKETPLACE` tenant types | `personal` / `business` / `platform` kinds | One table, three kinds; no separate tenant tables |
| `transaction_participants` as the access model | Two organization columns plus a fixed visibility matrix | Two-party transactions; the table arrives with a third participant |
| Synchronous provisioning through the onboarding request | Explicit idempotent `POST /v1/seller/onboarding` plus lazy sync | The console has no database, and webhooks are asynchronous |
| Registry owns agent identity and lifecycle | Control plane owns lifecycle and credentials; registry projects public state | One writer prevents status drift (decision 21) |
| Policies stored in the application database | Seller agent store is authoritative; control plane stores a hash | Matches the existing seller agent policy enforcement (decision 22) |
| Seven agent statuses including `PENDING_VERIFICATION` | Six: `draft`, `configuring`, `testing`, `active`, `suspended`, `revoked` | Seller verification already covers the pending review; a second pending state would duplicate it |
| Commerce integrations, catalog, and policy editor in the tenancy design | Deferred to the companion onboarding spec | Keeps this document about authorization and isolation |

## 21. Acceptance criteria

- [ ] A signed-out visitor cannot reach any console page, route handler, or Server
      Action.
- [ ] A signed-in user with two organizations can switch workspaces and sees only the
      active organization's data.
- [ ] No console request for a user action carries `VERIFUND_OPS_TOKEN`.
- [ ] No request carries `X-Actor-Id`; audit rows record `actor_user_id`.
- [ ] Every tenant-owned table has an `organization_id` and every read is scoped by it.
- [ ] A non-participant receives `404` on a transaction, evidence item, or agreement.
- [ ] Both participants can read the same transaction.
- [ ] An unverified seller cannot register an agent, appear in discovery, be awarded, or
      configure a payout.
- [ ] Verification transitions are audited and visible to platform admins.
- [ ] A removed member cannot release funds with an unexpired token.
- [ ] Payout resolution reads `payment_accounts` only.
- [ ] Evidence written after the change lives under a tenant prefix.
- [ ] The reconciler writes tenant-attributed audit rows and never impersonates a
      tenant.
- [ ] Creating a business organization through Clerk does not create a `seller_profiles`
      row; only `POST /v1/seller/onboarding` does.
- [ ] Onboarding is idempotent and resumable, and its progress is stored server-side.
- [ ] A verified seller with a `configuring` agent cannot be discovered or called.
- [ ] Activation is blocked after a policy or card change until a retest passes.
- [ ] A suspended seller can fulfill an existing transaction but is paid only with a
      platform-admin release.
- [ ] A card URL cannot point at another seller's endpoint.
- [ ] Isolation tests 1–7, 14, and 21–30 pass in CI.
- [ ] The four seeded sellers still complete the sample brief end to end.
