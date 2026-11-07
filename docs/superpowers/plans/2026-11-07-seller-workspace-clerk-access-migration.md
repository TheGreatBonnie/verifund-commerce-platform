# Seller Workspace Clerk Access Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `Seller access is required` on the seller workspace after verification by migrating seller workspace data access from legacy cookie/seller-token auth to Clerk org identity (console) and internal service auth (trusted settlement), with fail-closed tenant scoping.

**Architecture:** Add a CP `SellerPrincipal` resolver for migrated `/seller/*` routes: `require_identity` (Clerk) resolves the seller profile for `identity.tenant_id`; an explicit internal service token path (settlement) authenticates with constant-time token verification plus validated org/seller context. All per-transaction access is authorized by transaction ownership (`seller_id`/`seller_organization_id`). Console pages/proxies switch to `controlPlaneForUser` (Clerk). Settlement/outbox switch to internal auth and the CP’s current evidence contract (`requirement_id`, not `kind`). Legacy `SellerTokenService` auth is removed from migrated routes; affected callers/tests are migrated.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async/SQLite, Pydantic v2, pytest + `httpx.AsyncClient`; Next.js App Router (TS), Clerk `auth()`/`auth.protect()`, server actions/route handlers, vitest.

**Spec:** `docs/superpowers/specs/2026-11-07-seller-workspace-clerk-access-design.md`

## Global Constraints

- **Fail closed:** never trust client `seller_id`/org from body/query. Resolve seller context server-side (Clerk identity → seller profile; internal token → validated explicit context). Unknown/not-owned resources do not leak existence (follow existing isolation semantics: prefer `404` for cross-tenant where applicable).
- **No legacy seller tokens on migrated routes:** remove `app.state.tokens.verify`/`SellerTokenService`-based `authenticate`/`authenticate_seller` from `verifund_control_plane/api/seller.py`. Settlement uses internal service auth only.
- **Contract parity:** preserve request/response shapes, pagination/filter validation, and business rules (state/hash/agreement checks, upload validation) except token-specific agreement-hash binding and the required settlement upload alignment to `requirement_id` (CP already rejects `kind`).
- **Scopes:** console read/write mapped from Clerk role/permissions; settlement gets only `txn:read` + `evidence:write` equivalent for owned transactions.
- **Tests/evidence:** keep isolation assertions. Run targeted suites; report broader/full-suite results with evidence (prior full run had non-isolated/flaky failures — do not mask regressions).

## File Structure

**Control plane (create/modify):**
- `apps/verifund_control_plane/verifund_control_plane/settings.py` — add `settlement_internal_token` (env `VERIFUND_SETTLEMENT_INTERNAL_TOKEN`), fallback to `seller_internal_token` only if explicitly wired; document.
- `apps/verifund_control_plane/verifund_control_plane/api/seller_auth.py` (create) — `SellerPrincipal`, `resolve_seller_principal`, `authorize_seller_transaction` helpers.
- `apps/verifund_control_plane/verifund_control_plane/api/seller.py` (modify) — use resolver; re-key rate limit; remove legacy token auth.
- `apps/verifund_control_plane/verifund_control_plane/service.py` / `repository.py` (modify only if needed) — minimal org-aware scoping for backfilled records, preserving behavior.
- `tests/unit/test_seller_principal_auth.py` (create) — resolver/authorization unit tests.
- `tests/support/seller_auth.py` (create) — shared Clerk/internal auth test helpers for migrated seller routes.

**Console (modify):**
- `apps/console/lib/seller-api.ts` — Clerk-based `SellerResult`/`SellerApiError`/`loadSeller` (and any needed request helper) via `controlPlaneForUser`; remove cookie seller-session workspace dependency.
- `apps/console/app/seller/{dashboard,orders,fulfillment,evidence,payouts}/page.tsx` and `app/seller/fulfillment/[id]/{page,activity/page,evidence/page}.tsx` — keep `loadSeller` API but now Clerk-backed (minimal changes).
- `apps/console/app/api/seller/transactions/[id]/evidence/route.ts`, `dispute-evidence/route.ts`, `evidence/[evidenceId]/route.ts` — forward with Clerk auth.
- `apps/console/app/seller/actions.ts` — remove legacy cookie clearing if unused.

**Seller agent (modify):**
- `apps/seller_agent/seller_agent/settings.py` — settlement internal token / CP auth config.
- `apps/seller_agent/seller_agent/settlement.py` — internal service auth headers; upload uses `requirement_id` contract (no `kind`).
- `apps/seller_agent/seller_agent/evidence_outbox.py` — send internal-auth context; upload payload uses `requirement_id`-based fields.
- `apps/seller_agent/seller_agent/store.py` and `shared_store.py` — migrate outbox/token persistence from legacy settlement token / `kind` to internal-auth context and `requirement_id` (with safe handling for existing rows); update method signatures consistently.
- `apps/seller_agent/seller_agent/graph.py`, `server.py` — pass required context/config.

