# Dynamic Seller Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace static `make dev` seller seeding with Clerk-authenticated workspace onboarding so a seller only appears after completing the strict onboarding sequence.

**Architecture:** Delete the `SELLERS`→`seed.py` bypass from the default boot path; drive org/profile/agent/catalog/test/verification/activation through existing control-plane endpoints gated by Clerk org identity; buyer discovers sellers by polling the registry every 30s instead of a baked token map; keep `scripts/seed.py` behind `make seed-demo`.

**Tech Stack:** Python 3.12 (control plane, buyer, scripts), Next.js console via `@clerk/nextjs` Server Actions, SQLite (`data/verifund.db`, `data/sellers.db`), httpx, Clerk Backend (`clerk_backend_api`).

**Spec:** `docs/superpowers/specs/2026-11-08-dynamic-seller-onboarding-design.md`

## Global Constraints

- Next.js in this repo has breaking changes — console tasks MUST read the relevant guide in `node_modules/next/dist/docs/` (resolved from `apps/console/`) before writing Server Components / Server Actions / route code; do not rely on training-data conventions.
- Fake identity (`MARKETMESH_DEV_IDENTITY=fake`) must never be usable with a production Clerk key: fail fast if `CLERK_SECRET_KEY` does not start with `sk_test_` when fake is set.
- Existing endpoints keep their outward contracts: `POST /v1/seller/onboarding`, `POST /v1/seller/onboarding/profile`, `POST /v1/seller/verification/submit`, `POST /v1/agents`, `PATCH /v1/agents/{id}/config|policies`, `POST /v1/seller/catalog/import`, `POST /v1/agents/{id}/test`, `POST /v1/agents/{id}/activate`, `GET /v1/agents/{id}/status`, `GET /v1/sellers`.
- Open-question resolutions locked by this plan (from spec §6): (1) single UUID shared by `seller_profiles.seller_id` and `agent_id` (`agent_<uuid>`); (2) fake org `org_dev_fake` persisted in DB, wiped only by `make reset`; (3) first catalog import defaults `replace_catalog=true`; (4) buyer holds per-seller tokens (one `a2a:call` credential per activated agent).
- `data/demo-credentials.json` generation is deleted; no code reads it. Existing orphaned rows in `data/sellers.db`/`data/verifund.db` are left alone (fresh `make reset` is the clean path).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py` | Fake-identity bypass in `resolve_identity()` | 1 |
| `apps/verifund_control_plane/verifund_control_plane/agents/routes.py` | Opaque `agent_<uuid>` at create; per-agent credential issuance at activate (already via `issue_credential` in test route); publish-on-activate already there | 2, 4 |
| `apps/verifund_control_plane/verifund_control_plane/onboarding/routes.py` + `onboarding/service.py` | Strict sequence enforcement; required `payout_email` on verification submit; `VERIFUND_AUTO_VERIFY` opt-out | 3, 4 |
| `apps/verifund_control_plane/verifund_control_plane/settings.py` | `verifund_auto_verify`, `marketmesh_dev_identity` fields | 1, 3 |
| `apps/buyer_agent/buyer_agent/registry_client.py` + `settings.py` | Registry poller (30s), atomic map swap, per-seller token resolution | 5 |
| `scripts/dev.py` | Remove `run_seed()` from boot; trim env (`BUYER_SELLER_TOKENS` out, `BUYER_REGISTRY_POLL_SECONDS=30` in, `ALLOWED_CARD_URLS=[]`); onboard banner; fake-identity passthrough | 6 |
| `scripts/config.py` | Delete `SELLERS`, `SellerConfig`, `SELLER_PAYOUT_EMAILS`, `seller_tokens_json()`, `seller_payout_emails()` (seed script gets its own local copy) | 7 |
| `scripts/seed.py` | Standalone `make seed-demo` only; keep logic, import its own seller list | 7 |
| `Makefile` | Add `seed-demo` target; `dev` unchanged | 7 |
| `docs/templates/` | Relocated 4 YAMLs from `apps/seller_agent/profiles/` | 7 |
| `apps/console/app/(seller-onboarding)/.../page.tsx`, `VerificationSubmitForm.tsx`, `actions.ts`, `apps/console/lib/agent-api.ts` | Stepper wizard, payout-email field, template links | 8 |
| `tests/unit/test_tenancy_identity.py`, `tests/unit/test_verifund_dev_config.py`, `tests/integration/test_seller_onboarding_routes.py`, `tests/integration/test_onboarding_agent_flow.py`, `tests/unit/test_registry_client.py` (new) | Test coverage per task | 1–9 |

---

### Task 1: Fake-identity bypass for Clerk-less dev/CI

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py:40-96`
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py`
- Test: `tests/unit/test_tenancy_identity.py`

**Interfaces:**
- Consumes: `settings.clerk_secret_key`, env `MARKETMESH_DEV_IDENTITY`, `store.ensure_personal_organization` / `get_organization_by_clerk_id`.
- Produces: `resolve_identity(store, payload, settings)` returns `Identity(user_id="user_dev_fake", clerk_user_id="user_dev_fake_clerk", tenant_id="org_dev_fake", role="org:admin", permissions=ROLE_PERMISSIONS["org:admin"], is_platform_admin=False, organization_status="active")` when fake is on. `require_identity(request)` needs no change (calls `resolve_identity`).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_resolve_identity_fake_branch_returns_dev_org(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKETMESH_DEV_IDENTITY", "fake")
    store = await make_tenancy_store(tmp_path)  # existing fixture in tests/unit/test_tenancy_identity.py
    settings = SimpleNamespace(clerk_secret_key="sk_test_dev", clerk_directory=None, _clerk_directory=None)
    ident = await resolve_identity(store, {"sub": "user_x"}, settings)
    assert ident.tenant_id == "org_dev_fake"
    assert ident.role == "org:admin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tenancy_identity.py::test_resolve_identity_fake_branch_returns_dev_org -xvs`
