# Dynamic Seller Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make buyer seller-auth fully dynamic: the buyer exchanges per-seller `a2a:call` tokens with the control plane over an internal-token-gated endpoint instead of the static `BUYER_SELLER_TOKENS` env map.

**Architecture:** At `POST /v1/agents/{id}/activate` the control plane issues one long-lived `a2a:call` credential (hash-stored, raw only via internal exchange). A new internal route `POST /v1/internal/agent-token` gated by `BUYER_INTERNAL_TOKEN` returns that raw token per `seller_id`. Buyer `RegistryClient` caches exchanged tokens per seller, evicts on registry-miss/401, and `seller_tokens` env is deleted after a fallback release.

**Tech Stack:** Python 3.12 (control plane `verifund_control_plane`, buyer `buyer_agent`), httpx, SQLAlchemy async (SQLite), FastAPI/Pydantic.

**Spec:** `docs/superpowers/specs/2026-11-08-dynamic-seller-auth-design.md`

## Global Constraints

- Existing endpoints keep their outward contracts: `POST /v1/agents`, `PATCH /v1/agents/{id}/config|policies`, `POST /v1/seller/catalog/import`, `POST /v1/agents/{id}/test`, `POST /v1/agents/{id}/activate`, `GET /v1/agents/{id}/status`, `GET /v1/sellers`, `POST /v1/agent-credentials/verify`.
- Exchange endpoint is internal-only: `X-Internal-Token` must equal `BUYER_INTERNAL_TOKEN`; it must not be reachable with Clerk JWTs and must not be linked from the console.
- Raw tokens are returned once per exchange call, never logged, never persisted by the control plane beyond the existing hash row (`issue_credential` in `apps/verifund_control_plane/verifund_control_plane/agents/credentials.py`).
- `a2a:test` and `a2a:call` scopes stay strictly separated (`credentials.verify_credential` with `purpose="a2a:test"` vs `a2a:call`).
- Long-lived, revoke-only: no TTL scheduler; revocation = `set_agent_status("revoked")` or `revoke_credential()`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `apps/verifund_control_plane/verifund_control_plane/settings.py` | `buyer_internal_token: str = "dev-buyer-internal"` (`BUYER_INTERNAL_TOKEN` alias) | 1 |
| `apps/verifund_control_plane/verifund_control_plane/agents/routes.py` | Issue `a2a:call` at activate + new `POST /v1/internal/agent-token` route | 1, 2 |
| `apps/verifund_control_plane/verifund_control_plane/agents/credentials.py` | Reuse `issue_credential()` / `verify_credential()` unchanged | 1, 2 |
| `apps/buyer_agent/buyer_agent/registry_client.py` | `_token_cache` + `_exchange_token()` + eviction; `poll_registry()`/`discover()` use cache | 3 |
| `apps/buyer_agent/buyer_agent/settings.py` | Delete `seller_tokens`; wire `buyer_internal_token` (alias `BUYER_INTERNAL_TOKEN`, default `dev-buyer-internal`) + `control_plane_url` | 3, 4 |
| `apps/buyer_agent/buyer_agent/services.py` | Pass `buyer_internal_token` to `RegistryClient`; remove deprecation log | 3, 4 |
| `apps/buyer_agent/buyer_agent/server.py` | Poll lifespan unchanged (30s) | 3 |
| `scripts/dev.py`, `.env.example` | Drop `BUYER_SELLER_TOKENS` from docs/env (already dropped from env construction in prior work) | 4 |
| `tests/integration/test_onboarding_agent_flow.py`, `tests/unit/test_registry_client.py`, `tests/integration/test_buyer_discovery.py` | Exchange, eviction, and end-to-end tests | 1–4 |

---

