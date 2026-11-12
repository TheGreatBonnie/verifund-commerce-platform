# Seller Onboarding Profile & Verification MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the seller onboarding wizard `profile` and `verification` steps functional (MVP) so a seller can complete onboarding in sandbox and reach agent activation, using server-authoritative control-plane transitions and sandbox auto-approve.

**Architecture:** Add a seller-authenticated control-plane endpoint to save minimal profile fields and advance onboarding to `verification`, and extend verification submission to auto-approve in sandbox (`settings.is_sandbox`) by invoking the existing `decide_verification` state machine. In the console, add static `profile/` and `verification/` route segments (overriding `[step]`) with server pages + client forms + server actions that call the control plane via `controlPlaneForUser`, matching existing onboarding/agent patterns.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/SQLite (tenancy repo), Pydantic v2, pytest + `httpx.AsyncClient`/ASGITransport; Next.js App Router (TypeScript), Clerk (`auth.protect`), server actions, vitest.

**Spec:** `docs/superpowers/specs/2026-11-07-seller-onboarding-profile-verification-mvp-design.md`

## Global Constraints

- **Tenancy/auth:** organization/tenant derived only from verified identity (`require_identity`); never from request body. `console` mutations use `auth.protect()` + `controlPlaneForUser`.
- **State machine:** verification transitions follow `SUBMIT_FROM={"unverified","rejected"}` and `DECIDE_MAP` (`verified` allowed from `pending|suspended`; for auto-approve on submit, decide `verified` from `pending`).
- **Sandbox auto-approve:** gated strictly by server settings (`request.app.state.settings.is_sandbox` / `mode=="sandbox"`). Never client-controlled. Non-sandbox: submit remains `pending` (awaiting out-of-band approval).
- **No scope creep:** no file/KYC document upload/storage, no in-console admin review UI, minimal profile fields (reuse existing schema).
- **Routing:** `sellerEntryPath` keeps verified → `/seller/dashboard` (`apps/console/lib/onboarding.ts`); provide explicit CTAs for post-verify continuation.
- **Tests green:** keep existing tests passing; run targeted tests and full `uv run pytest` at the end.

## File Structure

**Modify (control plane):**
- `apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py` — add `update_seller_display_name(...)` (existing `upsert_seller_profile` returns existing without updating).
- `apps/verifund_control_plane/verifund_control_plane/onboarding/service.py` — add `save_profile_and_continue(...)`; extend `submit_verification(...)` with `auto_approve_sandbox: bool = False` and in-flow `decide_verification`.
- `apps/verifund_control_plane/verifund_control_plane/onboarding/routes.py` — add `POST /v1/seller/onboarding/profile`; pass sandbox flag in submit route.

**Modify (console):**
- `apps/console/app/(seller-onboarding)/seller/onboarding/actions.ts` — add `saveProfileAction`, `submitVerificationAction` (CP calls via `controlPlaneForUser`, `ActionResult` pattern).
- `apps/console/lib/agent-types.ts` (or new `lib/onboarding-types.ts`, if preferred) — optional types for onboarding action results; only if needed.

**Create (console):**
- `apps/console/app/(seller-onboarding)/seller/onboarding/profile/page.tsx` — server page.
- `apps/console/app/(seller-onboarding)/seller/onboarding/verification/page.tsx` — server page.
- `apps/console/components/seller-agent/ProfileForm.tsx` — client form.
- `apps/console/components/seller-agent/VerificationSubmitForm.tsx` — client form.

**Tests:**
- `tests/unit/test_seller_onboarding_profile.py` (create) — service/repo profile advance behavior.
- `tests/unit/test_seller_onboarding_verification.py` (create) — submit + sandbox auto-approve behavior.
- `tests/integration/test_seller_onboarding_routes.py` (create) — HTTP route behavior with `httpx.AsyncClient`/ASGITransport (follow `tests/integration/test_onboarding_agent_flow.py` fixture style; mock `clerk_authenticator`).
- `apps/console/tests/lib/onboarding.test.ts` (modify) — add `current_step:"profile"` routing case if useful.

---

### Task 1: Repository — update seller display name

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py`
- Test: `tests/unit/test_seller_onboarding_profile.py`

**Interfaces:**
- Produces: `TenancyRepository.update_seller_display_name(seller_id: str, display_name: str) -> dict | None` (updates `display_name`, `updated_at`; returns refreshed profile or `None`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_seller_onboarding_profile.py`:

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    repository = TenancyRepository(engine)
    async with engine.begin() as conn:
        await repository.create_tables(conn)
    yield repository
    await engine.dispose()