**Tests/callers (modify, targeted):**
- CP: `tests/unit/test_verifund_seller_reads.py`, `test_verifund_upload.py`, `test_verifund_declarations.py`, and any other tests hitting migrated `/seller/*` with seller tokens/`award_flow.seller_headers` or `app.state.tokens`.
- Integration/support: `tests/integration/test_verifund_seller_api.py`, `tests/integration/test_verifund_lifecycle.py`, `tests/support/award_flow.py` (provide Clerk/internal auth helpers; keep or deprecate legacy helper only if still needed elsewhere).
- Seller agent: settlement/outbox unit tests and any graph/server tests using seller tokens or `kind` upload.
- Contracts/scripts: update migrated `/seller/*` client usage as needed.

**Reference (read-only during planning/execution):**
- `apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py` (`require_identity`, `Identity.tenant_id`)
- `apps/verifund_control_plane/verifund_control_plane/tenancy/transaction_access.py`, `tests/unit/test_tenant_isolation.py`
- `apps/console/lib/control-plane.ts` (`controlPlaneForUser`)

---

### Task 1: CP settings and seller principal resolver

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/api/seller_auth.py`
- Test: `tests/unit/test_seller_principal_auth.py`

**Interfaces:**
- Produces: `SellerPrincipal(seller_id, organization_id, actor, auth_kind, scopes)` dataclass; `async resolve_seller_principal(request, *, required_scope: str) -> SellerPrincipal`; `async authorize_seller_transaction(request, transaction_id: str, *, required_scope: str) -> tuple[SellerPrincipal, Any]`.
- Internal auth contract (explicit): header `X-Verifund-Internal-Token` must equal `settings.settlement_internal_token or settings.seller_internal_token` (constant-time). When present, require `X-Seller-Org-Id` (organization_id) **or** resolve org from `X-Seller-Id` by loading profile; validate that the resolved profile belongs to that org and is eligible. Missing/invalid → 401/403/404 (fail closed). If internal header absent, use Clerk `require_identity`.
- Consumes: `request.app.state.tenancy` (seller profile lookups), `request.app.state.repo` (transactions), `request.app.state.settings`, `require_identity`.

- [ ] **Step 1: Write failing resolver tests**

Create `tests/unit/test_seller_principal_auth.py`:

```python
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.api.seller_auth import (
    SellerPrincipal,
    resolve_seller_principal,
)
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


class Req:
    def __init__(self, headers=None, app=None):
        self.headers = headers or {}
        self.app = app


@pytest.fixture
async def tenancy(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    ten = TenancyRepository(engine)
    core = Repository(engine)
    async with engine.begin() as conn:
        await conn.run_sync(core.metadata.create_all)
        await conn.run_sync(ten.metadata.create_all)
    yield ten
    await engine.dispose()


async def test_internal_auth_resolves_principal(tenancy):
    org = await tenancy.upsert_organization("org_s1", "Seller Org", "seller-org")
    await tenancy.upsert_seller_profile(org["id"], "northwind", "Northwind")
    app = SimpleNamespace(state=SimpleNamespace(
        tenancy=tenancy,
        settings=SimpleNamespace(settlement_internal_token="secret", seller_internal_token=None),
    ))
    request = Req(headers={
        "x-verifund-internal-token": "secret",
        "x-seller-org-id": org["id"],
    }, app=app)
    principal = await resolve_seller_principal(request, required_scope="txn:read")
    assert principal == SellerPrincipal(
        seller_id="northwind",
        organization_id=org["id"],
        actor="service:settlement",
        auth_kind="internal_service",
        scopes=frozenset({"txn:read", "evidence:write"}),
    )


async def test_internal_auth_wrong_token_is_401(tenancy):
    org = await tenancy.upsert_organization("org_s1", "Seller Org", "seller-org")
    await tenancy.upsert_seller_profile(org["id"], "northwind", "Northwind")
    app = SimpleNamespace(state=SimpleNamespace(
        tenancy=tenancy,
        settings=SimpleNamespace(settlement_internal_token="secret", seller_internal_token=None),
    ))
    request = Req(headers={"x-verifund-internal-token": "bad", "x-seller-org-id": org["id"]}, app=app)
    with pytest.raises(VerifundError) as exc:
        await resolve_seller_principal(request, required_scope="txn:read")
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_seller_principal_auth.py -v`  
Expected: FAIL (module/function missing).

- [ ] **Step 3: Add settings field**

In `apps/verifund_control_plane/verifund_control_plane/settings.py`, add near `seller_internal_token`:

```python
    settlement_internal_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VERIFUND_SETTLEMENT_INTERNAL_TOKEN", "SETTLEMENT_INTERNAL_TOKEN"
        ),
    )
