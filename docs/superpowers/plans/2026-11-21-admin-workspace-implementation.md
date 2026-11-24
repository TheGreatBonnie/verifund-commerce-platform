# Admin Workspace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a top-level, Clerk-gated `/admin` workspace that owns Verifund platform transactions keyed to `PAYPAL_PLATFORM_EMAIL`, with a full ops suite, while preserving buyer/seller isolation and additive admin access.

**Architecture:** Mirror the seller workspace pattern (`app/seller/layout.tsx` + `lib/seller-access.ts`) with a top-level `app/admin/**` tree and a `lib/admin-access.ts` gate. Clerk `publicMetadata.role = "admin"` is the source of truth, mirrored into the backend `platform_admins` table by the verified Clerk webhook; the backend stays fail-closed via `require_identity`/`is_platform_admin`. Platform ownership is a server-stamped `platform_account_email` column on transactions, authorized by `authorize_platform_transaction()`, with human admin actors recorded in the audit log. No ops token is ever exposed to the browser.

**Source spec:** `docs/superpowers/specs/2026-11-21-admin-workspace-design.md` (committed as `2975baa`).

## Prerequisites / branch layout

- Backend tasks (M1–T1..T2, M2, M3–backend) are authored on branch **`deploy/render`**.
- Console tasks (M1–T3..T5, M3–console, M4) are authored on branch **`deploy/console`** (current branch, spec commit `2975baa`).
- Use `superpowers:using-git-worktrees` before execution so both branches can be worked without switching the dirty tree. The current `deploy/console` working tree has **unrelated uncommitted chat work** (`apps/console/features/chat/**`, `apps/console/app/globals.css`, related tests) — never stage or reset those files.
- Frontend path prefix: `apps/console`. Backend path prefix: `apps/verifund_control_plane/verifund_control_plane`.
- **Before writing any console code**, follow `apps/console/AGENTS.md`: this is Next.js 16 with breaking API changes. Read the relevant guides under `apps/console/node_modules/next/dist/docs/` for App Router route groups, layouts, dynamic route `params` (async in Next 15+), server actions, and `route.ts` handlers. Heed deprecation notices; do not assume older Next.js APIs. The templates in this plan use Next 16 conventions (`await params`, `export const dynamic = "force-dynamic"`) but must be reconciled against the installed docs before implementation.
- Test commands:
  - Console: `cd apps/console && npm run typecheck && npm run test -- <path>`
  - Backend (from the render worktree): `uv run pytest tests/unit/<file> -q`

---

## Milestone 1 — Clerk role mirrors to backend; console gate and navigation

### Task 1: Backend — platform-admin reconciliation helpers

**Files:** `apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py`

- [ ] **Step 1: Write failing tests** in `tests/unit/test_platform_admin.py` (append):

```python
async def test_reconcile_platform_admin_grants_and_revokes(client):
    store = client._transport.app.state.tenancy
    user = await store.upsert_user("role_user", "r@example.com", "R")
    assert await store.is_platform_admin(user["id"]) is False
    await store.reconcile_platform_admin(user["id"], True, granted_by="clerk-webhook")
    assert await store.is_platform_admin(user["id"]) is True
    await store.reconcile_platform_admin(user["id"], False, granted_by="clerk-webhook")
    assert await store.is_platform_admin(user["id"]) is False
```

- [ ] **Step 2: Run the test to confirm it fails** — `uv run pytest tests/unit/test_platform_admin.py -q`. Expect `AttributeError: 'TenancyRepository' object has no attribute 'reconcile_platform_admin'`.

- [ ] **Step 3: Implement** directly after `add_platform_admin`/`is_platform_admin` (repository.py:484–501):

```python
    async def remove_platform_admin(self, user_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                self.platform_admins.delete().where(
                    self.platform_admins.c.user_id == user_id
                )
            )

    async def reconcile_platform_admin(
        self, user_id: str, is_admin: bool, granted_by: str | None = None
    ) -> None:
        if is_admin:
            await self.add_platform_admin(user_id, granted_by=granted_by)
        else:
            await self.remove_platform_admin(user_id)
```

- [ ] **Step 4: Run the test again** — `uv run pytest tests/unit/test_platform_admin.py -q`. Both new and existing tests pass.

- [ ] **Step 5: Commit** — `git add ...repository.py tests/unit/test_platform_admin.py && git commit -m "feat(tenancy): add platform-admin grant/revoke reconciliation"`

### Task 2: Backend — sync Clerk `publicMetadata.role` in the verified webhook

**Files:** `apps/verifund_control_plane/verifund_control_plane/tenancy/sync.py`, `tests/unit/test_clerk_webhooks.py`

- [ ] **Step 1: Write failing tests** (append to `tests/unit/test_clerk_webhooks.py`). The verifier is injected per test; assert the mirrored state through `app.state.tenancy`:

```python
async def test_clerk_webhook_grants_and_revokes_platform_admin(client):
    app = client._transport.app
    store = app.state.tenancy

    def verifier_for(role):
        return lambda body, headers: {
            "type": "user.updated",
            "data": {
                "id": "user_1",
                "email_addresses": [{"email_address": "a@example.com"}],
                "public_metadata": {"role": role},
            },
        }

    app.state.clerk_verifier = verifier_for("admin")
    await client.post(
        "/v1/webhooks/clerk",
        content=b"{}",
        headers={"svix-id": "role_grant", "content-type": "application/json"},
    )
    user = await store.get_user_by_clerk_id("user_1")
    assert await store.is_platform_admin(user["id"]) is True

    app.state.clerk_verifier = verifier_for("buyer")
    await client.post(
        "/v1/webhooks/clerk",
        content=b"{}",
        headers={"svix-id": "role_revoke", "content-type": "application/json"},
    )
    assert await store.is_platform_admin(user["id"]) is False
```