Expected: FAIL — `resolve_identity` queries Clerk and raises 401/403 (not the `org_dev_fake` identity).

- [ ] **Step 3: Write minimal implementation**

Add to `Settings` in `apps/verifund_control_plane/verifund_control_plane/settings.py`:

```python
marketmesh_dev_identity: str = Field(default="", env="MARKETMESH_DEV_IDENTITY")
```

Add at the top of `resolve_identity()` in `identity.py` (before any directory lookup):

```python
import os
if os.environ.get("MARKETMESH_DEV_IDENTITY") == "fake":
    if (settings.clerk_secret_key or "").startswith("sk_live_"):
        raise VerifundError("misconfigured", "fake identity requires sk_test_ Clerk key", status_code=500)
    org = await store.ensure_seed_organization(seller_id="dev-fake-seller", kind="business", verified=True)
    user = await store.upsert_user("user_dev_fake", "dev-fake@marketmesh.dev", "Dev Fake")
    return Identity(
        user_id=user["id"], clerk_user_id="user_dev_fake_clerk", tenant_id=org["id"],
        clerk_org_id="org_dev_fake", role="org:admin",
        permissions=ROLE_PERMISSIONS["org:admin"], is_platform_admin=False,
        organization_status="active",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tenancy_identity.py -x -q`
Expected: PASS (all existing identity tests + new fake test).

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tenancy/identity.py apps/verifund_control_plane/verifund_control_plane/settings.py tests/unit/test_tenancy_identity.py
git commit -m "feat: add MARKETMESH_DEV_IDENTITY fake bypass in resolve_identity"
```

---

### Task 2: Opaque `agent_<uuid>` at agent creation

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/agents/routes.py:196-242` (`create_agent_route`)
- Modify: `apps/verifund_control_plane/verifund_control_plane/onboarding/service.py:17-40` (`create_onboarding` seller_id)
- Test: `tests/integration/test_onboarding_agent_flow.py`