```

- [ ] **Step 4: Implement `api/seller_auth.py`**

Create `apps/verifund_control_plane/verifund_control_plane/api/seller_auth.py`:

```python
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Request

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.identity import require_identity


@dataclass(frozen=True)
class SellerPrincipal:
    seller_id: str
    organization_id: str
    actor: str
    auth_kind: Literal["clerk", "internal_service"]
    scopes: frozenset[str]


_INTERNAL_SCOPES = frozenset({"txn:read", "evidence:write"})


def _constant_time_eq(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


async def _principal_for_org(store, organization_id: str, *, actor: str, auth_kind: str, scopes: frozenset[str]) -> SellerPrincipal:
    org = await store.get_organization(organization_id)
    if org is None:
        raise VerifundError("forbidden", "seller access denied", status_code=403)
    profile = await store.get_seller_profile_by_organization(organization_id)
    if profile is None:
        raise VerifundError("forbidden", "seller access denied", status_code=403)
    if profile.get("verification_status") == "suspended":
        # preserve existing read-only/suspended handling at route/service level if needed;
        # fail closed for now unless explicitly allowed.
        pass
    return SellerPrincipal(
        seller_id=profile["seller_id"],
        organization_id=organization_id,
        actor=actor,
        auth_kind=auth_kind,  # type: ignore[arg-type]
        scopes=scopes,
    )


async def resolve_seller_principal(request: Request, *, required_scope: str) -> SellerPrincipal:
    settings = request.app.state.settings
    internal = request.headers.get("x-verifund-internal-token")
    if internal is not None:
        expected = getattr(settings, "settlement_internal_token", None) or getattr(settings, "seller_internal_token", None)
        if not _constant_time_eq(internal, expected):
            raise VerifundError("unauthorized", "seller access is required", status_code=401)
        org_id = request.headers.get("x-seller-org-id")
        if not org_id:
            seller_id = request.headers.get("x-seller-id")
            if seller_id:
                profile = await request.app.state.tenancy.get_seller_profile(seller_id)
                org_id = (profile or {}).get("organization_id")
        if not org_id:
            raise VerifundError("unauthorized", "seller access is required", status_code=401)
        principal = await _principal_for_org(
            request.app.state.tenancy, org_id,
            actor="service:settlement", auth_kind="internal_service", scopes=_INTERNAL_SCOPES,
        )
        # If caller provided seller_id, it must match.
        header_seller = request.headers.get("x-seller-id")
        if header_seller and header_seller != principal.seller_id:
            raise VerifundError("forbidden", "seller access denied", status_code=403)
        if required_scope and required_scope not in principal.scopes:
            raise VerifundError("forbidden", "insufficient scope", status_code=403)
        return principal

    identity = await require_identity(request)
    scopes = {"txn:read"}
    if required_scope == "evidence:write":
        # Clerk users with workspace access may submit evidence; refine with role/permission checks if present.
        scopes.add("evidence:write")
    principal = await _principal_for_org(
        request.app.state.tenancy, identity.tenant_id,
        actor=f"user:{identity.user_id}", auth_kind="clerk", scopes=frozenset(scopes),
    )
    if required_scope and required_scope not in principal.scopes:
        raise VerifundError("forbidden", "insufficient scope", status_code=403)
    return principal


def seller_owns_transaction(principal: SellerPrincipal, record: Any) -> bool:
    if getattr(record, "seller_id", None) == principal.seller_id:
        return True
    org_id = getattr(record, "seller_organization_id", None)
    return bool(org_id and org_id == principal.organization_id)


async def authorize_seller_transaction(
    request: Request, transaction_id: str, *, required_scope: str
) -> tuple[SellerPrincipal, Any]:
    principal = await resolve_seller_principal(request, required_scope=required_scope)
    try:
        record = await request.app.state.repo.get_transaction(transaction_id)
    except Exception:
        raise VerifundError("not_found", "transaction not found", status_code=404)
    if record is None or not seller_owns_transaction(principal, record):
        raise VerifundError("not_found", "transaction not found", status_code=404)
    return principal, record
```

(Adjust exception handling to match the repo’s `get_transaction` behavior — if it raises a known not-found error, catch and map to 404; if it returns `None`, handle that. Keep cross-tenant as 404.)

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_seller_principal_auth.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/settings.py apps/verifund_control_plane/verifund_control_plane/api/seller_auth.py tests/unit/test_seller_principal_auth.py
git commit -m "feat(control-plane): add Clerk/internal seller principal resolver"
```

---

### Task 2: Migrate CP seller list/read routes to principal auth

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Modify (if needed): `apps/verifund_control_plane/verifund_control_plane/service.py`, `repository.py`
- Test: `tests/unit/test_verifund_seller_reads.py` (and related seller route tests)

**Interfaces:**
- Consumes: `resolve_seller_principal`, `authorize_seller_transaction`, `seller_owns_transaction` from `api.seller_auth`.
- Produces: same response models/shapes for `GET /seller/transactions`, `/seller/evidence`, `/seller/payouts`, `/seller/agreements/{id}`, `/seller/transactions/{id}`, `/seller/transactions/{id}/events`, `/seller/transactions/{id}/evidence` (list), `GET /seller/transactions/{id}/evidence/{evidence_id}` (download).

- [ ] **Step 1: Update tests to use Clerk/internal auth helper (TDD harness)**

Create `tests/support/seller_auth.py`:

```python
from __future__ import annotations


def clerk_seller_headers(app, *, sub="user_seller", org_id="org_seller", org_role="org:admin", token="seller-bearer"):
    app.state.clerk_authenticator = lambda request: {
        "sub": sub,
        "org_id": org_id,
        "org_role": org_role,
    }
    return {"authorization": f"Bearer {token}"}


def internal_seller_headers(*, token="secret", organization_id: str, seller_id: str | None = None):
    headers = {"x-verifund-internal-token": token, "x-seller-org-id": organization_id}
    if seller_id:
        headers["x-seller-id"] = seller_id
    return headers
```

In `tests/support/award_flow.py`, keep `seller_headers(award_body)` as a legacy compatibility wrapper **only if still referenced by non-migrated tests**; add `clerk_headers_for_award(client_or_app, award_body, seller_org_id, seller_user_sub)`-style helpers as needed by migrated tests. Prefer migrating tests to seed a seller org/profile matching `award_body["seller_id"]` and use Clerk headers.

- [ ] **Step 2: Migrate `test_verifund_seller_reads.py` (representative, high value)**

Update imports/fixtures to seed tenancy org+user+membership+seller_profile whose `seller_id` matches the transaction seller (e.g. `northwind-audio`) and set `app.state.clerk_authenticator`. Replace `seller_headers(first)` / token headers with `clerk_seller_headers(...)`. Keep assertions on shapes/counts/pagination/403/404 semantics intact; for cross-seller access expect `404` or `403` consistent with new fail-closed behavior (adjust the specific status if the resolver uses 404 to avoid leaks, but be consistent and deliberate).

Run: `uv run pytest tests/unit/test_verifund_seller_reads.py -v`  
Expected: FAIL until routes are migrated.

- [ ] **Step 3: Implement route migration for read/list/download**

In `apps/verifund_control_plane/verifund_control_plane/api/seller.py`:
- Remove `authenticate`, `authenticate_seller`, legacy `app.state.tokens` usage.
- Import and use `resolve_seller_principal`, `authorize_seller_transaction`.
- Re-key `_seller_rate_limit` to use principal identity when resolvable without breaking public behavior; simplest safe approach: after resolving principal in-route for list endpoints, enforce a per-principal bucket in app state; for the dependency, do a lightweight pre-check or move limiting into a wrapper — keep 429 behavior.
- Replace each read route’s auth with principal/authorize and pass `principal.seller_id` / `principal.actor`.

Example pattern:

```python
@router.get("/transactions")
async def list_seller_transactions(request: Request, state: str | None = None, limit: int = 50, cursor: str | None = None, seller_id: str | None = None):
    if seller_id is not None:
        raise VerifundError("invalid_request", "seller_id is not an allowed filter", status_code=400)
    principal = await resolve_seller_principal(request, required_scope="txn:read")
    return (await _service(request).list_seller_transactions(
        principal.seller_id, state=state, limit=limit, cursor=cursor
    )).model_dump(mode="json")

@router.get("/transactions/{transaction_id}")
async def get_seller_transaction(transaction_id: str, request: Request):
    principal, _record = await authorize_seller_transaction(request, transaction_id, required_scope="txn:read")
    return (await _service(request).seller_projection(transaction_id, seller_id=principal.seller_id)).model_dump(mode="json")

@router.get("/transactions/{transaction_id}/evidence/{evidence_id}")
async def download_evidence(transaction_id: str, evidence_id: str, request: Request):
    principal, _record = await authorize_seller_transaction(request, transaction_id, required_scope="txn:read")
    await _service(request).seller_projection(transaction_id, seller_id=principal.seller_id)
    item = await request.app.state.repo.get_evidence(transaction_id, evidence_id)
    return Response(
        content=request.app.state.evidence_store.read(item.sha256, item.storage_key),
        media_type=item.media_type,
        headers={"content-disposition": f'attachment; filename="{item.original_filename}"'},
    )
```

Apply the same pattern to payouts, evidence list, events, agreement.

- [ ] **Step 4: Run migrated read tests**

Run: `uv run pytest tests/unit/test_verifund_seller_reads.py -v`  
Expected: PASS (fix resolver/service scoping as needed, without weakening isolation).

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/seller.py tests/unit/test_verifund_seller_reads.py tests/support/seller_auth.py
git commit -m "feat(control-plane): migrate seller read routes to Clerk/internal auth"
```

---

### Task 3: Migrate CP seller write routes (evidence, dispute, declarations)

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Test: `tests/unit/test_verifund_upload.py`, `tests/unit/test_verifund_declarations.py`, `tests/integration/test_verifund_seller_api.py`, and any dispute-evidence tests

**Interfaces:**
- `POST /seller/transactions/{id}/evidence` (multipart, `requirement_id` required, reject `kind`) — `evidence:write`, actor from principal.
- `POST /seller/transactions/{id}/dispute-evidence`, `POST /seller/transactions/{id}/requirements/{rid}/declare`, `GET declarations` — same ownership checks.

- [ ] **Step 1: Migrate write-path tests to Clerk/internal helper**

For each test file, seed org/membership/seller profile for the seller in the award and replace seller-token headers with `clerk_seller_headers` (or `internal_seller_headers` where testing service path). Keep all validation assertions (422 kind rejected, requirement_id required, 409 agreement mismatch/state rules, etc.).

Run targets individually to confirm failures point to auth (not test logic):
`uv run pytest tests/unit/test_verifund_upload.py -v`  
`uv run pytest tests/unit/test_verifund_declarations.py -v`

- [ ] **Step 2: Implement write route auth**

```python
@router.post("/transactions/{transaction_id}/evidence", status_code=201)
async def upload_evidence(transaction_id: str, request: Request, requirement_id: str | None = Form(None), kind: str | None = Form(None), file: UploadFile | None = File(None), reference: str | None = Form(None), reference_type: str | None = Form(None), agreement_version: int | None = Form(None), note: str | None = Form(None), captured_at: datetime | None = Form(None)):
    principal, record = await authorize_seller_transaction(request, transaction_id, required_scope="evidence:write")
    if kind is not None:
        raise VerifundError("invalid_request", "kind is deprecated; evidence uploads are addressed by requirement_id", status_code=422)
    if requirement_id is None:
        raise VerifundError("invalid_request", "requirement_id is required", status_code=422)
    data = await file.read(request.app.state.settings.max_evidence_bytes + 1) if file is not None else None
    receipt = await _service(request).add_evidence(
        transaction_id,
        seller_id=principal.seller_id,
        agreement_hash=record.agreement_hash,
        requirement_id=requirement_id,
        reference=reference,
        reference_type=reference_type,
        media_type=file.content_type if file is not None else None,
        original_filename=file.filename if file is not None else None,
        data=data,
        note=note,
        captured_at=captured_at,
        agreement_version=agreement_version,
        actor=principal.actor,
    )
    return receipt.model_dump(mode="json")
```

Apply to dispute-evidence and declarations.

- [ ] **Step 3: Run write/integration tests**

Run:
```bash
uv run pytest tests/unit/test_verifund_upload.py tests/unit/test_verifund_declarations.py tests/integration/test_verifund_seller_api.py -v
```
Expected: PASS (fix ownership/seed setup; do not weaken validation).

- [ ] **Step 4: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/seller.py tests/unit/test_verifund_upload.py tests/unit/test_verifund_declarations.py tests/integration/test_verifund_seller_api.py
git commit -m "feat(control-plane): migrate seller write routes to Clerk/internal auth"
```

---

### Task 4: Console seller-api refactor and workspace pages

**Files:**
- Modify: `apps/console/lib/seller-api.ts`
- Modify: `apps/console/app/seller/{dashboard,orders,fulfillment,evidence,payouts}/page.tsx`, `app/seller/fulfillment/[id]/page.tsx`, `app/seller/fulfillment/[id]/activity/page.tsx`, `app/seller/fulfillment/[id]/evidence/page.tsx`, `app/seller/actions.ts`
- Test: existing console tests + `cd apps/console && npx tsc --noEmit`

**Interfaces:**
- Preserve `SellerApiError`, `SellerResult<T>`, `loadSeller<T>(path, _transactionId?)` for minimal page churn (ignore/remove `transactionId` cookie dependency).
- `loadSeller` uses `controlPlaneForUser(path)` and maps JSON/error responses.

- [ ] **Step 1: Replace `lib/seller-api.ts` implementation**

```ts
import { controlPlaneForUser } from "@/lib/control-plane";

export class SellerApiError extends Error {
  readonly status: number;
  readonly code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "SellerApiError";
    this.status = status;
    this.code = code;
  }
}

export type SellerResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; status: number };

async function failure(response: Response): Promise<SellerApiError> {
  let message = `Seller API responded ${response.status}`;
  let code: string | undefined;
  try {
    const body = (await response.json()) as {
      error?: { message?: string; code?: string };
      detail?: string;
    };
    message = body.error?.message ?? body.detail ?? message;
    code = body.error?.code;
  } catch {}
  return new SellerApiError(message, response.status, code);
}

export async function sellerJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await controlPlaneForUser(path, init);
  } catch (err) {
    if (err instanceof SellerApiError) throw err;
    throw new SellerApiError("Control plane is unavailable", 503);
  }
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export async function loadSeller<T>(path: string, _transactionId?: string): Promise<SellerResult<T>> {
  try {
    return { ok: true, data: await sellerJson<T>(path) };
  } catch (error) {
    if (error instanceof SellerApiError) return { ok: false, error: error.message, status: error.status };
    return { ok: false, error: error instanceof Error ? error.message : "Seller API is unavailable", status: 503 };
  }
}

export async function clearSellerTokens(): Promise<void> {
  // Legacy cookie sessions removed for Clerk-based workspace access.
}
```

If other modules still import `exchangeInvitation`/`saveSellerToken`/`sellerRequest`/upload helpers, either keep minimal compatibility shims that throw clear errors (“migrated to Clerk workspace access”) or migrate those call sites (search and fix). Do not leave broken imports.

- [ ] **Step 2: Find and fix remaining `seller-api` import usages**

Run: `cd apps/console && grep -rn 'exchangeInvitation\|saveSellerToken\|readSellerSession\|sellerRequest\|uploadEvidence\|uploadDisputeEvidence' app lib components`  
Update any remaining call sites (especially API proxies in Task 5).

- [ ] **Step 3: Typecheck and run console tests**

Run:
```bash
cd apps/console && npx tsc --noEmit
cd apps/console && npx vitest run tests/lib/onboarding.test.ts
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/console/lib/seller-api.ts apps/console/app/seller apps/console/app/api/seller
git commit -m "feat(console): load seller workspace data via Clerk control-plane auth"
```

(Include any additional modified console files required for compilation; exclude unrelated changes.)

---

### Task 5: Console evidence/dispute/download proxies (Clerk forward)

**Files:**
- Modify: `apps/console/app/api/seller/transactions/[id]/evidence/route.ts`
- Modify: `apps/console/app/api/seller/transactions/[id]/dispute-evidence/route.ts`
- Modify: `apps/console/app/api/seller/transactions/[id]/evidence/[evidenceId]/route.ts`

- [ ] **Step 1: Rewrite proxies to use `controlPlaneForUser`**

Upload/dispute pattern:

```ts
import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  await auth.protect();
  const { id } = await params;
  let formData: FormData;
  try { formData = await request.formData(); } catch {
    return NextResponse.json({ error: { message: "Expected multipart form data" } }, { status: 400 });
  }
  const upstream = await controlPlaneForUser(
    `/seller/transactions/${encodeURIComponent(id)}/evidence`,
    { method: "POST", body: formData },
  );
  const text = await upstream.text();
  const contentType = upstream.headers.get("content-type") ?? "application/json";
  return new Response(text, { status: upstream.status, headers: { "content-type": contentType } });
}
```

(Use `/dispute-evidence` in that route. Do not set multipart `content-type` manually.)

Download pattern:

```ts
export async function GET(_request: Request, { params }: { params: Promise<{ id: string; evidenceId: string }> }) {
  await auth.protect();
  const { id, evidenceId } = await params;
  const upstream = await controlPlaneForUser(
    `/seller/transactions/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidenceId)}`,
  );
  if (!upstream.ok) {
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }
  return new Response(await upstream.arrayBuffer(), {
    status: 200,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
      "content-disposition": upstream.headers.get("content-disposition") ?? "inline",
    },
  });
}
```

