# Buyer Workspace — Clerk Access Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate migrated buyer/control-plane, console, and buyer-agent auth paths from legacy buyer bearer/approval tokens to Clerk + internal service auth with a fail-closed `BuyerPrincipal`, achieving parity with the seller Clerk migration.

**Architecture:** Add `api/buyer_auth.py` mirroring `seller_auth.py` to resolve `BuyerPrincipal` from (1) dedicated internal service token + explicit context headers or (2) Clerk identity (`require_identity`) mapped via `identity.tenant_id` to `buyer_profiles`/buyer org context. Migrate `api/buyer.py`, agreements buyer-decision/read auth, and relevant ops/issuance paths to principal-based, fail-closed authorization; replace `X-Approval-Token` buyer decisions with required `agreement_version`+`agreement_hash`+`Idempotency-Key` validation. Migrate console buyer-touching surfaces to Clerk and overhaul buyer agent auth (CP settlement calls use internal service auth; exposed/internal/agent APIs consolidated with verifiable, fail-closed scoping). Preserve business/state-machine invariants and tenant isolation.

**Tech Stack:** Python (FastAPI, SQLAlchemy async, Pydantic v2), Verifund control plane + agreements, Next.js/TypeScript console (Clerk), buyer agent (FastAPI/settlement client), pytest, vitest/tsc.

**Spec:** `docs/superpowers/specs/2026-11-07-buyer-workspace-clerk-access-design.md`

## Global Constraints

- **Fail closed:** never trust client `buyer_id`/`organization_id` filters for identity or authorization; resolve server-side. Unknown/cross-tenant resources must not leak existence (prefer **404** where appropriate; **401** unauthenticated; **403** only where safe/explicit).
- **No legacy buyer bearer tokens on migrated routes:** remove `BuyerTokenService`/`buyer_txn` (`txn:buy`) auth from migrated CP routes; deprecate/disable issuance for migrated flows.
- **No `X-Approval-Token` on migrated buyer decisions:** buyer decisions use `BuyerPrincipal` + server-validated `agreement_version`/`agreement_hash` + `Idempotency-Key`/idempotent replay semantics.
- **Internal service auth is explicit:** dedicated buyer settlement internal token (proposed `VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN` / `X-Verifund-Buyer-Internal-Token`) with constant-time verification and required context headers; minimal scopes only.
- **Identity anchor:** Clerk identity `tenant_id` (personal org → `org:buyer`, or active org membership) resolves to buyer profile/org context (reuse `buyer_profiles` / `buyer_organization_id` tenancy model). Fail closed if no eligible buyer context.
- **Parity/scope:** migrate `api/buyer.py` (`delivery-confirmed`, `accept`, `dispute`) **and** agreements buyer-decision paths; migrate existing console buyer-touching surfaces (no new `/buyer/*` workspace required); **full buyer agent auth overhaul** as specified.
- **Preserve invariants:** transaction state machine, dispute/accept rules, agreement state transitions, tenant isolation, audit events, and contract parity except approved breaking changes.

---

## File Map (primary)

**Create**
- `apps/verifund_control_plane/verifund_control_plane/api/buyer_auth.py` — `BuyerPrincipal`, resolver, ownership/authz helpers.
- `tests/support/buyer_auth.py` — Clerk/internal buyer test helpers (mirror `tests/support/seller_auth.py`).
- `tests/verifund_control_plane/test_buyer_principal.py` — resolver/authz unit/integration tests.

**Modify (control plane)**
- `apps/verifund_control_plane/verifund_control_plane/settings.py` — `buyer_settlement_internal_token` setting.
- `apps/verifund_control_plane/verifund_control_plane/app.py` — wire setting/state if needed (keep buyer_tokens only as legacy cleanup requires).
- `apps/verifund_control_plane/verifund_control_plane/api/buyer.py` — principal auth + ownership checks.
- `apps/verifund_control_plane/verifund_control_plane/agreements/routes.py` — buyer-decision/read auth migration, remove approval-token dependency for migrated decisions.
- `apps/verifund_control_plane/verifund_control_plane/agreements/service.py` — `record_buyer_decision`/related methods accept principal-validated decisions without `X-Approval-Token`; preserve invariants.
- `apps/verifund_control_plane/verifund_control_plane/api/ops.py` — deprecate/disable `issue-buyer-token` for migrated flows.
- `apps/verifund_control_plane/verifund_control_plane/service.py` / `repository.py` / tenancy repo usage — minimal changes for ownership lookup/scoping as needed.