### Task 1: `buyer_internal_token` setting + issue `a2a:call` at activate

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py:193-199`
- Modify: `apps/verifund_control_plane/verifund_control_plane/agents/routes.py:353-395` (`activate_agent_route`)
- Test: `tests/integration/test_onboarding_agent_flow.py`

**Interfaces:**
- Consumes: `store.list_credentials(agent_id)`, `store.create_credential(...)`, `issue_credential(store, org_id, agent_id, ["a2a:call"])`.
- Produces: `Settings.buyer_internal_token: str = "dev-buyer-internal"` (alias `BUYER_INTERNAL_TOKEN`). Activate ensures exactly one active `a2a:call` row for the agent; activate response shape unchanged (`{agent_id,status,registry_published,card}` — raw token NOT included).

- [ ] **Step 1: Write the failing test**

```python
async def test_activate_issues_a2a_call_credential(stack):
    cp, h = stack["cp"], stack["headers"]
    r = await cp.post("/v1/agents", json={"display_name": "Acme"}, headers=h)
    aid = r.json()["agent_id"]
    await cp.patch(f"/v1/agents/{aid}/config", json={"instructions": "x"}, headers=h)
    await cp.post("/v1/seller/catalog/import", json={"document": EXAMPLE}, headers=h)
    await cp.post(f"/v1/agents/{aid}/test", json={}, headers=h)
    r = await cp.post(f"/v1/agents/{aid}/activate", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert "credential" not in r.json()  # raw never leaks to console
    store = stack["cp_app"].state.tenancy
    creds = [c for c in await store.list_credentials(aid) if c["status"] == "active"]
    assert any("a2a:call" in (c["scopes"] if isinstance(c["scopes"], list) else __import__("json").loads(c["scopes"])) for c in creds)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_onboarding_agent_flow.py::test_activate_issues_a2a_call_credential -xvs`
Expected: FAIL — `activate_agent_route` never calls `issue_credential` with `a2a:call`.

- [ ] **Step 3: Write minimal implementation**

In `settings.py` after `clerk_jwt_key`:

```python
buyer_internal_token: str = Field(
    default="dev-buyer-internal", validation_alias="BUYER_INTERNAL_TOKEN"
)
```

In `activate_agent_route`, immediately after `activated = await activate_agent(store, agent_id)`:

```python
existing = [c for c in await store.list_credentials(agent_id) if c["status"] == "active"]
has_call = any(
    "a2a:call" in (c["scopes"] if isinstance(c["scopes"], list) else json.loads(c["scopes"]))
    for c in existing
)
if not has_call:
    await issue_credential(store, identity.tenant_id, agent_id, ["a2a:call"])
```

(`json` and `issue_credential` are already imported in `routes.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_onboarding_agent_flow.py -q`
Expected: PASS (`test_full_onboarding_saga_reaches_active` still green; new credential present).

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/settings.py apps/verifund_control_plane/verifund_control_plane/agents/routes.py tests/integration/test_onboarding_agent_flow.py
git commit -m "feat: issue a2a:call credential at activate; add buyer_internal_token setting"
```

---

### Task 2: Internal token-exchange endpoint `POST /v1/internal/agent-token`

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/agents/routes.py` (add route after `issue()`, ~line 176)
- Test: `tests/integration/test_onboarding_agent_flow.py` (append test)

**Interfaces:**
- Consumes: `request.headers.get("X-Internal-Token")`, `settings.buyer_internal_token`, `store.get_agent(agent_id)`, `store.list_credentials(agent_id)`, `issue_credential(...)`.
- Produces: `POST /v1/internal/agent-token` with body `{"seller_id": str}` → `{"agent_id": str, "token": str, "scopes": ["a2a:call"]}`. `401` wrong internal token; `404` unknown seller; `403` suspended/revoked/no-active-credential.

- [ ] **Step 1: Write the failing test**

```python
async def test_internal_exchange_returns_a2a_call_token(stack):
    cp, h = stack["cp"], stack["headers"]
    r = await cp.post("/v1/agents", json={"display_name": "Acme"}, headers=h)
    aid = r.json()["agent_id"]
    await cp.patch(f"/v1/agents/{aid}/config", json={"instructions": "x"}, headers=h)
    await cp.post("/v1/seller/catalog/import", json={"document": EXAMPLE}, headers=h)
    await cp.post(f"/v1/agents/{aid}/test", json={}, headers=h)
    await cp.post(f"/v1/agents/{aid}/activate", json={}, headers=h)
    # seller_id in profile equals agent suffix
    profile_seller_id = aid.removeprefix("agent_")
    r = await cp.post("/v1/internal/agent-token", json={"seller_id": profile_seller_id},
                      headers={"X-Internal-Token": stack["cp_app"].state.settings.buyer_internal_token})
    assert r.status_code == 200, r.text
    raw = r.json()["token"]
    # exchanged token verifies as a2a:call
    tenancy = stack["cp_app"].state.tenancy
    from verifund_control_plane.agents.credentials import verify_credential
    v = await verify_credential(tenancy, raw, purpose="a2a:call")
    assert v["agent_id"] == aid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_onboarding_agent_flow.py::test_internal_exchange_returns_a2a_call_token -xvs`
Expected: FAIL — `404` (route not defined).

- [ ] **Step 3: Write minimal implementation**

Add after `issue()` route in `agents/routes.py` (schema already uses `BaseModel`):

```python
class InternalTokenBody(BaseModel):
    seller_id: str = Field(min_length=1)


@router.post("/v1/internal/agent-token")
async def internal_agent_token(request: Request, body: InternalTokenBody) -> dict:
    settings = request.app.state.settings
    if request.headers.get("X-Internal-Token") != settings.buyer_internal_token:
        raise VerifundError("unauthorized", "invalid internal token", status_code=401)
    store = request.app.state.tenancy
    agent = await store.get_agent(f"agent_{body.seller_id}")
    if agent is None:
        raise VerifundError("not_found", "agent not found", status_code=404)
    if agent["status"] != "active":
        raise VerifundError("agent_not_active", "agent is not active", status_code=403)
    creds = [c for c in await store.list_credentials(agent["id"]) if c["status"] == "active"]
    has_call = any(
        "a2a:call" in (c["scopes"] if isinstance(c["scopes"], list) else json.loads(c["scopes"]))
        for c in creds
    )
    if not has_call:
        raw = await issue_credential(store, agent["organization_id"], agent["id"], ["a2a:call"])
        return {"agent_id": agent["id"], "token": raw, "scopes": ["a2a:call"]}
    # Re-issue and return the fresh raw (hashed row now has 2 entries; the newest is the one returned)
    raw = await issue_credential(store, agent["organization_id"], agent["id"], ["a2a:call"])
    return {"agent_id": agent["id"], "token": raw, "scopes": ["a2a:call"]}
```

Note: `get_agent` is keyed by `agent_id` (`agent_<seller_id>`); the body field is named `seller_id` per spec but carries the bare profile UUID. Document that mapping in the route docstring comment.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_onboarding_agent_flow.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agents/routes.py tests/integration/test_onboarding_agent_flow.py
git commit -m "feat: add POST /v1/internal/agent-token (buyer internal exchange)"
```

---

### Task 3: Buyer exchanges tokens; evicts on registry-miss / 401

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/registry_client.py` (`RegistryClient.__init__`, `poll_registry()`, `discover()`)
- Modify: `apps/buyer_agent/buyer_agent/settings.py` (add `buyer_internal_token`, keep `seller_tokens` as fallback in this task only)
- Modify: `apps/buyer_agent/buyer_agent/services.py` (wire new ctor args)
- Modify: `apps/buyer_agent/buyer_agent/server.py` (no change — poll already wired)
- Test: `tests/unit/test_registry_client.py`, `tests/integration/test_buyer_discovery.py`

**Interfaces:**
- Consumes: `POST {control_plane_url}/v1/internal/agent-token` with `X-Internal-Token`.
- Produces: `RegistryClient.__init__(..., *, seller_tokens: dict | None = None, control_plane_url: str = "", buyer_internal_token: str = "")`; `self._token_cache: dict[str, str]`; `async def _exchange_token(self, seller_id) -> str | None`. `poll_registry()`/`discover()` resolve tokens via cache→exchange→`seller_tokens` fallback (this task only).

- [ ] **Step 1: Write the failing test**

```python
async def test_poll_registry_exchanges_per_seller_token():
    # registry returns one seller; exchange returns a raw token
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://registry.test/v1/sellers").mock(
            return_value=httpx.Response(200, json={"sellers": [{"seller_id": "seller-a", "card_url": "http://127.0.0.1:9201/.well-known/agent-card.json"}]})
        )
        mock.get("http://127.0.0.1:9201/.well-known/agent-card.json").mock(
            return_value=httpx.Response(200, json=base_card_json())
        )
        mock.post("http://cp.test/v1/internal/agent-token").mock(
            return_value=httpx.Response(200, json={"agent_id": "agent_seller-a", "token": "vf_agent_raw", "scopes": ["a2a:call"]})
        )
        registry = RegistryClient(registry_url="http://registry.test", allowed_card_hosts=("127.0.0.1",), seller_tokens={}, control_plane_url="http://cp.test", buyer_internal_token="dev-buyer-internal", client=httpx.AsyncClient())
        try:
            endpoints = await registry.poll_registry()
            assert endpoints["seller-a"].token == "vf_agent_raw"
            assert registry._token_cache["seller-a"] == "vf_agent_raw"
        finally:
            await registry.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_registry_client.py::test_poll_registry_exchanges_per_seller_token -xvs`
Expected: FAIL — `RegistryClient.__init__` does not accept `control_plane_url`/`buyer_internal_token`.

- [ ] **Step 3: Write minimal implementation**

In `registry_client.py` `__init__`, add params and store:

```python
def __init__(self, *, registry_url: str, allowed_card_hosts: tuple[str, ...], seller_tokens: dict[str, str] | None = None, control_plane_url: str = "", buyer_internal_token: str = "", seller_internal_token: str = "", trace: TraceStore | None = None, client: httpx.AsyncClient | None = None) -> None:
    ...
    self.seller_tokens = seller_tokens or {}
    self.control_plane_url = (control_plane_url or "").rstrip("/")
    self.buyer_internal_token = buyer_internal_token
    self._token_cache: dict[str, str] = dict(self.seller_tokens)