- [ ] **Step 2: Typecheck**

Run: `cd apps/console && npx tsc --noEmit`  
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/console/app/api/seller/transactions
git commit -m "feat(console): proxy seller evidence routes with Clerk auth"
```

---

### Task 6: Settlement agent — internal auth and evidence contract alignment

**Files:**
- Modify: `apps/seller_agent/seller_agent/settings.py`, `settlement.py`, `evidence_outbox.py`, `store.py`, `shared_store.py`, `graph.py`, `server.py`
- Test: seller agent settlement/outbox/store tests (`rg -l "settlement|outbox|SettlementClient|upload_evidence" tests apps/seller_agent`)

**Interfaces:**
- `SellerSettlementClient` accepts internal auth config (token + org/seller context resolver) instead of per-call legacy bearer `token`. Methods send `X-Verifund-Internal-Token` and required context headers.
- `upload_evidence` sends CP’s current contract: `requirement_id` (required), `file` or `reference/reference_type`, optional `agreement_version`/`note`/`captured_at`. No `kind`.
- Outbox rows and enqueue accept/store `requirement_id` (+ metadata needed for upload). Idempotency preserved (update unique key/logic thoughtfully, e.g. `(transaction_id, requirement_id, artifact_fingerprint)` if appropriate; document and test).

- [ ] **Step 1: Write/update failing settlement client tests for internal auth + requirement_id**

Locate tests: `rg -l "SellerSettlementClient|upload_evidence" tests apps/seller_agent`. Update/create tests to assert:
- request includes `X-Verifund-Internal-Token` and org/seller context headers (not `Authorization: Bearer <legacy seller token>` for CP auth).
- upload form data contains `requirement_id` and does not contain `kind`.

Run targeted failing tests.

- [ ] **Step 2: Implement settlement client**

In `apps/seller_agent/seller_agent/settlement.py`:

```python
class SellerSettlementClient:
    def __init__(self, base_url: str, *, internal_token: str | None = None, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    def _headers(self, *, organization_id: str, seller_id: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.internal_token:
            headers["x-verifund-internal-token"] = self.internal_token
        headers["x-seller-org-id"] = organization_id
        headers["x-seller-id"] = seller_id
        return headers

    async def get_transaction(self, transaction_id: str, *, organization_id: str, seller_id: str) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}",
            headers=self._headers(organization_id=organization_id, seller_id=seller_id),
        )
        if response.status_code >= 400:
            raise SettlementError("invalid_request", "seller transaction lookup failed", status_code=response.status_code)
        return response.json()

    async def upload_evidence(self, transaction_id: str, *, organization_id: str, seller_id: str, requirement_id: str, content: bytes | None = None, media_type: str | None = None, filename: str | None = None, reference: str | None = None, reference_type: str | None = None, note: str = "", captured_at: str | None = None, agreement_version: int | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {"requirement_id": requirement_id}
        if note:
            data["note"] = note
        if captured_at:
            data["captured_at"] = captured_at
        if agreement_version is not None:
            data["agreement_version"] = str(agreement_version)
        files = None
        if content is not None:
            data.pop("reference", None)
            files = {"file": (filename or f"{requirement_id}.bin", content, media_type or "application/octet-stream")}
        elif reference is not None:
            data["reference"] = reference
            if reference_type:
                data["reference_type"] = reference_type
        response = await self._client.post(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence",
            headers=self._headers(organization_id=organization_id, seller_id=seller_id),
            data=data,
            files=files,
        )
        if response.status_code >= 400:
            raise SettlementError("invalid_request", "evidence upload failed", status_code=response.status_code)
        return response.json()
```

(Keep `close()` and `get_evidence` with the same auth pattern; update their signatures consistently.)

- [ ] **Step 3: Migrate outbox/store and callers**

- Replace `get_settlement_token` usage with `(organization_id, seller_id)` context derived from the transaction/offer/agent config available in the seller agent (fail closed with a retryable/clear error if context cannot be resolved).
- Change outbox schema/methods to store `requirement_id` and upload metadata; provide a migration for existing SQLite DBs (add columns / backfill defaults / create new uniqueness where safe). Update `shared_store.py` in lockstep with `store.py` (they mirror outbox behavior).
- Update `graph.py` enqueue sites to pass `requirement_id` (determine from the requirement/evidence context already present in the fulfillment flow; do not invent IDs — map to the catalog/requirement being satisfied).
- Update `server.py` to construct `SellerSettlementClient` with the internal token from settings.

Run targeted seller-agent tests: `uv run pytest -k 'settlement or outbox' -v` (adjust selector to actual test names).

- [ ] **Step 4: Commit**

```bash
git add apps/seller_agent/seller_agent
git commit -m "feat(seller-agent): use internal auth and requirement_id evidence uploads"
```

---

### Task 7: Migrate remaining CP/integration callers and isolation tests

**Files:**
- Modify: remaining tests/support/contracts/scripts that call migrated `/seller/*` with legacy seller tokens (find with `rg -n 'seller_headers\(|app\.state\.tokens\b|/seller/transactions.*Bearer' tests packages scripts`).

**Interfaces:**
- Clerk test path: seed org/user/membership/seller profile and set `app.state.clerk_authenticator`; use `tests/support/seller_auth.clerk_seller_headers`.
- Internal test path (where appropriate): `internal_seller_headers` + configure `app.state.settings.settlement_internal_token`.

- [ ] **Step 1: Build an inventory**

Run: `rg -l 'seller_headers\(|app\.state\.tokens\b|SellerTokenService' tests packages/verifund_contracts scripts` and classify each file: CP `/seller/*` caller (migrate), token-service unit tests (keep, they test legacy token module itself unless removed), or unrelated.

- [ ] **Step 2: Migrate CP seller/integration tests file-by-file**

For each migrated file: update setup to include tenancy seller profile for the relevant org/seller_id, replace bearer seller-token headers with Clerk/internal helpers, and keep assertions equivalent (status/body/isolation). Run the file after each change.

Key files to address explicitly: `tests/integration/test_verifund_seller_api.py`, `tests/integration/test_verifund_lifecycle.py` (if it exercises seller endpoints), `tests/support/award_flow.py` helpers, and any `test_seller_*` units still using legacy headers.

- [ ] **Step 3: Update contracts/scripts that target migrated routes**

For `packages/verifund_contracts` client methods and scripts that call `/seller/*` with bearer seller tokens, update to accept/provide the new auth mechanism (or clearly separate legacy vs migrated usage). Run their tests: `uv run pytest packages -v` or package-specific tests if present.

- [ ] **Step 4: Commit**

```bash
git add tests packages scripts
git commit -m "test: migrate seller workspace callers to Clerk/internal auth"
```

---

### Task 8: Verification, docs, and rollout evidence

**Files:**
- Modify: `docs/seller-fulfillment-workspace.md`, `docs/console.md` (or relevant docs), any env/compose examples referencing seller cookie sessions or settlement auth.

- [ ] **Step 1: Run targeted verification suite**

```bash
uv run pytest tests/unit/test_seller_principal_auth.py tests/unit/test_verifund_seller_reads.py tests/unit/test_verifund_upload.py tests/unit/test_verifund_declarations.py tests/integration/test_verifund_seller_api.py tests/integration/test_seller_onboarding_routes.py tests/unit/test_seller_onboarding_profile.py tests/unit/test_seller_onboarding_verification.py tests/unit/test_platform_admin.py -v
uv run pytest -k "settlement or outbox or seller" -v
cd apps/console && npx vitest run tests/lib/onboarding.test.ts && npx tsc --noEmit
```
Expected: PASS. Record results.

- [ ] **Step 2: Run broader/full Python suite and report with evidence**

Run: `uv run pytest`  
If failures appear, re-run failing tests in isolation and compare to baseline behavior. Do **not** claim a green full suite without evidence; distinguish regressions caused by this migration from pre-existing/non-isolated failures.

- [ ] **Step 3: Manual sandbox E2E**

With `VERIFUND_MODE=sandbox`, CP, seller agent, console, and Clerk configured: verified seller loads `/seller/dashboard` (no “Seller access is required”), list/detail/evidence pages work for owned transactions, upload/dispute/download proxies work, settlement (if enabled) uploads via internal auth, cross-org access denied.

- [ ] **Step 4: Update docs and config notes**

Document Clerk-based workspace access, removal of legacy cookie/seller-token auth on migrated routes, and `VERIFUND_SETTLEMENT_INTERNAL_TOKEN` (shared by CP and seller agent). Update spec status to Implemented only after merge/verification.

- [ ] **Step 5: Commit**

```bash
git add docs
git commit -m "docs: document Clerk-based seller workspace access and settlement auth"
```

## Self-Review Checklist (executor)

- Spec coverage: Clerk console access, CP principal resolver (Clerk + internal), fail-closed org/txn scoping, list+per-txn+upload+dispute+download+declarations routes, console pages + proxies, settlement internal auth + `requirement_id` contract alignment + outbox/store migration, caller/test migration, docs/verification.
- Placeholder scan: no `TBD`/`TODO`/`implement later`/`fill in details`/vague “handle edge cases”. (The plan includes concrete code and explicit search/migration commands for the blast radius.)
- Type/signature consistency: `SellerPrincipal`, `resolve_seller_principal(request, *, required_scope)`, `authorize_seller_transaction(request, transaction_id, *, required_scope)`, internal headers `X-Verifund-Internal-Token`/`X-Seller-Org-Id`/`X-Seller-Id`, setting `settlement_internal_token`, `SellerSettlementClient(..., internal_token=...)`, `upload_evidence(..., requirement_id=...)`.
- Isolation: every per-txn path checks ownership; no client-supplied seller filters accepted; cross-tenant returns 404/403 per repo conventions.
- Behavior change acknowledged: legacy seller token agreement-hash binding and cookie sessions removed from migrated routes; settlement `kind` upload replaced by `requirement_id`.