async def test_update_seller_display_name(repo):
    await repo.upsert_seller_profile("org_1", "acme", "Acme")
    updated = await repo.update_seller_display_name("acme", "Acme Industrial")
    assert updated is not None
    assert updated["seller_id"] == "acme"
    assert updated["display_name"] == "Acme Industrial"


async def test_update_seller_display_name_missing(repo):
    assert await repo.update_seller_display_name("missing", "X") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_onboarding_profile.py -v`  
Expected: FAIL with `AttributeError: 'TenancyRepository' object has no attribute 'update_seller_display_name'` (or similar).

- [ ] **Step 3: Write minimal implementation**

In `apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py`, add after `upsert_seller_profile` (near line 507):

```python
    async def update_seller_display_name(
        self, seller_id: str, display_name: str
    ) -> dict | None:
        existing = await self.get_seller_profile(seller_id)
        if existing is None:
            return None
        async with self.engine.begin() as conn:
            await conn.execute(
                self.seller_profiles.update()
                .where(self.seller_profiles.c.seller_id == seller_id)
                .values(display_name=display_name, updated_at=_now())
            )
        return await self.get_seller_profile(seller_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_seller_onboarding_profile.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py tests/unit/test_seller_onboarding_profile.py
git commit -m "feat(control-plane): add seller display name update for onboarding"
```

---

### Task 2: Onboarding service — save profile + advance

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/onboarding/service.py`
- Test: `tests/unit/test_seller_onboarding_profile.py`

**Interfaces:**
- Produces: `async def save_profile_and_continue(store, organization_id: str, actor_user_id: str, display_name: str) -> dict` returning `{"profile": ..., "onboarding": ...}`; raises `VerifundError("not_found")` if no profile; advances `current_step` to `verification` only when it would not regress meaningful progress.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_seller_onboarding_profile.py`:

```python
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.onboarding.service import (
    create_onboarding,
    save_profile_and_continue,
)


async def _seed_business(repo, organization_id="org_acme"):
    org = await repo.upsert_organization(organization_id, "Acme", "acme", kind="business")
    user = await repo.upsert_user("user_1", "u@example.com", "User")
    await repo.upsert_membership(org["id"], user["id"], "org:admin", "mem_1")
    return org, user


async def test_save_profile_and_continue_advances_to_verification(repo):
    org, user = await _seed_business(repo)
    await create_onboarding(repo, org["id"], user["id"])
    result = await save_profile_and_continue(
        repo, org["id"], user["id"], "Acme Industrial"
    )
    assert result["profile"]["display_name"] == "Acme Industrial"
    assert result["onboarding"]["current_step"] == "verification"
    assert result["onboarding"]["status"] == "in_progress"


async def test_save_profile_and_continue_not_found(repo):
    with pytest.raises(VerifundError) as exc:
        await save_profile_and_continue(repo, "org_missing", "u1", "X")
    assert exc.value.code == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_onboarding_profile.py -v`  
Expected: FAIL with import/name error for `save_profile_and_continue`.

- [ ] **Step 3: Write minimal implementation**

In `apps/verifund_control_plane/verifund_control_plane/onboarding/service.py`, add:

```python
async def save_profile_and_continue(
    store, organization_id: str, actor_user_id: str, display_name: str
) -> dict:
    profile = await store.get_seller_profile_by_organization(organization_id)
    if profile is None:
        raise VerifundError("not_found", "seller profile not found", status_code=404)
    name = display_name.strip()
    if not name:
        raise VerifundError("invalid_argument", "display_name is required", status_code=400)
    updated_profile = await store.update_seller_display_name(profile["seller_id"], name)
    if updated_profile is None:
        raise VerifundError("not_found", "seller profile not found", status_code=404)

    onboarding = await store.get_onboarding(organization_id)
    current = (onboarding or {}).get("current_step")
    # Do not regress submitted/verified workflows; advance early steps to verification.
    if current in (None, "profile"):
        onboarding = await store.upsert_onboarding(
            organization_id, "in_progress", "verification"
        )
    else:
        onboarding = await store.get_onboarding(organization_id)

    await store.record_audit(
        scope="organization",
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_type="user",
        action="seller.onboarding.profile_saved",
        resource_id=updated_profile["seller_id"],
        payload={"display_name": name},
    )
    return {"profile": updated_profile, "onboarding": onboarding}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_seller_onboarding_profile.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/onboarding/service.py tests/unit/test_seller_onboarding_profile.py
git commit -m "feat(control-plane): save seller onboarding profile and advance step"
```

---

### Task 3: Verification service — sandbox auto-approve

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/onboarding/service.py`
- Test: `tests/unit/test_seller_onboarding_verification.py`

**Interfaces:**
- Changes: `submit_verification(store, organization_id, submitted_by, documents, *, auto_approve_sandbox: bool = False) -> dict`.
- Behavior: after normal submit, if `auto_approve_sandbox` is true, call `decide_verification(..., decision="verified", note="Auto-approved in sandbox", reviewer_user_id=submitted_by)` and set onboarding `status="in_progress", current_step="activation"` (informational; verified profile drives entry routing). Returns refreshed profile.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_seller_onboarding_verification.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.onboarding.service import (
    create_onboarding,
    submit_verification,
)
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    repository = TenancyRepository(engine)
    async with engine.begin() as conn:
        await repository.create_tables(conn)
    yield repository
    await engine.dispose()


async def _seed(repo):
    org = await repo.upsert_organization("org_acme", "Acme", "acme", kind="business")
    user = await repo.upsert_user("user_1", "u@example.com", "User")
    await repo.upsert_membership(org["id"], user["id"], "org:admin", "mem_1")
    await create_onboarding(repo, org["id"], user["id"])
    return org, user


async def test_submit_verification_pending_without_auto_approve(repo):
    org, user = await _seed(repo)
    profile = await submit_verification(
        repo, org["id"], user["id"], {"note": "docs"}, auto_approve_sandbox=False
    )
    assert profile["verification_status"] == "pending"
    onboarding = await repo.get_onboarding(org["id"])
    assert onboarding["status"] == "submitted"
    assert onboarding["current_step"] == "verification"


async def test_submit_verification_auto_approves_in_sandbox(repo):
    org, user = await _seed(repo)
    profile = await submit_verification(
        repo, org["id"], user["id"], {"note": "docs"}, auto_approve_sandbox=True
    )
    assert profile["verification_status"] == "verified"
    onboarding = await repo.get_onboarding(org["id"])
    assert onboarding["current_step"] in {"activation", "agent_setup", "verified", "complete"} or onboarding["status"] == "in_progress"
    # strongest check: seller is verified and onboarding unblocked
    assert (await repo.get_seller_profile_by_organization(org["id"]))["verification_status"] == "verified"


async def test_submit_verification_invalid_state(repo):
    org, user = await _seed(repo)
    await submit_verification(repo, org["id"], user["id"], {}, auto_approve_sandbox=False)
    with pytest.raises(VerifundError) as exc:
        await submit_verification(repo, org["id"], user["id"], {}, auto_approve_sandbox=False)
    assert exc.value.code == "invalid_state"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_onboarding_verification.py -v`  
Expected: FAIL because `submit_verification` does not accept `auto_approve_sandbox` (or auto-approve not implemented).

- [ ] **Step 3: Write minimal implementation**

In `apps/verifund_control_plane/verifund_control_plane/onboarding/service.py`, change `submit_verification` to:

```python
async def submit_verification(
    store, organization_id: str, submitted_by: str, documents: list | dict,
    *, auto_approve_sandbox: bool = False,
) -> dict:
    profile = await store.get_seller_profile_by_organization(organization_id)
    if profile is None:
        raise VerifundError("not_found", "seller profile not found", status_code=404)
    if profile["verification_status"] not in SUBMIT_FROM:
        raise VerifundError("invalid_state", "cannot submit for verification", status_code=409)
    await store.set_verification_status(profile["seller_id"], "pending")
    await store.create_verification(organization_id, submitted_by, documents)
    await store.upsert_onboarding(organization_id, "submitted", "verification")
    await store.record_audit(
        scope="organization",
        organization_id=organization_id,
        actor_user_id=submitted_by,
        actor_type="user",
        action="seller.verification.submitted",
        resource_id=profile["seller_id"],
        payload={"documents": documents},
    )
    if auto_approve_sandbox:
        approved = await decide_verification(
            store,
            organization_id,
            decision="verified",
            note="Auto-approved in sandbox",
            reviewer_user_id=submitted_by,
        )
        await store.upsert_onboarding(organization_id, "in_progress", "activation")
        return approved
    return await store.get_seller_profile(profile["seller_id"])  # type: ignore[return-value]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_seller_onboarding_verification.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/onboarding/service.py tests/unit/test_seller_onboarding_verification.py
git commit -m "feat(control-plane): auto-approve seller verification in sandbox"
```

---

### Task 4: Control plane routes — profile endpoint + sandbox submit wiring

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/onboarding/routes.py`
- Test: `tests/integration/test_seller_onboarding_routes.py`

**Interfaces:**
- Produces: `POST /v1/seller/onboarding/profile` (body `{"display_name": "..."}`) → `{"profile","onboarding"}`.
- Changes: `POST /v1/seller/verification/submit` passes `auto_approve_sandbox=bool(getattr(request.app.state.settings, "is_sandbox", False))`.

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_seller_onboarding_routes.py`:

```python
from datetime import UTC, datetime

import httpx
import pytest_asyncio
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

CLOCK = lambda: datetime.now(UTC)


async def _build_app(tmp_path, *, sandbox: bool):
    settings = Settings(
        _env_file=None,
        mode="sandbox" if sandbox else "fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="https://test.example.com" if sandbox else "http://test",
    )
    app = create_app(settings, clock=CLOCK)
    return app


async def _seed_seller(app):
    store = app.state.tenancy
    user = await store.upsert_user("user_s1", "s1@example.com", "Seller")
    org = await store.upsert_organization("org_s1", "Seller Org", "seller-org", kind="business")
    await store.upsert_membership(org["id"], user["id"], "org:admin", "mem_s1")
    app.state.clerk_authenticator = lambda request: {
        "sub": "user_s1",
        "org_id": "org_s1",
        "org_role": "org:admin",
    }
    return {"authorization": "Bearer s1"}


@pytest_asyncio.fixture
async def sandbox_client(tmp_path):
    app = await _build_app(tmp_path, sandbox=True)
    async with app.router.lifespan_context(app):
        headers = await _seed_seller(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, headers


@pytest_asyncio.fixture
async def pending_client(tmp_path):
    app = await _build_app(tmp_path, sandbox=False)
    async with app.router.lifespan_context(app):
        headers = await _seed_seller(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, headers


async def test_profile_route_saves_and_advances(sandbox_client):
    client, headers = sandbox_client
    r = await client.post("/v1/seller/onboarding", headers=headers)
    assert r.status_code == 201
    r = await client.post(
        "/v1/seller/onboarding/profile",
        json={"display_name": "Seller One Inc"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"]["display_name"] == "Seller One Inc"
    assert body["onboarding"]["current_step"] == "verification"


async def test_submit_route_auto_approves_in_sandbox(sandbox_client):
    client, headers = sandbox_client
    await client.post("/v1/seller/onboarding", headers=headers)
    await client.post(
        "/v1/seller/onboarding/profile",
        json={"display_name": "Seller One Inc"},
        headers=headers,
    )
    r = await client.post(
        "/v1/seller/verification/submit",
        json={"documents": {"note": "sandbox"}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "verified"


async def test_submit_route_pending_when_not_sandbox(pending_client):
    client, headers = pending_client
    await client.post("/v1/seller/onboarding", headers=headers)
    await client.post(
        "/v1/seller/onboarding/profile",
        json={"display_name": "Seller One Inc"},
        headers=headers,
    )
    r = await client.post(
        "/v1/seller/verification/submit",
        json={"documents": {"note": "review"}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_seller_onboarding_routes.py -v`  
Expected: FAIL on missing `/v1/seller/onboarding/profile` (404) and/or submit not auto-approving (depending on route wiring).

- [ ] **Step 3: Write minimal implementation**

In `apps/verifund_control_plane/verifund_control_plane/onboarding/routes.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.onboarding.service import (
    create_onboarding,
    save_profile_and_continue,
    submit_verification,
)
from verifund_control_plane.tenancy.identity import require_identity

router = APIRouter()


class VerificationSubmit(BaseModel):
    documents: list | dict = Field(default_factory=list)


class ProfileSave(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)


@router.post("/v1/seller/onboarding", status_code=201)
async def start_onboarding(request: Request, response: Response) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    org = await store.get_organization(identity.tenant_id)
    if org is None or org["kind"] != "business":
        raise VerifundError(
            "forbidden", "seller onboarding requires a business organization", status_code=403
        )
    existing = await store.get_seller_profile_by_organization(identity.tenant_id)
    profile = await create_onboarding(store, identity.tenant_id, identity.user_id)
    onboarding = await store.get_onboarding(identity.tenant_id)
    if existing is not None:
        response.status_code = 200
    return {"profile": profile, "onboarding": onboarding}


@router.get("/v1/seller/onboarding")
async def get_onboarding(request: Request) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    profile = await store.get_seller_profile_by_organization(identity.tenant_id)
    onboarding = await store.get_onboarding(identity.tenant_id)
    if profile is None and onboarding is None:
        raise VerifundError("not_found", "seller onboarding not found", status_code=404)
    return {"profile": profile, "onboarding": onboarding}


@router.post("/v1/seller/onboarding/profile")
async def save_profile(request: Request, body: ProfileSave) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    return await save_profile_and_continue(
        store, identity.tenant_id, identity.user_id, body.display_name
    )


@router.post("/v1/seller/verification/submit")
async def submit(request: Request, body: VerificationSubmit) -> dict:
    identity = await require_identity(request)
    store = request.app.state.tenancy
    settings = request.app.state.settings
    return await submit_verification(
        store,
        identity.tenant_id,
        identity.user_id,
        body.documents,
        auto_approve_sandbox=bool(getattr(settings, "is_sandbox", False)),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_seller_onboarding_routes.py -v`  
Expected: PASS. (If sandbox fixture fails due to strict sandbox settings validation in `Settings.validate_for_mode`/`_env_file=None`, adjust the test fixture to use `mode="sandbox"` with required sandbox fields present as in `Settings` defaults, or set `mode="fake"` and monkeypatch `app.state.settings` to an object with `is_sandbox=True` for the auto-approve check — keep behavior identical: server-side `is_sandbox` gates auto-approve.)

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/onboarding/routes.py tests/integration/test_seller_onboarding_routes.py
git commit -m "feat(control-plane): add onboarding profile route and sandbox verification submit"
```

---

### Task 5: Console server actions — profile save & verification submit

**Files:**
- Modify: `apps/console/app/(seller-onboarding)/seller/onboarding/actions.ts`
- (No new TS test file required if repo has no server-action test harness; rely on manual E2E + lib tests. If adding, follow existing `apps/console/tests` patterns.)

**Interfaces:**
- Produces: `saveProfileAction(displayName: string): Promise<ActionResult<{ profile: unknown; onboarding: unknown }>>`
- Produces: `submitVerificationAction(documents: Record<string, unknown> | unknown[]): Promise<ActionResult<{ verification_status?: string; profile?: unknown; onboarding?: unknown }>>`
- Both: `auth.protect()`, call control plane via `controlPlaneForUser`, `revalidatePath("/seller/onboarding")`, return `{ok:false,error,status,code}` on failure.

- [ ] **Step 1: Implement actions (TDD-light; verify via typecheck/manual in later steps)**

Edit `apps/console/app/(seller-onboarding)/seller/onboarding/actions.ts` — add imports and functions (keep existing agent actions intact):

```ts
"use server";

import { auth } from "@clerk/nextjs/server";
import { revalidatePath } from "next/cache";
import { controlPlaneForUser } from "@/lib/control-plane";
import {
  activateAgent,
  createAgent,
  importCatalog,
  runAgentTests,
  saveConfig,
  savePolicies,
  SellerApiError,
} from "@/lib/agent-api";
import type {
  AgentConfigPatch,
  AgentPoliciesPatch,
  CatalogImportErrorEntry,
} from "@/lib/agent-types";

type ActionResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; status?: number; code?: string };

function asFriendlyError(err: unknown): { error: string; status?: number; code?: string } {
  if (err instanceof SellerApiError) {
    return { error: err.message, status: err.status, code: err.code };
  }
  return { error: "Something went wrong. Please try again." };
}

async function readControlPlaneError(response: Response): Promise<{ error: string; status: number; code?: string }> {
  let message = `Request failed (${response.status})`;
  let code: string | undefined;
  try {
    const body = (await response.json()) as { error?: { message?: string; code?: string }; detail?: string };
    message = body?.error?.message ?? body?.detail ?? message;
    code = body?.error?.code;
  } catch {
    // keep status message
  }
  return { error: message, status: response.status, code };
}

function revalidateAgentPaths() {
  revalidatePath("/seller/onboarding");
  revalidatePath("/seller/agent");
}

function revalidateOnboarding() {
  revalidatePath("/seller/onboarding");
  revalidatePath("/seller/onboarding/profile");
  revalidatePath("/seller/onboarding/verification");
}

export async function saveProfileAction(
  displayName: string,
): Promise<ActionResult<{ profile: unknown; onboarding: unknown }>> {
  await auth.protect();
  const name = displayName.trim();
  if (!name) return { ok: false, error: "Display name is required.", status: 400 };
  try {
    const response = await controlPlaneForUser("/v1/seller/onboarding/profile", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ display_name: name }),
    });
    if (!response.ok) return { ok: false, ...(await readControlPlaneError(response)) };
    revalidateOnboarding();
    return { ok: true, data: (await response.json()) as { profile: unknown; onboarding: unknown } };
  } catch (err) {
    return { ok: false, ...asFriendlyError(err) };
  }
}

export async function submitVerificationAction(
  documents: Record<string, unknown> | unknown[],
): Promise<ActionResult<Record<string, unknown>>> {
  await auth.protect();
  try {
    const response = await controlPlaneForUser("/v1/seller/verification/submit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ documents }),
    });
    if (!response.ok) return { ok: false, ...(await readControlPlaneError(response)) };
    revalidateOnboarding();
    return { ok: true, data: (await response.json()) as Record<string, unknown> };
  } catch (err) {
    return { ok: false, ...asFriendlyError(err) };
  }
}

/* existing createAgentAction, saveConfigAction, savePoliciesAction,
   importCatalogAction, runTestsAction, activateAgentAction remain unchanged below */
```

(When editing, preserve the existing exported agent actions verbatim below the new helpers/actions.)

- [ ] **Step 2: Typecheck console**

Run: `cd apps/console && npx tsc --noEmit` (or the repo’s console typecheck script, e.g. `npm run typecheck`/`pnpm -C apps/console ...` — use the command this repo uses).  
Expected: PASS (or only pre-existing unrelated errors; fix any errors introduced by this file).

- [ ] **Step 3: Commit**

```bash
git add apps/console/app/\(seller-onboarding\)/seller/onboarding/actions.ts
git commit -m "feat(console): add onboarding profile and verification server actions"
```

---

### Task 6: Console — Profile page and form

**Files:**
- Create: `apps/console/components/seller-agent/ProfileForm.tsx`
- Create: `apps/console/app/(seller-onboarding)/seller/onboarding/profile/page.tsx`

- [ ] **Step 1: Create `ProfileForm.tsx`**

```tsx
"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { saveProfileAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";

type Props = { initialDisplayName: string };

export function ProfileForm({ initialDisplayName }: Props) {
  const router = useRouter();
  const [displayName, setDisplayName] = useState(initialDisplayName);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        const name = displayName.trim();
        if (!name) {
          setError("Display name is required.");
          return;
        }
        startTransition(async () => {
          const result = await saveProfileAction(name);
          if (!result.ok) {
            setError(result.error);
            return;
          }
          router.push("/seller/onboarding/verification");
          router.refresh();
        });
      }}
      style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 520 }}
    >
      <label className="mm-seller-field" style={{ margin: 0 }}>
        <span>Display name</span>
        <input
          type="text"
          maxLength={128}
          required
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder="e.g. Acme Industrial"
        />
      </label>
      {error ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" disabled={pending || !displayName.trim()}>
          {pending ? "Saving…" : "Save and continue"}
        </Button>
      </div>
    </form>
  );
}
```

- [ ] **Step 2: Create `profile/page.tsx`**

```tsx
import { auth } from "@clerk/nextjs/server";
import { OnboardingStepper } from "@/components/seller-agent/OnboardingStepper";
import { ProfileForm } from "@/components/seller-agent/ProfileForm";
import { Alert } from "@/components/ui/alert";
import { Panel } from "@/components/ui/panel";
import { controlPlaneForUser } from "@/lib/control-plane";

export const dynamic = "force-dynamic";

export default async function ProfileStepPage() {
  await auth.protect();
  let profile: { display_name?: string | null; verification_status?: string | null } | null = null;
  let unreachable = false;
  try {
    const response = await controlPlaneForUser("/v1/seller/onboarding");
    if (response.ok) {
      const body = (await response.json()) as { profile?: typeof profile };
      profile = body.profile ?? null;
    } else if (response.status !== 404) {
      unreachable = true;
    }
  } catch {
    unreachable = true;
  }

  if (unreachable) {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Profile" title="Couldn't reach the server">
          <Alert message="The Verifund control plane is unreachable. Check that it's running and try again." />
        </Panel>
      </main>
    );
  }

  if (profile?.verification_status === "verified") {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Profile" title="Profile verified">
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
            Your seller profile is verified. Continue setting up your agent.
          </p>
          <a href="/seller/onboarding/agent_setup" className="mm-button mm-button-sm" style={{ marginTop: 12, display: "inline-flex", textDecoration: "none" }}>
            Continue to agent setup
          </a>
        </Panel>
      </main>
    );
  }

  return (
    <main className="mm-seller-main">
      <OnboardingStepper />
      <Panel kicker="Seller onboarding · Profile" title="Confirm your business profile">
        <p style={{ margin: "0 0 12px", color: "var(--muted)", fontSize: 12 }}>
          Confirm the name buyers and the network will see for this seller account.
        </p>
        <ProfileForm initialDisplayName={profile?.display_name ?? ""} />
      </Panel>
    </main>
  );
}
```

- [ ] **Step 3: Typecheck console**

Run: `cd apps/console && npx tsc --noEmit`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/console/components/seller-agent/ProfileForm.tsx apps/console/app/\(seller-onboarding\)/seller/onboarding/profile/page.tsx
git commit -m "feat(console): add functional seller onboarding profile step"
```

---

### Task 7: Console — Verification page and form

**Files:**
- Create: `apps/console/components/seller-agent/VerificationSubmitForm.tsx`
- Create: `apps/console/app/(seller-onboarding)/seller/onboarding/verification/page.tsx`

- [ ] **Step 1: Create `VerificationSubmitForm.tsx`**

```tsx
"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { submitVerificationAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";

export function VerificationSubmitForm() {
  const router = useRouter();
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        if (!confirmed) {
          setError("Please confirm your business details before submitting.");
          return;
        }
        startTransition(async () => {
          const result = await submitVerificationAction({
            confirmed: true,
            note: note.trim() || undefined,
            submitted_via: "seller_onboarding_wizard",
          });
          if (!result.ok) {
            setError(result.error);
            return;
          }
          const status = (result.data as { verification_status?: string }).verification_status;
          if (status === "verified") {
            router.push("/seller/onboarding/agent_setup");
          } else {
            router.refresh();
          }
        });
      }}
      style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 560 }}
    >
      <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12, color: "var(--muted)" }}>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>I confirm the business information provided for this seller account is accurate.</span>
      </label>
      <label className="mm-seller-field" style={{ margin: 0 }}>
        <span>Reference note (optional)</span>
        <input
          type="text"
          maxLength={500}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional reference for review"
        />
      </label>
      {error ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" disabled={pending || !confirmed}>
          {pending ? "Submitting…" : "Submit for verification"}
        </Button>
      </div>
    </form>
  );
}
```

- [ ] **Step 2: Create `verification/page.tsx`**

```tsx
import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { OnboardingStepper } from "@/components/seller-agent/OnboardingStepper";
import { VerificationSubmitForm } from "@/components/seller-agent/VerificationSubmitForm";
import { Alert } from "@/components/ui/alert";
import { Panel } from "@/components/ui/panel";
import { controlPlaneForUser } from "@/lib/control-plane";

export const dynamic = "force-dynamic";

type Profile = { verification_status?: string | null } | null;

export default async function VerificationStepPage() {
  await auth.protect();
  let profile: Profile = null;
  let unreachable = false;
  try {
    const response = await controlPlaneForUser("/v1/seller/onboarding");
    if (response.ok) {
      const body = (await response.json()) as { profile?: Profile };
      profile = body.profile ?? null;
    } else if (response.status !== 404) {
      unreachable = true;
    }
  } catch {
    unreachable = true;
  }

  if (unreachable) {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Verification" title="Couldn't reach the server">
          <Alert message="The Verifund control plane is unreachable. Check that it's running and try again." />
        </Panel>
      </main>
    );
  }

  const status = profile?.verification_status ?? "unverified";

  if (status === "verified") {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Verification" title="Seller verified">
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
            Your seller account is verified. Continue to configure and activate your agent.
          </p>
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <Link href="/seller/onboarding/agent_setup" className="mm-button mm-button-sm" style={{ textDecoration: "none" }}>
              Continue to agent setup
            </Link>
            <Link href="/seller/agent" className="mm-button mm-button-outline mm-button-sm" style={{ textDecoration: "none" }}>
              Open seller agent
            </Link>
          </div>
        </Panel>
      </main>
    );
  }

  if (status === "pending") {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Verification" title="Verification pending">
          <Alert message="Your verification has been submitted and is awaiting review. Activation remains blocked until the seller account is verified." />
        </Panel>
      </main>
    );
  }

  return (
    <main className="mm-seller-main">
      <OnboardingStepper />
      <Panel kicker="Seller onboarding · Verification" title="Verify your seller account">
        <p style={{ margin: "0 0 12px", color: "var(--muted)", fontSize: 12 }}>
          Submit verification to unlock activation. In sandbox environments, eligible submissions may be verified automatically; otherwise review is completed out of band.
        </p>
        {status === "rejected" ? (
          <Alert message="Your previous verification was rejected. Update any details if needed and submit again." />
        ) : null}
        <div style={{ marginTop: status === "rejected" ? 12 : 0 }}>
          <VerificationSubmitForm />
        </div>
      </Panel>
    </main>
  );
}
```

- [ ] **Step 3: Typecheck console**

Run: `cd apps/console && npx tsc --noEmit`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/console/components/seller-agent/VerificationSubmitForm.tsx apps/console/app/\(seller-onboarding\)/seller/onboarding/verification/page.tsx
git commit -m "feat(console): add functional seller onboarding verification step"
```

---

### Task 8: Routing polish, full verification, and docs note

**Files:**
- Modify (optional): `apps/console/tests/lib/onboarding.test.ts`
- Modify (optional, small): `docs/superpowers/specs/2026-11-07-seller-onboarding-profile-verification-mvp-design.md` status → `Implemented` **only after** code lands; or add a README note.

- [ ] **Step 1: Add/adjust routing test (optional but cheap)**

In `apps/console/tests/lib/onboarding.test.ts`, add:

```ts
  it("routes an unverified profile to profile step", () => {
    expect(
      sellerEntryPath(
        { verification_status: "unverified" },
        { current_step: "profile", status: "in_progress" }
      )
    ).toBe("/seller/onboarding/profile");
  });
```

- [ ] **Step 2: Run targeted tests**

Run:
```bash
uv run pytest tests/unit/test_seller_onboarding_profile.py tests/unit/test_seller_onboarding_verification.py tests/integration/test_seller_onboarding_routes.py -v
cd apps/console && npx vitest run tests/lib/onboarding.test.ts
```
Expected: PASS.

- [ ] **Step 3: Run full Python suite and console typecheck**

Run:
```bash
uv run pytest
cd apps/console && npx tsc --noEmit
```
Expected: all green (or pre-existing failures documented; do not claim green without evidence).

- [ ] **Step 4: Manual sandbox E2E (required before calling complete)**

With `VERIFUND_MODE=sandbox`, control plane, seller runtime, and console running:
1. Open `/seller/onboarding` as a new business seller → redirected to `/seller/onboarding/profile`.
2. Save display name → `/seller/onboarding/verification`.
3. Submit verification → status becomes verified (sandbox auto-approve), CTA continues to agent setup.
4. Complete `integrations` → `agent_setup` → `policies` → `testing` → `activation` (verified gate satisfied).
5. Confirm `/seller/agent` loads for verified seller.

- [ ] **Step 5: Commit final polish**

```bash
git add -A
git commit -m "test(onboarding): cover profile and verification MVP flow"
```

(Only if there are actual staged changes; otherwise skip.)

## Self-Review Checklist (executor)

- Spec coverage: profile save+advance, verification submit + sandbox auto-approve, console profile/verification pages+actions, routing/CTAs, sandbox-only gating, non-sandbox pending path, auth/tenancy, tests/E2E.
- Placeholder scan: confirm no `TBD`/`TODO`/“handle edge cases” without code remains in the plan.
- Type/signature consistency: `submit_verification(..., auto_approve_sandbox=...)`, `save_profile_and_continue(...)`, `update_seller_display_name(...)`, action names `saveProfileAction`/`submitVerificationAction`, routes `/v1/seller/onboarding/profile` and `/v1/seller/verification/submit`.
- If `Settings` sandbox validation makes the `mode="sandbox"` test fixture impractical in your environment, use the documented fallback (fake mode + `app.state.settings.is_sandbox=True` stub for the specific test) without weakening the production gate (production always uses real `settings.is_sandbox`).