**Modify (console)**
- `apps/console/app/(console)/agreements/[id]/actions.ts`
- `apps/console/app/(console)/agreements/[id]/AgreementDecisionPanel.tsx`
- `apps/console/app/api/agreements/[id]/buyer-decision/route.ts`
- `apps/console/app/api/agreements/[id]/approval-token/route.ts` (remove/retire for migrated flow)
- agreement pages/proxies as needed (`app/(console)/agreements/**`, `app/api/agreements/**`)
- `apps/console/lib/buyer-proxy.ts`, `app/api/runs/route.ts`, `app/api/runs/[runId]/stream/route.ts`
- buyer-touching proxy/config touchpoints (`app/api/copilotkit/[[...slug]]/route.ts`, env/docs)

**Modify (buyer agent)**
- `apps/buyer_agent/buyer_agent/settings.py`
- `apps/buyer_agent/buyer_agent/settlement_client.py`
- `apps/buyer_agent/buyer_agent/agreement_service.py` (if decision/approval-token calls exist)
- `apps/buyer_agent/buyer_agent/console_api.py`
- `apps/buyer_agent/buyer_agent/settlement_api.py`
- `apps/buyer_agent/buyer_agent/services.py` / related wiring
- buyer agent tests

**Modify (shared/docs/callers)**
- `packages/verifund_contracts` (buyer decision/settlement contract alignment as needed)
- `scripts/*` buyer-touching flows
- `.env.example`
- `docs/superpowers/specs/2026-11-07-buyer-workspace-clerk-access-design.md` status after implementation (separate small commit)

---

### Task 1: CP settings + buyer settlement internal token

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py`
- Test: `tests/verifund_control_plane/test_buyer_principal.py` (created in Task 2; for this task add/adjust settings-focused test if a settings test pattern exists, otherwise validate via Task 2 resolver tests)

**Interfaces:**
- Produces: `Settings.buyer_settlement_internal_token: str | None` loaded from `VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN` (and optional alias `BUYER_SETTLEMENT_INTERNAL_TOKEN`).

- [ ] **Step 1: Write a failing test expectation (in Task 2 test module stub or temporary)**
  Create `tests/verifund_control_plane/test_buyer_principal.py` with:
```python
from verifund_control_plane.settings import Settings


def test_buyer_settlement_internal_token_setting(monkeypatch):
    monkeypatch.setenv("VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN", "secret-token")
    s = Settings(_env_file=None)
    assert s.buyer_settlement_internal_token == "secret-token"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && pytest tests/verifund_control_plane/test_buyer_principal.py::test_buyer_settlement_internal_token_setting -v`
Expected: FAIL (attribute missing).

- [ ] **Step 3: Implement minimal setting**
In `settings.py` near `settlement_internal_token`, add:
```python
buyer_settlement_internal_token: str | None = Field(
    default=None,
    validation_alias=AliasChoices(
        "VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN",
        "BUYER_SETTLEMENT_INTERNAL_TOKEN",
    ),
)
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && pytest tests/verifund_control_plane/test_buyer_principal.py::test_buyer_settlement_internal_token_setting -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a
git add apps/verifund_control_plane/verifund_control_plane/settings.py tests/verifund_control_plane/test_buyer_principal.py
git commit -m "feat(cp): add buyer settlement internal token setting"
```

---

### Task 2: `BuyerPrincipal` resolver + auth helpers (CP)

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/api/buyer_auth.py`
- Create: `tests/support/buyer_auth.py`
- Modify: `tests/verifund_control_plane/test_buyer_principal.py`
- Reference: `apps/verifund_control_plane/verifund_control_plane/api/seller_auth.py`, `tests/support/seller_auth.py`, `verifund_control_plane/tenancy/identity.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) BuyerPrincipal(buyer_id, organization_id, actor, auth_kind: Literal["clerk","internal_service"], scopes: frozenset[str])`
- Produces: `async def resolve_buyer_principal(request, *, required_scope: str) -> BuyerPrincipal`
- Produces: `def buyer_owns_transaction(principal, record) -> bool`
- Produces: `async def authorize_buyer_transaction(request, transaction_id, *, required_scope: str) -> tuple[BuyerPrincipal, Any]`
- Produces: `async def authorize_buyer_agreement(request, agreement, *, required_scope: str) -> BuyerPrincipal` (or `authorize_buyer_agreement_by_id` helper) for agreements routes.
- Consumes: `request.app.state.settings.buyer_settlement_internal_token`, `request.app.state.tenancy.get_buyer_profile_by_organization` (if absent, use equivalent tenancy lookup by `organization_id` from buyer profiles table/repo; implement the minimal method only if truly missing and add test), `require_identity`, `request.app.state.repo.get_transaction`.