```

Add method after `poll_registry()`:

```python
async def _exchange_token(self, seller_id: str) -> str | None:
    if not self.control_plane_url or not self.buyer_internal_token:
        return self.seller_tokens.get(seller_id)
    try:
        resp = await self.http.post(
            f"{self.control_plane_url}/v1/internal/agent-token",
            json={"seller_id": seller_id},
            headers={"X-Internal-Token": self.buyer_internal_token},
        )
        if resp.status_code in (401, 403, 404):
            return None
        resp.raise_for_status()
        token = resp.json()["token"]
        self._token_cache[seller_id] = token
        return token
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        import logging; logging.getLogger(__name__).warning("token exchange failed for %s: %s", seller_id, exc)
        return self._token_cache.get(seller_id)
```

In `poll_registry()` and `discover()`, replace `token = self.seller_tokens.get(seller_id); if not token: continue/raise` with:

```python
token = self._token_cache.get(seller_id) or await self._exchange_token(seller_id)
if not token:
    continue  # poll: skip; discover: raise ValueError as before
```

After building `new_endpoints` in `poll_registry()`, evict: `self._token_cache = {k: v for k, v in self._token_cache.items() if k in new_endpoints or k in self.seller_tokens}`.

In `settings.py` add `buyer_internal_token: str = "dev-buyer-internal"` (alias `BUYER_INTERNAL_TOKEN`). In `services.py` pass `control_plane_url=settings.verifund_url`, `buyer_internal_token=settings.buyer_internal_token`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_registry_client.py tests/integration/test_buyer_discovery.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/registry_client.py apps/buyer_agent/buyer_agent/settings.py apps/buyer_agent/buyer_agent/services.py tests/unit/test_registry_client.py tests/integration/test_buyer_discovery.py
git commit -m "feat: buyer exchanges per-seller tokens via internal API"
```

