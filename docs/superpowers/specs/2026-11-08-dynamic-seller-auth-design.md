# Dynamic Seller Auth — Design Spec (amendment)

**Date:** 2026-11-08
**Status:** Approved design, pending spec review
**Parent spec:** `docs/superpowers/specs/2026-11-08-dynamic-seller-onboarding-design.md`
**Classification:** Architectural (brainstorming path)

> Next.js constraint (per `apps/console/AGENTS.md`): no console code in this amendment — control-plane + buyer only, so the breaking-changes doc read is out of scope here. Implementation plan must still verify the buyer lifespan edit against the current async patterns in `apps/buyer_agent/buyer_agent/server.py` (no Next.js involved).

## 1. Problem

Seller *discovery* is dynamic (buyer `RegistryClient.poll_registry()` every 30s against `GET /v1/sellers`). Seller *auth* is not: `registry_client` resolves the bearer token from a static `seller_tokens` dict sourced from the `BUYER_SELLER_TOKENS` env (`apps/buyer_agent/buyer_agent/settings.py:59`, `scripts/config.py` already deleted `seller_tokens_json()`). `scripts/dev.py` no longer sets `BUYER_SELLER_TOKENS`, so a fresh `make dev` map is empty and `poll_registry()` yields no endpoints. The token must follow the seller lifecycle (activation → publish → exchange → revoke) instead of the env file.

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Token source | Control-plane internal exchange: buyer calls `POST /v1/internal/agent-token` per seller on poll-detected changes |
| Lifetime | Long-lived, revoke-only (no fixed TTL; re-exchange only on revocation or 401) |
| Exchange auth | Reuse `BUYER_INTERNAL_TOKEN` (internal-only route, not console-exposed) |
| Exchange shape | Per-seller on-demand (not bulk) |
| Issuance point | `a2a:call` credential created at `POST /v1/agents/{agent_id}/activate`, alongside existing `a2a:test` |
| Revocation | Buyer evicts cache when seller leaves registry or A2A returns 401 |

## 3. Architecture

### 3.1 Control plane (`apps/verifund_control_plane/`)

**`agents/credentials.py`** — unchanged `issue_credential()` (hash-only storage, `vf_agent_` prefix). Already the pattern used by `/v1/agents/{id}/test` for `a2a:test`.

**`agents/routes.py:activate_agent_route`** — after existing `activate_agent()` precondition checks pass (verified, passing hash-matched test run, active credential), in addition to registry publish, issue one `a2a:call` credential:

```python
# inside activate_agent_route, after activated = await activate_agent(...)
raw = await issue_credential(store, identity.tenant_id, agent_id, ["a2a:call"])
```

The raw value is not returned in the public activate response (console must never see it); it is only retrievable via the internal exchange (3.2). A second activate for the same agent reuses the existing active `a2a:call` row (check `list_credentials` first) to avoid duplicate active credentials.

**New internal route** `POST /v1/internal/agent-token` in `agents/routes.py` (or `internal/routes.py` if that module is preferred by the implementer — one file, one responsibility):

- Auth: `X-Internal-Token` header equals `settings.buyer_internal_token` (already present as `BUYER_INTERNAL_TOKEN` in `control_plane_environment()`). Mismatch → `401`.
- Body: `{"seller_id": str}`.
- Lookup: agent by `agent_id == seller_id` via `store.get_agent`; require `status == "active"` and an active `a2a:call` credential row. If none, lazily `issue_credential(scopes=["a2a:call"])` (covers agents activated before this feature).
- Response: `{"agent_id", "token": <raw>, "scopes": ["a2a:call"]}` — raw token in this response only, never logged, never persisted by the control plane beyond the existing hash row.
- Errors: `403` if agent suspended/revoked or has no active credential; `404` if unknown seller.

### 3.2 Buyer (`apps/buyer_agent/`)

**`registry_client.py`** — replace `self.seller_tokens: dict[str,str]` with `self._token_cache: dict[str, str]`. `poll_registry()` flow becomes:

1. `GET /v1/sellers` → entries.
2. For each entry with valid card: if `seller_id not in _token_cache`, call `_exchange_token(seller_id)` → `POST {control_plane_url}/v1/internal/agent-token` with `X-Internal-Token: buyer_internal_token`. On 403/404 skip seller + log; on 5xx keep previous cache (existing poll-failure behavior).
3. Build `SellerEndpoint` with cached token; atomically swap `self._endpoints` and `self._token_cache` (evict ids absent from the registry response).
4. `discover()` keeps the same token-resolution path (cache-first, exchange-on-miss).