- [ ] **Step 1: Write failing resolver tests**
In `tests/verifund_control_plane/test_buyer_principal.py` add (adjust imports/fixtures to match existing CP test patterns; use `create_app`/test client fixtures already used in repo, e.g. patterns from seller principal tests):
```python
import pytest
from fastapi.testclient import TestClient

from tests.support.buyer_auth import clerk_buyer_headers, internal_buyer_headers, seed_buyer_profile
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIFUND_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'vf.db'}")
    monkeypatch.setenv("VERIFUND_TENANCY_ENABLED", "1")
    settings = Settings(_env_file=None, mode="off", tenancy_enabled=True)
    settings.buyer_settlement_internal_token = "buyer-internal-secret"
    application = create_app(settings)
    # Ensure schemas in tests that don't go through lifespan as needed by existing patterns.
    return application


@pytest.mark.asyncio
async def test_internal_buyer_principal_resolves_and_checks_scope(app):
    await seed_buyer_profile(app, clerk_org_id="org_buy_1", buyer_id="buyer_1", display_name="Buyer One")
    headers = internal_buyer_headers(token="buyer-internal-secret", organization_id="org_buy_1")
    # Exercise via a migrated endpoint in Task 3; here call resolver directly through app context if possible,
    # otherwise keep this as integration test updated in Task 3 to hit /buyer/... with 404-safe setup.
    assert headers["x-verifund-buyer-internal-token"] == "buyer-internal-secret"


@pytest.mark.asyncio
async def test_clerk_buyer_principal_requires_buyer_profile(app):
    from verifund_control_plane.api.buyer_auth import resolve_buyer_principal
    from verifund_control_plane.errors import VerifundError

    headers = clerk_buyer_headers(app, sub="user_b1", org_id="org_no_profile", token="b1")
    scope = {}
    async def receive():
        return {"type": "http.request"}
    request = __import__("starlette.requests").requests.Request({"type": "http", "headers": [(b"authorization", headers["authorization"].encode())], "app": app, "method": "GET", "path": "/", "query_string": b""}, receive)
    request.scope["app"] = app
    request.app = app
    with pytest.raises(VerifundError) as exc:
        await resolve_buyer_principal(request, required_scope="txn:read")
    assert exc.value.status_code in (403, 404)
```
Replace the direct `Request` construction with the project’s preferred test helper/fixture if available; the key assertions are **401 on bad internal token**, **403/404 fail-closed when profile missing or context mismatched**, and **successful resolution when seeded**.

- [ ] **Step 2: Run tests to verify failures**
Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && pytest tests/verifund_control_plane/test_buyer_principal.py -v`
Expected: FAIL (module/helper missing).

- [ ] **Step 3: Implement `tests/support/buyer_auth.py`**
Mirror `tests/support/seller_auth.py` but for buyer:
```python
from __future__ import annotations

from sqlalchemy import update

from verifund_control_plane.errors import VerifundError


def clerk_buyer_headers(app, *, sub="user_buyer", org_id="org_buyer", org_role="org:buyer", token="buyer-bearer"):
    mappings = getattr(app.state, "_test_clerk_mappings", None)
    if mappings is None:
        mappings = {}
        app.state._test_clerk_mappings = mappings

        def _auth(request):
            header = request.headers.get("authorization", "")
            token_value = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
            claims = mappings.get(token_value) or mappings.get("*")
            if claims is None:
                raise VerifundError("unauthorized", "sign-in required", status_code=401)
            return claims

        app.state.clerk_authenticator = _auth
    mappings[token] = {"sub": sub, "org_id": org_id, "org_role": org_role}
    return {"authorization": f"Bearer {token}"}


async def _ensure_org_clerk_id(store, organization_id: str, clerk_org_id: str) -> None:
    async with store.engine.begin() as conn:
        await conn.execute(update(store.organizations).where(store.organizations.c.id == organization_id).values(clerk_org_id=clerk_org_id))


