# Dynamic Seller Onboarding — Design Spec

**Date:** 2026-11-08
**Status:** Approved design, pending spec review
**Classification:** Architectural (brainstorming path)
**Scope:** Remove static seller seeding from `make dev`; make seller state dynamic via Clerk-authenticated seller workspace onboarding.

> Next.js constraint (per `apps/console/AGENTS.md`): this Next.js version has breaking changes. Console code must be written against `node_modules/next/dist/docs/` for the resolved `next` package, not against pre-change training-data conventions. This spec is implementation-agnostic; the implementation plan must call out the doc read for every Server Component / Server Action / route change.

## 1. Today (static) vs. target (dynamic)

### 1.1 `make dev` boot sequence today

`Makefile:dev` → `uv run python scripts/dev.py` → `run_stack()` in `scripts/dev.py`:

1. Boot infrastructure (unchanged): `registry` (`9105`), `verifund` control plane (`9300`, if `VERIFUND_MODE != off`), `seller-shared` (`9200`), `buyer` (`9100`), `verifund-agent` (`9301`) + one-shot `verifund_agent.register`, `orchestrator` (`9000`), console (`3000`). Each gated by `wait_for_http()` on `/health`.
2. `run_seed(mode)` → `scripts/seed.py:main()`:
   - `seed_control_plane()` → `TenancyRepository` + `seed_demo_agents()` creates buyer + 4 seller orgs/profiles/agents with `verified=True`, `status=active`, static `SELLER_*_TOKEN` → `a2a:test` credentials.
   - `seed_catalogs()` → for each entry in `scripts/config.py:SELLERS` (4 YAMLs in `apps/seller_agent/profiles/`) calls `scripts/seed_shared.py:seed_seller_rows()` → `OrgScopedStore.import_products()` + `seller_configs` row in `data/sellers.db`, card built by `build_agent_card()`.
   - `write_demo_credentials()` → `data/demo-credentials.json` (SHA-256 of tokens → org/agent/scopes).
   - `register_seller()` → `POST /v1/sellers` with `REGISTRY_ADMIN_TOKEN` + `shared_card_url()` (`9200/{seller_id}/.well-known/agent-card.json`) + categories from YAML policy.
3. Env built from `SELLERS`: `allowed_card_urls_json()`, `allowed_card_hosts_json()`, `seller_tokens_json()` → `BUYER_SELLER_TOKENS`, `SELLER_PAYOUT_EMAILS` static map in `scripts/config.py`.

This bypasses the real seller workspace entirely: a seller needs no Clerk account, no verification, no test run, and no catalog import to appear in the marketplace.

### 1.2 Existing dynamic flow (already in repo, not wired to boot)

- Console: `apps/console/app/post-auth/seller-activator.tsx` → Clerk org create/`setActive()` → `/seller/onboarding`.
- Server actions (`apps/console/app/(seller-onboarding)/seller/onboarding/actions.ts`): `auth.protect()` → `controlPlaneForUser()` (`apps/console/lib/control-plane.ts`, forwards Clerk JWT `Authorization: Bearer …` to `VERIFUND_CONTROL_PLANE_URL`) → `/v1/seller/onboarding`, `/v1/seller/verification/submit`, `/v1/agents` (`createAgent`), `PATCH /v1/agents/{id}/config|policies`, `POST /v1/seller/catalog/import`, `POST /v1/agents/{id}/test`, `POST /v1/agents/{id}/activate`.
- Control plane: `onboarding/routes.py` resolves identity via `tenancy/identity.py:resolve_identity()` → `tenant_id` (Clerk org) → `create_onboarding()` creates `seller_profiles` row on demand; `agents/lifecycle.py` blocks activation with `onboarding_incomplete` until passing test run matching `policy_hash`/`card_hash`, verified profile, and active credential exist.
- Registry publish is already returned as `registry_published` from activate (`activateAgentAction`).

The design wires `make dev` to *this* flow and deletes the bypass.

## 2. Goals / Non-goals

**Goals:** (1) Empty registry on fresh `make dev` — a seller appears only after completing workspace onboarding. (2) All seller state (org, profile, agent, catalog, credentials, registry card, payout) derived from the Clerk-authenticated session. (3) Preserve a one-command demo escape hatch.

**Non-goals:** No per-seller processes (already removed in `a05f201`). No change to buyer/orchestrator LLM logic. No production AuthZ redesign beyond the local dev-loop.