- [ ] **Step 2: Run to confirm failure** — `uv run pytest tests/unit/test_clerk_webhooks.py -q`. The admin assertion fails because `apply_clerk_event` ignores `public_metadata`.

- [ ] **Step 3: Implement.** Current `sync.py:7–14` is:

```python
    if kind in {"user.created", "user.updated"}:
        await store.upsert_user(
            data["id"],
            (data.get("email_addresses") or [{}])[0].get("email_address"),
            " ".join(filter(None, [data.get("first_name"), data.get("last_name")])) or None,
        )
    elif kind == "user.deleted":
        await store.anonymize_user(data["id"])
```

Replace it with:

```python
    if kind in {"user.created", "user.updated"}:
        user = await store.upsert_user(
            data["id"],
            (data.get("email_addresses") or [{}])[0].get("email_address"),
            " ".join(filter(None, [data.get("first_name"), data.get("last_name")])) or None,
        )
        role = (data.get("public_metadata") or {}).get("role")
        await store.reconcile_platform_admin(
            user["id"], role == "admin", granted_by="clerk-webhook"
        )
    elif kind == "user.deleted":
        user = await store.get_user_by_clerk_id(data["id"])
        if user is not None:
            await store.remove_platform_admin(user["id"])
        await store.anonymize_user(data["id"])
```

Everything else in the file stays identical. This code is only reachable after Svix verification and dedupe (`api/webhooks.py:106–126`), so no unverified request can grant authority.

- [ ] **Step 4: Run the webhook and platform-admin suites** — `uv run pytest tests/unit/test_clerk_webhooks.py tests/unit/test_platform_admin.py -q`. All pass; the original idempotency test still passes.

- [ ] **Step 5: Commit** — `git add ...tenancy/sync.py tests/unit/test_clerk_webhooks.py && git commit -m "feat(tenancy): mirror Clerk admin role into platform_admins"`

### Task 3: Console — role vocabulary, post-auth routing, choose-role guard

**Files:** `apps/console/lib/user-role.ts`, `apps/console/app/post-auth/page.tsx`, `apps/console/app/choose-role/actions.ts`, `tests/lib/user-role.test.ts`, `tests/app/post-auth.test.tsx`, `tests/app/choose-role-actions.test.ts`

- [ ] **Step 1: Write failing tests.** In `tests/app/post-auth.test.tsx` add:

```tsx
  it("redirects admins to /admin", async () => {
    hoisted.currentUser.mockResolvedValue(makeUser({ publicMetadata: { role: "admin" } }));
    await expect(PostAuthPage()).rejects.toThrow("REDIRECT:/admin");
    expect(hoisted.redirect).toHaveBeenCalledWith("/admin");
  });
```

In `tests/app/choose-role-actions.test.ts`, add a `currentUser` mock to the hoisted block and the `@clerk/nextjs/server` mock, reset it in `beforeEach`, then add:

```ts
  it("refuses to demote an admin through the chooser", async () => {
    hoisted.protect.mockResolvedValue({ userId: "user_1" });
    hoisted.authFn.mockResolvedValue({ userId: "user_1" });
    hoisted.currentUser.mockResolvedValue({ publicMetadata: { role: "admin" } });
    await expect(setRole("buyer")).rejects.toThrow("admin role cannot be changed here");
    expect(hoisted.promoteUserRole).not.toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run to confirm failure** — `npm run test -- tests/app/post-auth.test.tsx tests/app/choose-role-actions.test.ts`. The admin case redirects to `/choose-role` (or the demote case succeeds).

- [ ] **Step 3: Extend the role union.** In `lib/user-role.ts:3`:

```ts
export type UserRole = "buyer" | "seller" | "admin";
```

`promoteUserRole()` is unchanged; no user-facing flow calls it with `"admin"`.

- [ ] **Step 4: Update post-auth.** In `app/post-auth/page.tsx:8–10`:

```ts
function isRole(value: unknown): value is UserRole {
  return value === "buyer" || value === "seller" || value === "admin";
}
```

And at `:42`, before the seller branch:

```ts
  if (role === "admin") redirect("/admin");
```

Order must be admin → seller → buyer so an admin never reaches `SellerActivator`.

- [ ] **Step 5: Guard the chooser action.** In `app/choose-role/actions.ts`, import `currentUser`:

```ts
import { auth, currentUser } from "@clerk/nextjs/server";
```

And insert the guard after the `userId` check:

```ts
  const user = await currentUser();
  if ((user?.publicMetadata?.role as string) === "admin") {
    throw new Error("admin role cannot be changed here");
  }
```

- [ ] **Step 6: Keep sign-up buyer/seller-only.** Do not touch `components/layout/console-layout.tsx:50,55`. There is no admin signup option.

- [ ] **Step 7: Run tests and typecheck** — `npm run typecheck && npm run test -- tests/lib/user-role.test.ts tests/app/post-auth.test.tsx tests/app/choose-role-actions.test.ts`. All pass.

- [ ] **Step 8: Commit** — `git add apps/console/lib/user-role.ts apps/console/app/post-auth/page.tsx apps/console/app/choose-role/actions.ts apps/console/tests && git commit -m "feat(console): route Clerk admins to /admin and block chooser demotion"`

### Task 4: Console — `adminAccess()` gate and top-level admin layout

**Files:** new `apps/console/lib/admin-access.ts`, new `apps/console/app/admin/layout.tsx`, new `apps/console/app/admin/actions.ts`, new `tests/lib/admin-access.test.ts`, new `tests/app/admin-layout.test.tsx`

- [ ] **Step 1: Write failing tests.** `tests/lib/admin-access.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  protect: vi.fn(),
  forUser: vi.fn(),
}));
vi.mock("@/lib/console-session", () => ({ consoleSession: hoisted.protect }));
vi.mock("@/lib/control-plane", () => ({ controlPlaneForUser: hoisted.forUser }));

