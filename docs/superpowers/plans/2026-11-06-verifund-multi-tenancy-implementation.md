# Verifund Multi-Tenancy Implementation Plan (M0–M8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the shared ops token and hardcoded demo identities with Clerk-authenticated organizations, database-authoritative membership, tenant-scoped transaction access, a seller onboarding and verification gate, a control-plane agent lifecycle, tenant-safe money and evidence, and an optional PostgreSQL RLS layer.

**Architecture:** Clerk authenticates humans and asserts the active organization; the control plane verifies the session token, resolves an `Identity` from its own mirror tables, and authorizes every action through `TenantScope`. Tenancy state lives in new tables owned by `tenancy/repository.py`; transactions keep two organization columns plus a fixed counterparty visibility matrix. Seller onboarding is an explicit idempotent action, and the control plane owns agent lifecycle while the registry holds only a public projection. Money actions re-read membership, and suspended sellers are paid only through an audited release.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core/async + aiosqlite (PostgreSQL in M8), Pydantic v2, `clerk-backend-api`, `svix`, pytest/pytest-asyncio, Next.js 15.5.15, React 19, TypeScript, `@clerk/nextjs` v7, Vitest, pnpm, uv.

**Spec:** `docs/superpowers/specs/2026-11-06-verifund-multi-tenancy-design.md`

**Phase note:** the spec's M1–M4 boundaries are dependency-ordered here. The onboarding service and state machine land in M1 (Task 10), its authenticated routes in M2 (Task 15), and the wizard/workspace in M4. Every spec phase item is still covered; only the implementation order within M1–M4 differs.

## Global Constraints

- Next.js is **15.5.15**; use `middleware.ts`, not `proxy.ts`.
- `@clerk/nextjs` v7+: bare `clerkMiddleware()`; `await auth.protect()` at the top of every page, route handler, and Server Action. Do not use `createRouteMatcher`.
- The control plane accepts **session tokens only**: `accepts_token=["session_token"]`. Reject machine, OAuth, and pending-session (`sts`) tokens with `401`.
- Never accept `X-Actor-Id`, `X-Actor-Type`, a body `organization_id`, or a query `tenant_id` as authority.
- A non-participant gets `404 not_found`; `403 forbidden` is only used inside a participant.
- Selling requires a `kind='business'` organization. Personal organizations are buyer-only.
- Seller onboarding is `POST /v1/seller/onboarding`; `organization.created` must not create a `seller_profile`.
- The control plane owns agent status, credentials, and activation. The registry is a projection (`published` + card fields).
- The seller agent's store owns the negotiation policy body; the control plane stores `policy_ref`, `policy_version`, and `policy_hash`.
- Activation requires a passing `agent_test_runs` row matching the current `policy_hash` and `card_hash`.
- A suspended seller may fulfill existing transactions but is paid only with a `payout_releases` row.
- SQLite has no in-place migrations. Schema changes go through `create_schema()` plus idempotent `PRAGMA table_info` checks and `ALTER TABLE`.
- Python `>=3.12`; ruff line length 100. Run Python tests with `uv run pytest`.
- Console uses pnpm: `pnpm --filter marketmesh-console ...`.
- Do not add PostgreSQL/RLS before M8. M8 is gated and must not ship with M0–M7.
- Keep the four seeded sellers and `demo-buyer` working through the migration (decision 19).

---

## File Structure

**Control plane — new**
- `apps/verifund_control_plane/verifund_control_plane/tenancy/__init__.py`
- `.../tenancy/repository.py` — tenancy schema, CRUD, audit, onboarding, agent, payout-release tables
- `.../tenancy/identity.py` — `Identity`, `require_identity`, `resolve_identity`
- `.../tenancy/permissions.py` — role→permission and action→permission maps
- `.../tenancy/clerk.py` — `ClerkDirectory` protocol and Backend API implementation
- `.../tenancy/sync.py` — Clerk event and lazy-sync application
- `.../tenancy/tenant_repository.py` — `TenantScope`, `TenantRepository`
- `.../tenancy/transaction_access.py` — `require_transaction`, visibility checks
- `.../tenancy/backfill.py` — demo and legacy backfill
- `.../tenancy/routes.py` — `/ops` verification and review endpoints
- `.../onboarding/service.py`, `.../onboarding/routes.py` — seller onboarding and verification submission
- `.../agents/lifecycle.py`, `.../agents/credentials.py`, `.../agents/registry_sync.py`, `.../agents/routes.py`
- `.../tenancy/rls.sql` (M8 only)

**Control plane — modified**
- `.../app.py` — wire tenancy, onboarding, agents, webhook verification
- `.../settings.py` — Clerk keys, webhook secret, agent ceiling
- `.../repository.py` — tenant columns, audit rebuild, webhook source
- `.../api/webhooks.py` — `POST /v1/webhooks/clerk`
- `.../api/ops.py` — award/token/invitation gate checks, payout release
- `.../service.py` — award gate, payout-account resolution, evidence keys
- `.../reconciler.py` — payout release condition
- `.../evidence.py` — tenant-prefixed storage and legacy fallback

**Console — new**
- `apps/console/lib/control-plane.ts`, `apps/console/lib/console-session.ts`, `apps/console/lib/seller-access.ts`, `apps/console/lib/onboarding.ts`, `apps/console/lib/invitation.ts`
- `apps/console/middleware.ts`
- `apps/console/app/sign-in/[[...sign-in]]/page.tsx`, `apps/console/app/sign-up/[[...sign-up]]/page.tsx`
- `apps/console/app/api/webhooks/clerk/route.ts`
- `apps/console/app/seller/onboarding/**`
- `apps/console/app/seller/agents/**`
- `apps/console/app/(console)/admin/verification/**`

**Console — modified**
- `apps/console/app/layout.tsx`, `app/(console)/layout.tsx`, `components/layout/console-layout.tsx`
- `apps/console/app/(console)/agreements/[id]/actions.ts`
- `apps/console/app/seller/layout.tsx`, `app/seller/actions.ts`
- `apps/console/app/fulfillment/access/[token]/actions.ts`
- every `app/api/**/route.ts` and `app/**/actions.ts`

**Tests**
- Python: `tests/unit/test_tenancy_*.py`, `test_seller_onboarding.py`, `test_agent_*.py`, `test_payment_accounts.py`, `test_payout_releases.py`, `test_tenant_isolation.py`, `test_runs_tenancy.py`, `test_registry_projection.py`
- Console: `apps/console/tests/lib/control-plane.test.ts`, `console-session.test.ts`, `seller-access.test.ts`, `onboarding.test.ts`, `apps/console/tests/app/auth-routes.test.tsx`, `route-guards.test.ts`, `agreement-actions.test.ts`

---

## Milestone M0 — Clerk in the console

### Task 1: Clerk dependency, provider, and public auth routes

**Files:**
- Modify: `apps/console/package.json`, `apps/console/app/layout.tsx`, `.env.example`
- Create: `apps/console/app/sign-in/[[...sign-in]]/page.tsx`, `apps/console/app/sign-up/[[...sign-up]]/page.tsx`
- Test: `apps/console/tests/app/auth-routes.test.tsx`

**Interfaces:**
- Produces: `<ClerkProvider>` at the root; public `/sign-in` and `/sign-up` pages; env names `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`.

- [ ] **Step 1: Write the failing test**

```tsx
// apps/console/tests/app/auth-routes.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({
  SignIn: () => <div data-testid="clerk-sign-in" />,
  SignUp: () => <div data-testid="clerk-sign-up" />,
}));

import SignInPage from "@/app/sign-in/[[...sign-in]]/page";
import SignUpPage from "@/app/sign-up/[[...sign-up]]/page";

describe("public auth routes", () => {
  it("renders Clerk sign-in", () => {
    render(<SignInPage />);
    expect(screen.getByTestId("clerk-sign-in")).toBeInTheDocument();
  });

  it("renders Clerk sign-up", () => {
    render(<SignUpPage />);
    expect(screen.getByTestId("clerk-sign-up")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/auth-routes.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```bash
pnpm --filter marketmesh-console add @clerk/nextjs
```

```tsx
// app/sign-in/[[...sign-in]]/page.tsx
import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="mm-auth-page">
      <SignIn />
    </main>
  );
}
```

```tsx
// app/sign-up/[[...sign-up]]/page.tsx
import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <main className="mm-auth-page">
      <SignUp />
    </main>
  );
}
```

Wrap the root body in `app/layout.tsx`:

```tsx
import { ClerkProvider } from "@clerk/nextjs";
// ...
return (
  <ClerkProvider>
    <html lang="en">
      <body className={...}>{children}</body>
    </html>
  </ClerkProvider>
);
```

Add to `.env.example`:

```dotenv
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_replace_me
CLERK_SECRET_KEY=sk_test_replace_me
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/auth-routes.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/package.json pnpm-lock.yaml apps/console/app/layout.tsx apps/console/app/sign-in apps/console/app/sign-up apps/console/tests/app/auth-routes.test.tsx .env.example
git commit -m "feat(console): add Clerk provider and auth routes"
```

### Task 2: Bare middleware and the console session helper

**Files:**
- Create: `apps/console/middleware.ts`, `apps/console/lib/console-session.ts`
- Test: `apps/console/tests/lib/console-session.test.ts`

**Interfaces:**
- Produces: `consoleSession(): Promise<{ userId: string; orgId: string | null; orgRole: string | null }>`, which throws on an unauthenticated request.
- Produces: `middleware` from `clerkMiddleware()` with no route matcher.

- [ ] **Step 1: Write the failing test**

```ts
// apps/console/tests/lib/console-session.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";

const protect = vi.fn();
vi.mock("@clerk/nextjs/server", () => ({
  auth: Object.assign(vi.fn(), { protect }),
}));

import { consoleSession } from "@/lib/console-session";