## 3. Locked decisions (grilling rounds, all “recommended”)

| Decision | Choice |
|---|---|
| Demo sellers after cutover | Only-source onboarding. Old seed survives as `make seed-demo` (opt-in, never called by default `make dev`). |
| Catalog source of truth | Import-document only (JSON + YAML accepted, row-level errors, atomic save). Bundled YAMLs become `docs/templates/`. |
| `agent_id` | Opaque `agent_<uuid>` generated at `POST /v1/agents`. Display name for UI; slug only for card path if needed. |
| Credentials | Per-agent hashed credential rows in control-plane DB at activation (`a2a:test` vs `a2a:call` scopes). `data/demo-credentials.json` deleted. |
| Registry publish | Synchronous on `POST /v1/agents/{id}/activate`; background reconciler only retries failures. |
| Verification gate in dev | Hard gate (verified + passing hash-matched test run + active credential). `VERIFUND_AUTO_VERIFY=1` is the sole opt-out. |
| Clerk-less dev/CI | `MARKETMESH_DEV_IDENTITY=fake` short-circuits `resolve_identity()` to a deterministic dev org. Never enabled when a real Clerk publishable key is configured; guarded by env + a startup log warning. |
| Onboarding sequence | Strict order enforced server-side: profile → create agent → config → policies → import catalog → test → verification (+ payout email, required) → activate. Later steps 409 until prior step satisfies its precondition. |
| Payout email | Required field in verification form. Replaces `SELLER_PAYOUT_EMAILS` static map entirely. |
| Buyer discovery | Buyer polls `GET /v1/sellers` every 30 s, rebuilds card/token map. `dev.py` env map removed. Startup fetch is a special case of the poll. |
| YAML files | Move `apps/seller_agent/profiles/*.yaml` to `docs/templates/`; delete `profile_path` file lookup from the onboarding path (kept only in `make seed-demo`). |

## 4. Architecture

### 4.1 Boot path (`scripts/dev.py`)

`run_stack()` unchanged except:

- Delete `run_seed(mode)` call and function (replaced by `scripts/seed.py` invoked only via `make seed-demo`).
- `registry_environment()`: `ALLOWED_CARD_URLS` = `[]` or shared-host only; `ALLOWED_CARD_HOSTS` = `{127.0.0.1, localhost, shared host}` — no per-seller entries passed.
- `buyer_environment()`: remove `BUYER_SELLER_TOKENS` (built by `seller_tokens_json()`), add `REGISTRY_URL` polling config (`BUYER_REGISTRY_POLL_SECONDS=30`).
- `control_plane_environment()`: pass through `VERIFUND_AUTO_VERIFY`, `MARKETMESH_DEV_IDENTITY`, and Clerk env passthrough (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` already survive from `.env` via `os.environ.copy()`).
- Print a boot banner: “No sellers seeded — onboard via http://127.0.0.1:3000/seller/onboarding”.

### 4.2 Control plane (`apps/verifund_control_plane/`)

**`tenancy/identity.py`**: add fake-identity branch at the top of `resolve_identity()`:

```python
if os.environ.get("MARKETMESH_DEV_IDENTITY") == "fake":
    return Identity(tenant_id="org_dev_fake", user_id="user_dev_fake", role="business", ...)
```

Guard: only when `CLERK_SECRET_KEY` is unset or explicitly overridden with `MARKETMESH_DEV_IDENTITY=fake`; log a loud warning on startup. The onboarding service then treats `org_dev_fake` as a normal tenant — no other code changes.

**`onboarding/service.py`**: enforce strict sequence. Each mutator checks its precondition:

- `POST /v1/seller/onboarding` → creates profile row (`seller_id = agent_<uuid>` slug placeholder until agent creation, or reuse the same UUID for profile→agent linkage — see §6 open question), `onboarding.status=in_progress, current_step=profile`.
- `POST /v1/seller/onboarding/profile` → requires profile exists; advances to `agent`.
- `POST /v1/agents` (existing) → requires `current_step` ≥ `agent`; creates opaque `agent_id`.
- `PATCH /v1/agents/{id}/config|policies` → requires agent exists; stores `config_version`, `policy_hash`, `card_hash`.
- `POST /v1/seller/catalog/import` → validates document (JSON/YAML), each product validated; on any error returns 422 with row-level errors, saves nothing.
- `POST /v1/agents/{id}/test` → runs checks against current `policy_hash`/`card_hash`; stores `test_run_id`, `passed`.
- `POST /v1/seller/verification/submit` → accepts `{documents, payout_email}`; when `VERIFUND_AUTO_VERIFY=1`, marks `verified=true` immediately, else leaves `pending_review`.
- `POST /v1/agents/{id}/activate` → full precondition check (existing `lifecycle.py`): passing test run whose `policy_hash`/`card_hash` match current config, `verified`, active credential. On success: issue per-agent credential row (hash only), publish card to registry via `REGISTRY_URL` + `REGISTRY_ADMIN_TOKEN` (server-side, not from dev.py), return `{status, registry_published:true}`.

**`tenancy/backfill.py`**: remove seller branch of `seed_demo_agents()` from the default boot path. Keep the function for `make seed-demo` only, called explicitly by the seed script. `seed_payment_accounts()` reads from `seller_profiles.payment_account` (written by verification), not `SELLER_PAYOUT_EMAILS`.

**Payout**: verification payload gains required `payout_email` (PayPal-matched). `upsert_payment_account(provider="paypal", provider_account_id=email, status="active")` at verification approval time.

### 4.3 Seller-shared (`apps/seller_agent/`)

No change to the single process (`seller-shared` on `9200`, `seller_configs` table keyed by `agent_id`). `seed_shared.py:seed_seller_rows()` stays for `make seed-demo` only. Catalog import is handled control-plane-side and written to the same `sellers.db` via the shared store (existing `OrgScopedStore`).

### 4.4 Buyer (`apps/buyer_agent/`)

Replace `BUYER_SELLER_TOKENS` env with a registry poller:

- Startup: `GET {REGISTRY_URL}/v1/sellers` → build `{seller_id: {card_url, categories}}`.
- Loop every 30 s (configurable `BUYER_REGISTRY_POLL_SECONDS`): re-fetch, diff, log changes, atomically swap the map.
- Token resolution per card: control-plane credential lookup by `seller_id` (replacing the baked map). Fail-closed when seller not in registry.

### 4.5 Console (`apps/console/`)

- `/seller/onboarding` wizard renders the strict sequence as a stepper; completed steps show checkmarks, current step is the only editable one. Each action already exists as a Server Action; add server-side precondition surfacing (`onboarding_incomplete` → inline message, as already handled in `activateAgentAction`).
- Import panel: text area for JSON/YAML + example templates linking to `docs/templates/*.yaml` (fetched statically, not from `apps/seller_agent/profiles/`).
- Verification form: add required payout-email input (PayPal sandbox hint).
- `SellerActivator` unchanged (Clerk org bootstrap).

### 4.6 `scripts/seed.py` → `make seed-demo`

- Keep file, add `if __name__ == "__main__"` CLI guard (already present) and a Makefile target `seed-demo: uv run python scripts/seed.py`.
- `run_stack()` no longer calls it; `make dev` prints the onboard URL instead.
- `Makefile` gains `seed-demo` target; `dev` target unchanged command (`uv run python scripts/dev.py`).

### 4.7 Data migration

- Delete `data/demo-credentials.json` generation; existing file ignored after cutover (no reader).
- Existing `data/sellers.db` / `data/verifund.db` rows for the 4 static sellers remain but are orphaned (no profile row links after fresh DB). Fresh `make reset` + `make dev` = empty marketplace until onboarding.
- `ALLOWED_CARD_URLS` / `ALLOWED_CARD_HOSTS` in `.env` should be scrubbed of `9201-9204` remnants (already done in `.env.example`; local `.env` cleanup recommended but not enforced by code).

## 5. Data flow (target)

```text
Clerk User → Clerk Org (orgId) → Console /seller/onboarding
  → Server Action (JWT via controlPlaneForUser)
  → Control Plane resolve_identity(orgId) → tenant org
  → Onboarding state machine (profile → agent → config → import → test → verify → activate)
  → Credential row (hashed) + card publish POST /v1/sellers
       → Registry (GET /v1/sellers)
       → Buyer poll (30s) → A2A calls to seller-shared (9200/{seller_id}/a2a)
```

Static `make dev` no longer appears in this flow except for infra boot and the opt-in `make seed-demo`.

## 6. Open questions (deferred to plan)

1. **Profile → agent linkage:** should `seller_profiles.seller_id` equal the opaque `agent_<uuid>` from `POST /v1/agents`, or remain a separate slug (`seller_<uuid>`)? The card path `9200/{seller_id}/...` needs one consistent key. Recommendation: single UUID for both, display name is free text.
2. **Fake-identity tenancy:** does `org_dev_fake` get reset on `make reset` (wipe `data/`), or persisted across runs for CI determinism? Recommendation: persisted, reset by `make reset` only.
3. **Catalog replace semantics:** `importCatalog(document, replaceCatalog=false)` — default append/update vs. replace. Recommendation: default `replaceCatalog=true` in onboarding (a seller's first import is authoritative), append thereafter.
4. **Buyer token scope:** should buyer hold one `a2a:call` credential spanning all sellers, or per-seller tokens matching the credential store? Recommendation: per-seller, issued at activate alongside the seller's `a2a:test` credential.

## 7. Error handling

| Failure | Behavior |
|---|---|
| Onboarding step out of order | `409 onboarding_incomplete` with `current_step` and the missing precondition name (existing `lifecycle.py` pattern). |
| Catalog validation error | `422 catalog_invalid`, row-level `{row, field, message}` list, nothing written. |
| Worker 409 during wizard | Inline stepper error; state unchanged. |
| Registry publish failure on activate | Activate fails with `registry_publish_failed`; reconciler retries every 60 s until success or agent disabled. |
| Buyer poll failure | Log at warning, keep last known map, retry next tick. |
| Fake identity misused in prod | Startup fails fast if `MARKETMESH_DEV_IDENTITY=fake` and `CLERK_SECRET_KEY` looks production (non-`sk_test_` prefix) — belt-and-braces alongside the log warning. |

## 8. Testing

- **Unit:** `tests/unit/test_verifund_dev_config.py` — `run_stack()` no longer references `SELLERS`; `buyer_environment()` has no `BUYER_SELLER_TOKENS`; `allowed_card_*` helpers need no `SELLERS` import.
- **Integration:** extend `tests/integration/test_seller_onboarding_routes.py` and `test_onboarding_agent_flow.py` — full strict-sequence walkthrough with Clerk JWT (existing fixtures) including the `onboarding_incomplete` gates and the catalog 422 path.
- **Buyer poll:** new unit test for the registry poller (fetch → diff → atomic swap; failure keeps last map).
- **Card publish:** integration test asserting `POST /v1/sellers` is called by activate, not by seed.
- **Seed-demo:** `scripts/seed.py` still passes its existing smoke (run manually, not in CI by default).
- **Console:** `apps/console/tests/app/actions.test.ts` existing Clerk mock covers the new stepper preconditions (add payout-email required case).

## 9. Rollout / compatibility

1. Land control-plane sequence enforcement + fake-identity bypass.
2. Land buyer registry polling; flip env removal behind a `BUYER_SELLER_TOKENS` deprecated warning for one release.
3. Land console stepper + verification payout field.
4. Remove `run_seed()` from `run_stack()`, add `make seed-demo`, move YAMLs to `docs/templates/`, delete `SELLERS` tuple + `SELLER_PAYOUT_EMAILS` helper (+ `seller_tokens_json()`).
5. `make reset && make dev` → empty marketplace; onboard manually or via `MARKETMESH_DEV_IDENTITY=fake` + curl.

## 10. Non-obvious risks

- **Single-process tenant isolation:** `seller-shared` already keys state by `agent_id`; opaque UUIDs reduce collision risk vs. user-chosen slugs.
- **Clerk rate limits:** `SellerActivator` already surfaces the org-limit error; the design does not change that.
- **SEO of Client Components:** Server Actions already `auth.protect()` — strict sequence is enforced server-side, so UI tampering cannot skip steps.
- **`seller_organization_id` vs Clerk `orgId`:** early link table exists (`seller_profiles` keyed by `organization_id`); keep `orgId` opaque, never parse it (e.g. never assume `org_...` prefix semantics beyond equality).

---

## Self-review

- **Placeholders:** none — all sections have concrete file/function references. §6 lists 4 genuinely deferred choices rather than TBDs.
- **Consistency:** §3 decisions match §4 components (seed-demo opt-in, strict sequence, poll 30 s, fake identity). Activation preconditions (§4.2) match `lifecycle.py` as it exists today.
- **Scope:** one plan-size chunk (control plane + buyer poller + console stepper + scripts/Makefile). No orchestrator LLM changes.
- **Ambiguity resolved:** “dynamic” means per §4.1–4.5 for every seller-specific row; §9 step ordering disambiguates rollout vs. final state.