---

### Task 4: Delete `seller_tokens` fallback; drop env docs

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/registry_client.py` (remove `seller_tokens` param + fallback), `apps/buyer_agent/buyer_agent/settings.py` (delete field), `apps/buyer_agent/buyer_agent/services.py` (remove passthrough + deprecation log)
- Modify: `.env.example` (remove `BUYER_SELLER_TOKENS` line)
- Test: `tests/unit/test_registry_client.py` (exchange-only), `tests/integration/test_buyer_discovery.py` (inject exchange transport)

**Interfaces:**
- Consumes: Task 3 `RegistryClient.__init__(..., control_plane_url, buyer_internal_token)` signature.
- Produces: `RegistryClient` with no `seller_tokens`; `Settings` with no `seller_tokens`. `BUYER_SELLER_TOKENS` no longer read anywhere.

- [ ] **Step 1: Write the failing test**

```python
def test_settings_has_no_seller_tokens():
    s = Settings(_env_file=None)
    assert not hasattr(s, "seller_tokens")

async def test_poll_registry_without_env_tokens():
    # same respx setup as Task 3 but RegistryClient constructed WITHOUT seller_tokens
    registry = RegistryClient(registry_url="http://registry.test", allowed_card_hosts=("127.0.0.1",), control_plane_url="http://cp.test", buyer_internal_token="dev-buyer-internal", client=httpx.AsyncClient())
    endpoints = await registry.poll_registry()
    assert endpoints["seller-a"].token == "vf_agent_raw"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_registry_client.py::test_settings_has_no_seller_tokens -xvs`
Expected: FAIL — field still exists.

- [ ] **Step 3: Write minimal implementation**

- `registry_client.py`: change `__init__` signature to remove `seller_tokens`; set `self._token_cache: dict[str, str] = {}`; `_exchange_token` no longer falls back to `seller_tokens`; `poll_registry()` eviction becomes exact (`k in new_endpoints`).
- `settings.py`: delete the `seller_tokens` field block.
- `services.py`: drop `seller_tokens=settings.seller_tokens` and the deprecation log block.
- `.env.example`: delete the `BUYER_SELLER_TOKENS=...` line.
- Update `tests/integration/test_buyer_discovery.py` `buyer_services` fixture to pass `control_plane_url="http://cp.test"` + `buyer_internal_token="dev-buyer-internal"` and mock `POST http://cp.test/v1/internal/agent-token` returning distinct raw tokens per seller.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_registry_client.py tests/integration/test_buyer_discovery.py tests/unit/ -q`
Expected: PASS (`tests/unit/` green; integration green with exchange transport).

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/registry_client.py apps/buyer_agent/buyer_agent/settings.py apps/buyer_agent/buyer_agent/services.py .env.example tests/unit/test_registry_client.py tests/integration/test_buyer_discovery.py
git commit -m "feat: delete seller_tokens fallback; buyer auth is exchange-only"
```

---

### Task 5: End-to-end validation + runbook

**Files:**
- Modify: `docs/runbook.md` (dynamic-auth subsection), `tests/integration/test_onboarding_agent_flow.py` (activate→exchange→verify loop assertion)

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: proven activate→exchange→A2A loop; docs updated.

- [ ] **Step 1: Write the failing test**

```python
async def test_activate_exchange_verify_loop(stack):
    cp, h = stack["cp"], stack["headers"]
    r = await cp.post("/v1/agents", json={"display_name": "Acme"}, headers=h)
    aid = r.json()["agent_id"]
    await cp.patch(f"/v1/agents/{aid}/config", json={"instructions": "x"}, headers=h)
    await cp.post("/v1/seller/catalog/import", json={"document": EXAMPLE}, headers=h)
    await cp.post(f"/v1/agents/{aid}/test", json={}, headers=h)
    await cp.post(f"/v1/agents/{aid}/activate", json={}, headers=h)
    ex = await cp.post("/v1/internal/agent-token", json={"seller_id": aid.removeprefix("agent_")},
                       headers={"X-Internal-Token": stack["cp_app"].state.settings.buyer_internal_token})
    assert ex.status_code == 200
    from verifund_control_plane.agents.credentials import verify_credential
    v = await verify_credential(stack["cp_app"].state.tenancy, ex.json()["token"], purpose="a2a:call")
    assert v["agent_id"] == aid
    # suspended agent can no longer exchange
    await stack["cp_app"].state.tenancy.set_agent_status(aid, "suspended")
    ex2 = await cp.post("/v1/internal/agent-token", json={"seller_id": aid.removeprefix("agent_")},
                        headers={"X-Internal-Token": stack["cp_app"].state.settings.buyer_internal_token})
    assert ex2.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_onboarding_agent_flow.py::test_activate_exchange_verify_loop -xvs`
Expected: FAIL before Tasks 1–4 (runs after them, so it should already pass — this step documents the loop).

- [ ] **Step 3: Runbook docs**

Append to `docs/runbook.md`:

```markdown
### Dynamic seller auth (buyer tokens)