import { adminAccess } from "@/lib/admin-access";

describe("adminAccess", () => {
  beforeEach(() => {
    hoisted.protect.mockReset().mockResolvedValue({ userId: "user_1" });
    hoisted.forUser.mockReset();
  });

  it("returns true only for is_platform_admin", async () => {
    hoisted.forUser.mockResolvedValue(
      new Response(JSON.stringify({ is_platform_admin: true }), { status: 200 }),
    );
    expect(await adminAccess()).toBe(true);
  });

  it.each([
    ["non-admin 200", 200, { is_platform_admin: false }],
    ["403", 403, {}],
    ["malformed json", 200, null],
  ])("fails closed for %s", async (_name, status, body) => {
    hoisted.forUser.mockResolvedValue(
      new Response(body === null ? "not-json" : JSON.stringify(body), { status }),
    );
    expect(await adminAccess()).toBe(false);
  });

  it("fails closed on network error", async () => {
    hoisted.forUser.mockRejectedValue(new Error("offline"));
    expect(await adminAccess()).toBe(false);
  });
});
```

`tests/app/admin-layout.test.tsx` (mirrors the seller-gate test style): mock `@/lib/admin-access` and `next/navigation`'s `redirect` (throw), mock `@clerk/nextjs` `UserButton`, `lucide-react` icons, `@/components/admin/admin-nav`, `@/components/layout/marketplace-link`, and `./actions`; assert that a false gate calls `redirect("/")` and a true gate renders children.

- [ ] **Step 2: Run to confirm failure** — `npm run test -- tests/lib/admin-access.test.ts tests/app/admin-layout.test.tsx`. Modules do not exist yet.

- [ ] **Step 3: Implement the gate** as `lib/admin-access.ts`:

```ts
import { consoleSession } from "@/lib/console-session";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function adminAccess(): Promise<boolean> {
  await consoleSession(); // auth.protect() — fail closed for signed-out users
  try {
    const response = await controlPlaneForUser("/v1/me");
    if (!response.ok) return false;
    const body = (await response.json()) as { is_platform_admin?: unknown };
    return body.is_platform_admin === true;
  } catch {
    return false;
  }
}
```

Use `controlPlaneForUser` only. Never call `controlPlaneAsPlatform` from admin code — that helper (`lib/control-plane.ts:21–35`) stays webhook/machine-only.

- [ ] **Step 4: Implement the sign-out action** as `app/admin/actions.ts`:

```ts
"use server";

import { auth, signOut } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

export async function signOutAction(): Promise<void> {
  await auth.protect(); // literal guard required by tests/app/route-guards.test.ts
  await signOut();
  redirect("/");
}
```

- [ ] **Step 5: Implement the layout** as `app/admin/layout.tsx`:

```tsx
import { redirect } from "next/navigation";
import Link from "next/link";
import { LogOut, ShieldCheck } from "lucide-react";
import { UserButton } from "@clerk/nextjs";
import { AdminNav } from "@/components/admin/admin-nav";
import { MarketplaceLink } from "@/components/layout/marketplace-link";
import { adminAccess } from "@/lib/admin-access";
import { signOutAction } from "./actions";

export const dynamic = "force-dynamic";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!(await adminAccess())) redirect("/");

  return (
    <div className="mm-seller-shell" suppressHydrationWarning>
      <aside className="mm-seller-sidebar">
        <Link href="/admin" className="mm-seller-brand">
          <span className="mm-seller-brand-mark" aria-hidden="true">
            <ShieldCheck size={19} />
          </span>
          <span>
            <strong>verifund</strong>
            <small>Platform admin</small>
          </span>
        </Link>

        <p className="mm-seller-nav-label">Workspace</p>
        <AdminNav />

        <div className="mm-seller-session">
          <span className="mm-kicker">Signed in</span>
          <UserButton />
          <form action={signOutAction}>
            <button type="submit" className="mm-seller-signout">
              <LogOut size={13} aria-hidden="true" />
              Sign out
            </button>
          </form>
        </div>

        <p className="mm-seller-sidebar-note">
          Platform transactions are read from the Verifund control plane for the
          configured PayPal platform account only.
        </p>
      </aside>

      <div className="mm-seller-frame">
        <header className="mm-seller-topbar">
          <div>
            <span className="mm-kicker">Platform operations</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <MarketplaceLink />
          </div>
        </header>
        <main className="mm-seller-main">{children}</main>
      </div>
    </div>
  );
}
```

Reusing `mm-seller-*` classes keeps the admin chrome consistent without new CSS. The `OrganizationSwitcher` is intentionally omitted — admin authority is user-level, not org-scoped.

- [ ] **Step 6: Implement `components/admin/admin-nav.tsx`** (mirror `components/seller/seller-nav.tsx:16–50` exactly, changing the nav array and aria label):

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ClipboardList,
  FileClock,
  LayoutDashboard,
  ListChecks,
  Settings,
  ShieldCheck,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";

const NAV: Array<{ href: string; label: string; icon: LucideIcon }> = [
  { href: "/admin", label: "Overview", icon: LayoutDashboard },
  { href: "/admin/transactions", label: "Platform transactions", icon: ClipboardList },
  { href: "/admin/payouts", label: "Payouts", icon: Wallet },
  { href: "/admin/disputes", label: "Disputes", icon: ListChecks },
  { href: "/admin/verification", label: "Verification", icon: ShieldCheck },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/audit", label: "Audit", icon: FileClock },
  { href: "/admin/settings", label: "Settings", icon: Settings },
];

export function AdminNav() {
  const pathname = usePathname();
  return (
    <nav className="mm-seller-nav" aria-label="Admin workspace">
      <ul>
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href ||
            (href !== "/admin" && pathname.startsWith(`${href}/`));
          return (
            <li key={href}>
              <Link
                href={href}
                className={cn("mm-seller-nav-link", active && "is-active")}
                aria-current={active ? "page" : undefined}
              >
                <Icon size={15} aria-hidden="true" />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
```