describe("consoleSession", () => {
  beforeEach(() => protect.mockReset());

  it("returns the verified identity", async () => {
    protect.mockResolvedValue({ userId: "user_1", orgId: "org_1", orgRole: "org:admin" });
    await expect(consoleSession()).resolves.toEqual({
      userId: "user_1",
      orgId: "org_1",
      orgRole: "org:admin",
    });
  });

  it("rejects when Clerk has no session", async () => {
    protect.mockRejectedValue(new Error("unauthenticated"));
    await expect(consoleSession()).rejects.toThrow("unauthenticated");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter marketmesh-console exec vitest run tests/lib/console-session.test.ts`
Expected: FAIL — `@/lib/console-session` not found.

- [ ] **Step 3: Implement**

```ts
// lib/console-session.ts
import { auth } from "@clerk/nextjs/server";

export async function consoleSession() {
  const { userId, orgId, orgRole } = await auth.protect();
  if (!userId) throw new Error("unauthenticated");
  return { userId, orgId: orgId ?? null, orgRole: orgRole ?? null };
}
```

```ts
// middleware.ts
import { clerkMiddleware } from "@clerk/nextjs/server";

export default clerkMiddleware();
```

Do **not** add a matcher. Protection lives in each page, route handler, and action.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter marketmesh-console exec vitest run tests/lib/console-session.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/middleware.ts apps/console/lib/console-session.ts apps/console/tests/lib/console-session.test.ts
git commit -m "feat(console): add bare Clerk middleware and session helper"
```

### Task 3: Console shell guard, user identity, and organization switcher

**Files:**
- Modify: `apps/console/app/(console)/layout.tsx`, `apps/console/components/layout/console-layout.tsx`
- Test: `apps/console/tests/app/console-layout.test.tsx`

**Interfaces:**
- Consumes: `consoleSession()`.
- Produces: `<ConsoleLayout userId={...} orgId={...}>`; the header renders `<OrganizationSwitcher />` and `<UserButton />`.

- [ ] **Step 1: Write the failing test**

```tsx
// apps/console/tests/app/console-layout.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({
  OrganizationSwitcher: () => <div data-testid="org-switcher" />,
  UserButton: () => <div data-testid="user-button" />,
}));

import { ConsoleLayout } from "@/components/layout/console-layout";

describe("ConsoleLayout", () => {
  it("shows the organization and user controls", () => {
    render(
      <ConsoleLayout userId="user_1" orgId="org_1">
        <div>content</div>
      </ConsoleLayout>,
    );
    expect(screen.getByTestId("org-switcher")).toBeInTheDocument();
    expect(screen.getByTestId("user-button")).toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/console-layout.test.tsx`
Expected: FAIL — `ConsoleLayout` does not accept the new props.

- [ ] **Step 3: Implement**

```tsx
// app/(console)/layout.tsx
import { ConsoleLayout } from "@/components/layout/console-layout";
import { consoleSession } from "@/lib/console-session";

export const dynamic = "force-dynamic";

export default async function Layout({ children }: { children: React.ReactNode }) {
  const { userId, orgId } = await consoleSession();
  return (
    <ConsoleLayout userId={userId} orgId={orgId}>
      {children}
    </ConsoleLayout>
  );
}
```

In `components/layout/console-layout.tsx`, accept `{ children, userId, orgId }`, keep the existing shell markup, and add to the header:

```tsx
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
// ...
<OrganizationSwitcher
  afterCreateOrganizationUrl="/"
  afterSelectOrganizationUrl="/"
  hidePersonal={false}
/>
<UserButton />
```

Render `userId` only as a `title` attribute; never as authorization input.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/console-layout.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/app/\(console\)/layout.tsx apps/console/components/layout/console-layout.tsx apps/console/tests/app/console-layout.test.tsx
git commit -m "feat(console): guard the shell and add org switching"
```

### Task 4: `controlPlaneForUser` and agreement actions without `demo-buyer`

**Files:**
- Create: `apps/console/lib/control-plane.ts`
- Modify: `apps/console/app/(console)/agreements/[id]/actions.ts`
- Test: `apps/console/tests/lib/control-plane.test.ts`, `apps/console/tests/app/agreement-actions.test.ts`

**Interfaces:**
- Produces: `controlPlaneForUser(path, init?): Promise<Response>` — forwards `Authorization: Bearer <session token>` and no actor headers.
- Produces: `controlPlaneAsPlatform(path, init?, timeoutMs?)` — the existing ops-token proxy, used only by platform routes and webhooks.

- [ ] **Step 1: Write the failing test**

```ts
// apps/console/tests/lib/control-plane.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";

const getToken = vi.fn();
vi.mock("@clerk/nextjs/server", () => ({
  auth: vi.fn(async () => ({ getToken, orgId: "org_1" })),
}));

import { controlPlaneForUser } from "@/lib/control-plane";

describe("controlPlaneForUser", () => {
  beforeEach(() => {
    getToken.mockReset();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  });

  it("requests a token for the active organization", async () => {
    getToken.mockResolvedValue("tok_1");
    await controlPlaneForUser("/transactions");
    expect(getToken).toHaveBeenCalledWith({ organizationId: "org_1" });
    const [, init] = vi.mocked(fetch).mock.calls[0];
    const headers = init?.headers as Headers;
    expect(headers.get("authorization")).toBe("Bearer tok_1");
    expect(headers.get("x-actor-id")).toBeNull();
  });

  it("throws instead of falling back to the ops token", async () => {
    getToken.mockResolvedValue(null);
    await expect(controlPlaneForUser("/transactions")).rejects.toThrow("not signed in");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter marketmesh-console exec vitest run tests/lib/control-plane.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```ts
// lib/control-plane.ts
import { auth } from "@clerk/nextjs/server";

const CONTROL_PLANE =
  process.env.VERIFUND_CONTROL_PLANE_URL ?? "http://127.0.0.1:9300";

export async function controlPlaneForUser(path: string, init: RequestInit = {}) {
  const { getToken, orgId } = await auth();
  const token = await getToken({ organizationId: orgId ?? undefined });
  if (!token) throw new Error("not signed in");
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
  return fetch(`${CONTROL_PLANE}${path}`, {
    ...init,
    cache: "no-store",
    headers,
  });
}

export async function controlPlaneAsPlatform(
  path: string,
  init: RequestInit = {},
  timeoutMs = 10_000,
) {
  const token = process.env.VERIFUND_OPS_TOKEN ?? "dev-verifund-ops";
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
  return fetch(`${CONTROL_PLANE}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: AbortSignal.timeout(timeoutMs),
  });
}
```

Rewrite `agreements/[id]/actions.ts`:

- Delete `actorHeaders` and `resolveBuyerId`.
- Replace every control-plane `fetch` with `controlPlaneForUser`.
- Keep the orchestrator resume body unchanged.

```ts
import { controlPlaneForUser } from "@/lib/control-plane";

async function recordDecision(id, version, hash, decision, note, idempotencyKey) {
  const tokenRes = await controlPlaneForUser(
    `/agreements/${encodeURIComponent(id)}/approval-token`,
    { method: "POST", headers: { "Idempotency-Key": idempotencyKey } },
  );
  // ... unchanged response handling
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter marketmesh-console exec vitest run tests/lib/control-plane.test.ts tests/app/agreement-actions.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/lib/control-plane.ts apps/console/app/\(console\)/agreements/\[id\]/actions.ts apps/console/tests/lib/control-plane.test.ts apps/console/tests/app/agreement-actions.test.ts
git commit -m "feat(console): forward the Clerk token to the control plane"
```

### Task 5: Sweep every route handler, action, and demo identity

**Files:**
- Modify: every `apps/console/app/api/**/route.ts`, every `apps/console/app/**/actions.ts`, `apps/console/app/api/copilotkit/[[...slug]]/route.ts`
- Test: `apps/console/tests/app/route-guards.test.ts`

**Interfaces:**
- Produces: a repo-wide invariant test: no `demo-buyer`/`demo-user`; every non-public page, route handler, and action calls `auth.protect()`.

- [ ] **Step 1: Write the failing test**

```ts
// apps/console/tests/app/route-guards.test.ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const APP = path.resolve(__dirname, "../../app");
const PUBLIC = new Set([
  "app/sign-in/[[...sign-in]]/page.tsx",
  "app/sign-up/[[...sign-up]]/page.tsx",
  "app/api/webhooks/clerk/route.ts",
  "app/fulfillment/access/[token]/page.tsx",
  "app/fulfillment/access/[token]/actions.ts",
]);

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

describe("console guards", () => {
  const files = walk(APP);

  it("has no hardcoded demo identities", () => {
    const offenders = files.filter((file) => {
      const text = readFileSync(file, "utf8");
      return text.includes("demo-buyer") || text.includes("demo-user");
    });
    expect(offenders).toEqual([]);
  });

  it("protects every route handler and action", () => {
    const guarded = files.filter(
      (file) =>
        (file.endsWith("/page.tsx") ||
          file.endsWith("/route.ts") ||
          file.endsWith("/actions.ts")) &&
        !PUBLIC.has(path.relative(APP, file)),
    );
    const offenders = guarded.filter(
      (file) => !readFileSync(file, "utf8").includes("auth.protect()"),
    );
    expect(offenders).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/route-guards.test.ts`
Expected: FAIL — offenders list `demo-buyer`, `demo-user`, and unguarded handlers.

- [ ] **Step 3: Implement**

At the top of every page, handler, and action:

```ts
import { auth } from "@clerk/nextjs/server";
// ...
await auth.protect();
```

For `app/api/copilotkit/[[...slug]]/route.ts`, change `identifyUser` to return the Clerk identity:

```ts
const { userId } = await auth.protect();
// identifyUser: async () => ({ id: userId })
```

Replace the seller API proxy routes that used the ops token with `controlPlaneForUser` when they serve a user action. Keep `controlPlaneAsPlatform` only in `app/api/webhooks/clerk/route.ts` and platform-admin routes.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/route-guards.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/app apps/console/tests/app/route-guards.test.ts
git commit -m "feat(console): protect every route and remove demo identities"
```

---

## Milestone M1 — tenant schema, webhooks, onboarding state, backfill

### Task 6: Tenancy schema and repository

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/tenancy/__init__.py`, `.../tenancy/repository.py`
- Modify: `.../app.py`, `.../settings.py`
- Test: `tests/unit/test_tenancy_repository.py`

**Interfaces:**
- Produces: `TenancyRepository(engine)` with `create_schema()`, `upsert_user`, `get_user_by_clerk_id`, `anonymize_user`, `upsert_organization`, `get_organization`, `get_organization_by_clerk_id`, `update_organization`, `set_organization_status_by_clerk_id`, `upsert_membership`, `get_membership`, `set_membership_status`, `upsert_membership_from_clerk`, `remove_membership_from_clerk`, `create_personal_organization`, `ensure_personal_organization`, `add_platform_admin`, `is_platform_admin`, `unique_seller_id`, `upsert_seller_profile`, `get_seller_profile`, `get_seller_profile_by_organization`, `set_verification_status`, `ensure_seed_organization`, `ensure_seed_buyer_organization`, `upsert_invitation_from_clerk`, `revoke_invitation_from_clerk`, `record_audit`, `list_audit`.
- Note: `audit_log` is owned by `Repository` (Task 7). `TenancyRepository` writes to it with raw SQL and does not define a second table with the same name.
- Produces: `app.state.tenancy`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tenancy_repository.py
from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine


async def test_organization_membership_and_seller_profile_round_trip(tmp_path):
    from verifund_control_plane.tenancy.repository import TenancyRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tenancy.db'}")
    store = TenancyRepository(engine)
    await store.create_schema()
    try:
        user = await store.upsert_user("user_1", "a@example.com", "A")
        org = await store.upsert_organization("org_1", "Acme", "acme")
        await store.upsert_membership(org["id"], user["id"], "org:admin", "mem_1")
        membership = await store.get_membership(org["id"], user["id"])
        assert membership["role"] == "org:admin"
        assert membership["status"] == "active"

        seller = await store.upsert_seller_profile(org["id"], "acme", "Acme")
        assert seller["verification_status"] == "unverified"
        assert await store.get_seller_profile("acme") is not None
    finally:
        await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tenancy_repository.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create the tables with SQLAlchemy Core, mirroring spec §7.1–7.2:

```python
# tenancy/repository.py
class TenancyRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.metadata = MetaData()
        self._define_tables()

    def _define_tables(self) -> None:
        self.users = Table(
            "users", self.metadata,
            Column("id", String, primary_key=True),
            Column("clerk_user_id", String, unique=True, nullable=False),
            Column("email", String), Column("name", String),
            Column("status", String, nullable=False, default="active"),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.organizations = Table(
            "organizations", self.metadata,
            Column("id", String, primary_key=True),
            Column("clerk_org_id", String, unique=True),
            Column("kind", String, nullable=False),          # business | personal | platform
            Column("name", String, nullable=False),
            Column("slug", String, unique=True),
            Column("status", String, nullable=False, default="active"),
            Column("owner_user_id", String),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.organization_members = Table(
            "organization_members", self.metadata,
            Column("id", String, primary_key=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("user_id", String, nullable=False, index=True),
            Column("role", String, nullable=False),
            Column("status", String, nullable=False, default="active"),
            Column("clerk_membership_id", String, unique=True),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.platform_admins = Table(
            "platform_admins", self.metadata,
            Column("user_id", String, primary_key=True),
            Column("granted_by", String), Column("created_at", String, nullable=False),
        )
        self.seller_profiles = Table(
            "seller_profiles", self.metadata,
            Column("seller_id", String, primary_key=True),
            Column("organization_id", String, unique=True, nullable=False),
            Column("display_name", String, nullable=False),
            Column("verification_status", String, nullable=False, default="unverified"),
            Column("verification_note", String), Column("verified_at", String),
            Column("verified_by", String),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
        self.buyer_profiles = Table(
            "buyer_profiles", self.metadata,
            Column("buyer_id", String, primary_key=True),
            Column("organization_id", String, unique=True, nullable=False),
            Column("created_at", String, nullable=False),
        )
        self.organization_invitations = Table(
            "organization_invitations", self.metadata,
            Column("id", String, primary_key=True),
            Column("organization_id", String, nullable=False, index=True),
            Column("clerk_invitation_id", String, unique=True),
            Column("email", String, nullable=False),
            Column("role", String, nullable=False),
            Column("status", String, nullable=False),
            Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False),
        )
```

`create_schema()` uses `configure_sqlite` + `metadata.create_all`. Implement the CRUD methods with `sqlite_insert(...).on_conflict_do_update` and return `dict(row._mapping)`.

`record_audit` writes to the `Repository`-owned table with raw SQL, because the two repositories share one database but not one `MetaData`:

```python
async def record_audit(self, *, scope, action, organization_id=None, transaction_id=None,
                       actor_user_id=None, actor_type="user", resource_id=None, payload=None):
    async with self.engine.begin() as conn:
        await conn.exec_driver_sql(
            "INSERT INTO audit_log (audit_id, scope, transaction_id, organization_id,"
            " actor_user_id, actor_type, action, resource_id, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), scope, transaction_id, organization_id, actor_user_id,
             actor_type, action, resource_id, json.dumps(payload or {}),
             datetime.now(UTC).isoformat()),
        )
```

Add settings fields:

```python
tenancy_enabled: bool = Field(default=False, validation_alias="VERIFUND_TENANCY_ENABLED")
```

Wire in `app.py`:

```python
tenancy = TenancyRepository(engine)
app.state.tenancy = tenancy
# inside lifespan, after repo.create_schema():
await app.state.tenancy.create_schema()
```

Inline the settings in each test. **Do not** add a shared test-support module or a second app factory in this plan.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tenancy_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy apps/verifund_control_plane/verifund_control_plane/app.py apps/verifund_control_plane/verifund_control_plane/settings.py tests/unit/test_tenancy_repository.py
git commit -m "feat(tenancy): add identity and membership schema"
```

### Task 7: Rebuild `audit_log` and add `webhook_events.source`

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_audit_scope.py`

**Interfaces:**
- Produces: `audit_log` accepts `transaction_id = NULL` with `scope`, `organization_id`, `actor_user_id`, `actor_type`, and `resource_id`; the legacy `actor`/`note` columns stay nullable for old writers. `webhook_events` gains `source` (default `'paypal'`); `mode` stays NOT NULL with default `'live'`, and Clerk rows pass `mode='clerk'`.

- [ ] **Step 1: Write the failing test**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.repository import Repository


async def test_organization_audit_has_no_transaction(tmp_path):
    repo = Repository(create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"))
    await repo.create_schema()
    async with repo.transaction() as conn:
        await conn.execute(repo.audit_log.insert().values(
            audit_id="a1", scope="organization", transaction_id=None,
            organization_id="org_1", actor_user_id="user_1", actor_type="user",
            action="seller.verification.approved", resource_id="acme",
            payload={}, created_at="2026-11-06T00:00:00+00:00",
        ))
    async with repo.transaction() as conn:
        row = (await conn.execute(select(repo.audit_log))).first()
    assert row.organization_id == "org_1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_audit_scope.py -q`
Expected: FAIL — `scope` is unknown / `transaction_id` is NOT NULL.

- [ ] **Step 3: Implement**

Change `audit_log` in `_define_tables` to this shape (legacy `actor`/`note` become nullable so old writes keep working):

```python
self.audit_log = Table(
    "audit_log", self.metadata,
    Column("audit_id", String, primary_key=True),
    Column("scope", String, nullable=False, default="transaction"),
    Column("transaction_id", String, nullable=True, index=True),
    Column("organization_id", String, nullable=True, index=True),
    Column("actor_user_id", String, nullable=True),
    Column("actor_type", String, nullable=False, default="user"),
    Column("actor", String, nullable=True),          # legacy
    Column("action", String, nullable=False),
    Column("resource_id", String, nullable=True),
    Column("note", String, nullable=True),          # legacy
    Column("payload", JSON, nullable=False),
    Column("created_at", String, nullable=False),
)
```

`create_schema()` cannot alter NOT NULL in SQLite. Add a rebuild step guarded by `PRAGMA table_info(audit_log)`:

```python
columns = {row[1]: row for row in await conn.exec_driver_sql("PRAGMA table_info(audit_log)")}
if "scope" not in columns:
    await conn.exec_driver_sql("ALTER TABLE audit_log RENAME TO audit_log_old")
    await conn.run_sync(self.audit_log.create)
    await conn.exec_driver_sql("""
        INSERT INTO audit_log (audit_id, scope, transaction_id, organization_id,
            actor_user_id, actor_type, actor, action, resource_id, note, payload, created_at)
        SELECT audit_id, 'transaction', transaction_id, NULL, NULL, 'user',
            actor, action, NULL, note, payload, created_at FROM audit_log_old
    """)
    await conn.exec_driver_sql("DROP TABLE audit_log_old")
```

Keep `Repository.audit(...)` writing `actor=audit.actor` and `note=audit.note` for now; new tenancy writes pass `actor_user_id`, `actor_type`, `scope`, and `resource_id`. This keeps every existing service call compiling and makes the migration copy lossless.

Add `source` to `webhook_events` with a default:

```python
Column("source", String, nullable=False, default="paypal")
```

For existing databases, the `PRAGMA table_info(webhook_events)` guard adds the column with `DEFAULT 'paypal'`. Do not make `mode` nullable: Clerk rows pass `mode='clerk'`, and existing PayPal paths keep their current values.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_audit_scope.py tests/unit/test_verifund_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py tests/unit/test_audit_scope.py
git commit -m "feat(repo): scope audit rows and tag webhook sources"
```

### Task 8: Clerk webhook ingestion with Svix verification

**Files:**
- Modify: `pyproject.toml`, `.../settings.py`, `.../app.py`, `.../api/webhooks.py`
- Create: `apps/console/app/api/webhooks/clerk/route.ts`
- Test: `tests/unit/test_clerk_webhooks.py`

**Interfaces:**
- Produces: `POST /v1/webhooks/clerk` on the control plane; verifies the raw body with `svix.Webhook(secret).verify(body, headers)`.
- Produces: `app.state.clerk_verifier(body: bytes, headers: dict[str, str]) -> dict` (injectable for tests).
- Consumes: `TenancyRepository` for idempotent `webhook_events` writes.

- [ ] **Step 1: Write the failing test**

```python
async def test_clerk_webhook_is_idempotent(client):
    app = client._transport.app
    app.state.clerk_verifier = lambda body, headers: {
        "type": "user.created",
        "data": {"id": "user_1", "email_addresses": [{"email_address": "a@example.com"}]},
    }
    payload = b'{"type":"user.created"}'
    first = await client.post("/v1/webhooks/clerk", content=payload,
                              headers={"svix-id": "msg_1", "content-type": "application/json"})
    second = await client.post("/v1/webhooks/clerk", content=payload,
                               headers={"svix-id": "msg_1", "content-type": "application/json"})
    assert first.status_code == 200
    assert second.status_code == 200
    rows = await app.state.repo.list_webhook_events(source="clerk")
    assert len([r for r in rows if r["event_id"] == "msg_1"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_clerk_webhooks.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Implement**

Add `"svix>=1.40,<2"` to `pyproject.toml` dependencies, then `uv sync`.

`tenancy/repository.py` imports `json`, `datetime`, `UTC`, and `uuid4` for the raw audit insert.

Add to `Settings`:

```python
clerk_webhook_secret: str = Field(
    default="", validation_alias="CLERK_WEBHOOK_SIGNING_SECRET"
)
```

```python
# api/webhooks.py
import hashlib

from svix.webhooks import Webhook, WebhookVerificationError
from verifund_control_plane.tenancy.sync import apply_clerk_event

def verify_clerk_payload(secret: str, body: bytes, headers: dict[str, str]) -> dict:
    try:
        return Webhook(secret).verify(body, headers)
    except WebhookVerificationError as exc:
        raise VerifundError("unauthorized", "invalid webhook signature", status_code=401) from exc

@router.post("/v1/webhooks/clerk")
async def clerk_webhook(request: Request) -> dict[str, str]:
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    verifier = getattr(request.app.state, "clerk_verifier", None)
    event = verifier(body, headers) if verifier else verify_clerk_payload(
        request.app.state.settings.clerk_webhook_secret, body, headers
    )
    event_id = headers.get("svix-id")
    if not event_id:
        raise VerifundError("invalid_request", "svix-id is required", status_code=400)
    repo = request.app.state.repo
    if await repo.webhook_event_exists("clerk", event_id):
        return {"status": "duplicate"}
    await repo.record_webhook_event(
        source="clerk", event_id=event_id, event_type=event["type"], mode="clerk",
        payload=event, payload_hash=hashlib.sha256(body).hexdigest(),
        verified=True, status="processed",
    )
    await apply_clerk_event(request.app.state.tenancy, event)
    return {"status": "ok"}
```

Add `source: str = "paypal"` to `record_webhook_event`/`list_webhook_events`, plus `webhook_event_exists`. `record_webhook_event` must fill the existing required columns (`payload_hash`, `mode`, `verified`, `status`, `received_at`) and use `on_conflict_do_nothing` on `event_id`.

Console forwarder:

```ts
// app/api/webhooks/clerk/route.ts
import { controlPlaneAsPlatform } from "@/lib/control-plane";

export async function POST(request: Request) {
  const body = await request.text();
  const headers = new Headers({ "content-type": "application/json" });
  for (const name of ["svix-id", "svix-timestamp", "svix-signature"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const response = await controlPlaneAsPlatform("/v1/webhooks/clerk", {
    method: "POST",
    headers,
    body,
  });
  return new Response(await response.text(), { status: response.status });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_clerk_webhooks.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock apps/verifund_control_plane/verifund_control_plane/api/webhooks.py apps/verifund_control_plane/verifund_control_plane/settings.py apps/console/app/api/webhooks/clerk/route.ts tests/unit/test_clerk_webhooks.py
git commit -m "feat(webhooks): ingest Clerk events in the control plane"
```

### Task 9: Apply Clerk events to the mirror

**Files:**
- Create: `.../tenancy/sync.py`
- Test: `tests/unit/test_tenancy_sync.py`

**Interfaces:**
- Produces: `apply_clerk_event(store: TenancyRepository, event: dict) -> None`.
- Behavior: `organization.created` creates only the organization; membership deletion sets `status='removed'`; user deletion anonymizes PII.

- [ ] **Step 1: Write the failing test**

```python
async def test_org_created_does_not_create_a_seller_profile(store):
    await apply_clerk_event(store, {
        "type": "organization.created",
        "data": {"id": "org_1", "name": "Acme", "slug": "acme"},
    })
    org = await store.get_organization_by_clerk_id("org_1")
    assert org["kind"] == "business"
    assert await store.get_seller_profile_by_organization(org["id"]) is None


async def test_membership_deleted_marks_removed(store):
    user = await store.upsert_user("user_1", "a@example.com", "A")
    org = await store.upsert_organization("org_1", "Acme", "acme")
    await store.upsert_membership(org["id"], user["id"], "org:member", "mem_1")
    await apply_clerk_event(store, {
        "type": "organizationMembership.deleted",
        "data": {"organization": {"id": "org_1"}, "public_user_data": {"user_id": "user_1"}},
    })
    row = await store.get_membership(org["id"], user["id"])
    assert row["status"] == "removed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tenancy_sync.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# tenancy/sync.py
ORGANIZATION_EVENTS = {
    "organization.created", "organization.updated", "organization.deleted",
}

async def apply_clerk_event(store, event: dict) -> None:
    kind = event["type"]
    data = event.get("data") or {}
    if kind in {"user.created", "user.updated"}:
        await store.upsert_user(
            data["id"],
            (data.get("email_addresses") or [{}])[0].get("email_address"),
            " ".join(filter(None, [data.get("first_name"), data.get("last_name")])) or None,
        )
    elif kind == "user.deleted":
        await store.anonymize_user(data["id"])
    elif kind == "organization.created":
        await store.upsert_organization(data["id"], data.get("name", ""), data.get("slug"))
    elif kind == "organization.updated":
        await store.update_organization(data["id"], data.get("name"), data.get("slug"))
    elif kind == "organization.deleted":
        await store.set_organization_status_by_clerk_id(data["id"], "disabled")
    elif kind == "organizationMembership.created":
        await store.upsert_membership_from_clerk(data)
    elif kind == "organizationMembership.updated":
        await store.upsert_membership_from_clerk(data)
    elif kind == "organizationMembership.deleted":
        await store.remove_membership_from_clerk(data)
    elif kind == "organizationInvitation.created":
        await store.upsert_invitation_from_clerk(data)
    elif kind == "organizationInvitation.revoked":
        await store.revoke_invitation_from_clerk(data)
```

`upsert_membership_from_clerk` resolves the local user and organization by Clerk ID and creates a local row if both exist; if the user is not mirrored yet, it stores the membership payload in `organization_invitations` only when it is an invitation, not a membership. This prevents a membership for an unknown user.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tenancy_sync.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/sync.py tests/unit/test_tenancy_sync.py
git commit -m "feat(tenancy): apply Clerk events without implicit seller intent"
```

### Task 10: Seller onboarding and verification state machine

**Files:**
- Create: `.../onboarding/__init__.py`, `.../onboarding/service.py`
- Test: `tests/unit/test_seller_onboarding.py`

**Interfaces:**
- Produces: `create_onboarding(store, organization_id, actor_user_id) -> dict`, `submit_verification(...)`, `decide_verification(..., decision, note, reviewer_user_id)`.
- Produces: `store.upsert_onboarding(organization_id, status, current_step) -> dict`, `store.get_onboarding(organization_id) -> dict | None`.
- The service and store land here; `onboarding/routes.py` and its wiring are created in Task 15, after `require_identity` exists in M2.

- [ ] **Step 1: Write the failing test**

```python
async def test_create_onboarding_is_idempotent(store):
    org = await store.upsert_organization("org_1", "Acme", "acme")
    user = await store.upsert_user("user_1", "a@example.com", "A")
    first = await create_onboarding(store, org["id"], user["id"])
    second = await create_onboarding(store, org["id"], user["id"])
    assert first["seller_id"] == second["seller_id"]
    assert (await store.get_onboarding(org["id"]))["status"] == "in_progress"


async def test_personal_org_is_rejected(store):
    personal = await store.create_personal_organization(
        (await store.upsert_user("user_2", "b@example.com", "B"))["id"]
    )
    with pytest.raises(VerifundError) as exc:
        await create_onboarding(store, personal["id"], "user_2")
    assert exc.value.status_code == 403
```

The `store` fixture creates `Repository` first (for `audit_log`) and then `TenancyRepository`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_onboarding.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Add the onboarding table to `tenancy/repository.py`:

```python
self.seller_onboarding = Table(
    "seller_onboarding", self.metadata,
    Column("organization_id", String, primary_key=True),
    Column("status", String, nullable=False),
    Column("current_step", String, nullable=False),
    Column("completed_steps", JSON, nullable=False),
    Column("submitted_at", String), Column("completed_at", String),
    Column("updated_at", String, nullable=False),
)
self.seller_verifications = Table(
    "seller_verifications", self.metadata,
    Column("id", String, primary_key=True),
    Column("organization_id", String, nullable=False, index=True),
    Column("submitted_by", String, nullable=False),
    Column("documents", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("reviewer_user_id", String), Column("decision_note", String),
    Column("decided_at", String), Column("created_at", String, nullable=False),
)
```

`create_onboarding`:

```python
async def create_onboarding(store, organization_id: str, actor_user_id: str) -> dict:
    org = await store.get_organization(organization_id)
    if org is None or org["kind"] != "business":
        raise VerifundError("forbidden", "seller onboarding requires a business organization", 403)
    existing = await store.get_seller_profile_by_organization(organization_id)
    if existing:
        return existing
    seller_id = await store.unique_seller_id(org["slug"] or org["name"])
    profile = await store.upsert_seller_profile(organization_id, seller_id, org["name"])
    await store.upsert_onboarding(organization_id, "in_progress", "profile")
    await store.record_audit(
        scope="organization", organization_id=organization_id,
        actor_user_id=actor_user_id, actor_type="user",
        action="seller.onboarding.started", resource_id=seller_id, payload={},
    )
    return profile
```

Verification transitions use the exact map from spec §9.3. Reject any transition not listed with `409 invalid_state`. `decide_verification` requires a platform admin and writes an audit row.

Task 15 adds thin routes that call `require_identity` and this service.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_seller_onboarding.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/onboarding apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py tests/unit/test_seller_onboarding.py
git commit -m "feat(onboarding): explicit idempotent seller onboarding"
```

### Task 11: Backfill and demo seed

**Files:**
- Create: `.../tenancy/backfill.py`
- Modify: `.../app.py` (run only when `tenancy_enabled`), `.../repository.py`
- Test: `tests/unit/test_tenancy_backfill.py`

**Interfaces:**
- Produces: `backfill_tenancy(repo, store) -> None`; idempotent. Payment accounts are seeded in Task 31, after their table exists.
- Backfills `transactions.buyer_organization_id` / `seller_organization_id`, `evidence.organization_id`, `agreements` columns, `audit_log.organization_id`.

- [ ] **Step 1: Write the failing test**

```python
async def test_backfill_maps_demo_sellers_and_buyer(repo, store):
    await seed_legacy_award(repo, seller_id="northwind-audio", buyer_id="demo-buyer")
    await backfill_tenancy(repo, store)
    async with repo.transaction() as conn:
        row = (await conn.execute(select(repo.transactions))).first()
    assert row.seller_organization_id
    assert row.buyer_organization_id
    seller = await store.get_seller_profile("northwind-audio")
    assert seller["verification_status"] == "verified"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tenancy_backfill.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
async def backfill_tenancy(repo, store) -> None:
    async with repo.transaction() as conn:
        rows = (await conn.execute(select(repo.transactions))).all()
        for row in rows:
            seller_org = await store.ensure_seed_organization(
                seller_id=row.seller_id, kind="business",
                verified=row.seller_id in SEED_SELLERS,
            )
            buyer_org = await store.ensure_seed_buyer_organization(row.buyer_id)
            await conn.execute(
                repo.transactions.update()
                .where(repo.transactions.c.transaction_id == row.transaction_id)
                .values(
                    seller_organization_id=seller_org["id"],
                    buyer_organization_id=buyer_org["id"],
                )
            )
```

`ensure_seed_organization` derives `seller_id` from the slug if the row does not exist, creates the profile with the requested verification status, and is idempotent. `SEED_SELLERS = {"northwind-audio", "circuitforge", "aurora-supply", "summit-tech"}`.

Run only in `lifespan` when `settings.tenancy_enabled` and the `organizations` table is empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tenancy_backfill.py -q`
Expected: PASS.

Run the existing lifecycle to confirm the demo sellers still complete the sample brief:

Run: `uv run pytest tests/integration/test_verifund_lifecycle.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/backfill.py apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_tenancy_backfill.py
git commit -m "feat(tenancy): backfill legacy sellers and buyers"
```

---

## Milestone M2 — identity, tenant repository, platform admin

### Task 12: Clerk session verification and `Identity`

**Files:**
- Modify: `pyproject.toml`, `.../settings.py`, `.../app.py`
- Create: `.../tenancy/identity.py`, `.../tenancy/permissions.py`
- Test: `tests/unit/test_tenancy_identity.py`

**Interfaces:**
- Produces: `Identity(user_id, clerk_user_id, tenant_id, clerk_org_id, role, permissions, is_platform_admin, organization_status)`.
- Produces: `require_identity(request) -> Identity`; `app.state.clerk_authenticator` is injectable.
- Produces: `SYSTEM_IDENTITY` for the ops-token path.
- Produces: `ROLE_PERMISSIONS: dict[str, frozenset[str]]`, `ACTION_PERMISSIONS: dict[tuple[str, str], str]`.

- [ ] **Step 1: Write the failing test**

```python
async def test_require_identity_rejects_missing_token(client):
    response = await client.get("/v1/me")
    assert response.status_code == 401


async def test_require_identity_expands_role_from_database(client, seeded_identity):
    app = client._transport.app
    app.state.clerk_authenticator = lambda request: {
        "sub": "user_1", "org_id": "org_1", "org_role": "org:admin",
    }
    response = await client.get("/v1/me", headers={"authorization": "Bearer x"})
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == seeded_identity["tenant_id"]
    assert "org:transactions:read" in body["permissions"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tenancy_identity.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Implement**

Add `"clerk-backend-api>=4,<5"` to `pyproject.toml`. If the installed version exposes verification under `clerk_backend_api.security`, import from there instead; keep the import in one module so the rest of the code does not care.

Add to `Settings`:

```python
clerk_secret_key: str = Field(default="", validation_alias="CLERK_SECRET_KEY")
clerk_jwt_key: str = Field(default="", validation_alias="CLERK_JWT_KEY")
```

```python
# tenancy/identity.py
from clerk_backend_api import AuthenticateRequestOptions, authenticate_request

@dataclass(frozen=True)
class Identity:
    user_id: str
    clerk_user_id: str
    tenant_id: str
    clerk_org_id: str | None
    role: str
    permissions: frozenset[str]
    is_platform_admin: bool
    organization_status: str

def _default_authenticator(request: Request, settings: Settings) -> dict:
    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            secret_key=settings.clerk_secret_key,
            jwt_key=settings.clerk_jwt_key,
            authorized_parties=[settings.console_base_url],
            accepts_token=["session_token"],
        ),
    )
    if not state.is_signed_in:
        raise VerifundError("unauthorized", "sign-in required", status_code=401)
    return state.payload

async def require_identity(request: Request) -> Identity:
    authenticator = getattr(request.app.state, "clerk_authenticator", None)
    payload = authenticator(request) if authenticator else _default_authenticator(
        request, request.app.state.settings
    )
    return await resolve_identity(request.app.state.tenancy, payload, request.app.state.settings)

SYSTEM_IDENTITY = Identity(
    user_id="system", clerk_user_id="system", tenant_id="",
    clerk_org_id=None, role="system", permissions=frozenset({"*"}),
    is_platform_admin=True, organization_status="active",
)
```

Task 12 also implements the database-only path of `resolve_identity`. Task 13 adds the lazy Clerk lookups; the signature does not change.

```python
async def resolve_identity(store, payload: dict, settings: Settings,
                           directory=None) -> Identity:
    clerk_user_id = payload["sub"]
    user = await store.get_user_by_clerk_id(clerk_user_id)
    if user is None:
        email = payload.get("email") or f"{clerk_user_id}@clerk.local"
        user = await store.upsert_user(clerk_user_id, email, payload.get("name"))

    clerk_org_id = payload.get("org_id")
    if clerk_org_id:
        org = await store.get_organization_by_clerk_id(clerk_org_id)
        membership = await store.get_membership(org["id"], user["id"]) if org else None
        if org is None or membership is None:
            raise VerifundError("forbidden", "organization membership required", status_code=403)
        role = membership.get("role") or payload.get("org_role") or "org:member"
    else:
        org = await store.ensure_personal_organization(user["id"])
        role = "org:buyer"

    if org["status"] != "active":
        raise VerifundError("forbidden", "organization is not active", status_code=403)

    return _identity(user, org, role, settings, await store.is_platform_admin(user["id"]))


def _identity(user: dict, org: dict, role: str, settings: Settings,
              is_platform_admin: bool) -> Identity:
    return Identity(
        user_id=user["id"], clerk_user_id=user["clerk_user_id"],
        tenant_id=org["id"], clerk_org_id=org.get("clerk_org_id"), role=role,
        permissions=ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["org:member"]),
        is_platform_admin=is_platform_admin, organization_status=org["status"],
    )
```

`permissions.py` maps roles exactly as spec §8.1–8.2. `org:admin` gets every permission; personal organizations use `org:buyer`; unknown roles get the `org:member` set.

Add `/v1/me` in `tenancy/routes.py` returning the identity fields.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tenancy_identity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py apps/verifund_control_plane/verifund_control_plane/tenancy/permissions.py apps/verifund_control_plane/verifund_control_plane/tenancy/routes.py apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_tenancy_identity.py
git commit -m "feat(tenancy): verify Clerk sessions and expand permissions"
```

### Task 13: Identity resolution and lazy Clerk sync

**Files:**
- Create: `.../tenancy/clerk.py`
- Modify: `.../tenancy/identity.py`, `.../app.py`
- Test: `tests/unit/test_tenancy_lazy_sync.py`

**Interfaces:**
- Produces: `ClerkDirectory` protocol with `user`, `organization`, `membership` async methods.
- Produces: `resolve_identity(store, payload, settings, directory=None) -> Identity`; creates the personal organization lazily when `org_id` is absent.
- Produces: `app.state.clerk_directory` (fake in tests).

- [ ] **Step 1: Write the failing test**

```python
async def test_missing_organization_is_fetched_lazily(store, fake_directory):
    identity = await resolve_identity(store, {
        "sub": "user_1", "org_id": "org_new", "org_role": "org:admin",
    }, settings, directory=fake_directory)
    assert identity.tenant_id
    assert await store.get_organization_by_clerk_id("org_new") is not None


async def test_no_org_claim_resolves_personal_tenant(store, fake_directory):
    identity = await resolve_identity(store, {"sub": "user_1"}, settings, directory=fake_directory)
    org = await store.get_organization(identity.tenant_id)
    assert org["kind"] == "personal"
    assert org["owner_user_id"] == identity.user_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tenancy_lazy_sync.py -q`
Expected: FAIL — `resolve_identity` missing.

- [ ] **Step 3: Implement**

Replace the Task 12 `resolve_identity` body with this version; the `_identity` helper stays in `identity.py`.

```python
import asyncio
from clerk_backend_api import Clerk

class ClerkDirectory(Protocol):
    async def user(self, clerk_user_id: str) -> dict | None: ...
    async def organization(self, clerk_org_id: str) -> dict | None: ...
    async def membership(self, clerk_org_id: str, clerk_user_id: str) -> dict | None: ...

class ClerkBackendDirectory:
    def __init__(self, secret_key: str) -> None:
        self.secret_key = secret_key
        self._sdk = Clerk(bearer_auth=secret_key)

    async def user(self, clerk_user_id: str) -> dict | None:
        user = await asyncio.to_thread(self._sdk.users.get, user_id=clerk_user_id)
        if user is None:
            return None
        email = user.email_addresses[0].email_address if user.email_addresses else None
        name = " ".join(filter(None, [user.first_name, user.last_name])) or None
        return {"id": user.id, "email": email, "name": name}

    async def organization(self, clerk_org_id: str) -> dict | None:
        org = await asyncio.to_thread(
            self._sdk.organizations.get, organization_id=clerk_org_id
        )
        if org is None:
            return None
        return {"id": org.id, "name": org.name, "slug": getattr(org, "slug", None)}

    async def membership(self, clerk_org_id: str, clerk_user_id: str) -> dict | None:
        memberships = await asyncio.to_thread(
            self._sdk.organizations.list_memberships,
            organization_id=clerk_org_id,
            user_id=clerk_user_id,
        )
        if not memberships:
            return None
        membership = memberships[0]
        return {
            "organization": {"id": clerk_org_id},
            "public_user_data": {"user_id": clerk_user_id},
            "role": membership.role,
        }

async def resolve_identity(store, payload, settings, directory=None) -> Identity:
    directory = directory or settings.clerk_directory
    user = await store.get_user_by_clerk_id(payload["sub"])
    if user is None:
        remote = await directory.user(payload["sub"])
        if remote is None:
            raise VerifundError("unauthorized", "unknown user", status_code=401)
        user = await store.upsert_user(remote["id"], remote.get("email"), remote.get("name"))

    clerk_org_id = payload.get("org_id")
    if not clerk_org_id:
        org = await store.ensure_personal_organization(user["id"])
        return _identity(user, org, "org:buyer", settings, await store.is_platform_admin(user["id"]))

    org = await store.get_organization_by_clerk_id(clerk_org_id)
    if org is None:
        remote_org = await directory.organization(clerk_org_id)
        if remote_org is None:
            raise VerifundError("forbidden", "unknown organization", status_code=403)
        org = await store.upsert_organization(remote_org["id"], remote_org["name"], remote_org.get("slug"))
    membership = await store.get_membership(org["id"], user["id"])
    if membership is None or membership["status"] != "active":
        remote = await directory.membership(clerk_org_id, payload["sub"])
        if remote is None:
            raise VerifundError("forbidden", "not a member", status_code=403)
        membership = await store.upsert_membership_from_clerk(remote)
    if org["status"] != "active":
        raise VerifundError("forbidden", "organization is not active", status_code=403)
    return _identity(user, org, membership["role"], settings, await store.is_platform_admin(user["id"]))
```

`settings.clerk_directory` defaults to `ClerkBackendDirectory(settings.clerk_secret_key)`, implemented with `clerk_backend_api` users/organizations/memberships calls behind the same protocol.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tenancy_lazy_sync.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/clerk.py apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_tenancy_lazy_sync.py
git commit -m "feat(tenancy): lazy-sync organizations and memberships"
```

### Task 14: `TenantScope` and tenant-scoped transaction reads

**Files:**
- Create: `.../tenancy/tenant_repository.py`
- Test: `tests/unit/test_tenant_repository.py`

**Interfaces:**
- Produces: `TenantScope(organization_id, user_id, permissions, is_platform_admin=False)`.
- Produces: `TenantRepository(repo).list_transactions(scope, state=None, limit=50)`, `.get_transaction(scope, transaction_id)`.
- Behavior: a non-participant raises `VerifundError("not_found", ..., 404)`; `is_platform_admin` alone does not grant access without `include_all_tenants=True`.

- [ ] **Step 1: Write the failing test**

```python
async def test_cross_tenant_transaction_is_404(repo, seeded_transactions):
    tenant_repo = TenantRepository(repo)
    scope = TenantScope(organization_id="org_b", user_id="user_b", permissions=frozenset())
    with pytest.raises(VerifundError) as exc:
        await tenant_repo.get_transaction(scope, seeded_transactions["org_a_txn"])
    assert exc.value.status_code == 404


async def test_participant_can_read(repo, seeded_transactions):
    tenant_repo = TenantRepository(repo)
    scope = TenantScope(organization_id="org_a", user_id="user_a", permissions=frozenset())
    txn = await tenant_repo.get_transaction(scope, seeded_transactions["org_a_txn"])
    assert txn.transaction_id == seeded_transactions["org_a_txn"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tenant_repository.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
@dataclass(frozen=True)
class TenantScope:
    organization_id: str
    user_id: str
    permissions: frozenset[str]
    is_platform_admin: bool = False

class TenantRepository:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def _predicate(self, scope: TenantScope, include_all: bool = False):
        t = self.repo.transactions
        if include_all and scope.is_platform_admin:
            return true()
        return or_(
            t.c.buyer_organization_id == scope.organization_id,
            t.c.seller_organization_id == scope.organization_id,
        )

    async def get_transaction(self, scope, transaction_id):
        async with self.repo.transaction() as conn:
            row = (await conn.execute(
                select(self.repo.transactions).where(
                    self.repo.transactions.c.transaction_id == transaction_id,
                    self._predicate(scope),
                )
            )).first()
        if row is None:
            raise VerifundError("not_found", "transaction not found", status_code=404)
        return self.repo._record(row)
```

`list_transactions` applies the same predicate, optional `state`, and `limit`. Platform-admin access requires an explicit `include_all_tenants=True` argument, which the caller must pass and audit.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tenant_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/tenant_repository.py tests/unit/test_tenant_repository.py
git commit -m "feat(tenancy): scope transaction reads by tenant"
```

### Task 15: Platform-admin identity and verification endpoints

**Files:**
- Create: `.../onboarding/routes.py`
- Modify: `.../tenancy/routes.py`, `.../api/ops.py`, `.../app.py`
- Test: `tests/unit/test_platform_admin.py`

**Interfaces:**
- Produces: `require_platform_admin(request) -> Identity`, accepting either a valid platform-admin Clerk identity or the ops token (system actor).
- Produces: `POST /ops/sellers/{seller_id}/verification` with `{decision, note}`; writes an audit row with `scope='organization'`.
- Also creates `.../onboarding/routes.py` and wires the Task 10 service: `POST /v1/seller/onboarding` (201 first time, 200 when it already exists), `GET /v1/seller/onboarding`, `POST /v1/seller/verification/submit`.
- Routes use `require_identity` and reject `kind != 'business'` with `403` before calling the service.

- [ ] **Step 1: Write the failing test**

```python
async def test_member_cannot_decide_verification(client, member_headers):
    response = await client.post("/ops/sellers/acme/verification",
                                 json={"decision": "verified", "note": "ok"},
                                 headers=member_headers)
    assert response.status_code == 403


async def test_platform_admin_can_verify_and_is_audited(client, admin_headers, pending_seller):
    response = await client.post("/ops/sellers/acme/verification",
                                 json={"decision": "verified", "note": "ok"},
                                 headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["verification_status"] == "verified"
    audit = await client._transport.app.state.tenancy.list_audit(organization_id="org_acme")
    assert audit[-1]["action"] == "seller.verification.approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_platform_admin.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Implement**

```python
async def require_platform_admin(request: Request) -> Identity:
    provided = request.headers.get("authorization", "")
    if provided.startswith("Bearer ") and secrets.compare_digest(
        provided.removeprefix("Bearer "), request.app.state.settings.ops_token
    ):
        return SYSTEM_IDENTITY
    identity = await require_identity(request)
    if not identity.is_platform_admin:
        raise VerifundError("forbidden", "platform admin required", status_code=403)
    return identity
```

The endpoint validates `decision in {"verified", "rejected", "suspended"}` and calls `store.set_verification_status` with the reviewer's `user_id`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_platform_admin.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/routes.py apps/verifund_control_plane/verifund_control_plane/onboarding/routes.py apps/verifund_control_plane/verifund_control_plane/api/ops.py apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_platform_admin.py
git commit -m "feat(ops): platform-admin verification decisions"
```

---

## Milestone M3 — tenant columns, participant gate, and isolation

### Task 16: Tenant columns and backfill on core records

**Files:**
- Modify: `.../repository.py`, `.../app.py`
- Test: `tests/unit/test_tenant_columns.py`

**Interfaces:**
- Produces: `transactions.buyer_organization_id`, `transactions.seller_organization_id`, `evidence.organization_id`, `evidence.storage_key`, `agreements.buyer_organization_id`, `agreements.seller_organization_id`, `checkout_links.organization_id`, `buyer_tokens.organization_id`, `seller_tokens.organization_id`.

- [ ] **Step 1: Write the failing test**

```python
from sqlalchemy import select

from tests.support.award_flow import award


async def test_new_award_writes_both_organization_columns(client):
    await award(client)
    repo = client._transport.app.state.repo
    async with repo.transaction() as conn:
        row = (await conn.execute(select(repo.transactions))).first()
    assert row.buyer_organization_id
    assert row.seller_organization_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tenant_columns.py -q`
Expected: FAIL — missing columns.

- [ ] **Step 3: Implement**

Add nullable `String` columns to each table in `_define_tables`. In `create_award`, resolve both tenant organizations through `TenancyRepository` (`ensure_seed_buyer_organization` for the buyer, `get_seller_profile_by_organization`/`ensure_seed_organization` for the seller) and set both columns on insert. Extend the `create_schema` `PRAGMA table_info` pattern:

```python
async def _ensure_column(conn, table: str, name: str, ddl_type: str) -> None:
    columns = {row[1] for row in await conn.exec_driver_sql(f"PRAGMA table_info({table})")}
    if name not in columns:
        await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")
```

Call for every new column. In `service.award`, resolve both organizations through `app.state.tenancy` and write them in the insert. Keep `buyer_id`/`seller_id` unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tenant_columns.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py apps/verifund_control_plane/verifund_control_plane/service.py tests/unit/test_tenant_columns.py
git commit -m "feat(tenancy): add organization columns to core records"
```

### Task 17: `require_transaction` and the action permission map

**Files:**
- Create: `.../tenancy/transaction_access.py`
- Modify: `.../api/seller.py`, `.../api/agreements` routes
- Test: `tests/unit/test_transaction_access.py`

**Interfaces:**
- Produces: `require_transaction(identity, transaction_id, action, repo) -> tuple[TransactionRecord, Literal["buyer","seller"]]`.
- Produces: `ACTION_PERMISSIONS` keys such as `("seller", "upload_evidence") -> "org:evidence:write"`, `("buyer", "approve_agreement") -> "org:transactions:approve"`.

- [ ] **Step 1: Write the failing test**

```python
async def test_non_participant_gets_404(repo, identity_b, txn_a):
    with pytest.raises(VerifundError) as exc:
        await require_transaction(identity_b, txn_a.transaction_id, "read", repo)
    assert exc.value.status_code == 404


async def test_sales_role_cannot_release(repo, identity_sales, txn_a):
    with pytest.raises(VerifundError) as exc:
        await require_transaction(identity_sales, txn_a.transaction_id, "release_funds", repo)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_transaction_access.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
async def require_transaction(identity, transaction_id, action, repo):
    txn = await repo.get_transaction(transaction_id)
    if identity.tenant_id not in (
        txn.buyer_organization_id, txn.seller_organization_id
    ):
        raise VerifundError("not_found", "transaction not found", status_code=404)
    side = "buyer" if identity.tenant_id == txn.buyer_organization_id else "seller"
    permission = ACTION_PERMISSIONS.get((side, action))
    if permission is None:
        raise VerifundError("forbidden", "action not permitted", status_code=403)
    if permission not in identity.permissions:
        raise VerifundError("forbidden", "permission denied", status_code=403)
    return txn, side
```

Replace the seller routes' `claims.seller_id == transaction.seller_id` checks with `require_transaction` where the request is Clerk-authenticated. Keep the legacy token path behind `settings.tenancy_enabled = false`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_transaction_access.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/transaction_access.py apps/verifund_control_plane/verifund_control_plane/api/seller.py tests/unit/test_transaction_access.py
git commit -m "feat(tenancy): participant gate with 404 for outsiders"
```

### Task 18: Counterparty visibility matrix

**Files:**
- Create: `.../tenancy/visibility.py`
- Modify: `.../api/seller.py` (payout and evidence projections), `.../api/ops.py` (evidence download)
- Test: `tests/unit/test_visibility.py`

**Interfaces:**
- Produces: `assert_resource_visible(side: str, resource: str) -> None` raising `403` for forbidden resources.
- Produces: `filter_payout_projection(side, payout)` returning `None` for the buyer side.

- [ ] **Step 1: Write the failing test**

```python
def test_buyer_cannot_read_seller_payout_account():
    with pytest.raises(VerifundError) as exc:
        assert_resource_visible("buyer", "payout_account")
    assert exc.value.status_code == 403


def test_buyer_can_read_agreement():
    assert_resource_visible("buyer", "agreement")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_visibility.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
VISIBILITY = {
    "buyer": {"agreement", "offer", "evidence", "transaction", "dispute"},
    "seller": {"agreement", "offer", "evidence", "transaction", "dispute",
               "catalog", "inventory", "payout_account", "pricing_policy"},
}

def assert_resource_visible(side: str, resource: str) -> None:
    if resource not in VISIBILITY.get(side, set()):
        raise VerifundError("forbidden", "resource not visible", status_code=403)
```

Call it in the seller/buyer projection builders and before returning a payout account. The transaction participant check must run first.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_visibility.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/visibility.py apps/verifund_control_plane/verifund_control_plane/api/seller.py tests/unit/test_visibility.py
git commit -m "feat(tenancy): enforce counterparty visibility"
```

### Task 19: Seller gate in award, tokens, and invitations

**Files:**
- Modify: `.../service.py`
- Test: `tests/unit/test_seller_gate.py`

**Interfaces:**
- Produces: `seller_status(seller_id) -> str` on `VerifundService`, reading `seller_profiles`.
- Behavior: `award` rejects a non-verified seller with `403 seller_not_verified` before writing; `reissue_seller_token` and `issue_invitation` do the same.

- [ ] **Step 1: Write the failing test**

```python
async def test_unverified_seller_cannot_be_awarded(client, unverified_seller):
    response = await client.post("/awards", json=award_payload(seller_id="new-seller"),
                                 headers={**OPS, "idempotency-key": "a1"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "seller_not_verified"
    assert await transaction_count(client) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_gate.py -q`
Expected: FAIL — award returns 201.

- [ ] **Step 3: Implement**

```python
async def seller_status(self, seller_id: str) -> str | None:
    profile = await self.tenancy.get_seller_profile(seller_id)
    return profile["verification_status"] if profile else None

# in award(), before any insert:
status = await self.seller_status(request.seller_id)
if status != "verified":
    raise VerifundError("seller_not_verified",
                        "seller is not verified for new transactions", status_code=403)
```

Add the same check at the top of `reissue_seller_token` and `issue_invitation`. Gate on `settings.tenancy_enabled` so the legacy test suite can run with the flag off.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_seller_gate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py tests/unit/test_seller_gate.py
git commit -m "feat(seller): gate awards, tokens, and invitations on verification"
```

### Task 20: Isolation suite

**Files:**
- Test: `tests/unit/test_tenant_isolation.py`

**Interfaces:**
- Consumes: everything in M0–M3.
- Produces: spec §17 cases 1–7, 9, 10, and 14 as executable tests. Cases 8 and 11 belong to M6; 12–13 to M7; 15–30 to later milestones.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_cannot_read_b_transaction(client, two_tenants):
    response = await client.get(f"/transactions/{two_tenants.b_txn}",
                                headers=two_tenants.a_headers)
    assert response.status_code == 404


async def test_both_participants_read_shared_transaction(client, two_tenants):
    for headers in (two_tenants.a_headers, two_tenants.b_headers):
        response = await client.get(f"/transactions/{two_tenants.shared_txn}",
                                    headers=headers)
        assert response.status_code == 200


async def test_sales_role_cannot_read_payouts(client, two_tenants):
    response = await client.get("/seller/payouts", headers=two_tenants.sales_headers)
    assert response.status_code == 403


async def test_request_without_token_is_401(client):
    assert (await client.get("/transactions")).status_code == 401
```

The same file also contains the remaining M3 cases:

| Test | Assertion |
|---|---|
| `test_a_cannot_read_b_evidence` | `GET /evidence/{id}` with A's headers returns `404` |
| `test_a_cannot_read_b_agreement` | `GET /agreements/{id}` with A's headers returns `404` |
| `test_fulfillment_role_uploads_evidence` | `POST` evidence with the fulfillment role returns `200` |
| `test_finance_role_releases_funds` | release action with the finance role returns `200` |
| `test_unverified_seller_is_not_awardable` | award returns `403` with code `seller_not_verified` |
| `test_unverified_seller_is_absent_from_discovery` | discovery response omits the seller |
| `test_no_token_is_401` | every protected route in the file returns `401` without a token |

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_tenant_isolation.py -q`
Expected: FAIL on the first assertions.

- [ ] **Step 3: Implement**

No new production code. Fix the route wiring uncovered by the tests: ensure `/transactions` and `/seller/*` use `require_identity`/`require_transaction`, and ensure the seller routes no longer fall back to `X-Actor-Id`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tenant_isolation.py tests/unit/test_transaction_access.py tests/unit/test_seller_gate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane tests/unit/test_tenant_isolation.py
git commit -m "test(tenancy): cross-tenant isolation suite"
```

---

## Milestone M4 — seller onboarding UI and workspace

### Task 21: Seller access from Clerk, not the cookie

**Files:**
- Create: `apps/console/lib/seller-access.ts`
- Modify: `apps/console/app/seller/layout.tsx`
- Test: `apps/console/tests/lib/seller-access.test.ts`

**Interfaces:**
- Produces: `sellerAccess(orgId: string | null): Promise<"onboarding" | "workspace" | "read_only" | "none">`.
- Consumes: `controlPlaneForUser("/v1/me")` plus `GET /v1/seller/onboarding`.

- [ ] **Step 1: Write the failing test**

```ts
vi.mock("@/lib/control-plane", () => ({
  controlPlaneForUser: vi.fn(async () => new Response(JSON.stringify({
    profile: null,
  }), { status: 200 })),
}));

it("sends an organization with no seller profile to onboarding", async () => {
  await expect(sellerAccess("org_1")).resolves.toBe("onboarding");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter marketmesh-console exec vitest run tests/lib/seller-access.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```ts
export async function sellerAccess(orgId: string | null) {
  if (!orgId) return "none";
  const response = await controlPlaneForUser("/v1/seller/onboarding");
  if (response.status === 404) return "onboarding";
  if (!response.ok) return "none";
  const body = await response.json();
  if (!body.profile) return "onboarding";
  if (body.profile.verification_status === "suspended") return "read_only";
  return "workspace";
}
```

In `app/seller/layout.tsx`:

```tsx
const { orgId } = await consoleSession();
const access = await sellerAccess(orgId);
if (access === "none") redirect("/");
if (access === "onboarding") redirect("/seller/onboarding");
```

Remove `readSellerSession()` from the staff layout. Keep the invitation cookie only for the legacy `/fulfillment/access/[token]` route until Task 23.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter marketmesh-console exec vitest run tests/lib/seller-access.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/lib/seller-access.ts apps/console/app/seller/layout.tsx apps/console/tests/lib/seller-access.test.ts
git commit -m "feat(seller): resolve workspace access from Clerk"
```

### Task 22: Onboarding entry routing and wizard shell

**Files:**
- Create: `apps/console/lib/onboarding.ts`, `apps/console/app/seller/onboarding/page.tsx`, `.../onboarding/[step]/page.tsx`
- Test: `apps/console/tests/lib/onboarding.test.ts`

**Interfaces:**
- Produces: `sellerEntryPath(profile, onboarding): string`.
- Produces: seven step routes: `profile`, `verification`, `integrations`, `agent_setup`, `policies`, `testing`, `activation`.

- [ ] **Step 1: Write the failing test**

```ts
import { sellerEntryPath } from "@/lib/onboarding";

it("routes an unverified profile to verification", () => {
  expect(sellerEntryPath(
    { verification_status: "unverified" },
    { current_step: "verification", status: "in_progress" },
  )).toBe("/seller/onboarding/verification");
});

it("routes a verified profile to the workspace", () => {
  expect(sellerEntryPath({ verification_status: "verified" }, null)).toBe("/seller/dashboard");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter marketmesh-console exec vitest run tests/lib/onboarding.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```ts
const STEPS = [
  "profile", "verification", "integrations",
  "agent_setup", "policies", "testing", "activation",
] as const;

export function sellerEntryPath(profile: { verification_status: string } | null,
                                onboarding: { current_step: string } | null) {
  if (!profile) return "/seller/onboarding";
  if (profile.verification_status === "verified") return "/seller/dashboard";
  const step = onboarding?.current_step ?? "profile";
  return STEPS.includes(step as (typeof STEPS)[number])
    ? `/seller/onboarding/${step}`
    : "/seller/onboarding/profile";
}
```

The step page renders a server-side guard and a client form shell. Each save calls `controlPlaneForUser("/v1/seller/onboarding/steps/{step}", { method: "PUT" })`. Progress is read from the server; no `localStorage`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter marketmesh-console exec vitest run tests/lib/onboarding.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/lib/onboarding.ts apps/console/app/seller/onboarding apps/console/tests/lib/onboarding.test.ts
git commit -m "feat(seller): add resumable onboarding shell"
```

### Task 23: Invitation link becomes a Clerk onboarding redirect

**Files:**
- Create: `apps/console/lib/invitation.ts`
- Modify: `apps/console/app/fulfillment/access/[token]/actions.ts`, `.../page.tsx`
- Test: `apps/console/tests/app/invitation.test.ts`

**Interfaces:**
- Produces: `invitationRedirect(token: string): string` returning `/sign-in?redirect_url=/seller/onboarding?invitation=<token>`.
- Behavior: the token is never exchanged for a seller session cookie; after sign-in, organization membership is required.

- [ ] **Step 1: Write the failing test**

```ts
import { invitationRedirect } from "@/lib/invitation";

it("preserves the token through sign-in", () => {
  expect(invitationRedirect("tok_1")).toBe(
    "/sign-in?redirect_url=%2Fseller%2Fonboarding%3Finvitation%3Dtok_1",
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/invitation.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```ts
export function invitationRedirect(token: string) {
  const target = `/seller/onboarding?invitation=${encodeURIComponent(token)}`;
  return `/sign-in?redirect_url=${encodeURIComponent(target)}`;
}
```

Replace the action body with `redirect(invitationRedirect(token))`. Do not call `exchangeInvitation` or `saveSellerToken` on this route.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/invitation.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/lib/invitation.ts apps/console/app/fulfillment/access apps/console/tests/app/invitation.test.ts
git commit -m "feat(seller): route invitations through Clerk onboarding"
```

### Task 24: Remove the staff seller cookie store

**Files:**
- Modify: `apps/console/lib/seller-api.ts`, `apps/console/app/seller/**`
- Test: `apps/console/tests/app/seller-cookie-removal.test.ts`

**Interfaces:**
- Behavior: no `app/seller/**` file imports `readSellerSession`, `SELLER_COOKIE`, or `saveSellerToken`.

- [ ] **Step 1: Write the failing test**

```ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

it("does not use the seller cookie for staff access", () => {
  const root = path.resolve(__dirname, "../../app/seller");
  const files = walk(root);
  const offenders = files.filter((f) =>
    /readSellerSession|SELLER_COOKIE|saveSellerToken/.test(readFileSync(f, "utf8")),
  );
  expect(offenders).toEqual([]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/seller-cookie-removal.test.ts`
Expected: FAIL — layout imports `readSellerSession`.

- [ ] **Step 3: Implement**

Delete `readSellerSession`/`readAllSellerSessions` calls from `app/seller/**`. Replace seller fetches with `controlPlaneForUser("/seller/...")`. Remove `app/seller/actions.ts` sign-out (use `<UserButton />`). Keep `seller-api.ts` only for the public invitation exchange if the route still imports it; otherwise delete the module and its tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter marketmesh-console exec vitest run tests/app/seller-cookie-removal.test.ts tests/lib/seller-status.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/lib/seller-api.ts apps/console/app/seller apps/console/tests/app/seller-cookie-removal.test.ts
git commit -m "refactor(seller): remove the parallel cookie session"
```

---

## Milestone M5 — agent lifecycle and registry projection

### Task 25: Agent, credential, and test-run tables

**Files:**
- Modify: `.../tenancy/repository.py`
- Test: `tests/unit/test_agent_store.py`

**Interfaces:**
- Produces: `agents`, `agent_credentials`, `agent_test_runs` tables plus `create_agent`, `get_agent`, `list_agents`, `set_agent_status`, `set_policy_hash`, `set_policy_drift`, `create_test_run`, `latest_passing_test`, `create_credential`, `get_credential_by_hash`, `list_credentials`, `revoke_credential`.
- Produces: `list_audit(*, scope=None, organization_id=None, resource_id=None, actor_type=None)` on `TenancyRepository`.
- Produces: `agent_credentials.token_hash` only; the raw token is never stored.

- [ ] **Step 1: Write the failing test**

```python
async def test_agent_round_trip_and_active_test_run(store):
    agent = await store.create_agent(
        organization_id="org_1", name="Acme Agent", created_by="user_1",
        policy_ref="acme/main", policy_version="1", policy_hash="a" * 64,
    )
    assert agent["status"] == "draft"
    await store.set_agent_status(agent["id"], "testing")
    await store.create_test_run(
        agent["id"], "org_1", policy_hash="a" * 64, card_hash="b" * 64,
        checks=[{"name": "catalog", "passed": True}], passed=True,
    )
    assert await store.latest_passing_test(agent["id"], "a" * 64, "b" * 64) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_store.py -q`
Expected: FAIL — missing tables.

- [ ] **Step 3: Implement**

Add the three tables exactly as spec §7.6. `create_agent` inserts `status='draft'`. `latest_passing_test` selects the newest row where `passed=1` and both hashes match.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_agent_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py tests/unit/test_agent_store.py
git commit -m "feat(agents): add lifecycle and test-run tables"
```

### Task 26: Credential issuance and verification

**Files:**
- Create: `.../agents/__init__.py`, `.../agents/credentials.py`, `.../agents/routes.py`
- Modify: `.../app.py`
- Test: `tests/unit/test_agent_credentials.py`

**Interfaces:**
- Produces: `issue_credential(store, organization_id, agent_id, scopes) -> str` (raw `vf_agent_...`, once).
- Produces: `verify_credential(store, token) -> dict` returning `{organization_id, agent_id, scopes, status}`.
- Produces: `POST /v1/agent-credentials/verify` (service auth) and `POST /v1/agents/{id}/credentials`.

- [ ] **Step 1: Write the failing test**

```python
async def test_raw_credential_is_returned_once_and_verifies(store, agent):
    raw = await issue_credential(store, agent["organization_id"], agent["id"], ["a2a:call"])
    assert raw.startswith("vf_agent_")
    verified = await verify_credential(store, raw)
    assert verified["agent_id"] == agent["id"]
    rows = await store.list_credentials(agent["id"])
    assert all(raw != row["token_hash"] for row in rows)


async def test_non_active_agent_credential_is_rejected(store, agent):
    raw = await issue_credential(store, agent["organization_id"], agent["id"], ["a2a:call"])
    await store.set_agent_status(agent["id"], "suspended")
    with pytest.raises(VerifundError) as exc:
        await verify_credential(store, raw)
    assert exc.value.code == "agent_not_active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_credentials.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

async def issue_credential(store, organization_id, agent_id, scopes) -> str:
    token = "vf_agent_" + secrets.token_urlsafe(32)
    await store.create_credential(organization_id, agent_id, _hash(token), scopes)
    return token

async def verify_credential(store, token) -> dict:
    row = await store.get_credential_by_hash(_hash(token))
    if row is None or row["status"] != "active":
        raise VerifundError("unauthorized", "invalid credential", status_code=401)
    agent = await store.get_agent(row["agent_id"])
    if agent is None or agent["status"] != "active":
        raise VerifundError("agent_not_active", "agent is not active", status_code=403)
    return {"organization_id": row["organization_id"], "agent_id": row["agent_id"],
            "scopes": json.loads(row["scopes"]), "status": "active"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_agent_credentials.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agents apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_agent_credentials.py
git commit -m "feat(agents): issue and verify per-agent credentials"
```

### Task 27: Provisioning, policy confirmation, and drift

**Files:**
- Create: `.../agents/lifecycle.py`
- Test: `tests/unit/test_agent_lifecycle.py`

**Interfaces:**
- Produces: `provision_agent(store, organization_id, name, created_by, policy_ref) -> dict` (idempotent on `Idempotency-Key`).
- Produces: `confirm_policy(store, agent_id, version, hash) -> dict`; sets `policy_drift` when the hash differs.
- Produces: `check_drift(store, agent) -> bool`, `activate_agent(store, agent_id, actor_agent_id=None) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
async def test_policy_confirmation_records_hash(store, draft_agent):
    updated = await confirm_policy(store, draft_agent["id"], "2", "c" * 64)
    assert updated["policy_version"] == "2"
    assert updated["policy_hash"] == "c" * 64


async def test_activation_blocked_on_drift(store, active_agent):
    await store.set_agent_status(active_agent["id"], "testing")
    await store.set_policy_drift(active_agent["id"], True)
    with pytest.raises(VerifundError) as exc:
        await activate_agent(store, active_agent["id"])
    assert exc.value.code == "policy_drift"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_lifecycle.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Allowed transitions exactly as spec §9.4. `provision_agent` requires a seller profile in `pending` or `verified`, creates a draft, and issues a credential. `confirm_policy` updates the version/hash and clears `policy_drift`. `activate_agent` checks seller verification, the latest passing test for both hashes, and at least one active credential; any failure raises `409 policy_drift`, `403 seller_not_verified`, or `409 onboarding_incomplete`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_agent_lifecycle.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agents/lifecycle.py tests/unit/test_agent_lifecycle.py
git commit -m "feat(agents): provisioning and policy drift"
```

### Task 28: Activation test gate

**Files:**
- Modify: `.../agents/lifecycle.py`, `.../agents/routes.py`
- Test: `tests/unit/test_agent_test_gate.py`

**Interfaces:**
- Produces: `POST /v1/agents/{id}/test` returning `{passed, checks}` and recording `agent_test_runs`.
- Behavior: a policy or card hash change invalidates a prior pass.

- [ ] **Step 1: Write the failing test**

```python
async def test_policy_change_after_pass_blocks_activation(store, tested_agent):
    await store.set_policy_hash(tested_agent["id"], "e" * 64)
    with pytest.raises(VerifundError) as exc:
        await activate_agent(store, tested_agent["id"])
    assert exc.value.code == "onboarding_incomplete"


async def test_passing_run_allows_activation(store, tested_agent):
    agent = await activate_agent(store, tested_agent["id"])
    assert agent["status"] == "active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_test_gate.py -q`
Expected: FAIL — no gate on the new hash.

- [ ] **Step 3: Implement**

`run_agent_tests` calls the seller agent's test endpoint through the `RegistryClient`/agent client, records the six checks from the spec (auth, catalog, pricing, A2A, authority, revocation), and writes `passed` only if all pass. `activate_agent` calls `latest_passing_test(agent_id, current_policy_hash, current_card_hash)`; `None` → `409 onboarding_incomplete`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_agent_test_gate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agents/lifecycle.py apps/verifund_control_plane/verifund_control_plane/agents/routes.py tests/unit/test_agent_test_gate.py
git commit -m "feat(agents): bind activation to the current test run"
```

### Task 29: Registry projection and card URL ownership

**Files:**
- Create: `.../agents/registry_sync.py`
- Modify: `apps/registry/registry/store.py`, `apps/registry/registry/api.py`
- Test: `tests/unit/test_registry_projection.py`

**Interfaces:**
- Produces: `publish_agent(client, agent, card)`, `unpublish_agent(client, agent_id)`.
- Registry `agents` gains `organization_id`, `published`; `POST /v1/agents` and `POST /v1/sellers` become service-auth projection syncs.
- Produces: `assert_card_url_owned(seller_id, card_url)` → `400 card_url_not_owned`.

- [ ] **Step 1: Write the failing test**

```python
async def test_registry_hides_unpublished_agents(registry_client):
    await registry_client.post("/v1/agents", json={
        "agent_id": "a1", "name": "A", "card_url": "http://localhost:9200/a1",
        "skills": [], "card_json": {}, "organization_id": "org_1", "published": False,
    })
    listing = await registry_client.get("/v1/agents")
    assert listing.json()["items"] == []


async def test_card_url_must_match_seller_path(registry_client):
    response = await registry_client.post("/v1/sellers", json={
        "seller_id": "acme", "card_url": "http://localhost:9200/other/a2a",
        "categories": ["electronics"], "organization_id": "org_1",
    })
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "card_url_not_owned"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_registry_projection.py -q`
Expected: FAIL — unknown fields / `published` ignored.

- [ ] **Step 3: Implement**

Add the columns to `RegistryStore` tables and the projection fields to the request models. `assert_card_url_owned` accepts `/{seller_id}/a2a` or an exact match against `settings.allowed_card_hosts` plus the seller's registered base URL; otherwise it raises `400`. Discovery queries add `published = true` and `sellers.verified = true`.

`publish_agent` calls the registry admin endpoint after activation; `unpublish_agent` sets `published=false`. A sweep compares `updated_at` and repairs.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_registry_projection.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/registry/registry apps/verifund_control_plane/verifund_control_plane/agents/registry_sync.py tests/unit/test_registry_projection.py
git commit -m "feat(registry): project published agents only"
```

### Task 30: Agent audit and `fulfillment:assist`

**Files:**
- Modify: `.../agents/routes.py`, `.../tenancy/permissions.py`
- Test: `tests/unit/test_agent_audit.py`

**Interfaces:**
- Produces: every agent mutation writes `audit_log` with `actor_type='agent'` and `actor_user_id=None` when the actor is the credential.
- Produces: `fulfillment:assist` in the seller agent's scope set; it is read+draft only.

- [ ] **Step 1: Write the failing test**

```python
async def test_agent_activation_is_audited(store, tested_agent):
    await activate_agent(store, tested_agent["id"], actor_agent_id=tested_agent["id"])
    rows = await store.list_audit(resource_id=tested_agent["id"], actor_type="agent")
    assert rows[-1]["actor_type"] == "agent"
    assert rows[-1]["action"] == "agent.activated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_audit.py -q`
Expected: FAIL — no audit row.

- [ ] **Step 3: Implement**

Add a `record_agent_audit` helper and call it in provision, policy confirmation, test, activation, suspension, and revocation. Add `fulfillment:assist` to the seller agent scope list and document that it must never map to a mutation endpoint.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_agent_audit.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agents apps/verifund_control_plane/verifund_control_plane/tenancy/permissions.py tests/unit/test_agent_audit.py
git commit -m "feat(agents): audit lifecycle actions"
```

---

## Milestone M6 — payments, evidence, and workers

### Task 31: `payment_accounts` and payout resolution

**Files:**
- Modify: `.../tenancy/repository.py`, `.../service.py`, `.../app.py`
- Test: `tests/unit/test_payment_accounts.py`

**Interfaces:**
- Produces: `payment_accounts` table, `upsert_payment_account(...)`, and `resolve_payout_account(store, organization_id) -> dict`.
- Behavior: upsert requires a `verified` seller (`403 seller_not_verified`); resolution reads only the database; a missing/ambiguous active account raises `409 payout_account_unavailable`.

- [ ] **Step 1: Write the failing test**

```python
async def test_payout_uses_active_database_account(store, verified_seller):
    await store.upsert_payment_account(
        organization_id=verified_seller["organization_id"], provider="paypal",
        provider_account_id="pay@acme.test", account_type="payout",
        status="active", credentials_reference="secret:acme",
    )
    account = await resolve_payout_account(store, verified_seller["organization_id"])
    assert account["provider_account_id"] == "pay@acme.test"


async def test_missing_account_is_409(store, verified_seller):
    with pytest.raises(VerifundError) as exc:
        await resolve_payout_account(store, verified_seller["organization_id"])
    assert exc.value.status_code == 409
    assert exc.value.code == "payout_account_unavailable"


async def test_unverified_seller_cannot_add_a_payout_account(store, unverified_seller):
    with pytest.raises(VerifundError) as exc:
        await store.upsert_payment_account(
            organization_id=unverified_seller["organization_id"], provider="paypal",
            provider_account_id="pay@acme.test", account_type="payout",
            status="active", credentials_reference="secret:acme",
        )
    assert exc.value.status_code == 403
    assert exc.value.code == "seller_not_verified"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_payment_accounts.py -q`
Expected: FAIL — table missing.

- [ ] **Step 3: Implement**

Add the table per spec §7.4. In this task, seed it once from `VERIFUND_SELLER_PAYOUT_EMAILS` (the Task 11 backfill runs before the table exists).

Add `tenancy: TenancyRepository | None = None` to `VerifundService.__init__` and pass `app.state.tenancy` in `app.py`. Add `resolve_payout_account_for_seller(store, seller_id) -> dict` for the award precheck, which resolves the seller profile's `organization_id` and then calls `resolve_payout_account`.

Replace both `settings.payout_email_for(...)` call sites in `service.py` (the sandbox award precheck and payout start) with the database helpers. Keep the env map only as a one-time seed source.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_payment_accounts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_payment_accounts.py
git commit -m "feat(payments): resolve payouts from payment_accounts"
```

### Task 32: Payout releases and the reconciler condition

**Files:**
- Modify: `.../tenancy/repository.py`, `.../reconciler.py`, `.../api/ops.py`
- Test: `tests/unit/test_payout_releases.py`

**Interfaces:**
- Produces: `payout_releases` table; `POST /ops/transactions/{id}/payout-release` with `{reason}`.
- Behavior: a suspended seller is paid only when a release row exists for `(transaction_id, organization_id)`.

- [ ] **Step 1: Write the failing test**

```python
async def test_removed_member_cannot_release_funds(client, txn_with_removed_member, removed_member_headers):
    response = await client.post(
        f"/transactions/{txn_with_removed_member}/release",
        headers=removed_member_headers,
    )
    assert response.status_code == 403


async def test_suspended_seller_payout_is_held_without_release(client, suspended_txn):
    await run_reconciler(client)
    state = await payout_state(client, suspended_txn)
    assert state == "held"


async def test_release_allows_the_payout(client, suspended_txn, admin_headers):
    await client.post(f"/ops/transactions/{suspended_txn}/payout-release",
                      json={"reason": "delivered before suspension"},
                      headers=admin_headers)
    await run_reconciler(client)
    assert await payout_state(client, suspended_txn) == "paid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_payout_releases.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Implement**

Add the table. Pass `tenancy` into `Reconciler` from `app.py`; `run_once` re-reads the seller's organization and verification state. Compute:

```python
seller_active = profile["verification_status"] == "verified" and org["status"] == "active"
release = await store.get_payout_release(transaction_id, seller_org_id)
if not seller_active and release is None:
    await self._hold_payout(transaction_id, "payout_hold_seller_suspended")
    continue
```

Every money action, including this release, re-reads `organization_members` for the acting user (decision 10); a missing or non-active row is `403` even when the session token is still valid. The release endpoint requires a platform admin plus `org:payouts:manage`, writes an audit row, and is per transaction.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_payout_releases.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/api/ops.py tests/unit/test_payout_releases.py
git commit -m "feat(payments): hold suspended-seller payouts until release"
```

### Task 33: Tenant-prefixed evidence and verification documents

**Files:**
- Modify: `.../evidence.py`, `.../service.py`, `.../tenancy/repository.py`
- Test: `tests/unit/test_evidence_tenant.py`

**Interfaces:**
- Produces: `EvidenceStore.put(..., organization_id, transaction_id)` writing `tenants/{org}/transactions/{txn}/{sha256}`.
- Produces: legacy reads fall back to `{root}/{sha256}` when `storage_key` is null.

- [ ] **Step 1: Write the failing test**

```python
async def test_new_evidence_uses_the_tenant_prefix(store, evidence_store):
    item = await evidence_store.put(
        organization_id="org_1", transaction_id="vf_1", seller_id="acme",
        kind="invoice", media_type="application/pdf", original_filename="i.pdf",
        data=b"%PDF-1.4", note=None, captured_at=None,
    )
    assert item.storage_key == f"tenants/org_1/transactions/vf_1/{item.sha256}"
    assert (evidence_store.root / item.storage_key).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_evidence_tenant.py -q`
Expected: FAIL — signature mismatch.

- [ ] **Step 3: Implement**

```python
def _key(self, organization_id: str, transaction_id: str, sha256: str) -> str:
    return f"tenants/{organization_id}/transactions/{transaction_id}/{sha256}"

def read(self, sha256: str, storage_key: str | None = None) -> bytes:
    path = self.root / storage_key if storage_key else self.root / sha256
    return path.read_bytes()
```

Add `document_id` verification keys with the `verification/` segment. The service passes the transaction's seller organization on write and the evidence row's `organization_id` on read.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_evidence_tenant.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/evidence.py apps/verifund_control_plane/verifund_control_plane/service.py tests/unit/test_evidence_tenant.py
git commit -m "feat(evidence): tenant-prefixed storage keys"
```

### Task 34: System principal and worker attribution

**Files:**
- Modify: `.../reconciler.py`, `.../tenancy/identity.py`, `.../tenancy/repository.py`
- Test: `tests/unit/test_system_principal.py`

**Interfaces:**
- Reuses the `SYSTEM_IDENTITY` defined in Task 12; no second definition.
- Behavior: every worker audit row has `organization_id` and `actor_type='system'`; no worker impersonates a tenant.

- [ ] **Step 1: Write the failing test**

```python
async def test_reconciler_audit_is_system_scoped(store, reconciler):
    await reconciler.run_once()
    rows = await store.list_audit(scope="system")
    assert rows
    assert all(row["actor_type"] == "system" for row in rows)
    assert all(row["organization_id"] is not None for row in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_system_principal.py -q`
Expected: FAIL — no system rows.

- [ ] **Step 3: Implement**

```python
from verifund_control_plane.tenancy.identity import SYSTEM_IDENTITY
```

Pass `actor_type="system"` to every reconciler audit write, plus the transaction's `organization_id`. Do not use a tenant identity for worker actions.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_system_principal.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py tests/unit/test_system_principal.py
git commit -m "feat(workers): attribute jobs to the system principal"
```

---

## Milestone M7 — runs, checkpoints, and streaming

### Task 35: Tenant columns on runs and the console runs API

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/trace.py`, `.../console_api.py`, `apps/console/app/api/runs/route.ts`, `.../runs/[runId]/route.ts`
- Test: `tests/unit/test_runs_tenancy.py`, `apps/console/tests/app/runs-api.test.ts`

**Interfaces:**
- Produces: `runs.organization_id`, `runs.user_id`; `GET /api/runs?organization_id=...` filters.
- Produces: the console route calls `auth.protect()` and forwards `organization_id` from `consoleSession()` with an internal service header.

- [ ] **Step 1: Write the failing test**

```python
async def test_runs_are_filtered_by_organization(buyer_store):
    await buyer_store.trace.upsert_run("run_a", organization_id="org_a", user_id="u_a")
    await buyer_store.trace.upsert_run("run_b", organization_id="org_b", user_id="u_b")
    assert [r["run_id"] for r in await buyer_store.trace.list_runs("org_a")] == ["run_a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_runs_tenancy.py -q`
Expected: FAIL — missing columns.

- [ ] **Step 3: Implement**

Add `organization_id` and `user_id` to `TraceStore.runs` plus `PRAGMA`-guarded ALTERs. Extend the existing `TraceStore.upsert_run` (it already inserts-or-updates by `run_id`) so both fields are in `insert_values` and in `update_set` when provided. Change `list_runs` to accept `organization_id` and filter on it; update every caller, including `console_api.py`. `console_api.list_runs` takes `organization_id` and rejects a missing header with `400`. The console route:

```ts
await auth.protect();
const { orgId } = await consoleSession();
const response = await fetch(`${buyer}/api/runs?organization_id=${encodeURIComponent(orgId ?? "")}`, {
  headers: { "x-verifund-internal-token": process.env.BUYER_INTERNAL_TOKEN ?? "" },
  cache: "no-store",
});
```

The buyer API accepts the request only when the internal token matches `BUYER_INTERNAL_TOKEN`; otherwise `401`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_runs_tenancy.py -q`
Run: `pnpm --filter marketmesh-console exec vitest run tests/app/runs-api.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/trace.py apps/buyer_agent/buyer_agent/console_api.py apps/console/app/api/runs apps/console/tests/app/runs-api.test.ts tests/unit/test_runs_tenancy.py
git commit -m "feat(runs): scope runs to the organization"
```

### Task 36: Checkpoint thread IDs and memory namespace

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/executor.py`, `apps/buyer_agent/buyer_agent/graph.py`
- Test: `tests/unit/test_checkpoint_scope.py`

**Interfaces:**
- Produces: `thread_id(organization_id, run_id) -> f"{organization_id}:{run_id}"`.
- Behavior: resume asserts the checkpoint metadata's `organization_id` and `agent_id` match the caller.

- [ ] **Step 1: Write the failing test**

```python
def test_thread_id_is_tenant_prefixed():
    assert thread_id("org_1", "run_1") == "org_1:run_1"


async def test_resume_with_wrong_org_is_rejected(executor):
    with pytest.raises(VerifundError):
        await executor.resume("run_1", organization_id="org_b")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_checkpoint_scope.py -q`
Expected: FAIL — module or parameter missing.

- [ ] **Step 3: Implement**

```python
def thread_id(organization_id: str, run_id: str) -> str:
    return f"{organization_id}:{run_id}"
```

Use it in `graph` config and executor resume. Store `organization_id` and `agent_id` in checkpoint metadata. On resume, compare against the authenticated run record; mismatch → `404 not_found`.

Memory namespace: `("tenants", organization_id, "agents", agent_id, "memory")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_checkpoint_scope.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/executor.py apps/buyer_agent/buyer_agent/graph.py tests/unit/test_checkpoint_scope.py
git commit -m "feat(runs): tenant-prefixed checkpoints and memory"
```

### Task 37: SSE and streaming authorization

**Files:**
- Create: `apps/console/app/api/runs/[runId]/stream/route.ts`
- Modify: `apps/buyer_agent/buyer_agent/console_api.py` (stream guard)
- Test: `tests/unit/test_stream_auth.py`, `apps/console/tests/app/stream-route.test.ts`

**Interfaces:**
- Produces: `authorize_run_stream(user, run_id) -> bool`; a run ID is not a capability.
- Behavior: cross-tenant subscription returns `404` before the stream opens.

- [ ] **Step 1: Write the failing test**

```python
async def test_stream_rejects_a_foreign_organization(buyer_client, run_org_a):
    response = await buyer_client.get(
        f"/api/runs/{run_org_a}/stream",
        params={"organization_id": "org_b"},
        headers={"x-verifund-internal-token": "test-internal-token"},
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stream_auth.py -q`
Expected: FAIL — 200 or 404 from an unrelated path.

- [ ] **Step 3: Implement**

Add the route with `auth.protect()`, resolve `organization_id`, and call the buyer API stream endpoint with the internal token and organization. The buyer API checks the run's `organization_id` before streaming and returns `404` on mismatch.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_stream_auth.py -q`
Run: `pnpm --filter marketmesh-console exec vitest run tests/app/stream-route.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/app/api/runs apps/buyer_agent/buyer_agent/console_api.py tests/unit/test_stream_auth.py apps/console/tests/app/stream-route.test.ts
git commit -m "feat(streams): authorize run subscriptions"
```

---

## Milestone M8 — PostgreSQL and RLS (gated; do not ship with M0–M7)

### Task 38: PostgreSQL engine and schema port

**Files:**
- Modify: `pyproject.toml`, `.../db.py`, `.../settings.py`, `.../app.py`
- Create: `scripts/migrate_sqlite_to_postgres.py`
- Test: `tests/unit/test_postgres_schema.py` (skipped unless `VERIFUND_TEST_POSTGRES_URL`)

**Interfaces:**
- Produces: `create_engine(url)` passes through any SQLAlchemy URL; add `asyncpg`.
- Produces: `python scripts/migrate_sqlite_to_postgres.py --source ... --target ...` copying tables in FK order.

- [ ] **Step 1: Write the failing test**

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("VERIFUND_TEST_POSTGRES_URL"), reason="Postgres not configured"
)

async def test_schema_creates_on_postgres():
    engine = create_engine(os.environ["VERIFUND_TEST_POSTGRES_URL"])
    repo = Repository(engine)
    await repo.create_schema()
    assert await repo.table_exists("transactions")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `VERIFUND_TEST_POSTGRES_URL=postgresql+asyncpg://... uv run pytest tests/unit/test_postgres_schema.py -q`
Expected: FAIL — asyncpg driver missing.

- [ ] **Step 3: Implement**

Add `"asyncpg>=0.30,<1"` and `"psycopg[binary]>=3.2,<4"`. Replace `configure_sqlite` calls with a dialect check; keep SQLite for tests. Add `Repository.table_exists(name) -> bool` using `inspect(conn).has_table(name)`. The migration script reads table metadata, copies rows with `INSERT`, and resets sequences. It refuses to run when the target has rows.

- [ ] **Step 4: Run test to verify it passes**

Run: `VERIFUND_TEST_POSTGRES_URL=postgresql+asyncpg://... uv run pytest tests/unit/test_postgres_schema.py -q`
Expected: PASS (or skipped without a database).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock apps/verifund_control_plane/verifund_control_plane/db.py apps/verifund_control_plane/verifund_control_plane/settings.py scripts/migrate_sqlite_to_postgres.py tests/unit/test_postgres_schema.py
git commit -m "feat(db): support PostgreSQL"
```

### Task 39: RLS policies and per-transaction tenant context

**Files:**
- Create: `.../tenancy/rls.sql`
- Modify: `.../tenancy/tenant_repository.py`, `.../db.py`
- Test: `tests/unit/test_postgres_rls.py` (gated)

**Interfaces:**
- Produces: `set_tenant(conn, organization_id)` calling `SELECT set_config('app.tenant_id', :id, true)`.
- Produces: policies for `transactions`, `evidence`, `agreements`, `seller_profiles`, `buyer_profiles`, `payment_accounts`, `agents`.

- [ ] **Step 1: Write the failing test**

```python
pytestmark = pytest.mark.skipif(not os.getenv("VERIFUND_TEST_POSTGRES_URL"), reason="...")

async def test_rls_blocks_cross_tenant_rows(pg_engine, seeded_pg):
    async with pg_engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', 'org_a', true)"))
        rows = (await conn.execute(
            text("SELECT transaction_id FROM transactions WHERE transaction_id = :id"),
            {"id": seeded_pg["org_b_txn"]},
        )).all()
    assert rows == []

    async with pg_engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', 'org_b', true)"))
        rows = (await conn.execute(
            text("SELECT transaction_id FROM transactions WHERE transaction_id = :id"),
            {"id": seeded_pg["org_b_txn"]},
        )).all()
    assert len(rows) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `VERIFUND_TEST_POSTGRES_URL=... uv run pytest tests/unit/test_postgres_rls.py -q`
Expected: FAIL — RLS not enabled.

- [ ] **Step 3: Implement**

`rls.sql` enables and forces RLS, then creates:

```sql
CREATE POLICY tenant_isolation ON transactions
USING (
  organization_id = current_setting('app.tenant_id', true)::text
  OR buyer_organization_id = current_setting('app.tenant_id', true)::text
  OR seller_organization_id = current_setting('app.tenant_id', true)::text
);
```

For tenant-owned tables (`seller_profiles`, `payment_accounts`, `agents`), use `organization_id = current_setting('app.tenant_id', true)`. Use a non-superuser application role without `BYPASSRLS`. `TenantRepository` calls `set_tenant` inside every transaction.

- [ ] **Step 4: Run test to verify it passes**

Run: `VERIFUND_TEST_POSTGRES_URL=... uv run pytest tests/unit/test_postgres_rls.py -q`
Expected: PASS (or skipped).

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/rls.sql apps/verifund_control_plane/verifund_control_plane/tenancy/tenant_repository.py apps/verifund_control_plane/verifund_control_plane/db.py tests/unit/test_postgres_rls.py
git commit -m "feat(db): enable tenant RLS policies"
```

### Task 40: RLS verification suite

**Files:**
- Test: `tests/unit/test_postgres_rls_suite.py` (gated)

**Interfaces:**
- Produces: the policy-level equivalents of spec §17 cases 1–4 and 19 (cross-tenant transaction, evidence, agreement reads, and suspended-organization visibility).

- [ ] **Step 1: Write the failing tests**

```python
async def test_non_participant_selects_zero_rows(pg_engine, seeded_pg):
    async with pg_engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', 'org_b', true)"))
        rows = (await conn.execute(text(
            "SELECT * FROM transactions WHERE transaction_id = :id"
        ), {"id": seeded_pg["org_a_txn"]})).all()
    assert rows == []
```

The same file also contains:

| Test | Assertion |
|---|---|
| `test_non_participant_selects_zero_evidence` | tenant `org_a` selecting `org_b`'s evidence row returns no rows |
| `test_non_participant_selects_zero_agreements` | tenant `org_a` selecting `org_b`'s agreement row returns no rows |
| `test_both_participants_select_the_shared_transaction` | `org_a` and `org_b` each select the shared row once |
| `test_suspended_organization_keeps_history_reads` | a suspended org's tenant context still selects its completed transactions |

- [ ] **Step 2: Run tests to verify they fail**

Run: `VERIFUND_TEST_POSTGRES_URL=... uv run pytest tests/unit/test_postgres_rls_suite.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Fix policies uncovered by the tests. No application code changes: RLS is the boundary. Ensure the test role is not the table owner and does not have `BYPASSRLS`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `VERIFUND_TEST_POSTGRES_URL=... uv run pytest tests/unit/test_postgres_rls_suite.py -q`
Expected: PASS (or skipped).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_postgres_rls_suite.py apps/verifund_control_plane/verifund_control_plane/tenancy/rls.sql
git commit -m "test(db): RLS isolation suite"
```

---

## Execution Handoff

Plan complete. Execute milestones in order; M8 stays gated behind M0–M7 and a real PostgreSQL target.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with `executing-plans`, batching with checkpoints.

If subagent-driven is chosen, use `superpowers:subagent-driven-development`. If inline, use `superpowers:executing-plans`.