After a seller activates, the buyer obtains its `a2a:call` token from `POST /v1/internal/agent-token` (gated by `BUYER_INTERNAL_TOKEN`, per-seller, long-lived until revoke). The buyer polls the registry every 30 s and exchanges on demand — no `BUYER_SELLER_TOKENS` env needed. Suspend/revoke evicts the cached token on the next poll.
```

- [ ] **Step 4: Run validation**

Run: `uv run pytest tests/integration/test_onboarding_agent_flow.py tests/unit/test_registry_client.py tests/integration/test_buyer_discovery.py tests/unit/ -q`
Expected: PASS.

Manual smoke (not automated):
```bash
make reset && make dev   # banner: onboard URL, empty marketplace
# onboard one seller in browser, then within 30s it appears for the buyer
# with no BUYER_SELLER_TOKENS in .env
```

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_onboarding_agent_flow.py docs/runbook.md
git commit -m "test: activate-exchange-verify loop; runbook for dynamic seller auth"
```

---

## Self-Review

1. **Spec coverage:** §3.1 issue-at-activate → Task 1; internal route + lazy fallback → Task 2; buyer cache/exchange/eviction → Task 3; delete env fallback → Task 4; §4 flow + §5 errors + §6 tests → Tasks 3–5; §7 rollout order → Tasks 1→4 order; §8 non-goals (no TTL scheduler, no console change) → no task claims them.
2. **Placeholder scan:** no `TBD`/`TODO`/`appropriate handling`; every code step has a concrete snippet + run command + expected output.
3. **Type consistency:** `seller_id` = bare profile UUID everywhere (`agent_<seller_id>` = `agent_id`); `POST /v1/internal/agent-token` body key is `seller_id` even though it carries the bare UUID (documented in Task 2); `buyer_internal_token` name identical in Settings + internal route check + buyer settings/services.