- [ ] **Step 7: Run tests and typecheck** — `npm run typecheck && npm run test -- tests/lib/admin-access.test.ts tests/app/admin-layout.test.tsx`.

- [ ] **Step 8: Commit** — `git add apps/console/lib/admin-access.ts apps/console/app/admin apps/console/components/admin apps/console/tests && git commit -m "feat(console): add Clerk-gated admin layout and navigation"`

### Task 5: Console — admin nav link in buyer and seller headers

**Files:** new `apps/console/app/api/me/admin-access/route.ts`, new `apps/console/components/layout/admin-link.tsx`, new `tests/components/layout/admin-link.test.tsx`, edit `components/layout/console-layout.tsx`, edit `app/seller/layout.tsx`, edit `tests/app/console-layout.test.tsx`

- [ ] **Step 1: Write failing test** `tests/components/layout/admin-link.test.tsx`, mirroring `tests/components/layout/seller-link.test.tsx:1–77`: mock `@clerk/nextjs` (`useAuth`), `next/navigation` (`useRouter`), `@tanstack/react-query` (`useQuery` returning `{ data: { admin: adminMock() } }` keyed on `"admin-access"`), and `@/components/ui/button`. Assert: admin `true` → button "Admin" and `pushMock("/admin")`; admin `false` → empty DOM; signed-out → empty DOM.

- [ ] **Step 2: Run to confirm failure** — `npm run test -- tests/components/layout/admin-link.test.tsx`.

- [ ] **Step 3: Add the API probe** as `app/api/me/admin-access/route.ts`:

```ts
import { auth } from "@clerk/nextjs/server";
import { adminAccess } from "@/lib/admin-access";

export const dynamic = "force-dynamic";

export async function GET() {
  await auth.protect();
  const admin = await adminAccess();
  return Response.json({ admin }, { headers: { "Cache-Control": "no-store" } });
}
```

- [ ] **Step 4: Add the client link** as `components/layout/admin-link.tsx`:

```tsx
"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";

export function AdminLink() {
  const router = useRouter();
  const { isSignedIn } = useAuth();

  const adminQuery = useQuery({
    queryKey: ["admin-access"],
    queryFn: () =>
      fetch("/api/me/admin-access", { cache: "no-store" }).then(async (r) => {
        if (!r.ok) throw new Error(`admin-access ${r.status}`);
        return (await r.json()) as { admin: boolean };
      }),
    enabled: isSignedIn === true,
    staleTime: 30_000,
    retry: false,
  });

  if (adminQuery.data?.admin !== true) return null;

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => router.push("/admin")}
      leftIcon={<ShieldCheck size={14} aria-hidden="true" />}
    >
      Admin
    </Button>
  );
}
```

- [ ] **Step 5: Wire into both headers.** In `components/layout/console-layout.tsx`, add `import { AdminLink } from "@/components/layout/admin-link";` and render `<AdminLink />` immediately after `<SellerLink />` (currently line 63). In `app/seller/layout.tsx`, add the same import and render `<AdminLink />` beside `<MarketplaceLink />` (currently line 62).

- [ ] **Step 6: Update the layout test** `tests/app/console-layout.test.tsx`: add `AdminLink` to the mocks so signed-in assertions account for the extra header element; no change to the signed-out sign-up button assertions.

- [ ] **Step 7: Run tests and typecheck** — `npm run typecheck && npm run test -- tests/components/layout/admin-link.test.tsx tests/app/console-layout.test.tsx tests/app/route-guards.test.ts`.

- [ ] **Step 8: Commit** — `git add apps/console/app/api/me/admin-access apps/console/components/layout/admin-link.tsx apps/console/components/layout/console-layout.tsx apps/console/app/seller/layout.tsx apps/console/tests && git commit -m "feat(console): add additive admin link to buyer and seller headers"`

**Milestone 1 checkpoint:** a Clerk admin can sign in, land on `/admin`, and see the admin shell; a non-admin hitting `/admin` is redirected to `/`; both headers show an Admin link only for admins.

---

## Milestone 2 — Platform-owner principal and transaction ownership (`deploy/render`)

### Task 6: Stamp `platform_account_email` on transactions at creation

**Files:** `domain.py`, `repository.py`, `service.py`, `tests/unit/test_platform_owner.py` (new)

- [ ] **Step 1: Write failing tests** in new `tests/unit/test_platform_owner.py`. Use the `client`/`identities` fixture pattern from `test_platform_admin.py`, then assert that a transaction created through the award path carries the configured platform email and that retrieval exposes it. Concretely, seed settings with `paypal_platform_email="platform@example.com"`, call the award endpoint used by existing transaction tests, then:

```python
async def test_transaction_is_stamped_with_platform_email(client):
    txn = await _award_a_transaction(client)  # reuse existing award helper/fixture
    assert txn["platform_account_email"] == "platform@example.com"
```

(If no award helper exists in this test module, import the one from `tests/unit/test_transactions.py` or create the transaction directly through `app.state.service.create_transaction_from_award` as that test does.)

- [ ] **Step 2: Run to confirm failure** — `uv run pytest tests/unit/test_platform_owner.py -q`.

- [ ] **Step 3: Add the field to `TransactionRecord`** in `domain.py:147–180`, after `seller_organization_id`:

```python
    platform_account_email: str | None = None
```

- [ ] **Step 4: Add the column to the core transactions table** in `repository.py:97–130`, after `seller_organization_id`:

```python
            Column("platform_account_email", String, nullable=True, index=True),
```

- [ ] **Step 5: Add an idempotent column migration** in `Repository.create_schema` (`repository.py:473+`), mirroring the `buyer_profiles` migration at `repository.py:218–226`:

```python
            try:
                cols = await existing_columns(conn, "transactions")
                if "platform_account_email" not in cols:
                    await conn.exec_driver_sql(
                        "ALTER TABLE transactions ADD COLUMN platform_account_email TEXT"
                    )
            except Exception:
                pass
```

- [ ] **Step 6: Persist and read the field.** In `repository.py::_record` (`:547`), add:

```python
        platform_account_email=getattr(row, "platform_account_email", None),
```

In `repository.py::insert_transaction` values dict (`:735`), add:

```python
                platform_account_email=txn.platform_account_email,
```

- [ ] **Step 7: Stamp at creation** in `service.py` inside the `TransactionRecord(...)` construction at `:491`, after `seller_organization_id=seller_org_id,`:

```python
                platform_account_email=self.settings.paypal_platform_email,
```

`VerifundService` already holds `self.settings` (`service.py:258`), so no constructor change is needed. The value comes from server config only — never from request input. Existing transactions keep `NULL` and are therefore invisible to the admin workspace.

- [ ] **Step 8: Run the new test plus the transaction suites** — `uv run pytest tests/unit/test_platform_owner.py tests/unit/test_transactions.py -q`. All pass.

- [ ] **Step 9: Commit** — `git add ...domain.py ...repository.py ...service.py tests/unit/test_platform_owner.py && git commit -m "feat(verifund): stamp platform_account_email on new transactions"`

### Task 7: Fail-closed platform-owner authorization

**Files:** new `apps/verifund_control_plane/verifund_control_plane/api/platform_auth.py`, new tests in `tests/unit/test_platform_owner.py`

- [ ] **Step 1: Write failing tests** (append to `tests/unit/test_platform_owner.py`):

```python
async def test_platform_owner_mismatch_returns_404(client):
    from verifund_control_plane.api.platform_auth import authorize_platform_transaction

    app = client._transport.app
    txn = await _award_a_transaction(client)  # stamped platform@example.com
    with pytest.raises(Exception) as exc:
        authorize_platform_transaction(txn, "other@example.com")
    assert getattr(exc.value, "status_code", None) == 404
```

and a positive case asserting no exception for `"platform@example.com"`.

- [ ] **Step 2: Run to confirm failure** — module does not exist.

- [ ] **Step 3: Implement** `api/platform_auth.py`:

```python
from __future__ import annotations

from verifund_control_plane.errors import VerifundError


def authorize_platform_transaction(txn, platform_email: str):
    """Fail closed when a transaction was settled by a different platform account."""
    if not platform_email or getattr(txn, "platform_account_email", None) != platform_email:
        raise VerifundError("not_found", "transaction not found", status_code=404)
    return txn
```