**`settings.py`** — delete `seller_tokens` field; add `control_plane_url` (reuse `verifund_url`, already present) and `buyer_internal_token` (already present as `internal_api_token` / `BUYER_INTERNAL_TOKEN` — verify alias in implementation). Add deprecation log removal (Task 5 warning goes away once the field is gone).

**`services.py` / `server.py`** — wire `buyer_internal_token` into `RegistryClient(...)`; poll lifespan already exists (30s) — no timer change.

### 3.3 Seller-shared — no change

`verify_credential(store, token, purpose="a2a:call")` already requires `agent.status == "active"` and the `a2a:call` scope. The exchanged token validates with no seller-side change.

## 4. Data flow

```text
Seller: … → POST /v1/agents/{id}/activate
  → CP issues a2a:call credential (hash row) + publishes card to registry
Buyer poll (30s): GET /v1/sellers
  → for new seller_id: POST /v1/internal/agent-token (BUYER_INTERNAL_TOKEN)
      → 200 {token} → cache
A2A: Authorization: Bearer <token> → seller-shared → verify_credential(a2a:call) → 200
Suspend/revoke: CP sets agent status + revokes credential + unpublishes
  → next buyer poll omits seller → cache evicted
  → if still cached, A2A returns 401 → buyer evicts + attempts re-exchange → 403 → skip
```

## 5. Error handling

| Failure | Behavior |
|---|---|
| Exchange 403 (suspended/revoked) | Buyer evicts cache entry, logs, continues with remaining sellers. |
| Exchange 404 (unknown seller) | Same as 403. |
| Exchange 5xx / CP down | Poll keeps last `_token_cache` + `_endpoints` (existing failure semantics). |
| No active `a2a:call` row at exchange | Lazily issue one, return it (idempotent — reuse if already active). |
| Buyer has no `BUYER_INTERNAL_TOKEN` | Exchange calls fail with 401 → discovery yields zero endpoints; log at warning. `dev.py` already sets it when Verifund is enabled. |

## 6. Testing

- **Unit:** `verify/exchange` auth failures (wrong internal token → 401; revoked agent → 403); `poll_registry` eviction on missing seller (extend `tests/unit/test_registry_client.py`).
- **Integration:** full loop in `tests/integration/test_onboarding_agent_flow.py` style — activate → extract via internal exchange using the fake/internal token → A2A call with exchanged bearer succeeds; suspend → exchange 403; `test_buyer_discovery.py` updated to inject a fake exchange transport instead of `seller_tokens`.
- **Regression:** existing `lifespan` poll test still passes; `BUYER_SELLER_TOKENS` env no longer consulted (assert `Settings().seller_tokens` attribute gone or ignored).

## 7. Rollout

1. Land internal exchange + lazy-issue fallback (control plane) behind existing `buyer_internal_token` (no flag).
2. Land buyer exchange + cache eviction; keep `seller_tokens` fallback for one release with the existing deprecation log.
3. Delete `seller_tokens` field + fallback; remove `BUYER_SELLER_TOKENS` from `.env.example` / docker-compose docs.
4. `make reset && make dev` → onboard one seller in browser (or `MARKETMESH_DEV_IDENTITY=fake` saga test) → appears in buyer within 30s without any env token.

## 8. Scope / non-goals

Single plan-sized chunk (control plane 1 route + activate tweak; buyer client + settings; tests). No console change. No TTL/rotation scheduler. No change to `a2a:test` semantics. Per-seller scope is one credential per activated agent per buyer (the buyer is a single principal in this prototype).

---

## Self-review

- **Placeholders:** none — endpoint, auth header name, scopes, and error codes are stated literally.
- **Consistency:** issuance-at-activate (locked) is implemented by the same `issue_credential` helper used for `a2a:test`; lazy fallback in §3.1 covers the existing "active credential" gate in `lifecycle.activate_agent` without double-issuing.
- **Scope:** one subsystem (credential exchange) — fits a single implementation plan; deliberately excludes TTL scheduling and console work.
- **Ambiguity resolved:** “dynamic auth” means §3.1–3.3 for every token use in the buyer path; rollout step 2 defines the one-release fallback window.