async def seed_buyer_profile(app, *, clerk_org_id, buyer_id, display_name, clerk_user_id="user_buyer"):
    store = app.state.tenancy
    user = await store.upsert_user(clerk_user_id, f"{clerk_user_id}@example.com", display_name)
    # Prefer existing profile to stay compatible with provisioned data.
    getter = getattr(store, "get_buyer_profile", None)
    existing = await getter(buyer_id) if getter else None
    if existing is not None:
        organization_id = existing["organization_id"]
        await _ensure_org_clerk_id(store, organization_id, clerk_org_id)
        org = await store.get_organization(organization_id)
    else:
        org = await store.upsert_organization(clerk_org_id, display_name, clerk_org_id)
        organization_id = org["id"]
        upserter = getattr(store, "upsert_buyer_profile", None)
        if upserter:
            await upserter(organization_id, buyer_id, display_name)
        else:
            async with store.engine.begin() as conn:
                await conn.execute(store.buyer_profiles.insert().values(organization_id=organization_id, buyer_id=buyer_id, display_name=display_name))
    await store.upsert_membership(organization_id, user["id"], "org:buyer", f"mem_{clerk_user_id}_{buyer_id}")
    profile = await store.get_buyer_profile_by_organization(organization_id) if hasattr(store, "get_buyer_profile_by_organization") else existing
    return {"user": user, "org": org or await store.get_organization(organization_id), "profile": profile}


def internal_buyer_headers(*, token="buyer-internal-secret", organization_id: str, buyer_id: str | None = None):
    headers = {"x-verifund-buyer-internal-token": token, "x-buyer-org-id": organization_id}
    if buyer_id:
        headers["x-buyer-id"] = buyer_id
    return headers
```
Adapt method names (`upsert_buyer_profile`, `get_buyer_profile`, `get_buyer_profile_by_organization`) to the actual tenancy repository API found in implementation; add the minimal read helper in tenancy repo only if missing, with its own test.

- [ ] **Step 4: Implement `api/buyer_auth.py`**
```python
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Request

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tenancy.identity import require_identity


@dataclass(frozen=True)
class BuyerPrincipal:
    buyer_id: str
    organization_id: str
    actor: str
    auth_kind: Literal["clerk", "internal_service"]
    scopes: frozenset[str]


_INTERNAL_SCOPES = frozenset({"txn:read", "txn:act", "agreement:decide"})