Use `VerifundError` (the project's standard error type, already mapped to HTTP status by `verifund_error_handler` at `app.py:239`) so mismatches return 404 without leaking existence.

- [ ] **Step 4: Run tests** — `uv run pytest tests/unit/test_platform_owner.py -q`.

- [ ] **Step 5: Commit** — `git add ...api/platform_auth.py tests/unit/test_platform_owner.py && git commit -m "feat(verifund): add fail-closed platform transaction authorization"`

### Task 8: Platform-admin `/v1/admin/*` router

**Files:** new `apps/verifund_control_plane/verifund_control_plane/admin/__init__.py`, new `admin/routes.py`, edit `app.py`, new tests in `tests/unit/test_admin_routes.py`

- [ ] **Step 1: Write failing tests** in new `tests/unit/test_admin_routes.py` reusing the `client`/`identities` fixture from `test_platform_admin.py`:

```python
async def test_member_cannot_read_admin_overview(client, identities):
    r = await client.get("/v1/admin/overview", headers=identities["member_headers"])
    assert r.status_code == 403

async def test_admin_reads_only_platform_transactions(client, identities):
    r = await client.get("/v1/admin/transactions", headers=identities["admin_headers"])
    assert r.status_code == 200
    assert all(t["platform_account_email"] == "platform@example.com" for t in r.json())

async def test_admin_cannot_read_foreign_platform_transaction(client, identities):
    r = await client.get("/v1/admin/transactions/vf_foreign", headers=identities["admin_headers"])
    assert r.status_code == 404
```

- [ ] **Step 2: Run to confirm failure** — 404/405 from an unregistered route.

- [ ] **Step 3: Implement the router.** `admin/routes.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from verifund_control_plane.api.platform_auth import authorize_platform_transaction
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.identity import Identity, require_identity
from verifund_control_plane.tenancy.routes import PayoutReleaseRequest

router = APIRouter(prefix="/v1/admin")


async def require_admin(request: Request) -> Identity:
    identity = await require_identity(request)
    if not identity.is_platform_admin:
        raise VerifundError("forbidden", "platform admin required", status_code=403)
    return identity


def _platform_email(request: Request) -> str:
    return request.app.state.settings.paypal_platform_email


@router.get("/overview")
async def overview(request: Request) -> dict:
    await require_admin(request)
    store = request.app.state.tenancy
    pending = [
        r
        for r in await store.list_seller_verifications(status="pending")
    ]
    transactions = await request.app.state.repo.list_platform_transactions(
        _platform_email(request), limit=500
    )
    return {
        "pending_verifications": len(pending),
        "platform_transaction_count": len(transactions),
        "platform_held_cents": sum(
            (await request.app.state.repo.ledger_balances(t.transaction_id)).get(
                "platform_cash", 0
            )
            for t in transactions
        ),
    }


@router.get("/transactions")
async def list_platform_transactions(
    request: Request,
    state: str | None = None,
    seller_id: str | None = None,
    buyer_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    await require_admin(request)
    txns = await request.app.state.repo.list_platform_transactions(
        _platform_email(request),
        state=state,
        seller_id=seller_id,
        buyer_id=buyer_id,
        limit=limit,
    )
    return [_serialize(t) for t in txns]


@router.get("/transactions/{transaction_id}")
async def get_platform_transaction(transaction_id: str, request: Request) -> dict:
    await require_admin(request)
    repo = request.app.state.repo
    txn = await repo.get_transaction(transaction_id)
    authorize_platform_transaction(txn, _platform_email(request))
    return {
        **_serialize(txn),
        "agreement": await repo.get_agreement(txn.agreement_id),
        "ledger": await repo.ledger_entries(transaction_id),
        "events": await repo.list_transaction_events(transaction_id),
        "evidence": await repo.list_evidence(transaction_id),
    }


@router.get("/transactions/{transaction_id}/audit")
async def platform_transaction_audit(transaction_id: str, request: Request) -> list[dict]:
    await require_admin(request)
    repo = request.app.state.repo
    txn = await repo.get_transaction(transaction_id)
    authorize_platform_transaction(txn, _platform_email(request))
    return await request.app.state.tenancy.list_audit(
        scope="transaction", resource_id=transaction_id
    )


@router.post("/transactions/{transaction_id}/payout-release", status_code=201)
async def admin_payout_release(
    transaction_id: str, body: PayoutReleaseRequest, request: Request
) -> dict:
    identity = await require_admin(request)
    repo = request.app.state.repo
    txn = await repo.get_transaction(transaction_id)
    authorize_platform_transaction(txn, _platform_email(request))
    store = request.app.state.tenancy
    seller_org_id = txn.seller_organization_id
    if seller_org_id is None:
        org = await store.ensure_seed_organization(
            seller_id=txn.seller_id, kind="business", verified=False
        )
        seller_org_id = org["id"]
    release = await store.create_payout_release(
        transaction_id, seller_org_id, identity.user_id, body.reason
    )
    await store.record_audit(
        scope="organization",
        organization_id=seller_org_id,
        transaction_id=transaction_id,
        actor_user_id=identity.user_id,
        actor_type="user",
        action="payout.release_approved",
        resource_id=transaction_id,
        payload={
            "reason": body.reason,
            "actor": f"user:{identity.clerk_user_id} acting for platform:{_platform_email(request)}",
        },
    )
    return release


@router.get("/disputes")
async def platform_disputes(request: Request) -> list[dict]:
    await require_admin(request)
    txns = await request.app.state.repo.list_platform_transactions(
        _platform_email(request), limit=500
    )
    return [
        {"transaction_id": t.transaction_id, "dispute": t.dispute}
        for t in txns
        if t.dispute
    ]


@router.get("/disputes/{transaction_id}")
async def platform_dispute_detail(transaction_id: str, request: Request) -> dict:
    await require_admin(request)
    repo = request.app.state.repo
    txn = await repo.get_transaction(transaction_id)
    authorize_platform_transaction(txn, _platform_email(request))
    return {"transaction_id": transaction_id, "dispute": txn.dispute,
            "evidence": await repo.list_evidence(transaction_id)}


@router.get("/verification/pending")
async def pending_verifications(request: Request) -> list[dict]:
    await require_admin(request)
    return await request.app.state.tenancy.list_seller_verifications(status="pending")


@router.get("/settings")
async def platform_settings(request: Request) -> dict:
    await require_admin(request)
    email = _platform_email(request)
    return {"platform_account_email": _redact_email(email)}


def _redact_email(email: str) -> str:
    if "@" not in email:
        return "(unset)"
    local, domain = email.split("@", 1)
    return f"{local[:2]}***@{domain}"


def _serialize(txn) -> dict:
    return {
        "transaction_id": txn.transaction_id,
        "state": txn.state.value if hasattr(txn.state, "value") else txn.state,
        "buyer_id": txn.buyer_id,
        "seller_id": txn.seller_id,
        "amount_cents": txn.amount_cents,
        "currency": txn.currency,
        "platform_account_email": txn.platform_account_email,
        "created_at": txn.created_at.isoformat(),
    }
```

Add the supporting repository methods to core `repository.py` (next to `list_transactions` at `:602`):

```python
    async def list_platform_transactions(
        self,
        platform_email: str,
        *,
        state: str | None = None,
        seller_id: str | None = None,
        buyer_id: str | None = None,
        limit: int = 50,
    ) -> list[TransactionRecord]:
        statement = self.transactions.select().where(
            self.transactions.c.platform_account_email == platform_email
        )
        if state:
            statement = statement.where(self.transactions.c.state == state)
        if seller_id:
            statement = statement.where(self.transactions.c.seller_id == seller_id)
        if buyer_id:
            statement = statement.where(self.transactions.c.buyer_id == buyer_id)
        statement = statement.order_by(
            self.transactions.c.created_at.desc()
        ).limit(max(1, min(limit, 500)))
        async with self.engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [self._record(row) for row in rows]
```

Add `list_seller_verifications(self, status: str | None = None)` to `TenancyRepository` (`tenancy/repository.py`), selecting from `self.seller_verifications` with an optional status filter and ordering by `created_at`. Reuse existing `_record`-style mapping: `dict(row._mapping)`.

If `repo.get_agreement`, `repo.list_transaction_events`, or `repo.list_evidence` do not exist under those exact names, locate their equivalents in `repository.py`/`agreement/repository.py` and adapt the three calls in `get_platform_transaction` — do not invent new storage.

- [ ] **Step 4: Register the router** in `app.py`. Add `from verifund_control_plane.admin import routes as admin_routes` beside the other imports and, after line 250:

```python
    app.include_router(admin_routes.router)
```

- [ ] **Step 5: Leave the machine `/ops/*` routes untouched.** Do **not** add the platform-ownership check to `tenancy/routes.py::ops_payout_release` — that route also serves ops-token machine flows whose transactions may predate the `platform_account_email` stamp, and changing it would break them. The new `admin_payout_release` above is the human/admin path: it enforces ownership via `authorize_platform_transaction()` and records the human actor. `require_platform_admin` already accepts both the ops token and a mirrored admin identity, so verification stays backward-compatible.

- [ ] **Step 6: Run tests** — `uv run pytest tests/unit/test_admin_routes.py tests/unit/test_platform_admin.py tests/unit/test_platform_owner.py tests/unit/test_tenant_isolation.py tests/unit/test_payout_releases.py -q`. All pass; existing 403 member / 200 platform-admin verification behavior and machine payout flows are unchanged.

- [ ] **Step 7: Commit** — `git add ...admin ...app.py ...repository.py ...tenancy/repository.py tests/unit/test_admin_routes.py && git commit -m "feat(verifund): add platform-admin admin API and ownership checks"`

**Milestone 2 checkpoint:** admins can list/detail only transactions stamped with `PAYPAL_PLATFORM_EMAIL`; foreign or unstamped transactions return 404; payout release requires platform ownership and records the human actor.

---

## Milestone 3 — Admin pages (`deploy/console`)

### Task 9: Add all ten admin pages

Every page is a server component, contains a literal `auth.protect()` (required by `tests/app/route-guards.test.ts:51–53`), inherits the `app/admin/layout.tsx` gate, and fetches through `controlPlaneForUser` — never `controlPlaneAsPlatform`.

- [ ] **Step 1: Add a small shared fetch helper** as `apps/console/lib/admin-api.ts`:

```ts
import { auth } from "@clerk/nextjs/server";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function adminJson<T>(path: string): Promise<T> {
  await auth.protect(); // literal guard — every admin page includes this transitively
  const response = await controlPlaneForUser(path);
  if (response.status === 403) throw new Error("forbidden");
  if (!response.ok) throw new Error(`admin API ${response.status}`);
  return (await response.json()) as T;
}
```

Note: because the static guard test checks each *file*, every page must still contain its own literal `auth.protect()` call even though `adminJson` also guards.

- [ ] **Step 2: Add a reusable page shell** as `apps/console/components/admin/admin-page.tsx`:

```tsx
import { Panel } from "@/components/ui/panel";

export function AdminPage({
  kicker,
  title,
  children,
}: {
  kicker: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <main className="mm-dashboard-page">
      <Panel className="mm-dashboard-hero">
        <div className="mm-dashboard-hero-copy">
          <p className="mm-kicker">{kicker}</p>
          <h1 className="mm-home-title">{title}</h1>
          {children}
        </div>
      </Panel>
    </main>
  );
}
```

- [ ] **Step 3: Create the ten route files.** Use this exact template for each (shown once for `/admin/transactions`), replacing kicker/title/endpoint:

```tsx
import { auth } from "@clerk/nextjs/server";
import { AdminPage } from "@/components/admin/admin-page";
import { adminJson } from "@/lib/admin-api";

export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

export default async function AdminTransactionsPage() {
  await auth.protect();
  const rows = await adminJson<Row[]>("/v1/admin/transactions");
  return (
    <AdminPage kicker="Platform admin" title="Platform transactions">
      <pre data-testid="admin-transactions">{JSON.stringify(rows, null, 2)}</pre>
    </AdminPage>
  );
}
```

Create these files with the corresponding endpoints:

| File | Kicker / Title | `adminJson` endpoint |
|---|---|---|
| `app/admin/page.tsx` | `Platform admin` / `Overview` | `/v1/admin/overview` |
| `app/admin/transactions/page.tsx` | `Platform admin` / `Platform transactions` | `/v1/admin/transactions` |
| `app/admin/transactions/[id]/page.tsx` | `Platform transaction` / `Transaction detail` | `/v1/admin/transactions/${id}` |
| `app/admin/transactions/[id]/audit/page.tsx` | `Platform transaction` / `Transaction audit` | `/v1/admin/transactions/${id}/audit` |
| `app/admin/payouts/page.tsx` | `Platform admin` / `Payouts` | `/v1/admin/transactions?state=funded` (queue; approval posts to `/v1/admin/transactions/{id}/payout-release` via a new server action — see Step 4) |
| `app/admin/disputes/page.tsx` | `Platform admin` / `Disputes` | `/v1/admin/disputes` |
| `app/admin/disputes/[id]/page.tsx` | `Platform admin` / `Dispute detail` | `/v1/admin/disputes/${id}` |
| `app/admin/verification/page.tsx` | `Platform admin` / `Seller verification` | `/v1/admin/verification/pending` |
| `app/admin/users/page.tsx` | `Platform admin` / `Users` | `/api/admin/users` (console route, Step 5) |
| `app/admin/audit/page.tsx` | `Platform admin` / `Audit log` | `/v1/admin/audit` |
| `app/admin/settings/page.tsx` | `Platform admin` / `Settings` | `/v1/admin/settings` |

Dynamic `[id]` pages read `params` as `Promise<{ id: string }>` (Next 16) and `await params` before interpolating.

Add `/v1/admin/audit` to `admin/routes.py` if not already present, reusing `tenancy.list_audit()` with optional `scope`/`actor_type` query filters and `require_admin`.

- [ ] **Step 4: Add the payout approval server action** as `app/admin/payouts/actions.ts`:

```ts
"use server";

import { auth } from "@clerk/nextjs/server";
import { revalidatePath } from "next/cache";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function approvePayout(transactionId: string, reason: string): Promise<void> {
  await auth.protect();
  const response = await controlPlaneForUser(
    `/v1/admin/transactions/${encodeURIComponent(transactionId)}/payout-release`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reason }),
    },
  );
  if (!response.ok) throw new Error(`payout release ${response.status}`);
  revalidatePath("/admin/payouts");
}
```

This uses the user's Clerk token; the backend's `require_platform_admin` accepts the mirrored admin identity. No ops token is involved. Add a confirm button to `payouts/page.tsx` wired to this action.

- [ ] **Step 5: Add the read-only users route** as `app/api/admin/users/route.ts`:

```ts
import { auth } from "@clerk/nextjs/server";
import { clerkClient } from "@clerk/nextjs/server";
import { adminAccess } from "@/lib/admin-access";

export const dynamic = "force-dynamic";

export async function GET() {
  await auth.protect();
  if (!(await adminAccess())) return Response.json({ error: "forbidden" }, { status: 403 });
  const client = await clerkClient();
  const users = await client.users.getUserList({ limit: 100 });
  return Response.json(
    {
      users: users.data.map((u) => ({
        id: u.id,
        email: u.emailAddresses.find((e) => e.id === u.primaryEmailAddressId)?.emailAddress ?? null,
        role: (u.publicMetadata?.role as string) ?? null,
      })),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
```

This is strictly read-only — there is no promote/demote endpoint anywhere in the admin workspace. Add a test `tests/app/admin-users-route.test.ts` asserting a non-admin call returns 403 and no mutation method exists.

- [ ] **Step 6: Add page tests.** Create `tests/app/admin-pages.test.tsx`: mock `@clerk/nextjs/server` (`auth.protect`), `@/lib/admin-api` (`adminJson`), and `@/components/admin/admin-page`; for each of the ten pages, import it, call it (awaiting `params` where needed), and assert `adminJson` was called with the expected endpoint from the Step 3 table. This also guards the literal `auth.protect()` requirement.

- [ ] **Step 7: Run validation** — `npm run typecheck && npm run test -- tests/app/admin-pages.test.tsx tests/app/admin-users-route.test.ts tests/app/route-guards.test.ts`.

- [ ] **Step 8: Commit** — `git add apps/console/app/admin apps/console/app/api/admin apps/console/components/admin apps/console/lib/admin-api.ts apps/console/tests && git commit -m "feat(console): add admin ops pages (transactions, payouts, disputes, users, audit)"`

**Milestone 3 checkpoint:** `/admin` and all nine sub-pages render for admins with live backend data; non-admins never reach them (layout gate + per-file guards + API 403s).

---

## Milestone 4 — End-to-end validation and rollout

### Task 10: E2E and full-suite verification

- [ ] **Step 1: Add E2E spec** `apps/console/e2e/admin-workspace.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test("non-admin is silently redirected from /admin", async ({ page }) => {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/$/);
});

test("admin can open the workspace and platform transactions", async ({ page }) => {
  // authenticate as a Clerk user whose publicMetadata.role === "admin"
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.goto("/admin/transactions");
  await expect(page.getByRole("heading", { name: "Platform transactions" })).toBeVisible();
});
```

Use the same Clerk test-user setup as the existing `e2e/console.spec.ts`; document the required `publicMetadata.role = "admin"` in the spec comment.

- [ ] **Step 2: Run the console suite** — `cd apps/console && npm run typecheck && npm run test && npm run test:e2e`. Report any pre-existing/flaky failures separately with command output; do not silently skip.

- [ ] **Step 3: Run the backend suite** — from the render worktree: `uv run pytest tests/unit -q`. Pay particular attention to `test_platform_admin.py`, `test_clerk_webhooks.py`, `test_platform_owner.py`, `test_admin_routes.py`, `test_tenant_isolation.py`, `test_transaction_access.py`, and `test_payout_releases.py`.

- [ ] **Step 4: Manual sandbox verification.** With a real Clerk admin user and `PAYPAL_PLATFORM_EMAIL` configured:
  1. Set `publicMetadata.role = "admin"` in the Clerk Dashboard; confirm the webhook creates the `platform_admins` row and `GET /v1/me` returns `is_platform_admin: true`.
  2. Sign in → `/post-auth` → lands on `/admin`.
  3. Open `/admin/transactions`; confirm only transactions stamped with that platform email appear.
  4. Try a foreign transaction id → 404.
  5. Approve a payout; confirm the audit entry actor is `user:<clerk_id> acting for platform:<email>`.
  6. Demote the user in Clerk; confirm the webhook removes the row, `/admin` redirects to `/`, and `/v1/admin/*` returns 403.

- [ ] **Step 5: Commit** — `git add apps/console/e2e/admin-workspace.spec.ts && git commit -m "test(console): add admin workspace e2e coverage"` (on `deploy/console`).

- [ ] **Step 6: Integration.** Merge/stack the `deploy/render` backend commits and `deploy/console` frontend commits per the team's release process. Verify the combined deploy: the console's `VERIFUND_CONTROL_PLANE_URL` points at the updated control plane and `PAYPAL_PLATFORM_EMAIL` is set in both the webhook-verified backend environment and the payout configuration.

- [ ] **Step 7: Update docs** — add an "Admin workspace" section to `docs/console.md` pointing at the design spec and listing `/admin/*` routes; note that role granting is out-of-band. Commit separately: `git commit -m "docs: document the admin workspace"`.

- [ ] **Step 8: Finish the branch** using `superpowers:finishing-a-development-branch` once implementation and verification are green.

---

## Invariants to re-check at every commit

1. Authority comes from a verified Clerk session + mirrored `platform_admins` row — never from `publicMetadata` at request time, query strings, or headers.
2. Webhook grants/revokes are Svix-verified and deduplicated; demotion and deletion revoke access.
3. `platform_account_email` is server-derived from `PAYPAL_PLATFORM_EMAIL`, stamped at creation, and compared server-side with 404 on mismatch.
4. Every admin mutation writes an audit entry naming the human actor and the platform account.
5. No ops token, `controlPlaneAsPlatform`, or platform credential appears in any admin page, client component, or browser bundle.
6. Buyer/seller tenant predicates (`buyer_organization_id`/`seller_organization_id`) are untouched; `include_all` is never implicit.
7. Every new admin server file contains the literal `auth.protect()` string.
8. Admin access is additive — buyer and seller workspaces still work for an admin user.