**Interfaces:**
- Consumes: `store.unique_seller_id(...)`, `store.create_agent(...)`.
- Produces: `POST /v1/agents` returns `{"agent_id": "agent_<uuid4hex>", "status": "draft"}`; idempotent on `Idempotency-Key` header (existing `_idem_key` helper). `seller_profiles.seller_id` equals the same UUID (no `agent_` prefix stored in profile row — profile stores bare uuid, card path uses `f"agent_{seller_id}"`).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_create_agent_uses_opaque_uuid(stack):
    client, org = await stack.onboarded_business_client()
    token = await stack.clerk_token_for(org)
    r = await client.post("/v1/agents", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201
    assert r.json()["agent_id"].startswith("agent_")
    assert "northwind" not in r.json()["agent_id"]
    # profile linkage: seller_id bare uuid matches agent suffix
    profile = await stack.tenancy.get_seller_profile_by_organization(org["id"])
    assert profile["seller_id"] == r.json()["agent_id"].removeprefix("agent_")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_onboarding_agent_flow.py::test_create_agent_uses_opaque_uuid -xvs`
Expected: FAIL — `agent_id` is currently `f"agent_{seller_id}"` where `seller_id` is the slug from `unique_seller_id(org["slug"])`.

- [ ] **Step 3: Write minimal implementation**

In `agents/routes.py:create_agent_route`, replace lines 204–206:

```python
import uuid
profile = await store.get_seller_profile_by_organization(identity.tenant_id)
seller_id = (profile or {}).get("seller_id") or uuid.uuid4().hex
agent_id = f"agent_{seller_id}"
```

In `onboarding/service.py:create_onboarding`, replace `store.unique_seller_id(...)` with `uuid.uuid4().hex` so the profile's `seller_id` is born as the shared UUID.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_onboarding_agent_flow.py -x -q`
Expected: PASS (full saga still reaches `active`; agent ids are now opaque).

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agents/routes.py apps/verifund_control_plane/verifund_control_plane/onboarding/service.py tests/integration/test_onboarding_agent_flow.py
git commit -m "feat: use opaque agent uuid at creation (single UUID for profile+agent)"
```

---

### Task 3: Payout email required on verification + `VERIFUND_AUTO_VERIFY` flag

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/onboarding/routes.py:17-18`, `onboarding/service.py:43-74`
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py`
- Modify: `apps/console/app/(seller-onboarding)/seller/onboarding/actions.ts:81-97` (pass `payout_email` through)
- Test: `tests/unit/test_seller_onboarding_verification.py`, `tests/integration/test_seller_onboarding_routes.py`

**Interfaces:**
- Consumes: `submit_verification(store, org_id, submitted_by, documents, payout_email, *, auto_approve)`.
- Produces: `POST /v1/seller/verification/submit` body `{"documents": ..., "payout_email": str}` → `payment_account` row written on approval; `settings.verifund_auto_verify: bool` (env `VERIFUND_AUTO_VERIFY`, default `False`).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_verification_submit_requires_payout_email(sandbox_client):
    # logged-in business org, profile exists, verification_status=unverified
    r = await sandbox_client.post("/v1/seller/verification/submit", json={"documents": {"kyc": "doc-1"}})
    assert r.status_code == 422  # payout_email required
    r = await sandbox_client.post("/v1/seller/verification/submit", json={"documents": {"kyc": "doc-1"}, "payout_email": "seller@paypal.example"})
    assert r.status_code == 200
    rows = await sandbox_client.tenancy.list_payment_accounts(await sandbox_client.org_id())
    assert any(p["provider_account_id"] == "seller@paypal.example" for p in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_onboarding_verification.py -k payout -xvs`
Expected: FAIL — `VerificationSubmit` has no `payout_email` field; no payment account is written.

- [ ] **Step 3: Write minimal implementation**

In `onboarding/routes.py`:

```python
class VerificationSubmit(BaseModel):
    documents: list | dict = Field(default_factory=list)
    payout_email: str = Field(min_length=3, max_length=254)  # required
```

In `onboarding/service.py:submit_verification`, add `payout_email: str` kwarg; after `decide_verification` succeeds (including the auto-approve path), call:

```python
await store.upsert_payment_account(
    organization_id=organization_id, provider="paypal",
    provider_account_id=payout_email, account_type="payout",
    status="active", credentials_reference=f"secret:{profile['seller_id']}",
)
```

In `settings.py` add `verifund_auto_verify: bool = Field(default=False, env="VERIFUND_AUTO_VERIFY")` and wire `auto_approve_sandbox=bool(getattr(settings, "verifund_auto_verify", False) or getattr(settings, "is_sandbox", False))` in `routes.py:72`.

Console: `actions.ts` `submitVerificationAction(documents, payoutEmail)` → body `{ documents, payout_email: payoutEmail }`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_seller_onboarding_verification.py tests/integration/test_seller_onboarding_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/onboarding/ apps/verifund_control_plane/verifund_control_plane/settings.py apps/console/app/\(seller-onboarding\)/seller/onboarding/actions.ts tests/unit/test_seller_onboarding_verification.py tests/integration/test_seller_onboarding_routes.py
git commit -m "feat: require payout_email on verification submit; add VERIFUND_AUTO_VERIFY"
```

> Next.js check (Task 8 covers the form): the `actions.ts` change is a signature/body change only — re-verify against `node_modules/next/dist/docs/` before the form render change in Task 8.

---

### Task 4: Strict onboarding sequence enforcement

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/onboarding/service.py` (`save_profile_and_continue`), `apps/verifund_control_plane/verifund_control_plane/agents/routes.py` (`create_agent_route`, `update_agent_config`, `catalog_import_route`)
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py` (`upsert_onboarding` persists `current_step`)
- Test: `tests/integration/test_seller_onboarding_routes.py`, `tests/integration/test_onboarding_agent_flow.py`

**Interfaces:**
- Consumes: `store.get_onboarding(org_id) -> {"current_step", "status"}`, `store.upsert_onboarding(org_id, status, current_step)`.
- Produces: sequence `profile → agent → config → catalog → test → verification → activation`. Every mutator returns `409 onboarding_incomplete` (`{"current_step": ..., "missing": "<precondition>"}`) when its precondition is unmet. Step order constant: `["profile", "agent", "config", "catalog", "test", "verification", "activation"]`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_agent_create_blocked_before_profile(stack):
    client, org = await stack.business_client()  # org exists, no profile yet
    token = await stack.clerk_token_for(org)
    r = await client.post("/v1/agents", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "onboarding_incomplete"
    assert r.json()["error"]["details"]["current_step"] == "profile"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_seller_onboarding_routes.py::test_agent_create_blocked_before_profile -xvs`
Expected: FAIL — agent creation succeeds without a profile (no sequence check exists).

- [ ] **Step 3: Write minimal implementation**

Add a helper in `onboarding/service.py`:

```python
STEP_ORDER = ["profile", "agent", "config", "catalog", "test", "verification", "activation"]

async def require_step(store, organization_id: str, required: str) -> dict:
    onboarding = await store.get_onboarding(organization_id)
    current = (onboarding or {}).get("current_step")
    idx = STEP_ORDER.index(current) if current in STEP_ORDER else -1
    if idx < STEP_ORDER.index(required):
        raise VerifundError(
            "onboarding_incomplete",
            f"onboarding step {required!r} requires step {current!r} complete",
            status_code=409,
            details={"current_step": current, "missing": required},
        )
    return onboarding or {}
```

Call `require_step(store, org_id, "profile")` at the top of `create_agent_route`; `require_step(..., "agent")` in `update_agent_config`; `require_step(..., "config")` in `catalog_import_route`; `require_step(..., "catalog")` in `test_agent`; `require_step(..., "test")` in `submit_verification`. Advance `current_step` after each success: profile→agent (in `save_profile_and_continue`), agent→config (in `create_agent_route`), config→catalog (in `update_agent_config`), catalog→test (in `catalog_import_route`), test→verification (in `test_agent` when `passed`), verification→activation (in `decide_verification` when `verified`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_seller_onboarding_routes.py tests/integration/test_onboarding_agent_flow.py -q`
Expected: PASS (existing saga in `test_full_onboarding_saga_reaches_active` now walks the enforced order).

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/onboarding apps/verifund_control_plane/verifund_control_plane/agents/routes.py apps/verifund_control_plane/verifund_control_plane/tenancy/repository.py tests/integration/test_seller_onboarding_routes.py tests/integration/test_onboarding_agent_flow.py
git commit -m "feat: enforce strict onboarding sequence with 409 onboarding_incomplete"
```

---

### Task 5: Buyer registry poller (30s) replacing `BUYER_SELLER_TOKENS`

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/registry_client.py` (`RegistryClient.__init__`, add `async def poll_registry()`), `apps/buyer_agent/buyer_agent/settings.py`, `apps/buyer_agent/buyer_agent/services.py` (wire poll task)
- Modify: `apps/buyer_agent/buyer_agent/server.py` (start poll on lifespan)
- Create: `tests/unit/test_registry_client.py`
- Delete: `seller_tokens` field usage (keep env read for one release with a deprecation warning — see step 3)

**Interfaces:**
- Consumes: `GET {registry_url}/v1/sellers` → `{"sellers": [{"seller_id","card_url","categories"}]}`, `GET /v1/products` (existing), control-plane credential store via internal token.
- Produces: `RegistryClient.poll_registry() -> dict[str, SellerEndpoint]` atomically replaces `self._endpoints` on success, keeps last map on failure. `seller_tokens` param becomes optional; token per seller resolved from injected `token_resolver: Callable[[str], str | None]` (default: `self.seller_tokens.get(seller_id)` for backward-compat during rollout).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_poll_registry_replaces_map_and_keeps_old_on_failure():
    seller_card = build_test_card("seller-<uuid>")  # helper using existing test support in tests/support/
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"sellers": [{"seller_id": "seller-a", "card_url": "http://127.0.0.1:9200/seller-a/.well-known/agent-card.json", "categories": ["audio"]}]}))
    client = RegistryClient(registry_url="http://127.0.0.1:9105", allowed_card_hosts=("127.0.0.1",), seller_tokens={"seller-a": "tok-a"}, client=httpx.AsyncClient(transport=transport))
    endpoints = await client.poll_registry()
    assert "seller-a" in endpoints
    # next poll fails (HTTP 500) — map unchanged
    transport.handler = lambda req: httpx.Response(500)
    endpoints2 = await client.poll_registry()
    assert endpoints2 == endpoints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_registry_client.py::test_poll_registry_replaces_map_and_keeps_old_on_failure -xvs`
Expected: FAIL — `poll_registry` does not exist; `RegistryClient` only has `discover()`.

- [ ] **Step 3: Write minimal implementation**

In `registry_client.py` add:

```python
async def poll_registry(self) -> dict[str, SellerEndpoint]:
    try:
        response = await self.http.get(f"{self.registry_url}/v1/sellers")
        response.raise_for_status()
        sellers = response.json().get("sellers", [])
    except (httpx.HTTPError, ValueError) as exc:
        import logging; logging.getLogger(__name__).warning("registry poll failed: %s", exc)
        return self._endpoints
    new_endpoints: dict[str, SellerEndpoint] = {}
    for entry in sellers:
        seller_id, card_url = entry["seller_id"], entry["card_url"]
        try:
            card = await fetch_agent_card(card_url, client=self.http, allowed_hosts=self.allowed_card_hosts)
            if validate_agent_card(card):
                continue
        except Exception:
            continue
        token = self.seller_tokens.get(seller_id)
        if not token:
            continue
        metadata = card_commerce_metadata(card)
        new_endpoints[seller_id] = SellerEndpoint(
            seller_id=seller_id, name=card.name, card_url=card_url, card=card,
            token=token, rating=float(metadata["rating"]),
            sustainability_certified=bool(metadata["sustainability_certified"]),
        )
    self._endpoints = new_endpoints
    return self._endpoints
```

In `settings.py` add `buyer_registry_poll_seconds: int = 30` (`BUYER_REGISTRY_POLL_SECONDS`). In `server.py` lifespan start `asyncio.create_task` that loops `poll_registry()` every polling interval until cancelled. In `services.py`, pass `seller_tokens` through unchanged but add a deprecation warning log when the env `BUYER_SELLER_TOKENS` is non-empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_registry_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/registry_client.py apps/buyer_agent/buyer_agent/settings.py apps/buyer_agent/buyer_agent/services.py apps/buyer_agent/buyer_agent/server.py tests/unit/test_registry_client.py
git commit -m "feat: buyer registry poller (30s) with atomic map swap"
```

---

### Task 6: `scripts/dev.py` boot path goes dynamic

**Files:**
- Modify: `scripts/dev.py` (delete `run_seed()`, change `buyer_environment`, `registry_environment`, `control_plane_environment`, banner print, `AGENT_FORBIDDEN_ENV`)
- Test: `tests/unit/test_verifund_dev_config.py`

**Interfaces:**
- Consumes: `scripts/config.py` helpers that survive (`registry_url()`, `shared_seller_url()`, `buyer_url()`, `console_port()`).
- Produces: `buyer_environment()` no longer sets `BUYER_SELLER_TOKENS`, sets `BUYER_REGISTRY_POLL_SECONDS=30`; `registry_environment()` sets `ALLOWED_CARD_URLS="[]"` (plus any explicit `ALLOWED_CARD_URLS` env override) and `ALLOWED_CARD_HOSTS='["127.0.0.1","localhost"]'` (+ shared hostname); `control_plane_environment()` passes `VERIFUND_AUTO_VERIFY` and `MARKETMESH_DEV_IDENTITY` through; `run_stack()` prints `No sellers seeded — onboard via http://127.0.0.1:{console_port}/seller/onboarding` instead of calling `run_seed()`.

- [ ] **Step 1: Write the failing test**

```python
def test_buyer_environment_has_no_seller_tokens(monkeypatch):
    monkeypatch.delenv("BUYER_SELLER_TOKENS", raising=False)
    env = dev.buyer_environment("scripted", "sandbox")
    assert "BUYER_SELLER_TOKENS" not in env
    assert env["BUYER_REGISTRY_POLL_SECONDS"] == "30"
    assert env["REGISTRY_URL"] == config.registry_url()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_dev_config.py::test_buyer_environment_has_no_seller_tokens -xvs`
Expected: FAIL — `BUYER_SELLER_TOKENS` still present via `seller_tokens_json()`.

- [ ] **Step 3: Write minimal implementation**

- Delete `run_seed()` and its call at `scripts/dev.py:622`.
- In `buyer_environment()`, delete the `"BUYER_SELLER_TOKENS": seller_tokens_json(),` line; add `"BUYER_REGISTRY_POLL_SECONDS": _env_value("BUYER_REGISTRY_POLL_SECONDS", "30"),`.
- In `registry_environment()`, change `"ALLOWED_CARD_URLS": allowed_card_urls_json(),` to `"ALLOWED_CARD_URLS": _env_value("ALLOWED_CARD_URLS", "[]"),` (keep `allowed_card_hosts_json()` call, which already only tracks the shared host).
- In `control_plane_environment()`, add `"VERIFUND_AUTO_VERIFY": _env_value("VERIFUND_AUTO_VERIFY", "0"), "MARKETMESH_DEV_IDENTITY": _env_value("MARKETMESH_DEV_IDENTITY", ""),`.
- Replace the `run_seed(mode)` line with:
  ```python
  print(f"  onboard      http://127.0.0.1:{console_port()}/seller/onboarding  (no sellers seeded)")
  ```
- `AGENT_FORBIDDEN_ENV`: delete the `+ tuple(seller.token_var for seller in SELLERS)` suffix (no longer needed once Task 7 lands; keep `BUYER_SELLER_TOKENS` for one release).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_verifund_dev_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/dev.py tests/unit/test_verifund_dev_config.py
git commit -m "feat: dev boot no longer seeds sellers; registry-poll buyer config"
```

---

### Task 7: Remove `SELLERS` tuple; `seed.py` becomes `make seed-demo`; YAMLs to `docs/templates/`

**Files:**
- Modify: `scripts/config.py` (delete `SellerConfig`, `SELLERS`, `SELLER_PAYOUT_EMAILS`, `seller_tokens_json()`, `seller_payout_emails()`), `scripts/seed.py` (own local `SEED_SELLERS` list + `SEED_TOKENS` dict), `Makefile` (add `seed-demo` target), `scripts/seed_shared.py` (unchanged — still used by seed-demo)
- Move: `apps/seller_agent/seller_agent/profiles/*.yaml` → `docs/templates/`
- Modify: `apps/verifund_control_plane/verifund_control_plane/tenancy/backfill.py` (drop seller branch from `seed_demo_agents` default path; keep for seed-demo)
- Test: `tests/unit/test_verifund_dev_config.py` (import-error guard), manual `make seed-demo` smoke

**Interfaces:**
- Consumes: none from `SELLERS` after this task (`scripts/dev.py` already decoupled in Task 6).
- Produces: `make seed-demo` runs `uv run python scripts/seed.py` against a live stack (same logic as before). Default `make dev` has zero seller state.

- [ ] **Step 1: Write the failing test**

```python
def test_config_no_longer_exports_seed_tuple():
    assert not hasattr(config, "SELLERS"), "SELLERS must be deleted"
def test_seed_script_has_own_local_seed_list():
    source = pathlib.Path("scripts/seed.py").read_text()
    assert "SEED_SELLERS" in source or "seller_tokens" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_dev_config.py -k seed_tuple -xvs`
Expected: FAIL — `config.SELLERS` still exists.

- [ ] **Step 3: Write minimal implementation**

- `scripts/config.py`: delete the block from `@dataclass(frozen=True)\nclass SellerConfig` through `seller_payout_emails()` (the four helpers). Keep `shared_*`, `verifund_*`, `paypal_*`, `registry_url`, `admin_token`, `buyer_*`, `orchestrator_*`.
- `scripts/seed.py`: add at module top:
  ```python
  SEED_SELLERS = (
      SimpleNamespace(seller_id="northwind-audio", profile="northwind.yaml", token="dev-northwind"),
      SimpleNamespace(seller_id="circuitforge", profile="circuitforge.yaml", token="dev-circuitforge"),
      SimpleNamespace(seller_id="aurora-supply", profile="aurora.yaml", token="dev-aurora"),
      SimpleNamespace(seller_id="summit-tech", profile="summit-tech.yaml", token="dev-summit-tech"),
  )
  ```
  and replace every `SELLERS` reference in `seed.py` with `SEED_SELLERS`, using `.token` (already present) and `.seller_id` / `.phone`-style fields. `seller.profile_path` is replaced by an explicit `ROOT / "docs/templates" / seller.profile` path.
- `tenancy/backfill.py`: guard the seller loop in `seed_demo_agents` behind `if os.environ.get("MARKETMESH_SEED_DEMO") == "1":` so default boot does nothing seller-side. `seed.py` sets that env.
- `Makefile`: add target
  ```make
  seed-demo:
      MARKETMESH_SEED_DEMO=1 uv run python scripts/seed.py
  ```
  and add `seed-demo` to `.PHONY`.
- Shell: `mkdir -p docs/templates && git mv apps/seller_agent/seller_agent/profiles/*.yaml docs/templates/` (keep filenames).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_verifund_dev_config.py -q && ls docs/templates/`
Expected: PASS; 4 YAMLs listed in `docs/templates/`.

- [ ] **Step 5: Commit**

```bash
git add scripts/config.py scripts/seed.py scripts/dev.py Makefile apps/verifund_control_plane/verifund_control_plane/tenancy/backfill.py tests/unit/test_verifund_dev_config.py
git mv apps/seller_agent/seller_agent/profiles docs/templates 2>/dev/null || (mkdir -p docs/templates && git mv apps/seller_agent/seller_agent/profiles/*.yaml docs/templates/)
git commit -m "feat: remove SELLERS tuple; seed.py behind make seed-demo; YAMLs to docs/templates"
```

---

### Task 8: Console — strict stepper, payout-email field, template links

**Files:**
- Modify: `apps/console/app/(seller-onboarding)/seller/onboarding/page.tsx`, `apps/console/app/(seller-onboarding)/seller/onboarding/verification/VerificationSubmitForm.tsx`, `apps/console/app/(seller-onboarding)/seller/onboarding/actions.ts` (already touched in Task 3 — verify signature), `apps/console/lib/agent-api.ts` (`importCatalog` call), `apps/console/components/seller-agent/CatalogImportPanel.tsx`
- Test: `apps/console/tests/app/actions.test.ts`

**Interfaces:**
- Consumes: `POST /v1/seller/onboarding` (`GET` returns `{profile, onboarding: {current_step}}`), `submitVerificationAction(documents, payoutEmail)`.
- Produces: wizard shows 7 steps; only `current_step` is editable. Verification form validates payout email (required, simple `type="email"` + server 422 fallback). Import panel links `docs/templates/*.yaml` as downloadable examples.

- [ ] **Step 1: Read the Next.js guide (required by Global Constraints)**

Run: `ls node_modules/next/dist/docs/ && cat node_modules/next/dist/docs/app-guides/server-actions.mdx 2>/dev/null | head -100`
Expected: Server Action conventions confirmed (no `cache: "no-store"` conflicts; existing `controlPlaneForUser` pattern stays valid).

- [ ] **Step 2: Write the failing test**

```typescript
// apps/console/tests/app/actions.test.ts
it("verification action sends payout_email", async () => {
  const { submitVerificationAction } = await import("@/app/(seller-onboarding)/seller/onboarding/actions");
  global.fetch = vi.fn(async () => new Response(JSON.stringify({}), { status: 200 }));
  await submitVerificationAction({ "kyc": "doc" }, "seller@paypal.example");
  const init = (global.fetch as any).mock.calls[0][1];
  expect(JSON.parse(init.body).payout_email).toBe("seller@paypal.example");
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd apps/console && pnpm run test tests/app/actions.test.ts -t "payout_email" 2>&1 | tail -20`
Expected: FAIL — `submitVerificationAction` currently takes only `documents`.

- [ ] **Step 4: Write minimal implementation**

- `actions.ts`: `submitVerificationAction(documents, payoutEmail: string)` → POST body `{ documents, payout_email: payoutEmail }`; return 422 mapping unchanged.
- `VerificationSubmitForm.tsx`: add `<input type="email" required name="payout_email" />` with label “PayPal payout email”, wire to the action second arg.
- Onboarding `page.tsx`: derive steps array from `onboarding.current_step`; render completed steps as checkmarks, current step form, future steps disabled with tooltip.
- `CatalogImportPanel.tsx`: prepend “Or start from an example: /templates/northwind.yaml” link list (static links to `docs/templates/` served copies — copy the 4 YAMLs into `apps/console/public/templates/` if not already served).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/console && pnpm run test tests/app/actions.test.ts 2>&1 | tail -20` and `pnpm run typecheck 2>&1 | tail -20`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/console/app/\(seller-onboarding\)/ apps/console/lib/agent-api.ts apps/console/tests/app/actions.test.ts apps/console/public/templates/
git commit -m "feat: console stepper, payout-email field, template links"
```

---

### Task 9: End-to-end validation + boot banner

**Files:**
- Modify: `tests/integration/test_onboarding_agent_flow.py` (full fake-identity saga), `docs/runbook.md` (onboard instructions)
- Test: manual `make dev` + `make seed-demo` smoke

**Interfaces:**
- Consumes: all Tasks 1–8.
- Produces: proven empty-boot → onboard → marketplace loop; `make seed-demo` still populates 4 sellers.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_fake_identity_full_saga(fake_identity_stack):
    # uses MARKETMESH_DEV_IDENTITY=fake — no Clerk HTTP calls
    # steps: onboarding → profile → agent → config → import(JSON) → test → verification(+payout) → activate
    agent_id = await fake_identity_stack.walk_onboarding(payout_email="dev@paypal.example")
    assert agent_id.startswith("agent_")
    sellers = (await fake_identity_stack.registry_client.get("/v1/sellers")).json()["sellers"]
    assert any(s["seller_id"] in agent_id for s in sellers)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_onboarding_agent_flow.py::test_fake_identity_full_saga -xvs`
Expected: FAIL until Tasks 1–4 land (fake branch / sequence / payout).

- [ ] **Step 3: Add runbook docs (`docs/runbook.md`)**

Append a subsection:

```markdown
### Onboarding a seller after `make dev`

1. Open http://127.0.0.1:3000/seller/onboarding (Clerk org) or set `MARKETMESH_DEV_IDENTITY=fake` for local/CI.
2. Walk steps: profile → create agent → config → catalog import (JSON/YAML, examples in `docs/templates/`) → test → verification + payout email → activate.
3. The seller appears in the buyer marketplace within 30 s (registry poll).
4. For the legacy 4-seller demo: `make seed-demo` (requires a running stack).
```

- [ ] **Step 4: Run validation**

Run: `uv run pytest tests/unit/test_verifund_dev_config.py tests/integration/test_seller_onboarding_routes.py tests/integration/test_onboarding_agent_flow.py -q`
Expected: PASS.

Manual smoke (not automated):
```bash
make reset && make dev          # → banner "No sellers seeded", registry empty
MARKETMESH_DEV_IDENTITY=fake make dev   # → onboard one seller via curl → appears
make seed-demo                  # → 4 legacy sellers appear (opt-in only)
```

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_onboarding_agent_flow.py docs/runbook.md
git commit -m "test: fake-identity end-to-end onboarding saga; runbook for dynamic flow"
```

---

## Self-Review

1. **Spec coverage:** §4.1 boot env/banner → Task 6. §4.2 fake identity → Task 1; opaque UUID → Task 2; payout + auto-verify → Task 3; strict sequence → Task 4; publish-on-activate exists (`routes.py:341-395`) + per-agent credentials at activate → covered by Tasks 2/4 (activate already calls `issue_credential` + `publish_agent`; lifecycle gates verified in Task 4 tests). §4.4 buyer poll → Task 5. §4.5 console → Task 8. §4.6 seed-demo + Makefile + YAML move → Task 7. §4.7 migration notes → Tasks 6–7. §7 error table → Task 4 (409/422). §8 testing → each task's own test steps + Task 9 E2E. §6 open questions → Global Constraints resolutions + Task 2/5 locks.
2. **Placeholder scan:** no `TBD`/`TODO`/`appropriate handling`; every code step has a concrete snippet and a run command with expected output.
3. **Type consistency:** `seller_id`/`agent_id` linkage (single UUID) used identically in Tasks 2, 4, 5, 9. `submit_verification(..., payout_email, auto_approve)` signature consistent between Task 3's service, route, action, and test. `poll_registry()` name consistent in Task 5 implementation + test + server wiring.

## Rollout Notes (from spec §9)

Land in task order (1 → 9). Task 6 lands before Task 7 so `scripts/dev.py` never imports the deleted `SELLERS`. `BUYER_SELLER_TOKENS` deprecation warning (Task 5) stays for one release after Task 6 removes it from env construction. `make reset && make dev` is the clean-slate verification at Task 9.