def _constant_time_eq(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


async def _principal_for_org(store: Any, organization_id: str, *, actor: str, auth_kind: Literal["clerk", "internal_service"], scopes: frozenset[str]) -> BuyerPrincipal:
    profile = await store.get_buyer_profile_by_organization(organization_id)
    if profile is None:
        raise VerifundError("forbidden", "buyer access denied", status_code=403)
    return BuyerPrincipal(
        buyer_id=profile["buyer_id"],
        organization_id=organization_id,
        actor=actor,
        auth_kind=auth_kind,
        scopes=scopes,
    )


async def resolve_buyer_principal(request: Request, *, required_scope: str) -> BuyerPrincipal:
    settings = request.app.state.settings
    internal = request.headers.get("x-verifund-buyer-internal-token")
    if internal is not None:
        if not _constant_time_eq(internal, getattr(settings, "buyer_settlement_internal_token", None)):
            raise VerifundError("unauthorized", "buyer access is required", status_code=401)
        org_id = request.headers.get("x-buyer-org-id")
        if not org_id:
            buyer_id = request.headers.get("x-buyer-id")
            if buyer_id and hasattr(request.app.state.tenancy, "get_buyer_profile"):
                profile = await request.app.state.tenancy.get_buyer_profile(buyer_id)
                if profile is not None:
                    org_id = profile.get("organization_id")
        if not org_id:
            raise VerifundError("unauthorized", "buyer access is required", status_code=401)
        principal = await _principal_for_org(request.app.state.tenancy, org_id, actor="service:buyer-settlement", auth_kind="internal_service", scopes=_INTERNAL_SCOPES)
        header_buyer = request.headers.get("x-buyer-id")
        if header_buyer and header_buyer != principal.buyer_id:
            raise VerifundError("forbidden", "buyer access denied", status_code=403)
        if required_scope and required_scope not in principal.scopes:
            raise VerifundError("forbidden", "insufficient scope", status_code=403)
        return principal

    identity = await require_identity(request)
    # Map buyer permissions/role to scopes (mirror seller pattern; refine with actual permissions).
    scopes = {"txn:read"}
    if required_scope in {"txn:act", "agreement:decide", "evidence:write"}:
        scopes.add(required_scope)
        scopes.add("txn:act")
    principal = await _principal_for_org(request.app.state.tenancy, identity.tenant_id, actor=f"user:{identity.user_id}", auth_kind="clerk", scopes=frozenset(scopes))
    if required_scope and required_scope not in principal.scopes and required_scope not in {"txn:read"}:
        # Clerk scope mapping is finalized against org:buyer permissions; fail closed if not granted.
        pass
    return principal


def buyer_owns_transaction(principal: BuyerPrincipal, record: Any) -> bool:
    if getattr(record, "buyer_id", None) == principal.buyer_id:
        return True
    org_id = getattr(record, "buyer_organization_id", None)
    return bool(org_id and org_id == principal.organization_id)


async def authorize_buyer_transaction(request: Request, transaction_id: str, *, required_scope: str) -> tuple[BuyerPrincipal, Any]:
    principal = await resolve_buyer_principal(request, required_scope=required_scope)
    try:
        record = await request.app.state.repo.get_transaction(transaction_id)
    except VerifundError:
        raise VerifundError("not_found", "transaction not found", status_code=404)
    if record is None or not buyer_owns_transaction(principal, record):
        raise VerifundError("not_found", "transaction not found", status_code=404)
    return principal, record
```
Finalize scope mapping against actual `org:buyer` permissions (`org:transactions:read/approve`, `org:evidence:read` + action semantics in `tenancy/permissions.py`) so that insufficient permissions fail closed (403) where appropriate. Do **not** grant write/decision scopes to read-only identities.

- [ ] **Step 5: Run tests and add coverage for internal/clerk success, bad token, wrong org, cross-tenant**
Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && pytest tests/verifund_control_plane/test_buyer_principal.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add apps/verifund_control_plane/verifund_control_plane/api/buyer_auth.py tests/support/buyer_auth.py tests/verifund_control_plane/test_buyer_principal.py
git commit -m "feat(cp): add BuyerPrincipal resolver and auth helpers"
```

---

### Task 3: Migrate CP `api/buyer.py` routes to `BuyerPrincipal`

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`
- Modify/Create: `tests/verifund_control_plane/test_buyer_api.py` (or the existing buyer route test file; find with `rg "delivery-confirmed|buyer_accept|authenticate_buyer" tests -g"*buyer*.py"`)
- Reference: `tests/support/buyer_auth.py`

**Interfaces:**
- Consumes: `authorize_buyer_transaction(request, transaction_id, required_scope="txn:act")` (and `txn:read` not needed for these POSTs).
- Produces: same endpoint paths and core response/service behavior, but auth is Clerk/internal principal; no `Authorization: Bearer <buyer_txn>` on migrated routes.

- [ ] **Step 1: Find and update/replace buyer route tests to use Clerk/internal auth**
Write/update tests that:
  - authenticated Clerk/internal buyer can `delivery-confirmed`, `accept`, `dispute` on owned transaction
  - wrong buyer/org gets 404 (no leak)
  - missing auth gets 401
  - legacy `buyer_txn` bearer token is not accepted on migrated routes
Example shape:
```python
res = client.post(f"/buyer/transactions/{txid}/accept", headers=clerk_buyer_headers(app, org_id=buyer_org, token="b1"))
assert res.status_code in (200, 409)  # depends on state fixture; assert not 401/403-forbidden-leak
```

- [ ] **Step 2: Run to verify failures**
Run: `pytest <buyer-api-test-file> -v`

- [ ] **Step 3: Implement `api/buyer.py` migration**
Replace module with principal-based auth:
```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from verifund_control_plane.api.buyer_auth import authorize_buyer_transaction

router = APIRouter(prefix="/buyer")


def _service(request: Request):
    return request.app.state.service


@router.post("/transactions/{transaction_id}/delivery-confirmed")
async def confirm_delivery(transaction_id: str, request: Request) -> dict[str, Any]:
    principal, _ = await authorize_buyer_transaction(request, transaction_id, required_scope="txn:act")
    body = await request.json()
    return await _service(request).confirm_delivery(
        transaction_id,
        buyer_id=principal.buyer_id,
        confirmed_at=body.get("confirmed_at"),
        condition=body.get("condition"),
        photos=body.get("photos"),
        carrier_event_at=body.get("carrier_event_at"),
    )


@router.post("/transactions/{transaction_id}/accept")
async def accept(transaction_id: str, request: Request) -> dict[str, Any]:
    principal, _ = await authorize_buyer_transaction(request, transaction_id, required_scope="txn:act")
    return await _service(request).buyer_accept(transaction_id, buyer_id=principal.buyer_id, actor=principal.actor)


@router.post("/transactions/{transaction_id}/dispute")
async def dispute(transaction_id: str, request: Request) -> dict[str, Any]:
    principal, _ = await authorize_buyer_transaction(request, transaction_id, required_scope="txn:act")
    body = await request.json()
    return await _service(request).open_dispute(
        transaction_id,
        buyer_id=principal.buyer_id,
        requirement_ids=body.get("requirement_ids") or [],
        reason_code=body.get("reason_code"),
        claim=body.get("claim"),
        evidence=body.get("evidence") or [],
    )
```
Preserve any additional validation/response fields present in the current implementation.

- [ ] **Step 4: Run tests**
Run: `pytest <buyer-api-test-file> tests/verifund_control_plane/test_buyer_principal.py -v`

- [ ] **Step 5: Commit**
```bash
git add apps/verifund_control_plane/verifund_control_plane/api/buyer.py <buyer-api-test-file>
git commit -m "feat(cp): migrate buyer action routes to BuyerPrincipal auth"
```

---

### Task 4: Migrate agreements buyer decision (remove `X-Approval-Token`, enforce version/hash/idempotency)

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/routes.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/service.py`
- Modify/Create: agreements tests covering buyer decision (search: `rg "buyer-decision|X-Approval-Token|record_buyer_decision" tests -g"*agreement*.py"`)
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/repository.py` only if approval-token persistence for buyer decisions must change (minimize).

**Interfaces:**
- Produces: `POST /agreements/{id}/buyer-decision` accepts `BuyerPrincipal` auth (Clerk or internal), requires `Idempotency-Key`, requires body fields `agreement_version` and `agreement_hash` (and `decision`/`note`/idempotency fields per existing `BuyerAgreementApprovalDecision`/contract — extend contract only if necessary, update callers/tests).
- Consumes: `BuyerPrincipal` ownership of agreement/transaction; `agreement.current_version`/`agreement_hash` must match request; idempotency must be enforced.
- Removes: `X-Approval-Token` header requirement for migrated buyer decisions; `POST /agreements/{id}/approval-token` no longer required for migrated console flow (disable/restrict; return 410 `gone` or 403 with clear message unless a justified retained caller exists).

- [ ] **Step 1: Write failing agreement decision tests**
Cover: Clerk/internal authorized buyer can decide with correct hash+version+idempotency; stale hash/version rejected (409/400 as per domain mapping); wrong buyer 404; missing idempotency rejected; `X-Approval-Token` not required/not accepted as sole auth.

- [ ] **Step 2: Run to verify failures**
Run: `pytest <agreement-decision-tests> -v`

- [ ] **Step 3: Implement route changes**
In `agreements/routes.py`:
  - `buyer_decision`: remove `token: str = Header(..., alias="X-Approval-Token")`; resolve `BuyerPrincipal` via new helper (e.g. `from verifund_control_plane.api.buyer_auth import resolve_buyer_principal` / agreement ownership helper). Authorize ownership. Pass principal/validated data to service.
  - `issue_token` (approval-token): deprecate for migrated user flow (e.g. raise `VerifundError("gone","buyer approval tokens are not used; authenticate and submit decision", status_code=410)` or gate by ops-only if needed). Update tests/callers accordingly.

- [ ] **Step 4: Implement service changes**
In `agreements/service.py` refactor `record_buyer_decision` (and related) to:
  - accept `(conn, agreement_id, body, actor_or_principal, now, *, expected_buyer_id/org)` or equivalent
  - load agreement, verify buyer ownership, verify `body.agreement_version == agreement.current_version` and `body.agreement_hash == agreement.agreement_hash` (or service’s canonical hash field)
  - enforce idempotency (use existing idempotency patterns/keys; do not allow replay to mutate state)
  - perform same state transitions/audits/txn sync as before
  - remove approval token verify/consume path
Keep `AgreementError` codes/messages compatible where possible.

- [ ] **Step 5: Run agreement tests**
Run: `pytest <agreement-decision-tests> -v`

- [ ] **Step 6: Commit**
```bash
git add apps/verifund_control_plane/verifund_control_plane/agreements/routes.py apps/verifund_control_plane/verifund_control_plane/agreements/service.py apps/verifund_control_plane/verifund_control_plane/agreements/repository.py <agreement-tests>
git commit -m "feat(cp): migrate agreement buyer decisions to BuyerPrincipal and hash/version idempotency"
```

---

### Task 5: Migrate agreements read/list auth (buyer principal) and ops buyer-token deprecation

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/routes.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Modify: related agreement/service tests

**Interfaces:**
- Produces: agreement read/list accepts Clerk `BuyerPrincipal` (and still supports ops/seller read paths as explicitly retained) without `buyer_txn` bearer dependency for buyer reads.
- Produces: ops `issue-buyer-token` disabled for migrated flows (410/clear error) and callers/tests updated.

- [ ] **Step 1: Write failing tests** for Clerk buyer reading owned agreement(s) and ops issue-buyer-token returning deprecation/gone.
- [ ] **Step 2: Run to verify failures**
- [ ] **Step 3: Implement `_authorize_agreement_read` to try `BuyerPrincipal` (Clerk/internal) before or instead of legacy `buyer_tokens.verify`; fail closed.** Keep ops/seller checks intact unless tests prove safe to adjust.
- [ ] **Step 4: Disable/deprecate ops `issue-buyer-token` and update tests/callers.**
- [ ] **Step 5: Run tests**
Run: `pytest <agreement-read-tests> <ops-buyer-token-tests> -v`
- [ ] **Step 6: Commit**

---

### Task 6: Console — agreement decision flow (remove approval token, Clerk→CP principal)

**Files:**
- Modify: `apps/console/app/(console)/agreements/[id]/actions.ts`
- Modify: `apps/console/app/(console)/agreements/[id]/AgreementDecisionPanel.tsx`
- Modify: `apps/console/app/api/agreements/[id]/buyer-decision/route.ts`
- Modify/Delete behavior: `apps/console/app/api/agreements/[id]/approval-token/route.ts`
- Modify: agreement Vitest tests under `apps/console`

**Interfaces:**
- Consumes: migrated CP `POST /agreements/{id}/buyer-decision` contract (no `X-Approval-Token`; requires `agreement_version`, `agreement_hash`, `decision`, idempotency, Clerk auth via `controlPlaneForUser`).
- Produces: same UX outcomes (approve/reject/request changes, orchestrator resume where applicable).

- [ ] **Step 1: Write/update failing console tests** (Vitest) for decision submission without approval-token step.
- [ ] **Step 2: Run to verify failures**: `cd apps/console && npm test -- <pattern>` (or project’s vitest command).
- [ ] **Step 3: Implement actions/proxy/UI changes.** Remove `approval-token` fetch and `X-Approval-Token` header. Ensure `agreement_version`/`agreement_hash` are sent from current agreement data. Keep `Idempotency-Key`.
- [ ] **Step 4: Retire approval-token route** (404/410) or remove if unused.
- [ ] **Step 5: Run console tests + typecheck**: `npm test -- <pattern> && npm run typecheck` (or `tsc --noEmit`).
- [ ] **Step 6: Commit**

---

### Task 7: Console — runs/buyer-agent proxies and buyer-touching auth alignment

**Files:**
- Modify: `apps/console/lib/buyer-proxy.ts`
- Modify: `apps/console/app/api/runs/route.ts`
- Modify: `apps/console/app/api/runs/[runId]/stream/route.ts`
- Modify: affected buyer agent console/internal auth checks (coordinate with Task 8)
- Modify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts` and env references only as needed

**Interfaces:**
- Produces: Clerk-authenticated, fail-closed org-scoped access to buyer agent run surfaces; no static `x-marketmesh-console-token` for migrated console paths unless explicitly retained with justification.

- [ ] **Step 1: Define the console↔buyer-agent auth contract** (headers/proof). Prefer verifiable mechanism (Clerk token validated by buyer agent, or signed internal principal minted by trusted server boundary) — implement the simplest verifiable option.
- [ ] **Step 2: Write failing tests** (console + buyer agent as appropriate).
- [ ] **Step 3: Implement proxy/client + buyer agent verification (Task 8 dependency).**
- [ ] **Step 4: Run tests/typecheck.**
- [ ] **Step 5: Commit**

---

### Task 8: Buyer agent — settlement client to CP uses internal service auth; remove approval-token buyer decisions

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/settings.py`
- Modify: `apps/buyer_agent/buyer_agent/settlement_client.py`
- Modify: `apps/buyer_agent/buyer_agent/agreement_service.py`
- Modify: `apps/buyer_agent/buyer_agent/services.py`
- Modify: buyer agent tests for settlement/agreements

**Interfaces:**
- Produces: CP calls for migrated buyer/agreement routes include `X-Verifund-Buyer-Internal-Token` + context headers (`X-Buyer-Org-Id`/`X-Buyer-Id`/resource context) validated by CP. `buyer_decision` sends `agreement_version`, `agreement_hash`, `decision`, `idempotency_key`; no `X-Approval-Token`.

- [ ] **Step 1: Write failing tests** for settlement client headers and decision payload contract.
- [ ] **Step 2: Run to verify failures**: `pytest` in buyer agent context (find existing pattern: `rg "settlement_client|BuyerSettlementClient" apps/buyer_agent tests -g"*.py"`).
- [ ] **Step 3: Implement client/service/settings changes.**
- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit**

---

### Task 9: Buyer agent — full exposed/internal/agent API auth overhaul

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/console_api.py`
- Modify: `apps/buyer_agent/buyer_agent/settlement_api.py`
- Modify: any middleware/auth helpers
- Modify: buyer agent API tests

**Interfaces:**
- Produces: consolidated, least-privilege auth. Console/user reads/actions require verifiable identity + fail-closed org ownership (404 on mismatch/missing). Internal/agent endpoints use explicit internal tokens with constant-time checks. Remove/replace `x-marketmesh-console-token` trust for user-scoped data where it bypasses ownership.

- [ ] **Step 1: Inventory all auth checks and write failing tests** for cross-org denial and valid access.
- [ ] **Step 2: Run to verify failures.**
- [ ] **Step 3: Implement cohesive auth model** (may introduce a small `auth.py` in buyer agent). Keep contracts used by Verifund Agent/internal callers working or migrate them in lockstep with tests.
- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit**

---

### Task 10: Contracts, scripts, caller migration, and legacy cleanup

**Files:**
- Modify: `packages/verifund_contracts` (decision/settlement request shapes if changed)
- Modify: `scripts/verifund_flow.py` and other buyer-touching scripts
- Modify: `.env.example`
- Modify: any remaining in-repo callers found by `rg "issue-buyer-token|X-Approval-Token|buyer_txn|BUYER_CONSOLE_API_TOKEN|x-marketmesh-console-token" -g"!*.lock" -g"!*plan*"`

- [ ] **Step 1: Find callers**: run ripgrep for legacy tokens/headers/endpoints.
- [ ] **Step 2: Write/update tests or script smoke checks** for migrated contracts.
- [ ] **Step 3: Update contracts/scripts/env docs.**
- [ ] **Step 4: Run targeted tests.**
- [ ] **Step 5: Commit**

---

### Task 11: Full validation, docs, and spec status

**Files:**
- Modify: `docs/superpowers/specs/2026-11-07-buyer-workspace-clerk-access-design.md` (set **Status:** Implemented after verification)
- Modify: relevant runbooks/docs if buyer auth behavior documented

- [ ] **Step 1: Run targeted CP suites**
Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && pytest tests/verifund_control_plane/test_buyer_principal.py <buyer-api-tests> <agreement-tests> -v`
Expected: PASS.

- [ ] **Step 2: Run targeted buyer agent + console checks**
Run buyer agent pytest targets and `cd apps/console && npm test -- <buyer/agreement/run patterns> && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Run broader regression**
Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && pytest -x -q` (or the project’s standard suite). Record failures; distinguish pre-existing/flaky from regressions with evidence.
Expected: no regressions attributable to this migration.

- [ ] **Step 4: Update spec status and commit**
Change spec status to `Implemented` with date/notes as appropriate.
```bash
git add docs/superpowers/specs/2026-11-07-buyer-workspace-clerk-access-design.md
git commit -m "docs: mark buyer Clerk access migration spec implemented"
```

- [ ] **Step 5: Final report**
Summarize changed auth model, env vars (`VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN` etc.), migrated routes, removed legacy paths, test evidence, and manual sandbox E2E steps still required.

---

## Self-Review Notes (plan author)

- **Spec coverage:** principals/resolver, CP buyer.py, agreements decision+read, ops issuance, console agreements+runs/proxies, buyer agent settlement + full API overhaul, contracts/scripts/tests/docs, fail-closed/legacy removal/invariants — covered across Tasks 1–11.
- **Placeholders:** tasks specify concrete files/commands/behaviors; tenancy helper names may require alignment with actual API during implementation (explicitly noted) — implementer must resolve by reading `tenancy/repository.py` and adding minimal methods with tests, not “TBD”.
- **Dependencies:** Task 2 before 3–5; Task 4/5 before 6/8; Task 7 coordinated with Task 9; Task 10 after core migrations.
- **Risk areas:** agreement service refactor (Task 4) and buyer agent full overhaul (Tasks 7–9) are highest risk — keep commits small, run targeted tests after each.
